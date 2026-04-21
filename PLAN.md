# Ralph Loop Optimizer Implementation Plan

## Implementation Goal

Build a local CLI tool that runs an AI-assisted optimization loop over a user-provided harness repository.

The tool should:

- Initialize a harness by inspecting it and writing `RALPH_LOOP.md`.
- Wait for explicit user approval before modifying the harness for optimization.
- Run bounded optimization iterations through a selected coding CLI backend.
- Run or record harness evaluation after each attempted improvement.
- Preserve prompts, backend output, evaluation output, diffs, lessons, artifacts, and Git commits.
- Keep orchestration generic and keep domain behavior inside harness repositories.

## MVP Definition Of Done

- `ralph-loop init` works on a local Git harness and creates `RALPH_LOOP.md`.
- `ralph-loop run` can complete at least one deterministic iteration with a fake backend and evaluation command.
- The run creates `ralph_loop_runs/<run_id>/iterations/001/` with prompt, evaluation, result, lesson, and diff artifacts.
- The harness Git repository receives an experiment commit for the completed iteration.
- At least one toy harness under `examples/` can be used in an end-to-end smoke test.
- The project has automated tests for the MVP path.

## Non-Goals For The First Implementation

- Do not build a hosted service, web UI, or remote job runner.
- Do not require a fixed evaluation output schema.
- Do not add domain-specific assumptions to core orchestration.
- Do not add remote push, pull request creation, or leaderboard integrations until the local loop works.

## Assumptions

- The first implementation should be a small Python CLI package. Python keeps local process orchestration, Git interaction, file inspection, and testing straightforward.
- The initial CLI should use standard library tools where practical. Add dependencies only when they remove real complexity.
- The optimizer owns orchestration only. Harness-specific training, scoring, metrics, and domain rules remain in the harness repository.
- `RALPH_LOOP.md` is created during initialization, then optimization waits for an explicit start command.
- A fixed evaluation output schema should not be required. The optimizer should capture whatever the harness emits.

## Implementation Order

- Foundation: Tasks 1-5 create the package, configuration, harness inspection, operating brief, and artifact layout.
- Execution path: Tasks 6-12 add backend adapters, iteration context, evaluation, Git handling, lessons, and the core loop.
- Reliability path: Tasks 13-16 add resume behavior, complete CLI coverage, toy harnesses, and end-to-end smoke testing.
- Documentation and release path: Tasks 17-20 update human docs, agent guidance, packaging, and later enhancements.

## Success Criteria

- A user can point the tool at a local Git harness repository and provide an optimization prompt.
- The tool can inspect the harness and create a useful `RALPH_LOOP.md`.
- The tool can run bounded optimization iterations through a selected coding CLI adapter.
- Each iteration records prompts, command outputs, evaluation output, diffs, lessons, and Git commits under `ralph_loop_runs/`.
- The implementation keeps CLI-specific behavior behind adapters and keeps domain-specific behavior inside harnesses.

## Task 1: Create Initial Codebase Scaffold [Importance: 10]

Goals:

- Establish the first actual implementation code in the repository.
- Create `pyproject.toml` with package metadata, supported Python version, console script entry point, and test tooling.
- Create `src/ralph_loop_optimizer/` with a minimal package layout.
- Create `tests/` with an initial smoke test.
- Add basic developer commands to `README.md` only after they exist and work.

Proposed files and functions:

- `src/ralph_loop_optimizer/__init__.py`
- `src/ralph_loop_optimizer/cli.py`
  - `main(argv: list[str] | None = None) -> int`
  - `build_parser() -> argparse.ArgumentParser`
- `tests/test_cli.py`
  - Verifies the CLI help command runs.

Verification:

- `python -m pytest`
- `python -m ralph_loop_optimizer.cli --help`

Status: Finished. The repository now has a Python package scaffold, console entry point, CLI smoke test, and verified developer commands.

## Task 2: Configuration Model [Importance: 9]

Goals:

- Define the orchestration configuration needed to initialize and run the loop.
- Validate harness paths, iteration limits, backend names, evaluation commands, timeout values, and artifact directory settings.
- Keep domain-specific settings out of optimizer configuration.

Proposed files and functions:

- `src/ralph_loop_optimizer/config.py`
  - `OptimizerConfig`
  - `load_config(path: Path) -> OptimizerConfig`
  - `write_config(config: OptimizerConfig, path: Path) -> None`
  - `validate_config(config: OptimizerConfig) -> None`
