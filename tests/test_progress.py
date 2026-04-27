from __future__ import annotations

from io import StringIO
import json

from ralph_loop_optimizer.progress import BackendEventFormatter, ProgressReporter


def test_codex_formatter_suppresses_action_output() -> None:
    event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "python evaluate.py",
            "exit_code": 0,
            "aggregated_output": "long command output\nscore=10",
        },
    }

    lines = BackendEventFormatter("codex").format_chunk(json.dumps(event) + "\n")

    assert lines == ["codex action completed: python evaluate.py (exit 0)"]
    assert "score=10" not in "\n".join(lines)


def test_codex_formatter_keeps_file_change_output() -> None:
    event = {
        "type": "item.completed",
        "item": {
            "type": "file_change",
            "diff": "diff --git a/model.py b/model.py\n+WIDTH = 64",
        },
    }

    lines = BackendEventFormatter("codex").format_chunk(json.dumps(event) + "\n")

    assert lines == [
        "codex file change:\ndiff --git a/model.py b/model.py\n+WIDTH = 64"
    ]


def test_codex_formatter_keeps_git_diff_output_after_file_change() -> None:
    formatter = BackendEventFormatter("codex")
    file_change_event = {
        "type": "item.completed",
        "item": {
            "type": "file_change",
        },
    }
    git_diff_event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "git diff -- model.py",
            "exit_code": 0,
            "aggregated_output": "diff --git a/model.py b/model.py\n+WIDTH = 64",
        },
    }

    assert formatter.format_chunk(json.dumps(file_change_event) + "\n") == [
        "codex file change"
    ]
    lines = formatter.format_chunk(json.dumps(git_diff_event) + "\n")

    assert lines == [
        "codex action completed: git diff -- model.py (exit 0)",
        "codex file change:\ndiff --git a/model.py b/model.py\n+WIDTH = 64",
    ]


def test_codex_formatter_keeps_shell_wrapped_git_diff_after_file_change_started() -> None:
    formatter = BackendEventFormatter("codex")
    file_change_started = {
        "type": "item.started",
        "item": {
            "type": "file_change",
        },
    }
    status_started = {
        "type": "item.started",
        "item": {
            "type": "command_execution",
            "command": "/bin/zsh -lc 'git status --short'",
        },
    }
    diff_started = {
        "type": "item.started",
        "item": {
            "type": "command_execution",
            "command": "/bin/zsh -lc 'git diff -- model.py train_config.py'",
        },
    }
    status_completed = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "/bin/zsh -lc 'git status --short'",
            "exit_code": 0,
            "output": " M model.py",
        },
    }
    diff_completed = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "/bin/zsh -lc 'git diff -- model.py train_config.py'",
            "exit_code": 0,
            "output": "diff --git a/model.py b/model.py\n+WIDTH = 64",
        },
    }

    assert formatter.format_chunk(json.dumps(file_change_started) + "\n") == [
        "codex file change"
    ]
    assert formatter.format_chunk(json.dumps(status_started) + "\n") == [
        "codex action started: /bin/zsh -lc 'git status --short'"
    ]
    assert formatter.format_chunk(json.dumps(diff_started) + "\n") == [
        "codex action started: /bin/zsh -lc 'git diff -- model.py train_config.py'"
    ]
    assert formatter.format_chunk(json.dumps(status_completed) + "\n") == [
        "codex action completed: /bin/zsh -lc 'git status --short' (exit 0)"
    ]
    assert formatter.format_chunk(json.dumps(diff_completed) + "\n") == [
        "codex action completed: "
        "/bin/zsh -lc 'git diff -- model.py train_config.py' (exit 0)",
        "codex file change:\ndiff --git a/model.py b/model.py\n+WIDTH = 64",
    ]


def test_codex_formatter_suppresses_non_diff_output_after_file_change() -> None:
    formatter = BackendEventFormatter("codex")
    file_change_event = {
        "type": "item.completed",
        "item": {
            "type": "file_change",
        },
    }
    command_event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "python evaluate.py",
            "exit_code": 0,
            "aggregated_output": "score=10",
        },
    }

    formatter.format_chunk(json.dumps(file_change_event) + "\n")
    lines = formatter.format_chunk(json.dumps(command_event) + "\n")

    assert lines == ["codex action completed: python evaluate.py (exit 0)"]
    assert "score=10" not in "\n".join(lines)


def test_claude_formatter_suppresses_tool_result_content() -> None:
    event = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "content": "long command output\nscore=10",
                }
            ]
        },
    }

    lines = BackendEventFormatter("claude").format_chunk(json.dumps(event) + "\n")

    assert lines == ["claude action completed"]
    assert "score=10" not in "\n".join(lines)


def test_formatter_keeps_assistant_text() -> None:
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "text",
                    "text": "I updated the training configuration.",
                }
            ]
        },
    }

    lines = BackendEventFormatter("claude").format_chunk(json.dumps(event) + "\n")

    assert lines == ["claude: I updated the training configuration."]


