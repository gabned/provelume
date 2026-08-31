from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .email_contract import EMAIL_SOURCE_STATES, EMAIL_SUPPORTED_PROFILES, EmailContractError
from .email_sources import EMAIL_SOURCE_SCHEDULE_MODES, EmailSourceError
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance


def _positive_int(value: str) -> int:
    selected = int(value)
    if selected < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return selected


def add_email_commands(subparsers: Any) -> None:
    capability = subparsers.add_parser(
        "email-capability",
        help="Report qualified local email intake without network access",
    )
    capability.add_argument("instance", type=Path)
    capability.add_argument("--source-id")

    create = subparsers.add_parser(
        "email-source-create",
        help="Create a disabled explicit local email Source",
    )
    create.add_argument("instance", type=Path)
    create.add_argument("--name", required=True)
    create.add_argument("--path", required=True, type=Path)
    create.add_argument("--profile", choices=EMAIL_SUPPORTED_PROFILES, required=True)

    sources = subparsers.add_parser(
        "email-source-list",
        help="List configured local email Sources",
    )
    sources.add_argument("instance", type=Path)
    sources.add_argument("--active-only", action="store_true")

    source = subparsers.add_parser(
        "email-source-show",
        help="Show one local email Source including its local path",
    )
    source.add_argument("instance", type=Path)
    source.add_argument("source_id")

    state = subparsers.add_parser(
        "email-source-state",
        help="Enable, pause or disable one local email Source explicitly",
    )
    state.add_argument("instance", type=Path)
    state.add_argument("source_id")
    state.add_argument("state", choices=EMAIL_SOURCE_STATES)

    schedule = subparsers.add_parser(
        "email-source-schedule",
        help="Set a manual or bounded interval policy for one email Source",
    )
    schedule.add_argument("instance", type=Path)
    schedule.add_argument("source_id")
    schedule.add_argument("mode", choices=EMAIL_SOURCE_SCHEDULE_MODES)
    schedule.add_argument("--interval-seconds", type=_positive_int)

    remove_source = subparsers.add_parser(
        "email-source-remove",
        help="Tombstone a local email Source without deleting prior acquisitions",
    )
    remove_source.add_argument("instance", type=Path)
    remove_source.add_argument("source_id")

    queue = subparsers.add_parser(
        "email-intake-queue",
        help="Queue explicit local email intake for one enabled Source",
    )
    queue.add_argument("instance", type=Path)
    queue.add_argument("source_id")
    queue.add_argument("--request-key")

    run = subparsers.add_parser(
        "email-intake-run",
        help="Execute one queued local email intake job",
    )
    run.add_argument("instance", type=Path)
    run.add_argument("job_id")

    jobs = subparsers.add_parser("email-intake-jobs", help="List local email jobs")
    jobs.add_argument("instance", type=Path)
    jobs.add_argument("--limit", type=_positive_int, default=100)

    job = subparsers.add_parser("email-intake-job", help="Show one local email job")
    job.add_argument("instance", type=Path)
    job.add_argument("job_id")

    cancel = subparsers.add_parser("email-intake-cancel", help="Cancel one email job")
    cancel.add_argument("instance", type=Path)
    cancel.add_argument("job_id")

    for command, noun, identifier in (
        ("email-messages", "messages", None),
        ("email-threads", "threads", None),
        ("email-attachments", "attachments", None),
        ("email-message", "message", "message_id"),
        ("email-thread", "thread", "thread_id"),
        ("email-attachment", "attachment", "attachment_id"),
    ):
        parser = subparsers.add_parser(command, help=f"List or inspect email {noun}")
        parser.add_argument("instance", type=Path)
        if identifier is not None:
            parser.add_argument(identifier)
        else:
            parser.add_argument("--limit", type=_positive_int, default=100)
            if command in {"email-messages", "email-threads"}:
                parser.add_argument("--source-id")
            if command == "email-attachments":
                parser.add_argument("--message-id")

    remove = subparsers.add_parser(
        "email-derived-remove",
        help="Remove a derived email representation without changing Originals",
    )
    remove.add_argument("instance", type=Path)
    remove.add_argument("message_id")

    rebuild = subparsers.add_parser(
        "email-derived-rebuild",
        help="Rebuild a derived email representation from its Original",
    )
    rebuild.add_argument("instance", type=Path)
    rebuild.add_argument("message_id")


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_email_command(args: argparse.Namespace) -> int | None:
    if not str(args.command).startswith("email-"):
        return None
    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "email-capability":
            result = instance.email_capability(args.source_id, local=True)
        elif args.command == "email-source-create":
            result = instance.create_email_source(
                name=args.name,
                path=args.path,
                profile=args.profile,
            )
        elif args.command == "email-source-list":
            result = instance.list_email_sources(
                local=True,
                include_removed=not args.active_only,
            )
        elif args.command == "email-source-show":
            result = instance.get_email_source(args.source_id, local=True)
        elif args.command == "email-source-state":
            result = instance.set_email_source_state(args.source_id, args.state)
        elif args.command == "email-source-schedule":
            result = instance.configure_email_source_schedule(
                args.source_id,
                mode=args.mode,
                interval_seconds=args.interval_seconds,
            )
        elif args.command == "email-source-remove":
            result = instance.remove_email_source(args.source_id)
        elif args.command == "email-intake-queue":
            result = instance.queue_email_intake(
                args.source_id,
                request_key=args.request_key,
            )
        elif args.command == "email-intake-run":
            result = instance.run_email_job(args.job_id)
        elif args.command == "email-intake-jobs":
            result = instance.list_email_jobs(limit=args.limit)
        elif args.command == "email-intake-job":
            result = instance.get_email_job(args.job_id)
        elif args.command == "email-intake-cancel":
            result = instance.cancel_email_job(args.job_id)
        elif args.command == "email-messages":
            result = instance.list_email_messages(
                source_id=args.source_id,
                limit=args.limit,
            )
        elif args.command == "email-message":
            result = instance.get_email_message(args.message_id)
        elif args.command == "email-threads":
            result = instance.list_email_threads(
                source_id=args.source_id,
                limit=args.limit,
            )
        elif args.command == "email-thread":
            result = instance.get_email_thread(args.thread_id)
        elif args.command == "email-attachments":
            result = instance.list_email_attachments(
                message_id=args.message_id,
                limit=args.limit,
            )
        elif args.command == "email-attachment":
            result = instance.get_email_attachment(args.attachment_id)
        elif args.command == "email-derived-remove":
            result = instance.remove_email_derived(args.message_id)
        elif args.command == "email-derived-rebuild":
            result = instance.rebuild_email_derived(args.message_id)
        else:
            return None
    except (EmailContractError, EmailSourceError, SchedulerError, OSError) as exc:
        code = getattr(exc, "code", "email_internal_error")
        message = str(exc) if not isinstance(exc, OSError) else "local email I/O failed"
        _print({"status": "error", "code": code, "error": message})
        return 2
    if result is None:
        _print({"status": "not_found"})
        return 3
    _print(result)
    if args.command == "email-intake-run" and isinstance(result, dict):
        return 0 if result.get("status") == "succeeded" else 2
    return 0


__all__ = ["add_email_commands", "handle_email_command"]
