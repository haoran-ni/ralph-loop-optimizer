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
from ralph_loop_optimizer.config import (
    OptimizerConfig,
    validate_config,
    write_config,
)
from ralph_loop_optimizer.context import (
    IterationContext,
    build_iteration_prompt,
    build_lesson_update_prompt,
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
from ralph_loop_optimizer.git import (
    commit,
    current_head,
    get_diff_since,
    get_status,
    stage_paths,
)
from ralph_loop_optimizer.harness import get_worktree_status, read_harness_instructions
from ralph_loop_optimizer.lessons import LessonEvidence, distill_lesson
from ralph_loop_optimizer.progress import ProgressReporter, relative_path


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
    artifact_commit_hash: str
    lesson_backend_result: BackendResult | None = None

    @property
    def succeeded(self) -> bool:
        return (
            self.backend_result.succeeded
            and self.evaluation_result.succeeded
            and (
                self.lesson_backend_result is None
                or self.lesson_backend_result.succeeded
            )
        )


@dataclass(frozen=True)
class RunState:
    config: OptimizerConfig
    run_paths: RunPaths
    completed_iterations: tuple[IterationRecord, ...] = ()

    @property
    def next_iteration_number(self) -> int:
        return len(self.completed_iterations) + 1


def initialize_run(
    config: OptimizerConfig,
    *,
    progress: ProgressReporter | None = None,
) -> RunState:
    validate_config(config)
    repo_path = config.harness_path.expanduser().resolve()
    if progress is not None:
        progress.status(f"Preparing harness: {repo_path}")
    _assert_starting_worktree_safe(repo_path)
    load_operating_brief(repo_path)

    run_paths = create_run_paths(
        repo_path,
        _new_run_id(repo_path, config.run_artifact_dir),
        config.run_artifact_dir,
    )
    if progress is not None:
        progress.status(f"Run id: {run_paths.run_id}")
        progress.status(
            "Run artifacts: "
            f"{relative_path(run_paths.run_dir, run_paths.repo_path)}"
        )
    return RunState(config=replace(config, harness_path=repo_path), run_paths=run_paths)


def run_iteration(
    state: RunState,
    *,
    progress: ProgressReporter | None = None,
) -> IterationRecord:
    iteration_number = state.next_iteration_number
    if progress is not None:
        progress.status(
            f"Starting iteration {iteration_number:03d} "
            f"of {state.config.max_iterations}"
        )
    context = _load_iteration_context(state)
    prompt = build_iteration_prompt(state.config, context)
    implementation_base_ref = current_head(state.run_paths.repo_path)
    if progress is not None:
        progress.block(f"Prompt for iteration {iteration_number:03d}", prompt)

    backend = get_backend(state.config.backend)
    if progress is not None:
        progress.status(f"Calling backend: {backend.name}")
        progress.status("Waiting for backend output or events...")
    backend_result = run_backend(
        backend,
        BackendRequest(
            harness_path=state.run_paths.repo_path,
            prompt=prompt,
            phase="implementation",
            operating_brief=context.operating_brief,
            harness_instructions=context.harness_instructions,
            prior_lessons=context.prior_lessons,
            latest_evaluation=context.latest_evaluation,
            timeout_seconds=state.config.command_timeout_seconds,
            stream_output=progress is not None,
            stdout_callback=(
                progress.backend_stdout_callback(backend.name)
                if progress is not None
                else None
            ),
            stderr_callback=(
                progress.backend_stderr_callback(backend.name)
                if progress is not None
                else None
            ),
        ),
    )
    if progress is not None:
        progress.status(
            f"Backend finished: exit code {backend_result.exit_code}, "
            f"elapsed {_format_elapsed(backend_result.elapsed_seconds)}"
        )
    _assert_backend_did_not_commit(
        state.run_paths.repo_path,
        implementation_base_ref,
        "implementation",
    )

    if progress is not None:
        if state.config.evaluation_command is None:
            progress.status("No evaluation command configured; recording manual mode")
        else:
            progress.status(
                f"Evaluating harness: {state.config.evaluation_command.strip()}"
            )
    evaluation_result = run_evaluation(
        EvaluationRequest(
            harness_path=state.run_paths.repo_path,
            evaluation_command=state.config.evaluation_command,
            timeout_seconds=state.config.command_timeout_seconds,
            stdout_callback=(
                progress.evaluation_stdout_callback()
                if progress is not None
                else None
            ),
            stderr_callback=(
                progress.evaluation_stderr_callback()
                if progress is not None
                else None
            ),
        )
    )
    if progress is not None:
        progress.status(
            "Evaluation finished: "
            f"{'succeeded' if evaluation_result.succeeded else 'not successful'}, "
            f"elapsed {evaluation_result.elapsed_seconds:.3f}s"
        )
    evaluation_text = format_evaluation_result(evaluation_result)

    if progress is not None:
        progress.status("Capturing implementation diff")
    captured_diff = get_diff_since(state.run_paths.repo_path, implementation_base_ref)

    iteration_paths = create_iteration_paths(state.run_paths, iteration_number)
    if progress is not None:
        progress.status(
            "Writing iteration artifacts: "
            f"{relative_path(iteration_paths.iteration_dir, state.run_paths.repo_path)}"
        )
    lesson_seed = distill_lesson(
        LessonEvidence(
            iteration_number=iteration_paths.iteration_number,
            backend_name=backend_result.backend_name,
            backend_succeeded=backend_result.succeeded,
            backend_exit_code=backend_result.exit_code,
            evaluation_succeeded=evaluation_result.succeeded,
            evaluation_exit_code=evaluation_result.exit_code,
            evaluation_timed_out=evaluation_result.timed_out,
            manual_evaluation_required=evaluation_result.manual_required,
            commit_hash=None,
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
    )
    lesson_prompt = build_lesson_update_prompt(
        state.config,
        context,
        iteration_paths,
        evaluation_text,
        captured_diff,
    )
    _write_iteration_artifacts(
        state,
        iteration_paths,
        prompt,
        lesson_prompt,
        evaluation_text,
        captured_diff,
        lesson_seed,
        backend_result,
        evaluation_result,
    )

    lesson_commit_base_ref = current_head(state.run_paths.repo_path)
    if progress is not None:
        progress.block(
            f"Lesson update prompt for iteration {iteration_number:03d}",
            lesson_prompt,
        )
        progress.status(f"Calling backend for lesson update: {backend.name}")
        progress.status("Waiting for lesson update commit...")
    lesson_backend_result = run_backend(
        backend,
        BackendRequest(
            harness_path=state.run_paths.repo_path,
            prompt=lesson_prompt,
            phase="lesson_update",
            operating_brief=context.operating_brief,
            harness_instructions=context.harness_instructions,
            prior_lessons=context.prior_lessons,
            latest_evaluation=evaluation_text,
            timeout_seconds=state.config.command_timeout_seconds,
            stream_output=progress is not None,
            stdout_callback=(
                progress.backend_stdout_callback(backend.name)
                if progress is not None
                else None
            ),
            stderr_callback=(
                progress.backend_stderr_callback(backend.name)
                if progress is not None
                else None
            ),
        ),
    )
    if progress is not None:
        progress.status(
            f"Lesson update backend finished: exit code "
            f"{lesson_backend_result.exit_code}, elapsed "
            f"{_format_elapsed(lesson_backend_result.elapsed_seconds)}"
        )

    final_commit_hash = _finalize_iteration_commit(
        state.run_paths.repo_path,
        lesson_commit_base_ref,
        lesson_backend_result,
        iteration_number,
        evaluation_result,
    )
    if progress is not None:
        progress.status(f"Final iteration commit: {final_commit_hash}")
        progress.status(f"Completed iteration {iteration_number:03d}")

    return IterationRecord(
        iteration_number=iteration_number,
        prompt_path=iteration_paths.prompt_path,
        evaluation_path=iteration_paths.evaluation_path,
        result_path=iteration_paths.result_path,
        lesson_path=iteration_paths.lesson_path,
        diff_path=iteration_paths.diff_path,
        backend_result=backend_result,
        evaluation_result=evaluation_result,
        commit_hash=final_commit_hash,
        artifact_commit_hash=final_commit_hash,
        lesson_backend_result=lesson_backend_result,
    )


def run_loop(
    config: OptimizerConfig,
    *,
    progress: ProgressReporter | None = None,
) -> RunState:
    if progress is not None:
        progress.status("Starting optimization run")
    state = initialize_run(config, progress=progress)
    while should_continue(state):
        record = run_iteration(state, progress=progress)
        state = replace(
            state,
            completed_iterations=(*state.completed_iterations, record),
        )
    if progress is not None:
        progress.status("Optimization run completed")
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
    lesson_prompt: str,
    evaluation_text: str,
    captured_diff: str,
    lesson_text: str,
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
        iteration_paths.lesson_prompt_path,
        lesson_prompt,
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
        lesson_text,
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
            "- Final commit hash: recorded by Git after Ralph Loop Optimizer "
            "stages and commits the completed iteration.",
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


def _finalize_iteration_commit(
    repo_path: Path,
    base_ref: str,
    lesson_backend_result: BackendResult,
    iteration_number: int,
    evaluation_result: EvaluationResult,
) -> str:
    if not lesson_backend_result.succeeded:
        raise OrchestratorError(
            "lesson update backend did not complete successfully; "
            f"exit code {lesson_backend_result.exit_code}"
        )

    _assert_backend_did_not_commit(repo_path, base_ref, "lesson update")
    stage_paths(repo_path, [Path(".")])
    return commit(
        repo_path,
        _build_iteration_commit_message(iteration_number, evaluation_result),
    )


def _assert_starting_worktree_safe(repo_path: Path) -> None:
    status = get_status(repo_path)
    if not status.is_dirty:
        return

    entries = "\n".join(f"- {entry}" for entry in status.entries)
    raise OrchestratorError(
        "harness worktree has uncommitted changes; commit or stash them "
        f"before starting optimization:\n{entries}"
    )


def _assert_backend_did_not_commit(
    repo_path: Path,
    base_ref: str,
    phase: str,
) -> None:
    final_commit_hash = current_head(repo_path)
    if final_commit_hash != base_ref:
        raise OrchestratorError(
            f"{phase} backend must not create Git commits; "
            f"expected HEAD {base_ref}, found {final_commit_hash}"
        )


def _build_iteration_commit_message(
    iteration_number: int,
    evaluation_result: EvaluationResult,
) -> str:
    summary = _summarize_evaluation_for_commit(evaluation_result)
    return "\n".join(
        [
            f"Add ralph loop iteration {iteration_number:03d}",
            "",
            "Evaluation summary:",
            summary,
        ]
    )


def _summarize_evaluation_for_commit(evaluation_result: EvaluationResult) -> str:
    if evaluation_result.manual_required:
        return "Manual evaluation required."
    if evaluation_result.succeeded:
        return evaluation_result.stdout.strip() or "Evaluation succeeded."
    if evaluation_result.timed_out:
        timeout_text = _first_nonempty_text(
            evaluation_result.stderr,
            evaluation_result.stdout,
        )
        if timeout_text:
            return timeout_text
        return (
            "Evaluation timed out after "
            f"{evaluation_result.elapsed_seconds:.3f} seconds."
        )

    failure_text = _first_nonempty_text(
        evaluation_result.stderr,
        evaluation_result.stdout,
    )
    if failure_text:
        return failure_text

    if evaluation_result.exit_code is not None:
        return f"Evaluation failed with exit code {evaluation_result.exit_code}."
    return "Evaluation failed."


def _first_nonempty_text(*values: str) -> str | None:
    for value in values:
        stripped = value.strip()
        if stripped:
            return stripped
    return None


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


def _format_elapsed(elapsed_seconds: float | None) -> str:
    if elapsed_seconds is None:
        return "not available"
    return f"{elapsed_seconds:.3f}s"


def _format_text_block(content: str) -> list[str]:
    if not content:
        return ["(empty)"]
    return ["```text", content.rstrip(), "```"]


def _relative_path(path: Path, repo_path: Path) -> Path:
    try:
        return path.resolve().relative_to(repo_path.resolve())
    except ValueError:
        return path
