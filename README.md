# Ralph Loop Optimizer

Ralph Loop Optimizer is a framework for running repeated AI-driven improvement cycles over a user-provided harness repository.

Instead of using a Ralph loop only to complete a sequence of tasks, this project treats each Ralph iteration as one optimization step. A coding agent reviews the objective, the harness, prior attempts, evaluation results, and lessons learned, then proposes or implements the next experiment. The harness evaluates that experiment and produces performance feedback. The next iteration uses that feedback to search for a better strategy.

The goal is to help optimize policies, strategies, models, workflows, or agent behaviors when there is an external evaluation system that can measure progress.

Example use cases include:

- Optimizing an ML model architecture inside a training and evaluation workflow.
- Improving a poker bot's betting behavior inside a game simulation harness.
- Iterating on a benchmarked strategy, solver, policy, or workflow.
- Running experiments against a leaderboard, simulation environment, or automated scoring pipeline.

## Core Idea

Ralph Loop Optimizer owns the orchestration loop:

- Read the user's optimization goal.
- Inspect the harness repository.
- Build an iteration brief.
- Run a selected coding CLI, such as Codex, opencode, or Claude Code.
- Run the harness evaluation.
- Save results, logs, diffs, and lessons.
- Commit experiments so they can be retrieved later.
- Continue until the configured limit or target is reached.

The harness owns the domain behavior:

- Training models.
- Running simulations.
- Evaluating performance.
- Producing benchmark, metric, leaderboard, or test output.
- Defining what improvement means in that domain.

This separation is intentional. Ralph Loop Optimizer should not need to know whether the harness is written in Python, JavaScript, C++, shell scripts, notebooks, or another toolchain. It only needs enough information to modify the harness, run its evaluation, understand the result, and carry lessons forward.

## Expected Harness System

An input harness should be a local Git repository. It can be backed by GitHub or another remote, but Git history must be enabled so each experiment can be committed and recovered.

The harness should provide:

- Code, configuration, prompts, or workflow files that an AI coding agent can modify.
- One or more evaluation commands, scripts, functions, tests, benchmarks, or workflows.
- Performance output that can be compared across iterations.
- Setup instructions that explain how to install dependencies and run the evaluation.
- Domain instructions that describe what should be optimized and what should not be changed.

Ralph Loop Optimizer does not require a fixed evaluation output schema. A harness may print terminal logs, write JSON, write Markdown, emit CSV files, generate leaderboard tables, produce model metrics, or output custom reports.

Structured outputs are recommended because they are easier to compare. Good options include JSON, Markdown summaries, CSV metric tables, or clearly labeled log sections. However, any format is acceptable if the output is visible, repeatable enough to compare, and understandable to an LLM.

## Planned Workflow

The intended workflow is:

1. The user provides a harness repository directory.
2. The user provides a prompt describing what they want to optimize.
3. Ralph Loop Optimizer inspects the harness and creates `RALPH_LOOP.md` in the harness repository.
4. The user and agent review or refine `RALPH_LOOP.md` until the optimization plan is clear.
5. The optimizer waits for an explicit user start message.
6. Each iteration runs a coding CLI against the harness, evaluates the result, records the outcome, saves lessons, and commits the experiment.

`RALPH_LOOP.md` is the run-specific operating brief. It should capture:

- The user's optimization goal.
- What the harness appears to do.
- How evaluation appears to work.
- What files or workflows seem relevant.
- The expected iteration process.
- Assumptions or uncertainties that need user review.

Optimization should not begin until the user explicitly confirms that the loop should start.

## Generated Artifacts

Ralph Loop Optimizer is expected to create visible run artifacts inside the harness repository.

The preferred layout is:

```text
RALPH_LOOP.md
ralph_loop_runs/
  <run_id>/
    config.*
    iterations/
      001/
        prompt.md
        evaluation.*
        result.md
        lesson.md
        diff.*
```

The exact filenames and formats may evolve, but the purpose should remain stable:

- `RALPH_LOOP.md` is the human-readable operating brief.
- `ralph_loop_runs/` stores iteration history, evaluation outputs, and lessons.
- Git commits preserve each experiment so users can inspect, compare, revert, or reuse work.

## Configuration

Ralph Loop Optimizer should support configuration for orchestration concerns such as:

- Harness repository path.
- User optimization prompt.
- Coding CLI backend to use.
- Maximum number of iterations.
- Evaluation command or evaluation instructions.
- Stopping condition or target performance.
- Output directory for run artifacts.
- Resume behavior.
- Optional command timeouts.

Domain-specific configuration should usually stay inside the harness. For example, model search spaces, poker simulation settings, or benchmark-specific parameters belong with the harness unless the optimizer needs them to orchestrate the loop.

## Example Harnesses

This repository includes example harness folders that demonstrate how external systems connect to the optimizer.

Example harness folders in this repository are templates. The optimizer requires the harness path itself to be a local Git repository root, so run an example by copying it into a separate directory and initializing Git there. Do not point `--harness` directly at a subfolder inside this optimizer repository.

For example:

```bash
cp -R examples/cifar10-cnn /tmp/cifar10-cnn-harness
cd /tmp/cifar10-cnn-harness
git init
git add .
git commit -m "initial CIFAR-10 harness"
python -m pip install -r requirements.txt
```

Then initialize the optimizer against the copied harness repository:

```bash
ralph-loop init \
  --harness /tmp/cifar10-cnn-harness \
  --goal "Improve the CIFAR-10 test accuracy of the CNN model." \
  --evaluation-command "python evaluate.py"
```

Generated files such as `RALPH_LOOP.md`, `ralph_loop_runs/`, and iteration commits are written to the copied harness repository, not to this optimizer repository.

Current examples:

- `examples/cifar10-cnn/`: a PyTorch and torchvision CIFAR-10 harness where the optimizer improves a small CNN by editing `model.py` and `train_config.py`.

## Current Status

This repository now has an initial Python package scaffold, CLI entry point, configuration model, harness inspection, `init` command, backend adapters, evaluation capture, artifact writing, Git commit handling, and a bounded `run` command.

## Development

Install the package with development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the test suite:

```bash
python -m pytest
```

Check the CLI help:

```bash
python -m ralph_loop_optimizer.cli --help
```
