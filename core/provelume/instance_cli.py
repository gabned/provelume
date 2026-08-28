from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .instance_backup import BackupError
from .instance_lifecycle import InstanceLifecycleError, InstanceLifecycleManager
from .portable_transfer import (
    DERIVED_STATE_MODES,
    PortableInstanceTransfer,
    PortableTransferError,
)
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

    export = subparsers.add_parser(
        "export",
        help="Create a deterministic, hash-manifested portable Instance bundle",
    )
    export.add_argument("instance", type=Path)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument(
        "--derived-state",
        choices=DERIVED_STATE_MODES,
        default="rebuild",
        help="rebuild indexes/library after import or include their current bytes",
    )

    import_command = subparsers.add_parser(
        "import",
        help="Replace an existing Instance from a verified portable bundle",
    )
    import_command.add_argument("instance", type=Path)
    import_command.add_argument("bundle", type=Path)


def handle_instance_lifecycle_command(args: argparse.Namespace) -> int | None:
    if args.command not in {
        "backup",
        "export",
        "import",
        "migrate",
        "restore",
        "validate",
    }:
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
        elif args.command == "restore":
            result = manager.restore(args.archive)
        elif args.command == "export":
            result = PortableInstanceTransfer(manager.store).export(
                args.output,
                derived_state=args.derived_state,
            )
        else:
            result = PortableInstanceTransfer(manager.store).import_bundle(args.bundle)
    except (
        BackupError,
        InstanceLifecycleError,
        OSError,
        PortableTransferError,
        ValueError,
    ) as exc:
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
