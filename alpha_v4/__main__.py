"""Command-line entry point for the ALPHA v4 rebuild runtime."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .runtime import AlphaRuntime, RuntimeConfig, RuntimeMode
from .server import serve_forever
from .worker import run_snapshot_cycle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alpha-v4")
    parser.add_argument(
        "command",
        choices=("status", "init", "serve", "snapshot"),
        help="Initialize, report health, serve health, or run one source snapshot cycle.",
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
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for the serve command.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Bind port for the serve command.",
    )
    parser.add_argument("--source", help="Official source id for snapshot command.")
    parser.add_argument(
        "--surface", help="Allowlisted source surface for snapshot command."
    )
    parser.add_argument(
        "--owner",
        default="alpha-v4-cli",
        help="Worker owner id for snapshot leases.",
    )
    parser.add_argument(
        "--cycle-key",
        help="Idempotency key; defaults to the current UTC minute.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database_path = Path(args.db)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = AlphaRuntime(
        RuntimeConfig(mode=RuntimeMode(args.mode), database_path=database_path)
    )

    if args.command == "serve":
        serve_forever(runtime, args.host, args.port)
        return 0

    if args.command == "snapshot":
        if not args.source or not args.surface:
            raise SystemExit("snapshot requires --source and --surface")
        started_at = datetime.now(timezone.utc)
        cycle_key = args.cycle_key or started_at.strftime("%Y-%m-%dT%H:%MZ")
        result = run_snapshot_cycle(
            runtime,
            source_id=args.source,
            surface=args.surface,
            owner_id=args.owner,
            cycle_key=cycle_key,
            started_at=started_at,
        )
        print(json.dumps(asdict(result), sort_keys=True))
        return 0

    if args.command == "init":
        output = {"initialized": True, **runtime.health()}
    else:
        output = runtime.health()

    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
