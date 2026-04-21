"""Codex CLI backend adapter."""

from __future__ import annotations

from dataclasses import dataclass

from ralph_loop_optimizer.backends.base import BackendRequest, BackendResult
from ralph_loop_optimizer.processes import run_command


@dataclass(frozen=True)
class CodexBackend:
    name: str = "codex"

    def run_backend(self, request: BackendRequest) -> BackendResult:
        result = run_command(
            build_codex_command(request),
            cwd=request.harness_path,
            timeout_seconds=request.timeout_seconds,
            input_text=request.prompt,
        )
        return BackendResult(
            backend_name=self.name,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            elapsed_seconds=result.elapsed_seconds,
            transcript_path=None,
        )


def build_codex_command(request: BackendRequest) -> list[str]:
    return [
        "codex",
        "exec",
        "--cd",
        str(request.harness_path),
        "--full-auto",
        "--color",
        "never",
        "-",
    ]
