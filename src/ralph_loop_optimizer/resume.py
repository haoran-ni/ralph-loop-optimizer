"""Resume helpers for interrupted optimization runs."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from ralph_loop_optimizer.artifacts import (
    DEFAULT_RUN_ARTIFACT_DIR,
    IterationPaths,
    RunPaths,
)
from ralph_loop_optimizer.backends import BackendResult
from ralph_loop_optimizer.config import (
    ConfigError,
    OptimizerConfig,
    default_config_path,
    load_config,
)
from ralph_loop_optimizer.evaluation import EvaluationResult
from ralph_loop_optimizer.git import current_head, get_status, reset_hard
from ralph_loop_optimizer.harness import assert_git_repository
from ralph_loop_optimizer.orchestrator import (
    IterationRecord,
    RunState,
    run_iteration,
    should_continue,
)


class ResumeError(ValueError):
    """Raised when an existing run cannot be resumed safely."""


def discover_runs(repo_path: Path) -> list[RunPaths]:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)

    return [
        _run_paths_from_dir(repo_path, run_dir)
        for run_dir in sorted(
            _candidate_run_dirs(repo_path),
            key=lambda path: path.name,
        )
    ]


def load_run_state(run_paths: RunPaths) -> RunState:
    validate_resume_state(run_paths)
    config = _load_resume_config(run_paths)
    completed_iterations = tuple(
        _load_iteration_record(run_paths, iteration_number, config)
        for iteration_number in range(1, find_last_complete_iteration(run_paths) + 1)
    )
    return RunState(
        config=config,
        run_paths=run_paths,
        completed_iterations=completed_iterations,
    )


def find_last_complete_iteration(run_paths: RunPaths) -> int:
    last_complete = 0
    expected_number = 1
    for iteration_dir in _iteration_dirs(run_paths):
        iteration_number = int(iteration_dir.name)
        if iteration_number != expected_number:
            break
        if not _is_complete_iteration(iteration_dir):
            break
        last_complete = iteration_number
        expected_number += 1
    return last_complete


def validate_resume_state(run_paths: RunPaths) -> None:
    if not run_paths.run_dir.is_dir():
        raise ResumeError(f"run directory does not exist: {run_paths.run_dir}")
    if not run_paths.config_path.is_file():
        raise ResumeError(f"run config does not exist: {run_paths.config_path}")
    if not run_paths.iterations_dir.is_dir():
        raise ResumeError(
            f"iterations directory does not exist: {run_paths.iterations_dir}"
        )

    _load_resume_config(run_paths)

    expected_number = 1
    for iteration_dir in _iteration_dirs(run_paths):
        iteration_number = int(iteration_dir.name)
        if iteration_number != expected_number:
            raise ResumeError(
                "iteration directories must be consecutive; "
                f"expected {expected_number:03d}, found {iteration_dir.name}"
            )
        _validate_complete_iteration(iteration_dir)
        expected_number += 1


def resume_loop(repo_path: Path, run_id: str) -> RunState:
    run_paths = _run_paths_for_id(repo_path, run_id)
    state = load_run_state(run_paths)
    _assert_clean_resume_worktree(state.run_paths.repo_path)
    _restore_last_completed_iteration_commit(state)

    while should_continue(state):
        record = run_iteration(state)
        state = replace(
            state,
            completed_iterations=(*state.completed_iterations, record),
        )
    return state


def _run_paths_for_id(repo_path: Path, run_id: str) -> RunPaths:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)
    if not run_id.strip() or Path(run_id).name != run_id:
        raise ResumeError("run_id must be a single directory name")

    matching_runs = [
        run_dir
        for run_dir in _candidate_run_dirs(repo_path)
        if run_dir.name == run_id
    ]
    if not matching_runs:
        raise ResumeError(f"run does not exist: {run_id}")
    if len(matching_runs) > 1:
        locations = ", ".join(path.as_posix() for path in matching_runs)
        raise ResumeError(
            f"run id is ambiguous across artifact directories: {locations}"
        )

    return _run_paths_from_dir(repo_path, matching_runs[0])


def _run_paths_from_dir(repo_path: Path, run_dir: Path) -> RunPaths:
    return RunPaths(
        repo_path=repo_path,
        run_id=run_dir.name,
        run_dir=run_dir,
        config_path=run_dir / "config.json",
        iterations_dir=run_dir / "iterations",
    )


def _load_resume_config(run_paths: RunPaths) -> OptimizerConfig:
    config = load_config(run_paths.config_path)
    repo_path = run_paths.repo_path.expanduser().resolve()
    if config.harness_path.expanduser().resolve() != repo_path:
        raise ResumeError(
            "run config harness_path does not match the harness being resumed"
        )

    configured_run_dir = (
        repo_path / config.run_artifact_dir / run_paths.run_id
    ).resolve()
    if configured_run_dir != run_paths.run_dir.resolve():
        raise ResumeError(
            "run directory does not match configured run_artifact_dir: "
            f"expected {configured_run_dir}, found {run_paths.run_dir}"
        )

    return replace(config, harness_path=repo_path)


@dataclass(frozen=True)
class _ParsedIterationResult:
    backend_name: str
    backend_exit_code: int
    backend_succeeded: bool
    evaluation_succeeded: bool
    evaluation_exit_code: int | None
    evaluation_timed_out: bool
    manual_evaluation_required: bool
    experiment_commit_hash: str | None


def _load_iteration_record(
    run_paths: RunPaths,
    iteration_number: int,
    config: OptimizerConfig,
) -> IterationRecord:
    iteration_paths = _iteration_paths(run_paths, iteration_number)
    result_text = iteration_paths.result_path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    parsed_result = _parse_iteration_result(
        iteration_paths.iteration_dir,
        result_text,
    )
    backend_result = BackendResult(
        backend_name=parsed_result.backend_name,
        exit_code=parsed_result.backend_exit_code,
    )
    evaluation_result = EvaluationResult(
        evaluation_command=config.evaluation_command,
        exit_code=parsed_result.evaluation_exit_code,
        timed_out=parsed_result.evaluation_timed_out,
        manual_required=parsed_result.manual_evaluation_required,
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
        commit_hash=(
            parsed_result.experiment_commit_hash
            or _latest_commit_touching(
                run_paths.repo_path,
                iteration_paths.iteration_dir,
            )
        ),
        artifact_commit_hash=_latest_commit_touching(
            run_paths.repo_path,
            iteration_paths.iteration_dir,
        ),
    )


def _iteration_paths(run_paths: RunPaths, iteration_number: int) -> IterationPaths:
    iteration_dir = run_paths.iterations_dir / f"{iteration_number:03d}"
    return IterationPaths(
        iteration_number=iteration_number,
        iteration_dir=iteration_dir,
        prompt_path=iteration_dir / "prompt.md",
        lesson_prompt_path=iteration_dir / "lesson_prompt.md",
        evaluation_path=iteration_dir / "evaluation.txt",
        result_path=iteration_dir / "result.md",
        lesson_path=iteration_dir / "lesson.md",
        diff_path=iteration_dir / "diff.patch",
    )


def _candidate_run_dirs(repo_path: Path) -> list[Path]:
    candidates: dict[Path, Path] = {}
    for artifact_dir in _candidate_artifact_dirs(repo_path):
        if not artifact_dir.exists():
            continue
        if not artifact_dir.is_dir():
            raise ResumeError(
                f"artifact directory must be a directory: {artifact_dir}"
            )
        for run_dir in artifact_dir.iterdir():
            if run_dir.is_dir():
                candidates[run_dir.resolve()] = run_dir

    for config_path in _run_config_paths(repo_path):
        run_dir = config_path.parent
        candidates[run_dir.resolve()] = run_dir

    return list(candidates.values())


def _candidate_artifact_dirs(repo_path: Path) -> list[Path]:
    artifact_dirs = [repo_path / DEFAULT_RUN_ARTIFACT_DIR]
    root_config_path = default_config_path(repo_path)
    if root_config_path.is_file():
        try:
            root_config = load_config(root_config_path)
        except ConfigError:
            root_config = None
        if root_config is not None:
            artifact_dirs.append(repo_path / root_config.run_artifact_dir)
    return _unique_paths(artifact_dirs)


def _run_config_paths(repo_path: Path) -> list[Path]:
    paths: list[Path] = []
    for config_path in repo_path.rglob("config.json"):
        relative_parts = config_path.relative_to(repo_path).parts
        if ".git" in relative_parts:
            continue
        if (config_path.parent / "iterations").is_dir():
            paths.append(config_path)
    return paths


def _iteration_dirs(run_paths: RunPaths) -> list[Path]:
    if not run_paths.iterations_dir.exists():
        return []

    dirs = [path for path in run_paths.iterations_dir.iterdir() if path.is_dir()]
    invalid = [path.name for path in dirs if not _is_iteration_dir_name(path.name)]
    if invalid:
        joined = ", ".join(sorted(invalid))
        raise ResumeError(
            f"iteration directories must be zero-padded numbers: {joined}"
        )
    return sorted(dirs, key=lambda path: int(path.name))


def _is_iteration_dir_name(name: str) -> bool:
    return len(name) == 3 and name.isdecimal() and int(name) > 0


def _is_complete_iteration(iteration_dir: Path) -> bool:
    if _missing_iteration_files(iteration_dir):
        return False

    result_text = (iteration_dir / "result.md").read_text(
        encoding="utf-8",
        errors="replace",
    )
    _parse_iteration_result(iteration_dir, result_text)
    return True


def _validate_complete_iteration(iteration_dir: Path) -> None:
    missing = _missing_iteration_files(iteration_dir)
    if missing:
        joined = ", ".join(missing)
        raise ResumeError(
            f"incomplete iteration {iteration_dir.name}; missing {joined}"
        )

    result_text = (iteration_dir / "result.md").read_text(
        encoding="utf-8",
        errors="replace",
    )
    _parse_iteration_result(iteration_dir, result_text)


def _missing_iteration_files(iteration_dir: Path) -> list[str]:
    required = [
        "prompt.md",
        "evaluation.txt",
        "result.md",
        "lesson.md",
        "diff.patch",
    ]
    return [name for name in required if not (iteration_dir / name).is_file()]


def _assert_clean_resume_worktree(repo_path: Path) -> None:
    status = get_status(repo_path)
    if not status.is_dirty:
        return

    entries = "\n".join(f"- {entry}" for entry in status.entries)
    raise ResumeError(
        "harness worktree has uncommitted changes; commit or stash them "
        f"before resuming optimization:\n{entries}"
    )


def _restore_last_completed_iteration_commit(state: RunState) -> None:
    if not state.completed_iterations:
        return

    target_commit = state.completed_iterations[-1].commit_hash
    if current_head(state.run_paths.repo_path) == target_commit:
        return
    reset_hard(state.run_paths.repo_path, target_commit)


def _parse_iteration_result(
    iteration_dir: Path,
    text: str,
) -> _ParsedIterationResult:
    backend_name = _require_backtick_field(iteration_dir, text, "Backend")
    backend_exit_code = _require_int_field(iteration_dir, text, "Backend exit code")
    backend_succeeded = _require_yes_no_field(
        iteration_dir,
        text,
        "Backend succeeded",
    )
    evaluation_succeeded = _require_yes_no_field(
        iteration_dir,
        text,
        "Evaluation succeeded",
    )
    evaluation_exit_code = _require_optional_exit_code(iteration_dir, text)
    evaluation_timed_out = _require_yes_no_field(
        iteration_dir,
        text,
        "Evaluation timed out",
    )
    manual_evaluation_required = _require_yes_no_field(
        iteration_dir,
        text,
        "Manual evaluation required",
    )
    experiment_commit_hash = _optional_backtick_field(
        text,
        "Experiment commit hash",
    )

    if backend_succeeded != (backend_exit_code == 0):
        raise ResumeError(
            f"malformed result for iteration {iteration_dir.name}: "
            "backend success does not match backend exit code"
        )

    expected_evaluation_succeeded = (
        not manual_evaluation_required
        and not evaluation_timed_out
        and evaluation_exit_code == 0
    )
    if evaluation_succeeded != expected_evaluation_succeeded:
        raise ResumeError(
            f"malformed result for iteration {iteration_dir.name}: "
            "evaluation success does not match evaluation status fields"
        )

    return _ParsedIterationResult(
        backend_name=backend_name,
        backend_exit_code=backend_exit_code,
        backend_succeeded=backend_succeeded,
        evaluation_succeeded=evaluation_succeeded,
        evaluation_exit_code=evaluation_exit_code,
        evaluation_timed_out=evaluation_timed_out,
        manual_evaluation_required=manual_evaluation_required,
        experiment_commit_hash=experiment_commit_hash,
    )


def _require_backtick_field(iteration_dir: Path, text: str, field_name: str) -> str:
    match = re.search(
        rf"^- {re.escape(field_name)}: `([^`]+)`$",
        text,
        re.MULTILINE,
    )
    if match is None:
        raise _malformed_result_error(iteration_dir, field_name)
    return match.group(1)


def _optional_backtick_field(text: str, field_name: str) -> str | None:
    match = re.search(
        rf"^- {re.escape(field_name)}: `([^`]+)`$",
        text,
        re.MULTILINE,
    )
    if match is None:
        return None
    return match.group(1)


def _require_int_field(iteration_dir: Path, text: str, field_name: str) -> int:
    match = re.search(
        rf"^- {re.escape(field_name)}: (-?\d+)$",
        text,
        re.MULTILINE,
    )
    if match is None:
        raise _malformed_result_error(iteration_dir, field_name)
    return int(match.group(1))


def _require_optional_exit_code(iteration_dir: Path, text: str) -> int | None:
    match = re.search(r"^- Evaluation exit code: (.+)$", text, re.MULTILINE)
    if match is None:
        raise _malformed_result_error(iteration_dir, "Evaluation exit code")
    if match.group(1) == "not available":
        return None
    if not re.fullmatch(r"-?\d+", match.group(1)):
        raise _malformed_result_error(iteration_dir, "Evaluation exit code")
    return int(match.group(1))


def _require_yes_no_field(iteration_dir: Path, text: str, field_name: str) -> bool:
    match = re.search(
        rf"^- {re.escape(field_name)}: (yes|no)$",
        text,
        re.MULTILINE,
    )
    if match is None:
        raise _malformed_result_error(iteration_dir, field_name)
    return match.group(1) == "yes"


def _malformed_result_error(iteration_dir: Path, field_name: str) -> ResumeError:
    return ResumeError(
        f"malformed result for iteration {iteration_dir.name}; "
        f"missing or invalid {field_name!r}"
    )


def _latest_commit_touching(repo_path: Path, path: Path) -> str:
    relative_path = _relative_path(path, repo_path).as_posix()
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", relative_path],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    commit_hash = result.stdout.strip()
    if result.returncode != 0 or not commit_hash:
        return "not recorded"
    return commit_hash


def _relative_path(path: Path, repo_path: Path) -> Path:
    try:
        return path.resolve().relative_to(repo_path.resolve())
    except ValueError:
        return path


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: dict[Path, Path] = {}
    for path in paths:
        unique[path.resolve(strict=False)] = path
    return list(unique.values())
