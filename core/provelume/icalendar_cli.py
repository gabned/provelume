"""Explicit feed registration and bounded reads; no payload/credential diagnostics."""

import json
from pathlib import Path

from .connector_model import ConnectorError
from .google_credentials import GoogleCredentialError
from .icalendar_feeds import IcalendarFeeds, _local_path
from .productivity_contract import ProductivityError, require
from .productivity_jobs import ProductivityJobs
from .service import ProvelumeInstance


def add_icalendar_commands(commands):
    add = commands.add_parser("icalendar-add")
    add.add_argument("instance", type=Path)
    add.add_argument("--name", required=True)
    location = add.add_mutually_exclusive_group(required=True)
    location.add_argument("--local", type=Path)
    location.add_argument("--https-location-file", type=Path)
    add.add_argument("--time-zone")
    add.add_argument("--confirm", action="store_true")
    for name in ("icalendar-read", "icalendar-schedule"):
        command = commands.add_parser(name)
        command.add_argument("instance", type=Path)
        command.add_argument("source_id")
        if name == "icalendar-schedule":
            command.add_argument("--interval-seconds", type=int)
        command.add_argument("--confirm", action="store_true")
    duplicates = commands.add_parser("icalendar-duplicates")
    duplicates.add_argument("instance", type=Path)


def handle_icalendar_command(options):
    if options.command not in {"icalendar-add", "icalendar-read", "icalendar-schedule",
                                "icalendar-duplicates"}:
        return None
    try:
        instance = ProvelumeInstance(options.instance)
        manager = IcalendarFeeds(instance.store)
        if options.command == "icalendar-duplicates":
            result = manager.duplicates()
        else:
            require(options.confirm is True, "consent_required")
            if options.command == "icalendar-add":
                location, authorization = options.local, None
                if options.https_location_file is not None:
                    path = _local_path(options.https_location_file, instance.root)
                    require(path.stat().st_size <= 16384, "limit")
                    record = json.loads(path.read_bytes())
                    require(type(record) is dict and set(record) <= {"url", "authorization"})
                    location, authorization = record["url"], record.get("authorization")
                result = manager.add(name=options.name,
                    kind="local" if options.local is not None else "https",
                    location=location, authorization=authorization, time_zone=options.time_zone,
                    confirmed=True)
            elif options.command == "icalendar-schedule":
                result = ProductivityJobs(instance.store).policy(
                    options.source_id, interval_seconds=options.interval_seconds)
            else:
                queued = ProductivityJobs(instance.store).queue(options.source_id)
                result = instance.scheduler.run_one(job_id=queued["job"]["id"])
        print(json.dumps({"result": result}, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, ConnectorError, ProductivityError,
            GoogleCredentialError):
        print(json.dumps({"error": "icalendar_operation_unavailable"}))
        return 2
