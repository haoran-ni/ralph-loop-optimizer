"""Command line entry point for Ralph Loop Optimizer."""

from __future__ import annotations

import argparse
from pathlib import Path

from ralph_loop_optimizer import __version__
from ralph_loop_optimizer.brief import (
    BriefError,
    build_operating_brief,
    write_operating_brief,
)
from ralph_loop_optimizer.backends import BackendError
from ralph_loop_optimizer.config import (
    ConfigError,
    OptimizerConfig,
    load_config,
    validate_config,
)
from ralph_loop_optimizer.context import ContextError
from ralph_loop_optimizer.evaluation import EvaluationError
from ralph_loop_optimizer.git import GitError
from ralph_loop_optimizer.harness import HarnessError, inspect_harness
from ralph_loop_optimizer.orchestrator import OrchestratorError, run_loop


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
            "Inspect a local harness repository and create RALPH_LOOP.md "
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
        help="optional harness evaluation command to capture in the brief",
    )
    init_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing RALPH_LOOP.md",
    )
    init_parser.set_defaults(func=cmd_init)

    run_parser = subparsers.add_parser(
        "run",
        help="run a bounded optimization loop from a config file",
        description=(
            "Run optimization iterations from a JSON config file. "
            "Run init and review RALPH_LOOP.md before using this command."
        ),
    )
    run_parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="path to a Ralph Loop Optimizer JSON config file",
    )
    run_parser.set_defaults(func=cmd_run)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    config = OptimizerConfig(
        harness_path=args.harness,
        goal=args.goal,
        evaluation_command=args.evaluation_command,
    )
    validate_config(config)
    summary = inspect_harness(config.harness_path)
    content = build_operating_brief(config, summary)
    brief_path = write_operating_brief(
        summary.repo_path,
        content,
        overwrite=args.overwrite,
    )
    print(f"Created {brief_path}")
    print("Optimization was not started. Review RALPH_LOOP.md before running.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    state = run_loop(load_config(args.config))
    print(f"Run {state.run_paths.run_id} completed.")
    print(f"Iterations completed: {len(state.completed_iterations)}")
    if state.completed_iterations:
        latest = state.completed_iterations[-1]
        print(f"Latest experiment commit: {latest.commit_hash}")
        print(f"Latest artifact commit: {latest.artifact_commit_hash}")
    return 0


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
        ConfigError,
        ContextError,
        EvaluationError,
        GitError,
        HarnessError,
        OrchestratorError,
    ) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
