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
- Run a selected coding CLI, such as Codex or Claude Code.
- Run the harness evaluation.
- Call the coding CLI again to update concise lessons from the diff and
  evaluation feedback.
- Save results, logs, diffs, prompts, and lessons.
- Commit completed iterations so they can be retrieved later.
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

Structured outputs are recommended because they are easier to compare. Good
options include JSON, Markdown summaries, CSV metric tables, or clearly
labeled log sections. However, any format is acceptable if the output is
visible, repeatable enough to compare, and understandable to an LLM.

For best results, the harness evaluation command should emit concise text that
directly states the current performance metrics on success, or a concise
failure message on error. Ralph Loop Optimizer uses that summary text in
iteration records, lessons, and commit messages.

## Workflow

The intended workflow is:

1. The user provides a harness repository directory.
2. The user provides a prompt describing what they want to optimize.
3. Ralph Loop Optimizer validates the harness and creates a placeholder `RALPH_LOOP.md` plus a starter `ralph-loop.json` config in the harness repository.
4. Unless `--skip-ai-review` is passed, `init` calls the configured backend to inspect the harness and refine `RALPH_LOOP.md` without starting optimization.
5. The user reviews or edits `RALPH_LOOP.md` and `ralph-loop.json`, especially `backend`, `max_iterations`, `evaluation_command`, and `command_timeout_seconds`.
6. The user commits the reviewed harness state, including `RALPH_LOOP.md` and
   any approved config changes, so the harness worktree is clean.
7. The optimizer waits for an explicit `ralph-loop run --config ...` command.
8. Each iteration runs a coding CLI against the harness, evaluates the result,
   calls the coding CLI again to update `lesson.md`, and then Ralph Loop
   Optimizer stages and commits the code and Ralph Loop artifacts itself.

`RALPH_LOOP.md` is the run-specific operating brief. It should capture:

- The user's optimization goal.
- Harness reference file paths and short explanations.
- File modification scope, constraints, and requirements.
- AI behavior requirements for future optimization iterations.

The initial draft uses placeholders rather than guessed file paths. The init-time AI review, or the user, should fill in harness reference files only after inspecting the repository.

Optimization should not begin until the user explicitly confirms that the loop should start.

## Command Reference

Inspect a harness, write the starter files, and ask the configured backend to refine `RALPH_LOOP.md` without starting optimization:

```bash
ralph-loop init \
  --harness /path/to/harness \
  --goal "Describe what should improve." \
  --evaluation-command "python evaluate.py" \
  --backend fake
```

Skip the AI review during init when only the mechanical draft is needed:

```bash
ralph-loop init \
  --harness /path/to/harness \
  --goal "Describe what should improve." \
  --evaluation-command "python evaluate.py" \
  --backend fake \
  --skip-ai-review
```

Start the optimization loop explicitly:

```bash
ralph-loop run --config /path/to/harness/ralph-loop.json
```

Resume a recorded run:

```bash
ralph-loop resume --harness /path/to/harness --run-id run-YYYYMMDDTHHMMSSffffffZ
```

Inspect a harness and recorded runs without starting optimization:

```bash
ralph-loop status --harness /path/to/harness
ralph-loop status --harness /path/to/harness --run-id run-YYYYMMDDTHHMMSSffffffZ
```

List configured backends:

```bash
ralph-loop backends
```

## Generated Artifacts

Ralph Loop Optimizer is expected to create visible run artifacts inside the harness repository.

The preferred layout is:

```text
RALPH_LOOP.md
ralph-loop.json
ralph_loop_runs/
  <run_id>/
    config.*
    iterations/
      001/
        prompt.md
        lesson_prompt.md
        evaluation.*
        result.md
        lesson.md
        diff.*
```

The exact filenames and formats may evolve, but the purpose should remain stable:

- `RALPH_LOOP.md` is the human-readable operating brief.
- `ralph-loop.json` is the starter configuration used by `ralph-loop run`.
- `ralph_loop_runs/` stores iteration prompts, evaluation outputs, diffs,
  results, and lessons.
- Git commits preserve each completed iteration so users can inspect, compare,
  revert, or reuse work.

## Configuration

`ralph-loop init` writes a starter `ralph-loop.json` in the harness repository. Review it before running optimization.

Common fields:

