from __future__ import annotations

from pathlib import Path

import pytest

from ralph_loop_optimizer.backends import (
    BackendError,
    BackendRequest,
    BackendResult,
    get_backend,
    list_backends,
    run_backend,
)


def test_list_backends_includes_fake_backend() -> None:
    assert list_backends() == ["fake"]


def test_get_backend_returns_fake_backend() -> None:
    backend = get_backend("fake")

    assert backend.name == "fake"


def test_get_backend_rejects_unknown_backend() -> None:
    with pytest.raises(BackendError, match="unknown backend"):
        get_backend("missing")


def test_fake_backend_returns_normalized_success_result(tmp_path: Path) -> None:
    request = BackendRequest(
        harness_path=tmp_path,
        prompt="Improve the strategy.",
        operating_brief="# Brief\n",
        harness_instructions={Path("AGENTS.md"): "Use the harness rules.\n"},
        prior_lessons=("Iteration 001 improved score.",),
        latest_evaluation="score=10",
        timeout_seconds=30,
    )

    result = run_backend(get_backend("fake"), request)

    assert result == BackendResult(
        backend_name="fake",
        exit_code=0,
        stdout=result.stdout,
        stderr="",
        elapsed_seconds=result.elapsed_seconds,
        transcript_path=None,
    )
    assert result.succeeded is True
    assert "Fake backend completed" in result.stdout
    assert "Prompt characters: 21" in result.stdout
    assert "Operating brief characters: 8" in result.stdout
    assert "Harness instruction files: 1" in result.stdout
    assert "Prior lessons: 1" in result.stdout
    assert "Latest evaluation provided: yes" in result.stdout
    assert result.elapsed_seconds is not None
    assert result.elapsed_seconds >= 0


def test_run_backend_calls_adapter(tmp_path: Path) -> None:
    backend = RecordingBackend()
    request = BackendRequest(harness_path=tmp_path, prompt="Try one change.")

    result = run_backend(backend, request)

    assert backend.request == request
    assert result.backend_name == "recording"
    assert result.exit_code == 7
    assert result.succeeded is False


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.request: BackendRequest | None = None

    def run_backend(self, request: BackendRequest) -> BackendResult:
        self.request = request
        return BackendResult(
            backend_name=self.name,
            exit_code=7,
            stderr="failed",
        )
