# US Stock Strategy Harness

This example harness evaluates an editable trading strategy on popular US
stocks. Ralph Loop Optimizer can use it as a quantitative finance target: the
optimizer edits `strategy.py`, then the harness downloads or loads market data,
runs a temporally correct backtest, and reports return, risk, and trading
behavior metrics.

## Dataset

The evaluator uses `yfinance` to load 5 years of 1-day OHLCV data with
`auto_adjust=True`. The first evaluation downloads data into `data/`; later
evaluations reuse the cached CSV files unless `--refresh-data` is passed.

The default ticker set is:

```text
AAPL, MSFT, GOOGL, AMZN, NVDA, META, JPM, V, UNH, XOM
```

Each ticker is traded independently with `$100,000` starting cash. Final
portfolio metrics are calculated from the combined equity curve across all 10
tickers.

## Setup

```bash
python -m pip install -r requirements.txt
```

## Evaluation

```bash
python evaluate.py
```

Refresh cached Yahoo Finance data:

```bash
python evaluate.py --refresh-data
```

The command prints a concise summary, per-ticker results, and a final JSON
record. Command failure is reserved for runtime, data, or strategy contract
errors.

The headline score is:

```text
strategy_total_return - buy_and_hold_total_return + 0.25 * sharpe - 0.5 * abs(max_drawdown)
```

`max_drawdown` is represented as a negative decimal, so larger drawdowns reduce
the score.

## Backtest Rules

- Data interval is 1 trading day.
- The strategy receives full Yahoo Finance-style OHLCV history through the
  current day's close.
- A decision made after day `t` close executes at day `t+1` open.
- Portfolio value is marked using day `t+1` close after any next-open trade.
- The evaluator owns trade execution, portfolio accounting, and metrics.
- Fractional shares are allowed.
- No commission or slippage is included.
- Short selling and leverage are not allowed; target allocations must be from
  `0.0` to `1.0`.
- Closed-trade return metrics use average-cost accounting for partial positions.

## Files For Optimization

Ralph Loop Optimizer should improve the reported score by editing:

- `strategy.py`

`evaluate.py` owns data loading, backtesting, scoring, and output formatting and
should not be modified during optimization.

## Suggested Ralph Loop Initialization

Run this command from a Git repository root that contains this harness:

```bash
ralph-loop init \
  --harness /path/to/us-stock-strategy \
  --goal "Maximize the US stock strategy score versus buy-and-hold." \
  --evaluation-command "python evaluate.py" \
  --backend codex
```
