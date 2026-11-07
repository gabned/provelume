"""Explicit local productivity Source policy controls, without provider access."""

import json
from pathlib import Path

from .connector_model import ConnectorError
from .productivity_contract import READ_CAPABILITIES, ProductivityError
from .review_effects import ReviewError
from .service import ProvelumeInstance


def add_productivity_commands(commands):
    for name in ("productivity-policy", "productivity-consent"):
        command = commands.add_parser(name)
        command.add_argument("instance", type=Path)
        command.add_argument("source_id")
        if name == "productivity-consent":
            command.add_argument("--capability", choices=sorted(READ_CAPABILITIES),
                                 action="append", default=[])
            command.add_argument("--mode", choices=("disabled", "manual", "scheduled"),
                                 required=True)
            command.add_argument("--expected-revision", type=int, required=True)
            command.add_argument("--confirm", action="store_true")


def handle_productivity_command(arguments):
    if arguments.command not in {"productivity-policy", "productivity-consent"}:
        return None
    try:
        manager = ProvelumeInstance(arguments.instance).productivity_connectors()
        if arguments.command == "productivity-policy":
            result = manager.policy(arguments.source_id)
        else:
            result = manager.consent(arguments.source_id,
                capabilities=sorted(set(arguments.capability)), mode=arguments.mode,
                expected_revision=arguments.expected_revision, confirmed=arguments.confirm)
        print(json.dumps({"policy": result, "network_attempted": False}, sort_keys=True))
        return 0
    except (ProductivityError, ConnectorError, ReviewError):
        print(json.dumps({"error": "productivity_policy_unavailable", "network_attempted": False}))
        return 2
