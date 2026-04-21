from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import choose_action


def test_choose_action_returns_binary_decision() -> None:
    action = choose_action({"signal": 1, "risk": 0, "momentum": 1})

    assert action in {0, 1}
