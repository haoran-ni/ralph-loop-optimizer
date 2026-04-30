# Purpose

This file is for agentic AI coding assistants working on this repository. It consolidates the development requirements, boundaries, and coding guidelines for Ralph Loop Optimizer.

`README.md` is for human users who want to understand what this project does and how to use it. `AGENTS.md` is for coding agents that are developing the project. Keep that distinction clear when editing documentation.

# Project Overview

This project develops a framework that uses a Ralph loop with an LLM inside to iteratively improve a policy, strategy, model, or workflow against a user-defined objective.

Instead of using Ralph only to complete a sequence of tasks, the framework treats each Ralph iteration as one optimization step. The AI reviews the project goal, the harness repository, prior attempts, evaluation results, and accumulated lessons, then proposes or implements the next experiment.

The system is built around user-provided evaluation systems such as harnesses, benchmarks, leaderboards, simulation environments, training workflows, or automated scoring pipelines. These tools provide objective feedback after each iteration, allowing the AI to compare strategies, diagnose failures, preserve useful lessons, and decide what to try next.

The core idea is to turn Ralph from a task-execution loop into a performance-improvement loop: a framework where AI agents repeatedly propose, evaluate, learn, and revise strategies until they satisfy the user's target or reach the configured stopping point.

# Product Boundaries

Ralph Loop Optimizer owns orchestration:

- Inspecting the input harness repository.
- Creating and maintaining the run-specific operating brief.
- Creating and maintaining the starter optimizer configuration.
- Selecting and invoking coding CLI backends.
- Supplying iteration context to those backends.
- Running or requesting harness evaluation.
- Capturing evaluation outputs.
- Saving raw history and distilled lessons.
- Creating run artifact folders.
- Committing experiments to Git.
- Enforcing maximum iterations and other orchestration settings.

The input harness owns domain behavior:

- Training models.
- Running simulations.
- Scoring policies or strategies.
- Producing benchmark, leaderboard, metric, or test output.
- Defining what performance means.
- Defining which files, workflows, or behaviors are safe to change.

Do not blur these boundaries. The optimizer should not embed ML-specific, poker-specific, benchmark-specific, or leaderboard-specific assumptions into core orchestration code. Put domain-specific behavior in harness examples or harness instructions.

# Input Harness Expectations

An input harness is a user-provided local Git repository that Ralph Loop Optimizer can inspect, modify, evaluate, and commit against.

The harness should provide:

- Code, configuration, prompts, or workflow files that an AI coding agent can modify.
- One or more evaluation commands, scripts, functions, tests, benchmarks, or workflows.
- Performance output that can be compared across iterations.
- Setup instructions that explain how to install dependencies and run evaluation.
- Domain instructions that explain what should be optimized and what should not be changed.

Do not require a fixed evaluation output schema. The harness may emit terminal logs, JSON, Markdown, CSV, leaderboard tables, model metrics, test reports, generated files, or custom text.

Structured output should be recommended, not required. JSON, Markdown summaries, CSV metric tables, and clearly labeled logs are useful because they are easier for LLMs to compare. However, any output format is acceptable if it is visible, repeatable enough to compare, and understandable enough for an LLM to judge progress.

# Initialization Lifecycle

Ralph Loop Optimizer starts with:

- The path to the input harness repository.
- A user prompt describing what they want to optimize.

At runtime, the optimizer should inspect the harness and create `RALPH_LOOP.md` at the harness repository root. This file is the run-specific operating brief. It should capture:

- The user's optimization goal.
- Harness reference file paths and short explanations of why they matter.
- Working environment requirements and command wrappers for checks or evaluation.
- File modification scope, constraints, and requirements.
- AI behavior requirements for future optimization iterations.
- Current assumptions, uncertainties, and questions the user should answer before optimization starts.

