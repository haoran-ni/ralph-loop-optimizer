# Toy Benchmark Harness

This example harness is a tiny deterministic optimization target for Ralph Loop
Optimizer. It is intended for fast local smoke tests and demonstrations.

The editable strategy receives small numeric feature dictionaries and returns a
binary action. The evaluator scores those actions against fixed benchmark cases.

## Setup

No third-party dependencies are required.

## Evaluation

```bash
python evaluate.py
```

The command prints per-case decisions, a plain-text score summary, and a JSON
record. The command returns success even when the target score is not met;
command failure is reserved for runtime or contract errors.

## Files For Optimization

Ralph Loop Optimizer should improve the benchmark score by editing:

- `strategy.py`

`evaluate.py` owns scoring and output formatting and should not be modified
during optimization.

## Suggested Ralph Loop Initialization

Run this command from a Git repository root that contains this harness:

```bash
ralph-loop init \
  --harness /path/to/toy-benchmark \
  --goal "Improve the deterministic toy benchmark score." \
  --evaluation-command "python evaluate.py" \
  --backend fake
```
