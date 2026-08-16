"""Command-line entry point for the ALPHA v4 rebuild runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import AlphaRuntime, RuntimeConfig, RuntimeMode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alpha-v4")
    parser.add_argument(
        "command",
        choices=("status", "init"),
        help="Initialize the local event store or report runtime health.",
    )
    parser.add_argument(
        "--mode",
        choices=tuple(mode.value for mode in RuntimeMode),
        default=RuntimeMode.DEV.value,
    )
    parser.add_argument(
        "--db",
        default="data/alpha_v4/events.sqlite3",
        help="Path to the bootstrap append-only event store.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database_path = Path(args.db)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = AlphaRuntime(
        RuntimeConfig(mode=RuntimeMode(args.mode), database_path=database_path)
    )

    if args.command == "init":
        output = {"initialized": True, **runtime.health()}
    else:
        output = runtime.health()

    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
