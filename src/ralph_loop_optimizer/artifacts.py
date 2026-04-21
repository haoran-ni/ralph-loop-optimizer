"""Run artifact path creation and safe artifact writes."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from ralph_loop_optimizer.harness import assert_git_repository


DEFAULT_RUN_ARTIFACT_DIR = Path("ralph_loop_runs")


class ArtifactError(ValueError):
    """Raised when artifact paths or writes are invalid."""


@dataclass(frozen=True)
class RunPaths:
    repo_path: Path
    run_id: str
    run_dir: Path
    config_path: Path
    iterations_dir: Path


@dataclass(frozen=True)
class IterationPaths:
    iteration_number: int
    iteration_dir: Path
    prompt_path: Path
    evaluation_path: Path
    result_path: Path
    lesson_path: Path
    diff_path: Path


def create_run_paths(repo_path: Path, run_id: str) -> RunPaths:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)
    _validate_run_id(run_id)

    artifact_dir = repo_path / DEFAULT_RUN_ARTIFACT_DIR
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _assert_path_inside_repo(artifact_dir, repo_path)

    run_dir = artifact_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _assert_path_inside_repo(run_dir, repo_path)

    iterations_dir = run_dir / "iterations"
    iterations_dir.mkdir(parents=True, exist_ok=True)
    _assert_path_inside_repo(iterations_dir, repo_path)

    return RunPaths(
        repo_path=repo_path,
        run_id=run_id,
        run_dir=run_dir,
        config_path=run_dir / "config.json",
        iterations_dir=iterations_dir,
    )


def create_iteration_paths(
    run_paths: RunPaths,
    iteration_number: int,
) -> IterationPaths:
    if isinstance(iteration_number, bool) or not isinstance(iteration_number, int):
        raise ArtifactError("iteration_number must be an integer")
    if iteration_number < 1:
        raise ArtifactError("iteration_number must be at least 1")

    iteration_dir = run_paths.iterations_dir / f"{iteration_number:03d}"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    _assert_path_inside_repo(iteration_dir, run_paths.repo_path)

    return IterationPaths(
        iteration_number=iteration_number,
        iteration_dir=iteration_dir,
        prompt_path=iteration_dir / "prompt.md",
        evaluation_path=iteration_dir / "evaluation.txt",
        result_path=iteration_dir / "result.md",
        lesson_path=iteration_dir / "lesson.md",
        diff_path=iteration_dir / "diff.patch",
    )


def write_text_artifact(path: Path, content: str, *, repo_path: Path) -> None:
    destination = _prepare_destination(path, repo_path)
    destination.write_text(content, encoding="utf-8")


def write_json_artifact(path: Path, data: object, *, repo_path: Path) -> None:
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    write_text_artifact(path, content, repo_path=repo_path)


def copy_artifact(source: Path, destination: Path, *, repo_path: Path) -> None:
    source = source.expanduser()
    if not source.is_file():
        raise ArtifactError(f"artifact source must be a file: {source}")

    safe_destination = _prepare_destination(destination, repo_path)
    shutil.copyfile(source, safe_destination)


def _validate_run_id(run_id: str) -> None:
    if not run_id.strip():
        raise ArtifactError("run_id must not be empty")
    run_id_path = Path(run_id)
    if run_id_path.is_absolute() or run_id_path.name != run_id:
        raise ArtifactError("run_id must be a single directory name")
    if run_id in {".", ".."}:
        raise ArtifactError("run_id must be a single directory name")


def _prepare_destination(path: Path, repo_path: Path) -> Path:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)
    destination = _absolute_path(path.expanduser(), repo_path)
    resolved_destination = destination.resolve(strict=False)
    _assert_path_inside_repo(resolved_destination, repo_path)
    resolved_destination.parent.mkdir(parents=True, exist_ok=True)
    return resolved_destination


def _absolute_path(path: Path, repo_path: Path) -> Path:
    if path.is_absolute():
        return path
    return repo_path / path


def _assert_path_inside_repo(path: Path, repo_path: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(repo_path.resolve())
    except ValueError as exc:
        raise ArtifactError(
            f"artifact path must stay inside the harness repository: {path}"
        ) from exc
