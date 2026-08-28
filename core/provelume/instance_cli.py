from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .instance_backup import BackupError
from .instance_lifecycle import InstanceLifecycleError, InstanceLifecycleManager
from .storage import InstanceStore


def add_instance_lifecycle_commands(subparsers: Any) -> None:
    validate = subparsers.add_parser(
        "validate",
        help="Validate an Instance without migrating, repairing or rebuilding it",
    )
    validate.add_argument("instance", type=Path)
    validate.add_argument(
        "--fast",
        action="store_true",
        help="Validate identity and schema contracts without hashing canonical Originals",
    )

    migrate = subparsers.add_parser(
        "migrate",
        help="Preflight, back up and migrate an older supported Instance",
    )
    migrate.add_argument("instance", type=Path)

    backup = subparsers.add_parser(
        "backup",
        help="Create and independently verify a local Instance backup archive",
    )
    backup.add_argument("instance", type=Path)
    backup.add_argument(
        "--output",
        type=Path,
        help="ZIP path or destination directory outside the Instance",
    )

    restore = subparsers.add_parser(
        "restore",
        help="Validate and restore a same-Instance backup with automatic rollback",
    )
    restore.add_argument("instance", type=Path)
    restore.add_argument("archive", type=Path)


def handle_instance_lifecycle_command(args: argparse.Namespace) -> int | None:
    if args.command not in {"validate", "migrate", "backup", "restore"}:
        return None
    manager = InstanceLifecycleManager(InstanceStore(args.instance))
    try:
        if args.command == "validate":
            result = manager.validate(deep=not args.fast)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["status"] == "valid" else 2
        if args.command == "migrate":
            result = manager.prepare()
        elif args.command == "backup":
            result = manager.backup(destination=args.output, reason="manual_cli")
        else:
            result = manager.restore(args.archive)
    except (BackupError, InstanceLifecycleError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "error",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
