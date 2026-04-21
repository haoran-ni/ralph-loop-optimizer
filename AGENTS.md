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
- What the harness appears to do.
- How evaluation appears to work.
- Which files, commands, docs, or workflows seem relevant.
- The expected iteration process.
- Current assumptions and uncertainties.
- Any questions the user should answer before optimization starts.

After creating `RALPH_LOOP.md`, the optimizer should allow the conversation to continue until the user sends an explicit start message. Do not begin modifying the harness for optimization before that explicit approval.

# Iteration Lifecycle

Each optimization iteration should conceptually:

1. Read `RALPH_LOOP.md`.
2. Read the relevant harness instructions and docs.
3. Read prior iteration history and lessons.
4. Assemble a concise context pack for the selected coding CLI.
5. Ask the selected coding CLI to attempt an improvement in the harness repository.
6. Run or request the harness evaluation.
7. Capture performance output, logs, diffs, and relevant artifacts.
8. Distill lessons from the result.
9. Save iteration artifacts under `ralph_loop_runs/`.
10. Commit the experiment in the harness Git repository.
11. Decide whether to continue based on configuration and results.

The optimizer should not invent domain instructions. Harness files, the user prompt, `RALPH_LOOP.md`, and accumulated lessons should drive the content of each iteration.

# Generated Harness Artifacts

Generated run artifacts should be visible in the harness repository.

Prefer this layout:

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

The exact formats can evolve, but the responsibilities should stay clear:

- `RALPH_LOOP.md` is the human-readable operating brief.
- `ralph_loop_runs/` stores run history, evaluation outputs, logs, diffs, and lessons.
- Git commits preserve experiment states for retrieval, comparison, and rollback.

Before starting an optimization run, check whether the harness worktree has uncommitted user changes. Do not silently mix optimizer experiments with unrelated user edits.

# Coding CLI Support

The optimizer should support popular coding CLIs such as Codex, opencode, and Claude Code.

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

# Example Harness Guidelines

Example harnesses should live under an `examples/` directory when they are added.

Each example harness should be a folder, not a single file. It should demonstrate a complete external workflow with its own code, evaluation path, and instructions.

Good examples:

- A small ML training and evaluation workflow where the optimizer improves model architecture.
- A simple poker engine where the optimizer improves betting behavior.
- A toy benchmark that runs quickly and demonstrates the full loop.

Prefer examples that are deterministic, fast, and easy to inspect. Do not make the first examples heavy just to appear realistic.

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
