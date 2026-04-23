"""Backend adapter registry."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from ralph_loop_optimizer.backends.base import (
    BackendRequest,
    BackendResult,
    CodingBackend,
)
from ralph_loop_optimizer.backends.claude import ClaudeCodeBackend
from ralph_loop_optimizer.backends.codex import CodexBackend
from ralph_loop_optimizer.git import commit, get_status, stage_paths


class BackendError(ValueError):
    """Raised when a backend name cannot be resolved."""


@dataclass(frozen=True)
class FakeBackend:
    name: str = "fake"

    def run_backend(self, request: BackendRequest) -> BackendResult:
        started_at = perf_counter()
        if request.phase == "lesson_update":
            return self._run_lesson_update(request, started_at)

        stdout = "\n".join(
            [
                "Fake backend completed without modifying the harness.",
                f"Phase: {request.phase}",
                f"Prompt characters: {len(request.prompt)}",
                f"Operating brief characters: {len(request.operating_brief)}",
                f"Harness instruction files: {len(request.harness_instructions)}",
                f"Prior lessons: {len(request.prior_lessons)}",
                "Latest evaluation provided: "
                f"{'yes' if request.latest_evaluation is not None else 'no'}",
                "",
            ]
        )
        return BackendResult(
            backend_name=self.name,
            exit_code=0,
            stdout=stdout,
            stderr="",
            elapsed_seconds=perf_counter() - started_at,
            transcript_path=None,
        )

    def _run_lesson_update(
        self,
        request: BackendRequest,
        started_at: float,
    ) -> BackendResult:
        lesson_path = _extract_lesson_path(request)
        if lesson_path is not None:
            lesson_path.write_text(_fake_lesson_text(request), encoding="utf-8")

        stage_paths(request.harness_path, [Path(".")])
        if get_status(request.harness_path).is_dirty:
            commit(
                request.harness_path,
                _extract_commit_message(request),
            )

        stdout = "\n".join(
            [
                "Fake backend completed lesson update and final commit.",
                f"Phase: {request.phase}",
                f"Prompt characters: {len(request.prompt)}",
                f"Prior lessons: {len(request.prior_lessons)}",
                "",
            ]
        )
        return BackendResult(
            backend_name=self.name,
            exit_code=0,
            stdout=stdout,
            stderr="",
            elapsed_seconds=perf_counter() - started_at,
            transcript_path=None,
        )


def _extract_lesson_path(request: BackendRequest) -> Path | None:
    match = re.search(r"^- Lesson artifact: `([^`]+)`$", request.prompt, re.MULTILINE)
    if match is None:
        return None

    path = Path(match.group(1))
    if path.is_absolute():
        candidate = path
    else:
        candidate = request.harness_path / path
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(request.harness_path.resolve())
    except ValueError:
        return None
    return resolved


def _extract_commit_message(request: BackendRequest) -> str:
    match = re.search(r"^- Commit message: `([^`]+)`$", request.prompt, re.MULTILINE)
    if match is None:
        return "ralph-loop iteration"
    return match.group(1)


def _fake_lesson_text(request: BackendRequest) -> str:
    prior = (
        "Prior lessons were provided and should continue to guide the next change."
        if request.prior_lessons
        else "No prior lessons were available for this iteration."
    )
    current_evaluation = _prompt_section(request.prompt, "Current Evaluation")
    evaluation = (
        "Evaluation succeeded; compare the metric output against prior runs."
        if "- Succeeded: yes" in current_evaluation
        else "Evaluation did not succeed; inspect evaluation output before "
        "building on this change."
    )
    return "\n".join(
        [
            "# Iteration Lesson",
            "",
            "- Fake backend recorded the post-evaluation lesson update.",
            f"- {prior}",
            f"- {evaluation}",
            "- Compare the committed diff and evaluation output before choosing "
            "the next experiment.",
            "",
        ]
    )


def _prompt_section(prompt: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)",
        prompt,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return ""
    return match.group(1)


_BACKENDS: dict[str, CodingBackend] = {
    "claude": ClaudeCodeBackend(),
    "codex": CodexBackend(),
    "fake": FakeBackend(),
}


def get_backend(name: str) -> CodingBackend:
    try:
        return _BACKENDS[name]
    except KeyError as exc:
        supported = ", ".join(list_backends())
        raise BackendError(
            f"unknown backend {name!r}; available backends: {supported}"
        ) from exc


def list_backends() -> list[str]:
    return sorted(_BACKENDS)
