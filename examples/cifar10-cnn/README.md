# CIFAR-10 CNN Harness

This example harness trains and evaluates a small convolutional neural network on
CIFAR-10. It is intended as a domain-specific target for Ralph Loop Optimizer:
the optimizer edits the model or training knobs, then the harness reports
prediction accuracy.

## Dataset

This harness uses CIFAR-10 only. `evaluate.py` downloads CIFAR-10 with
`torchvision` into `data/` when the dataset is not already present.

The evaluation uses deterministic class-balanced subsets of the official
CIFAR-10 train and test splits so iterations are practical while still using the
real dataset.

## Setup

```bash
python -m pip install -r requirements.txt
```

## Evaluation

```bash
python evaluate.py
```

The command trains the current model, evaluates test accuracy, and prints
concise plain-text progress and summary lines. The objective is to make test
accuracy as high as possible; command failure is reserved for runtime or
configuration errors.

## Files For Optimization

Ralph Loop Optimizer should improve CIFAR-10 prediction accuracy by editing:

- `model.py`
- `train_config.py`

`evaluate.py` owns dataset loading, scoring, and output formatting and should
not be modified during optimization.

## Suggested Ralph Loop Initialization

Run this command from a Git repository root that contains this harness:

```bash
ralph-loop init \
  --harness /path/to/cifar10-cnn \
  --goal "Maximize the CIFAR-10 test accuracy of the CNN model." \
  --evaluation-command "python evaluate.py"
```
