from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from ralph_loop_optimizer.cli import main
from ralph_loop_optimizer.config import load_config


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
TOY_EXAMPLE_DIR = EXAMPLES_DIR / "toy-benchmark"


def test_init_then_single_iteration_with_fake_backend(
    tmp_path: Path,
    capsys,
) -> None:
    harness_path = tmp_path / "toy-benchmark-harness"
    shutil.copytree(TOY_EXAMPLE_DIR, harness_path)
    _git_repo(harness_path)
    _commit_all(harness_path, "initial toy harness")

    init_exit_code = main(
        [
            "init",
            "--harness",
            str(harness_path),
            "--goal",
            "Improve the deterministic toy benchmark score.",
            "--evaluation-command",
            _python_file_command("evaluate.py"),
            "--backend",
            "fake",
        ]
    )

    init_output = capsys.readouterr().out
    assert init_exit_code == 0
    assert "Optimization was not started" in init_output
    assert (harness_path / "RALPH_LOOP.md").is_file()
    assert (harness_path / "ralph-loop.json").is_file()
    assert not (harness_path / "ralph_loop_runs").exists()

    config = load_config(harness_path / "ralph-loop.json")
    assert config.backend == "fake"
    assert config.max_iterations == 1
    assert config.evaluation_command == _python_file_command("evaluate.py")

    run_exit_code = main(["run", "--config", str(harness_path / "ralph-loop.json")])

    run_output = capsys.readouterr().out
    assert run_exit_code == 0
    assert "Run run-" in run_output
    assert "Iterations completed: 1" in run_output
    assert "Latest experiment commit:" in run_output
    assert "Latest artifact commit:" in run_output
    assert _git_status(harness_path) == ""

    run_dirs = sorted((harness_path / "ralph_loop_runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    iteration_dir = run_dir / "iterations" / "001"
    assert (run_dir / "config.json").is_file()

    prompt = (iteration_dir / "prompt.md").read_text(encoding="utf-8")
    evaluation = (iteration_dir / "evaluation.txt").read_text(encoding="utf-8")
    result = (iteration_dir / "result.md").read_text(encoding="utf-8")
    lesson = (iteration_dir / "lesson.md").read_text(encoding="utf-8")
    diff = (iteration_dir / "diff.patch").read_text(encoding="utf-8")

    assert "Improve the deterministic toy benchmark score." in prompt
    assert (iteration_dir / "lesson_prompt.md").is_file()
    assert "toy-benchmark" in evaluation
    assert "- Succeeded: yes" in evaluation
    assert '"benchmark": "toy-benchmark"' in evaluation
    assert "- Backend: `fake`" in result
    assert "- Evaluation succeeded: yes" in result
    assert "Fake backend recorded the post-evaluation lesson update" in lesson
    assert "RALPH_LOOP.md" in diff
    assert "ralph-loop.json" in diff

    subjects = _git_log_subjects(harness_path)
    assert subjects[:2] == [
        "ralph-loop iteration 001",
        "initial toy harness",
    ]


def _git_repo(path: Path) -> None:
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


def _commit_all(repo_path: Path, message: str) -> None:
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def _git_status(repo_path: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _git_log_subjects(repo_path: Path) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _python_file_command(path: str) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(path)}"
