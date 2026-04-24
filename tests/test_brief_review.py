from __future__ import annotations

from io import StringIO
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
from ralph_loop_optimizer.progress import ProgressReporter


def test_build_brief_review_prompt_defines_init_boundary(
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

    assert "# Ralph Loop Init Brief Review" in prompt
    assert "Do not optimize the harness yet." in prompt
    assert "`RALPH_LOOP.md`" in prompt
    assert "`ralph-loop.json`" in prompt
    assert "Do not copy full harness instruction" in prompt
    assert "Harness reference file paths" in prompt
    assert "File modification scope" in prompt
    assert "AI behavior requirements" in prompt
    assert "python evaluate.py" in prompt
    assert "evaluate.py" in prompt
    assert "Candidate evaluation files" not in prompt
    assert "Relevant documentation" not in prompt
    assert "Agent instruction files" not in prompt
    assert "Maximum iterations" not in prompt


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


def test_run_brief_review_streams_progress_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_path = _prepared_harness(tmp_path)
    config = OptimizerConfig(harness_path=harness_path, goal="Improve the score.")
    config_path = default_config_path(harness_path)
    write_config(config, config_path)
    _write(harness_path / "RALPH_LOOP.md", "# Brief\n")
    stdout = StringIO()
    backend = StreamingBackend()
    monkeypatch.setattr(
        "ralph_loop_optimizer.brief_review.get_backend",
        lambda name: backend,
    )

    result = run_brief_review(
        BriefReviewRequest(
            config=config,
            config_path=config_path,
            summary=inspect_harness(harness_path),
            brief="# Brief\n",
        ),
        progress=ProgressReporter(stdout=stdout, color=False),
    )

    output = stdout.getvalue()
    assert result.succeeded is True
    assert backend.saw_streaming_request is True
    assert "[ralph-loop] Init AI review prompt" in output
    assert "# Ralph Loop Init Brief Review" in output
    assert "[ralph-loop] Calling backend for init AI review: fake" in output
    assert "[agent event] fake: streamed init review output" in output
    assert "[ralph-loop] Init AI review backend finished: exit code 0" in output


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


def test_run_brief_review_rejects_invalid_config_after_review(
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
        lambda name: ConfigCorruptingBackend(),
    )

    with pytest.raises(BriefReviewError, match="review config is invalid"):
        run_brief_review(
            BriefReviewRequest(
                config=config,
                config_path=config_path,
                summary=inspect_harness(harness_path),
                brief="# Brief\n",
            )
        )


def test_run_brief_review_rejects_deleted_config_after_review(
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
        lambda name: ConfigDeletingBackend(),
    )

    with pytest.raises(BriefReviewError, match="review config must exist"):
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


class StreamingBackend:
    name = "fake"

    def __init__(self) -> None:
        self.saw_streaming_request = False

    def run_backend(self, request: BackendRequest) -> BackendResult:
        self.saw_streaming_request = (
            request.stream_output
            and request.stdout_callback is not None
            and request.stderr_callback is not None
        )
        if request.stdout_callback is not None:
            request.stdout_callback("streamed init review output\n")
        return BackendResult(backend_name=self.name, exit_code=0)


class ConfigCorruptingBackend:
    name = "fake"

    def run_backend(self, request: BackendRequest) -> BackendResult:
        (request.harness_path / "ralph-loop.json").write_text(
            "not json\n",
            encoding="utf-8",
        )
        return BackendResult(backend_name=self.name, exit_code=0)


class ConfigDeletingBackend:
    name = "fake"

    def run_backend(self, request: BackendRequest) -> BackendResult:
        (request.harness_path / "ralph-loop.json").unlink()
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
