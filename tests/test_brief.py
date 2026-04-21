from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ralph_loop_optimizer.brief import (
    BriefError,
    brief_exists,
    build_operating_brief,
    write_operating_brief,
)
from ralph_loop_optimizer.config import OptimizerConfig
from ralph_loop_optimizer.harness import inspect_harness


def test_build_operating_brief_includes_goal_and_harness_findings(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _write(harness_path / "pyproject.toml", "[project]\nname = 'harness'\n")
    _write(harness_path / "evaluate.py", "print('score')\n")
    _write(harness_path / "tests" / "test_score.py", "def test_score(): pass\n")
    _write(harness_path / "AGENTS.md", "Use the harness rules.\n")

    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the score without changing the evaluator.",
        evaluation_command="python evaluate.py",
    )
    summary = inspect_harness(harness_path)

    brief = build_operating_brief(config, summary)

    assert "# Ralph Loop Operating Brief" in brief
    assert "Improve the score without changing the evaluator." in brief
    assert "`python evaluate.py`" in brief
    assert "`README.md`" in brief
    assert "`pyproject.toml`" in brief
    assert "`evaluate.py`" in brief
    assert "`tests/test_score.py`" in brief
    assert "`AGENTS.md`" in brief
    assert "Optimization must not start until the user explicitly approves" in brief


def test_build_operating_brief_records_missing_evaluation_command(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the workflow.",
    )
    summary = inspect_harness(harness_path)

    brief = build_operating_brief(config, summary)

    assert "- Configured evaluation command: not provided" in brief


def test_write_operating_brief_preserves_existing_file_by_default(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    brief_path = write_operating_brief(harness_path, "first\n")

    assert brief_path == harness_path.resolve() / "RALPH_LOOP.md"
    assert brief_exists(harness_path) is True
    with pytest.raises(BriefError, match="already exists"):
        write_operating_brief(harness_path, "second\n")
    assert brief_path.read_text(encoding="utf-8") == "first\n"


def test_write_operating_brief_can_overwrite_when_explicit(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    brief_path = write_operating_brief(harness_path, "first\n")
    write_operating_brief(harness_path, "second", overwrite=True)

    assert brief_path.read_text(encoding="utf-8") == "second\n"


def test_write_operating_brief_refuses_symlinked_brief(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    outside_path = tmp_path / "outside.md"
    outside_path.write_text("outside\n", encoding="utf-8")
    (harness_path / "RALPH_LOOP.md").symlink_to(outside_path)

    with pytest.raises(BriefError, match="symlink"):
        write_operating_brief(harness_path, "changed\n", overwrite=True)

    assert outside_path.read_text(encoding="utf-8") == "outside\n"


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    return path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
