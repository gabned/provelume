from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .hierarchy import HIERARCHY_KINDS, HierarchyError, HierarchyNotFoundError
from .service import ProvelumeInstance


def add_hierarchy_commands(subparsers: Any) -> None:
    list_parser = subparsers.add_parser(
        "hierarchy-list",
        help="List the stable local Area, Project and Collection hierarchy",
    )
    list_parser.add_argument("instance", type=Path)

    create = subparsers.add_parser(
        "hierarchy-create",
        help="Create one stable hierarchy node",
    )
    create.add_argument("instance", type=Path)
    create.add_argument("kind", choices=HIERARCHY_KINDS)
    create.add_argument("name")
    create.add_argument("--parent-id")

    rename = subparsers.add_parser(
        "hierarchy-rename",
        help="Rename a hierarchy node without changing its identity",
    )
    rename.add_argument("instance", type=Path)
    rename.add_argument("node_id")
    rename.add_argument("name")

    move = subparsers.add_parser(
        "hierarchy-move",
        help="Move a hierarchy node under a new parent or to the root",
    )
    move.add_argument("instance", type=Path)
    move.add_argument("node_id")
    move.add_argument(
        "--parent-id",
        help="new parent identity; omit to move the node to the hierarchy root",
    )

    classify = subparsers.add_parser(
        "classify",
        help="Set one primary and optional secondary hierarchy associations",
    )
    classify.add_argument("instance", type=Path)
    classify.add_argument("document_id")
    classify.add_argument("--primary", required=True, dest="primary_node_id")
    classify.add_argument(
        "--secondary",
        action="append",
        default=[],
        dest="secondary_node_ids",
        help="secondary hierarchy identity; repeat for multiple associations",
    )

    classification = subparsers.add_parser(
        "classification",
        help="Show one Document's canonical hierarchy classification",
    )
    classification.add_argument("instance", type=Path)
    classification.add_argument("document_id")


def handle_hierarchy_command(args: argparse.Namespace) -> int | None:
    if args.command not in {
        "hierarchy-list",
        "hierarchy-create",
        "hierarchy-rename",
        "hierarchy-move",
        "classify",
        "classification",
    }:
        return None

    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "hierarchy-list":
            result: Any = instance.hierarchy_tree()
        elif args.command == "hierarchy-create":
            result = instance.create_hierarchy_node(
                args.kind,
                args.name,
                parent_id=args.parent_id,
            )
        elif args.command == "hierarchy-rename":
            result = instance.rename_hierarchy_node(args.node_id, args.name)
        elif args.command == "hierarchy-move":
            result = instance.move_hierarchy_node(args.node_id, args.parent_id)
        elif args.command == "classify":
            result = instance.classify_document(
                args.document_id,
                args.primary_node_id,
                secondary_node_ids=args.secondary_node_ids,
            )
        else:
            if instance.get_document(args.document_id) is None:
                raise HierarchyNotFoundError(
                    f"document not found: {args.document_id}"
                )
            result = {
                "document_id": args.document_id,
                "classification": instance.document_classification(args.document_id),
            }
    except (HierarchyError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "not_found"
                    if isinstance(exc, HierarchyNotFoundError)
                    else "error",
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3 if isinstance(exc, HierarchyNotFoundError) else 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
