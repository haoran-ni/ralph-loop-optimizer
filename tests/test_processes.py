from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ralph_loop_optimizer.processes import ProcessError, run_command


def test_run_command_captures_stdout_stderr_and_stdin(tmp_path: Path) -> None:
    result = run_command(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "text = sys.stdin.read(); "
                "print(text.upper()); "
                "print('note', file=sys.stderr)"
            ),
        ],
        cwd=tmp_path,
        timeout_seconds=5,
        input_text="score",
    )

    assert result.exit_code == 0
    assert result.stdout == "SCORE\n"
    assert result.stderr == "note\n"
    assert result.timed_out is False
    assert result.elapsed_seconds >= 0


def test_run_command_streams_stdout_stderr_while_capturing(
    tmp_path: Path,
) -> None:
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    result = run_command(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "print('out', flush=True); "
                "print('err', file=sys.stderr, flush=True)"
            ),
        ],
        cwd=tmp_path,
        timeout_seconds=5,
        stdout_callback=stdout_chunks.append,
        stderr_callback=stderr_chunks.append,
    )

    assert result.exit_code == 0
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert stdout_chunks == ["out\n"]
    assert stderr_chunks == ["err\n"]


def test_run_command_records_missing_binary(tmp_path: Path) -> None:
    result = run_command(
        ["definitely-missing-ralph-loop-command"],
        cwd=tmp_path,
        timeout_seconds=5,
    )

    assert result.exit_code == 127
    assert "command not found" in result.stderr


def test_run_command_records_timeout(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        cwd=tmp_path,
        timeout_seconds=1,
    )

    assert result.exit_code == 124
    assert result.timed_out is True
    assert "timed out" in result.stderr


def test_run_command_rejects_empty_command(tmp_path: Path) -> None:
    with pytest.raises(ProcessError, match="must not be empty"):
        run_command([], cwd=tmp_path, timeout_seconds=5)