- `tests/test_config.py`
  - Covers valid config loading.
  - Covers invalid harness path, invalid max iterations, and unknown backend.

Verification:

- Config tests pass.
- Invalid configuration errors are clear and actionable.

Status: Finished. The repository now has an orchestration config dataclass, JSON load/write helpers, validation, and focused config tests.

## Task 3: Harness Repository Inspection [Importance: 10]

Goals:

- Inspect a user-provided local Git repository without making changes.
- Identify likely docs, setup files, test files, evaluation scripts, and agent instruction files.
- Summarize findings without embedding domain-specific assumptions.
- Detect whether the harness worktree has uncommitted changes before an optimization run starts.

Proposed files and functions:

- `src/ralph_loop_optimizer/harness.py`
  - `HarnessSummary`
  - `inspect_harness(repo_path: Path) -> HarnessSummary`
  - `find_candidate_docs(repo_path: Path) -> list[Path]`
  - `find_candidate_evaluation_files(repo_path: Path) -> list[Path]`
  - `read_harness_instructions(repo_path: Path) -> dict[Path, str]`
  - `assert_git_repository(repo_path: Path) -> None`
  - `get_worktree_status(repo_path: Path) -> WorktreeStatus`
- `tests/test_harness.py`
  - Uses temporary Git repositories.
  - Covers docs detection, evaluation file detection, instruction file detection, and dirty worktree detection.

Verification:

- Tests create a temporary harness and confirm inspection output is stable.
- Dirty worktree detection refuses to start optimization unless configured resume behavior allows it.

Status: Finished. The repository now has read-only harness inspection, candidate file discovery, instruction reading, worktree status detection, and temporary Git repository tests.

## Task 4: Operating Brief Initialization [Importance: 10]

Goals:

- Generate `RALPH_LOOP.md` at the harness repository root.
- Include the user optimization goal, harness summary, candidate evaluation commands/files, relevant docs, assumptions, uncertainties, and questions for the user.
- Avoid starting optimization during initialization.
- Preserve existing `RALPH_LOOP.md` unless the user explicitly chooses overwrite or resume behavior.

Proposed files and functions:

- `src/ralph_loop_optimizer/brief.py`
  - `build_operating_brief(config: OptimizerConfig, summary: HarnessSummary) -> str`
  - `write_operating_brief(repo_path: Path, content: str, overwrite: bool = False) -> Path`
  - `brief_exists(repo_path: Path) -> bool`
- CLI command:
  - `ralph-loop init --harness PATH --goal TEXT [--evaluation-command TEXT]`
- `tests/test_brief.py`
  - Covers generated sections.
  - Covers no overwrite by default.

Verification:

- Running `init` on a sample harness creates `RALPH_LOOP.md`.
- The command exits before any harness modification beyond the brief.

Status: Finished. The repository now generates `RALPH_LOOP.md` through `ralph-loop init`, preserves existing briefs by default, and tests the explicit initialization boundary.

## Task 5: Run Artifact Layout [Importance: 9]

Goals:

- Create visible run artifact folders inside the harness repository.
- Store run configuration and per-iteration records under `ralph_loop_runs/<run_id>/`.
- Use simple text-first formats that are easy for users and agents to inspect.

Proposed files and functions:

- `src/ralph_loop_optimizer/artifacts.py`
  - `RunPaths`
  - `IterationPaths`
  - `create_run_paths(repo_path: Path, run_id: str) -> RunPaths`
  - `create_iteration_paths(run_paths: RunPaths, iteration_number: int) -> IterationPaths`
  - `write_text_artifact(path: Path, content: str, *, repo_path: Path) -> None`
  - `write_json_artifact(path: Path, data: object, *, repo_path: Path) -> None`
  - `copy_artifact(source: Path, destination: Path, *, repo_path: Path) -> None`
- Artifact files:
  - `config.json`
  - `iterations/001/prompt.md`
  - `iterations/001/evaluation.txt`
  - `iterations/001/result.md`
  - `iterations/001/lesson.md`
  - `iterations/001/diff.patch`

Verification:

- Tests confirm path creation and zero-padded iteration directories.
- Tests confirm artifact writes do not escape the harness repository.

Status: Finished. The repository now has run and iteration artifact path helpers, text/JSON/copy writers, zero-padded iteration directories, and safety checks that reject artifact writes outside a Git harness repository.

