from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .qualification_contract import (
    DECISION_ACTIONS,
    FINDING_TYPES,
    WORKFLOW_STATES,
    QualificationError,
)
from .service import ProvelumeInstance


def _positive(value: str) -> int:
    selected = int(value)
    if selected < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return selected


def add_qualification_commands(subparsers: Any) -> None:
    for command, help_text in (
        ("qualification-matrix", "Inspect the closed cross-source qualification matrix"),
        ("qualification-limits", "Inspect bounded qualification defaults and ceilings"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)

    for command, help_text in (
        ("qualification-source-checkpoint", "Inspect one Source-confined checkpoint"),
        ("qualification-source-resync", "Reset one Source qualification cursor"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("source_id")

    queue = subparsers.add_parser(
        "qualification-queue", help="Queue an explicit bounded cross-source qualification"
    )
    queue.add_argument("instance", type=Path)
    queue.add_argument("--source-id", action="append", required=True)
    queue.add_argument("--request-key")
    queue.add_argument("--limits-json")

    jobs = subparsers.add_parser("qualification-jobs", help="List qualification jobs")
    jobs.add_argument("instance", type=Path)
    jobs.add_argument("--limit", type=_positive, default=100)
    for command, help_text in (
        ("qualification-job", "Inspect one qualification job"),
        ("qualification-run", "Run one queued qualification job"),
        ("qualification-retry", "Retry a failed or cancelled qualification job"),
        ("qualification-cancel", "Cancel one qualification job"),
        ("qualification-rebuild", "Recalculate findings from current Source state"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("instance", type=Path)
        parser.add_argument("job_id")

    findings = subparsers.add_parser(
        "qualification-findings", help="List provider-neutral qualification findings"
    )
    findings.add_argument("instance", type=Path)
    findings.add_argument("--source-id")
    findings.add_argument("--finding-type", choices=FINDING_TYPES)
    findings.add_argument("--workflow-state", choices=WORKFLOW_STATES)
    findings.add_argument("--limit", type=_positive, default=100)

    finding = subparsers.add_parser(
        "qualification-finding", help="Inspect finding evidence, provenance and history"
    )
    finding.add_argument("instance", type=Path)
    finding.add_argument("finding_id")

    decide = subparsers.add_parser(
        "qualification-decide", help="Append an attributed reversible human decision"
    )
    decide.add_argument("instance", type=Path)
    decide.add_argument("finding_id")
    decide.add_argument("--action", choices=DECISION_ACTIONS, required=True)
    decide.add_argument("--actor-id", required=True)
    decide.add_argument("--reason", required=True)
    decide.add_argument("--expected-revision", type=int, required=True)
    decide.add_argument("--payload-json")

    decisions = subparsers.add_parser(
        "qualification-decisions", help="Inspect append-only decision history"
    )
    decisions.add_argument("instance", type=Path)
    decisions.add_argument("--finding-id")
    decision = subparsers.add_parser(
        "qualification-decision", help="Inspect one qualification decision"
    )
    decision.add_argument("instance", type=Path)
    decision.add_argument("decision_id")


def _mapping(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    selected = json.loads(value)
    if not isinstance(selected, dict):
        raise QualificationError("qualification_invalid_decision", "JSON input must be an object")
    return selected


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_qualification_command(args: argparse.Namespace) -> int | None:
    if not str(args.command).startswith("qualification-"):
        return None
    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "qualification-matrix":
            result = instance.qualification_matrix()
        elif args.command == "qualification-limits":
            result = instance.qualification_limits()
        elif args.command == "qualification-source-checkpoint":
            result = instance.qualification_source_checkpoint(args.source_id)
        elif args.command == "qualification-source-resync":
            result = instance.reset_qualification_source(args.source_id)
        elif args.command == "qualification-queue":
            result = instance.queue_qualification(
                args.source_id,
                limits=_mapping(args.limits_json),
                request_key=args.request_key,
            )
        elif args.command == "qualification-jobs":
            result = instance.list_qualification_jobs(limit=args.limit)
        elif args.command == "qualification-job":
            result = instance.get_qualification_job(args.job_id)
        elif args.command == "qualification-run":
            result = instance.run_qualification(args.job_id)
        elif args.command == "qualification-retry":
            result = instance.retry_qualification(args.job_id)
        elif args.command == "qualification-cancel":
            result = instance.cancel_qualification(args.job_id)
        elif args.command == "qualification-rebuild":
            result = instance.rebuild_qualification(args.job_id)
        elif args.command == "qualification-findings":
            result = instance.list_qualification_findings(
                source_id=args.source_id,
                finding_type=args.finding_type,
                workflow_state=args.workflow_state,
                limit=args.limit,
            )
        elif args.command == "qualification-finding":
            result = instance.get_qualification_finding(args.finding_id)
        elif args.command == "qualification-decide":
            result = instance.decide_qualification_finding(
                args.finding_id,
                action=args.action,
                actor_id=args.actor_id,
                reason=args.reason,
                expected_revision=args.expected_revision,
                payload=_mapping(args.payload_json),
            )
        elif args.command == "qualification-decisions":
            result = instance.list_qualification_decisions(args.finding_id)
        elif args.command == "qualification-decision":
            result = instance.get_qualification_decision(args.decision_id)
        else:
            return None
    except (QualificationError, json.JSONDecodeError, OSError) as exc:
        _print(
            {
                "status": "error",
                "code": getattr(exc, "code", "qualification_invalid_json"),
                "error": str(exc) if not isinstance(exc, OSError) else "local I/O failed",
            }
        )
        return 2
    if result is None:
        _print({"status": "not_found"})
        return 3
    _print(result)
    if args.command == "qualification-run" and isinstance(result, dict):
        return 0 if result.get("status") == "succeeded" else 2
    return 0


__all__ = ["add_qualification_commands", "handle_qualification_command"]