The optimizer should also create a starter `ralph-loop.json` at the harness root. This config is used by `ralph-loop run --config ...` and should include orchestration settings such as `harness_path`, `goal`, `backend`, `max_iterations`, `evaluation_command`, `run_artifact_dir`, `command_timeout_seconds`, and `resume_behavior`.

The initial `RALPH_LOOP.md` draft should use placeholders rather than guessed file paths. Unless `--skip-ai-review` is used, `ralph-loop init` may call the configured backend to inspect the harness and refine `RALPH_LOOP.md` before optimization starts. This init-time review is still inside the explicit start boundary:

- It may update `RALPH_LOOP.md`.
- It may update `ralph-loop.json` only when configuration corrections are necessary.
- It must not edit optimization target files, tests, evaluators, datasets, or harness behavior.
- It must not create `ralph_loop_runs/` iteration artifacts.

After initialization and any init-time review, the optimizer should stop. Do not begin modifying the harness for optimization before the user explicitly runs `ralph-loop run --config ...`. The user should review and commit `RALPH_LOOP.md`, `ralph-loop.json`, and any other approved harness changes before starting so the harness worktree is clean.

# Iteration Lifecycle

Each optimization iteration should conceptually:

1. Read `RALPH_LOOP.md`.
2. Read the relevant harness instructions and docs.
3. Read prior iteration history and lessons.
4. Assemble a concise context pack for the selected coding CLI.
5. Ask the selected coding CLI to attempt an improvement in the harness repository.
6. Run or request the harness evaluation.
7. Capture performance output, logs, diffs, and relevant artifacts.
8. Write the implementation prompt, result record with evaluation output, diff, and a seed lesson under `ralph_loop_runs/`.
9. Ask the same coding CLI to update `lesson.md` from the implementation diff and evaluation feedback.
10. Commit the completed iteration in the harness Git repository.
11. Decide whether to continue based on configuration and results.

Backends must not create Git commits. Ralph Loop Optimizer owns staging and the final iteration commit. Implementation prompts should also tell backends not to run the evaluation command themselves; the optimizer runs or records evaluation after the implementation phase.

The optimizer should not invent domain instructions. Harness files, the user prompt, `RALPH_LOOP.md`, and accumulated lessons should drive the content of each iteration.

# Generated Harness Artifacts

Generated run artifacts should be visible in the harness repository.

Prefer this layout:

```text
RALPH_LOOP.md
ralph-loop.json
ralph_loop_runs/
  <run_id>/
    config.json
    iterations/
      001/
        prompt.md
        lesson_prompt.md
        result.md
        lesson.md
        diff.patch
```

The exact formats can evolve, but the responsibilities should stay clear:

- `RALPH_LOOP.md` is the human-readable operating brief.
- `ralph-loop.json` is the starter configuration used by `ralph-loop run`.
- `ralph_loop_runs/` stores run history, prompts, evaluation outputs, logs, diffs, results, and lessons.
- Git commits preserve experiment states for retrieval, comparison, and rollback.

Before starting an optimization run, check whether the harness worktree has uncommitted user changes. Do not silently mix optimizer experiments with unrelated user edits.

# Coding CLI Support

The current backend adapters are:

- `fake`: deterministic backend for dry runs and tests; it does not call an AI model.
- `codex`: Codex CLI backend using non-interactive `codex exec`.
- `claude`: Claude Code backend using non-interactive `claude --print`.

Do not describe unsupported backends as implemented. `opencode` is a reasonable future backend, but it should only be documented as supported after an adapter and tests exist.

Keep CLI-specific behavior isolated behind adapters or similarly narrow integration boundaries. Core orchestration should pass the same conceptual inputs to each backend:

- Harness working directory.
- Iteration prompt or task.
- `RALPH_LOOP.md` contents.
- Relevant harness instructions.
- Prior lessons.
- Latest evaluation feedback.
- Operational constraints.

Normalize backend outputs into common iteration records where practical. Avoid leaking one CLI's transcript format, command syntax, or session assumptions throughout the codebase.

