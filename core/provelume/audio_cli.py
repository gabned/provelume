from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .audio_profiles import AudioContractError, AudioProfileManager
from .storage import InstanceStore


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def add_audio_commands(subparsers: Any) -> None:
    support = subparsers.add_parser(
        "audio-support",
        help="Inspect bounded local audio and ASR support",
    )
    support.add_argument("instance", type=Path)

    queue = subparsers.add_parser(
        "audio-queue",
        help="Queue an audio profile for one exact DocumentVersion",
    )
    queue.add_argument("instance", type=Path)
    queue.add_argument("version_id")
    queue.add_argument("--language", choices=("auto", "en", "it"), default="auto")
    queue.add_argument("--threads", type=_positive_int, default=2)

    for command, help_text in (
        ("audio-run", "Run one queued local audio job"),
        ("audio-cancel", "Request cancellation for one local audio job"),
        ("audio-retry", "Retry one failed or cancelled local audio job"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("job_id")

    profiles = subparsers.add_parser(
        "audio-profiles",
        help="List bounded audio representations and jobs",
    )
    profiles.add_argument("instance", type=Path)
    profiles.add_argument("--version-id")
    profiles.add_argument("--limit", type=_positive_int, default=100)

    profile = subparsers.add_parser("audio-profile", help="Inspect one audio representation")
    profile.add_argument("instance", type=Path)
    profile.add_argument("representation_id")

    for command, help_text in (
        ("audio-remove", "Remove derived audio outputs, never the Original"),
        ("audio-rebuild", "Rebuild removed audio outputs from the exact Original"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("representation_id")


def handle_audio_command(args: argparse.Namespace) -> int | None:
    commands = {
        "audio-support",
        "audio-queue",
        "audio-run",
        "audio-cancel",
        "audio-retry",
        "audio-profiles",
        "audio-profile",
        "audio-remove",
        "audio-rebuild",
    }
    if args.command not in commands:
        return None
    manager = AudioProfileManager(InstanceStore.open(args.instance))
    try:
        if args.command == "audio-support":
            result = manager.capability()
        elif args.command == "audio-queue":
            result = manager.queue(
                args.version_id,
                language=args.language,
                threads=args.threads,
            )
        elif args.command == "audio-run":
            result = manager.run(args.job_id)
        elif args.command == "audio-cancel":
            result = manager.cancel(args.job_id)
        elif args.command == "audio-retry":
            result = manager.retry(args.job_id)
        elif args.command == "audio-profiles":
            result = manager.read_model(version_id=args.version_id, limit=args.limit)
        elif args.command == "audio-profile":
            result = manager.get(args.representation_id)
            if result is None:
                print(json.dumps({"status": "not_found"}, indent=2, sort_keys=True))
                return 3
        elif args.command == "audio-remove":
            result = manager.remove(args.representation_id)
        else:
            result = manager.rebuild(args.representation_id)
    except AudioContractError as exc:
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


__all__ = ["add_audio_commands", "handle_audio_command"]
