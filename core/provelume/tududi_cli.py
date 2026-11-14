"""Tududi operator commands; token configuration comes from an external device file."""

import json
from pathlib import Path

from .icalendar_feeds import _local_path
from .productivity_contract import require
from .productivity_jobs import ProductivityJobs
from .review_decisions import read_json
from .service import ProvelumeInstance
from .tududi_intake import reset_source


def add_tududi_commands(commands):
    for name in ("status", "connect", "catalogue", "source", "read", "reset", "disconnect"):
        command = commands.add_parser("tududi-" + name)
        command.add_argument("instance", type=Path)
        if name == "connect":
            command.add_argument("configuration_file", type=Path)
            command.add_argument("--name", required=True)
            command.add_argument("--identity")
        if name in {"catalogue", "source", "disconnect"}:
            command.add_argument("identity")
        if name in {"connect", "reset", "disconnect"}:
            command.add_argument("--expected-revision", type=int, required=True)
        if name in {"read", "reset"}:
            command.add_argument("source_id")
        if name == "source":
            command.add_argument("--scope", choices=("account", "project", "task"), required=True)
            command.add_argument("--remote-id")
            command.add_argument("--name", required=True)
        if name != "status":
            command.add_argument("--confirm", action="store_true")


def handle_tududi_command(options):
    if not options.command.startswith("tududi-"):
        return None
    try:
        instance = ProvelumeInstance(options.instance)
        manager, selected = instance.tududi_connection(), options.command.removeprefix("tududi-")
        if selected != "status":
            require(options.confirm is True, "consent_required")
        if selected == "status":
            result = manager.view()
        elif selected == "connect":
            path = _local_path(options.configuration_file, instance.root)
            require(path.stat().st_size <= 16384, "limit")
            result = manager.connect(
                json.loads(path.read_bytes()),
                name=options.name,
                identity=options.identity,
                expected_revision=options.expected_revision,
                confirmed=True,
            )
        elif selected == "catalogue":
            manager.catalogue(options.identity, confirmed=True)
            result = manager.catalogs[options.identity]
        elif selected == "source":
            result = manager.select_source(
                options.identity,
                name=options.name,
                scope=options.scope,
                remote_id=options.remote_id,
                confirmed=True,
            )
        elif selected == "read":
            job = ProductivityJobs(instance.store).queue(options.source_id)["job"]
            result = {
                "job": instance.scheduler.run_one(job_id=job["id"]),
                "source_run": read_json(
                    instance.store, f"state/productivity-providers/tududi-runs/{job['id']}.json"
                ),
            }
        elif selected == "reset":
            result = reset_source(
                manager,
                options.source_id,
                expected_policy_revision=options.expected_revision,
                confirmed=True,
            )
        else:
            result = manager.disconnect(
                options.identity, expected_revision=options.expected_revision, confirmed=True
            )
        print(json.dumps({"result": result}, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(
            json.dumps(
                {
                    "error": "tududi_operation_unavailable",
                    "code": "unsupported"
                    if getattr(error, "code", None) == "unsupported"
                    else "invalid",
                }
            )
        )
        return 2
