"""Read-only inspection helpers for harness repositories."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class HarnessError(ValueError):
    """Raised when a harness repository cannot be inspected."""


@dataclass(frozen=True)
class WorktreeStatus:
    is_dirty: bool
    entries: tuple[str, ...]


@dataclass(frozen=True)
class HarnessSummary:
    repo_path: Path
    worktree_status: WorktreeStatus


def inspect_harness(repo_path: Path) -> HarnessSummary:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)
    return HarnessSummary(
        repo_path=repo_path,
        worktree_status=get_worktree_status(repo_path),
    )


def assert_git_repository(repo_path: Path) -> None:
    repo_path = repo_path.expanduser().resolve()
    if not repo_path.exists():
        raise HarnessError(f"harness path does not exist: {repo_path}")
    if not repo_path.is_dir():
        raise HarnessError(f"harness path must be a directory: {repo_path}")

    result = _run_git(
        repo_path,
        ["rev-parse", "--show-toplevel"],
        check=False,
    )
    if result.returncode != 0:
        raise HarnessError(f"harness path is not a Git repository: {repo_path}")

    git_root = Path(result.stdout.strip()).resolve()
    if git_root != repo_path:
        raise HarnessError(f"harness path must be the Git repository root: {repo_path}")


def get_worktree_status(repo_path: Path) -> WorktreeStatus:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)
    result = _run_git(repo_path, ["status", "--porcelain"], check=True)
    entries = tuple(line for line in result.stdout.splitlines() if line)
    return WorktreeStatus(is_dirty=bool(entries), entries=entries)


def _run_git(
    repo_path: Path,
    args: list[str],
    *,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=check,
        capture_output=True,
        text=True,
    )
