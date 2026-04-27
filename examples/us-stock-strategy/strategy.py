"""Editable stock trading strategy for the US stock strategy harness."""

from __future__ import annotations

from typing import Any

import pandas as pd


REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class Strategy:
    """Simple EMA crossover strategy.

    The evaluator calls ``decide`` once per ticker per trading day after that
    day's close. ``history`` is standard Yahoo Finance OHLCV data truncated
    through the current decision day. Returned allocations are executed by the
    evaluator at the next trading day's open.
    """

    def __init__(self, short_window: int = 20, long_window: int = 50) -> None:
        if short_window <= 0:
            raise ValueError("short_window must be positive")
        if long_window <= short_window:
            raise ValueError("long_window must be greater than short_window")
        self.short_window = short_window
        self.long_window = long_window

    def decide(
        self, ticker: str, history: pd.DataFrame, portfolio: Any
    ) -> float | None:
        """Return the desired allocation for ``ticker`` or ``None`` to hold.

        Return values:
        - ``1.0`` means all available capital invested in the stock.
        - ``0.0`` means all capital held as cash.
        - ``None`` means keep the current position unchanged.
        """

        missing_columns = [
            column for column in REQUIRED_COLUMNS if column not in history
        ]
        if missing_columns:
            raise ValueError(
                f"history for {ticker} is missing OHLCV columns: {missing_columns}"
            )

        if len(history) < self.long_window + 2:
            return None

        close = history["Close"].astype(float)
        short_ema = close.ewm(span=self.short_window, adjust=False).mean()
        long_ema = close.ewm(span=self.long_window, adjust=False).mean()

        previous_short = short_ema.iloc[-2]
        previous_long = long_ema.iloc[-2]
        current_short = short_ema.iloc[-1]
        current_long = long_ema.iloc[-1]
        current_allocation = float(getattr(portfolio, "allocation", 0.0))

        crossed_above = previous_short <= previous_long and current_short > current_long
        if crossed_above and current_allocation < 0.99:
            return 1.0

        crossed_below = previous_short >= previous_long and current_short < current_long
        if crossed_below and current_allocation > 0.01:
            return 0.0

        return None
