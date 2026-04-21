"""Backend adapter registry."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from ralph_loop_optimizer.backends.base import (
    BackendRequest,
    BackendResult,
    CodingBackend,
)
from ralph_loop_optimizer.backends.claude import ClaudeCodeBackend
from ralph_loop_optimizer.backends.codex import CodexBackend


class BackendError(ValueError):
    """Raised when a backend name cannot be resolved."""


@dataclass(frozen=True)
class FakeBackend:
    name: str = "fake"

    def run_backend(self, request: BackendRequest) -> BackendResult:
        started_at = perf_counter()
        stdout = "\n".join(
            [
                "Fake backend completed without modifying the harness.",
                f"Prompt characters: {len(request.prompt)}",
                f"Operating brief characters: {len(request.operating_brief)}",
                f"Harness instruction files: {len(request.harness_instructions)}",
                f"Prior lessons: {len(request.prior_lessons)}",
                "Latest evaluation provided: "
                f"{'yes' if request.latest_evaluation is not None else 'no'}",
                "",
            ]
        )
        return BackendResult(
            backend_name=self.name,
            exit_code=0,
            stdout=stdout,
            stderr="",
            elapsed_seconds=perf_counter() - started_at,
            transcript_path=None,
        )


_BACKENDS: dict[str, CodingBackend] = {
    "claude": ClaudeCodeBackend(),
    "codex": CodexBackend(),
    "fake": FakeBackend(),
}


def get_backend(name: str) -> CodingBackend:
    try:
        return _BACKENDS[name]
    except KeyError as exc:
        supported = ", ".join(list_backends())
        raise BackendError(
            f"unknown backend {name!r}; available backends: {supported}"
        ) from exc


def list_backends() -> list[str]:
    return sorted(_BACKENDS)
