"""Evaluate the editable toy benchmark strategy."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from strategy import choose_action


TARGET_SCORE = 21


@dataclass(frozen=True)
class Case:
    name: str
    features: dict[str, int]
    expected_action: int
    weight: int


CASES = (
    Case("calm-low-risk", {"signal": 1, "risk": 0, "momentum": 1}, 1, 2),
    Case("calm-high-risk", {"signal": 1, "risk": 2, "momentum": 0}, 0, 3),
    Case("strong-momentum", {"signal": 2, "risk": 1, "momentum": 2}, 1, 3),
    Case("weak-signal", {"signal": 0, "risk": 0, "momentum": 1}, 0, 2),
    Case("risk-spike", {"signal": 2, "risk": 3, "momentum": 1}, 0, 4),
    Case("balanced-edge", {"signal": 2, "risk": 1, "momentum": 0}, 1, 2),
    Case("negative-momentum", {"signal": 1, "risk": 1, "momentum": -1}, 0, 2),
    Case("clear-opportunity", {"signal": 3, "risk": 1, "momentum": 1}, 1, 3),
)


def main() -> int:
    started_at = time.perf_counter()
    results = [evaluate_case(case) for case in CASES]
    score = sum(result["points"] for result in results)
    max_score = sum(case.weight for case in CASES)
    correct = sum(1 for result in results if result["correct"])
    accuracy = correct / len(CASES)
    summary = {
        "benchmark": "toy-benchmark",
        "cases": len(CASES),
        "correct": correct,
        "score": score,
        "max_score": max_score,
        "accuracy": round(accuracy, 6),
        "target_score": TARGET_SCORE,
        "target_met": score >= TARGET_SCORE,
        "elapsed_seconds": round(time.perf_counter() - started_at, 6),
        "results": results,
    }

    for result in results:
        print(
            "case={case} expected={expected} actual={actual} "
            "correct={correct} points={points}".format(**result)
        )
    print(
        "summary score={score}/{max_score} accuracy={accuracy:.3f} "
        "target_score={target_score} target_met={target_met}".format(**summary)
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


def evaluate_case(case: Case) -> dict[str, object]:
    action = choose_action(dict(case.features))
    if action not in {0, 1}:
        raise ValueError(
            f"strategy returned {action!r} for {case.name}; expected 0 or 1"
        )

    correct = action == case.expected_action
    return {
        "case": case.name,
        "expected": case.expected_action,
        "actual": action,
        "correct": correct,
        "points": case.weight if correct else 0,
    }


if __name__ == "__main__":
    raise SystemExit(main())
