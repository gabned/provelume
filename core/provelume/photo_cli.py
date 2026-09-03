from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .photo_profiles import PhotoContractError, PhotoProfileManager
from .storage import InstanceStore


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def add_photo_commands(subparsers: Any) -> None:
    support = subparsers.add_parser(
        "photo-support",
        help="Inspect the bounded offline photo profile and optional decoder state",
    )
    support.add_argument("instance", type=Path)

    queue = subparsers.add_parser(
        "photo-queue", help="Queue a photo profile for one exact DocumentVersion"
    )
    queue.add_argument("instance", type=Path)
    queue.add_argument("version_id")

    run = subparsers.add_parser("photo-run", help="Run one queued local photo job")
    run.add_argument("instance", type=Path)
    run.add_argument("job_id")

    photos = subparsers.add_parser(
        "photos", help="List privacy-redacted photo representations and local jobs"
    )
    photos.add_argument("instance", type=Path)
    photos.add_argument("--version-id")
    photos.add_argument("--limit", type=_positive_int, default=100)

    photo = subparsers.add_parser("photo", help="Inspect one photo representation")
    photo.add_argument("instance", type=Path)
    photo.add_argument("representation_id")

    remove = subparsers.add_parser(
        "photo-remove", help="Remove one derived photo representation, never its Original"
    )
    remove.add_argument("instance", type=Path)
    remove.add_argument("representation_id")

    rebuild = subparsers.add_parser(
        "photo-rebuild", help="Rebuild one removed photo representation from its exact Original"
    )
    rebuild.add_argument("instance", type=Path)
    rebuild.add_argument("representation_id")


def handle_photo_command(args: argparse.Namespace) -> int | None:
    if args.command not in {
        "photo-support",
        "photo-queue",
        "photo-run",
        "photos",
        "photo",
        "photo-remove",
        "photo-rebuild",
    }:
        return None
    manager = PhotoProfileManager(InstanceStore.open(args.instance))
    try:
        if args.command == "photo-support":
            result = manager.capability()
        elif args.command == "photo-queue":
            result = manager.queue(args.version_id)
        elif args.command == "photo-run":
            result = manager.run(args.job_id)
        elif args.command == "photos":
            result = manager.read_model(version_id=args.version_id, limit=args.limit)
        elif args.command == "photo":
            result = manager.get(args.representation_id)
            if result is None:
                print(
                    json.dumps(
                        {
                            "status": "not_found",
                            "representation_id": args.representation_id,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 3
        elif args.command == "photo-remove":
            result = manager.remove(args.representation_id)
        else:
            result = manager.rebuild(args.representation_id)
    except PhotoContractError as exc:
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


__all__ = ["add_photo_commands", "handle_photo_command"]
