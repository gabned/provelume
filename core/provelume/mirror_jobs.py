"""Existing scheduler bridge; only independently implemented profiles may publish."""

import time
from datetime import UTC, datetime, timedelta

from .mirror_contract import MAX_SECONDS, MirrorError, fingerprint, require
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
                require(
                    previous["publication"] != "MANUAL_INTERVENTION_REQUIRED", "outcome_unknown"
                )
                due = datetime.fromisoformat(previous["prepared_at"]) + timedelta(
                    seconds=row["interval_seconds"]
                )
                if now < due:
                    skipped += 1
                    continue
            if profile in {"git", "github", "gitlab"}:
                from .mirror_git import GitMirrors
                from .mirror_github import GitHubMirrors
                from .mirror_gitlab import GitLabMirrors

                transport = (
                    {"git": GitMirrors, "github": GitHubMirrors, "gitlab": GitLabMirrors}[profile]
                )(self.store, mirrors=self.mirrors)
                # Explicit scheduled mode supplies current scope consent. An
                # unresolved external claim refuses admission before any process.
                result = None
                try:
                    result = transport.prepare(
                        row["id"],
                        expected_revision=row["revision"],
                        confirmed=True,
                        scheduled=True,
                        _deadline=deadline,
                    )
                    published = transport.publish(
                        result["id"],
                        expected_plan_sha256=result["plan_sha256"],
                        expected_git_plan_sha256=result["git_plan_sha256"],
                        confirmed=True,
                        _deadline=deadline,
                    )
                    require(
                        published["receipt"]["schema"] == "provelume-mirror-receipt/v1", "conflict"
                    )
                except (MirrorError, OSError, ValueError):
                    self.mirrors._pause_scheduled(
                        row["id"], expected_policy_sha256=fingerprint(row)
                    )
                    self.mirrors._save(
                        "scheduled/" + row["id"] + ".json",
                        {
                            "policy_revision": row["revision"],
                            "prepared_at": now.isoformat(),
                            "plan_id": result["id"] if result else None,
                            "publication": "MANUAL_INTERVENTION_REQUIRED",
                        },
                    )
                    raise
                publication = {
                    "github": "COMPLETED_GITHUB",
                    "gitlab": "COMPLETED_GITLAB",
                    "git": "COMPLETED_GIT_LOCAL",
                }[profile]
            else:
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
                publication = "TRANSPORT_NOT_QUALIFIED"
            self.mirrors._save(
                "scheduled/" + row["id"] + ".json",
                {
                    "policy_revision": row["revision"],
                    "prepared_at": now.isoformat(),
                    "plan_id": result["id"],
                    "publication": publication,
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
