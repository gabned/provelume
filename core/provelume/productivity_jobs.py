"""Scheduler bridge for bounded conformance adapters; each provider owns its evidence."""

from .productivity_connectors import ProductivityConnectors
from .productivity_contract import require
from .productivity_intake import ProductivityIntake
from .scheduler import SchedulerStore, public_job_record
from .scheduler_model import retry_payload, schedule_payload


def canonical_fingerprint(store):
    from .knowledge_object_contract import record_digest
    from .productivity_contract import fingerprint

    return fingerprint([store.knowledge_fingerprint(), sorted(
        (value["id"], record_digest(value)) for value in store.list_canonical("objects"))],
        maximum=8 * 1024 * 1024)


class ProductivityJobs:
    def __init__(self, store, *, feeds=None, asana=None, tududi=None):
        self.store, self.host = store, ProductivityConnectors(store)
        self.scheduler = SchedulerStore(store)
        self.feeds = feeds
        self.asana = asana
        self.tududi = tududi
        self.network_used, self.canonical_mutation = False, False

    def policy(self, source_id, *, interval_seconds=None):
        _identity, source, _definition = self.host._records(source_id)
        capability = "task_read" if source["source_kind"] == "tasks" else "calendar_read"
        if interval_seconds is not None:
            require(type(interval_seconds) is int and interval_seconds >= 60, "limit")
            self.host.authority(source_id, capability, scheduled=True)
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
        _identity, source, _definition = self.host._records(source_id)
        self.host.authority(source_id, "task_read" if source["source_kind"] == "tasks"
                            else "calendar_read")
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
        require(definition["provider"] in {"icalendar", "asana", "tududi"}, "unsupported")
        scheduled = job.get("reason") in {"scheduled", "coalesced", "catch_up"}

        def cancelled():
            current = self.scheduler.get_job(job["id"])
            return current is None or current["status"] in {"cancelling", "cancelled", "pausing"}

        if definition["provider"] in {"asana", "tududi"}:
            from .asana_connection import AsanaConnection
            from .asana_intake import execute_asana_job
            from .review_decisions import checked_path

            before = canonical_fingerprint(self.store)
            provider = definition["provider"]
            if provider == "tududi":
                from .tududi_connection import TududiConnection
                from .tududi_intake import execute_tududi_job

                connection = self.tududi or TududiConnection(self.store)
                execute = execute_tududi_job
            else:
                connection, execute = self.asana or AsanaConnection(self.store), execute_asana_job
            connection.network_used = False
            try:
                result = execute(self.store, job, connection=connection, cancelled=cancelled)
                self.network_used = result["network_used"]
                self.store._atomic_json(checked_path(self.store,
                    f"state/productivity-providers/{provider}-runs/{job['id']}.json"), {
                    "source_id": source_id, "job_id": job["id"], "status": "completed"
                    if result["status"] == "completed" else "continuation_available",
                    "progress": result["progress"], "network_used": self.network_used})
                self._provider_status(provider, job, "completed" if result["status"] == "completed"
                                      else "continuation_available")
                return result["progress"]
            except (ValueError, OSError) as error:
                code = getattr(error, "code", "invalid")
                allowed = {"rate_limited", "authorization_required", "stale", "scope_mismatch",
                           "account_mismatch", "transport", "response", "cursor_loop",
                           "cursor_invalidated", "selection", "limit", "deadline", "cancelled",
                           "invalid", "unsupported", "integrity", "disabled", "network_disabled",
                           "time_zone", "endpoint"}
                self.store._atomic_json(checked_path(self.store,
                    f"state/productivity-providers/{provider}-runs/{job['id']}.json"), {
                    "source_id": source_id, "job_id": job["id"], "status": "failed",
                    "error_code": code if code in allowed else "invalid",
                    "network_used": connection.network_used})
                self._provider_status(provider, job, "failed",
                                      code if code in allowed else "invalid")
                raise
            finally:
                self.network_used = connection.network_used
                self.canonical_mutation = canonical_fingerprint(self.store) != before
        feeds = self.feeds or IcalendarFeeds(self.store)
        before = canonical_fingerprint(self.store)
        feeds.network_used = False
        try:
            preview, adapter = feeds.preview(source_id, scheduled=scheduled, cancelled=cancelled)
            result = ProductivityIntake(self.store).accept_locked(
                preview, cancelled=cancelled, recheck=adapter.recheck)
            return {"processed": result["count"], "skipped": 0, "errors": 0}
        finally:
            self.network_used = feeds.network_used
            self.canonical_mutation = canonical_fingerprint(self.store) != before

    def _provider_status(self, provider, job, status, error_code=None):
        from .review_decisions import checked_path
        from .storage import utc_now

        self.store._atomic_json(checked_path(self.store,
            f"state/productivity-providers/{provider}-status/{job['scope']['id']}.json"), {
            "source_id": job["scope"]["id"], "job_id": job["id"], "status": status,
            "error_code": error_code, "finished_at": utc_now()})
