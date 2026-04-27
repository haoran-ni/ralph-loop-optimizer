"""Evaluate the editable US stock trading strategy."""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np
import pandas as pd

from strategy import Strategy


DEFAULT_TICKERS = (
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "JPM",
    "V",
    "UNH",
    "XOM",
)
INITIAL_CASH_PER_TICKER = 100_000.0
DATA_DIR = Path(__file__).resolve().parent / "data"
REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
TRADING_DAYS_PER_YEAR = 252
EPSILON = 1e-9


class StrategyProtocol(Protocol):
    def decide(
        self, ticker: str, history: pd.DataFrame, portfolio: "PortfolioState"
    ) -> float | None:
        ...


@dataclass(frozen=True)
class PortfolioState:
    ticker: str
    date: pd.Timestamp
    cash: float
    shares: float
    equity: float
    allocation: float
    is_invested: bool
    days_held: int
    trade_count: int


@dataclass(frozen=True)
class Trade:
    ticker: str
    date: pd.Timestamp
    action: str
    price: float
    shares_delta: float
    target_allocation: float
    cash_after: float
    shares_after: float


@dataclass(frozen=True)
class BacktestResult:
    ticker: str
    strategy_equity: pd.Series
    buy_and_hold_equity: pd.Series
    strategy_metrics: dict[str, float]
    buy_and_hold_metrics: dict[str, float]
    trades: tuple[Trade, ...]
    exposure_days: int
    tradeable_days: int
    holding_periods: tuple[int, ...]
    closed_trade_returns: tuple[float, ...]
    closed_trade_return_weights: tuple[float, ...]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="download fresh 5-year Yahoo Finance data instead of using cache",
    )
    args = parser.parse_args(argv)

    started_at = time.perf_counter()
    results = [
        evaluate_ticker(ticker, Strategy(), refresh_data=args.refresh_data)
        for ticker in DEFAULT_TICKERS
    ]
    summary = build_summary(results, elapsed_seconds=time.perf_counter() - started_at)
    print_summary(summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


def evaluate_ticker(
    ticker: str,
    strategy: StrategyProtocol,
    *,
    refresh_data: bool = False,
    data_dir: Path = DATA_DIR,
) -> BacktestResult:
    data = load_market_data(ticker, data_dir=data_dir, refresh=refresh_data)
    return run_backtest(ticker, data, strategy)


def load_market_data(ticker: str, *, data_dir: Path, refresh: bool) -> pd.DataFrame:
    cache_path = data_dir / f"{ticker.lower()}_5y_1d_auto_adjust.csv"
    if cache_path.exists() and not refresh:
        data = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        return validate_market_data(ticker, data)

    data = download_market_data(ticker)
    data_dir.mkdir(parents=True, exist_ok=True)
    data.to_csv(cache_path, index_label="Date")
    return validate_market_data(ticker, data)


def download_market_data(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    data = yf.download(
        ticker,
        period="5y",
        interval="1d",
        auto_adjust=True,
        progress=False,
        multi_level_index=False,
    )
    if data is None or data.empty:
        raise RuntimeError(f"Yahoo Finance returned no data for {ticker}")
    return validate_market_data(ticker, data)


def validate_market_data(ticker: str, data: pd.DataFrame) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        data = _flatten_single_ticker_columns(ticker, data)

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in data]
    if missing_columns:
        raise ValueError(f"{ticker} data is missing columns: {missing_columns}")

    validated = data.loc[:, list(REQUIRED_COLUMNS)].copy()
    validated.index = pd.to_datetime(validated.index)
    if validated.index.tz is not None:
        validated.index = validated.index.tz_localize(None)
    validated = validated.sort_index()
    validated = validated[~validated.index.duplicated(keep="last")]

    for column in REQUIRED_COLUMNS:
        validated[column] = pd.to_numeric(validated[column], errors="coerce")

    validated = validated.dropna(subset=REQUIRED_COLUMNS)
    validated = validated[(validated["Open"] > 0.0) & (validated["Close"] > 0.0)]
    if len(validated) < 60:
        raise ValueError(f"{ticker} data has only {len(validated)} usable rows")

    validated.index.name = "Date"
    return validated


def _flatten_single_ticker_columns(ticker: str, data: pd.DataFrame) -> pd.DataFrame:
    for level in range(data.columns.nlevels):
        if ticker in set(data.columns.get_level_values(level)):
            return data.xs(ticker, axis=1, level=level)
    return data.copy()


def run_backtest(
    ticker: str,
    data: pd.DataFrame,
    strategy: StrategyProtocol,
    *,
    initial_cash: float = INITIAL_CASH_PER_TICKER,
) -> BacktestResult:
    data = validate_market_data(ticker, data)
    if len(data) < 2:
        raise ValueError(f"{ticker} needs at least two rows for next-open execution")

    cash = float(initial_cash)
    shares = 0.0
    cost_basis = 0.0
    current_holding_days = 0
    exposure_days = 0
    trades: list[Trade] = []
    holding_periods: list[int] = []
    closed_trade_returns: list[float] = []
    closed_trade_return_weights: list[float] = []
    equity_records: list[tuple[pd.Timestamp, float]] = [
        (pd.Timestamp(data.index[0]), initial_cash)
    ]

    for decision_index in range(len(data) - 1):
        decision_date = pd.Timestamp(data.index[decision_index])
        execution_date = pd.Timestamp(data.index[decision_index + 1])
        decision_close = float(data["Close"].iloc[decision_index])
        equity_at_decision = cash + shares * decision_close
        allocation = _allocation(shares, decision_close, equity_at_decision)
        portfolio = PortfolioState(
            ticker=ticker,
            date=decision_date,
            cash=cash,
            shares=shares,
            equity=equity_at_decision,
            allocation=allocation,
            is_invested=shares > EPSILON,
            days_held=current_holding_days,
            trade_count=len(trades),
        )

        history = data.iloc[: decision_index + 1].copy()
        target_allocation = strategy.decide(ticker, history, portfolio)
        execution_open = float(data["Open"].iloc[decision_index + 1])
        invested_before_trade = shares > EPSILON

        if target_allocation is not None:
            target = normalize_target_allocation(target_allocation, ticker, decision_date)
            value_at_open = cash + shares * execution_open
            desired_shares = value_at_open * target / execution_open
            shares_delta = desired_shares - shares

            if abs(shares_delta) > EPSILON:
                if shares_delta > 0.0:
                    cost_basis += shares_delta * execution_open
                else:
                    shares_sold = min(-shares_delta, shares)
                    average_cost = cost_basis / shares if shares > EPSILON else 0.0
                    sold_cost_basis = shares_sold * average_cost
                    if sold_cost_basis > EPSILON and average_cost > EPSILON:
                        closed_trade_returns.append(
                            execution_open / average_cost - 1.0
                        )
                        closed_trade_return_weights.append(sold_cost_basis)
                    cost_basis = max(cost_basis - sold_cost_basis, 0.0)

                cash = value_at_open - desired_shares * execution_open
                shares = desired_shares
                if abs(cash) < EPSILON:
                    cash = 0.0
                if shares <= EPSILON:
                    shares = 0.0
                    cost_basis = 0.0

                action = "buy" if shares_delta > 0.0 else "sell"
                trades.append(
                    Trade(
                        ticker=ticker,
                        date=execution_date,
                        action=action,
                        price=execution_open,
                        shares_delta=shares_delta,
                        target_allocation=target,
                        cash_after=cash,
                        shares_after=shares,
                    )
                )

                invested_after_trade = shares > EPSILON
                if invested_before_trade and not invested_after_trade:
                    if current_holding_days > 0:
                        holding_periods.append(current_holding_days)
                    current_holding_days = 0

        execution_close = float(data["Close"].iloc[decision_index + 1])
        if shares > EPSILON:
            exposure_days += 1
            current_holding_days += 1
        equity_records.append((execution_date, cash + shares * execution_close))

    if shares > EPSILON and current_holding_days > 0:
        holding_periods.append(current_holding_days)

    strategy_equity = _series_from_records(equity_records, f"{ticker}_strategy")
    buy_and_hold_equity = build_buy_and_hold_equity(ticker, data, initial_cash)
    tradeable_days = len(data) - 1
    strategy_metrics = calculate_metrics(
        strategy_equity,
        exposure_days=exposure_days,
        trade_count=len(trades),
        buy_count=sum(1 for trade in trades if trade.action == "buy"),
        sell_count=sum(1 for trade in trades if trade.action == "sell"),
        holding_periods=holding_periods,
        closed_trade_returns=closed_trade_returns,
        closed_trade_return_weights=closed_trade_return_weights,
        tradeable_days=tradeable_days,
    )
    buy_and_hold_metrics = calculate_metrics(
        buy_and_hold_equity,
        exposure_days=tradeable_days,
        trade_count=1,
        buy_count=1,
        sell_count=0,
        holding_periods=[tradeable_days],
        closed_trade_returns=[],
        tradeable_days=tradeable_days,
    )

    return BacktestResult(
        ticker=ticker,
        strategy_equity=strategy_equity,
        buy_and_hold_equity=buy_and_hold_equity,
        strategy_metrics=strategy_metrics,
        buy_and_hold_metrics=buy_and_hold_metrics,
        trades=tuple(trades),
        exposure_days=exposure_days,
        tradeable_days=tradeable_days,
        holding_periods=tuple(holding_periods),
        closed_trade_returns=tuple(closed_trade_returns),
        closed_trade_return_weights=tuple(closed_trade_return_weights),
    )


def normalize_target_allocation(
    target_allocation: float, ticker: str, decision_date: pd.Timestamp
) -> float:
    try:
        target = float(target_allocation)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{ticker} strategy returned non-numeric allocation "
            f"{target_allocation!r} on {decision_date.date()}"
        ) from exc

    if not math.isfinite(target) or target < 0.0 or target > 1.0:
        raise ValueError(
            f"{ticker} strategy returned allocation {target!r} on "
            f"{decision_date.date()}; expected a finite value from 0.0 to 1.0"
        )
    return target


