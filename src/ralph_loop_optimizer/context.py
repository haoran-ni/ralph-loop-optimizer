"""Iteration context loading and prompt assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ralph_loop_optimizer.artifacts import IterationPaths, RunPaths
from ralph_loop_optimizer.brief import BRIEF_FILENAME
from ralph_loop_optimizer.config import OptimizerConfig
from ralph_loop_optimizer.harness import WorktreeStatus, assert_git_repository


class ContextError(ValueError):
    """Raised when iteration context cannot be loaded."""


@dataclass(frozen=True)
class IterationContext:
    operating_brief: str
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
        "## Evaluation Context",
        "",
        *_format_evaluation_context(config.evaluation_command),
        "",
        "## Current Worktree Status",
        "",
        *_format_worktree_status(context.worktree_status),
        "",
        "## Operating Brief",
        "",
        *_format_text_block(context.operating_brief),
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
        "1. If there are past lessons provided, learn from the past lessons "
        "to make better decisions. If no lesson is provided, just continue "
        "as normal.",
        "2. After finalizing the new modifications, review your code.",
        "3. You can only stop when the code is ready for evaluation. To be "
        "more specific, you can only stop after fully implementing the code "
        "in this iteration and have finished the code review.",
        "",
        "- Read the operating brief before editing.",
        "- Make changes tied directly to the goal.",
        "- Do not change harness evaluation behavior unless the brief explicitly "
        "allows it.",
        "- Do not commit changes in this implementation round. Ralph Loop "
        "Optimizer will run evaluation, call the backend again for the "
        "lesson update, and handle Git staging and the final commit itself.",
        "- Leave unrelated files and formatting alone.",
        "- Preserve useful evidence for the optimizer to record after evaluation.",
        "",
    ]
    return "\n".join(lines)


def build_lesson_update_prompt(
    config: OptimizerConfig,
    context: IterationContext,
    iteration_paths: IterationPaths,
    evaluation_text: str,
    captured_diff: str,
) -> str:
    lines = [
        "# Ralph Loop Lesson Update Prompt",
        "",
        "The implementation round for this iteration has finished, and Ralph "
        "Loop Optimizer has run the configured evaluation command. Complete "
        "the iteration by updating the lesson artifact. Ralph Loop Optimizer "
        "will stage and commit the iteration after this round finishes.",
        "",
        "## Goal",
        "",
        config.goal.strip(),
        "",
        "## Required Actions",
        "",
        "- Update the `lesson.md` file given the last modification and the "
        "performance change.",
        "- Think carefully before updating `lesson.md`.",
        "- Keep `lesson.md` concise; only keep the key points.",
        "- Do not modify any actual code in this round.",
        "- Do not run the evaluation command yourself.",
        "- Do not commit changes yourself. Ralph Loop Optimizer will stage "
        "and commit the code changes from the implementation round, "
        "`lesson.md`, and the Ralph Loop artifact files after you finish.",
        "- You can only quit after updating `lesson.md` and reviewing it.",
        "",
        "## Paths",
        "",
        f"- Harness repository: `{config.harness_path.expanduser().resolve()}`",
        f"- Lesson update prompt: `{_relative_path(iteration_paths.lesson_prompt_path, config.harness_path)}`",
        f"- Evaluation output: `{_relative_path(iteration_paths.evaluation_path, config.harness_path)}`",
        f"- Diff: `{_relative_path(iteration_paths.diff_path, config.harness_path)}`",
        f"- Result record: `{_relative_path(iteration_paths.result_path, config.harness_path)}`",
        f"- Lesson artifact: `{_relative_path(iteration_paths.lesson_path, config.harness_path)}`",
        "",
        "## Prior Lessons",
        "",
        *_format_optional_items(context.prior_lessons, "No prior lessons recorded."),
        "",
        "## Previous Evaluation",
        "",
        *_format_optional_text(
            context.latest_evaluation,
            "No prior evaluation output recorded.",
        ),
        "",
        "## Current Evaluation",
        "",
        *_format_text_block(evaluation_text),
        "",
        "## Captured Implementation Diff",
        "",
        *_format_text_block(captured_diff or "(no implementation diff captured)"),
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


def _format_evaluation_context(command: str | None) -> list[str]:
    if command is None:
        return [
            "No evaluation command is configured for this harness. The "
            "optimizer will record manual evaluation mode after you finish.",
            "",
            "Do not run evaluation yourself.",
        ]
    return [
        "The optimizer will run this harness evaluation after you finish:",
        "",
        _format_optional_command(command),
        "",
        "Do not run the evaluation command yourself.",
    ]


def _format_worktree_status(status: WorktreeStatus | None) -> list[str]:
    if status is None:
        return ["- Not checked."]
    if not status.entries:
        return ["- Clean."]
    return ["- Uncommitted entries:", *[f"  - `{entry}`" for entry in status.entries]]


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
    fence = "`" * max(3, _longest_backtick_run(text) + 1)
    return [f"{fence}text", text, fence]


def _longest_backtick_run(text: str) -> int:
    longest = 0
    current = 0
    for character in text:
        if character == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _relative_path(path: Path, repo_path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_path.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
