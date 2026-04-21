from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ralph_loop_optimizer.harness import (
    HarnessError,
    assert_git_repository,
    find_candidate_docs,
    find_candidate_evaluation_files,
    get_worktree_status,
    inspect_harness,
    read_harness_instructions,
)


def test_assert_git_repository_rejects_non_git_path(tmp_path: Path) -> None:
    harness_path = tmp_path / "not-git"
    harness_path.mkdir()

    with pytest.raises(HarnessError, match="not a Git repository"):
        assert_git_repository(harness_path)


def test_find_candidate_docs_detects_root_and_docs_folder_files(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _write(harness_path / "docs" / "evaluation.md", "# Evaluation\n")
    _write(harness_path / "src" / "notes.md", "# Internal notes\n")

    assert find_candidate_docs(harness_path) == [
        Path("README.md"),
        Path("docs/evaluation.md"),
    ]


def test_find_candidate_evaluation_files_detects_scripts_and_tests(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "evaluate.py", "print('score')\n")
    _write(harness_path / "scripts" / "benchmark.sh", "echo benchmark\n")
    _write(harness_path / "tests" / "test_policy.py", "def test_policy(): pass\n")
    _write(harness_path / "src" / "policy.py", "POLICY = 'baseline'\n")

    assert find_candidate_evaluation_files(harness_path) == [
        Path("evaluate.py"),
        Path("scripts/benchmark.sh"),
        Path("tests/test_policy.py"),
    ]


def test_read_harness_instructions_detects_agent_instruction_files(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "AGENTS.md", "Use the harness rules.\n")
    _write(harness_path / ".cursor" / "rules" / "optimizer.mdc", "Cursor rule.\n")
    _write(harness_path / "README.md", "# Harness\n")

    instructions = read_harness_instructions(harness_path)

    assert instructions == {
        Path(".cursor/rules/optimizer.mdc"): "Cursor rule.\n",
        Path("AGENTS.md"): "Use the harness rules.\n",
    }


def test_inspect_harness_skips_deleted_tracked_instruction_files(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "AGENTS.md", "Use the harness rules.\n")
    _commit_all(harness_path)
    (harness_path / "AGENTS.md").unlink()

    summary = inspect_harness(harness_path)

    assert summary.instruction_files == []
    assert summary.instructions == {}
    assert summary.worktree_status.is_dirty is True
    assert summary.worktree_status.entries == (" D AGENTS.md",)


def test_get_worktree_status_detects_clean_and_dirty_worktree(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _commit_all(harness_path)

    clean_status = get_worktree_status(harness_path)
    assert clean_status.is_dirty is False
    assert clean_status.entries == ()

    _write(harness_path / "scratch.txt", "uncommitted\n")
    dirty_status = get_worktree_status(harness_path)

    assert dirty_status.is_dirty is True
    assert dirty_status.entries == ("?? scratch.txt",)


def test_inspect_harness_returns_stable_summary(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _write(harness_path / "pyproject.toml", "[project]\nname = 'harness'\n")
    _write(harness_path / "evaluate.py", "print('score')\n")
    _write(harness_path / "tests" / "test_score.py", "def test_score(): pass\n")
    _write(harness_path / "AGENTS.md", "Stay generic.\n")

    summary = inspect_harness(harness_path)

    assert summary.repo_path == harness_path.resolve()
    assert summary.candidate_docs == [Path("README.md")]
    assert summary.candidate_setup_files == [Path("pyproject.toml")]
    assert summary.candidate_test_files == [Path("tests/test_score.py")]
    assert summary.candidate_evaluation_files == [
        Path("evaluate.py"),
        Path("tests/test_score.py"),
    ]
    assert summary.instruction_files == [Path("AGENTS.md")]
    assert summary.instructions == {Path("AGENTS.md"): "Stay generic.\n"}
    assert summary.worktree_status.is_dirty is True


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


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
