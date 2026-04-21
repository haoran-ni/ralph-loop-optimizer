"""Editable strategy for the toy benchmark."""

from __future__ import annotations


def choose_action(features: dict[str, int]) -> int:
    """Return 1 to act, or 0 to hold."""
    signal = features["signal"]
    risk = features["risk"]
    momentum = features["momentum"]

    score = signal + momentum - risk
    return 1 if score >= 2 else 0
