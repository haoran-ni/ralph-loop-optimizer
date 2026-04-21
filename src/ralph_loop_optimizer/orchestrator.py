"""Core optimization loop orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from ralph_loop_optimizer.artifacts import (
    IterationPaths,
    RunPaths,
    create_iteration_paths,
    create_run_paths,
    write_text_artifact,
)
from ralph_loop_optimizer.backends import BackendRequest, BackendResult, get_backend
from ralph_loop_optimizer.backends.base import run_backend
from ralph_loop_optimizer.config import OptimizerConfig, validate_config, write_config
from ralph_loop_optimizer.context import (
    IterationContext,
    build_iteration_prompt,
    load_latest_evaluation,
    load_operating_brief,
    load_prior_lessons,
)
from ralph_loop_optimizer.evaluation import (
    EvaluationRequest,
    EvaluationResult,
    format_evaluation_result,
    run_evaluation,
)
from ralph_loop_optimizer.git import commit, get_diff, get_status, stage_paths
from ralph_loop_optimizer.harness import get_worktree_status, read_harness_instructions
from ralph_loop_optimizer.lessons import LessonEvidence, distill_lesson


class OrchestratorError(ValueError):
    """Raised when an optimization run cannot be orchestrated safely."""


@dataclass(frozen=True)
class IterationRecord:
    iteration_number: int
    prompt_path: Path
    evaluation_path: Path
    result_path: Path
    lesson_path: Path
    diff_path: Path
    backend_result: BackendResult
    evaluation_result: EvaluationResult
    commit_hash: str

    @property
    def succeeded(self) -> bool:
        return self.backend_result.succeeded and self.evaluation_result.succeeded


@dataclass(frozen=True)
class RunState:
    config: OptimizerConfig
    run_paths: RunPaths
    completed_iterations: tuple[IterationRecord, ...] = ()

    @property
    def next_iteration_number(self) -> int:
        return len(self.completed_iterations) + 1


def initialize_run(config: OptimizerConfig) -> RunState:
    validate_config(config)
    repo_path = config.harness_path.expanduser().resolve()
    _assert_starting_worktree_safe(repo_path)
    load_operating_brief(repo_path)

    run_paths = create_run_paths(
        repo_path,
        _new_run_id(repo_path, config.run_artifact_dir),
        config.run_artifact_dir,
    )
    return RunState(config=replace(config, harness_path=repo_path), run_paths=run_paths)


def run_iteration(state: RunState) -> IterationRecord:
    iteration_number = state.next_iteration_number
    context = _load_iteration_context(state)
    prompt = build_iteration_prompt(state.config, context)

    backend = get_backend(state.config.backend)
    backend_result = run_backend(
        backend,
        BackendRequest(
            harness_path=state.run_paths.repo_path,
            prompt=prompt,
            operating_brief=context.operating_brief,
            harness_instructions=context.harness_instructions,
            prior_lessons=context.prior_lessons,
            latest_evaluation=context.latest_evaluation,
            timeout_seconds=state.config.command_timeout_seconds,
        ),
    )
    evaluation_result = run_evaluation(
        EvaluationRequest(
            harness_path=state.run_paths.repo_path,
            evaluation_command=state.config.evaluation_command,
            timeout_seconds=state.config.command_timeout_seconds,
        )
    )
    evaluation_text = format_evaluation_result(evaluation_result)
    captured_diff = get_diff(state.run_paths.repo_path)

    iteration_paths = create_iteration_paths(state.run_paths, iteration_number)
    _write_iteration_artifacts(
        state,
        iteration_paths,
        prompt,
        evaluation_text,
        captured_diff,
        backend_result,
        evaluation_result,
    )

    stage_paths(state.run_paths.repo_path, [Path(".")])
    commit_hash = commit(
        state.run_paths.repo_path,
        f"ralph-loop iteration {iteration_number:03d}",
    )

    return IterationRecord(
        iteration_number=iteration_number,
        prompt_path=iteration_paths.prompt_path,
        evaluation_path=iteration_paths.evaluation_path,
        result_path=iteration_paths.result_path,
        lesson_path=iteration_paths.lesson_path,
        diff_path=iteration_paths.diff_path,
        backend_result=backend_result,
        evaluation_result=evaluation_result,
        commit_hash=commit_hash,
    )


def run_loop(config: OptimizerConfig) -> RunState:
    state = initialize_run(config)
    while should_continue(state):
        record = run_iteration(state)
        state = replace(
            state,
            completed_iterations=(*state.completed_iterations, record),
        )
    return state


def should_continue(state: RunState) -> bool:
    return (
        len(state.completed_iterations) < state.config.max_iterations
        and not check_stopping_condition(state)
    )


def check_stopping_condition(state: RunState) -> bool:
    return False


def _load_iteration_context(state: RunState) -> IterationContext:
    return IterationContext(
        operating_brief=load_operating_brief(state.run_paths.repo_path),
        harness_instructions=read_harness_instructions(state.run_paths.repo_path),
        prior_lessons=tuple(load_prior_lessons(state.run_paths)),
        latest_evaluation=load_latest_evaluation(state.run_paths),
        worktree_status=get_worktree_status(state.run_paths.repo_path),
    )


def _write_iteration_artifacts(
    state: RunState,
    iteration_paths: IterationPaths,
    prompt: str,
    evaluation_text: str,
    captured_diff: str,
    backend_result: BackendResult,
    evaluation_result: EvaluationResult,
) -> None:
    if not state.run_paths.config_path.exists():
        write_config(state.config, state.run_paths.config_path)

    write_text_artifact(
        iteration_paths.prompt_path,
        prompt,
        repo_path=state.run_paths.repo_path,
    )
    write_text_artifact(
        iteration_paths.evaluation_path,
        evaluation_text,
        repo_path=state.run_paths.repo_path,
    )
    write_text_artifact(
        iteration_paths.diff_path,
        captured_diff,
        repo_path=state.run_paths.repo_path,
    )
    write_text_artifact(
        iteration_paths.result_path,
        _format_iteration_result(
            iteration_paths.iteration_number,
            backend_result,
            evaluation_result,
        ),
        repo_path=state.run_paths.repo_path,
    )
    write_text_artifact(
        iteration_paths.lesson_path,
        distill_lesson(
            LessonEvidence(
                iteration_number=iteration_paths.iteration_number,
                backend_name=backend_result.backend_name,
                backend_succeeded=backend_result.succeeded,
                backend_exit_code=backend_result.exit_code,
                evaluation_succeeded=evaluation_result.succeeded,
                evaluation_exit_code=evaluation_result.exit_code,
                evaluation_timed_out=evaluation_result.timed_out,
                manual_evaluation_required=evaluation_result.manual_required,
                evaluation_path=_relative_path(
                    iteration_paths.evaluation_path,
                    state.run_paths.repo_path,
                ),
                diff_path=_relative_path(
                    iteration_paths.diff_path,
                    state.run_paths.repo_path,
                ),
                result_path=_relative_path(
                    iteration_paths.result_path,
                    state.run_paths.repo_path,
                ),
            )
        ),
        repo_path=state.run_paths.repo_path,
    )


def _format_iteration_result(
    iteration_number: int,
    backend_result: BackendResult,
    evaluation_result: EvaluationResult,
) -> str:
    return "\n".join(
        [
            f"# Iteration {iteration_number:03d} Result",
            "",
            "## Summary",
            "",
            f"- Backend: `{backend_result.backend_name}`",
            f"- Backend exit code: {backend_result.exit_code}",
            f"- Backend succeeded: {'yes' if backend_result.succeeded else 'no'}",
            f"- Evaluation succeeded: {'yes' if evaluation_result.succeeded else 'no'}",
            f"- Evaluation exit code: {_format_optional_exit_code(evaluation_result.exit_code)}",
            f"- Evaluation timed out: {'yes' if evaluation_result.timed_out else 'no'}",
            "- Manual evaluation required: "
            f"{'yes' if evaluation_result.manual_required else 'no'}",
            "- Commit hash: pending until commit completes",
            "",
            "## Backend Stdout",
            "",
            *_format_text_block(backend_result.stdout),
            "",
            "## Backend Stderr",
            "",
            *_format_text_block(backend_result.stderr),
            "",
        ]
    )


def _assert_starting_worktree_safe(repo_path: Path) -> None:
    status = get_status(repo_path)
    unsafe_entries = tuple(
        entry for entry in status.entries if not _is_allowed_starting_entry(entry)
    )
    if not unsafe_entries:
        return

    entries = "\n".join(f"- {entry}" for entry in unsafe_entries)
    raise OrchestratorError(
        "harness worktree has uncommitted changes outside RALPH_LOOP.md; "
        f"commit or stash them before starting optimization:\n{entries}"
    )


def _is_allowed_starting_entry(entry: str) -> bool:
    return _status_entry_path(entry) == "RALPH_LOOP.md"


def _status_entry_path(entry: str) -> str:
    path = entry[3:] if len(entry) > 3 else entry
    if " -> " in path:
        return path.split(" -> ", 1)[1]
    return path


def _new_run_id(repo_path: Path, artifact_dir: Path) -> str:
    for _ in range(100):
        candidate = f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
        if not (repo_path / artifact_dir / candidate).exists():
            return candidate
    raise OrchestratorError("could not allocate a unique run id")


def _format_optional_exit_code(exit_code: int | None) -> str:
    if exit_code is None:
        return "not available"
    return str(exit_code)


def _format_text_block(content: str) -> list[str]:
    if not content:
        return ["(empty)"]
    return ["```text", content.rstrip(), "```"]


def _relative_path(path: Path, repo_path: Path) -> Path:
    try:
        return path.resolve().relative_to(repo_path.resolve())
    except ValueError:
        return path
