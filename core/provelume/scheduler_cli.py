from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .scheduler import retry_payload, schedule_payload
from .scheduler_model import (
    DST_POLICIES,
    JOB_STATUSES,
    MISSED_RUN_POLICIES,
    POLICY_STATES,
    SCHEDULE_MODES,
    USER_SCHEDULER_JOB_KINDS,
    SchedulerBusyError,
    SchedulerError,
)
from .service import ProvelumeInstance

SCHEDULER_COMMANDS = frozenset(
    {
        "scheduler-policy-create",
        "scheduler-policy-state",
        "scheduler-policies",
        "scheduler-run-now",
        "scheduler-run",
        "scheduler-jobs",
        "scheduler-job",
        "scheduler-receipts",
    }
)


def _positive(value: str) -> int:
    selected = int(value)
    if selected < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return selected


def _non_negative(value: str) -> int:
    selected = int(value)
    if selected < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return selected


def add_scheduler_commands(subparsers: Any) -> None:
    create = subparsers.add_parser(
        "scheduler-policy-create",
        help="Create one durable, user-controlled local scheduler policy",
    )
    create.add_argument("instance", type=Path)
    create.add_argument("--kind", choices=USER_SCHEDULER_JOB_KINDS, required=True)
    create.add_argument("--scope-kind", choices=("instance", "source"), default="instance")
    create.add_argument("--scope-id")
    create.add_argument("--state", choices=POLICY_STATES, default="disabled")
    create.add_argument("--mode", choices=SCHEDULE_MODES, default="manual")
    create.add_argument("--timezone", default="UTC")
    create.add_argument("--interval-seconds", type=_positive)
    create.add_argument("--calendar-time")
    create.add_argument(
        "--weekday",
        action="append",
        type=int,
        choices=range(7),
        help="Calendar weekday, Monday=0; repeat for a subset",
    )
    create.add_argument("--dst-policy", choices=DST_POLICIES, default="earliest")
    create.add_argument("--quiet-start")
    create.add_argument("--quiet-end")
    create.add_argument("--jitter-seconds", type=_non_negative, default=0)
    create.add_argument(
        "--missed-run-policy",
        choices=MISSED_RUN_POLICIES,
        default="coalesce",
    )
    create.add_argument("--max-attempts", type=_positive, default=3)
    create.add_argument("--retry-base-seconds", type=_positive, default=60)
    create.add_argument("--retry-max-seconds", type=_positive, default=900)

    policies = subparsers.add_parser(
        "scheduler-policies",
        help="List durable scheduler policies without executing jobs",
    )
    policies.add_argument("instance", type=Path)

    state = subparsers.add_parser(
        "scheduler-policy-state",
        help="Enable, pause or disable one durable scheduler policy",
    )
    state.add_argument("instance", type=Path)
    state.add_argument("policy_id")
    state.add_argument("state", choices=POLICY_STATES)

    run_now = subparsers.add_parser(
        "scheduler-run-now",
        help="Queue one explicit idempotent run for an executable policy",
    )
    run_now.add_argument("instance", type=Path)
    run_now.add_argument("policy_id")
    run_now.add_argument("--idempotency-key")

    run = subparsers.add_parser(
        "scheduler-run",
        help="Evaluate due policies and execute a bounded number of safe local jobs",
    )
    run.add_argument("instance", type=Path)
    run.add_argument("--max-jobs", type=_positive, default=1)

    jobs = subparsers.add_parser(
        "scheduler-jobs",
        help="List privacy-minimizing durable scheduler jobs",
    )
    jobs.add_argument("instance", type=Path)
    jobs.add_argument("--status", choices=JOB_STATUSES)
    jobs.add_argument("--policy-id")
    jobs.add_argument("--limit", type=_positive, default=100)

    job = subparsers.add_parser(
        "scheduler-job",
        help="Show one durable scheduler job and terminal receipt reference",
    )
    job.add_argument("instance", type=Path)
    job.add_argument("job_id")

    receipts = subparsers.add_parser(
        "scheduler-receipts",
        help="List immutable content-free terminal scheduler receipts",
    )
    receipts.add_argument("instance", type=Path)
    receipts.add_argument("--limit", type=_positive, default=100)


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_scheduler_command(args: argparse.Namespace) -> int | None:
    if args.command not in SCHEDULER_COMMANDS:
        return None
    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "scheduler-policy-create":
            scope_id = args.scope_id
            if args.scope_kind == "instance":
                if scope_id is not None and scope_id != instance.instance_summary()["id"]:
                    raise SchedulerError("Instance scope ID does not match this Instance")
                scope_id = instance.instance_summary()["id"]
            if not scope_id:
                raise SchedulerError("Source scope requires --scope-id")
            schedule = schedule_payload(
                mode=args.mode,
                timezone=args.timezone,
                interval_seconds=args.interval_seconds,
                calendar_time=args.calendar_time,
                weekdays=(
                    sorted(set(args.weekday or list(range(7))))
                    if args.mode == "calendar"
                    else []
                ),
                dst_policy=args.dst_policy,
                quiet_start=args.quiet_start,
                quiet_end=args.quiet_end,
                jitter_seconds=args.jitter_seconds,
                missed_run_policy=args.missed_run_policy,
            )
            retry = retry_payload(
                max_attempts=args.max_attempts,
                base_seconds=args.retry_base_seconds,
                max_seconds=args.retry_max_seconds,
            )
            _print(
                instance.create_schedule_policy(
                    job_kind=args.kind,
                    scope={"kind": args.scope_kind, "id": scope_id},
                    state=args.state,
                    schedule=schedule,
                    retry=retry,
                )
            )
            return 0
        if args.command == "scheduler-policies":
            _print(
                {
                    "status": instance.scheduler_status(),
                    "policies": instance.list_schedule_policies(),
                }
            )
            return 0
        if args.command == "scheduler-policy-state":
            _print(instance.update_schedule_policy(args.policy_id, state=args.state))
            return 0
        if args.command == "scheduler-run-now":
            _print(
                instance.schedule_run_now(
                    args.policy_id,
                    request_key=args.idempotency_key,
                )
            )
            return 0
        if args.command == "scheduler-run":
            result = instance.run_scheduler_cycle(max_jobs=args.max_jobs)
            _print(result)
            return 0 if all(job["status"] == "succeeded" for job in result["jobs"]) else 2
        if args.command == "scheduler-jobs":
            _print(
                instance.list_scheduler_jobs(
                    status=args.status,
                    policy_id=args.policy_id,
                    limit=args.limit,
                )
            )
            return 0
        if args.command == "scheduler-job":
            selected = instance.get_scheduler_job(args.job_id)
            if selected is None:
                _print({"status": "not_found", "job_id": args.job_id})
                return 3
            _print(selected)
            return 0
        if args.command == "scheduler-receipts":
            _print(instance.list_scheduler_receipts(limit=args.limit))
            return 0
    except SchedulerBusyError:
        _print({"status": "error", "error": "scheduler_busy"})
        return 2
    except (OSError, SchedulerError, ValueError) as exc:
        _print({"status": "error", "error": str(exc)})
        return 2
    raise RuntimeError(f"unsupported scheduler command: {args.command}")