def build_buy_and_hold_equity(
    ticker: str, data: pd.DataFrame, initial_cash: float
) -> pd.Series:
    data = validate_market_data(ticker, data)
    if len(data) < 2:
        raise ValueError(f"{ticker} needs at least two rows for buy-and-hold")

    entry_open = float(data["Open"].iloc[1])
    shares = initial_cash / entry_open
    records = [(pd.Timestamp(data.index[0]), initial_cash)]
    for row_index in range(1, len(data)):
        date = pd.Timestamp(data.index[row_index])
        close = float(data["Close"].iloc[row_index])
        records.append((date, shares * close))
    return _series_from_records(records, f"{ticker}_buy_and_hold")


def calculate_metrics(
    equity_curve: pd.Series,
    *,
    exposure_days: int = 0,
    trade_count: int = 0,
    buy_count: int = 0,
    sell_count: int = 0,
    holding_periods: Iterable[int] = (),
    closed_trade_returns: Iterable[float] = (),
    closed_trade_return_weights: Iterable[float] | None = None,
    tradeable_days: int | None = None,
) -> dict[str, float]:
    equity = equity_curve.astype(float)
    daily_returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    start_value = float(equity.iloc[0])
    end_value = float(equity.iloc[-1])
    total_return = end_value / start_value - 1.0
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 365.25)
    annualized_return = (end_value / start_value) ** (1.0 / years) - 1.0
    annualized_volatility = float(
        daily_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)
    )
    sharpe_ratio = _ratio(
        float(daily_returns.mean() * TRADING_DAYS_PER_YEAR),
        annualized_volatility,
    )
    downside_returns = daily_returns[daily_returns < 0.0]
    downside_volatility = float(
        downside_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)
    )
    sortino_ratio = _ratio(
        float(daily_returns.mean() * TRADING_DAYS_PER_YEAR),
        downside_volatility,
    )
    running_max = equity.cummax()
    drawdowns = equity / running_max - 1.0
    max_drawdown = float(drawdowns.min())
    calmar_ratio = _ratio(annualized_return, abs(max_drawdown))
    holding_period_values = tuple(float(value) for value in holding_periods)
    closed_returns = tuple(float(value) for value in closed_trade_returns)
    closed_return_weights = (
        tuple(float(value) for value in closed_trade_return_weights)
        if closed_trade_return_weights is not None
        else ()
    )
    days = tradeable_days if tradeable_days is not None else max(len(equity) - 1, 1)

    return {
        "start_value": start_value,
        "end_value": end_value,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "calmar_ratio": calmar_ratio,
        "win_rate": _mean(daily_returns > 0.0),
        "best_daily_return": _safe_series_value(daily_returns.max()),
        "worst_daily_return": _safe_series_value(daily_returns.min()),
        "exposure_percentage": exposure_days / max(days, 1),
        "trade_count": float(trade_count),
        "buy_count": float(buy_count),
        "sell_count": float(sell_count),
        "average_holding_days": _mean(holding_period_values),
        "average_closed_trade_return": _weighted_mean(
            closed_returns, closed_return_weights
        )
        if closed_return_weights
        else _mean(closed_returns),
    }


