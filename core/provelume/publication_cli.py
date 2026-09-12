from __future__ import annotations

import json
from pathlib import Path

from .publication import PublicationError, current_publication, import_publication


def add_publication_commands(subparsers) -> None:
    parser = subparsers.add_parser("publication", help="Inspect/import release publication offline")
    commands = parser.add_subparsers(dest="publication_command", required=True)
    commands.add_parser("show", help="Print descriptive publication metadata and timed eligibility")
    importer = commands.add_parser(
        "import", help="Import the unchanged matching publication receipt"
    )
    importer.add_argument("--receipt", required=True, type=Path)
    importer.add_argument("--manifest", required=True, type=Path)
    importer.add_argument("--payload", required=True, type=Path)
    importer.add_argument("--destination", type=Path)


def handle_publication_command(args) -> int | None:
    if args.command != "publication":
        return None
    try:
        value = (
            current_publication()
            if args.publication_command == "show"
            else import_publication(
                args.receipt,
                manifest_path=args.manifest,
                payload_path=args.payload,
                destination=args.destination,
            )
        )
    except (OSError, PublicationError):
        print(json.dumps({"schema_version": 1, "status": "import_failed", "network_used": False}))
        return 2
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0
