# Purpose

This is a quantitative finance strategy harness for Ralph Loop Optimizer
examples. The objective is to improve the score reported by
`python evaluate.py` on the 10 configured US stock tickers.

# Boundaries

You may edit:

- `strategy.py`

Do not edit:

- `evaluate.py`
- `README.md`
- `requirements.txt`
- Files under `data/`
- Files under `tests/`
- Generated `RALPH_LOOP.md`, `ralph-loop.json`, or `ralph_loop_runs/` artifacts
  except when Ralph Loop Optimizer writes them as part of initialization or a run

# Strategy Contract

`Strategy.decide(ticker, history, portfolio)` is called once per ticker per
trading day after the current day's close.

- `history` is a standard Yahoo Finance OHLCV `pandas.DataFrame` containing
  only data through the current decision day.
- `portfolio` describes current cash, shares, equity, allocation, holding days,
  and trade count as of the current decision day's close.
- Return `None` to keep the current position.
- Return a finite float from `0.0` to `1.0` to request the target allocation.
- The evaluator executes that target allocation at the next trading day's open.

Do not use future rows, next-day open prices, next-day close prices, cached
answers, external signals, or hard-coded ticker outcomes in the strategy.

# Evaluation

Run:

```bash
python evaluate.py
```

The evaluation uses 5 years of 1-day Yahoo Finance data with `auto_adjust=True`.
It caches data under `data/` and compares the strategy against a buy-and-hold
baseline. Improve the printed `score` without changing evaluator accounting,
market data, or output formatting.

