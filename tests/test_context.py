from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ralph_loop_optimizer.artifacts import (
    create_iteration_paths,
    create_run_paths,
)
from ralph_loop_optimizer.config import OptimizerConfig
from ralph_loop_optimizer.context import (
    ContextError,
    IterationContext,
    build_iteration_prompt,
    build_lesson_update_prompt,
    load_latest_evaluation,
    load_operating_brief,
    load_prior_lessons,
)
from ralph_loop_optimizer.harness import WorktreeStatus


def test_load_operating_brief_reads_existing_brief(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "RALPH_LOOP.md", "# Brief\n\nUse this plan.\n")

    brief = load_operating_brief(harness_path)

    assert brief == "# Brief\n\nUse this plan.\n"


def test_load_operating_brief_requires_init_first(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    with pytest.raises(ContextError, match="run init first"):
        load_operating_brief(harness_path)


def test_load_prior_lessons_includes_iteration_evidence(
    tmp_path: Path,
) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")
    first_paths = create_iteration_paths(run_paths, 1)
    second_paths = create_iteration_paths(run_paths, 2)
    _write(first_paths.lesson_path, "Score improved after smaller change.\n")
    _write(second_paths.lesson_path, "Second lesson stayed neutral.\n")

    lessons = load_prior_lessons(run_paths)

    assert lessons == [
        "Iteration 001 (`ralph_loop_runs/run-001/iterations/001/lesson.md`):"
        "\n\nScore improved after smaller change.",
        "Iteration 002 (`ralph_loop_runs/run-001/iterations/002/lesson.md`):"
        "\n\nSecond lesson stayed neutral.",
    ]


def test_load_prior_lessons_ignores_missing_and_empty_lessons(
    tmp_path: Path,
) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")
    first_paths = create_iteration_paths(run_paths, 1)
    create_iteration_paths(run_paths, 2)
    _write(first_paths.lesson_path, "\n")

    assert load_prior_lessons(run_paths) == []


def test_load_latest_evaluation_reads_newest_evaluation(
    tmp_path: Path,
) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")
    first_paths = create_iteration_paths(run_paths, 1)
    second_paths = create_iteration_paths(run_paths, 2)
    _write(first_paths.evaluation_path, "score=1\n")
    _write(second_paths.evaluation_path, "score=2\n")

    latest = load_latest_evaluation(run_paths)

    assert latest == (
        "Iteration 002 "
        "(`ralph_loop_runs/run-001/iterations/002/evaluation.txt`):"
        "\n\nscore=2"
    )


def test_load_latest_evaluation_returns_none_without_evaluation(
    tmp_path: Path,
) -> None:
    run_paths = create_run_paths(_git_repo(tmp_path / "harness"), "run-001")
    create_iteration_paths(run_paths, 1)

    assert load_latest_evaluation(run_paths) is None


def test_build_iteration_prompt_includes_context_and_constraints(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the measured score.",
        backend="fake",
        max_iterations=2,
        evaluation_command="python evaluate.py",
        command_timeout_seconds=30,
    )
    context = IterationContext(
        operating_brief="# Brief\n\nFollow the operating brief.\n",
        harness_instructions={Path("AGENTS.md"): "Use the harness rules.\n"},
        prior_lessons=("Iteration 001 (`lesson.md`):\n\nKeep changes small.",),
        latest_evaluation="Iteration 001 (`evaluation.txt`):\n\nscore=7",
        worktree_status=WorktreeStatus(
            is_dirty=True,
            entries=(" M strategy.py", "?? notes.md"),
        ),
    )

    prompt = build_iteration_prompt(config, context)

    assert "# Ralph Loop Iteration Prompt" in prompt
    assert "Improve the measured score." in prompt
    assert f"- Harness repository: `{harness_path.resolve()}`" in prompt
    assert "- Backend: `fake`" in prompt
    assert "- Maximum iterations for this run: 2" in prompt
    assert "- Evaluation command: `python evaluate.py`" in prompt
    assert "- Command timeout: 30 seconds" in prompt
    assert "- Resume behavior: `refuse_dirty`" in prompt
    assert "` M strategy.py`" in prompt
    assert "`?? notes.md`" in prompt
    assert "Follow the operating brief." in prompt
    assert "### `AGENTS.md`" in prompt
    assert "Use the harness rules." in prompt
    assert "Keep changes small." in prompt
    assert "score=7" in prompt
    assert "1. Do not run the evaluation command yourself." in prompt
    assert (
        "If there are past lessons provided, learn from the past lessons "
        "to make better decisions."
    ) in prompt
    assert "After finalizing the new modifications, review your code." in prompt
    assert "You can only stop when the code is ready for evaluation." in prompt
    assert "Do not change harness evaluation behavior" in prompt
    assert "Do not commit changes in this implementation round." in prompt
    assert "handle Git staging and the final commit itself" in prompt


def test_build_iteration_prompt_handles_missing_optional_context(
    tmp_path: Path,
) -> None:
    config = OptimizerConfig(
        harness_path=_git_repo(tmp_path / "harness"),
        goal="Improve the requested result.",
    )
    context = IterationContext(operating_brief="# Brief\n")

    prompt = build_iteration_prompt(config, context)

    assert "- Evaluation command: not provided" in prompt
    assert "- Command timeout: not configured" in prompt
    assert "- Not checked." in prompt
    assert "No harness instruction files were loaded." in prompt
    assert "No prior lessons recorded." in prompt
    assert "No prior evaluation output recorded." in prompt


def test_build_iteration_prompt_uses_adaptive_fences_for_embedded_fences(
    tmp_path: Path,
) -> None:
    config = OptimizerConfig(
        harness_path=_git_repo(tmp_path / "harness"),
        goal="Improve the requested result.",
    )
    context = IterationContext(
        operating_brief="# Brief\n\n```python\nprint('ok')\n```\n",
    )

    prompt = build_iteration_prompt(config, context)

    assert "````text\n# Brief\n\n```python\nprint('ok')\n```\n````" in prompt


def test_build_iteration_prompt_does_not_add_domain_specific_assumptions(
    tmp_path: Path,
) -> None:
    config = OptimizerConfig(
        harness_path=_git_repo(tmp_path / "harness"),
        goal="Improve the requested result.",
    )
    context = IterationContext(
        operating_brief="Use the provided evaluator.",
        harness_instructions={Path("AGENTS.md"): "Only edit allowed files."},
    )

    prompt = build_iteration_prompt(config, context)

    for forbidden in ("ML", "poker", "leaderboard", "benchmark"):
        assert forbidden not in prompt


def test_build_lesson_update_prompt_instructs_backend_to_update_lesson_and_commit(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    run_paths = create_run_paths(harness_path, "run-001")
    iteration_paths = create_iteration_paths(run_paths, 1)
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the measured score.",
        backend="fake",
        evaluation_command="python evaluate.py",
    )
    context = IterationContext(
        operating_brief="# Brief\n",
        prior_lessons=("Iteration 001 (`lesson.md`):\n\nKeep it small.",),
        latest_evaluation="Iteration 001 (`evaluation.txt`):\n\nscore=7",
    )

    prompt = build_lesson_update_prompt(
        config,
        context,
        iteration_paths,
        "implementation prompt",
        "# Evaluation Result\n\n- Succeeded: yes\n\nscore=8",
        "diff --git a/strategy.py b/strategy.py\n",
    )

    assert "# Ralph Loop Lesson Update Prompt" in prompt
    assert "Update the `lesson.md` file" in prompt
    assert "performance change" in prompt
    assert "Keep `lesson.md` concise" in prompt
    assert "Do not modify any actual code in this round." in prompt
    assert "Do not commit changes yourself." in prompt
    assert "Ralph Loop Optimizer will stage and commit" in prompt
    assert "You can only quit after updating `lesson.md` and reviewing it." in prompt
    assert "`ralph_loop_runs/run-001/iterations/001/lesson.md`" in prompt
    assert "score=7" in prompt
    assert "score=8" in prompt
    assert "diff --git" in prompt


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    return path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
