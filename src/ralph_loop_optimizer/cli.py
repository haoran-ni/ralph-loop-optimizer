"""Command line entry point for Ralph Loop Optimizer."""

from __future__ import annotations

import argparse
from pathlib import Path

from ralph_loop_optimizer import __version__
from ralph_loop_optimizer.artifacts import RunPaths
from ralph_loop_optimizer.brief import (
    BriefError,
    brief_exists,
    build_operating_brief,
    write_operating_brief,
)
from ralph_loop_optimizer.brief_review import (
    BriefReviewError,
    BriefReviewRequest,
    run_brief_review,
)
from ralph_loop_optimizer.backends import BackendError, list_backends
from ralph_loop_optimizer.config import (
    ConfigError,
    build_starter_config,
    default_config_path,
    load_config,
    write_config,
)
from ralph_loop_optimizer.context import ContextError
from ralph_loop_optimizer.evaluation import EvaluationError
from ralph_loop_optimizer.git import GitError, get_status
from ralph_loop_optimizer.harness import HarnessError, inspect_harness
from ralph_loop_optimizer.orchestrator import OrchestratorError, run_loop
from ralph_loop_optimizer.progress import ProgressReporter
from ralph_loop_optimizer.resume import (
    ResumeError,
    discover_runs,
    load_run_state,
    resume_loop,
)

INIT_REVIEW_COMMIT_REMINDER = (
    "Please commit the new files after finishing your review. The harness repo "
    "is required to be clean before running the ralph loop optimizer."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ralph-loop",
        description=(
            "Run AI-assisted optimization loops over local harness repositories."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser(
        "init",
        help="inspect a harness and create RALPH_LOOP.md",
        description=(
            "Inspect a local harness repository, create RALPH_LOOP.md, "
            "optionally ask the configured backend to refine it, and stop "
            "without starting optimization."
        ),
    )
    init_parser.add_argument(
        "--harness",
        required=True,
        type=Path,
        help="path to the harness Git repository root",
    )
    init_parser.add_argument(
        "--goal",
        required=True,
        help="optimization goal to capture in RALPH_LOOP.md",
    )
    init_parser.add_argument(
        "--evaluation-command",
        help="optional harness evaluation command to capture in the starter config",
    )
    init_parser.add_argument(
        "--backend",
        default="fake",
        help="coding backend to use for init review and write into the starter config",
    )
    init_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing RALPH_LOOP.md and starter config",
    )
    init_parser.add_argument(
        "--skip-ai-review",
        action="store_true",
        help=(
            "write the draft files without asking the configured backend to "
            "refine RALPH_LOOP.md"
        ),
    )
    init_parser.set_defaults(func=cmd_init)

    run_parser = subparsers.add_parser(
        "run",
        help="run a bounded optimization loop from a config file",
        description=(
            "Run optimization iterations from a JSON config file. "
            "Run init and inspect or edit RALPH_LOOP.md before using this command."
        ),
    )
    run_parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="path to a Ralph Loop Optimizer JSON config file",
    )
    run_parser.set_defaults(func=cmd_run)

    resume_parser = subparsers.add_parser(
        "resume",
        help="resume an existing optimization run",
        description=(
            "Resume an existing run from ralph_loop_runs/<run_id>. "
            "The run state must be complete and the harness worktree must be clean."
        ),
    )
    resume_parser.add_argument(
        "--harness",
        required=True,
        type=Path,
        help="path to the harness Git repository root",
    )
    resume_parser.add_argument(
        "--run-id",
        required=True,
        help="run id under ralph_loop_runs",
    )
    resume_parser.set_defaults(func=cmd_resume)

    status_parser = subparsers.add_parser(
        "status",
        help="inspect a harness and recorded optimization runs",
        description=(
            "Inspect a harness repository, starter files, worktree status, "
            "and recorded Ralph Loop runs without starting optimization."
        ),
    )
    status_parser.add_argument(
        "--harness",
        required=True,
        type=Path,
        help="path to the harness Git repository root",
    )
    status_parser.add_argument(
        "--run-id",
        help="optional run id under ralph_loop_runs to inspect in detail",
    )
    status_parser.set_defaults(func=cmd_status)

    backends_parser = subparsers.add_parser(
        "backends",
        help="list supported coding backends",
        description="List the coding backends accepted by optimizer configs.",
    )
    backends_parser.set_defaults(func=cmd_backends)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    config = build_starter_config(
        harness_path=args.harness,
        goal=args.goal,
        backend=args.backend,
        evaluation_command=args.evaluation_command,
    )
    summary = inspect_harness(config.harness_path)
    config_path = default_config_path(summary.repo_path)

    if brief_exists(summary.repo_path) and not args.overwrite:
        raise BriefError(
            "RALPH_LOOP.md already exists; pass --overwrite to replace it"
        )
    if config_path.is_symlink():
        raise ConfigError(f"{config_path.name} must not be a symlink")
    if config_path.exists() and not args.overwrite:
        raise ConfigError(
            f"{config_path.name} already exists; pass --overwrite to replace it"
        )

    content = build_operating_brief(config, summary)
    brief_path = write_operating_brief(
        summary.repo_path,
        content,
        overwrite=args.overwrite,
    )
    write_config(config, config_path)

    print(f"Created {brief_path}")
    print(f"Created {config_path}")
    if args.skip_ai_review:
        print("Skipped AI review during init.")
        print(
            "Optimization was not started. Review RALPH_LOOP.md and the starter "
            "config before running."
        )
        print(INIT_REVIEW_COMMIT_REMINDER)
        return 0

    result = run_brief_review(
        BriefReviewRequest(
            config=config,
            config_path=config_path,
            summary=summary,
            brief=content,
        ),
        progress=ProgressReporter(),
    )
    print(f"AI review backend: {result.backend_result.backend_name}")
    print(f"AI review succeeded: {'yes' if result.succeeded else 'no'}")
    if result.changed_paths:
        print("Changed init files:")
        for path in result.changed_paths:
            print(f"- {path.as_posix()}")
    else:
        print("Changed init files: none")
    print(
        "Optimization was not started. Review RALPH_LOOP.md and the starter "
        "config before running."
    )
    print(INIT_REVIEW_COMMIT_REMINDER)
    return 0 if result.succeeded else 1


