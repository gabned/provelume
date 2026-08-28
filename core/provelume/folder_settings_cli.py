from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .folder_settings import FolderSettingsError, FolderSettingsManager
from .storage import InstanceStore


def add_folder_settings_commands(subparsers: Any) -> None:
    show = subparsers.add_parser(
        "folder-settings",
        help="Show local Instance folder settings, including physical filesystem paths",
    )
    show.add_argument("instance", type=Path)

    configure = subparsers.add_parser(
        "configure-inbox",
        help=(
            "Configure the Inbox name plus Drop and managed-copy folders; "
            "paths may be inside or outside the Instance"
        ),
    )
    configure.add_argument("instance", type=Path)
    configure.add_argument("--name")
    configure.add_argument("--drop", type=Path, dest="drop_path")
    configure.add_argument("--managed", type=Path, dest="managed_path")


def handle_folder_settings_command(args: argparse.Namespace) -> int | None:
    if args.command not in {"folder-settings", "configure-inbox"}:
        return None
    store = InstanceStore(args.instance)
    store.validate()
    manager = FolderSettingsManager(store)

    if args.command == "folder-settings":
        try:
            result = manager.local_view()
        except (OSError, FolderSettingsError, ValueError) as exc:
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
        return 0

    if args.name is None and args.drop_path is None and args.managed_path is None:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": "at least one Inbox setting is required",
                    "error_type": "FolderSettingsError",
                },
                indent=2,
            )
        )
        return 2
    try:
        result = manager.configure(
            name=args.name,
            drop_path=args.drop_path,
            managed_path=args.managed_path,
        )
    except (OSError, FolderSettingsError, ValueError) as exc:
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
    return 0
