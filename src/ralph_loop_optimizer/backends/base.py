"""Shared contract for coding CLI backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


StreamCallback = Callable[[str], None]


@dataclass(frozen=True)
class BackendRequest:
    harness_path: Path
    prompt: str
    operating_brief: str = ""
    harness_instructions: dict[Path, str] = field(default_factory=dict)
    prior_lessons: tuple[str, ...] = ()
    latest_evaluation: str | None = None
    timeout_seconds: int | None = None
    stream_output: bool = False
    stdout_callback: StreamCallback | None = None
    stderr_callback: StreamCallback | None = None


@dataclass(frozen=True)
class BackendResult:
    backend_name: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    elapsed_seconds: float | None = None
    transcript_path: Path | None = None

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class CodingBackend(Protocol):
    name: str

    def run_backend(self, request: BackendRequest) -> BackendResult:
        """Run one backend attempt against the harness."""


def run_backend(
    backend: CodingBackend,
    request: BackendRequest,
) -> BackendResult:
    return backend.run_backend(request)
