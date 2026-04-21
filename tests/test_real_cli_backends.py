from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ralph_loop_optimizer.backends import BackendRequest, get_backend, run_backend


RUN_REAL_CLI_ENV = "RALPH_LOOP_RUN_REAL_AI_CLI"
OUTPUT_DIR_ENV = "RALPH_LOOP_REAL_CLI_OUTPUT_DIR"
TIMEOUT_ENV = "RALPH_LOOP_REAL_CLI_TIMEOUT_SECONDS"


pytestmark = pytest.mark.real_cli


@pytest.mark.parametrize(
    ("backend_name", "binary_name"),
    [
        ("codex", "codex"),
        ("claude", "claude"),
    ],
)
def test_real_ai_cli_writes_test_output(
    tmp_path: Path,
    backend_name: str,
    binary_name: str,
) -> None:
    if os.environ.get(RUN_REAL_CLI_ENV) != "1":
        pytest.skip(f"set {RUN_REAL_CLI_ENV}=1 to call real AI CLIs")
    if shutil.which(binary_name) is None:
        pytest.skip(f"{binary_name!r} is not installed")

    harness_path = _git_repo(tmp_path / f"{backend_name}-harness")
    _write(
        harness_path / "README.md",
        "# Real CLI Harness\n\nThis temporary harness is for adapter testing.\n",
    )
    _write(
        harness_path / "AGENTS.md",
        "\n".join(
            [
                "# Test Harness Instructions",
                "",
                "- Only create or update `ai_cli_output.txt`.",
                "- Do not commit changes.",
                "- Do not edit any other file.",
                "",
            ]
        ),
    )
    _commit_all(harness_path)

    result = run_backend(
        get_backend(backend_name),
        BackendRequest(
            harness_path=harness_path,
            prompt=_prompt_for_backend(backend_name),
            timeout_seconds=int(os.environ.get(TIMEOUT_ENV, "240")),
        ),
    )
    _write_run_outputs(backend_name, harness_path, result)

    output_path = harness_path / "ai_cli_output.txt"
    assert result.exit_code == 0, result.stderr
    assert output_path.is_file()
    assert output_path.read_text(encoding="utf-8").strip() == (
        f"backend={backend_name}\nstatus=ok"
    )


def _prompt_for_backend(backend_name: str) -> str:
    return "\n".join(
        [
            "This is an integration test for Ralph Loop Optimizer.",
            "",
            "Make exactly one file change in the current Git repository:",
            "",
            "Create `ai_cli_output.txt` with exactly this content:",
            "",
            f"backend={backend_name}",
            "status=ok",
            "",
            "Do not modify any other files. Do not commit. Keep the response short.",
            "",
        ]
    )


def _write_run_outputs(backend_name: str, harness_path: Path, result: object) -> None:
    output_dir = _output_dir() / backend_name
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout = getattr(result, "stdout")
    stderr = getattr(result, "stderr")
    exit_code = getattr(result, "exit_code")
    elapsed_seconds = getattr(result, "elapsed_seconds")

    (output_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (output_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    (output_dir / "git-status.txt").write_text(
        _git_status(harness_path),
        encoding="utf-8",
    )
    output_file = harness_path / "ai_cli_output.txt"
    (output_dir / "ai_cli_output.txt").write_text(
        (
            output_file.read_text(encoding="utf-8", errors="replace")
            if output_file.is_file()
            else "(missing)\n"
        ),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "backend": backend_name,
                "exit_code": exit_code,
                "elapsed_seconds": elapsed_seconds,
                "harness_path": str(harness_path),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _output_dir() -> Path:
    configured = os.environ.get(OUTPUT_DIR_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / "tmp" / "real_cli_outputs").resolve()


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Ralph Real CLI Test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "ralph-real-cli-test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path


def _commit_all(repo_path: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def _git_status(repo_path: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
