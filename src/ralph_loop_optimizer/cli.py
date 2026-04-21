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
from ralph_loop_optimizer.config import ConfigError, OptimizerConfig, validate_config
from ralph_loop_optimizer.harness import HarnessError, inspect_harness


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = getattr(args, "func", None)
    if command is None:
        return 0
    try:
        return command(args)
    except (BriefError, ConfigError, HarnessError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
