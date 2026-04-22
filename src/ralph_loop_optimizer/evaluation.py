"""Harness evaluation command execution and result formatting."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Callable

from ralph_loop_optimizer.config import OptimizerConfig
from ralph_loop_optimizer.harness import assert_git_repository


class EvaluationError(ValueError):
    """Raised when evaluation cannot be started safely."""


@dataclass(frozen=True)
class EvaluationRequest:
    harness_path: Path
    evaluation_command: str | None
    timeout_seconds: int | None = None
    output_paths: tuple[Path, ...] = ()
    stdout_callback: Callable[[str], None] | None = None
    stderr_callback: Callable[[str], None] | None = None


@dataclass(frozen=True)
class EvaluationResult:
    evaluation_command: str | None
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    elapsed_seconds: float = 0.0
    timed_out: bool = False
    manual_required: bool = False
    output_files: dict[Path, str] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return (
            not self.manual_required
            and not self.timed_out
            and self.exit_code == 0
        )


def requires_manual_evaluation(config: OptimizerConfig) -> bool:
    return config.evaluation_command is None


def run_evaluation(request: EvaluationRequest) -> EvaluationResult:
    harness_path = request.harness_path.expanduser().resolve()
    assert_git_repository(harness_path)
    output_paths = _resolve_output_paths(harness_path, request.output_paths)

    if request.evaluation_command is None:
        return EvaluationResult(
            evaluation_command=None,
            exit_code=None,
            manual_required=True,
            output_files=_read_output_files(output_paths, harness_path),
        )

    command = request.evaluation_command.strip()
    if not command:
        raise EvaluationError("evaluation_command must not be empty when provided")

    started_at = perf_counter()
    process = subprocess.Popen(
        command,
        cwd=harness_path,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_process_group_kwargs(),
    )
    if request.stdout_callback is not None or request.stderr_callback is not None:
        return _communicate_streaming(
            process,
            command,
            request.timeout_seconds,
            started_at,
            output_paths,
            harness_path,
            request.stdout_callback,
            request.stderr_callback,
        )

    try:
        stdout, stderr = process.communicate(timeout=request.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(process)
        stdout, stderr = process.communicate()
        return EvaluationResult(
            evaluation_command=command,
            exit_code=None,
            stdout=_merge_timeout_output(exc.stdout, stdout),
            stderr=_merge_timeout_output(exc.stderr, stderr),
            elapsed_seconds=perf_counter() - started_at,
            timed_out=True,
            output_files=_read_output_files(output_paths, harness_path),
        )

    return EvaluationResult(
        evaluation_command=command,
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        elapsed_seconds=perf_counter() - started_at,
        output_files=_read_output_files(output_paths, harness_path),
    )


def _communicate_streaming(
    process: subprocess.Popen[str],
    command: str,
    timeout_seconds: int | None,
    started_at: float,
    output_paths: tuple[Path, ...],
    harness_path: Path,
    stdout_callback: Callable[[str], None] | None,
    stderr_callback: Callable[[str], None] | None,
) -> EvaluationResult:
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    threads = [
        threading.Thread(
            target=_read_stream,
            args=(process.stdout, stdout_chunks, stdout_callback),
            daemon=True,
        ),
        threading.Thread(
            target=_read_stream,
            args=(process.stderr, stderr_chunks, stderr_callback),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    try:
        exit_code = process.wait(timeout=timeout_seconds)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        exit_code = None
        timed_out = True

    for thread in threads:
        thread.join(timeout=1)

    return EvaluationResult(
        evaluation_command=command,
        exit_code=exit_code,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        elapsed_seconds=perf_counter() - started_at,
        timed_out=timed_out,
        output_files=_read_output_files(output_paths, harness_path),
    )


def _read_stream(
    stream: object,
    chunks: list[str],
    callback: Callable[[str], None] | None,
) -> None:
    if stream is None:
        return
    while True:
        chunk = stream.readline()
        if chunk == "":
            break
        chunks.append(chunk)
        if callback is not None:
            callback(chunk)


def format_evaluation_result(result: EvaluationResult) -> str:
    lines = [
        "# Evaluation Result",
        "",
        f"- Mode: {'manual' if result.manual_required else 'command'}",
        "- Command: "
        f"{_format_optional_command(result.evaluation_command)}",
        f"- Exit code: {_format_optional_exit_code(result.exit_code)}",
        f"- Timed out: {'yes' if result.timed_out else 'no'}",
        f"- Manual evaluation required: {'yes' if result.manual_required else 'no'}",
        f"- Succeeded: {'yes' if result.succeeded else 'no'}",
        f"- Elapsed seconds: {result.elapsed_seconds:.3f}",
        "",
    ]

    if result.manual_required:
        lines.extend(
            [
                "No evaluation command was configured. Record user-provided "
                "evaluation output before comparing this iteration.",
                "",
            ]
        )

    lines.extend(
        [
            "## Stdout",
            "",
            *_format_text_block(result.stdout),
            "",
            "## Stderr",
            "",
            *_format_text_block(result.stderr),
            "",
            "## Captured Output Files",
            "",
            *_format_output_files(result.output_files),
            "",
        ]
    )
    return "\n".join(lines)


def _resolve_output_paths(repo_path: Path, paths: tuple[Path, ...]) -> tuple[Path, ...]:
    resolved_paths: list[Path] = []
    for path in paths:
        resolved = path.expanduser()
        if not resolved.is_absolute():
            resolved = repo_path / resolved
        resolved = resolved.resolve(strict=False)
        try:
            resolved.relative_to(repo_path)
        except ValueError as exc:
            raise EvaluationError(
                f"evaluation output path must stay inside the harness: {path}"
            ) from exc
        resolved_paths.append(resolved)
    return tuple(resolved_paths)


def _read_output_files(
    output_paths: tuple[Path, ...],
    repo_path: Path,
) -> dict[Path, str]:
    output_files: dict[Path, str] = {}
    for path in output_paths:
        if not path.is_file():
            output_files[_relative_path(path, repo_path)] = "(missing)"
            continue
        output_files[_relative_path(path, repo_path)] = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    return output_files


def _format_output_files(output_files: dict[Path, str]) -> list[str]:
    if not output_files:
        return ["No output files were configured."]

    lines: list[str] = []
    for path, content in sorted(output_files.items(), key=lambda item: item[0].as_posix()):
        lines.extend([f"### `{path.as_posix()}`", "", *_format_text_block(content), ""])
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _format_optional_command(command: str | None) -> str:
    if command is None:
        return "not configured"
    return f"`{command}`"


def _format_optional_exit_code(exit_code: int | None) -> str:
    if exit_code is None:
        return "not available"
    return str(exit_code)


def _format_text_block(content: str) -> list[str]:
    if not content:
        return ["(empty)"]
    return ["```text", content.rstrip(), "```"]


def _relative_path(path: Path, repo_path: Path) -> Path:
    try:
        return path.relative_to(repo_path)
    except ValueError:
        return path


def _process_group_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        }
    return {"start_new_session": True}


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            check=False,
            capture_output=True,
            text=True,
        )
        if process.poll() is None:
            _kill_process(process)
        return

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    if process.poll() is None:
        _kill_process(process)


def _kill_process(process: subprocess.Popen[str]) -> None:
    try:
        process.kill()
    except ProcessLookupError:
        return


def _merge_timeout_output(
    timeout_output: str | bytes | None,
    final_output: str | bytes | None,
) -> str:
    timeout_text = _text_from_timeout_output(timeout_output)
    final_text = _text_from_timeout_output(final_output)
    if final_text.startswith(timeout_text):
        return final_text
    return timeout_text + final_text


def _text_from_timeout_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(encoding="utf-8", errors="replace")
    return output
