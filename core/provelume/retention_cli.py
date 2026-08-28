from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .retention_model import RetentionError
from .service import ProvelumeInstance

RETENTION_COMMANDS = {
    "archive-document": "archive_document",
    "unarchive-document": "unarchive_document",
    "remove-from-library": "remove_document_from_library",
    "restore-to-library": "restore_document_to_library",
    "trash-document": "trash_document",
    "restore-from-trash": "restore_document_from_trash",
}


def _document_command(subparsers: Any, name: str, help_text: str) -> None:
    parser = subparsers.add_parser(name, help=help_text)
    parser.add_argument("instance", type=Path)
    parser.add_argument("document_id")


def add_retention_commands(subparsers: Any) -> None:
    _document_command(
        subparsers,
        "archive-document",
        "Move one Document into the archive projection without deleting its Original",
    )
    _document_command(
        subparsers,
        "unarchive-document",
        "Return one archived Document to its retained classification",
    )
    _document_command(
        subparsers,
        "remove-from-library",
        "Exclude one Document from the Markdown projection only",
    )
    _document_command(
        subparsers,
        "restore-to-library",
        "Include one non-trashed Document in the Markdown projection",
    )
    _document_command(
        subparsers,
        "trash-document",
        "Place one Document in recoverable trash while preserving its lineage",
    )
    _document_command(
        subparsers,
        "restore-from-trash",
        "Restore one Document from recoverable trash with identity intact",
    )
    _document_command(
        subparsers,
        "purge-preview",
        "Preview exact live-Instance purge impact and issue a short-lived token",
    )
    purge = subparsers.add_parser(
        "purge-document",
        help="Permanently purge a trashed Document after explicit local confirmation",
    )
    purge.add_argument("instance", type=Path)
    purge.add_argument("document_id")
    purge.add_argument("--confirm", required=True, dest="confirmation_token")
    purge.add_argument(
        "--acknowledge-boundaries",
        action="store_true",
        help=(
            "acknowledge that backups, replicas and configured source files are "
            "outside the live-Instance erasure claim"
        ),
    )


def handle_retention_command(args: argparse.Namespace) -> int | None:
    if args.command not in {
        *RETENTION_COMMANDS,
        "purge-preview",
        "purge-document",
    }:
        return None
    try:
        instance = ProvelumeInstance(args.instance)
        if args.command in RETENTION_COMMANDS:
            result = getattr(instance, RETENTION_COMMANDS[args.command])(
                args.document_id
            )
        elif args.command == "purge-preview":
            result = instance.purge_document_preview(args.document_id)
        else:
            result = instance.purge_document(
                args.document_id,
                args.confirmation_token,
                acknowledge_boundaries=args.acknowledge_boundaries,
            )
    except (OSError, ValueError, RetentionError) as exc:
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
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
