"""Configuration model for optimizer orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ralph_loop_optimizer.backends.registry import list_backends
from ralph_loop_optimizer.harness import HarnessError, assert_git_repository


SUPPORTED_BACKENDS = tuple(list_backends())
RESUME_BEHAVIORS = ("refuse_dirty", "resume_existing")


class ConfigError(ValueError):
    """Raised when optimizer configuration is invalid."""


@dataclass(frozen=True)
class OptimizerConfig:
    harness_path: Path
    goal: str
    backend: str = "fake"
    max_iterations: int = 1
    evaluation_command: str | None = None
    run_artifact_dir: Path = Path("ralph_loop_runs")
    command_timeout_seconds: int | None = None
    resume_behavior: str = "refuse_dirty"


def load_config(path: Path) -> OptimizerConfig:
    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file is not valid JSON: {path}") from exc

    if not isinstance(raw_data, dict):
        raise ConfigError("config file must contain a JSON object")

    config = _config_from_mapping(raw_data)
    validate_config(config)
    return config


def write_config(config: OptimizerConfig, path: Path) -> None:
    validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_config_to_mapping(config), indent=2) + "\n",
        encoding="utf-8",
    )


def validate_config(config: OptimizerConfig) -> None:
    harness_path = config.harness_path.expanduser()
    if not harness_path.exists():
        raise ConfigError(f"harness_path does not exist: {harness_path}")
    if not harness_path.is_dir():
        raise ConfigError(f"harness_path must be a directory: {harness_path}")
    try:
        assert_git_repository(harness_path)
    except HarnessError as exc:
        raise ConfigError(str(exc)) from exc

    if not config.goal.strip():
        raise ConfigError("goal must not be empty")

    if config.backend not in SUPPORTED_BACKENDS:
        supported = ", ".join(SUPPORTED_BACKENDS)
        raise ConfigError(
            f"backend must be one of: {supported}; got {config.backend!r}"
        )

    if isinstance(config.max_iterations, bool) or not isinstance(
        config.max_iterations, int
    ):
        raise ConfigError("max_iterations must be an integer")
    if config.max_iterations < 1:
        raise ConfigError("max_iterations must be at least 1")

    if (
        config.evaluation_command is not None
        and not config.evaluation_command.strip()
    ):
        raise ConfigError("evaluation_command must not be empty when provided")

    if (
        config.command_timeout_seconds is not None
        and (
            isinstance(config.command_timeout_seconds, bool)
            or not isinstance(config.command_timeout_seconds, int)
        )
    ):
        raise ConfigError("command_timeout_seconds must be an integer when provided")

    if (
        config.command_timeout_seconds is not None
        and config.command_timeout_seconds < 1
    ):
        raise ConfigError("command_timeout_seconds must be at least 1 when provided")

    if config.resume_behavior not in RESUME_BEHAVIORS:
        supported = ", ".join(RESUME_BEHAVIORS)
        raise ConfigError(
            "resume_behavior must be one of: "
            f"{supported}; got {config.resume_behavior!r}"
        )

    if config.run_artifact_dir.is_absolute():
        raise ConfigError("run_artifact_dir must be relative to the harness")
    if config.run_artifact_dir == Path(".") or ".." in config.run_artifact_dir.parts:
        raise ConfigError("run_artifact_dir must stay inside the harness")


def _config_from_mapping(data: dict[str, Any]) -> OptimizerConfig:
    allowed_keys = {
        "harness_path",
        "goal",
        "backend",
        "max_iterations",
        "evaluation_command",
        "run_artifact_dir",
        "command_timeout_seconds",
        "resume_behavior",
    }
    unknown_keys = sorted(set(data) - allowed_keys)
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ConfigError(f"unknown config field(s): {joined}")

    try:
        harness_path = data["harness_path"]
        goal = data["goal"]
    except KeyError as exc:
        raise ConfigError(f"missing required config field: {exc.args[0]}") from exc

    if not isinstance(harness_path, str):
        raise ConfigError("harness_path must be a string")
    if not isinstance(goal, str):
        raise ConfigError("goal must be a string")

    return OptimizerConfig(
        harness_path=Path(harness_path),
        goal=goal,
        backend=_string_field(data, "backend", default="fake"),
        max_iterations=_integer_field(data, "max_iterations", default=1),
        evaluation_command=_optional_string_field(data, "evaluation_command"),
        run_artifact_dir=Path(
            _string_field(data, "run_artifact_dir", default="ralph_loop_runs")
        ),
        command_timeout_seconds=_optional_integer_field(
            data, "command_timeout_seconds"
        ),
        resume_behavior=_string_field(
            data, "resume_behavior", default="refuse_dirty"
        ),
    )


def _config_to_mapping(config: OptimizerConfig) -> dict[str, object]:
    return {
        "harness_path": str(config.harness_path),
        "goal": config.goal,
        "backend": config.backend,
        "max_iterations": config.max_iterations,
        "evaluation_command": config.evaluation_command,
        "run_artifact_dir": str(config.run_artifact_dir),
        "command_timeout_seconds": config.command_timeout_seconds,
        "resume_behavior": config.resume_behavior,
    }


def _string_field(data: dict[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    return value


def _optional_string_field(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string when provided")
    return value


def _integer_field(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer")
    return value


def _optional_integer_field(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer when provided")
    return value
