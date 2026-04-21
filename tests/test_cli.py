from __future__ import annotations

import pytest

from ralph_loop_optimizer.cli import main


def test_cli_help_exits_successfully() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
