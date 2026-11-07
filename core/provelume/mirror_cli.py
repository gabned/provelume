"""Mirror operator controls; configuration and credentials are read from an external file."""

import json
from pathlib import Path

from .icalendar_feeds import _local_path
from .mirror_contract import parse, require
from .mirror_jobs import MirrorJobs, local_preview
from .service import ProvelumeInstance


def add_mirror_commands(commands):
    for name in (
        "status",
        "identity",
        "configure",
        "access",
        "prepare",
        "disable",
        "revoke",
        "discard",
        "forget-plan",
        "drop-generation",
        "schedule",
    ):
        command = commands.add_parser("mirror-" + name)
        command.add_argument("instance", type=Path)
        if name in {"identity", "configure", "access"}:
            command.add_argument("configuration_file", type=Path)
        if name in {"prepare", "disable"}:
            command.add_argument("destination_id")
            command.add_argument("--expected-revision", type=int, required=True)
        if name == "revoke":
            command.add_argument("identity_id")
            command.add_argument("--expected-revision", type=int, required=True)
        if name in {"discard", "forget-plan"}:
            command.add_argument("plan_id")
        if name == "discard":
            command.add_argument("--expected-plan-sha256", required=True)
        if name == "drop-generation":
            command.add_argument("generation")
        if name != "status":
            command.add_argument("--confirm", action="store_true")


def handle_mirror_command(options):
    if not options.command.startswith("mirror-"):
        return None
    try:
        instance = ProvelumeInstance(options.instance)
        engine = instance.mirrors()
        selected = options.command.removeprefix("mirror-")
        if selected != "status":
            require(options.confirm is True, "consent_required")
        if selected in {"identity", "configure", "access"}:
            external = _local_path(options.configuration_file, instance.root)
            require(external.stat().st_size <= 16384, "limit")
            with external.open("rb") as stream:
                configuration = parse(stream.read(16385))
            require("confirmed" not in configuration)
            handler = {
                "identity": engine.create_identity,
                "configure": engine.configure,
                "access": engine.set_access,
            }[selected]
            result = handler(**configuration, confirmed=True)
        elif selected == "status":
            result = engine.view()
        elif selected == "prepare":
            result = local_preview(
                engine, options.destination_id, expected_revision=options.expected_revision
            )
        elif selected == "disable":
            result = engine.disable(
                options.destination_id, expected_revision=options.expected_revision, confirmed=True
            )
        elif selected == "revoke":
            result = engine.revoke(
                options.identity_id, expected_revision=options.expected_revision, confirmed=True
            )
        elif selected == "discard":
            result = engine.discard(
                options.plan_id, expected_plan_sha256=options.expected_plan_sha256, confirmed=True
            )
        elif selected == "forget-plan":
            result = engine.forget_plan(options.plan_id, confirmed=True)
        elif selected == "drop-generation":
            result = engine.drop_generation(options.generation, confirmed=True)
        else:
            result = MirrorJobs(instance.store).policy()
        print(json.dumps({"result": result}, sort_keys=True, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        code = getattr(error, "code", "invalid")
        allowed = {
            "invalid",
            "stale",
            "disabled",
            "local_only",
            "github_disabled",
            "rsync_disabled",
            "limit",
            "generation_limit",
            "plan_limit",
            "deadline",
            "representation_required",
            "authorization_required",
            "in_use",
            "outcome_unknown",
            "integrity",
        }
        print(
            json.dumps(
                {
                    "error": "mirror_operation_unavailable",
                    "code": code if code in allowed else "invalid",
                }
            )
        )
        return 2
