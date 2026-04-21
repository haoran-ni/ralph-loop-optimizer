from __future__ import annotations

import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ralph_loop_optimizer.config import OptimizerConfig
from ralph_loop_optimizer.evaluation import (
    EvaluationError,
    EvaluationRequest,
    format_evaluation_result,
    requires_manual_evaluation,
    run_evaluation,
)


def test_run_evaluation_captures_successful_command(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    command = _python_command(
        "import sys; print('score=10'); print('note', file=sys.stderr)"
    )

    result = run_evaluation(
        EvaluationRequest(
            harness_path=harness_path,
            evaluation_command=command,
            timeout_seconds=5,
        )
    )

    assert result.evaluation_command == command
    assert result.exit_code == 0
    assert result.stdout == "score=10\n"
    assert result.stderr == "note\n"
    assert result.timed_out is False
    assert result.manual_required is False
    assert result.succeeded is True
    assert result.elapsed_seconds >= 0


def test_run_evaluation_captures_failing_command(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    command = _python_command(
        "import sys; print('bad score'); print('failed', file=sys.stderr); "
        "raise SystemExit(7)"
    )

    result = run_evaluation(
        EvaluationRequest(
            harness_path=harness_path,
            evaluation_command=command,
        )
    )

    assert result.exit_code == 7
    assert result.stdout == "bad score\n"
    assert result.stderr == "failed\n"
    assert result.succeeded is False

    formatted = format_evaluation_result(result)

    assert "- Exit code: 7" in formatted
    assert "- Succeeded: no" in formatted
    assert "bad score" in formatted
    assert "failed" in formatted


def test_run_evaluation_captures_timeout(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    command = _python_command("import time; time.sleep(2)")

    result = run_evaluation(
        EvaluationRequest(
            harness_path=harness_path,
            evaluation_command=command,
            timeout_seconds=1,
        )
    )

    assert result.exit_code is None
    assert result.timed_out is True
    assert result.succeeded is False
    assert result.elapsed_seconds >= 1

    formatted = format_evaluation_result(result)

    assert "- Timed out: yes" in formatted
    assert "- Exit code: not available" in formatted


def test_run_evaluation_timeout_kills_child_processes(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    sentinel_path = harness_path / "survived.txt"
    child_code = (
        "import time; "
        "from pathlib import Path; "
        "time.sleep(2); "
        "Path('survived.txt').write_text('alive\\n', encoding='utf-8')"
    )
    parent_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print('child started', flush=True); "
        "time.sleep(5)"
    )

    result = run_evaluation(
        EvaluationRequest(
            harness_path=harness_path,
            evaluation_command=_python_command(parent_code),
            timeout_seconds=1,
        )
    )
    time.sleep(2.5)

    assert result.timed_out is True
    assert "child started" in result.stdout
    assert not sentinel_path.exists()


def test_run_evaluation_records_manual_mode(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    result = run_evaluation(
        EvaluationRequest(
            harness_path=harness_path,
            evaluation_command=None,
        )
    )

    assert result.evaluation_command is None
    assert result.exit_code is None
    assert result.manual_required is True
    assert result.succeeded is False

    formatted = format_evaluation_result(result)

    assert "- Mode: manual" in formatted
    assert "- Manual evaluation required: yes" in formatted
    assert "No evaluation command was configured" in formatted


def test_requires_manual_evaluation_uses_missing_command(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    assert requires_manual_evaluation(
        OptimizerConfig(harness_path=harness_path, goal="Improve the score.")
    )
    assert not requires_manual_evaluation(
        OptimizerConfig(
            harness_path=harness_path,
            goal="Improve the score.",
            evaluation_command="python evaluate.py",
        )
    )


def test_run_evaluation_captures_configured_output_files(
    tmp_path: Path,
) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    command = _python_command(
        "from pathlib import Path; "
        "Path('metrics.txt').write_text('score=12\\n', encoding='utf-8')"
    )

    result = run_evaluation(
        EvaluationRequest(
            harness_path=harness_path,
            evaluation_command=command,
            output_paths=(Path("metrics.txt"), Path("missing.txt")),
        )
    )

    assert result.output_files == {
        Path("metrics.txt"): "score=12\n",
        Path("missing.txt"): "(missing)",
    }

    formatted = format_evaluation_result(result)

    assert "### `metrics.txt`" in formatted
    assert "score=12" in formatted
    assert "### `missing.txt`" in formatted
    assert "(missing)" in formatted


def test_run_evaluation_rejects_empty_command(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    with pytest.raises(EvaluationError, match="must not be empty"):
        run_evaluation(
            EvaluationRequest(
                harness_path=harness_path,
                evaluation_command=" ",
            )
        )


def test_run_evaluation_rejects_output_path_escape(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")

    with pytest.raises(EvaluationError, match="inside the harness"):
        run_evaluation(
            EvaluationRequest(
                harness_path=harness_path,
                evaluation_command="echo ok",
                output_paths=(Path("../outside.txt"),),
            )
        )


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    return path


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
