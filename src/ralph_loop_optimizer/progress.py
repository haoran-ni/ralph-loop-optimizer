"""Terminal progress reporting for interactive CLI runs."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
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
    if message.startswith("claude is rate limited"):
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
        self._claude_stream_blocks: dict[int | str, _ClaudeStreamBlock] = {}
        self._claude_seen_system_events: set[str] = set()
        self._claude_seen_status_lines: set[str] = set()
        self._claude_seen_action_lines: set[str] = set()
        self._claude_seen_text_lines: set[str] = set()

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
            if formatted is not None:
                return formatted
        elif self.backend_name == "codex":
            formatted = self._format_codex_event(event)
            if formatted:
                return formatted
        else:
            formatted = []

        event_type = _string_value(event, "type") or _string_value(event, "event")
        text = _first_text(event, ("text", "message", "content", "result"))
        if text:
            label = event_type or "event"
            return [f"{self.backend_name} {label}: {text}"]
        if event_type:
            return [f"{self.backend_name} event: {event_type}"]
        return [f"{self.backend_name} event: {json.dumps(event, sort_keys=True)}"]

    def _format_claude_event(self, event: dict[str, object]) -> list[str] | None:
        event_type = _string_value(event, "type")
        if event_type == "system":
            subtype = _string_value(event, "subtype")
            system_key = subtype or "system"
            if system_key in self._claude_seen_system_events:
                return []
            self._claude_seen_system_events.add(system_key)
            return [f"claude session started{subtype and f' ({subtype})' or ''}"]
        if event_type == "rate_limit_event":
            return self._dedupe_claude_lines(["claude is rate limited; waiting"])
        if event_type == "assistant":
            message = event.get("message")
            if not isinstance(message, dict):
                return ["claude assistant message"]
            return self._dedupe_claude_lines(
                _format_claude_content(message.get("content"))
            )
        if event_type == "user":
            message = event.get("message")
            if isinstance(message, dict):
                content_lines = _format_claude_content(message.get("content"))
                if content_lines:
                    if all(line == "claude tool result" for line in content_lines):
                        return ["claude action completed"]
                    return [
                        f"claude tool/user event: {line}" for line in content_lines
                    ]
            return []
        if event_type == "stream_event":
            return self._format_claude_stream_event(event)
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
        return None

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

    def _format_claude_stream_event(self, event: dict[str, object]) -> list[str]:
        nested = _first_mapping(event, ("event", "stream_event", "data", "payload"))
        if nested is None:
            return []

        nested_type = _string_value(nested, "type") or _string_value(nested, "event")
        if nested_type == "rate_limit_event":
            return self._dedupe_claude_lines(["claude is rate limited; waiting"])
        if nested_type == "error":
            message = _first_text(nested, ("message", "error"))
            return [f"claude error: {message or 'unknown error'}"]
        if nested_type == "content_block_start":
            return self._start_claude_content_block(nested)
        if nested_type == "content_block_delta":
            return self._update_claude_content_block(nested)
        if nested_type == "content_block_stop":
            return self._stop_claude_content_block(nested)
        return []

    def _start_claude_content_block(self, event: dict[str, object]) -> list[str]:
        content_block = event.get("content_block")
        if not isinstance(content_block, dict):
            return []

        block_type = _string_value(content_block, "type")
        key = _claude_block_key(event, content_block)
        if key is not None:
            self._claude_stream_blocks[key] = _ClaudeStreamBlock(
                block_type=block_type,
                name=_string_value(content_block, "name"),
                input_value=content_block.get("input"),
                text_fragments=[
                    text
                    for text in (_string_value(content_block, "text"),)
                    if text
                ],
            )

        if block_type in {"thinking", "redacted_thinking"}:
            return self._dedupe_claude_lines(["claude is thinking"])
        return []

    def _update_claude_content_block(self, event: dict[str, object]) -> list[str]:
        key = _claude_block_key(event)
        block = self._claude_stream_blocks.get(key) if key is not None else None
        delta = event.get("delta")
        if not isinstance(delta, dict):
            return []

        delta_type = _string_value(delta, "type")
        if delta_type == "thinking_delta":
            return self._dedupe_claude_lines(["claude is thinking"])
        if block is None:
            return []
        if delta_type == "input_json_delta":
            fragment = _string_value(delta, "partial_json")
            if fragment:
                block.input_fragments.append(fragment)
        elif delta_type == "text_delta":
            text = _string_value(delta, "text")
            if text:
                block.text_fragments.append(text)
        return []

    def _stop_claude_content_block(self, event: dict[str, object]) -> list[str]:
        key = _claude_block_key(event)
        if key is None:
            return []
        block = self._claude_stream_blocks.pop(key, None)
        if block is None:
            return []
        if block.block_type in {"thinking", "redacted_thinking"}:
            return []
        if block.block_type == "tool_use":
            input_value = block.input_value
            if block.input_fragments:
                parsed = _parse_json_object("".join(block.input_fragments))
                if parsed is not None:
                    input_value = parsed
            return self._dedupe_claude_lines(
                [_format_claude_tool_action(block.name or "tool", input_value)]
            )
        text = "".join(block.text_fragments).strip()
        if text:
            return self._dedupe_claude_lines([f"claude: {text}"])
        return []

    def _dedupe_claude_lines(self, lines: list[str]) -> list[str]:
        deduped: list[str] = []
        for line in lines:
            if line.startswith("claude action:"):
                if line in self._claude_seen_action_lines:
                    continue
                self._claude_seen_action_lines.add(line)
            elif line.startswith("claude:"):
                if line in self._claude_seen_text_lines:
                    continue
                self._claude_seen_text_lines.add(line)
            elif line in {
                "claude is thinking",
                "claude is rate limited; waiting",
            }:
                if line in self._claude_seen_status_lines:
                    continue
                self._claude_seen_status_lines.add(line)
            deduped.append(line)
        return deduped


@dataclass
class _ClaudeStreamBlock:
    block_type: str | None
    name: str | None = None
    input_value: object = None
    input_fragments: list[str] = field(default_factory=list)
    text_fragments: list[str] = field(default_factory=list)


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
            input_value = block.get("input")
            lines.append(_format_claude_tool_action(name, input_value))
        elif block_type == "tool_result":
            lines.append("claude tool result")
        elif block_type in {"thinking", "redacted_thinking"}:
            lines.append("claude is thinking")
    return lines


def _format_claude_tool_action(name: str, input_value: object) -> str:
    label = f"claude action: {name}"
    if not isinstance(input_value, dict):
        return label

    if name == "Bash":
        description = _first_text(input_value, ("description",))
        if description:
            return f"{label}: {_one_line(description)}"
        command = _first_text(input_value, ("command",))
        if command:
            return f"{label}: {_one_line(command)}"
        return label

    if name in {"Read", "Write", "Edit", "MultiEdit"}:
        path = _first_text(input_value, ("file_path", "path"))
        if path:
            return f"{label} {_display_path(path)}"
        return label

    if name in {"Grep", "Glob"}:
        pattern = _first_text(input_value, ("pattern",))
        path = _first_text(input_value, ("path",))
        detail = " in ".join(
            part
            for part in (
                _one_line(pattern) if pattern else None,
                _display_path(path) if path else None,
            )
            if part
        )
        if detail:
            return f"{label}: {detail}"
        return label

    if name == "LS":
        path = _first_text(input_value, ("path",))
        if path:
            return f"{label} {_display_path(path)}"
        return label

    description = _first_text(input_value, ("description",))
    if description:
        return f"{label}: {_one_line(description)}"
    return label


def _display_path(path: str) -> str:
    text = path.strip()
    if not text:
        return text
    if text.startswith("/"):
        name = Path(text).name
        if name:
            return name
    return _one_line(text, limit=120)


def _one_line(text: str, *, limit: int = 160) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _claude_block_key(
    event: dict[str, object],
    content_block: dict[str, object] | None = None,
) -> int | str | None:
    index = event.get("index")
    if isinstance(index, int):
        return index
    if content_block is not None:
        block_id = _string_value(content_block, "id")
        if block_id:
            return block_id
    return None


def _first_mapping(
    mapping: dict[str, object],
    keys: tuple[str, ...],
) -> dict[str, object] | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, dict):
            return value
    return None


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
