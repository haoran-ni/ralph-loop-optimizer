"""Terminal progress reporting for interactive CLI runs."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TextIO


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
PURPLE = "\033[38;2;106;0;255m"


class TerminalStyle:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def apply(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text
        return "".join(styles) + text + RESET


class ProgressReporter:
    def __init__(
        self,
        *,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        color: bool | None = None,
    ) -> None:
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.stdout_style = TerminalStyle(_should_use_color(self.stdout, color))
        self.stderr_style = TerminalStyle(_should_use_color(self.stderr, color))

    def status(self, message: str) -> None:
        prefix = self.stdout_style.apply("[ralph-loop]", BOLD, BLUE)
        print(f"{prefix} {message}", file=self.stdout, flush=True)

    def block(self, title: str, content: str) -> None:
        print("", file=self.stdout, flush=True)
        prefix = self.stdout_style.apply("[ralph-loop]", BOLD, BLUE)
        print(
            f"{prefix} {self.stdout_style.apply(title, BOLD)}",
            file=self.stdout,
            flush=True,
        )
        print("---", file=self.stdout, flush=True)
        if content:
            print(content.rstrip(), file=self.stdout, flush=True)
        else:
            print("(empty)", file=self.stdout, flush=True)
        print("---", file=self.stdout, flush=True)

    def stdout_chunk(self, prefix: str, chunk: str) -> None:
        self._write_chunk(self.stdout, self.stdout_style, prefix, chunk)

    def stderr_chunk(self, prefix: str, chunk: str) -> None:
        self._write_chunk(self.stderr, self.stderr_style, prefix, chunk, RED)

    def agent_event(self, message: str) -> None:
        kind = _agent_event_kind(message)
        label, label_styles, message_styles = _agent_event_style(kind)
        styled_label = self.stdout_style.apply(label, *label_styles)
        styled_message = self.stdout_style.apply(message, *message_styles)
        print(f"{styled_label} {styled_message}", file=self.stdout, flush=True)

    def backend_stdout_callback(self, backend_name: str):
        formatter = BackendEventFormatter(backend_name)

        def callback(chunk: str) -> None:
            for line in formatter.format_chunk(chunk):
                self.agent_event(line)

        return callback

    def backend_stderr_callback(self, backend_name: str):
        def callback(chunk: str) -> None:
            self.stderr_chunk(f"{backend_name} stderr", chunk)

        return callback

    def evaluation_stdout_callback(self):
        def callback(chunk: str) -> None:
            self.stdout_chunk("evaluation", chunk)

        return callback

    def evaluation_stderr_callback(self):
        def callback(chunk: str) -> None:
            self.stderr_chunk("evaluation stderr", chunk)

        return callback

    def _write_chunk(
        self,
        stream: TextIO,
        style: TerminalStyle,
        prefix: str,
        chunk: str,
        *message_styles: str,
    ) -> None:
        styled_prefix = style.apply(f"[{prefix}]", *message_styles)
        for line in chunk.splitlines(keepends=True):
            if line.endswith("\n"):
                text = style.apply(line[:-1], *message_styles)
            else:
                text = style.apply(line, *message_styles)
            print(f"{styled_prefix} {text}", file=stream, flush=True)


def _should_use_color(stream: TextIO, color: bool | None) -> bool:
    if color is not None:
        return color
    if os.environ.get("NO_COLOR") is not None:
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _agent_event_kind(message: str) -> str:
    if " error:" in message or message.endswith(" error"):
        return "error"
    if message.startswith("codex file change"):
        return "file_change"
    if message.startswith("codex: ") or message.startswith("claude: "):
        return "assistant"
    if " action " in message or " action:" in message:
        return "action"
    if " tool result" in message:
        return "action"
    if " is thinking" in message or " is working" in message:
        return "thinking"
    if " session started" in message or " turn completed" in message:
        return "thinking"
    return "event"


def _agent_event_style(kind: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    if kind == "assistant":
        return "[agent]", (BOLD, GREEN), (BOLD, GREEN)
    if kind == "action":
        return "[agent action]", (DIM,), (DIM,)
    if kind == "file_change":
        return "[file change]", (BOLD, YELLOW), ()
    if kind == "thinking":
        return "[agent status]", (DIM,), (DIM,)
    if kind == "error":
        return "[agent error]", (BOLD, RED), (BOLD, RED)
    return "[agent event]", (BOLD, PURPLE), ()


class BackendEventFormatter:
    def __init__(self, backend_name: str) -> None:
        self.backend_name = backend_name
        self._show_next_git_diff = False
        self._active_git_diff_commands: set[str] = set()

    def format_chunk(self, chunk: str) -> list[str]:
        lines: list[str] = []
        for raw_line in chunk.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            event = _parse_json_object(line)
            if event is None:
                lines.append(f"{self.backend_name}: {line}")
                continue
            lines.extend(self._format_event(event))
        return lines

    def _format_event(self, event: dict[str, object]) -> list[str]:
        if self.backend_name == "claude":
            formatted = self._format_claude_event(event)
        elif self.backend_name == "codex":
            formatted = self._format_codex_event(event)
        else:
            formatted = []
        if formatted:
            return formatted

        event_type = _string_value(event, "type") or _string_value(event, "event")
        text = _first_text(event, ("text", "message", "content", "result"))
        if text:
            label = event_type or "event"
            return [f"{self.backend_name} {label}: {text}"]
        if event_type:
            return [f"{self.backend_name} event: {event_type}"]
        return [f"{self.backend_name} event: {json.dumps(event, sort_keys=True)}"]

    def _format_claude_event(self, event: dict[str, object]) -> list[str]:
        event_type = _string_value(event, "type")
        if event_type == "system":
            subtype = _string_value(event, "subtype")
            return [f"claude session started{subtype and f' ({subtype})' or ''}"]
        if event_type == "assistant":
            message = event.get("message")
            if not isinstance(message, dict):
                return ["claude assistant message"]
            return _format_claude_content(message.get("content"))
        if event_type == "user":
            message = event.get("message")
            if isinstance(message, dict):
                content_lines = _format_claude_content(message.get("content"))
                if content_lines:
                    return [f"claude tool/user event: {line}" for line in content_lines]
            return ["claude tool/user event"]
        if event_type == "result":
            result = _string_value(event, "result")
            subtype = _string_value(event, "subtype")
            duration_ms = event.get("duration_ms")
            parts = ["claude result"]
            if subtype:
                parts.append(f"({subtype})")
            if duration_ms is not None:
                parts.append(f"in {duration_ms} ms")
            if result:
                parts.append(f": {result}")
            return [" ".join(parts)]
        return []

    def _format_codex_event(self, event: dict[str, object]) -> list[str]:
        event_type = _string_value(event, "type")
        if event_type in {"thread.started", "session.started"}:
            return ["codex session started"]
        if event_type == "turn.started":
            return ["codex is working"]
        if event_type == "turn.completed":
            return ["codex turn completed"]
        if event_type == "error":
            message = _first_text(event, ("message", "error"))
            return [f"codex error: {message or 'unknown error'}"]

        item = event.get("item")
        if not isinstance(item, dict):
            return []
        item_type = _string_value(item, "type") or event_type
        if event_type == "item.started":
            if item_type == "file_change":
                self._show_next_git_diff = True
                return ["codex file change"]
            if item_type in {"reasoning", "thinking"}:
                return ["codex is thinking"]
            command = _command_text(item)
            if item_type in {"command_execution", "tool_call"} or command is not None:
                if command is not None and self._should_show_git_diff(command):
                    self._active_git_diff_commands.add(command)
                return [f"codex action started: {command or item_type}"]
            return [f"codex item started: {item_type}"]
        if event_type == "item.completed":
            text = _output_text(item)
            if item_type in {"assistant_message", "message"} and text:
                return [f"codex: {text}"]
            if item_type == "file_change":
                diff_text = _first_text(
                    item,
                    (
                        "diff",
                        "patch",
                        "text",
                        "message",
                        "content",
                        "summary",
                        "aggregated_output",
                    ),
                )
                if diff_text:
                    self._show_next_git_diff = False
                    return [f"codex file change:\n{diff_text}"]
                self._show_next_git_diff = True
                return ["codex file change"]
            command = _command_text(item)
            if item_type in {"command_execution", "tool_call"} or command is not None:
                exit_code = item.get("exit_code")
                suffix = f" (exit {exit_code})" if exit_code is not None else ""
                lines = [f"codex action completed: {command or item_type}{suffix}"]
                show_diff = self._consume_active_git_diff(command)
                if show_diff and text:
                    lines.append(f"codex file change:\n{text}")
                return lines
            if text:
                return [f"codex {item_type}: {text}"]
            return [f"codex item completed: {item_type}"]
        return []

    def _should_show_git_diff(self, command: str | None) -> bool:
        if not self._show_next_git_diff:
            return False
        if command is None or not _is_git_diff_command(command):
            return False
        self._show_next_git_diff = False
        return True

    def _consume_active_git_diff(self, command: str | None) -> bool:
        if command is not None and command in self._active_git_diff_commands:
            self._active_git_diff_commands.remove(command)
            return True
        if command is not None and self._should_show_git_diff(command):
            return True
        if command is None and len(self._active_git_diff_commands) == 1:
            self._active_git_diff_commands.clear()
            return True
        return False


def relative_path(path: Path, repo_path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_path.resolve()).as_posix()
    except ValueError:
        return str(path)


def _parse_json_object(line: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _is_git_diff_command(command: str) -> bool:
    normalized = " ".join(command.strip().split())
    if "git diff" in normalized:
        return True

    parts = normalized.split()
    if len(parts) < 2:
        return False
    for index, part in enumerate(parts[:-1]):
        if part == "git" or part.endswith("/git"):
            return "diff" in parts[index + 1 :]
    return False


def _command_text(item: dict[str, object]) -> str | None:
    for key in ("command", "cmd"):
        if key in item:
            command = _text_from_command_value(item[key])
            if command:
                return command
    return None


def _output_text(item: dict[str, object]) -> str | None:
    return _first_text(
        item,
        (
            "aggregated_output",
            "output",
            "stdout",
            "stderr",
            "text",
            "message",
            "content",
            "summary",
            "result",
        ),
    )


def _text_from_command_value(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = [_text_from_command_value(item) for item in value]
        joined = " ".join(part for part in parts if part)
        return joined or None
    if isinstance(value, dict):
        args = value.get("args")
        if args is not None:
            program = _text_from_command_value(
                value.get("program")
                or value.get("name")
                or value.get("command")
                or value.get("cmd")
            )
            arg_text = _text_from_command_value(args)
            joined = " ".join(part for part in (program, arg_text) if part)
            return joined or None
        command = _command_text(value)
        if command:
            return command
    return None


def _format_claude_content(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []

    lines: list[str] = []
    for block in content:
        if isinstance(block, str):
            lines.append(block)
            continue
        if not isinstance(block, dict):
            continue
        block_type = _string_value(block, "type")
        if block_type == "text":
            text = _string_value(block, "text")
            if text:
                lines.append(f"claude: {text}")
        elif block_type == "tool_use":
            name = _string_value(block, "name") or "tool"
            lines.append(f"claude action: {name}")
        elif block_type == "tool_result":
            lines.append("claude tool result")
        elif block_type:
            lines.append(f"claude content: {block_type}")
    return lines


def _string_value(mapping: dict[str, object], key: str) -> str | None:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return None


def _first_text(value: object, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            nested = value.get(key)
            text = _text_from_value(nested)
            if text:
                return text
        return None
    return _text_from_value(value)


def _text_from_value(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = [_text_from_value(item) for item in value]
        joined = "\n".join(part for part in parts if part)
        return joined or None
    if isinstance(value, dict):
        return _first_text(value, ("text", "content", "message", "result"))
    return None
