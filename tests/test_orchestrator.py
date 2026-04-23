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
    assert record.artifact_commit_hash == current_head(harness_path)
    assert record.commit_hash == record.artifact_commit_hash
    assert get_status(harness_path).is_dirty is False

    iteration_dir = state.run_paths.iterations_dir / "001"
    assert state.run_paths.config_path.is_file()
    assert (iteration_dir / "prompt.md").is_file()
    assert (iteration_dir / "lesson_prompt.md").is_file()
    assert "score=10" in (iteration_dir / "evaluation.txt").read_text(
        encoding="utf-8"
    )
    assert (iteration_dir / "diff.patch").read_text(encoding="utf-8") == ""
    assert "Backend succeeded: yes" in (iteration_dir / "result.md").read_text(
        encoding="utf-8"
    )
    result = (iteration_dir / "result.md").read_text(encoding="utf-8")
    lesson = (iteration_dir / "lesson.md").read_text(encoding="utf-8")
    lesson_prompt = (iteration_dir / "lesson_prompt.md").read_text(encoding="utf-8")
    assert "Final commit hash: recorded by Git" in result
    assert "Do not commit changes yourself." in lesson_prompt
    assert "not recorded" not in lesson
    assert "Fake backend recorded the post-evaluation lesson update" in lesson
    assert "Evaluation succeeded" in lesson
    assert _latest_subject(harness_path) == "Add ralph loop iteration 001"
    assert "score=10" in _latest_body(harness_path)

    committed_files = _commit_files(harness_path, record.commit_hash)
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
    assert "Fake backend recorded the post-evaluation lesson update" in second_prompt
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
    assert "Evaluation did not succeed" in (iteration_dir / "lesson.md").read_text(
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
    assert "implementation backend did not complete cleanly" in lesson
    assert get_status(harness_path).is_dirty is False


def test_run_loop_refuses_lesson_update_backend_commit(
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
        lambda name: CommittingLessonBackend(),
    )

    with pytest.raises(OrchestratorError, match="must not create Git commits"):
        run_loop(config)


def test_initialize_run_refuses_dirty_worktree(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    _write(harness_path / "scratch.txt", "uncommitted\n")

    with pytest.raises(OrchestratorError, match="uncommitted changes"):
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
        if request.phase == "lesson_update":
            return BackendResult(
                backend_name=self.name,
                exit_code=0,
                stdout="lesson updated\n",
                stderr="",
            )

        return BackendResult(
            backend_name=self.name,
            exit_code=9,
            stdout="attempt started\n",
            stderr="backend failed\n",
        )


class CommittingLessonBackend:
    name = "fake"

    def run_backend(self, request: BackendRequest) -> BackendResult:
        if request.phase == "lesson_update":
            subprocess.run(["git", "add", "."], cwd=request.harness_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "unexpected backend commit"],
                cwd=request.harness_path,
                check=True,
                capture_output=True,
            )
        return BackendResult(
            backend_name=self.name,
            exit_code=0,
            stdout=f"{request.phase} done\n",
            stderr="",
        )


def _prepared_harness(tmp_path: Path) -> Path:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _write(
        harness_path / "RALPH_LOOP.md",
        "# Ralph Loop Operating Brief\n\nTry one improvement.\n",
    )
    _commit_all(harness_path, "initial")
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


def _commit_files(repo_path: Path, commit_hash: str) -> set[str]:
    result = subprocess.run(
        ["git", "show", "--name-only", "--format=", commit_hash],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line for line in result.stdout.splitlines() if line}


def _latest_subject(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _latest_body(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%b"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
