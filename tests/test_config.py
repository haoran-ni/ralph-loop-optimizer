from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ralph_loop_optimizer.config import (
    ConfigError,
    OptimizerConfig,
    load_config,
    validate_config,
    write_config,
)


def test_load_config_accepts_valid_config(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    config_path = tmp_path / "optimizer.json"
    config_path.write_text(
        json.dumps(
            {
                "harness_path": str(harness_path),
                "goal": "Improve the benchmark score.",
                "backend": "fake",
                "max_iterations": 3,
                "evaluation_command": "python evaluate.py",
                "run_artifact_dir": "ralph_loop_runs",
                "command_timeout_seconds": 60,
                "resume_behavior": "refuse_dirty",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.harness_path == harness_path
    assert config.goal == "Improve the benchmark score."
    assert config.backend == "fake"
    assert config.max_iterations == 3
    assert config.evaluation_command == "python evaluate.py"
    assert config.run_artifact_dir == Path("ralph_loop_runs")
    assert config.command_timeout_seconds == 60
    assert config.resume_behavior == "refuse_dirty"


def test_write_config_round_trips(tmp_path: Path) -> None:
    harness_path = _git_repo(tmp_path / "harness")
    original = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the workflow.",
        backend="codex",
        max_iterations=2,
        evaluation_command=None,
        command_timeout_seconds=None,
        resume_behavior="resume_existing",
    )

    config_path = tmp_path / "nested" / "optimizer.json"
    write_config(original, config_path)

    assert load_config(config_path) == original


def test_validate_config_rejects_missing_harness_path(tmp_path: Path) -> None:
    config = OptimizerConfig(
        harness_path=tmp_path / "missing",
        goal="Improve the benchmark score.",
    )

    with pytest.raises(ConfigError, match="harness_path does not exist"):
        validate_config(config)


def test_validate_config_rejects_non_git_harness(tmp_path: Path) -> None:
    harness_path = tmp_path / "harness"
    harness_path.mkdir()
    config = OptimizerConfig(
        harness_path=harness_path,
        goal="Improve the benchmark score.",
    )

    with pytest.raises(ConfigError, match="Git repository"):
        validate_config(config)


def test_validate_config_rejects_invalid_max_iterations(tmp_path: Path) -> None:
    config = OptimizerConfig(
        harness_path=_git_repo(tmp_path / "harness"),
        goal="Improve the benchmark score.",
        max_iterations=0,
    )

    with pytest.raises(ConfigError, match="max_iterations"):
        validate_config(config)


def test_validate_config_rejects_unknown_backend(tmp_path: Path) -> None:
    config = OptimizerConfig(
        harness_path=_git_repo(tmp_path / "harness"),
        goal="Improve the benchmark score.",
        backend="unknown",
    )

    with pytest.raises(ConfigError, match="backend must be one of"):
        validate_config(config)


def test_validate_config_rejects_artifact_dir_escape(tmp_path: Path) -> None:
    config = OptimizerConfig(
        harness_path=_git_repo(tmp_path / "harness"),
        goal="Improve the benchmark score.",
        run_artifact_dir=Path("../outside"),
    )

    with pytest.raises(ConfigError, match="inside the harness"):
        validate_config(config)


def test_validate_config_rejects_invalid_timeout(tmp_path: Path) -> None:
    config = OptimizerConfig(
        harness_path=_git_repo(tmp_path / "harness"),
        goal="Improve the benchmark score.",
        command_timeout_seconds=0,
    )

    with pytest.raises(ConfigError, match="command_timeout_seconds"):
        validate_config(config)


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    return path
