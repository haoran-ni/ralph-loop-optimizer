"""Lesson distillation and loading helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ralph_loop_optimizer.artifacts import RunPaths


@dataclass(frozen=True)
class LessonEvidence:
    iteration_number: int
    backend_name: str
    backend_succeeded: bool
    backend_exit_code: int | None = None
    evaluation_succeeded: bool | None = None
    evaluation_exit_code: int | None = None
    evaluation_timed_out: bool = False
    manual_evaluation_required: bool = False
    commit_hash: str | None = None
    evaluation_path: Path | None = None
    diff_path: Path | None = None
    result_path: Path | None = None


@dataclass(frozen=True)
class Lesson:
    iteration_number: int
    source_path: Path
    content: str


def distill_lesson(iteration_record: LessonEvidence) -> str:
    """Create a compact deterministic lesson from recorded iteration evidence."""

    _validate_iteration_number(iteration_record.iteration_number)
    return "\n".join(
        [
            f"# Iteration {iteration_record.iteration_number:03d} Lesson",
            "",
            "## Outcome",
            "",
            *_format_outcome(iteration_record),
            "",
            "## Evidence",
            "",
            *_format_evidence(iteration_record),
            "",
            "## Lesson",
            "",
            _lesson_text(iteration_record),
            "",
        ]
    )


def load_lessons(run_paths: RunPaths) -> list[Lesson]:
    if not run_paths.iterations_dir.exists():
        return []

    lessons: list[Lesson] = []
    for iteration_dir in _iteration_dirs(run_paths):
        lesson_path = iteration_dir / "lesson.md"
        if not lesson_path.is_file():
            continue

        content = lesson_path.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            continue

        lessons.append(
            Lesson(
                iteration_number=int(iteration_dir.name),
                source_path=_relative_path(lesson_path, run_paths.repo_path),
                content=content,
            )
        )
    return lessons


def format_lessons_for_prompt(lessons: list[Lesson]) -> str:
    if not lessons:
        return "No prior lessons recorded."

    blocks: list[str] = []
    for lesson in lessons:
        blocks.append(
            "\n".join(
                [
                    f"Iteration {lesson.iteration_number:03d} "
                    f"(`{lesson.source_path.as_posix()}`):",
                    "",
                    lesson.content,
                ]
            )
        )
    return "\n\n".join(blocks)


def _format_outcome(record: LessonEvidence) -> list[str]:
    return [
        "- Backend: "
        f"`{record.backend_name}` {_format_success(record.backend_succeeded)}"
        f"{_format_exit_code(record.backend_exit_code)}.",
        "- Evaluation: "
        f"{_format_evaluation_status(record)}"
        f"{_format_exit_code(record.evaluation_exit_code)}.",
        f"- Commit: {_format_commit(record.commit_hash)}.",
    ]


def _format_evidence(record: LessonEvidence) -> list[str]:
    return [
        f"- Evaluation output: {_format_optional_path(record.evaluation_path)}",
        f"- Diff: {_format_optional_path(record.diff_path)}",
        f"- Result record: {_format_optional_path(record.result_path)}",
        f"- Commit hash: {_format_commit(record.commit_hash)}",
    ]


def _lesson_text(record: LessonEvidence) -> str:
    prefix = (
        "Draft lesson seed for the post-evaluation AI review. Replace this "
        "with a concise, evidence-backed lesson after reviewing the "
        "implementation diff and evaluation output. "
    )

    if not record.backend_succeeded:
        return (
            prefix +
            "The implementation backend did not complete cleanly. The final "
            "lesson should mention whether any partial changes are usable, "
            "and should not treat this as an improvement without evidence."
        )

    if record.manual_evaluation_required:
        return (
            prefix +
            "Manual evaluation is required. The final lesson should stay "
            "inconclusive until user-provided evaluation evidence exists."
        )

    if record.evaluation_timed_out:
        return (
            prefix +
            "Evaluation timed out. The final lesson should identify whether "
            "the change likely exceeded the time budget or blocked evaluation, "
            "using the diff and logs."
        )

    if record.evaluation_succeeded is False:
        return (
            prefix +
            "Evaluation failed. The final lesson should summarize the failure "
            "signal and what to avoid or diagnose next."
        )

    if record.evaluation_succeeded is True:
        return (
            prefix +
            "Evaluation completed successfully. The final lesson should "
            "compare the current metric output against prior evidence and "
            "record only the key takeaway."
        )

    return (
        prefix +
        "No evaluation result was recorded. The final lesson should mark this "
        "iteration inconclusive."
    )


def _format_evaluation_status(record: LessonEvidence) -> str:
    if record.manual_evaluation_required:
        return "manual evaluation required"
    if record.evaluation_timed_out:
        return "timed out"
    if record.evaluation_succeeded is True:
        return "succeeded"
    if record.evaluation_succeeded is False:
        return "failed"
    return "not recorded"


def _format_success(succeeded: bool) -> str:
    return "succeeded" if succeeded else "failed"


def _format_exit_code(exit_code: int | None) -> str:
    if exit_code is None:
        return ""
    return f" with exit code {exit_code}"


def _format_commit(commit_hash: str | None) -> str:
    if commit_hash is None:
        return "not recorded"
    return f"`{commit_hash}`"


def _format_optional_path(path: Path | None) -> str:
    if path is None:
        return "not recorded"
    return f"`{path.as_posix()}`"


def _iteration_dirs(run_paths: RunPaths) -> list[Path]:
    return sorted(
        (
            path
            for path in run_paths.iterations_dir.iterdir()
            if path.is_dir() and path.name.isdecimal()
        ),
        key=lambda path: int(path.name),
    )


def _relative_path(path: Path, repo_path: Path) -> Path:
    try:
        return path.resolve().relative_to(repo_path.resolve())
    except ValueError:
        return path


def _validate_iteration_number(iteration_number: int) -> None:
    if isinstance(iteration_number, bool) or not isinstance(iteration_number, int):
        raise ValueError("iteration_number must be an integer")
    if iteration_number < 1:
        raise ValueError("iteration_number must be at least 1")
