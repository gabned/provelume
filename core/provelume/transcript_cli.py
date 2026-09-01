from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from .connectors import ConnectorError
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance
from .transcript_contract import (
    TRANSCRIPT_SELECTION_KINDS,
    TRANSCRIPT_SOURCE_SCHEDULE_MODES,
    TRANSCRIPT_SOURCE_STATES,
    TRANSCRIPT_SUPPORTED_PROFILES,
    TranscriptContractError,
)


def _positive(value: str) -> int:
    selected = int(value)
    if selected < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return selected


def add_transcript_commands(subparsers: Any) -> None:
    capability = subparsers.add_parser(
        "transcript-capability", help="Report deterministic local transcript profiles"
    )
    capability.add_argument("instance", type=Path)
    capability.add_argument("--source-id")

    create = subparsers.add_parser(
        "transcript-source-create", help="Create one disabled explicit transcript Source"
    )
    create.add_argument("instance", type=Path)
    create.add_argument("--name", required=True)
    create.add_argument("--path", type=Path, required=True)
    create.add_argument("--profile", choices=TRANSCRIPT_SUPPORTED_PROFILES, required=True)
    create.add_argument(
        "--selection-kind", choices=TRANSCRIPT_SELECTION_KINDS, required=True
    )

    sources = subparsers.add_parser(
        "transcript-source-list", help="List configured transcript Sources"
    )
    sources.add_argument("instance", type=Path)
    sources.add_argument("--active-only", action="store_true")

    show = subparsers.add_parser(
        "transcript-source-show", help="Show one transcript Source and its local selection"
    )
    show.add_argument("instance", type=Path)
    show.add_argument("source_id")

    state = subparsers.add_parser(
        "transcript-source-state", help="Enable, pause or disable one transcript Source"
    )
    state.add_argument("instance", type=Path)
    state.add_argument("source_id")
    state.add_argument("state", choices=TRANSCRIPT_SOURCE_STATES)

    configure = subparsers.add_parser(
        "transcript-source-configure",
        help="Reconfigure an explicitly disabled transcript Source",
    )
    configure.add_argument("instance", type=Path)
    configure.add_argument("source_id")
    configure.add_argument("--path", type=Path, required=True)
    configure.add_argument("--profile", choices=TRANSCRIPT_SUPPORTED_PROFILES, required=True)
    configure.add_argument(
        "--selection-kind", choices=TRANSCRIPT_SELECTION_KINDS, required=True
    )

    schedule = subparsers.add_parser(
        "transcript-source-schedule",
        help="Set manual or bounded interval refresh for one transcript Source",
    )
    schedule.add_argument("instance", type=Path)
    schedule.add_argument("source_id")
    schedule.add_argument("mode", choices=TRANSCRIPT_SOURCE_SCHEDULE_MODES)
    schedule.add_argument("--interval-seconds", type=_positive)

    for command, help_text in (
        ("transcript-source-remove", "Tombstone one transcript Source"),
        ("transcript-source-checkpoint", "Inspect one Source-confined checkpoint"),
        ("transcript-source-resync", "Reset one Source cursor explicitly"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("source_id")

    queue = subparsers.add_parser(
        "transcript-intake-queue", help="Queue explicit transcript refresh/import"
    )
    queue.add_argument("instance", type=Path)
    queue.add_argument("source_id")
    queue.add_argument("--request-key")

    run = subparsers.add_parser(
        "transcript-intake-run", help="Run one queued transcript job"
    )
    run.add_argument("instance", type=Path)
    run.add_argument("job_id")

    jobs = subparsers.add_parser(
        "transcript-intake-jobs", help="List transcript jobs"
    )
    jobs.add_argument("instance", type=Path)
    jobs.add_argument("--limit", type=_positive, default=100)

    for command, help_text in (
        ("transcript-intake-job", "Inspect one transcript job"),
        ("transcript-intake-retry", "Retry one terminal transcript job"),
        ("transcript-intake-cancel", "Cancel one transcript job"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("job_id")

    revisions = subparsers.add_parser(
        "transcript-revisions", help="List provider-neutral transcript revisions"
    )
    revisions.add_argument("instance", type=Path)
    revisions.add_argument("--source-id")
    revisions.add_argument("--limit", type=_positive, default=100)

    revision = subparsers.add_parser(
        "transcript-revision", help="Inspect transcript metadata or derived content"
    )
    revision.add_argument("instance", type=Path)
    revision.add_argument("revision_id")
    revision.add_argument("--content", action="store_true")

    original = subparsers.add_parser(
        "transcript-original", help="Inspect exact-byte Original metadata"
    )
    original.add_argument("instance", type=Path)
    original.add_argument("revision_id")
    original.add_argument("--base64", action="store_true")

    for command, help_text in (
        (
            "transcript-derived-remove",
            "Remove only a rebuildable transcript representation",
        ),
        (
            "transcript-derived-rebuild",
            "Rebuild a transcript representation from its Original",
        ),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("revision_id")


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_transcript_command(args: argparse.Namespace) -> int | None:
    if not str(args.command).startswith("transcript-"):
        return None
    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "transcript-capability":
            result = instance.transcript_capability(args.source_id, local=True)
        elif args.command == "transcript-source-create":
            result = instance.create_transcript_source(
                name=args.name,
                path=args.path,
                profile=args.profile,
                selection_kind=args.selection_kind,
            )
        elif args.command == "transcript-source-list":
            result = instance.list_transcript_sources(
                local=True, include_removed=not args.active_only
            )
        elif args.command == "transcript-source-show":
            result = instance.get_transcript_source(args.source_id, local=True)
        elif args.command == "transcript-source-state":
            result = instance.set_transcript_source_state(args.source_id, args.state)
        elif args.command == "transcript-source-configure":
            result = instance.reconfigure_transcript_source(
                args.source_id,
                path=args.path,
                profile=args.profile,
                selection_kind=args.selection_kind,
            )
        elif args.command == "transcript-source-schedule":
            result = instance.configure_transcript_source_schedule(
                args.source_id,
                mode=args.mode,
                interval_seconds=args.interval_seconds,
            )
        elif args.command == "transcript-source-remove":
            result = instance.remove_transcript_source(args.source_id)
        elif args.command == "transcript-source-checkpoint":
            result = instance.transcript_source_checkpoint(args.source_id)
        elif args.command == "transcript-source-resync":
            result = instance.reset_transcript_source_cursor(args.source_id)
        elif args.command == "transcript-intake-queue":
            result = instance.queue_transcript_intake(
                args.source_id, request_key=args.request_key
            )
        elif args.command == "transcript-intake-run":
            result = instance.run_transcript_job(args.job_id)
        elif args.command == "transcript-intake-jobs":
            result = instance.list_transcript_jobs(limit=args.limit)
        elif args.command == "transcript-intake-job":
            result = instance.get_transcript_job(args.job_id)
        elif args.command == "transcript-intake-retry":
            result = instance.retry_transcript_job(args.job_id)
        elif args.command == "transcript-intake-cancel":
            result = instance.cancel_transcript_job(args.job_id)
        elif args.command == "transcript-revisions":
            result = instance.list_transcript_revisions(
                source_id=args.source_id, limit=args.limit
            )
        elif args.command == "transcript-revision":
            result = instance.get_transcript_revision(
                args.revision_id, include_content=args.content
            )
        elif args.command == "transcript-original":
            original, data = instance.get_transcript_original(args.revision_id)
            result = {
                "original": original,
                "integrity_verified": True,
                "bytes_base64": (
                    base64.b64encode(data).decode("ascii") if args.base64 else None
                ),
                "private_content_included": bool(args.base64),
            }
        elif args.command == "transcript-derived-remove":
            result = instance.remove_transcript_derived(args.revision_id)
        elif args.command == "transcript-derived-rebuild":
            result = instance.rebuild_transcript_derived(args.revision_id)
        else:
            return None
    except (TranscriptContractError, ConnectorError, SchedulerError, OSError) as exc:
        _print(
            {
                "status": "error",
                "code": getattr(exc, "code", "transcript_internal_error"),
                "error": (
                    str(exc)
                    if not isinstance(exc, OSError)
                    else "local transcript I/O failed"
                ),
            }
        )
        return 2
    if result is None:
        _print({"status": "not_found"})
        return 3
    _print(result)
    if args.command == "transcript-intake-run" and isinstance(result, dict):
        return 0 if result.get("status") == "succeeded" else 2
    return 0


__all__ = ["add_transcript_commands", "handle_transcript_command"]