def build_summary(
    results: Iterable[BacktestResult], *, elapsed_seconds: float
) -> dict[str, object]:
    result_list = list(results)
    strategy_equity = combine_equity_curves(
        result.strategy_equity for result in result_list
    )
    buy_and_hold_equity = combine_equity_curves(
        result.buy_and_hold_equity for result in result_list
    )
    trading_metrics = aggregate_trading_metrics(result_list)
    strategy_metrics = calculate_metrics(strategy_equity)
    strategy_metrics.update(trading_metrics)
    buy_and_hold_metrics = calculate_metrics(
        buy_and_hold_equity,
        exposure_days=sum(result.tradeable_days for result in result_list),
        trade_count=len(result_list),
        buy_count=len(result_list),
        sell_count=0,
        holding_periods=[result.tradeable_days for result in result_list],
        closed_trade_returns=[],
        tradeable_days=sum(result.tradeable_days for result in result_list),
    )

    strategy_return = strategy_metrics["total_return"]
    buy_and_hold_return = buy_and_hold_metrics["total_return"]
    sharpe_ratio = strategy_metrics["sharpe_ratio"]
    max_drawdown = strategy_metrics["max_drawdown"]
    score = (
        strategy_return
        - buy_and_hold_return
        + 0.25 * sharpe_ratio
        - 0.5 * abs(max_drawdown)
    )

    return {
        "benchmark": "us-stock-strategy",
        "tickers": [result.ticker for result in result_list],
        "period": "5y",
        "interval": "1d",
        "price_adjustment": "auto_adjust=True",
        "initial_cash_per_ticker": INITIAL_CASH_PER_TICKER,
        "initial_cash_total": INITIAL_CASH_PER_TICKER * len(result_list),
        "score": _round(score),
        "score_formula": (
            "strategy_total_return - buy_and_hold_total_return + "
            "0.25 * sharpe - 0.5 * abs(max_drawdown)"
        ),
        "strategy": _rounded_metrics(strategy_metrics),
        "buy_and_hold": _rounded_metrics(buy_and_hold_metrics),
        "excess_total_return": _round(strategy_return - buy_and_hold_return),
        "per_ticker": [
            {
                "ticker": result.ticker,
                "strategy": _rounded_metrics(result.strategy_metrics),
                "buy_and_hold": _rounded_metrics(result.buy_and_hold_metrics),
                "excess_total_return": _round(
                    result.strategy_metrics["total_return"]
                    - result.buy_and_hold_metrics["total_return"]
                ),
            }
            for result in result_list
        ],
        "elapsed_seconds": _round(elapsed_seconds),
    }


