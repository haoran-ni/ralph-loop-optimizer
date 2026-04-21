# Purpose

This is a deterministic toy benchmark harness for Ralph Loop Optimizer examples.
The objective is to improve the score reported by `python evaluate.py`.

# Boundaries

You may edit:

- `strategy.py`

Do not edit:

- `evaluate.py`
- `README.md`
- Files under `tests/`
- Generated `RALPH_LOOP.md`, `ralph-loop.json`, or `ralph_loop_runs/` artifacts
  except when Ralph Loop Optimizer writes them as part of initialization or a run

# Evaluation

Run:

```bash
python evaluate.py
```

The evaluation is deterministic, uses only the fixed cases embedded in
`evaluate.py`, and prints a comparable score plus a JSON summary. Improve
`score` and `accuracy` without changing the evaluator or the benchmark cases.