## Task 6: Coding CLI Adapter Interface [Importance: 9]

Goals:

- Define a narrow adapter contract for coding backends.
- Keep Codex, opencode, and Claude Code command details out of the core loop.
- Normalize backend results into common iteration records.

Proposed files and functions:

- `src/ralph_loop_optimizer/backends/base.py`
  - `BackendRequest`
  - `BackendResult`
  - `CodingBackend`
  - `run_backend(request: BackendRequest) -> BackendResult`
- `src/ralph_loop_optimizer/backends/registry.py`
  - `get_backend(name: str) -> CodingBackend`
  - `list_backends() -> list[str]`
- `tests/test_backends.py`
  - Uses a fake backend for deterministic tests.

Verification:

- Core orchestration tests can run with a fake backend.
- Unknown backend names fail before any harness changes are made.

Status: Finished. The repository now has a backend adapter contract, normalized backend result type, registry helpers, and a deterministic fake backend for future orchestration tests.

## Task 7: Concrete Backend Adapters [Importance: 7]

Goals:

- Add initial adapters for supported coding CLIs.
- Pass the same conceptual inputs to each backend: harness path, iteration prompt, `RALPH_LOOP.md`, relevant harness instructions, prior lessons, latest evaluation feedback, and operational constraints.
- Capture stdout, stderr, exit code, elapsed time, and transcript paths when available.

Proposed files and functions:

- `src/ralph_loop_optimizer/backends/codex.py`
  - `CodexBackend`
  - `build_codex_command(request: BackendRequest) -> list[str]`
- `src/ralph_loop_optimizer/backends/opencode.py`
  - `OpenCodeBackend`
  - `build_opencode_command(request: BackendRequest) -> list[str]`
- `src/ralph_loop_optimizer/backends/claude.py`
  - `ClaudeCodeBackend`
  - `build_claude_command(request: BackendRequest) -> list[str]`
- `src/ralph_loop_optimizer/processes.py`
  - `CommandResult`
  - `run_command(command: list[str], cwd: Path, timeout_seconds: int | None) -> CommandResult`

Verification:

- Unit tests verify command construction without requiring the CLIs to be installed.
- Integration tests for real CLIs are optional and skipped when binaries are missing.

Status: Finished. The repository now has non-interactive Codex and Claude Code backend adapters, a shared subprocess runner with timeout and missing-binary handling, backend registry wiring, and tests for command construction plus subprocess invocation through fake CLI binaries.

## Task 8: Iteration Context Assembly [Importance: 9]

Goals:

- Build concise prompts for each optimization iteration.
- Include evidence from `RALPH_LOOP.md`, selected harness docs, prior lessons, latest evaluation output, current Git status, and constraints.
- Avoid inventing domain instructions.

Proposed files and functions:

- `src/ralph_loop_optimizer/context.py`
  - `IterationContext`
  - `load_operating_brief(repo_path: Path) -> str`
  - `load_prior_lessons(run_paths: RunPaths) -> list[str]`
  - `load_latest_evaluation(run_paths: RunPaths) -> str | None`
  - `build_iteration_prompt(config: OptimizerConfig, context: IterationContext) -> str`
- `tests/test_context.py`
  - Covers prompt content and omission of missing optional context.
  - Confirms prior lessons are linked to iteration evidence.

Verification:

- Generated prompts include orchestration constraints and relevant harness evidence.
- Generated prompts do not include hard-coded ML, poker, benchmark, or leaderboard assumptions.

Status: Finished. The repository now has read-only operating brief, prior lesson, and latest evaluation loaders plus deterministic iteration prompt assembly with focused context tests.

## Task 9: Evaluation Runner [Importance: 10]

Goals:

- Run the configured harness evaluation command after a backend attempts an improvement.
- Capture stdout, stderr, exit code, elapsed time, and any configured output file paths.
- Support cases where evaluation is manual or instruction-only by recording that user evaluation is required.
- Avoid enforcing a fixed metric schema.

Proposed files and functions:

- `src/ralph_loop_optimizer/evaluation.py`
  - `EvaluationRequest`
  - `EvaluationResult`
  - `run_evaluation(request: EvaluationRequest) -> EvaluationResult`
  - `format_evaluation_result(result: EvaluationResult) -> str`
  - `requires_manual_evaluation(config: OptimizerConfig) -> bool`
