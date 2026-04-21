"""Claude Code backend adapter."""

from __future__ import annotations

from dataclasses import dataclass

from ralph_loop_optimizer.backends.base import BackendRequest, BackendResult
from ralph_loop_optimizer.processes import run_command


@dataclass(frozen=True)
class ClaudeCodeBackend:
    name: str = "claude"

    def run_backend(self, request: BackendRequest) -> BackendResult:
        result = run_command(
            build_claude_command(request),
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


def build_claude_command(request: BackendRequest) -> list[str]:
    return [
        "claude",
        "--print",
        "--permission-mode",
        "acceptEdits",
        "--input-format",
        "text",
        "--output-format",
        "text",
    ]
