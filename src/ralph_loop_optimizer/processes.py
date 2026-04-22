"""Subprocess execution helpers."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable


class ProcessError(ValueError):
    """Raised when a subprocess cannot be configured safely."""


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    elapsed_seconds: float = 0.0
    timed_out: bool = False


def run_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: int | None,
    *,
    input_text: str | None = None,
    stdout_callback: Callable[[str], None] | None = None,
    stderr_callback: Callable[[str], None] | None = None,
) -> CommandResult:
    if not command:
        raise ProcessError("command must not be empty")

    started_at = perf_counter()
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **_process_group_kwargs(),
        )
    except FileNotFoundError:
        return CommandResult(
            command=tuple(command),
            exit_code=127,
            stderr=f"command not found: {command[0]}\n",
            elapsed_seconds=perf_counter() - started_at,
        )

    if stdout_callback is not None or stderr_callback is not None:
        return _communicate_streaming(
            process,
            tuple(command),
            input_text,
            timeout_seconds,
            started_at,
            stdout_callback,
            stderr_callback,
        )

    try:
        stdout, stderr = process.communicate(
            input=input_text,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(process)
        stdout, stderr = process.communicate()
        return CommandResult(
            command=tuple(command),
            exit_code=124,
            stdout=_merge_timeout_output(exc.stdout, stdout),
            stderr=(
                _merge_timeout_output(exc.stderr, stderr)
                + f"command timed out after {timeout_seconds} seconds\n"
            ),
            elapsed_seconds=perf_counter() - started_at,
            timed_out=True,
        )

    return CommandResult(
        command=tuple(command),
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        elapsed_seconds=perf_counter() - started_at,
    )


def _communicate_streaming(
    process: subprocess.Popen[str],
    command: tuple[str, ...],
    input_text: str | None,
    timeout_seconds: int | None,
    started_at: float,
    stdout_callback: Callable[[str], None] | None,
    stderr_callback: Callable[[str], None] | None,
) -> CommandResult:
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

    if input_text is not None and process.stdin is not None:
        try:
            process.stdin.write(input_text)
            process.stdin.close()
        except BrokenPipeError:
            pass

    try:
        exit_code = process.wait(timeout=timeout_seconds)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        exit_code = 124
        timed_out = True

    for thread in threads:
        thread.join(timeout=1)

    stderr = "".join(stderr_chunks)
    if timed_out:
        stderr += f"command timed out after {timeout_seconds} seconds\n"

    return CommandResult(
        command=command,
        exit_code=exit_code,
        stdout="".join(stdout_chunks),
        stderr=stderr,
        elapsed_seconds=perf_counter() - started_at,
        timed_out=timed_out,
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
        return output.decode("utf-8", errors="replace")
    return output
