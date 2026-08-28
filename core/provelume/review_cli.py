from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .assurance import AssuranceLimitError, OriginalAssuranceManager
from .duplicates import DuplicateCaseManager, DuplicateScanLimitError
from .storage import InstanceStore


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def add_review_commands(subparsers: Any) -> None:
    duplicate_scan = subparsers.add_parser(
        "duplicate-scan",
        help="Detect exact and probable duplicates without applying an action",
    )
    duplicate_scan.add_argument("instance", type=Path)

    duplicates = subparsers.add_parser(
        "duplicates",
        help="List persisted exact and probable duplicate cases",
    )
    duplicates.add_argument("instance", type=Path)
    duplicates.add_argument("--kind", choices=("exact", "probable"))
    duplicates.add_argument(
        "--current",
        choices=("true", "false", "all"),
        default="true",
    )
    duplicates.add_argument("--limit", type=_positive_int, default=100)

    duplicate = subparsers.add_parser(
        "duplicate",
        help="Show one explainable duplicate case",
    )
    duplicate.add_argument("instance", type=Path)
    duplicate.add_argument("case_id")

    assurance_check = subparsers.add_parser(
        "assurance-check",
        help="Verify canonical references and exact Original bytes without repair",
    )
    assurance_check.add_argument("instance", type=Path)

    assurance_reports = subparsers.add_parser(
        "assurance-reports",
        help="List retained Original assurance reports",
    )
    assurance_reports.add_argument("instance", type=Path)
    assurance_reports.add_argument("--limit", type=_positive_int, default=100)

    assurance_report = subparsers.add_parser(
        "assurance-report",
        help="Show one Original assurance report",
    )
    assurance_report.add_argument("instance", type=Path)
    assurance_report.add_argument("report_id")


def handle_review_command(args: argparse.Namespace) -> int | None:
    if args.command not in {
        "duplicate-scan",
        "duplicates",
        "duplicate",
        "assurance-check",
        "assurance-reports",
        "assurance-report",
    }:
        return None

    store = InstanceStore.open(args.instance)

    if args.command == "duplicate-scan":
        try:
            result = DuplicateCaseManager(store).scan()
        except (AssuranceLimitError, DuplicateScanLimitError) as exc:
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
        return 0 if result["operation"]["status"] == "completed" else 2

    if args.command == "duplicates":
        current = None if args.current == "all" else args.current == "true"
        print(
            json.dumps(
                DuplicateCaseManager(store).list_cases(
                    kind=args.kind,
                    current=current,
                    limit=args.limit,
                ),
                indent=2,
            )
        )
        return 0

    if args.command == "duplicate":
        record = DuplicateCaseManager(store).get_case(args.case_id)
        if record is None:
            print(
                json.dumps(
                    {"status": "not_found", "case_id": args.case_id},
                    indent=2,
                )
            )
            return 3
        print(json.dumps(record, indent=2))
        return 0

    if args.command == "assurance-check":
        try:
            report = OriginalAssuranceManager(store).check()
        except AssuranceLimitError as exc:
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
        return 0 if report["status"] == "healthy" else 2

    manager = OriginalAssuranceManager(store)
    if args.command == "assurance-reports":
        print(json.dumps(manager.list_reports(limit=args.limit), indent=2))
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
