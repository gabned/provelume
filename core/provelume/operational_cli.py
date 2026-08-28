from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .bundle_cli import add_bundle_commands, handle_bundle_command
from .inbox import InboxManager
from .ingest import DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_FILES
from .operations import OperationLedger
from .rebuild_cli import add_rebuild_commands, handle_rebuild_command
from .review_cli import add_review_commands, handle_review_command
from .storage import InstanceStore


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def add_operational_commands(subparsers: Any) -> None:
    submit = subparsers.add_parser(
        "inbox-submit",
        help="Copy a local file or directory into the Instance Inbox and acquire it",
    )
    submit.add_argument("instance", type=Path)
    submit.add_argument("source", type=Path)
    submit.add_argument(
        "--move-after-commit",
        action="store_true",
        help=(
            "remove each submitted source file only after exact bytes are copied, "
            "hash-verified and committed"
        ),
    )
    submit.add_argument(
        "--max-file-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_FILE_BYTES,
    )
    submit.add_argument("--max-files", type=_positive_int, default=DEFAULT_MAX_FILES)

    process = subparsers.add_parser(
        "inbox-process",
        help="Process files placed in the Instance inbox/drop directory",
    )
    process.add_argument("instance", type=Path)
    process.add_argument(
        "--max-file-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_FILE_BYTES,
    )
    process.add_argument("--max-files", type=_positive_int, default=DEFAULT_MAX_FILES)

    inbox_status = subparsers.add_parser(
        "inbox-status",
        help="Show the local Inbox summary and recent submissions",
    )
    inbox_status.add_argument("instance", type=Path)
    inbox_status.add_argument("--limit", type=_positive_int, default=100)

    operations = subparsers.add_parser(
        "operations",
        help="List the navigable Instance operation log",
    )
    operations.add_argument("instance", type=Path)
    operations.add_argument("--kind")
    operations.add_argument(
        "--status",
        choices=("running", "completed", "completed_with_errors", "failed"),
    )
    operations.add_argument("--limit", type=_positive_int, default=100)

    operation = subparsers.add_parser(
        "operation",
        help="Show one operation and its ordered event log",
    )
    operation.add_argument("instance", type=Path)
    operation.add_argument("operation_id")

    add_bundle_commands(subparsers)
    add_review_commands(subparsers)
    add_rebuild_commands(subparsers)


def handle_operational_command(args: argparse.Namespace) -> int | None:
    bundle_result = handle_bundle_command(args)
    if bundle_result is not None:
        return bundle_result
    review_result = handle_review_command(args)
    if review_result is not None:
        return review_result
    rebuild_result = handle_rebuild_command(args)
    if rebuild_result is not None:
        return rebuild_result

    if args.command not in {
        "inbox-submit",
        "inbox-process",
        "inbox-status",
        "operations",
        "operation",
    }:
        return None

    store = InstanceStore(args.instance)
    store.validate()

    if args.command == "inbox-submit":
        try:
            result = InboxManager(store).submit(
                args.source,
                move_after_commit=args.move_after_commit,
                max_file_bytes=args.max_file_bytes,
                max_files=args.max_files,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["submission"]["status"] == "completed" else 2

    if args.command == "inbox-process":
        try:
            result = InboxManager(store).process_drop(
                max_file_bytes=args.max_file_bytes,
                max_files=args.max_files,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["submission"]["status"] == "completed" else 2

    if args.command == "inbox-status":
        manager = InboxManager(store)
        print(
            json.dumps(
                {
                    "summary": manager.summary(),
                    "submissions": manager.list_submissions(limit=args.limit),
                },
                indent=2,
            )
        )
        return 0

    ledger = OperationLedger(store)
    if args.command == "operations":
        print(
            json.dumps(
                ledger.list(kind=args.kind, status=args.status, limit=args.limit),
                indent=2,
            )
        )
        return 0

    record = ledger.get(args.operation_id)
    if record is None:
        print(
            json.dumps(
                {"status": "not_found", "operation_id": args.operation_id},
                indent=2,
            )
        )
        return 3
    print(json.dumps(record, indent=2))
    return 0
