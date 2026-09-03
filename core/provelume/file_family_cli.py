from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .file_family_profiles import (
    FILE_FAMILY_PROFILE_IDS,
    FileFamilyContractError,
    FileFamilyProfileManager,
)
from .storage import InstanceStore


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def add_file_family_commands(subparsers: Any) -> None:
    support = subparsers.add_parser(
        "file-family-support",
        help="Inspect bounded CSV, XLSX and ZIP profile support",
    )
    support.add_argument("instance", type=Path)

    queue = subparsers.add_parser(
        "file-family-queue",
        help="Queue one bounded file-family profile for an exact DocumentVersion",
    )
    queue.add_argument("instance", type=Path)
    queue.add_argument("version_id")
    queue.add_argument("profile_id", choices=FILE_FAMILY_PROFILE_IDS)

    for command, help_text in (
        ("file-family-run", "Run one queued file-family job"),
        ("file-family-cancel", "Cancel one queued or running file-family job"),
        ("file-family-retry", "Retry one failed or cancelled file-family job"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("job_id")

    profiles = subparsers.add_parser(
        "file-family-profiles",
        help="List bounded file-family representations and jobs",
    )
    profiles.add_argument("instance", type=Path)
    profiles.add_argument("--profile-id", choices=FILE_FAMILY_PROFILE_IDS)
    profiles.add_argument("--version-id")
    profiles.add_argument("--limit", type=_positive_int, default=100)

    profile = subparsers.add_parser(
        "file-family-profile", help="Inspect one file-family representation"
    )
    profile.add_argument("instance", type=Path)
    profile.add_argument("representation_id")

    for command, help_text in (
        ("file-family-remove", "Remove derived file-family outputs, never the Original"),
        ("file-family-rebuild", "Rebuild removed outputs from the exact Original"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("representation_id")


def handle_file_family_command(args: argparse.Namespace) -> int | None:
    commands = {
        "file-family-support",
        "file-family-queue",
        "file-family-run",
        "file-family-cancel",
        "file-family-retry",
        "file-family-profiles",
        "file-family-profile",
        "file-family-remove",
        "file-family-rebuild",
    }
    if args.command not in commands:
        return None
    manager = FileFamilyProfileManager(InstanceStore.open(args.instance))
    try:
        if args.command == "file-family-support":
            result = manager.capability()
        elif args.command == "file-family-queue":
            result = manager.queue(args.version_id, args.profile_id)
        elif args.command == "file-family-run":
            result = manager.run(args.job_id)
        elif args.command == "file-family-cancel":
            result = manager.cancel(args.job_id)
        elif args.command == "file-family-retry":
            result = manager.retry(args.job_id)
        elif args.command == "file-family-profiles":
            result = manager.read_model(
                profile_id=args.profile_id,
                version_id=args.version_id,
                limit=args.limit,
            )
        elif args.command == "file-family-profile":
            result = manager.get(args.representation_id)
            if result is None:
                print(json.dumps({"status": "not_found"}, indent=2, sort_keys=True))
                return 3
        elif args.command == "file-family-remove":
            result = manager.remove(args.representation_id)
        else:
            result = manager.rebuild(args.representation_id)
    except FileFamilyContractError as exc:
        print(
            json.dumps(
                {"status": "error", "error_code": exc.code, "message": str(exc)},
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


__all__ = ["add_file_family_commands", "handle_file_family_command"]
