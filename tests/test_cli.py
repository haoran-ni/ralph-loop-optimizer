from __future__ import annotations

import subprocess
import shlex
import sys
from pathlib import Path

import pytest

from ralph_loop_optimizer.cli import main
from ralph_loop_optimizer.config import OptimizerConfig, load_config, write_config


def test_cli_help_exits_successfully() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0


def test_init_command_creates_brief_and_reviews_without_starting_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _write(harness_path / "evaluate.py", "print('score')\n")
    _commit_all(harness_path)

    exit_code = main(
        [
            "init",
            "--harness",
            str(harness_path),
            "--goal",
            "Improve the score.",
            "--evaluation-command",
            "python evaluate.py",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert (harness_path / "RALPH_LOOP.md").exists()
    assert (harness_path / "ralph-loop.json").exists()
    generated_config = load_config(harness_path / "ralph-loop.json")
    assert generated_config.harness_path == harness_path.resolve()
    assert generated_config.goal == "Improve the score."
    assert generated_config.backend == "fake"
    assert generated_config.evaluation_command == "python evaluate.py"
    assert not (harness_path / "ralph_loop_runs").exists()
    assert "[ralph-loop] Init AI review prompt" in output
    assert "# Ralph Loop Init Brief Review" in output
    assert "[ralph-loop] Calling backend for init AI review: fake" in output
    assert "[ralph-loop] Waiting for init AI review output or events..." in output
    assert "[ralph-loop] Init AI review backend finished: exit code 0" in output
    assert "AI review backend: fake" in output
    assert "AI review succeeded: yes" in output
    assert "Optimization was not started" in output
    assert _git_status_lines(harness_path) == [
        "?? RALPH_LOOP.md",
        "?? ralph-loop.json",
    ]


def test_init_command_accepts_backend_for_starter_config(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _commit_all(harness_path)

    exit_code = main(
        [
            "init",
            "--harness",
            str(harness_path),
            "--goal",
            "Improve the score.",
            "--backend",
            "codex",
            "--skip-ai-review",
        ]
    )

    assert exit_code == 0
    assert load_config(harness_path / "ralph-loop.json").backend == "codex"


def test_init_command_can_skip_ai_review(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _write(harness_path / "evaluate.py", "print('score')\n")
    _commit_all(harness_path)
    exit_code = main(
        [
            "init",
            "--harness",
            str(harness_path),
            "--goal",
            "Improve the score.",
            "--evaluation-command",
            "python evaluate.py",
            "--skip-ai-review",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Skipped AI review during init." in output
    assert "AI review backend" not in output
    assert "Optimization was not started" in output
    assert not (harness_path / "ralph_loop_runs").exists()
    assert _git_status_lines(harness_path) == [
        "?? RALPH_LOOP.md",
        "?? ralph-loop.json",
    ]


def test_review_command_is_not_public() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["review", "--config", "missing.json"])

    assert exc_info.value.code == 2


def test_run_command_completes_configured_loop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _write(
        harness_path / "RALPH_LOOP.md",
        "# Ralph Loop Operating Brief\n\nTry one improvement.\n",
    )
    _commit_all(harness_path)
    config_path = tmp_path / "ralph-loop.json"
    write_config(
        OptimizerConfig(
            harness_path=harness_path,
            goal="Improve the score.",
            evaluation_command=_python_command("print('score=10')"),
        ),
        config_path,
    )

    exit_code = main(["run", "--config", str(config_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[ralph-loop] Starting optimization run" in output
    assert "[ralph-loop] Starting iteration 001 of 1" in output
    assert "[ralph-loop] Prompt for iteration 001" in output
    assert "Improve the score." in output
    assert "[ralph-loop] Calling backend: fake" in output
    assert "[ralph-loop] Evaluating harness:" in output
    assert "[evaluation] score=10" in output
    assert "Run run-" in output
    assert "Iterations completed: 1" in output
    assert "Latest experiment commit:" in output
    assert "Latest artifact commit:" in output
    assert _git_status(harness_path) == ""


def test_run_command_accepts_generated_init_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _commit_all(harness_path)
    main(
        [
            "init",
            "--harness",
            str(harness_path),
            "--goal",
            "Improve the score.",
            "--evaluation-command",
            _python_command("print('score=10')"),
        ]
    )
    capsys.readouterr()
    _commit_all(harness_path)

    exit_code = main(["run", "--config", str(harness_path / "ralph-loop.json")])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Iterations completed: 1" in output
    assert _git_status(harness_path) == ""


def test_backends_command_lists_real_and_test_backends(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["backends"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Real coding backends:" in output
    assert "- claude" in output
    assert "- codex" in output
    assert "Test backend:" in output
    assert "- fake" in output
    assert "opencode" not in output


def test_status_command_reports_harness_without_starting_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _commit_all(harness_path)
    main(
        [
            "init",
            "--harness",
            str(harness_path),
            "--goal",
            "Improve the score.",
            "--evaluation-command",
            _python_command("print('score=10')"),
        ]
    )
    capsys.readouterr()

    exit_code = main(["status", "--harness", str(harness_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"Harness: {harness_path.resolve()}" in output
    assert "Git worktree: dirty" in output
    assert "- ?? RALPH_LOOP.md" in output
    assert "- ?? ralph-loop.json" in output
    assert "RALPH_LOOP.md: present" in output
    assert "ralph-loop.json: present" in output
    assert "Runs discovered: 0" in output
    assert not (harness_path / "ralph_loop_runs").exists()


def test_status_command_reports_selected_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _write(
        harness_path / "RALPH_LOOP.md",
        "# Ralph Loop Operating Brief\n\nTry one improvement.\n",
    )
    _commit_all(harness_path)
    config_path = tmp_path / "ralph-loop.json"
    write_config(
        OptimizerConfig(
            harness_path=harness_path,
            goal="Improve the score.",
            evaluation_command=_python_command("print('score=10')"),
        ),
        config_path,
    )
    main(["run", "--config", str(config_path)])
    capsys.readouterr()
    run_id = next((harness_path / "ralph_loop_runs").iterdir()).name

    exit_code = main(
        ["status", "--harness", str(harness_path), "--run-id", run_id]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Git worktree: clean" in output
    assert f"Run: {run_id}" in output
    assert "Run status: valid" in output
    assert "Completed iterations: 1" in output
    assert "Next iteration: 2" in output
    assert "Maximum iterations: 1" in output


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


def _commit_all(repo_path: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Ralph Test",
            "-c",
            "user.email=ralph-test@example.com",
            "commit",
            "-m",
            "initial",
        ],
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


def _git_status_lines(repo_path: Path) -> list[str]:
    return [line for line in _git_status(repo_path).splitlines() if line]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
