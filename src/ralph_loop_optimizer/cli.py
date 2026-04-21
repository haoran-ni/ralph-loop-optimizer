"""Command line entry point for Ralph Loop Optimizer."""

from __future__ import annotations

import argparse
from pathlib import Path

from ralph_loop_optimizer import __version__
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
from ralph_loop_optimizer.backends import BackendError
from ralph_loop_optimizer.config import (
    ConfigError,
    build_starter_config,
    default_config_path,
    load_config,
    write_config,
)
from ralph_loop_optimizer.context import ContextError, load_operating_brief
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
        "--backend",
        default="fake",
        help="coding backend to write into the starter config",
    )
    init_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing RALPH_LOOP.md and starter config",
    )
    init_parser.set_defaults(func=cmd_init)

    review_parser = subparsers.add_parser(
        "review",
        help="review and consolidate RALPH_LOOP.md before optimization",
        description=(
            "Use the configured backend to review RALPH_LOOP.md before any "
            "optimization iterations start. The review boundary allows edits "
            "only to RALPH_LOOP.md and the starter config file."
        ),
    )
    review_parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="path to a Ralph Loop Optimizer JSON config file",
    )
    review_parser.set_defaults(func=cmd_review)

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
    print(
        "Optimization was not started. Review RALPH_LOOP.md and the starter "
        "config before running."
    )
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    config_path = args.config.expanduser().resolve()
    config = load_config(config_path)
    summary = inspect_harness(config.harness_path)
    result = run_brief_review(
        BriefReviewRequest(
            config=config,
            config_path=config_path,
            summary=summary,
            brief=load_operating_brief(summary.repo_path),
        )
    )

    print(f"Review backend: {result.backend_result.backend_name}")
    print(f"Review succeeded: {'yes' if result.succeeded else 'no'}")
    print(f"Brief: {result.brief_path}")
    print(f"Config: {result.config_path}")
    if result.changed_paths:
        print("Changed review files:")
        for path in result.changed_paths:
            print(f"- {path.as_posix()}")
    else:
        print("Changed review files: none")
    print("Optimization was not started. Run explicitly when ready.")
    return 0 if result.succeeded else 1


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
        BriefReviewError,
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
