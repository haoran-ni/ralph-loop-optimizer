from __future__ import annotations

import shutil
import subprocess

import pytest


pytestmark = pytest.mark.real_cli


@pytest.mark.parametrize(
    ("binary_name", "expected_text"),
    [
        ("codex", "Codex CLI"),
        ("claude", "Claude Code"),
    ],
)
def test_real_ai_cli_help_is_available(
    binary_name: str,
    expected_text: str,
) -> None:
    if shutil.which(binary_name) is None:
        pytest.skip(f"{binary_name!r} is not installed")

    result = subprocess.run(
        [binary_name, "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert expected_text in output
