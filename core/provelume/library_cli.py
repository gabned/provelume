from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .library_projection import (
    DEFAULT_MAX_LIBRARY_DOCUMENTS,
    LibraryProjectionManager,
)
from .storage import InstanceStore


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def add_library_commands(subparsers: Any) -> None:
    rebuild = subparsers.add_parser(
        "library-rebuild",
        help="Rebuild the deterministic local Markdown library projection",
    )
    rebuild.add_argument("instance", type=Path)
    rebuild.add_argument(
        "--max-documents",
        type=_positive_int,
        default=DEFAULT_MAX_LIBRARY_DOCUMENTS,
    )

    status = subparsers.add_parser(
        "library-status",
        help="Validate the local Markdown library projection without changing it",
    )
    status.add_argument("instance", type=Path)


def handle_library_command(args: argparse.Namespace) -> int | None:
    if args.command not in {"library-rebuild", "library-status"}:
        return None
    manager = LibraryProjectionManager(InstanceStore.open(args.instance))
    if args.command == "library-status":
        print(json.dumps(manager.status(), indent=2, sort_keys=True))
        return 0
    try:
        result = manager.rebuild(max_documents=args.max_documents)
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
