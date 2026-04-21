from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ralph_loop_optimizer.cli import main


def test_cli_help_exits_successfully() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0


def test_init_command_creates_brief_without_starting_run(
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
    assert not (harness_path / "ralph_loop_runs").exists()
    assert "Optimization was not started" in output
    assert _git_status(harness_path) == "?? RALPH_LOOP.md\n"


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
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


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
