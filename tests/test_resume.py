from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from ralph_loop_optimizer.cli import main
from ralph_loop_optimizer.config import OptimizerConfig
from ralph_loop_optimizer.git import get_status
from ralph_loop_optimizer.orchestrator import initialize_run, run_iteration
from ralph_loop_optimizer.resume import (
    ResumeError,
    discover_runs,
    find_last_complete_iteration,
    load_run_state,
    resume_loop,
    validate_resume_state,
)


def test_discover_runs_lists_existing_run_directories(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    first = initialize_run(_config(harness_path, max_iterations=1))
    second = initialize_run(_config(harness_path, max_iterations=1))

    discovered = discover_runs(harness_path)

    assert [run.run_id for run in discovered] == sorted(
        [first.run_paths.run_id, second.run_paths.run_id]
    )


def test_load_run_state_from_complete_run(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    state = initialize_run(_config(harness_path, max_iterations=2))
    first_record = run_iteration(state)

    resumed_state = load_run_state(state.run_paths)

    assert resumed_state.run_paths == state.run_paths
    assert resumed_state.config.max_iterations == 2
    assert resumed_state.next_iteration_number == 2
    assert len(resumed_state.completed_iterations) == 1
    resumed_record = resumed_state.completed_iterations[0]
    assert resumed_record.iteration_number == 1
    assert resumed_record.succeeded is True
    assert resumed_record.commit_hash == first_record.commit_hash
    assert resumed_record.artifact_commit_hash == first_record.artifact_commit_hash


def test_resume_loop_continues_from_next_iteration_without_overwriting(
    tmp_path: Path,
) -> None:
    harness_path = _prepared_harness(tmp_path)
    state = initialize_run(_config(harness_path, max_iterations=2))
    run_iteration(state)
    first_prompt_path = state.run_paths.iterations_dir / "001" / "prompt.md"
    first_prompt = first_prompt_path.read_text(encoding="utf-8")

    resumed_state = resume_loop(harness_path, state.run_paths.run_id)

    assert [
        record.iteration_number for record in resumed_state.completed_iterations
    ] == [1, 2]
    assert first_prompt_path.read_text(encoding="utf-8") == first_prompt
    second_prompt = (
        state.run_paths.iterations_dir / "002" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "Iteration 001" in second_prompt
    assert "Fake backend recorded the post-evaluation lesson update" in second_prompt
    assert get_status(harness_path).is_dirty is False


def test_resume_loop_uses_configured_artifact_directory(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the score.",
        max_iterations=2,
        evaluation_command=_python_command("print('score=10')"),
        run_artifact_dir=Path("custom_runs"),
    )
    state = initialize_run(config)
    run_iteration(state)

    discovered = discover_runs(harness_path)
    resumed_state = resume_loop(harness_path, state.run_paths.run_id)

    assert state.run_paths.run_dir == (
        harness_path.resolve() / "custom_runs" / state.run_paths.run_id
    )
    assert state.run_paths.run_id in [run.run_id for run in discovered]
    assert resumed_state.run_paths.run_dir == state.run_paths.run_dir
    assert (state.run_paths.iterations_dir / "002" / "lesson.md").is_file()
    assert get_status(harness_path).is_dirty is False


def test_resume_loop_restores_last_completed_iteration_commit(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    state = initialize_run(_config(harness_path, max_iterations=2))
    first_record = run_iteration(state)
    _write(harness_path / "README.md", "# Harness\n\nDifferent clean commit.\n")
    _commit_all(harness_path, "detour")

    resumed_state = resume_loop(harness_path, state.run_paths.run_id)

    assert resumed_state.completed_iterations[-1].iteration_number == 2
    assert _git_log_subjects(harness_path)[:3] == [
        "Add ralph loop iteration 002",
        "Add ralph loop iteration 001",
        "initial",
    ]
    assert "detour" not in _git_log_subjects(harness_path)
    assert first_record.commit_hash in subprocess.run(
        ["git", "rev-list", "HEAD"],
        cwd=harness_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


def test_validate_resume_state_refuses_partial_iteration(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    state = initialize_run(_config(harness_path, max_iterations=2))
    run_iteration(state)
    partial_iteration_dir = state.run_paths.iterations_dir / "002"
    partial_iteration_dir.mkdir()
    _write(partial_iteration_dir / "prompt.md", "partial prompt\n")

    assert find_last_complete_iteration(state.run_paths) == 1
    with pytest.raises(ResumeError, match="incomplete iteration 002"):
        validate_resume_state(state.run_paths)
    with pytest.raises(ResumeError, match="incomplete iteration 002"):
        load_run_state(state.run_paths)


def test_validate_resume_state_refuses_missing_result_fields(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    state = initialize_run(_config(harness_path, max_iterations=2))
    run_iteration(state)
    result_path = state.run_paths.iterations_dir / "001" / "result.md"
    result_path.write_text(
        result_path.read_text(encoding="utf-8").replace("- Backend: `fake`\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ResumeError, match="missing or invalid 'Backend'"):
        find_last_complete_iteration(state.run_paths)
    with pytest.raises(ResumeError, match="missing or invalid 'Backend'"):
        validate_resume_state(state.run_paths)


def test_validate_resume_state_refuses_malformed_result_fields(
    tmp_path: Path,
) -> None:
    harness_path = _prepared_harness(tmp_path)
    state = initialize_run(_config(harness_path, max_iterations=2))
    run_iteration(state)
    result_path = state.run_paths.iterations_dir / "001" / "result.md"
    result_path.write_text(
        result_path.read_text(encoding="utf-8").replace(
            "- Evaluation exit code: 0",
            "- Evaluation exit code: nope",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ResumeError,
        match="missing or invalid 'Evaluation exit code'",
    ):
        find_last_complete_iteration(state.run_paths)
    with pytest.raises(
        ResumeError,
        match="missing or invalid 'Evaluation exit code'",
    ):
        validate_resume_state(state.run_paths)


def test_validate_resume_state_refuses_missing_config(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    state = initialize_run(_config(harness_path, max_iterations=2))
    run_iteration(state)
    state.run_paths.config_path.unlink()

    with pytest.raises(ResumeError, match="run config does not exist"):
        validate_resume_state(state.run_paths)


def test_resume_command_continues_existing_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness_path = _prepared_harness(tmp_path)
    state = initialize_run(_config(harness_path, max_iterations=2))
    run_iteration(state)

    exit_code = main(
        [
            "resume",
            "--harness",
            str(harness_path),
            "--run-id",
            state.run_paths.run_id,
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"Run {state.run_paths.run_id} resumed." in output
    assert "Iterations completed: 2" in output
    assert "Latest experiment commit:" in output
    assert "Latest artifact commit:" in output
    assert (state.run_paths.iterations_dir / "002" / "lesson.md").is_file()
    assert get_status(harness_path).is_dirty is False


def _config(harness_path: Path, *, max_iterations: int) -> OptimizerConfig:
    return OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the score.",
        max_iterations=max_iterations,
        evaluation_command=_python_command("print('score=10')"),
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


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _git_log_subjects(repo_path: Path) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]
