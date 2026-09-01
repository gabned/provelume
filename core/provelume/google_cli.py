from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .google_contract import GOOGLE_CAPABILITIES, GOOGLE_SOURCE_STATES, GoogleContractError
from .google_sources import GOOGLE_SCHEDULE_MODES
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance


def _positive_int(value: str) -> int:
    selected = int(value)
    if selected < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return selected


def add_google_commands(subparsers: Any) -> None:
    create = subparsers.add_parser(
        "google-connector-create",
        help="Create one disabled Google identity with separate Gmail and Drive consent",
    )
    create.add_argument("instance", type=Path)
    create.add_argument("--name", required=True)
    create.add_argument("--account-identity", required=True)

    listing = subparsers.add_parser("google-connectors", help="List Google identities")
    listing.add_argument("instance", type=Path)
    show = subparsers.add_parser("google-connector", help="Show one Google identity")
    show.add_argument("instance", type=Path)
    show.add_argument("connector_instance_id")
    state = subparsers.add_parser(
        "google-connector-state", help="Enable or disable one Google connector explicitly"
    )
    state.add_argument("instance", type=Path)
    state.add_argument("connector_instance_id")
    state.add_argument("state", choices=("enabled", "disabled"))

    authorize = subparsers.add_parser(
        "google-capability-authorize",
        help="Authorize Gmail or Drive using only an external credential reference",
    )
    authorize.add_argument("instance", type=Path)
    authorize.add_argument("connector_instance_id")
    authorize.add_argument("capability", choices=GOOGLE_CAPABILITIES)
    authorize.add_argument(
        "--credential-kind", choices=("environment", "system_keyring"), required=True
    )
    authorize.add_argument("--credential-name", required=True)
    authorize.add_argument("--consent", action="store_true", required=True)

    capability_state = subparsers.add_parser(
        "google-capability-state", help="Enable or disable Gmail or Drive independently"
    )
    capability_state.add_argument("instance", type=Path)
    capability_state.add_argument("connector_instance_id")
    capability_state.add_argument("capability", choices=GOOGLE_CAPABILITIES)
    capability_state.add_argument("state", choices=("enabled", "disabled"))

    revoke = subparsers.add_parser(
        "google-capability-revoke", help="Revoke Gmail or Drive independently"
    )
    revoke.add_argument("instance", type=Path)
    revoke.add_argument("connector_instance_id")
    revoke.add_argument("capability", choices=GOOGLE_CAPABILITIES)

    source_create = subparsers.add_parser(
        "google-source-create", help="Create one disabled explicitly selected Google Source"
    )
    source_create.add_argument("instance", type=Path)
    source_create.add_argument("connector_instance_id")
    source_create.add_argument("--name", required=True)
    source_create.add_argument("--capability", choices=GOOGLE_CAPABILITIES, required=True)
    source_create.add_argument(
        "--selection-kind", choices=("mailbox", "label", "file", "folder"), required=True
    )
    source_create.add_argument("--selector", action="append", required=True)

    sources = subparsers.add_parser("google-sources", help="List Google Sources")
    sources.add_argument("instance", type=Path)
    source = subparsers.add_parser("google-source", help="Show one Google Source")
    source.add_argument("instance", type=Path)
    source.add_argument("source_id")
    source_state = subparsers.add_parser(
        "google-source-state", help="Enable, pause or disable one Google Source"
    )
    source_state.add_argument("instance", type=Path)
    source_state.add_argument("source_id")
    source_state.add_argument("state", choices=GOOGLE_SOURCE_STATES)
    schedule = subparsers.add_parser(
        "google-source-schedule", help="Set a manual or bounded interval Google policy"
    )
    schedule.add_argument("instance", type=Path)
    schedule.add_argument("source_id")
    schedule.add_argument("mode", choices=GOOGLE_SCHEDULE_MODES)
    schedule.add_argument("--interval-seconds", type=_positive_int)
    reset = subparsers.add_parser("google-source-reset", help="Reset one Source cursor explicitly")
    reset.add_argument("instance", type=Path)
    reset.add_argument("source_id")
    remove = subparsers.add_parser("google-source-remove", help="Tombstone one Google Source")
    remove.add_argument("instance", type=Path)
    remove.add_argument("source_id")

    queue = subparsers.add_parser(
        "google-intake-queue", help="Queue bounded read-only Google intake"
    )
    queue.add_argument("instance", type=Path)
    queue.add_argument("source_id")
    queue.add_argument("--request-key")
    run = subparsers.add_parser("google-intake-run", help="Run one queued Google job")
    run.add_argument("instance", type=Path)
    run.add_argument("job_id")
    jobs = subparsers.add_parser("google-intake-jobs", help="List Google jobs")
    jobs.add_argument("instance", type=Path)
    jobs.add_argument("--limit", type=_positive_int, default=100)
    job = subparsers.add_parser("google-intake-job", help="Show one Google job")
    job.add_argument("instance", type=Path)
    job.add_argument("job_id")
    cancel = subparsers.add_parser("google-intake-cancel", help="Cancel one Google job")
    cancel.add_argument("instance", type=Path)
    cancel.add_argument("job_id")

    gmail = subparsers.add_parser(
        "google-gmail-observations", help="List hashed non-authoritative Gmail observations"
    )
    gmail.add_argument("instance", type=Path)
    gmail.add_argument("--limit", type=_positive_int, default=100)
    drive = subparsers.add_parser(
        "google-drive-revisions", help="List provider-neutral Drive revision evidence"
    )
    drive.add_argument("instance", type=Path)
    drive.add_argument("--limit", type=_positive_int, default=100)


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_google_command(args: argparse.Namespace) -> int | None:
    if not str(args.command).startswith("google-"):
        return None
    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "google-connector-create":
            result = instance.create_google_instance(
                name=args.name, account_identity=args.account_identity
            )
        elif args.command == "google-connectors":
            result = instance.list_google_instances()
        elif args.command == "google-connector":
            result = instance.get_google_instance(args.connector_instance_id)
        elif args.command == "google-connector-state":
            result = instance.set_google_connector_state(
                args.connector_instance_id, enabled=args.state == "enabled"
            )
        elif args.command == "google-capability-authorize":
            result = instance.authorize_google_capability(
                args.connector_instance_id,
                args.capability,
                credential_reference={"kind": args.credential_kind, "name": args.credential_name},
                consent=args.consent,
            )
        elif args.command == "google-capability-state":
            result = instance.set_google_capability_state(
                args.connector_instance_id, args.capability, state=args.state
            )
        elif args.command == "google-capability-revoke":
            result = instance.revoke_google_capability(args.connector_instance_id, args.capability)
        elif args.command == "google-source-create":
            result = instance.create_google_source(
                args.connector_instance_id,
                name=args.name,
                capability=args.capability,
                selection_kind=args.selection_kind,
                selectors=args.selector,
            )
        elif args.command == "google-sources":
            result = instance.list_google_sources()
        elif args.command == "google-source":
            result = instance.get_google_source(args.source_id)
        elif args.command == "google-source-state":
            result = instance.set_google_source_state(args.source_id, state=args.state)
        elif args.command == "google-source-schedule":
            result = instance.configure_google_source_schedule(
                args.source_id, mode=args.mode, interval_seconds=args.interval_seconds
            )
        elif args.command == "google-source-reset":
            result = instance.reset_google_source_cursor(args.source_id)
        elif args.command == "google-source-remove":
            result = instance.remove_google_source(args.source_id)
        elif args.command == "google-intake-queue":
            result = instance.queue_google_intake(args.source_id, request_key=args.request_key)
        elif args.command == "google-intake-run":
            result = instance.run_google_job(args.job_id)
        elif args.command == "google-intake-jobs":
            result = instance.list_google_jobs(limit=args.limit)
        elif args.command == "google-intake-job":
            result = instance.get_google_job(args.job_id)
        elif args.command == "google-intake-cancel":
            result = instance.cancel_google_job(args.job_id)
        elif args.command == "google-gmail-observations":
            result = instance.list_google_gmail_observations(limit=args.limit)
        elif args.command == "google-drive-revisions":
            result = instance.list_google_drive_revisions(limit=args.limit)
        else:
            return None
    except (GoogleContractError, SchedulerError, OSError) as exc:
        _print(
            {
                "status": "error",
                "code": getattr(exc, "code", "google_internal_error"),
                "error": str(exc),
            }
        )
        return 2
    if result is None:
        _print({"status": "not_found"})
        return 3
    _print(result)
    if args.command == "google-intake-run" and isinstance(result, dict):
        return 0 if result.get("status") == "succeeded" else 2
    return 0


__all__ = ["add_google_commands", "handle_google_command"]
