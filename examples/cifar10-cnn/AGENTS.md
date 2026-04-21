# Purpose

This is a CIFAR-10 computer vision harness for Ralph Loop Optimizer examples.
The objective is to improve the model's CIFAR-10 test accuracy reported by
`python evaluate.py`.

# Boundaries

You may edit:

- `model.py`
- `train_config.py`

Do not edit:

- `evaluate.py`
- `README.md`
- `requirements.txt`
- Files under `data/`
- Generated `ralph_loop_runs/` artifacts except when Ralph Loop Optimizer writes
  them as part of a run

# Dataset Rules

Use CIFAR-10 only. Do not switch to another dataset, add external training data,
use pretrained weights, or leak test labels into training.

# Evaluation

Run:

```bash
python evaluate.py
```

The evaluation uses deterministic train and test subsets from CIFAR-10. Improve
the printed `test_accuracy` while keeping the harness compatible with the
existing evaluation command.

