from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from ralph_loop_optimizer.backends import (
    BackendError,
    BackendRequest,
    BackendResult,
    get_backend,
    list_backends,
    run_backend,
)
from ralph_loop_optimizer.backends.claude import (
    ClaudeCodeBackend,
    build_claude_command,
)
from ralph_loop_optimizer.backends.codex import CodexBackend, build_codex_command


def test_list_backends_includes_supported_backends() -> None:
    assert list_backends() == ["claude", "codex", "fake"]


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


def test_build_codex_command_uses_noninteractive_exec(tmp_path: Path) -> None:
    request = BackendRequest(harness_path=tmp_path, prompt="Try one change.")

    assert build_codex_command(request) == [
        "codex",
        "exec",
        "--cd",
        str(tmp_path),
        "--full-auto",
        "--color",
        "never",
        "-",
    ]


def test_build_codex_command_uses_json_events_when_streaming(tmp_path: Path) -> None:
    request = BackendRequest(
        harness_path=tmp_path,
        prompt="Try one change.",
        stream_output=True,
    )

    assert build_codex_command(request) == [
        "codex",
        "exec",
        "--cd",
        str(tmp_path),
        "--full-auto",
        "--color",
        "never",
        "--json",
        "-",
    ]


def test_build_claude_command_uses_print_mode(tmp_path: Path) -> None:
    request = BackendRequest(harness_path=tmp_path, prompt="Try one change.")

    assert build_claude_command(request) == [
        "claude",
        "--print",
        "--permission-mode",
        "acceptEdits",
        "--input-format",
        "text",
        "--output-format",
        "text",
    ]


def test_build_claude_command_uses_stream_json_when_streaming(
    tmp_path: Path,
) -> None:
    request = BackendRequest(
        harness_path=tmp_path,
        prompt="Try one change.",
        stream_output=True,
    )

    assert build_claude_command(request) == [
        "claude",
        "--print",
        "--permission-mode",
        "acceptEdits",
        "--input-format",
        "text",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--include-hook-events",
    ]


def test_codex_backend_runs_cli_with_prompt_on_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_path = tmp_path / "harness"
    harness_path.mkdir()
    _write_fake_cli(tmp_path / "bin" / "codex", "codex")
    monkeypatch.setenv(
        "PATH",
        f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    )

    result = CodexBackend().run_backend(
        BackendRequest(harness_path=harness_path, prompt="Improve the score.")
    )

    assert result.backend_name == "codex"
    assert result.exit_code == 0
    assert result.succeeded is True
    assert "codex cwd=" in result.stdout
    assert "codex args=exec --cd" in result.stdout
    assert (harness_path / "codex-prompt.txt").read_text(
        encoding="utf-8"
    ) == "Improve the score."


def test_claude_backend_runs_cli_with_prompt_on_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_path = tmp_path / "harness"
    harness_path.mkdir()
    _write_fake_cli(tmp_path / "bin" / "claude", "claude")
    monkeypatch.setenv(
        "PATH",
        f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    )

    result = ClaudeCodeBackend().run_backend(
        BackendRequest(harness_path=harness_path, prompt="Improve the score.")
    )

    assert result.backend_name == "claude"
    assert result.exit_code == 0
    assert result.succeeded is True
    assert "claude cwd=" in result.stdout
    assert "claude args=--print --permission-mode acceptEdits" in result.stdout
    assert (harness_path / "claude-prompt.txt").read_text(
        encoding="utf-8"
    ) == "Improve the score."


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


def _write_fake_cli(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "from pathlib import Path",
                "import sys",
                "prompt = sys.stdin.read()",
                f"Path('{name}-prompt.txt').write_text(prompt, encoding='utf-8')",
                f"print('{name} cwd=' + str(Path.cwd()))",
                f"print('{name} args=' + ' '.join(sys.argv[1:]))",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)
