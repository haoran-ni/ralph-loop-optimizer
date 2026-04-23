from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import ralph_loop_optimizer.git as git_helpers
from ralph_loop_optimizer.git import (
    GitError,
    assert_clean_worktree,
    commit,
    current_head,
    get_diff,
    get_status,
    reset_hard,
    stage_paths,
)


def test_get_status_detects_clean_and_dirty_worktree(tmp_path: Path) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    _write(repo_path / "README.md", "# Harness\n")
    _commit_all(repo_path, "initial")

    clean_status = get_status(repo_path)
    assert clean_status.repo_path == repo_path.resolve()
    assert clean_status.is_dirty is False
    assert clean_status.entries == ()

    _write(repo_path / "scratch.txt", "uncommitted\n")
    dirty_status = get_status(repo_path)

    assert dirty_status.is_dirty is True
    assert dirty_status.entries == ("?? scratch.txt",)


def test_assert_clean_worktree_refuses_dirty_harness(tmp_path: Path) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    _write(repo_path / "README.md", "# Harness\n")

    with pytest.raises(GitError, match="uncommitted changes"):
        assert_clean_worktree(repo_path)


def test_get_diff_captures_tracked_and_untracked_changes(
    tmp_path: Path,
) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    _write(repo_path / "README.md", "# Harness\n")
    _commit_all(repo_path, "initial")
    _write(repo_path / "README.md", "# Harness\n\nChanged.\n")
    _write(repo_path / "notes.txt", "new note\n")

    diff = get_diff(repo_path)

    assert "diff --git a/README.md b/README.md" in diff
    assert "+Changed." in diff
    assert "notes.txt" in diff
    assert "+new note" in diff


def test_get_diff_uses_configured_null_device_for_untracked_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    empty_base = tmp_path / "empty-base"
    empty_base.write_text("", encoding="utf-8")
    _write(repo_path / "README.md", "# Harness\n")
    _commit_all(repo_path, "initial")
    _write(repo_path / "notes.txt", "new note\n")
    monkeypatch.setattr(git_helpers.os, "devnull", str(empty_base))

    diff = get_diff(repo_path)

    assert str(empty_base) in diff
    assert "+new note" in diff


def test_stage_paths_stages_only_requested_paths(tmp_path: Path) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    _write(repo_path / "README.md", "# Harness\n")
    _commit_all(repo_path, "initial")
    _write(repo_path / "result.txt", "recorded result\n")
    _write(repo_path / "scratch.txt", "do not stage\n")

    stage_paths(repo_path, [Path("result.txt")])

    assert _status_entries(repo_path) == ("A  result.txt", "?? scratch.txt")


def test_stage_paths_accepts_absolute_paths_inside_harness(
    tmp_path: Path,
) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    _write(repo_path / "README.md", "# Harness\n")
    _commit_all(repo_path, "initial")
    result_path = repo_path / "ralph_loop_runs" / "run-001" / "result.md"
    _write(result_path, "result\n")

    stage_paths(repo_path, [result_path])

    assert _status_entries(repo_path) == ("A  ralph_loop_runs/run-001/result.md",)


def test_stage_paths_rejects_paths_outside_harness(tmp_path: Path) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    outside_path = tmp_path / "outside.txt"
    outside_path.write_text("outside\n", encoding="utf-8")

    with pytest.raises(GitError, match="inside the harness"):
        stage_paths(repo_path, [outside_path])


def test_commit_returns_new_head_and_records_message(tmp_path: Path) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    _write(repo_path / "README.md", "# Harness\n")
    _commit_all(repo_path, "initial")
    previous_head = current_head(repo_path)
    _write(repo_path / "result.txt", "recorded result\n")
    stage_paths(repo_path, [Path("result.txt")])

    new_head = commit(repo_path, "ralph-loop iteration 001")

    assert new_head == current_head(repo_path)
    assert new_head != previous_head
    assert _latest_subject(repo_path) == "ralph-loop iteration 001"
    assert get_status(repo_path).is_dirty is False


def test_commit_rejects_empty_message(tmp_path: Path) -> None:
    repo_path = _git_repo(tmp_path / "harness")

    with pytest.raises(GitError, match="commit message"):
        commit(repo_path, " ")


def test_commit_can_create_empty_commit(tmp_path: Path) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    _write(repo_path / "README.md", "# Harness\n")
    _commit_all(repo_path, "initial")
    previous_head = current_head(repo_path)

    new_head = commit(repo_path, "empty experiment", allow_empty=True)

    assert new_head == current_head(repo_path)
    assert new_head != previous_head
    assert _latest_subject(repo_path) == "empty experiment"
    assert get_status(repo_path).is_dirty is False


def test_reset_hard_restores_requested_commit(tmp_path: Path) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    _write(repo_path / "README.md", "# Harness\n")
    _commit_all(repo_path, "initial")
    initial_head = current_head(repo_path)
    _write(repo_path / "README.md", "# Harness\n\nChanged.\n")
    _commit_all(repo_path, "second")

    restored_head = reset_hard(repo_path, initial_head)

    assert restored_head == initial_head
    assert current_head(repo_path) == initial_head
    assert _latest_subject(repo_path) == "initial"
    assert get_status(repo_path).is_dirty is False


def test_get_diff_after_staging_matches_committed_experiment(
    tmp_path: Path,
) -> None:
    repo_path = _git_repo(tmp_path / "harness")
    _write(repo_path / "README.md", "# Harness\n")
    _commit_all(repo_path, "initial")
    _write(repo_path / "README.md", "# Harness\n\nChanged.\n")
    _write(repo_path / "ralph_loop_runs" / "run-001" / "result.md", "result\n")
    stage_paths(
        repo_path,
        [Path("README.md"), Path("ralph_loop_runs/run-001/result.md")],
    )
    saved_diff = get_diff(repo_path)

    commit(repo_path, "ralph-loop iteration 001")
    committed_diff = _show_latest_diff(repo_path)

    assert saved_diff == committed_diff


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


def _status_entries(repo_path: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in result.stdout.splitlines() if line)


def _latest_subject(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _show_latest_diff(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "show", "--format=", "--binary", "HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