def aggregate_trading_metrics(results: Iterable[BacktestResult]) -> dict[str, float]:
    result_list = list(results)
    total_tradeable_days = sum(result.tradeable_days for result in result_list)
    total_exposure_days = sum(result.exposure_days for result in result_list)
    trades = [trade for result in result_list for trade in result.trades]
    holding_periods = [
        period for result in result_list for period in result.holding_periods
    ]
    closed_trade_returns = [
        trade_return
        for result in result_list
        for trade_return in result.closed_trade_returns
    ]
    closed_trade_return_weights = [
        trade_return_weight
        for result in result_list
        for trade_return_weight in result.closed_trade_return_weights
    ]
    return {
        "exposure_percentage": total_exposure_days / max(total_tradeable_days, 1),
        "trade_count": float(len(trades)),
        "buy_count": float(sum(1 for trade in trades if trade.action == "buy")),
        "sell_count": float(sum(1 for trade in trades if trade.action == "sell")),
        "average_holding_days": _mean(holding_periods),
        "average_closed_trade_return": _weighted_mean(
            closed_trade_returns, closed_trade_return_weights
        ),
    }


def combine_equity_curves(curves: Iterable[pd.Series]) -> pd.Series:
    frame = pd.concat(list(curves), axis=1).sort_index().ffill().dropna()
    if frame.empty:
        raise ValueError("cannot combine empty equity curves")
    return frame.sum(axis=1).rename("combined")


