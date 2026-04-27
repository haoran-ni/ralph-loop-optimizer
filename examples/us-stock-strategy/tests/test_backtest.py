from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

EXAMPLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXAMPLE_DIR))
sys.modules.pop("strategy", None)
sys.modules.pop("evaluate", None)

from evaluate import calculate_metrics, run_backtest  # noqa: E402


def test_strategy_receives_full_ohlcv_history_without_future_rows() -> None:
    data = _market_data(
        open_prices=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0] * 10,
        close_prices=[100.5, 101.5, 102.5, 103.5, 104.5, 105.5] * 10,
    )
    strategy = RecordingStrategy()

    run_backtest("TEST", data, strategy)

    assert strategy.history_columns[0] == ["Open", "High", "Low", "Close", "Volume"]
    assert strategy.history_lengths[:3] == [1, 2, 3]
    assert strategy.history_last_dates[0] == data.index[0]
    assert strategy.history_last_dates[-1] == data.index[-2]


def test_buy_signal_executes_at_next_open() -> None:
    data = _market_data(
        open_prices=[100.0, 10.0, 20.0, 30.0] * 15,
        close_prices=[100.0, 11.0, 22.0, 33.0] * 15,
    )

    result = run_backtest("TEST", data, ScriptedStrategy({0: 1.0}))

    first_trade = result.trades[0]
    assert first_trade.date == data.index[1]
    assert first_trade.price == 10.0
    assert first_trade.shares_after == pytest.approx(10_000.0)
    assert result.strategy_equity.iloc[1] == pytest.approx(110_000.0)


def test_sell_signal_executes_at_next_open() -> None:
    data = _market_data(
        open_prices=[100.0, 10.0, 20.0, 30.0] * 15,
        close_prices=[100.0, 11.0, 22.0, 33.0] * 15,
    )

    result = run_backtest("TEST", data, ScriptedStrategy({0: 1.0, 1: 0.0}))

    sell_trade = result.trades[1]
    assert sell_trade.action == "sell"
    assert sell_trade.date == data.index[2]
    assert sell_trade.price == 20.0
    assert sell_trade.cash_after == pytest.approx(200_000.0)
    assert result.strategy_equity.iloc[2] == pytest.approx(200_000.0)


def test_closed_trade_returns_use_average_cost_for_partial_positions() -> None:
    data = _market_data(
        open_prices=[50.0, 50.0, 60.0, 70.0, 80.0] + [80.0] * 55,
        close_prices=[50.0, 60.0, 70.0, 80.0, 80.0] + [80.0] * 55,
    )

    result = run_backtest(
        "TEST",
        data,
        TargetShareStrategy({0: 10.0, 1: 5.0, 2: 10.0, 3: 5.0}),
    )

    assert result.closed_trade_returns == pytest.approx((0.2, 1.0 / 3.0))
    assert result.closed_trade_return_weights == pytest.approx((250.0, 300.0))
    assert result.strategy_metrics["average_closed_trade_return"] == pytest.approx(
        150.0 / 550.0
    )


def test_calculate_metrics_reports_max_drawdown() -> None:
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    equity = pd.Series([100.0, 120.0, 90.0, 150.0], index=dates)

    metrics = calculate_metrics(equity)

    assert metrics["total_return"] == pytest.approx(0.5)
    assert metrics["max_drawdown"] == pytest.approx(-0.25)


class RecordingStrategy:
    def __init__(self) -> None:
        self.history_columns: list[list[str]] = []
        self.history_lengths: list[int] = []
        self.history_last_dates: list[pd.Timestamp] = []

    def decide(self, ticker: str, history: pd.DataFrame, portfolio: object) -> None:
        self.history_columns.append(list(history.columns))
        self.history_lengths.append(len(history))
        self.history_last_dates.append(history.index[-1])
        return None


class ScriptedStrategy:
    def __init__(self, decisions: dict[int, float]) -> None:
        self.decisions = decisions

    def decide(
        self, ticker: str, history: pd.DataFrame, portfolio: object
    ) -> float | None:
        return self.decisions.get(len(history) - 1)


class TargetShareStrategy:
    def __init__(self, desired_shares: dict[int, float]) -> None:
        self.desired_shares = desired_shares

    def decide(
        self, ticker: str, history: pd.DataFrame, portfolio: object
    ) -> float | None:
        target_shares = self.desired_shares.get(len(history) - 1)
        if target_shares is None:
            return None

        current_close = float(history["Close"].iloc[-1])
        cash = float(getattr(portfolio, "cash", 0.0))
        shares = float(getattr(portfolio, "shares", 0.0))
        equity = cash + shares * current_close
        if equity <= 0.0:
            return 0.0
        return target_shares * current_close / equity


def _market_data(open_prices: list[float], close_prices: list[float]) -> pd.DataFrame:
    if len(open_prices) != len(close_prices):
        raise ValueError("open_prices and close_prices must have the same length")
    dates = pd.date_range("2024-01-01", periods=len(open_prices), freq="B")
    return pd.DataFrame(
        {
            "Open": open_prices,
            "High": [
                max(open_price, close_price) + 1.0
                for open_price, close_price in zip(open_prices, close_prices)
            ],
            "Low": [
                min(open_price, close_price) - 1.0
                for open_price, close_price in zip(open_prices, close_prices)
            ],
            "Close": close_prices,
            "Volume": [1_000_000] * len(open_prices),
        },
        index=dates,
    )
