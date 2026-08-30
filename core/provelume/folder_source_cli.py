from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .folder_source_model import (
    SOURCE_CLASSES,
    SOURCE_LIFECYCLE_STATES,
    FolderSourceError,
)
from .scheduler import schedule_payload
from .scheduler_model import DST_POLICIES, MISSED_RUN_POLICIES, SCHEDULE_MODES, SchedulerError
from .service import ProvelumeInstance

FOLDER_SOURCE_COMMANDS = frozenset(
    {
        "folder-source-register",
        "folder-sources",
        "folder-source",
        "folder-source-observe",
        "folder-source-state",
        "folder-source-refresh",
    }
)


def _positive(value: str) -> int:
    selected = int(value)
    if selected < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return selected


def _non_negative(value: str) -> int:
    selected = int(value)
    if selected < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return selected


def add_folder_source_commands(subparsers: Any) -> None:
    register = subparsers.add_parser(
        "folder-source-register",
        help="Register one explicit local, removable or mounted-network folder Source",
    )
    register.add_argument("instance", type=Path)
    register.add_argument("path", type=Path)
    register.add_argument("--name", required=True)
    register.add_argument("--class", dest="source_class", choices=SOURCE_CLASSES, default="local")
    register.add_argument("--state", choices=SOURCE_LIFECYCLE_STATES, default="enabled")
    register.add_argument("--quiescence-seconds", type=_non_negative, default=5)
    register.add_argument("--stable-observations", type=_positive, default=2)
    register.add_argument("--max-file-bytes", type=_positive, default=25 * 1024 * 1024)
    register.add_argument("--max-files", type=_positive, default=1000)
    register.add_argument("--mode", choices=SCHEDULE_MODES, default="manual")
    register.add_argument("--timezone", default="UTC")
    register.add_argument("--interval-seconds", type=_positive)
    register.add_argument("--calendar-time")
    register.add_argument("--weekday", action="append", type=int, choices=range(7))
    register.add_argument("--dst-policy", choices=DST_POLICIES, default="earliest")
    register.add_argument("--quiet-start")
    register.add_argument("--quiet-end")
    register.add_argument("--jitter-seconds", type=_non_negative, default=0)
    register.add_argument(
        "--missed-run-policy",
        choices=MISSED_RUN_POLICIES,
        default="coalesce",
    )

    listing = subparsers.add_parser(
        "folder-sources",
        help="List managed folder Sources and durable observation state",
    )
    listing.add_argument("instance", type=Path)

    detail = subparsers.add_parser(
        "folder-source",
        help="Show one managed folder Source without reading its files",
    )
    detail.add_argument("instance", type=Path)
    detail.add_argument("source_id")

    observe = subparsers.add_parser(
        "folder-source-observe",
        help="Explicitly observe metadata and advance one Source quiescence state",
    )
    observe.add_argument("instance", type=Path)
    observe.add_argument("source_id")

    state = subparsers.add_parser(
        "folder-source-state",
        help="Enable or pause a managed folder Source and its linked policy",
    )
    state.add_argument("instance", type=Path)
    state.add_argument("source_id")
    state.add_argument("state", choices=SOURCE_LIFECYCLE_STATES)

    refresh = subparsers.add_parser(
        "folder-source-refresh",
        help="Queue and execute one exact, journaled folder Source refresh",
    )
    refresh.add_argument("instance", type=Path)
    refresh.add_argument("source_id")
    refresh.add_argument("--idempotency-key")


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_folder_source_command(args: argparse.Namespace) -> int | None:
    if args.command not in FOLDER_SOURCE_COMMANDS:
        return None
    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "folder-source-register":
            schedule = schedule_payload(
                mode=args.mode,
                timezone=args.timezone,
                interval_seconds=args.interval_seconds,
                calendar_time=args.calendar_time,
                weekdays=(
                    sorted(set(args.weekday or list(range(7)))) if args.mode == "calendar" else []
                ),
                dst_policy=args.dst_policy,
                quiet_start=args.quiet_start,
                quiet_end=args.quiet_end,
                jitter_seconds=args.jitter_seconds,
                missed_run_policy=args.missed_run_policy,
            )
            _print(
                instance.register_folder_source(
                    args.path,
                    name=args.name,
                    source_class=args.source_class,
                    lifecycle_state=args.state,
                    quiescence_seconds=args.quiescence_seconds,
                    stable_observations=args.stable_observations,
                    max_file_bytes=args.max_file_bytes,
                    max_files=args.max_files,
                    schedule=schedule,
                )
            )
            return 0
        if args.command == "folder-sources":
            _print(
                [
                    instance.folder_sources.local_view(str(item["id"]))
                    for item in instance.folder_sources.list_public()
                ]
            )
            return 0
        if args.command == "folder-source":
            _print(instance.folder_sources.local_view(args.source_id))
            return 0
        if args.command == "folder-source-observe":
            _print(instance.observe_folder_source(args.source_id))
            return 0
        if args.command == "folder-source-state":
            _print(instance.set_folder_source_state(args.source_id, args.state))
            return 0
        if args.command == "folder-source-refresh":
            result = instance.refresh_folder_source(
                args.source_id,
                request_key=args.idempotency_key,
            )
            _print(result)
            job = result.get("job")
            return 0 if isinstance(job, dict) and job.get("status") == "succeeded" else 2
    except (FolderSourceError, OSError, SchedulerError, ValueError) as exc:
        _print({"status": "error", "error": str(exc)})
        return 2
    raise RuntimeError(f"unsupported folder Source command: {args.command}")


__all__ = ["add_folder_source_commands", "handle_folder_source_command"]