def cmd_run(args: argparse.Namespace) -> int:
    state = run_loop(load_config(args.config), progress=ProgressReporter())
    print(f"Run {state.run_paths.run_id} completed.")
    print(f"Iterations completed: {len(state.completed_iterations)}")
    if state.completed_iterations:
        latest = state.completed_iterations[-1]
        print(f"Latest experiment commit: {latest.commit_hash}")
        print(f"Latest artifact commit: {latest.artifact_commit_hash}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    state = resume_loop(args.harness, args.run_id, progress=ProgressReporter())
    print(f"Run {state.run_paths.run_id} resumed.")
    print(f"Iterations completed: {len(state.completed_iterations)}")
    if state.completed_iterations:
        latest = state.completed_iterations[-1]
        print(f"Latest experiment commit: {latest.commit_hash}")
        print(f"Latest artifact commit: {latest.artifact_commit_hash}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo_path = args.harness.expanduser().resolve()
    inspect_harness(repo_path)
    status = get_status(repo_path)
    config_path = default_config_path(repo_path)
    runs = discover_runs(repo_path)

    print(f"Harness: {repo_path}")
    print(f"Git worktree: {'dirty' if status.is_dirty else 'clean'}")
    if status.is_dirty:
        print("Uncommitted changes:")
        for entry in status.entries:
            print(f"- {entry}")
    print(f"RALPH_LOOP.md: {'present' if brief_exists(repo_path) else 'missing'}")
    config_state = "present" if config_path.is_file() else "missing"
    print(f"{config_path.name}: {config_state}")

    if args.run_id is not None:
        run_paths = _select_run(runs, args.run_id)
        return _print_run_detail(run_paths)

    print(f"Runs discovered: {len(runs)}")
    for run_paths in runs:
        print(_format_run_summary(run_paths))
    return 0


def cmd_backends(args: argparse.Namespace) -> int:
    del args
    backends = list_backends()
    real_backends = [name for name in backends if name != "fake"]
    print("Real coding backends:")
    for name in real_backends:
        print(f"- {name}")
    if "fake" in backends:
        print("Test backend:")
        print("- fake")
    return 0


def _select_run(runs: list[RunPaths], run_id: str) -> RunPaths:
    for run_paths in runs:
        if run_paths.run_id == run_id:
            return run_paths
    raise ResumeError(f"run does not exist: {run_id}")


def _print_run_detail(run_paths: RunPaths) -> int:
    try:
        state = load_run_state(run_paths)
    except ResumeError as exc:
        print(f"Run: {run_paths.run_id}")
        print("Run status: invalid")
        print(f"Detail: {exc}")
        return 1

    print(f"Run: {state.run_paths.run_id}")
    print("Run status: valid")
    print(f"Run config: {state.run_paths.config_path}")
    print(f"Completed iterations: {len(state.completed_iterations)}")
    print(f"Next iteration: {state.next_iteration_number}")
    print(f"Maximum iterations: {state.config.max_iterations}")
    return 0


def _format_run_summary(run_paths: RunPaths) -> str:
    try:
        state = load_run_state(run_paths)
    except ResumeError as exc:
        return f"- {run_paths.run_id}: invalid ({exc})"

    completed = len(state.completed_iterations)
    return (
        f"- {state.run_paths.run_id}: {completed} completed iteration(s), "
        f"next {state.next_iteration_number} of {state.config.max_iterations}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = getattr(args, "func", None)
    if command is None:
        return 0
    try:
        return command(args)
    except (
        BackendError,
        BriefError,
        BriefReviewError,
        ConfigError,
        ContextError,
        EvaluationError,
        GitError,
        HarnessError,
        OrchestratorError,
        ResumeError,
    ) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