- `tests/test_evaluation.py`
  - Covers successful command, failing command, timeout, and manual evaluation mode.

Verification:

- Evaluation output is saved even when the command fails.
- A failing evaluation produces a recorded iteration result rather than losing context.

Status: Finished. The repository now has command and manual evaluation execution, stdout/stderr/exit-code/timeout capture, optional output-file capture, plain-text result formatting, and focused evaluation tests.

## Task 10: Diff And Git Commit Handling [Importance: 9]

Goals:

- Capture the harness diff for each iteration.
- Commit experiment changes in the harness repository after artifacts are recorded.
- Refuse to mix optimizer changes with unrelated uncommitted user edits.
- Record commit hashes in iteration results.

Proposed files and functions:

- `src/ralph_loop_optimizer/git.py`
  - `GitStatus`
  - `get_status(repo_path: Path) -> GitStatus`
  - `get_diff(repo_path: Path) -> str`
  - `stage_paths(repo_path: Path, paths: list[Path]) -> None`
  - `commit(repo_path: Path, message: str) -> str`
  - `current_head(repo_path: Path) -> str`
- `tests/test_git.py`
  - Uses temporary Git repositories.
  - Covers diff capture, commit creation, and dirty worktree refusal.

Verification:

- Each completed iteration creates a Git commit in the harness repository.
- The saved `diff.patch` matches the committed experiment.

Status: Finished. The repository now has Git status, clean-worktree refusal, diff capture including untracked files, path-safe staging, commit creation, current HEAD lookup, and temporary-repository Git tests.

## Task 11: Lesson Distillation [Importance: 8]

Goals:

- Produce compact, evidence-backed lessons after each iteration.
- Link each lesson to iteration number, evaluation output, diff, and commit hash.
- Avoid vague advice and preserve uncertainty when results are inconclusive.

Proposed files and functions:

- `src/ralph_loop_optimizer/lessons.py`
  - `Lesson`
  - `distill_lesson(iteration_record: IterationRecord) -> str`
  - `load_lessons(run_paths: RunPaths) -> list[Lesson]`
  - `format_lessons_for_prompt(lessons: list[Lesson]) -> str`
- `tests/test_lessons.py`
  - Covers lesson formatting and evidence links.
  - Covers inconclusive and failed evaluations.

Verification:

- `lesson.md` is created for every iteration.
- Future iteration prompts include compact prior lessons.

Status: Finished. The repository now has deterministic lesson distillation from iteration evidence, lesson loading, prompt formatting helpers, and focused tests for successful, failed, manual, timed-out, and inconclusive evaluation outcomes.

## Task 12: Core Orchestration Loop [Importance: 10]

Goals:

- Connect configuration, context assembly, backend execution, evaluation, artifact recording, lesson distillation, Git diff capture, and commit creation.
- Enforce maximum iterations and stopping condition checks.
- Keep loop state resumable from recorded artifacts.

Proposed files and functions:

- `src/ralph_loop_optimizer/orchestrator.py`
  - `IterationRecord`
  - `RunState`
  - `initialize_run(config: OptimizerConfig) -> RunState`
  - `run_iteration(state: RunState) -> IterationRecord`
  - `run_loop(config: OptimizerConfig) -> RunState`
  - `should_continue(state: RunState) -> bool`
  - `check_stopping_condition(state: RunState) -> bool`
- CLI command:
  - `ralph-loop run --config PATH`
- `tests/test_orchestrator.py`
  - Uses fake backend and fake evaluation command.
  - Covers one successful iteration.
  - Covers max iteration stopping.
  - Covers failed backend or evaluation handling.

Verification:

- A fake end-to-end run creates the expected artifact tree and commit.
- The loop stops at the configured iteration limit.

Status: Finished. The repository now has a core orchestrator that initializes runs, builds iteration prompts, executes the selected backend, runs evaluation, writes prompt/evaluation/result/lesson/diff artifacts, commits completed iterations, exposes `ralph-loop run --config PATH`, and tests successful, failed-evaluation, failed-backend, and max-iteration paths with a fake backend.

## Task 13: Resume Behavior [Importance: 6]

Goals:

- Resume an interrupted run from `ralph_loop_runs/<run_id>/`.
- Detect completed and incomplete iterations.
- Continue from the next safe iteration number.
- Avoid overwriting existing artifacts.

Proposed files and functions:

