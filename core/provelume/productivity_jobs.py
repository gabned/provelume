"""Scheduler bridge for bounded conformance adapters; each provider owns its evidence."""

from .productivity_connectors import ProductivityConnectors
from .productivity_contract import require
from .productivity_intake import ProductivityIntake
from .scheduler import SchedulerStore, public_job_record
from .scheduler_model import retry_payload, schedule_payload


class ProductivityJobs:
    def __init__(self, store, *, feeds=None):
        self.store, self.host = store, ProductivityConnectors(store)
        self.scheduler = SchedulerStore(store)
        self.feeds = feeds
        self.network_used, self.canonical_mutation = False, False

    def policy(self, source_id, *, interval_seconds=None):
        self.host._records(source_id)
        if interval_seconds is not None:
            require(type(interval_seconds) is int and interval_seconds >= 60, "limit")
            self.host.authority(source_id, "calendar_read", scheduled=True)
        schedule = schedule_payload(mode="interval" if interval_seconds else "manual",
                                    timezone="UTC", interval_seconds=interval_seconds)
        rows = [row for row in self.scheduler.list_policies() if row["job_kind"]
                == "productivity.intake" and row["scope"] == {"kind": "source", "id": source_id}]
        require(len(rows) <= 1, "integrity")
        state = "enabled" if interval_seconds is not None else "disabled"
        if rows:
            return self.scheduler.update_policy(rows[0]["id"], state=state, schedule=schedule)
        return self.scheduler.create_policy(job_kind="productivity.intake",
            scope={"kind": "source", "id": source_id}, state=state, schedule=schedule,
            retry=retry_payload(max_attempts=1))

    def queue(self, source_id, *, request_key=None):
        self.host.authority(source_id, "calendar_read")
        rows = [row for row in self.scheduler.list_policies() if row["job_kind"]
                == "productivity.intake" and row["scope"] == {"kind": "source", "id": source_id}]
        require(len(rows) <= 1, "integrity")
        policy = rows[0] if rows else self.policy(source_id)
        queued = self.scheduler.run_now(policy["id"], request_key=request_key)
        return {"created": queued["created"], "job": public_job_record(queued["job"])}

    def execute(self, job):
        from .icalendar_feeds import IcalendarFeeds

        source_id = job["scope"]["id"]
        _identity, _source, definition = self.host._records(source_id)
        require(definition["provider"] == "icalendar", "unsupported")
        scheduled = job.get("reason") in {"scheduled", "coalesced", "catch_up"}

        def cancelled():
            current = self.scheduler.get_job(job["id"])
            return current is None or current["status"] in {"cancelling", "cancelled", "pausing"}

        feeds = self.feeds or IcalendarFeeds(self.store)
        before = self.store.knowledge_fingerprint()
        feeds.network_used = False
        try:
            preview, adapter = feeds.preview(source_id, scheduled=scheduled, cancelled=cancelled)
            result = ProductivityIntake(self.store).accept_locked(
                preview, cancelled=cancelled, recheck=adapter.recheck)
            return {"processed": result["count"], "skipped": 0, "errors": 0}
        finally:
            self.network_used = feeds.network_used
            self.canonical_mutation = self.store.knowledge_fingerprint() != before
