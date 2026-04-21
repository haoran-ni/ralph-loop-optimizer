"""Pre-loop operating brief review through a coding backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ralph_loop_optimizer.backends import BackendResult, get_backend
from ralph_loop_optimizer.backends.base import BackendRequest, run_backend
from ralph_loop_optimizer.brief import BRIEF_FILENAME
from ralph_loop_optimizer.config import ConfigError, OptimizerConfig, load_config
from ralph_loop_optimizer.git import get_status
from ralph_loop_optimizer.harness import HarnessSummary


class BriefReviewError(ValueError):
    """Raised when pre-loop brief review cannot be completed safely."""


@dataclass(frozen=True)
class BriefReviewRequest:
    config: OptimizerConfig
    config_path: Path
    summary: HarnessSummary
    brief: str


@dataclass(frozen=True)
class BriefReviewResult:
    backend_result: BackendResult
    brief_path: Path
    config_path: Path
    changed_paths: tuple[Path, ...]

    @property
    def succeeded(self) -> bool:
        return self.backend_result.succeeded


def run_brief_review(request: BriefReviewRequest) -> BriefReviewResult:
    repo_path = request.summary.repo_path
    brief_path = repo_path / BRIEF_FILENAME
    config_path = request.config_path.expanduser().resolve()
    allowed_paths = _allowed_review_paths(repo_path, config_path)

    _assert_only_review_files_changed(repo_path, allowed_paths, "before review")

    backend_result = run_backend(
        get_backend(request.config.backend),
        BackendRequest(
            harness_path=repo_path,
            prompt=build_brief_review_prompt(
                request.config,
                request.summary,
                request.brief,
            ),
            operating_brief=request.brief,
            harness_instructions=request.summary.instructions,
            timeout_seconds=request.config.command_timeout_seconds,
        ),
    )

    changed_paths = _dirty_paths(repo_path)
    _assert_only_review_files_changed(repo_path, allowed_paths, "after review")

    result = BriefReviewResult(
        backend_result=backend_result,
        brief_path=brief_path,
        config_path=config_path,
        changed_paths=changed_paths,
    )
    apply_brief_review_result(repo_path, result)
    return result


def build_brief_review_prompt(
    config: OptimizerConfig,
    summary: HarnessSummary,
    brief: str,
) -> str:
    return "\n".join(
        [
            "# Ralph Loop Pre-Run Brief Review",
            "",
            "You are reviewing a harness before any optimization iterations start.",
            "Do not optimize the harness yet.",
            "",
            "Allowed file edits:",
            f"- `{BRIEF_FILENAME}`",
            "- `ralph-loop.json` if configuration corrections are necessary",
            "",
            "Do not edit target source files, evaluation files, tests, datasets, or "
            "other harness behavior.",
            "",
            "Review the operating brief against the harness files and instructions. "
            "If useful, update the brief to clarify the goal, evaluation command, "
            "safe edit boundaries, assumptions, uncertainties, and questions for "
            "the user. If the brief is already adequate, leave it unchanged.",
            "",
            "If user clarification is needed, add concise questions to "
            f"`{BRIEF_FILENAME}` instead of starting an optimization attempt.",
            "",
            "Current configuration:",
            "",
            f"- Harness path: `{summary.repo_path}`",
            f"- Goal: {config.goal.strip()}",
            f"- Backend: `{config.backend}`",
            f"- Maximum iterations: {config.max_iterations}",
            "- Evaluation command: "
            f"{_format_optional(config.evaluation_command)}",
            f"- Run artifact directory: `{config.run_artifact_dir.as_posix()}`",
            "- Command timeout seconds: "
            f"{_format_optional(config.command_timeout_seconds)}",
            "",
            "Candidate evaluation files:",
            "",
            *_format_paths(summary.candidate_evaluation_files),
            "",
            "Relevant documentation:",
            "",
            *_format_paths(summary.candidate_docs),
            "",
            "Agent instruction files:",
            "",
            *_format_paths(summary.instruction_files),
            "",
            "Current operating brief:",
            "",
            brief.rstrip(),
            "",
        ]
    )


def apply_brief_review_result(
    repo_path: Path,
    result: BriefReviewResult,
) -> Path:
    expected_brief = repo_path.expanduser().resolve() / BRIEF_FILENAME
    if result.brief_path != expected_brief:
        raise BriefReviewError("review result points at the wrong operating brief")
    if not result.brief_path.is_file():
        raise BriefReviewError(f"{BRIEF_FILENAME} must exist after review")
    if result.config_path.is_symlink():
        raise BriefReviewError("review config must not be a symlink")
    if not result.config_path.is_file():
        raise BriefReviewError("review config must exist after review")

    try:
        reviewed_config = load_config(result.config_path)
    except ConfigError as exc:
        raise BriefReviewError(f"review config is invalid after review: {exc}") from exc

    if reviewed_config.harness_path.expanduser().resolve() != expected_brief.parent:
        raise BriefReviewError("review config must still point at the reviewed harness")
    return result.brief_path


def _allowed_review_paths(repo_path: Path, config_path: Path) -> set[Path]:
    allowed = {Path(BRIEF_FILENAME)}
    try:
        allowed.add(config_path.relative_to(repo_path))
    except ValueError:
        pass
    return allowed


def _assert_only_review_files_changed(
    repo_path: Path,
    allowed_paths: set[Path],
    phase: str,
) -> None:
    disallowed = [
        path for path in _dirty_paths(repo_path) if path not in allowed_paths
    ]
    if not disallowed:
        return

    formatted = ", ".join(path.as_posix() for path in disallowed)
    allowed = ", ".join(path.as_posix() for path in sorted(allowed_paths))
    raise BriefReviewError(
        f"worktree has changes outside review files {phase}: {formatted}. "
        f"Only these files may be dirty for brief review: {allowed}"
    )


def _dirty_paths(repo_path: Path) -> tuple[Path, ...]:
    return tuple(_status_entry_path(entry) for entry in get_status(repo_path).entries)


def _status_entry_path(entry: str) -> Path:
    path_text = entry[3:]
    if " -> " in path_text:
        path_text = path_text.split(" -> ", 1)[1]
    return Path(path_text.strip('"'))


def _format_paths(paths: list[Path]) -> list[str]:
    if not paths:
        return ["- None found."]
    return [f"- `{path.as_posix()}`" for path in paths]


def _format_optional(value: object | None) -> str:
    if value is None:
        return "not provided"
    return f"`{value}`"