- `src/ralph_loop_optimizer/resume.py`
  - `discover_runs(repo_path: Path) -> list[RunPaths]`
  - `load_run_state(run_paths: RunPaths) -> RunState`
  - `find_last_complete_iteration(run_paths: RunPaths) -> int`
  - `validate_resume_state(run_paths: RunPaths) -> None`
- CLI command:
  - `ralph-loop resume --harness PATH --run-id ID`
- `tests/test_resume.py`
  - Covers complete runs, partial iterations, missing files, and next iteration numbering.

Verification:

- Resume continues from the next iteration without replacing previous records.
- Resume refuses ambiguous or corrupted state with a clear message.

Status: Not finished.

## Task 14: User-Facing CLI Commands [Importance: 9]

Goals:

- Provide clear commands for initialization, running, resuming, inspecting status, and listing supported backends.
- Keep command output concise and actionable.
- Make dry-run style inspection possible before starting optimization.

Proposed commands:

- `ralph-loop init --harness PATH --goal TEXT [--evaluation-command TEXT]`
- `ralph-loop run --config PATH`
- `ralph-loop resume --harness PATH --run-id ID`
- `ralph-loop status --harness PATH [--run-id ID]`
- `ralph-loop backends`

Proposed files and functions:

- `src/ralph_loop_optimizer/cli.py`
  - `cmd_init(args: argparse.Namespace) -> int`
  - `cmd_run(args: argparse.Namespace) -> int`
  - `cmd_resume(args: argparse.Namespace) -> int`
  - `cmd_status(args: argparse.Namespace) -> int`
  - `cmd_backends(args: argparse.Namespace) -> int`

Verification:

- CLI tests cover every command's success and common failure paths.
- Help output explains the explicit start boundary after initialization.

Status: Not finished.

## Task 14A: Guided Setup And Brief Consolidation [Importance: 10]

Goals:

- Make the required user workflow explicit and copy-paste runnable from the documentation.
- Automate starter configuration creation so users do not have to manually write the JSON file required by `ralph-loop run --config PATH`.
- Use a selected backend AI CLI before the optimization loop to help the user review, question, and consolidate `RALPH_LOOP.md`.
- Preserve the explicit start boundary: pre-loop brief consolidation may edit `RALPH_LOOP.md` and configuration, but it must not modify optimization target files or start iterations.

Proposed workflow:

1. `ralph-loop init --harness PATH --goal TEXT [--evaluation-command TEXT]`
   creates `RALPH_LOOP.md` and a starter config file such as `ralph-loop.json`.
2. The user selects or edits the backend in the generated config, for example
   `fake`, `codex`, or `claude`.
3. A pre-loop review command uses the selected backend to inspect the harness,
   ask the user clarification questions, and update `RALPH_LOOP.md` with the
   agreed operating brief.
4. The user explicitly starts optimization with
   `ralph-loop run --config PATH`.

Proposed commands:

- `ralph-loop init --harness PATH --goal TEXT [--evaluation-command TEXT] [--backend NAME]`
- `ralph-loop review --config PATH`
- `ralph-loop run --config PATH`

Proposed files and functions:

- `src/ralph_loop_optimizer/config.py`
  - `default_config_path(repo_path: Path) -> Path`
  - `build_starter_config(...) -> OptimizerConfig`
- `src/ralph_loop_optimizer/brief_review.py`
  - `BriefReviewRequest`
  - `BriefReviewResult`
  - `build_brief_review_prompt(config: OptimizerConfig, summary: HarnessSummary, brief: str) -> str`
  - `apply_brief_review_result(repo_path: Path, result: BriefReviewResult) -> Path`
- `src/ralph_loop_optimizer/cli.py`
  - `cmd_init(...)` writes both `RALPH_LOOP.md` and the starter config.
  - `cmd_review(...)` invokes the configured backend for pre-loop brief review.

Documentation requirements:

- Show the complete sequence from example harness copy, Git initialization,
  dependency installation, `ralph-loop init`, config review, brief review, and
  `ralph-loop run`.
- Explain that example folders are templates and must be copied into their own
  harness Git repository before use.
- Explain which values users are expected to edit, especially `backend`,
  `max_iterations`, `evaluation_command`, and command timeouts.
- Clearly distinguish pre-loop brief consolidation from optimization
  iterations.

Verification:

- CLI tests confirm `init` writes a valid starter config without starting
  optimization.
