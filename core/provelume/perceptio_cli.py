from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .perceptio import PerceptioError
from .service import ProvelumeInstance


def _bounded_limit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 500:
        raise argparse.ArgumentTypeError("value must be from 1 through 500")
    return parsed


def add_perceptio_commands(subparsers: Any) -> None:
    status = subparsers.add_parser(
        "perceptio-status",
        help="Inspect the bounded, read-only Perceptio pilot journey",
    )
    status.add_argument("instance", type=Path)
    status.add_argument("--version-id")
    status.add_argument("--limit", type=_bounded_limit, default=100)

    selected = subparsers.add_parser(
        "perceptio-representation",
        help="Inspect one Perceptio representation without changing it",
    )
    selected.add_argument("instance", type=Path)
    selected.add_argument("representation_id")


def handle_perceptio_command(args: argparse.Namespace) -> int | None:
    if args.command not in {"perceptio-status", "perceptio-representation"}:
        return None
    instance = ProvelumeInstance(args.instance)
    try:
        if args.command == "perceptio-status":
            result = instance.perceptio_read_model(
                version_id=args.version_id,
                limit=args.limit,
            )
        else:
            result = instance.get_perceptio_representation(args.representation_id)
            if result is None:
                print(json.dumps({"status": "not_found"}, indent=2, sort_keys=True))
                return 3
    except PerceptioError as exc:
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


__all__ = ["add_perceptio_commands", "handle_perceptio_command"]
