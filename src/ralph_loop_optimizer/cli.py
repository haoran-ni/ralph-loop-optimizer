"""Command line entry point for Ralph Loop Optimizer."""

from __future__ import annotations

import argparse

from ralph_loop_optimizer import __version__


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