- Tests confirm `review` can run with the fake backend and update or preserve
  `RALPH_LOOP.md` without touching harness target files.
- README commands are copy-paste runnable for the example harness workflow.
- `run` continues to require an explicit user command after review completes.

Status: Finished. The repository now writes a starter `ralph-loop.json` during `init`, supports backend selection for initialization, adds a pre-loop `review` command that invokes the configured backend within the explicit start boundary, checks that review only leaves `RALPH_LOOP.md` and the starter config dirty, documents the generated-config workflow, and tests the fake-backend review path plus running from the generated config.

## Task 15: Toy Harness Folders [Importance: 8]

Goals:

- Add deterministic, fast toy harness folders under `examples/`.
- Make each harness a complete external workflow with its own code, evaluation command, and instructions.
- Use the harnesses to prove the optimizer remains generic across different domains and output formats.
- Keep every example small enough that tests or demos can run quickly.

Proposed initial harness:

- `examples/toy-benchmark/README.md`
- `examples/toy-benchmark/AGENTS.md`
- `examples/toy-benchmark/strategy.py`
- `examples/toy-benchmark/evaluate.py`
- `examples/toy-benchmark/tests/`

Possible additional harnesses after the first one works:

- `examples/config-search/`
  - A small deterministic scoring harness where the optimizer changes config values.
  - Useful for testing non-code-heavy optimization loops.
- `examples/simple-policy-game/`
  - A small deterministic policy harness where the optimizer changes a policy function.
  - Useful for testing strategy iteration without adding heavy simulation dependencies.

Verification:

- Each example evaluation command runs in a few seconds.
- Each example includes clear instructions about what may and may not be changed.
- The optimizer can initialize against each example and generate `RALPH_LOOP.md`.
- At least one example is used by the end-to-end smoke test.

Status: Not finished.

## Task 16: End-To-End Smoke Test [Importance: 9]

Goals:

- Exercise the full lifecycle on one toy harness using a fake backend.
- Verify initialization, explicit run start, iteration artifact creation, evaluation capture, lesson creation, and Git commit creation.
- Keep this test deterministic and fast.

Proposed files and functions:

- `tests/test_end_to_end.py`
  - `test_init_then_single_iteration_with_fake_backend()`

Verification:

- The test passes from a clean checkout.
- The test does not require external coding CLIs or network access.

Status: Not finished.

## Task 17: Documentation For Human Users [Importance: 7]

Goals:

- Update `README.md` with commands only after they are implemented.
- Explain the initialization and explicit start lifecycle.
- Explain generated artifacts and how to inspect them.
- Explain supported backends and evaluation command expectations.

Proposed docs:

- Installation from source.
- Quick start with `examples/toy-benchmark`.
- Configuration reference.
- Artifact layout reference.
- Backend setup notes.

Verification:

- README commands are copy-paste runnable.
- Documentation preserves the distinction between human-facing usage and agent-facing development guidance.

Status: Not finished.

## Task 18: Agent-Facing Development Guidance Maintenance [Importance: 6]

Goals:

- Keep `AGENTS.md` aligned with actual implementation choices as the project evolves.
- Add repository-specific development commands after they exist.
- Keep product boundaries, artifact responsibilities, and harness separation clear.

Verification:

- `AGENTS.md` remains about agent development requirements.
- `README.md` remains about user-facing behavior.

Status: Partially finished. The initial guidance exists, but implementation-specific commands and conventions are not yet available.

## Task 19: Packaging And Release Readiness [Importance: 5]

Goals:

- Make the package installable from source.
- Define license metadata and project classifiers.
- Ensure source distributions include examples and documentation where appropriate.
- Add versioning guidance.

Proposed files and functions:

- `pyproject.toml`
- `src/ralph_loop_optimizer/__init__.py`
  - `__version__`

Verification:

- `python -m build` succeeds once build tooling is configured.
- Installing the local package exposes the `ralph-loop` command.

Status: Not finished.

## Task 20: Optional Future Enhancements [Importance: 2]

Goals:

- Capture richer backend transcripts where each CLI supports it.
- Add structured metric extraction as an optional helper without requiring a schema.
- Add configurable artifact retention policies.
- Add optional remote push or pull request creation after runs.
- Add richer stopping conditions based on user-provided evaluators.

Verification:

- Each enhancement should be introduced only after the core loop works.
- Each enhancement should remain optional and avoid domain-specific assumptions.

Status: Not finished.
