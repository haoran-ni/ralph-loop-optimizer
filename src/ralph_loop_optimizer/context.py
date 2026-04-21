"""Iteration context loading and prompt assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ralph_loop_optimizer.artifacts import RunPaths
from ralph_loop_optimizer.brief import BRIEF_FILENAME
from ralph_loop_optimizer.config import OptimizerConfig
from ralph_loop_optimizer.harness import WorktreeStatus, assert_git_repository


class ContextError(ValueError):
    """Raised when iteration context cannot be loaded."""


@dataclass(frozen=True)
class IterationContext:
    operating_brief: str
    harness_instructions: dict[Path, str] = field(default_factory=dict)
    prior_lessons: tuple[str, ...] = ()
    latest_evaluation: str | None = None
    worktree_status: WorktreeStatus | None = None


def load_operating_brief(repo_path: Path) -> str:
    repo_path = repo_path.expanduser().resolve()
    assert_git_repository(repo_path)
    brief_path = repo_path / BRIEF_FILENAME

    if not brief_path.exists():
        raise ContextError(f"{BRIEF_FILENAME} does not exist; run init first")
    if not brief_path.is_file():
        raise ContextError(f"{BRIEF_FILENAME} must be a file")

    return brief_path.read_text(encoding="utf-8", errors="replace")


def load_prior_lessons(run_paths: RunPaths) -> list[str]:
    if not run_paths.iterations_dir.exists():
        return []

    lessons: list[str] = []
    for iteration_dir in _iteration_dirs(run_paths):
        lesson_path = iteration_dir / "lesson.md"
        if not lesson_path.is_file():
            continue
        lesson = lesson_path.read_text(encoding="utf-8", errors="replace").strip()
        if lesson:
            lessons.append(
                _format_evidence_text(
                    f"Iteration {iteration_dir.name}",
                    lesson_path,
                    run_paths.repo_path,
                    lesson,
                )
            )
    return lessons


def load_latest_evaluation(run_paths: RunPaths) -> str | None:
    if not run_paths.iterations_dir.exists():
        return None

    for iteration_dir in reversed(_iteration_dirs(run_paths)):
        evaluation_path = iteration_dir / "evaluation.txt"
        if not evaluation_path.is_file():
            continue
        evaluation = evaluation_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).strip()
        return _format_evidence_text(
            f"Iteration {iteration_dir.name}",
            evaluation_path,
            run_paths.repo_path,
            evaluation or "(empty evaluation output)",
        )
    return None


def build_iteration_prompt(
    config: OptimizerConfig,
    context: IterationContext,
) -> str:
    lines = [
        "# Ralph Loop Iteration Prompt",
        "",
        "Use the evidence below to attempt exactly one focused improvement in "
        "the harness repository.",
        "",
        "## Goal",
        "",
        config.goal.strip(),
        "",
        "## Orchestration Constraints",
        "",
        f"- Harness repository: `{config.harness_path.expanduser().resolve()}`",
        f"- Backend: `{config.backend}`",
        f"- Maximum iterations for this run: {config.max_iterations}",
        "- Evaluation command: "
        f"{_format_optional_command(config.evaluation_command)}",
        f"- Run artifact directory: `{config.run_artifact_dir.as_posix()}`",
        "- Command timeout: "
        f"{_format_optional_seconds(config.command_timeout_seconds)}",
        f"- Resume behavior: `{config.resume_behavior}`",
        "",
        "## Current Worktree Status",
        "",
        *_format_worktree_status(context.worktree_status),
        "",
        "## Operating Brief",
        "",
        *_format_text_block(context.operating_brief),
        "",
        "## Harness Instructions",
        "",
        *_format_harness_instructions(context.harness_instructions),
        "",
        "## Prior Lessons",
        "",
        *_format_optional_items(context.prior_lessons, "No prior lessons recorded."),
        "",
        "## Latest Evaluation",
        "",
        *_format_optional_text(
            context.latest_evaluation,
            "No prior evaluation output recorded.",
        ),
        "",
        "## Backend Task",
        "",
        "- Read the operating brief and harness instructions before editing.",
        "- Make one small, reviewable change tied directly to the goal.",
        "- Do not change harness evaluation behavior unless the brief explicitly "
        "allows it.",
        "- Leave unrelated files and formatting alone.",
        "- Preserve useful evidence for the optimizer to record after evaluation.",
        "",
    ]
    return "\n".join(lines)


def _iteration_dirs(run_paths: RunPaths) -> list[Path]:
    return sorted(
        (path for path in run_paths.iterations_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    )


def _format_evidence_text(
    title: str,
    path: Path,
    repo_path: Path,
    content: str,
) -> str:
    return "\n".join(
        [
            f"{title} (`{_relative_path(path, repo_path)}`):",
            "",
            content,
        ]
    )


def _format_optional_command(command: str | None) -> str:
    if command is None:
        return "not provided"
    return f"`{command.strip()}`"


def _format_optional_seconds(seconds: int | None) -> str:
    if seconds is None:
        return "not configured"
    return f"{seconds} seconds"


def _format_worktree_status(status: WorktreeStatus | None) -> list[str]:
    if status is None:
        return ["- Not checked."]
    if not status.entries:
        return ["- Clean."]
    return ["- Uncommitted entries:", *[f"  - `{entry}`" for entry in status.entries]]


def _format_harness_instructions(instructions: dict[Path, str]) -> list[str]:
    if not instructions:
        return ["No harness instruction files were loaded."]

    lines: list[str] = []
    for path, content in sorted(instructions.items(), key=lambda item: item[0].as_posix()):
        lines.extend([f"### `{path.as_posix()}`", "", *_format_text_block(content), ""])
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _format_optional_items(items: tuple[str, ...], empty_message: str) -> list[str]:
    if not items:
        return [empty_message]

    lines: list[str] = []
    for item in items:
        lines.extend(_format_text_block(item))
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _format_optional_text(content: str | None, empty_message: str) -> list[str]:
    if content is None:
        return [empty_message]
    return _format_text_block(content)


def _format_text_block(content: str) -> list[str]:
    text = content.strip()
    if not text:
        return ["(empty)"]
    return ["```text", text, "```"]


def _relative_path(path: Path, repo_path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_path.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
