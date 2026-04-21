from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from ralph_loop_optimizer.backends import BackendRequest, BackendResult
from ralph_loop_optimizer.config import OptimizerConfig
from ralph_loop_optimizer.git import current_head, get_status
from ralph_loop_optimizer.orchestrator import (
    OrchestratorError,
    initialize_run,
    run_loop,
)


def test_run_loop_completes_one_fake_iteration(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the score.",
        evaluation_command=_python_command("print('score=10')"),
    )

    state = run_loop(config)

    assert len(state.completed_iterations) == 1
    record = state.completed_iterations[0]
    assert record.iteration_number == 1
    assert record.succeeded is True
    assert record.commit_hash == current_head(harness_path)
    assert get_status(harness_path).is_dirty is False

    iteration_dir = state.run_paths.iterations_dir / "001"
    assert state.run_paths.config_path.is_file()
    assert (iteration_dir / "prompt.md").is_file()
    assert "score=10" in (iteration_dir / "evaluation.txt").read_text(
        encoding="utf-8"
    )
    assert "RALPH_LOOP.md" in (iteration_dir / "diff.patch").read_text(
        encoding="utf-8"
    )
    assert "Backend succeeded: yes" in (iteration_dir / "result.md").read_text(
        encoding="utf-8"
    )
    assert "candidate improvement" in (iteration_dir / "lesson.md").read_text(
        encoding="utf-8"
    )

    committed_files = _latest_commit_files(harness_path)
    assert "RALPH_LOOP.md" in committed_files
    assert f"{state.run_paths.run_dir.relative_to(harness_path).as_posix()}/config.json" in (
        committed_files
    )
    assert (
        f"{iteration_dir.relative_to(harness_path).as_posix()}/lesson.md"
        in committed_files
    )


def test_run_loop_stops_at_max_iterations_and_uses_prior_lessons(
    tmp_path: Path,
) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the score.",
        max_iterations=2,
        evaluation_command=_python_command("print('score=10')"),
    )

    state = run_loop(config)

    assert [record.iteration_number for record in state.completed_iterations] == [1, 2]
    assert (state.run_paths.iterations_dir / "002" / "lesson.md").is_file()
    second_prompt = (
        state.run_paths.iterations_dir / "002" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "Iteration 001" in second_prompt
    assert "candidate improvement" in second_prompt
    assert get_status(harness_path).is_dirty is False


def test_run_loop_records_failing_evaluation(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the score.",
        evaluation_command=_python_command("import sys; print('bad'); sys.exit(5)"),
    )

    state = run_loop(config)

    record = state.completed_iterations[0]
    assert record.succeeded is False
    assert record.evaluation_result.exit_code == 5
    iteration_dir = state.run_paths.iterations_dir / "001"
    assert "- Exit code: 5" in (iteration_dir / "evaluation.txt").read_text(
        encoding="utf-8"
    )
    assert "The evaluation failed" in (iteration_dir / "lesson.md").read_text(
        encoding="utf-8"
    )
    assert get_status(harness_path).is_dirty is False


def test_run_loop_records_failed_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the score.",
        evaluation_command=_python_command("print('score=10')"),
    )
    monkeypatch.setattr(
        "ralph_loop_optimizer.orchestrator.get_backend",
        lambda name: FailingBackend(),
    )

    state = run_loop(config)

    record = state.completed_iterations[0]
    assert record.backend_result.succeeded is False
    assert record.evaluation_result.succeeded is True
    lesson = (state.run_paths.iterations_dir / "001" / "lesson.md").read_text(
        encoding="utf-8"
    )
    assert "backend attempt did not complete successfully" in lesson
    assert get_status(harness_path).is_dirty is False


def test_initialize_run_refuses_unrelated_dirty_worktree(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    _write(harness_path / "scratch.txt", "uncommitted\n")

    with pytest.raises(OrchestratorError, match="outside RALPH_LOOP.md"):
        initialize_run(
            OptimizerConfig(
                harness_path=harness_path,
                goal="Improve the score.",
                evaluation_command=_python_command("print('score=10')"),
            )
        )

    assert not (harness_path / "ralph_loop_runs").exists()


class FailingBackend:
    name = "fake"

    def run_backend(self, request: BackendRequest) -> BackendResult:
        return BackendResult(
            backend_name=self.name,
            exit_code=9,
            stdout="attempt started\n",
            stderr="backend failed\n",
        )


def _prepared_harness(tmp_path: Path) -> Path:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _commit_all(harness_path, "initial")
    _write(
        harness_path / "RALPH_LOOP.md",
        "# Ralph Loop Operating Brief\n\nTry one improvement.\n",
    )
    return harness_path


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Ralph Test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "ralph-test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path


def _commit_all(repo_path: Path, message: str) -> None:
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def _latest_commit_files(repo_path: Path) -> set[str]:
    result = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line for line in result.stdout.splitlines() if line}


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
