"""Read-only inspection helpers for harness repositories."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


DOC_SUFFIXES = {".md", ".rst", ".txt"}
DOC_STEMS = {
    "BENCHMARK",
    "CONTRIBUTING",
    "DEVELOPMENT",
    "EVALUATION",
    "INSTALL",
    "README",
    "SETUP",
    "USAGE",
}
EVALUATION_NAME_PARTS = (
    "benchmark",
    "eval",
    "evaluate",
    "leaderboard",
    "score",
    "scoring",
)
INSTRUCTION_FILE_NAMES = {
    ".cursorrules",
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    "GEMINI.md",
}
SETUP_FILE_NAMES = {
    "Cargo.toml",
    "Dockerfile",
    "Makefile",
    "Pipfile",
    "environment.yml",
    "go.mod",
    "justfile",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "uv.lock",
    "yarn.lock",
}


class HarnessError(ValueError):
    """Raised when a harness repository cannot be inspected."""


@dataclass(frozen=True)
class WorktreeStatus:
    is_dirty: bool
    entries: tuple[str, ...]


@dataclass(frozen=True)
class HarnessSummary:
    repo_path: Path
    candidate_docs: list[Path]
    candidate_setup_files: list[Path]
    candidate_test_files: list[Path]
    candidate_evaluation_files: list[Path]
    instruction_files: list[Path]
    instructions: dict[Path, str]
    worktree_status: WorktreeStatus


def inspect_harness(repo_path: Path) -> HarnessSummary:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)
    files = _repository_files(repo_path)
    instruction_files = _find_candidate_instruction_files(files)
    return HarnessSummary(
        repo_path=repo_path,
        candidate_docs=_find_candidate_docs(files),
        candidate_setup_files=_find_candidate_setup_files(files),
        candidate_test_files=_find_candidate_test_files(files),
        candidate_evaluation_files=_find_candidate_evaluation_files(files),
        instruction_files=instruction_files,
        instructions=_read_files(repo_path, instruction_files),
        worktree_status=get_worktree_status(repo_path),
    )


def find_candidate_docs(repo_path: Path) -> list[Path]:
    return _find_candidate_docs(_repository_files(repo_path))


def find_candidate_evaluation_files(repo_path: Path) -> list[Path]:
    return _find_candidate_evaluation_files(_repository_files(repo_path))


def read_harness_instructions(repo_path: Path) -> dict[Path, str]:
    repo_path = repo_path.expanduser().resolve()
    instruction_files = _find_candidate_instruction_files(_repository_files(repo_path))
    return _read_files(repo_path, instruction_files)


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


def _repository_files(repo_path: Path) -> list[Path]:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)
    result = _run_git(
        repo_path,
        ["ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
    )
    return sorted(
        (Path(line) for line in result.stdout.splitlines() if line),
        key=lambda path: path.as_posix(),
    )


def _find_candidate_docs(files: list[Path]) -> list[Path]:
    return [
        path
        for path in files
        if (
            path.suffix.lower() in DOC_SUFFIXES
            and (
                path.stem.upper() in DOC_STEMS
                or (path.parts and path.parts[0].lower() == "docs")
            )
        )
    ]


def _find_candidate_setup_files(files: list[Path]) -> list[Path]:
    return [
        path
        for path in files
        if path.name in SETUP_FILE_NAMES
        or path.name.startswith("requirements-")
        or path.name.startswith("docker-compose.")
    ]


def _find_candidate_test_files(files: list[Path]) -> list[Path]:
    return [
        path
        for path in files
        if (
            any(part in {"test", "tests", "spec", "specs"} for part in path.parts)
            or path.name.startswith("test_")
            or _stem_ends_with(path, "_test")
            or path.name.endswith(".test.js")
            or path.name.endswith(".spec.js")
            or path.name.endswith(".test.ts")
            or path.name.endswith(".spec.ts")
        )
    ]


def _find_candidate_evaluation_files(files: list[Path]) -> list[Path]:
    evaluation_files = [
        path
        for path in files
        if any(part in path.name.lower() for part in EVALUATION_NAME_PARTS)
    ]
    return _dedupe_paths(evaluation_files + _find_candidate_test_files(files))


def _find_candidate_instruction_files(files: list[Path]) -> list[Path]:
    return [
        path
        for path in files
        if path.name in INSTRUCTION_FILE_NAMES
        or (
            len(path.parts) >= 3
            and path.parts[0] == ".cursor"
            and path.parts[1] == "rules"
        )
        or path.as_posix() == ".github/copilot-instructions.md"
    ]


def _read_files(repo_path: Path, files: list[Path]) -> dict[Path, str]:
    contents: dict[Path, str] = {}
    for path in files:
        contents[path] = (repo_path / path).read_text(
            encoding="utf-8",
            errors="replace",
        )
    return contents


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _stem_ends_with(path: Path, suffix: str) -> bool:
    return path.name[: -len(path.suffix)].endswith(suffix)


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
