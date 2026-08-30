from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .maintenance_model import (
    MAINTENANCE_ACTION_IDS,
    MaintenanceError,
)
from .scheduler import retry_payload, schedule_payload
from .scheduler_model import (
    DST_POLICIES,
    MISSED_RUN_POLICIES,
    POLICY_STATES,
    SCHEDULE_MODES,
    SchedulerBusyError,
    SchedulerError,
)
from .service import ProvelumeInstance

MAINTENANCE_COMMANDS = frozenset(
    {
        "maintenance-catalog",
        "maintenance-action",
        "maintenance-plan",
        "maintenance-policy-create",
        "maintenance-run",
        "maintenance-runs",
        "maintenance-reindex-run",
        "maintenance-source-cursors",
        "maintenance-source-runs",
        "maintenance-source-run",
        "maintenance-resource-status",
        "maintenance-resource-thresholds-set",
        "maintenance-resource-snapshots",
        "maintenance-resource-snapshot",
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


def add_maintenance_commands(subparsers: Any) -> None:
    catalog = subparsers.add_parser(
        "maintenance-catalog",
        help="List the closed maintenance catalogue and exact availability boundaries",
    )
    catalog.add_argument("instance", type=Path)

    action = subparsers.add_parser(
        "maintenance-action",
        help="Show one maintenance action and its durable policies",
    )
    action.add_argument("instance", type=Path)
    action.add_argument("action_id", choices=MAINTENANCE_ACTION_IDS)

    plan = subparsers.add_parser(
        "maintenance-plan",
        help="Dry-run one supported maintenance action without changing derived state",
    )
    plan.add_argument("instance", type=Path)
    plan.add_argument("action_id", choices=MAINTENANCE_ACTION_IDS)

    policy = subparsers.add_parser(
        "maintenance-policy-create",
        help="Create one explicit scheduler policy for an available maintenance action",
    )
    policy.add_argument("instance", type=Path)
    policy.add_argument("action_id", choices=MAINTENANCE_ACTION_IDS)
    policy.add_argument("--source-id")
    policy.add_argument("--state", choices=POLICY_STATES, default="disabled")
    policy.add_argument("--mode", choices=SCHEDULE_MODES, default="manual")
    policy.add_argument("--timezone", default="UTC")
    policy.add_argument("--interval-seconds", type=_positive)
    policy.add_argument("--calendar-time")
    policy.add_argument("--weekday", action="append", type=int, choices=range(7))
    policy.add_argument("--dst-policy", choices=DST_POLICIES, default="earliest")
    policy.add_argument("--quiet-start")
    policy.add_argument("--quiet-end")
    policy.add_argument("--jitter-seconds", type=_non_negative, default=0)
    policy.add_argument(
        "--missed-run-policy",
        choices=MISSED_RUN_POLICIES,
        default="coalesce",
    )
    policy.add_argument("--max-attempts", type=_positive, default=3)
    policy.add_argument("--retry-base-seconds", type=_positive, default=60)
    policy.add_argument("--retry-max-seconds", type=_positive, default=900)

    run = subparsers.add_parser(
        "maintenance-run",
        help="Queue and execute one exact journaled maintenance action",
    )
    run.add_argument("instance", type=Path)
    run.add_argument("action_id", choices=MAINTENANCE_ACTION_IDS)
    run.add_argument("--source-id")
    run.add_argument("--policy-id")
    run.add_argument("--idempotency-key")

    runs = subparsers.add_parser(
        "maintenance-runs",
        help="List durable content-free reindex generation records",
    )
    runs.add_argument("instance", type=Path)
    runs.add_argument("--limit", type=_positive, default=100)

    detail = subparsers.add_parser(
        "maintenance-reindex-run",
        help="Show one durable reindex generation record",
    )
    detail.add_argument("instance", type=Path)
    detail.add_argument("run_id")

    cursors = subparsers.add_parser(
        "maintenance-source-cursors",
        help="List durable, path-redacted Source reconciliation cursors",
    )
    cursors.add_argument("instance", type=Path)

    source_runs = subparsers.add_parser(
        "maintenance-source-runs",
        help="List durable, content-free Source reconciliation runs",
    )
    source_runs.add_argument("instance", type=Path)
    source_runs.add_argument("--limit", type=_positive, default=100)

    source_run = subparsers.add_parser(
        "maintenance-source-run",
        help="Show one durable Source reconciliation run",
    )
    source_run.add_argument("instance", type=Path)
    source_run.add_argument("run_id")

    resource_status = subparsers.add_parser(
        "maintenance-resource-status",
        help="Show path-free Instance resource statistics, thresholds and trends",
    )
    resource_status.add_argument("instance", type=Path)
    resource_status.add_argument("--history-limit", type=_positive, default=30)

    thresholds = subparsers.add_parser(
        "maintenance-resource-thresholds-set",
        help="Replace optional warning and critical Instance capacity thresholds",
    )
    thresholds.add_argument("instance", type=Path)
    thresholds.add_argument("--minimum-free-bytes-warning", type=_non_negative)
    thresholds.add_argument("--minimum-free-bytes-critical", type=_non_negative)
    thresholds.add_argument("--maximum-instance-bytes-warning", type=_non_negative)
    thresholds.add_argument("--maximum-instance-bytes-critical", type=_non_negative)

    resource_snapshots = subparsers.add_parser(
        "maintenance-resource-snapshots",
        help="List durable content-free Instance resource snapshots",
    )
    resource_snapshots.add_argument("instance", type=Path)
    resource_snapshots.add_argument("--limit", type=_positive, default=100)

    resource_snapshot = subparsers.add_parser(
        "maintenance-resource-snapshot",
        help="Show one durable Instance resource snapshot",
    )
    resource_snapshot.add_argument("instance", type=Path)
    resource_snapshot.add_argument("snapshot_id")


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_maintenance_command(args: argparse.Namespace) -> int | None:
    if args.command not in MAINTENANCE_COMMANDS:
        return None
    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "maintenance-catalog":
            _print(instance.maintenance_catalog())
            return 0
        if args.command == "maintenance-action":
            _print(instance.get_maintenance_action(args.action_id))
            return 0
        if args.command == "maintenance-plan":
            result = instance.plan_maintenance_action(args.action_id)
            _print(result)
            return 0 if result["ready"] else 2
        if args.command == "maintenance-policy-create":
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
                instance.create_maintenance_policy(
                    args.action_id,
                    state=args.state,
                    schedule=schedule,
                    retry=retry,
                    source_id=args.source_id,
                )
            )
            return 0
        if args.command == "maintenance-run":
            result = instance.run_maintenance_action(
                args.action_id,
                request_key=args.idempotency_key,
                policy_id=args.policy_id,
                source_id=args.source_id,
            )
            _print(result)
            job = result.get("job")
            return 0 if isinstance(job, dict) and job.get("status") == "succeeded" else 2
        if args.command == "maintenance-runs":
            _print(instance.list_maintenance_runs(limit=args.limit))
            return 0
        if args.command == "maintenance-reindex-run":
            result = instance.get_maintenance_run(args.run_id)
            if result is None:
                _print({"status": "not_found", "run_id": args.run_id})
                return 3
            _print(result)
            return 0
        if args.command == "maintenance-source-cursors":
            _print(instance.list_source_reconciliation_cursors())
            return 0
        if args.command == "maintenance-source-runs":
            _print(instance.list_source_reconciliation_runs(limit=args.limit))
            return 0
        if args.command == "maintenance-source-run":
            result = instance.get_source_reconciliation_run(args.run_id)
            if result is None:
                _print({"status": "not_found", "run_id": args.run_id})
                return 3
            _print(result)
            return 0
        if args.command == "maintenance-resource-status":
            _print(
                instance.resource_statistics_status(
                    history_limit=args.history_limit
                )
            )
            return 0
        if args.command == "maintenance-resource-thresholds-set":
            _print(
                instance.configure_resource_thresholds(
                    minimum_free_bytes_warning=args.minimum_free_bytes_warning,
                    minimum_free_bytes_critical=args.minimum_free_bytes_critical,
                    maximum_instance_bytes_warning=args.maximum_instance_bytes_warning,
                    maximum_instance_bytes_critical=args.maximum_instance_bytes_critical,
                )
            )
            return 0
        if args.command == "maintenance-resource-snapshots":
            _print(instance.list_resource_snapshots(limit=args.limit))
            return 0
        if args.command == "maintenance-resource-snapshot":
            result = instance.get_resource_snapshot(args.snapshot_id)
            if result is None:
                _print({"status": "not_found", "snapshot_id": args.snapshot_id})
                return 3
            _print(result)
            return 0
    except SchedulerBusyError:
        _print({"status": "error", "error": "scheduler_busy"})
        return 2
    except (MaintenanceError, OSError, SchedulerError, ValueError) as exc:
        _print({"status": "error", "error": str(exc)})
        return 2
    raise RuntimeError(f"unsupported maintenance command: {args.command}")


__all__ = ["add_maintenance_commands", "handle_maintenance_command"]
