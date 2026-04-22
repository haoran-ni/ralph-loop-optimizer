"""Terminal progress reporting for interactive CLI runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO


class ProgressReporter:
    def __init__(
        self,
        *,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr

    def status(self, message: str) -> None:
        print(f"[ralph-loop] {message}", file=self.stdout, flush=True)

    def block(self, title: str, content: str) -> None:
        print("", file=self.stdout, flush=True)
        print(f"[ralph-loop] {title}", file=self.stdout, flush=True)
        print("---", file=self.stdout, flush=True)
        if content:
            print(content.rstrip(), file=self.stdout, flush=True)
        else:
            print("(empty)", file=self.stdout, flush=True)
        print("---", file=self.stdout, flush=True)

    def stdout_chunk(self, prefix: str, chunk: str) -> None:
        self._write_chunk(self.stdout, prefix, chunk)

    def stderr_chunk(self, prefix: str, chunk: str) -> None:
        self._write_chunk(self.stderr, prefix, chunk)

    def backend_stdout_callback(self, backend_name: str):
        formatter = BackendEventFormatter(backend_name)

        def callback(chunk: str) -> None:
            for line in formatter.format_chunk(chunk):
                self.status(line)

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

    def _write_chunk(self, stream: TextIO, prefix: str, chunk: str) -> None:
        for line in chunk.splitlines(keepends=True):
            if line.endswith("\n"):
                print(f"[{prefix}] {line[:-1]}", file=stream, flush=True)
            else:
                print(f"[{prefix}] {line}", file=stream, flush=True)


class BackendEventFormatter:
    def __init__(self, backend_name: str) -> None:
        self.backend_name = backend_name

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
            if item_type in {"reasoning", "thinking"}:
                return ["codex is thinking"]
            if item_type in {"command_execution", "tool_call"}:
                command = _first_text(item, ("command", "cmd"))
                return [f"codex action started: {command or item_type}"]
            return [f"codex item started: {item_type}"]
        if event_type == "item.completed":
            text = _first_text(
                item,
                ("text", "message", "content", "summary", "aggregated_output"),
            )
            if item_type in {"assistant_message", "message"} and text:
                return [f"codex: {text}"]
            if item_type in {"command_execution", "tool_call"}:
                command = _first_text(item, ("command", "cmd"))
                exit_code = item.get("exit_code")
                suffix = f" (exit {exit_code})" if exit_code is not None else ""
                if text:
                    return [
                        f"codex action completed: {command or item_type}{suffix}",
                        f"codex action output: {text}",
                    ]
                return [f"codex action completed: {command or item_type}{suffix}"]
            if text:
                return [f"codex {item_type}: {text}"]
            return [f"codex item completed: {item_type}"]
        return []


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
            text = _first_text(block, ("content", "text"))
            if text:
                lines.append(f"claude tool result: {text}")
            else:
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
