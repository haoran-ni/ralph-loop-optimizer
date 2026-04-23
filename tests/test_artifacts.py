from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ralph_loop_optimizer.artifacts import (
    ArtifactError,
    create_iteration_paths,
    create_run_paths,
    copy_artifact,
    write_json_artifact,
    write_text_artifact,
)


def test_create_run_paths_creates_expected_layout(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    run_paths = create_run_paths(harness_path, "run-001")

    assert run_paths.repo_path == harness_path.resolve()
    assert run_paths.run_id == "run-001"
    assert run_paths.run_dir == harness_path / "ralph_loop_runs" / "run-001"
    assert run_paths.config_path == run_paths.run_dir / "config.json"
    assert run_paths.iterations_dir == run_paths.run_dir / "iterations"
    assert run_paths.iterations_dir.is_dir()


def test_create_iteration_paths_uses_zero_padded_directory(
    tmp_path: Path,
) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")

    iteration_paths = create_iteration_paths(run_paths, 1)

    assert iteration_paths.iteration_number == 1
    assert iteration_paths.iteration_dir == run_paths.iterations_dir / "001"
    assert iteration_paths.prompt_path == iteration_paths.iteration_dir / "prompt.md"
    assert iteration_paths.lesson_prompt_path == (
        iteration_paths.iteration_dir / "lesson_prompt.md"
    )
    assert iteration_paths.evaluation_path == (
        iteration_paths.iteration_dir / "evaluation.txt"
    )
    assert iteration_paths.result_path == iteration_paths.iteration_dir / "result.md"
    assert iteration_paths.lesson_path == iteration_paths.iteration_dir / "lesson.md"
    assert iteration_paths.diff_path == iteration_paths.iteration_dir / "diff.patch"
    assert iteration_paths.iteration_dir.is_dir()


def test_write_text_and_json_artifacts(tmp_path: Path) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")
    iteration_paths = create_iteration_paths(run_paths, 1)

    write_text_artifact(
        iteration_paths.prompt_path,
        "Try one improvement.\n",
        repo_path=run_paths.repo_path,
    )
    write_json_artifact(
        run_paths.config_path,
        {"backend": "fake", "max": 1},
        repo_path=run_paths.repo_path,
    )

    assert iteration_paths.prompt_path.read_text(encoding="utf-8") == (
        "Try one improvement.\n"
    )
    assert json.loads(run_paths.config_path.read_text(encoding="utf-8")) == {
        "backend": "fake",
        "max": 1,
    }


def test_copy_artifact_copies_file_into_run_layout(tmp_path: Path) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")
    iteration_paths = create_iteration_paths(run_paths, 1)
    source = tmp_path / "evaluation-output.txt"
    source.write_text("score=10\n", encoding="utf-8")

    copy_artifact(
        source,
        iteration_paths.evaluation_path,
        repo_path=run_paths.repo_path,
    )

    assert iteration_paths.evaluation_path.read_text(encoding="utf-8") == "score=10\n"


def test_artifact_writes_reject_paths_outside_harness_repository(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    other_repo_path = _git_repo(tmp_path / "other")
    outside_path = other_repo_path / "artifact.txt"

    with pytest.raises(ArtifactError, match="inside the harness"):
        write_text_artifact(outside_path, "outside\n", repo_path=harness_path)

    assert not outside_path.exists()


def test_artifact_writes_reject_paths_that_escape_repository(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    run_paths = create_run_paths(harness_path, "run-001")
    escaping_path = run_paths.run_dir / ".." / ".." / ".." / "outside.txt"

    with pytest.raises(ArtifactError, match="inside the harness"):
        write_text_artifact(escaping_path, "outside\n", repo_path=harness_path)

    assert not (tmp_path / "outside.txt").exists()


def test_relative_artifact_paths_are_resolved_inside_harness(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    write_text_artifact(
        Path("ralph_loop_runs/run-001/config.json"),
        "config\n",
        repo_path=harness_path,
    )

    assert (
        harness_path / "ralph_loop_runs" / "run-001" / "config.json"
    ).read_text(encoding="utf-8") == "config\n"


def test_create_run_paths_rejects_escaping_run_id(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    with pytest.raises(ArtifactError, match="single directory name"):
        create_run_paths(harness_path, "../outside")


def test_create_iteration_paths_rejects_invalid_iteration_number(
    tmp_path: Path,
) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")

    with pytest.raises(ArtifactError, match="at least 1"):
        create_iteration_paths(run_paths, 0)


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    return path
