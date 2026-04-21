"""Git helpers for harness experiment recording."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ralph_loop_optimizer.harness import assert_git_repository


class GitError(ValueError):
    """Raised when a Git operation cannot be completed."""


@dataclass(frozen=True)
class GitStatus:
    repo_path: Path
    entries: tuple[str, ...]

    @property
    def is_dirty(self) -> bool:
        return bool(self.entries)


def get_status(repo_path: Path) -> GitStatus:
    repo_path = _repo_root(repo_path)
    result = _run_git(repo_path, ["status", "--porcelain"], check=True)
    return GitStatus(
        repo_path=repo_path,
        entries=tuple(line for line in result.stdout.splitlines() if line),
    )


def assert_clean_worktree(repo_path: Path) -> None:
    status = get_status(repo_path)
    if not status.is_dirty:
        return

    entries = "\n".join(f"- {entry}" for entry in status.entries)
    raise GitError(
        "harness worktree has uncommitted changes; commit or stash them "
        f"before starting optimization:\n{entries}"
    )


def get_diff(repo_path: Path) -> str:
    repo_path = _repo_root(repo_path)
    diff_parts: list[str] = []

    if _has_head(repo_path):
        diff_result = _run_git(repo_path, ["diff", "--binary", "HEAD"], check=True)
        if diff_result.stdout:
            diff_parts.append(diff_result.stdout.rstrip())
    else:
        diff_result = _run_git(repo_path, ["diff", "--binary"], check=True)
        if diff_result.stdout:
            diff_parts.append(diff_result.stdout.rstrip())

    for path in _untracked_files(repo_path):
        result = _run_git(
            repo_path,
            ["diff", "--binary", "--no-index", "--", "/dev/null", path.as_posix()],
            check=False,
        )
        if result.stdout:
            diff_parts.append(result.stdout.rstrip())

    if not diff_parts:
        return ""
    return "\n".join(diff_parts) + "\n"


def stage_paths(repo_path: Path, paths: list[Path]) -> None:
    repo_path = _repo_root(repo_path)
    if not paths:
        raise GitError("at least one path must be provided for staging")

    relative_paths = [_relative_repo_path(repo_path, path) for path in paths]
    _run_git(
        repo_path,
        ["add", "--", *[path.as_posix() for path in relative_paths]],
        check=True,
    )


def commit(repo_path: Path, message: str) -> str:
    repo_path = _repo_root(repo_path)
    if not message.strip():
        raise GitError("commit message must not be empty")

    _run_git(repo_path, ["commit", "-m", message.strip()], check=True)
    return current_head(repo_path)


def current_head(repo_path: Path) -> str:
    repo_path = _repo_root(repo_path)
    result = _run_git(repo_path, ["rev-parse", "HEAD"], check=True)
    return result.stdout.strip()


def _repo_root(repo_path: Path) -> Path:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)
    return repo_path


def _has_head(repo_path: Path) -> bool:
    result = _run_git(repo_path, ["rev-parse", "--verify", "HEAD"], check=False)
    return result.returncode == 0


def _untracked_files(repo_path: Path) -> list[Path]:
    result = _run_git(
        repo_path,
        ["ls-files", "--others", "--exclude-standard"],
        check=True,
    )
    return [
        Path(line)
        for line in result.stdout.splitlines()
        if line and (repo_path / line).is_file()
    ]


def _relative_repo_path(repo_path: Path, path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = repo_path / candidate
    resolved = candidate.resolve(strict=False)

    try:
        return resolved.relative_to(repo_path)
    except ValueError as exc:
        raise GitError(f"Git path must stay inside the harness repository: {path}") from exc


def _run_git(
    repo_path: Path,
    args: list[str],
    *,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        command = "git " + " ".join(args)
        raise GitError(f"{command} failed: {detail}")
    return result
