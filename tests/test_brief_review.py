from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ralph_loop_optimizer.backends import BackendRequest, BackendResult
from ralph_loop_optimizer.brief_review import (
    BriefReviewError,
    BriefReviewRequest,
    build_brief_review_prompt,
    run_brief_review,
)
from ralph_loop_optimizer.config import OptimizerConfig, default_config_path, write_config
from ralph_loop_optimizer.harness import inspect_harness


def test_build_brief_review_prompt_preserves_start_boundary(
    tmp_path: Path,
) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the score.",
        evaluation_command="python evaluate.py",
    )
    summary = inspect_harness(harness_path)

    prompt = build_brief_review_prompt(
        config,
        summary,
        "# Ralph Loop Operating Brief\n",
    )

    assert "Do not optimize the harness yet." in prompt
    assert "`RALPH_LOOP.md`" in prompt
    assert "`ralph-loop.json`" in prompt
    assert "python evaluate.py" in prompt
    assert "evaluate.py" in prompt


def test_run_brief_review_with_fake_backend_preserves_harness_targets(
    tmp_path: Path,
) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the score.",
        evaluation_command="python evaluate.py",
    )
    config_path = default_config_path(harness_path)
    write_config(config, config_path)
    _write(
        harness_path / "RALPH_LOOP.md",
        "# Ralph Loop Operating Brief\n\nReview before running.\n",
    )

    result = run_brief_review(
        BriefReviewRequest(
            config=config,
            config_path=config_path,
            summary=inspect_harness(harness_path),
            brief=(harness_path / "RALPH_LOOP.md").read_text(encoding="utf-8"),
        )
    )

    assert result.succeeded is True
    assert result.backend_result.backend_name == "fake"
    assert result.changed_paths == (Path("RALPH_LOOP.md"), Path("ralph-loop.json"))
    assert (harness_path / "strategy.py").read_text(encoding="utf-8") == (
        "VALUE = 1\n"
    )
    assert not (harness_path / "ralph_loop_runs").exists()


def test_run_brief_review_refuses_dirty_target_file(tmp_path: Path) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(harness_path=harness_path, goal="Improve the score.")
    config_path = default_config_path(harness_path)
    write_config(config, config_path)
    _write(harness_path / "RALPH_LOOP.md", "# Brief\n")
    _write(harness_path / "strategy.py", "VALUE = 2\n")

    with pytest.raises(BriefReviewError, match="outside review files before"):
        run_brief_review(
            BriefReviewRequest(
                config=config,
                config_path=config_path,
                summary=inspect_harness(harness_path),
                brief="# Brief\n",
            )
        )


def test_run_brief_review_detects_backend_target_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(harness_path=harness_path, goal="Improve the score.")
    config_path = default_config_path(harness_path)
    write_config(config, config_path)
    _write(harness_path / "RALPH_LOOP.md", "# Brief\n")
    monkeypatch.setattr(
        "ralph_loop_optimizer.brief_review.get_backend",
        lambda name: TargetEditingBackend(),
    )

    with pytest.raises(BriefReviewError, match="outside review files after"):
        run_brief_review(
            BriefReviewRequest(
                config=config,
                config_path=config_path,
                summary=inspect_harness(harness_path),
                brief="# Brief\n",
            )
        )


class TargetEditingBackend:
    name = "fake"

    def run_backend(self, request: BackendRequest) -> BackendResult:
        (request.harness_path / "strategy.py").write_text(
            "VALUE = 3\n",
            encoding="utf-8",
        )
        return BackendResult(backend_name=self.name, exit_code=0)


def _prepared_harness(tmp_path: Path) -> Path:
    harness_path = _git_repo(tmp_path / "harness")
    _write(harness_path / "README.md", "# Harness\n")
    _write(harness_path / "evaluate.py", "print('score')\n")
    _write(harness_path / "strategy.py", "VALUE = 1\n")
    _commit_all(harness_path)
    return harness_path


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


def _commit_all(repo_path: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