# Lessons And History

Preserve both raw history and distilled lessons.

Raw history should include prompts, CLI outputs when available, evaluation outputs, diffs, command logs, scores, failures, and commits.

Lessons should be compact, reusable observations that can influence future iterations. A lesson should be linked to the iteration or evidence that produced it so later agents can judge whether it is reliable.

Avoid accumulating vague advice. Prefer evidence-backed lessons such as:

- "Increasing hidden layer width improved validation score but exceeded the time budget in iteration 004."
- "More aggressive early-position poker raises increased variance and reduced tournament score in iteration 003."

# Configuration Boundaries

Configuration should cover orchestration concerns, such as:

- Harness repository path.
- User optimization prompt.
- Coding CLI backend.
- Maximum iterations.
- Evaluation command or evaluation instructions.
- Stopping condition or target performance.
- Run artifact directory.
- Resume behavior.
- Optional command timeouts.

Keep domain-specific settings inside the harness unless the optimizer needs them to orchestrate the loop. Model search spaces, poker simulation parameters, benchmark settings, and scoring details should usually belong to the harness.

Current config files are JSON and are usually written to `ralph-loop.json` at the harness root during `init`. Per-run snapshots are written to `ralph_loop_runs/<run_id>/config.json`.

# Example Harness Guidelines

Example harnesses should live under an `examples/` directory when they are added.

Each example harness should be a folder, not a single file. It should demonstrate a complete external workflow with its own code, evaluation path, and instructions.

Good examples:

- A small ML training and evaluation workflow where the optimizer improves model architecture.
- A simple poker engine where the optimizer improves betting behavior.
- A toy benchmark that runs quickly and demonstrates the full loop.

Prefer examples that are deterministic, fast, and easy to inspect. Do not make the first examples heavy just to appear realistic.

Current example harnesses:

- `examples/toy-benchmark/`: dependency-free deterministic benchmark where the editable target is `strategy.py`.
- `examples/cifar10-cnn/`: PyTorch and torchvision CIFAR-10 harness where editable targets are `model.py` and `train_config.py`.
- `examples/us-stock-strategy/`: yfinance-based US stock strategy harness where the editable target is `strategy.py`.

# Development Commands

Use these commands when working on this repository:

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m pytest tests/test_real_cli_availability.py
RALPH_LOOP_RUN_REAL_AI_CLI=1 python -m pytest tests/test_real_cli_backends.py
```

The opt-in real CLI backend tests call installed AI CLIs and ask them to edit temporary harnesses. Do not run them by default unless the task specifically concerns real backend behavior or the user asks for that coverage.

# Current Implementation Limits

Keep these limits in mind during implementation:

- There is no standalone public `ralph-loop review` command. Init-time AI review is part of `ralph-loop init` unless `--skip-ai-review` is passed.
- There is no opencode backend adapter yet.
- There is no automatic metric extraction or target-based stopping condition yet.
- There is no hosted runner, remote push, pull request creation, or leaderboard integration yet.

# Desired Behavior From Coding Agents

## 1. Think Before Coding

Do not assume. Do not hide confusion. Surface tradeoffs.

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them. Do not pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what is confusing. Ask.

## 2. Simplicity First

Write the minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No flexibility or configurability that was not requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

- Do not improve adjacent code, comments, or formatting.
- Do not refactor things that are not broken.
- Match existing style, even if you would do it differently.
- If you notice unrelated dead code, mention it. Do not delete it.

When your changes create orphans:

- Remove imports, variables, functions, and files that your changes made unused.
- Do not remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

- "Add validation" means "write tests for invalid inputs, then make them pass."
- "Fix the bug" means "write a test that reproduces it, then make it pass."
- "Refactor X" means "ensure tests pass before and after."

For multi-step tasks, state a brief plan:

```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

Strong success criteria let you loop independently. Weak criteria such as "make it work" require clarification.