def test_claude_formatter_summarizes_assistant_tool_use() -> None:
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Read",
                    "input": {
                        "file_path": (
                            "/Users/haoran/Desktop/haoran_git_repos/"
                            "us-stock-strategy/strategy.py"
                        ),
                    },
                },
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {
                        "command": "python3 << 'PYEOF'\nprint('long script')\nPYEOF",
                        "description": "Analyze drawdown events for passive tickers",
                    },
                },
            ]
        },
    }

    lines = BackendEventFormatter("claude").format_chunk(json.dumps(event) + "\n")

    assert lines == [
        "claude action: Read strategy.py",
        "claude action: Bash: Analyze drawdown events for passive tickers",
    ]


def test_claude_formatter_buffers_stream_tool_use_until_stop() -> None:
    formatter = BackendEventFormatter("claude")
    start_event = {
        "type": "stream_event",
        "event": {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "name": "Read",
                "input": {},
            },
        },
    }
    first_delta = {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "index": 1,
            "delta": {
                "type": "input_json_delta",
                "partial_json": '{"file_path": "/tmp/harness/',
            },
        },
    }
    second_delta = {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "index": 1,
            "delta": {
                "type": "input_json_delta",
                "partial_json": 'strategy.py"}',
            },
        },
    }
    stop_event = {
        "type": "stream_event",
        "event": {
            "type": "content_block_stop",
            "index": 1,
        },
    }

    assert formatter.format_chunk(json.dumps(start_event) + "\n") == []
    assert formatter.format_chunk(json.dumps(first_delta) + "\n") == []
    assert formatter.format_chunk(json.dumps(second_delta) + "\n") == []

    lines = formatter.format_chunk(json.dumps(stop_event) + "\n")

    assert lines == ["claude action: Read strategy.py"]


def test_claude_formatter_suppresses_stream_protocol_metadata() -> None:
    event = {
        "type": "stream_event",
        "event": {
            "type": "message_delta",
            "delta": {
                "stop_reason": "end_turn",
                "stop_sequence": None,
            },
            "usage": {
                "output_tokens": 12,
            },
        },
    }

    lines = BackendEventFormatter("claude").format_chunk(json.dumps(event) + "\n")

    assert lines == []


def test_claude_formatter_collapses_thinking_deltas_to_status() -> None:
    formatter = BackendEventFormatter("claude")
    thinking_start = {
        "type": "stream_event",
        "event": {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "thinking",
                "thinking": "",
                "signature": "",
            },
        },
    }
    thinking_delta = {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "index": 0,
            "delta": {
                "type": "thinking_delta",
                "thinking": "hidden analysis",
            },
        },
    }

    assert formatter.format_chunk(json.dumps(thinking_start) + "\n") == [
        "claude is thinking"
    ]
    assert formatter.format_chunk(json.dumps(thinking_delta) + "\n") == []


def test_progress_reporter_keeps_plain_output_when_color_disabled() -> None:
    stdout = StringIO()
    reporter = ProgressReporter(stdout=stdout, color=False)

    reporter.status("Starting optimization run")
    reporter.agent_event("claude: I updated the training configuration.")
    reporter.agent_event("claude action: Edit")

    output = stdout.getvalue()
    assert "\033[" not in output
    assert "[ralph-loop] Starting optimization run" in output
    assert "[agent] claude: I updated the training configuration." in output
    assert "[agent action] claude action: Edit" in output


def test_progress_reporter_styles_message_types_when_color_forced() -> None:
    stdout = StringIO()
    reporter = ProgressReporter(stdout=stdout, color=True)

    reporter.status("Starting optimization run")
    reporter.agent_event("claude: I updated the training configuration.")
    reporter.agent_event("claude action: Edit")
    reporter.agent_event("codex is thinking")
    reporter.agent_event("codex file change:\ndiff --git a/model.py b/model.py")

    output = stdout.getvalue()
    assert "\033[1m\033[34m[ralph-loop]\033[0m Starting optimization run" in output
    assert "\033[1m\033[32m[agent]\033[0m" in output
    assert "\033[2m[agent action]\033[0m" in output
    assert "\033[2m[agent status]\033[0m" in output
    assert "\033[1m\033[33m[file change]\033[0m codex file change:" in output


def test_progress_reporter_styles_agent_event_label_only() -> None:
    stdout = StringIO()
    reporter = ProgressReporter(stdout=stdout, color=True)

    reporter.agent_event("codex event: unknown")

    output = stdout.getvalue()
    assert "\033[1m\033[38;2;106;0;255m[agent event]\033[0m" in output
    assert "[agent event]\033[0m codex event: unknown" in output
    assert "codex event: unknown\033[0m" not in output


def test_progress_reporter_respects_no_color_for_tty(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    stdout = TtyStringIO()
    reporter = ProgressReporter(stdout=stdout)

    reporter.status("Starting optimization run")

    output = stdout.getvalue()
    assert "\033[" not in output
    assert "[ralph-loop] Starting optimization run" in output


def test_progress_reporter_styles_stderr_when_color_forced() -> None:
    stderr = StringIO()
    reporter = ProgressReporter(stdout=StringIO(), stderr=stderr, color=True)

    reporter.stderr_chunk("evaluation stderr", "failed\n")

    output = stderr.getvalue()
    assert "\033[31m[evaluation stderr]\033[0m" in output
    assert "\033[31mfailed\033[0m" in output


class TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True
