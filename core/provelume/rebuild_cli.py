from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .bundles import DEFAULT_MAX_BUNDLE_DOCUMENTS, BundleBuildError
from .duplicates import DuplicateScanLimitError
from .locks import InstanceLockOwnershipError, InstanceLockUnavailable
from .rebuild import (
    DerivedRebuildManager,
    RebuildInvariantError,
    RebuildLimitError,
)
from .storage import InstanceStore


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def add_rebuild_commands(subparsers: Any) -> None:
    rebuild = subparsers.add_parser(
        "rebuild-derived",
        help=(
            "Run a locked incremental, full or agreement rebuild of local "
            "derived state"
        ),
    )
    rebuild.add_argument("instance", type=Path)
    rebuild.add_argument(
        "--mode",
        choices=("incremental", "full", "agreement"),
        default="agreement",
    )
    rebuild.add_argument(
        "--max-documents",
        type=_positive_int,
        default=DEFAULT_MAX_BUNDLE_DOCUMENTS,
    )

    reports = subparsers.add_parser(
        "rebuild-reports",
        help="List retained derived-state rebuild reports",
    )
    reports.add_argument("instance", type=Path)
    reports.add_argument("--limit", type=_positive_int, default=100)

    report = subparsers.add_parser(
        "rebuild-report",
        help="Show one derived-state rebuild report",
    )
    report.add_argument("instance", type=Path)
    report.add_argument("report_id")

    lock = subparsers.add_parser(
        "rebuild-lock",
        help="Inspect the exclusive derived-state rebuild lock without changing it",
    )
    lock.add_argument("instance", type=Path)


def handle_rebuild_command(args: argparse.Namespace) -> int | None:
    if args.command not in {
        "rebuild-derived",
        "rebuild-reports",
        "rebuild-report",
        "rebuild-lock",
    }:
        return None

    store = InstanceStore.open(args.instance)
    manager = DerivedRebuildManager(store)

    if args.command == "rebuild-derived":
        try:
            report = manager.run(
                args.mode,
                max_documents=args.max_documents,
            )
        except (
            BundleBuildError,
            DuplicateScanLimitError,
            InstanceLockOwnershipError,
            InstanceLockUnavailable,
            RebuildInvariantError,
            RebuildLimitError,
            OSError,
            ValueError,
        ) as exc:
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
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "completed" else 2

    if args.command == "rebuild-reports":
        print(json.dumps(manager.list_reports(limit=args.limit), indent=2))
        return 0

    if args.command == "rebuild-lock":
        print(json.dumps(manager.lock_status(), indent=2))
        return 0

    report = manager.get_report(args.report_id)
    if report is None:
        print(
            json.dumps(
                {"status": "not_found", "report_id": args.report_id},
                indent=2,
            )
        )
        return 3
    print(json.dumps(report, indent=2))
    return 0
