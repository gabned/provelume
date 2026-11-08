"""Explicit Asana operator commands. OAuth callback sessions belong to the UI server."""

import json
from pathlib import Path

from .asana_intake import reset_source
from .icalendar_feeds import _local_path
from .productivity_contract import require
from .productivity_jobs import ProductivityJobs
from .service import ProvelumeInstance


def add_asana_commands(commands):
    for name in ("status", "configure", "catalogue", "source", "read", "reset", "disconnect",
                 "revoke"):
        command = commands.add_parser("asana-" + name)
        command.add_argument("instance", type=Path)
        if name == "configure":
            command.add_argument("client_file", type=Path)
        if name in {"catalogue", "source", "disconnect", "revoke"}:
            command.add_argument("identity")
        if name in {"read", "reset"}:
            command.add_argument("source_id")
        if name in {"reset", "disconnect", "revoke"}:
            command.add_argument("--expected-revision", type=int, required=True)
        if name in {"catalogue", "source"}:
            command.add_argument("--workspace", required=name == "source")
        if name == "source":
            command.add_argument("--scope",
                choices=("workspace", "organization", "team", "project"), required=True)
            command.add_argument("--name", required=True)
            command.add_argument("--team")
            command.add_argument("--project")
        if name != "status":
            command.add_argument("--confirm", action="store_true")


def handle_asana_command(options):
    if not options.command.startswith("asana-"):
        return None
    try:
        instance = ProvelumeInstance(options.instance)
        manager = instance.asana_connection()
        selected = options.command.removeprefix("asana-")
        if selected != "status":
            require(options.confirm is True, "consent_required")
        if selected == "configure":
            path = _local_path(options.client_file, instance.root)
            require(path.stat().st_size <= 16384, "limit")
            manager.configure(json.loads(path.read_bytes()))
            result = {"status": "configured"}
        elif selected == "status":
            result = manager.view()
        elif selected == "catalogue":
            manager.catalogue(options.identity, workspace=options.workspace, confirmed=True)
            result = manager.catalogs[options.identity]
        elif selected == "source":
            result = manager.select_source(options.identity, name=options.name, scope=options.scope,
                workspace=options.workspace, team=options.team, project=options.project,
                confirmed=True)
        elif selected == "read":
            job = ProductivityJobs(instance.store).queue(options.source_id)["job"]
            from .review_decisions import read_json

            result = {"job": instance.scheduler.run_one(job_id=job["id"]),
                      "source_run": read_json(instance.store,
                        f"state/productivity-providers/asana-runs/{job['id']}.json")}
        elif selected == "reset":
            result = reset_source(manager, options.source_id,
                                  expected_policy_revision=options.expected_revision,
                                  confirmed=True)
        elif selected == "disconnect":
            result = manager.disconnect(options.identity,
                expected_revision=options.expected_revision, confirmed=True)
        else:
            result = manager.revoke_remote(options.identity,
                expected_revision=options.expected_revision, confirmed=True)
        print(json.dumps({"result": result}, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"error": "asana_operation_unavailable"}))
        return 2