def print_summary(summary: dict[str, object]) -> None:
    strategy = summary["strategy"]
    buy_and_hold = summary["buy_and_hold"]
    assert isinstance(strategy, dict)
    assert isinstance(buy_and_hold, dict)

    print("US stock strategy evaluation")
    print(
        "tickers={tickers} period={period} interval={interval} "
        "initial_cash_total=${cash:,.2f}".format(
            tickers=",".join(str(ticker) for ticker in summary["tickers"]),
            period=summary["period"],
            interval=summary["interval"],
            cash=float(summary["initial_cash_total"]),
        )
    )
    print(
        "score={score:.6f} strategy_return={strategy_return} "
        "buy_and_hold_return={buy_hold_return} excess_return={excess_return}".format(
            score=float(summary["score"]),
            strategy_return=_format_percent(float(strategy["total_return"])),
            buy_hold_return=_format_percent(float(buy_and_hold["total_return"])),
            excess_return=_format_percent(float(summary["excess_total_return"])),
        )
    )
    print(
        "risk sharpe={sharpe:.3f} sortino={sortino:.3f} "
        "max_drawdown={max_drawdown} volatility={volatility}".format(
            sharpe=float(strategy["sharpe_ratio"]),
            sortino=float(strategy["sortino_ratio"]),
            max_drawdown=_format_percent(float(strategy["max_drawdown"])),
            volatility=_format_percent(float(strategy["annualized_volatility"])),
        )
    )
    print(
        "trading exposure={exposure} trades={trades:.0f} buys={buys:.0f} "
        "sells={sells:.0f} avg_holding_days={holding:.2f} "
        "avg_closed_trade_return={trade_return}".format(
            exposure=_format_percent(float(strategy["exposure_percentage"])),
            trades=float(strategy["trade_count"]),
            buys=float(strategy["buy_count"]),
            sells=float(strategy["sell_count"]),
            holding=float(strategy["average_holding_days"]),
            trade_return=_format_percent(float(strategy["average_closed_trade_return"])),
        )
    )
    print("per_ticker ticker strategy_return buy_hold_return excess sharpe drawdown trades exposure")
    for record in summary["per_ticker"]:
        assert isinstance(record, dict)
        ticker_strategy = record["strategy"]
        ticker_buy_hold = record["buy_and_hold"]
        assert isinstance(ticker_strategy, dict)
        assert isinstance(ticker_buy_hold, dict)
        print(
            "per_ticker {ticker} {strategy_return} {buy_hold_return} "
            "{excess} {sharpe:.3f} {drawdown} {trades:.0f} {exposure}".format(
                ticker=record["ticker"],
                strategy_return=_format_percent(float(ticker_strategy["total_return"])),
                buy_hold_return=_format_percent(float(ticker_buy_hold["total_return"])),
                excess=_format_percent(float(record["excess_total_return"])),
                sharpe=float(ticker_strategy["sharpe_ratio"]),
                drawdown=_format_percent(float(ticker_strategy["max_drawdown"])),
                trades=float(ticker_strategy["trade_count"]),
                exposure=_format_percent(float(ticker_strategy["exposure_percentage"])),
            )
        )


def _allocation(shares: float, price: float, equity: float) -> float:
    if equity <= EPSILON:
        return 0.0
    return shares * price / equity


def _series_from_records(
    records: list[tuple[pd.Timestamp, float]], name: str
) -> pd.Series:
    index = [date for date, _ in records]
    values = [value for _, value in records]
    return pd.Series(values, index=pd.DatetimeIndex(index, name="Date"), name=name)


def _ratio(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return 0.0
    if abs(denominator) < EPSILON:
        return 0.0
    return numerator / denominator


def _mean(values: Iterable[float] | pd.Series | np.ndarray) -> float:
    if isinstance(values, pd.Series):
        values_array = values.astype(float).to_numpy()
    else:
        values_array = np.asarray(tuple(values), dtype=float)
    values_array = values_array[np.isfinite(values_array)]
    if len(values_array) == 0:
        return 0.0
    return float(values_array.mean())


def _weighted_mean(values: Iterable[float], weights: Iterable[float]) -> float:
    values_array = np.asarray(tuple(values), dtype=float)
    weights_array = np.asarray(tuple(weights), dtype=float)
    if len(values_array) == 0 or len(values_array) != len(weights_array):
        return _mean(values_array)

    valid = (
        np.isfinite(values_array)
        & np.isfinite(weights_array)
        & (weights_array > EPSILON)
    )
    if not valid.any():
        return 0.0

    valid_weights = weights_array[valid]
    weight_sum = float(valid_weights.sum())
    if weight_sum <= EPSILON:
        return 0.0
    return float((values_array[valid] * valid_weights).sum() / weight_sum)


def _safe_series_value(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return number


def _rounded_metrics(metrics: dict[str, float]) -> dict[str, float]:
    return {key: _round(value) for key, value in metrics.items()}


def _round(value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        return 0.0
    return round(number, 6)


def _format_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


if __name__ == "__main__":
    raise SystemExit(main())
