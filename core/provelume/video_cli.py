from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .storage import InstanceStore
from .video_profiles import VideoContractError, VideoProfileManager


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _timestamp(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("timestamp must be a non-negative integer")
    return parsed


def add_video_commands(subparsers: Any) -> None:
    support = subparsers.add_parser(
        "video-support",
        help="Inspect bounded local video, subtitle, ASR and selected-frame OCR support",
    )
    support.add_argument("instance", type=Path)

    queue = subparsers.add_parser(
        "video-queue",
        help="Queue a video profile for one exact DocumentVersion",
    )
    queue.add_argument("instance", type=Path)
    queue.add_argument("version_id")
    queue.add_argument("--frame-ms", action="append", type=_timestamp, default=[])
    queue.add_argument("--language", choices=("auto", "en", "it"), default="auto")

    for command, help_text in (
        ("video-run", "Run one queued local video job"),
        ("video-cancel", "Request cancellation for one local video job"),
        ("video-retry", "Retry one failed or cancelled local video job"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("job_id")

    profiles = subparsers.add_parser(
        "video-profiles",
        help="List bounded video representations and jobs",
    )
    profiles.add_argument("instance", type=Path)
    profiles.add_argument("--version-id")
    profiles.add_argument("--limit", type=_positive_int, default=100)

    profile = subparsers.add_parser("video-profile", help="Inspect one video representation")
    profile.add_argument("instance", type=Path)
    profile.add_argument("representation_id")

    for command, help_text in (
        ("video-remove", "Remove derived video outputs, never the Original"),
        ("video-rebuild", "Rebuild removed video outputs from the exact Original"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("representation_id")


def handle_video_command(args: argparse.Namespace) -> int | None:
    commands = {
        "video-support",
        "video-queue",
        "video-run",
        "video-cancel",
        "video-retry",
        "video-profiles",
        "video-profile",
        "video-remove",
        "video-rebuild",
    }
    if args.command not in commands:
        return None
    manager = VideoProfileManager(InstanceStore.open(args.instance))
    try:
        if args.command == "video-support":
            result = manager.capability()
        elif args.command == "video-queue":
            result = manager.queue(
                args.version_id,
                timestamps_ms=sorted(set(args.frame_ms)),
                transcript_language=args.language,
            )
        elif args.command == "video-run":
            result = manager.run(args.job_id)
        elif args.command == "video-cancel":
            result = manager.cancel(args.job_id)
        elif args.command == "video-retry":
            result = manager.retry(args.job_id)
        elif args.command == "video-profiles":
            result = manager.read_model(version_id=args.version_id, limit=args.limit)
        elif args.command == "video-profile":
            result = manager.get(args.representation_id)
            if result is None:
                print(json.dumps({"status": "not_found"}, indent=2, sort_keys=True))
                return 3
        elif args.command == "video-remove":
            result = manager.remove(args.representation_id)
        else:
            result = manager.rebuild(args.representation_id)
    except VideoContractError as exc:
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


__all__ = ["add_video_commands", "handle_video_command"]
