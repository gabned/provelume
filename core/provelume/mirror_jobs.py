"""Existing scheduler bridge: prepare complete local generations, never publish."""

import time
from datetime import UTC, datetime, timedelta

from .mirror_contract import MAX_SECONDS, require
from .mirrors import Mirrors
from .scheduler import SchedulerStore
from .scheduler_model import retry_payload, schedule_payload


class MirrorJobs:
    def __init__(self, store, *, mirrors=None):
        self.store = store
        self.mirrors = mirrors or Mirrors(store)
        self.scheduler = SchedulerStore(store)

    def policy(self):
        enabled = self.mirrors.access()["enabled"] and any(
            row["mode"] == "scheduled" and row["device"] == self.mirrors.device()
            for row in self.mirrors.state()["destinations"]
        )
        rows = [
            row for row in self.scheduler.list_policies() if row["job_kind"] == "mirror.prepare"
        ]
        require(len(rows) <= 1, "integrity")
        schedule = schedule_payload(mode="interval", timezone="UTC", interval_seconds=60)
        if rows:
            return self.scheduler.update_policy(
                rows[0]["id"], state="enabled" if enabled else "disabled", schedule=schedule
            )
        return self.scheduler.create_policy(
            job_kind="mirror.prepare",
            scope={"kind": "instance", "id": self.store.read_config()["instance"]["id"]},
            state="enabled" if enabled else "disabled",
            schedule=schedule,
            retry=retry_payload(max_attempts=1),
        )

    def execute(self, job):
        require(job["job_kind"] == "mirror.prepare")
        processed, skipped = 0, 0
        deadline = time.monotonic() + MAX_SECONDS
        now = datetime.now(UTC)
        access = self.mirrors.access()
        for row in self.mirrors.state()["destinations"]:
            current = self.scheduler.get_job(job["id"])
            require(
                current is not None
                and current["status"] not in {"cancelled", "cancelling", "pausing"},
                "cancelled",
            )
            require(time.monotonic() <= deadline, "deadline")
            profile = self.mirrors.identity(row["identity_id"])["profile"]
            if (
                row["mode"] != "scheduled"
                or not access["enabled"]
                or (profile == "github" and not access["github"])
                or (profile == "rsync-ssh" and not access["rsync"])
            ):
                skipped += 1
                continue
            previous = self.mirrors._load("scheduled/" + row["id"] + ".json")
            if previous is not None and previous["policy_revision"] == row["revision"]:
                due = datetime.fromisoformat(previous["prepared_at"]) + timedelta(
                    seconds=row["interval_seconds"]
                )
                if now < due:
                    skipped += 1
                    continue
            # A local-only observation is explicitly UNKNOWN, never an invented remote check.
            result = self.mirrors.preview(
                row["id"],
                {
                    "destination_sha256": row["destination_sha256"],
                    "visibility": "unknown",
                    "writable": False,
                    "inventory": [],
                    "revision": "NOT_OBSERVED",
                },
                expected_revision=row["revision"],
                scheduled=True,
                _deadline=deadline,
            )
            self.mirrors._save(
                "scheduled/" + row["id"] + ".json",
                {
                    "policy_revision": row["revision"],
                    "prepared_at": now.isoformat(),
                    "plan_id": result["id"],
                    "publication": "TRANSPORT_NOT_QUALIFIED",
                },
            )
            processed += 1
        return {"processed": processed, "skipped": skipped, "errors": 0}


def local_preview(engine, destination_id, *, expected_revision):
    row = engine.destination(destination_id)
    return engine.preview(
        destination_id,
        {
            "destination_sha256": row["destination_sha256"],
            "visibility": "unknown",
            "writable": False,
            "inventory": [],
            "revision": "NOT_OBSERVED",
        },
        expected_revision=expected_revision,
    )
