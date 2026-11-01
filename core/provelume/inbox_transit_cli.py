"""Local, two-step Inbox consent and exact release commands."""

import json
from pathlib import Path

from .review_effects import ReviewError


def add_inbox_transit_commands(subparsers):
    preview = subparsers.add_parser("inbox-transit-preview", help="Preview Inbox consent or exit")
    preview.add_argument("instance", type=Path)
    preview.add_argument("source_id")
    preview.add_argument("action", choices=("grant", "policy", "release"))
    preview.add_argument("--mode", choices=("transit", "keep"), default="transit")
    preview.add_argument("--disable", action="store_true")
    preview.add_argument("--items", type=Path)
    confirm = subparsers.add_parser("inbox-transit-confirm", help="Confirm an unchanged Inbox plan")
    confirm.add_argument("instance", type=Path)
    confirm.add_argument("source_id")
    confirm.add_argument("plan", type=Path)
    confirm.add_argument("--request-id", required=True)
    release = subparsers.add_parser("inbox-transit-release", help="Execute a confirmed input exit")
    release.add_argument("instance", type=Path)
    release.add_argument("receipt_id")
    status = subparsers.add_parser("inbox-transit-status", help="Read Inbox policy and input state")
    status.add_argument("instance", type=Path)
    status.add_argument("source_id")


def _read(path):
    with path.open("rb") as handle:
        raw = handle.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Inbox plan exceeds its 2 MiB bound")
    return json.loads(raw)


def handle_inbox_transit_command(args):
    if args.command not in {"inbox-transit-preview", "inbox-transit-confirm",
                            "inbox-transit-release", "inbox-transit-status"}:
        return None
    from .service import ProvelumeInstance

    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "inbox-transit-status":
            result = instance.inbox_transit.status(args.source_id)
        elif args.command == "inbox-transit-release":
            result = instance.inbox_transit.release(args.receipt_id)
        elif args.command == "inbox-transit-preview":
            if args.action == "grant":
                result = instance.review_decisions.preview(
                    "capabilities", "inbox_transit", "configure", {
                        "mode": "disabled" if args.disable else "confirm-each",
                        "scope": {"subjects": [args.source_id], "sources": [args.source_id],
                                  "actions": ["release", "save_policy"]}})
            elif args.action == "policy":
                result = instance.review_decisions.preview(
                    "inbox_transit", args.source_id, "save_policy", {"mode": args.mode})
            else:
                if args.items is None:
                    raise ValueError("Release preview requires an exact --items JSON selection")
                result = instance.review_decisions.preview(
                    "inbox_transit", args.source_id, "release", {"items": _read(args.items)})
        else:
            plan = _read(args.plan)
            if (plan["domain"] == "capabilities" and plan["subject"] == "inbox_transit"):
                if (plan["action"] != "configure" or plan["parameters"]["scope"] != {
                        "subjects": [args.source_id], "sources": [args.source_id],
                        "actions": ["release", "save_policy"]}):
                    raise ValueError("Inbox grant must bind this exact Source")
            elif plan["domain"] != "inbox_transit" or plan["subject"] != args.source_id:
                raise ValueError("Inbox confirmation selected another domain or Source")
            result = instance.review_decisions.confirm(
                plan["domain"], plan["subject"], plan["action"], plan["parameters"],
                expected_plan_revision=plan["plan_revision"],
                expected_authority_revision=plan["authority_revision"],
                request_id=args.request_id, principal="local_cli")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ReviewError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2