- `harness_path`: absolute path to the harness Git repository root.
- `goal`: the optimization objective.
- `backend`: `fake`, `codex`, or `claude`.
- `max_iterations`: maximum number of optimization attempts for `run` or `resume`.
- `evaluation_command`: optional command to run after each backend attempt. If omitted, the iteration records that manual evaluation is required.
- `run_artifact_dir`: relative directory for run history, usually `ralph_loop_runs`.
- `command_timeout_seconds`: optional timeout for backend and evaluation commands.
- `resume_behavior`: current resume policy setting.

Domain-specific configuration should usually stay inside the harness. For example, model search spaces, poker simulation settings, or benchmark-specific parameters belong with the harness unless the optimizer needs them to orchestrate the loop.

## Example Harnesses

This repository includes example harness folders that demonstrate how external systems connect to the optimizer.

Example harness folders in this repository are templates. The optimizer requires the harness path itself to be a local Git repository root, so run an example by copying it into a separate directory and initializing Git there. Do not point `--harness` directly at a subfolder inside this optimizer repository.

## Quick Start With Toy Benchmark

Install the package from this repository:

```bash
python -m pip install -e ".[dev]"
```

Copy the deterministic toy benchmark into its own Git repository:

```bash
HARNESS_DIR="$(mktemp -d)/toy-benchmark-harness"
cp -R examples/toy-benchmark "$HARNESS_DIR"
cd "$HARNESS_DIR"
git init
git add .
git -c user.name="Ralph Loop Demo" \
  -c user.email="ralph-loop-demo@example.com" \
  commit -m "initial toy benchmark harness"
python evaluate.py
```

Then initialize the optimizer against the copied harness repository:

```bash
ralph-loop init \
  --harness "$HARNESS_DIR" \
  --goal "Improve the deterministic toy benchmark score." \
  --evaluation-command "python evaluate.py" \
  --backend fake
```

This writes:

```text
$HARNESS_DIR/RALPH_LOOP.md
$HARNESS_DIR/ralph-loop.json
```

Review and edit `$HARNESS_DIR/RALPH_LOOP.md` and `$HARNESS_DIR/ralph-loop.json` before starting. The most common config fields to change are:

- `backend`: use `fake` for deterministic dry runs, or `codex` / `claude` when those CLIs are installed.
- `max_iterations`: the maximum number of optimization attempts.
- `evaluation_command`: the harness command that produces performance feedback.
- `command_timeout_seconds`: optional timeout for backend and evaluation commands.

Before `ralph-loop run`, commit the reviewed harness state so the harness
worktree is clean. This includes `RALPH_LOOP.md`, `ralph-loop.json`, and any
other user-approved harness changes.

Check the pre-run state:

```bash
ralph-loop status --harness "$HARNESS_DIR"
ralph-loop backends
```

Commit the reviewed harness state before running the loop:

```bash
git add RALPH_LOOP.md ralph-loop.json
git commit -m "prepare Ralph Loop run"
```

Start optimization explicitly:

```bash
ralph-loop run --config "$HARNESS_DIR/ralph-loop.json"
ralph-loop status --harness "$HARNESS_DIR"
```

Generated files such as `RALPH_LOOP.md`, `ralph_loop_runs/`, and iteration commits are written to the copied harness repository, not to this optimizer repository.

The `fake` backend does not modify the harness target files. It is useful for
checking the orchestration flow, artifact creation, evaluation capture, lesson
updates, and package-managed Git commits before using a real AI backend.

Current examples:

- `examples/toy-benchmark/`: a dependency-free deterministic benchmark where the optimizer improves a binary decision strategy by editing `strategy.py`.
- `examples/cifar10-cnn/`: a PyTorch and torchvision CIFAR-10 harness where the optimizer improves a small CNN by editing `model.py` and `train_config.py`.

## Backends

The current real coding backends are:

- `codex`: runs the Codex CLI in non-interactive exec mode.
- `claude`: runs Claude Code in non-interactive print mode.

The `fake` backend remains available for deterministic dry runs and automated tests. It exercises the optimizer loop without calling an AI model or editing target files.

Use `ralph-loop backends` to print the backend names accepted by the installed package.

## Current Status

This repository now has a Python package scaffold, CLI entry point, configuration model, harness inspection, `init` command with starter config generation and optional AI brief refinement, backend adapters, evaluation capture, artifact writing, Git commit handling, bounded `run`, `resume`, `status`, and backend listing.

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

Run the real CLI availability checks:

```bash
python -m pytest tests/test_real_cli_availability.py
```

Run the opt-in tests that ask the installed AI CLIs to edit a temporary harness:

```bash
RALPH_LOOP_RUN_REAL_AI_CLI=1 python -m pytest tests/test_real_cli_backends.py
```
