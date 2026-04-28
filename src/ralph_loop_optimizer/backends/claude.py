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
            stdout_callback=request.stdout_callback,
            stderr_callback=request.stderr_callback,
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
    command = [
        "claude",
        "--print",
        "--permission-mode",
        "acceptEdits",
        "--input-format",
        "text",
        "--output-format",
        "stream-json" if request.stream_output else "text",
    ]
    if request.stream_output:
        command.extend(["--verbose", "--include-partial-messages"])
    return command
