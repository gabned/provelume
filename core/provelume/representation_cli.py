from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .representations import RepresentationReadModel
from .storage import InstanceStore


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def add_representation_commands(subparsers: Any) -> None:
    support = subparsers.add_parser(
        "representation-support",
        help="Inspect declared and effective representation support without network access",
    )
    support.add_argument("instance", type=Path)
    support.add_argument("--profile-id")

    representations = subparsers.add_parser(
        "representations",
        help="Inspect universal bundles and Lectio compatibility views read-only",
    )
    representations.add_argument("instance", type=Path)
    representations.add_argument("--profile-id")
    representations.add_argument("--version-id")
    representations.add_argument("--limit", type=_positive_int, default=100)

    representation = subparsers.add_parser(
        "representation",
        help="Inspect one validated universal representation bundle read-only",
    )
    representation.add_argument("instance", type=Path)
    representation.add_argument("representation_id")


def handle_representation_command(args: argparse.Namespace) -> int | None:
    if args.command not in {
        "representation-support",
        "representations",
        "representation",
    }:
        return None
    model = RepresentationReadModel(InstanceStore.open(args.instance))
    if args.command == "representation-support":
        result = model.support.read(profile_id=args.profile_id)
    elif args.command == "representations":
        result = model.read(
            profile_id=args.profile_id,
            version_id=args.version_id,
            limit=args.limit,
        )
    else:
        result = model.get(args.representation_id)
        if result is None:
            print(
                json.dumps(
                    {"status": "not_found", "representation_id": args.representation_id},
                    indent=2,
                    sort_keys=True,
                )
            )
            return 3
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
