from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ralph_loop_optimizer.artifacts import (
    create_iteration_paths,
    create_run_paths,
)
from ralph_loop_optimizer.lessons import (
    Lesson,
    LessonEvidence,
    distill_lesson,
    format_lessons_for_prompt,
    load_lessons,
)


def test_distill_lesson_links_successful_iteration_evidence() -> None:
    lesson = distill_lesson(
        LessonEvidence(
            iteration_number=1,
            backend_name="fake",
            backend_succeeded=True,
            backend_exit_code=0,
            evaluation_succeeded=True,
            evaluation_exit_code=0,
            commit_hash="abc1234",
            diff_path=Path("ralph_loop_runs/run-001/iterations/001/diff.patch"),
            result_path=Path("ralph_loop_runs/run-001/iterations/001/result.md"),
        )
    )

    assert "# Iteration 001 Lesson" in lesson
    assert "- Backend: `fake` succeeded with exit code 0." in lesson
    assert "- Evaluation: succeeded with exit code 0." in lesson
    assert "- Commit: `abc1234`." in lesson
    assert (
        "- Result and evaluation record: "
        "`ralph_loop_runs/run-001/iterations/001/result.md`"
    ) in lesson
    assert "- Diff: `ralph_loop_runs/run-001/iterations/001/diff.patch`" in lesson
    assert "Draft lesson seed for the post-evaluation AI review" in lesson
    assert "compare the current metric output against prior evidence" in lesson
    assert "record only the key takeaway" in lesson


def test_distill_lesson_handles_failed_backend() -> None:
    lesson = distill_lesson(
        LessonEvidence(
            iteration_number=2,
            backend_name="fake",
            backend_succeeded=False,
            backend_exit_code=7,
            evaluation_succeeded=None,
        )
    )

    assert "- Backend: `fake` failed with exit code 7." in lesson
    assert "- Evaluation: not recorded." in lesson
    assert "implementation backend did not complete cleanly" in lesson
    assert "should not treat this as an improvement without evidence" in lesson


def test_distill_lesson_handles_failed_evaluation() -> None:
    lesson = distill_lesson(
        LessonEvidence(
            iteration_number=3,
            backend_name="fake",
            backend_succeeded=True,
            backend_exit_code=0,
            evaluation_succeeded=False,
            evaluation_exit_code=2,
        )
    )

    assert "- Evaluation: failed with exit code 2." in lesson
    assert "Evaluation failed" in lesson
    assert "failure signal" in lesson
    assert "what to avoid or diagnose next" in lesson


def test_distill_lesson_handles_manual_evaluation() -> None:
    lesson = distill_lesson(
        LessonEvidence(
            iteration_number=4,
            backend_name="fake",
            backend_succeeded=True,
            manual_evaluation_required=True,
        )
    )

    assert "- Evaluation: manual evaluation required." in lesson
    assert "Manual evaluation is required" in lesson
    assert "stay inconclusive until user-provided evaluation evidence exists" in lesson


def test_distill_lesson_handles_timed_out_evaluation() -> None:
    lesson = distill_lesson(
        LessonEvidence(
            iteration_number=5,
            backend_name="fake",
            backend_succeeded=True,
            evaluation_timed_out=True,
        )
    )

    assert "- Evaluation: timed out." in lesson
    assert "Evaluation timed out" in lesson
    assert "time budget" in lesson
    assert "using the diff and logs" in lesson


def test_distill_lesson_handles_inconclusive_evaluation() -> None:
    lesson = distill_lesson(
        LessonEvidence(
            iteration_number=6,
            backend_name="fake",
            backend_succeeded=True,
            evaluation_succeeded=None,
        )
    )

    assert "- Evaluation: not recorded." in lesson
    assert "inconclusive" in lesson


def test_distill_lesson_rejects_invalid_iteration_number() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        distill_lesson(
            LessonEvidence(
                iteration_number=0,
                backend_name="fake",
                backend_succeeded=True,
            )
        )


def test_load_lessons_reads_nonempty_iteration_lessons(tmp_path: Path) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")
    first_paths = create_iteration_paths(run_paths, 1)
    second_paths = create_iteration_paths(run_paths, 2)
    create_iteration_paths(run_paths, 3)
    _write(first_paths.lesson_path, "First lesson.\n")
    _write(second_paths.lesson_path, "\n")

    lessons = load_lessons(run_paths)

    assert lessons == [
        Lesson(
            iteration_number=1,
            source_path=Path("ralph_loop_runs/run-001/iterations/001/lesson.md"),
            content="First lesson.",
        )
    ]


def test_load_lessons_returns_empty_list_without_iterations(tmp_path: Path) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")
    run_paths.iterations_dir.rmdir()

    assert load_lessons(run_paths) == []


def test_format_lessons_for_prompt_includes_evidence_paths() -> None:
    formatted = format_lessons_for_prompt(
        [
            Lesson(
                iteration_number=1,
                source_path=Path("ralph_loop_runs/run-001/iterations/001/lesson.md"),
                content="First lesson.",
            ),
            Lesson(
                iteration_number=2,
                source_path=Path("ralph_loop_runs/run-001/iterations/002/lesson.md"),
                content="Second lesson.",
            ),
        ]
    )

    assert formatted == (
        "Iteration 001 (`ralph_loop_runs/run-001/iterations/001/lesson.md`):"
        "\n\nFirst lesson.\n\n"
        "Iteration 002 (`ralph_loop_runs/run-001/iterations/002/lesson.md`):"
        "\n\nSecond lesson."
    )


def test_format_lessons_for_prompt_handles_empty_list() -> None:
    assert format_lessons_for_prompt([]) == "No prior lessons recorded."


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    return path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
