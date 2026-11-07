"""Single-confirmation task writes: closed fields, atomic remote condition, no retry.

Public providers are deliberately unavailable until their actual primitive is
qualified. The injection seam is restricted to a network-free synthetic provider
and cannot be enabled by an application request or imported capability document.
"""

import time
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

from .connectors import ConnectorManager
from .instance_lifecycle import InstanceLifecycleManager
from .knowledge_object_contract import record_digest
from .productivity_connectors import ProductivityConnectors
from .productivity_contract import fingerprint, require, temporal, text
from .productivity_objects import connector_object_snapshot
from .review_decisions import checked_path, read_json
from .storage import utc_now

ROOT = "state/task-writeback"
FIELDS = frozenset({"completed", "due"})
QUALIFICATION_KEY = "synthetic-task-cas-qualification"
QUALIFICATION_PROFILE = "synthetic-memory-cas/v1"


def changes(value):
    require(type(value) is dict and value and set(value) <= FIELDS, "unsupported_fields")
    if "completed" in value:
        require(type(value["completed"]) is bool)
    if value.get("due") is not None:
        temporal(value["due"])
    return deepcopy(value)


def remote_state(value):
    require(type(value) is dict and set(value) == {"revision", "completed", "due"}, "response")
    text(value["revision"], 2048)
    changes({"completed": value["completed"], "due": value["due"]})
    return value


class TaskWriteBack:
    def __init__(self, store, *, _qualification_adapter=None):
        self.store, self.connectors = store, ConnectorManager(store)
        self.host = ProductivityConnectors(store)
        self._qualification_adapter = _qualification_adapter

    @contextmanager
    def guard(self):
        with (
            InstanceLifecycleManager(self.store)._hold(purpose="task-writeback"),
            self.connectors.policy_commit_guard(purpose="task-writeback"),
        ):
            yield

    def object(self, object_id):
        value = self.store.read_canonical("objects", object_id)
        require(
            value is not None
            and value["kind"] == "task"
            and value["origin"]["kind"] == "connector",
            "unsupported",
        )
        snapshot = connector_object_snapshot(self.store, value)
        return value, snapshot

    def capability(self, source_id):
        _identity, _source, definition = self.host._records(source_id)
        synthetic = (
            definition["provider"] == "synthetic"
            and definition["adapter_key"] == QUALIFICATION_KEY
            and definition["network_access"] == "none"
            and self._qualification_adapter is not None
            and self._qualification_adapter.profile == QUALIFICATION_PROFILE
        )
        return {
            "provider": definition["provider"],
            "available": synthetic,
            "qualification_only": synthetic,
            "atomic_remote_revision": "SYNTHETIC_ONLY" if synthetic else "NOT_QUALIFIED",
            "fields": sorted(FIELDS),
            "release_status": "SYNTHETIC_ONLY" if synthetic else "DEFERRED_BY_MAINTAINER",
        }

    def adapter(self, source_id):
        require(self.capability(source_id)["available"], "conditional_write_unavailable")
        return self._qualification_adapter

    def ledger(self, source_id):
        value = read_json(self.store, f"{ROOT}/{source_id}/ledger.json")
        if value is None:
            return {
                "schema": "task-writeback-source/v1",
                "source_id": source_id,
                "consent": {
                    "revision": 0,
                    "enabled": False,
                    "fields": [],
                    "identity_id": None,
                    "device_binding": None,
                },
                "inflight": None,
            }
        require(
            type(value) is dict
            and set(value) == {"schema", "source_id", "consent", "inflight"}
            and value["schema"] == "task-writeback-source/v1"
            and value["source_id"] == source_id,
            "integrity",
        )
        consent = value["consent"]
        require(
            type(consent) is dict
            and set(consent) == {"revision", "enabled", "fields", "identity_id", "device_binding"}
            and type(consent["revision"]) is int
            and consent["revision"] >= 0
            and type(consent["enabled"]) is bool
            and type(consent["fields"]) is list
            and all(type(field) is str and field in FIELDS for field in consent["fields"])
            and len(consent["fields"]) == len(set(consent["fields"])),
            "integrity",
        )
        if consent["revision"] > 0:
            identity, _source, _definition = self.host._records(source_id)
            require(consent["identity_id"] == identity["id"], "integrity")
            entry = read_json(
                self.store, f"{ROOT}/{source_id}/consents/{consent['revision']:08d}.json"
            )
            require(
                entry is not None and all(entry.get(key) == val for key, val in consent.items()),
                "integrity",
            )
        inflight = value["inflight"]
        require(
            inflight is None
            or (
                type(inflight) is dict
                and set(inflight) == {"plan", "operation_id", "status"}
                and inflight["status"] in {"DISPATCHED", "UNKNOWN"}
                and inflight["plan"]["source_id"] == source_id
            ),
            "integrity",
        )
        return value

    def device_binding(self):
        return fingerprint(
            [self.store.read_config()["instance"]["id"], str(self.store.paths.root.absolute())]
        )

    def save_ledger(self, value):
        self.store._atomic_json(
            checked_path(self.store, f"{ROOT}/{value['source_id']}/ledger.json"), value
        )

    def consent(self, source_id, *, enabled, fields, expected_revision, confirmed):
        require(confirmed is True and type(enabled) is bool, "consent_required")
        require(
            type(fields) is list
            and len(fields) == len(set(fields))
            and set(fields) <= FIELDS
            and (bool(fields) or not enabled),
            "unsupported_fields",
        )
        if enabled:
            self.adapter(source_id)
        with self.guard():
            identity, _source, _definition = self.host._records(source_id)
            ledger = self.ledger(source_id)
            previous = ledger["consent"]
            require(previous["revision"] == expected_revision, "stale")
            consent = {
                "revision": previous["revision"] + 1,
                "enabled": enabled,
                "fields": sorted(fields),
                "identity_id": identity["id"],
                "device_binding": self.device_binding(),
            }
            # Immutable revision is durable before publishing the active pointer.
            path = checked_path(
                self.store, f"{ROOT}/{source_id}/consents/{consent['revision']:08d}.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {**consent, "previous_sha256": fingerprint(previous), "at": utc_now()}
            if path.exists():
                require(
                    read_json(self.store, str(path.relative_to(self.store.paths.root)))[
                        "previous_sha256"
                    ]
                    == fingerprint(previous),
                    "integrity",
                )
                # A prior interrupted publication cannot authorize a different choice.
                old = read_json(self.store, str(path.relative_to(self.store.paths.root)))
                require(all(old[key] == consent[key] for key in consent), "stale")
            else:
                self.store._atomic_json(path, payload)
            self.save_ledger({**ledger, "consent": consent})
            return consent

    def binding(self, source_id):
        identity, _source, _definition = self.host._records(source_id)
        adapter = self.adapter(source_id)
        return {
            "read_authority": self.host.authority(source_id, "task_read")["sha256"],
            "consent": self.ledger(source_id)["consent"],
            "identity_id": identity["id"],
            "credential_epoch": adapter.epoch(identity["id"]),
        }

    def prepare(self, object_id, requested, *, expected_local_sha256, expected_consent_revision):
        requested = changes(requested)
        obj, snapshot = self.object(object_id)
        source_id, item = snapshot["source_id"], snapshot["item"]
        adapter = self.adapter(source_id)
        require(
            snapshot["current"] and item["state"] in {"open", "in_progress", "completed"},
            "stale_source",
        )
        require(record_digest(obj) == expected_local_sha256, "stale")
        admitted = self.binding(source_id)
        consent = admitted["consent"]
        require(
            consent["enabled"]
            and consent["device_binding"] == self.device_binding()
            and consent["revision"] == expected_consent_revision
            and set(requested) <= set(consent["fields"]),
            "consent_required",
        )
        require(self.ledger(source_id)["inflight"] is None, "unknown_outcome")
        remote = remote_state(adapter.read(item["remote_id"]))
        observed = {"completed": item["state"] == "completed", "due": item["due"]}
        require(all(remote[key] == observed[key] for key in observed), "stale_source")
        before = {key: remote[key] for key in requested}
        require(any(before[key] != value for key, value in requested.items()), "no_change")
        plan = {
            "schema": "task-writeback-plan/v1",
            "id": uuid4().hex,
            "source_id": source_id,
            "object_id": object_id,
            "local_sha256": expected_local_sha256,
            "remote_id": item["remote_id"],
            "expected_remote_revision": remote["revision"],
            "before": before,
            "changes": requested,
            "binding": admitted,
            "expires_at": time.time() + 900,
        }
        plan["sha256"] = fingerprint(plan)
        with self.guard():
            current, _snapshot = self.object(object_id)
            require(
                record_digest(current) == expected_local_sha256
                and self.binding(source_id) == admitted,
                "stale",
            )
            require(self.ledger(source_id)["inflight"] is None, "unknown_outcome")
            directory = checked_path(self.store, f"{ROOT}/{source_id}/plans")
            directory.mkdir(parents=True, exist_ok=True)
            pending = list(directory.glob("*.json"))
            for path in pending:
                old = self.load_plan(source_id, path.stem)
                if old["expires_at"] < time.time():
                    path.unlink()
            pending = list(directory.glob("*.json"))
            require(len(pending) < 32, "limit")
            self.store._atomic_json(directory / (plan["id"] + ".json"), plan)
        return plan

    def load_plan(self, source_id, plan_id):
        require(
            type(plan_id) is str
            and len(plan_id) == 32
            and all(char in "0123456789abcdef" for char in plan_id)
        )
        value = read_json(self.store, f"{ROOT}/{source_id}/plans/{plan_id}.json")
        require(
            value is not None
            and value["schema"] == "task-writeback-plan/v1"
            and value["id"] == plan_id
            and value["source_id"] == source_id,
            "stale",
        )
        require(
            value["sha256"]
            == fingerprint({key: val for key, val in value.items() if key != "sha256"}),
            "integrity",
        )
        return value

    def audit(self, source_id, plan_id):
        require(
            type(plan_id) is str
            and len(plan_id) == 32
            and all(char in "0123456789abcdef" for char in plan_id)
        )
        return read_json(self.store, f"{ROOT}/{source_id}/receipts/{plan_id}.json")

    def discard(self, object_id, plan_id, *, expected_plan_sha256):
        with self.guard():
            _obj, snapshot = self.object(object_id)
            source_id = snapshot["source_id"]
            require(self.ledger(source_id)["inflight"] is None, "unknown_outcome")
            plan = self.load_plan(source_id, plan_id)
            require(
                plan["object_id"] == object_id and plan["sha256"] == expected_plan_sha256, "stale"
            )
            checked_path(self.store, f"{ROOT}/{source_id}/plans/{plan_id}.json").unlink()
        return {"status": "DISCARDED"}

    @staticmethod
    def outcome(value, operation):
        require(
            type(value) is dict
            and set(value) == {"operation_id", "outcome", "revision"}
            and value["operation_id"] == operation
            and value["outcome"] in {"APPLIED", "CONFLICT", "NOT_APPLIED", "UNKNOWN"},
            "response",
        )
        if value["outcome"] == "APPLIED":
            text(value["revision"], 2048)
        return value

    def finish(self, plan, outcome):
        with self.guard():
            ledger = self.ledger(plan["source_id"])
            inflight = ledger["inflight"]
            existing = self.audit(plan["source_id"], plan["id"])
            if existing is not None:
                require(existing["plan_sha256"] == plan["sha256"], "integrity")
                if inflight is not None and inflight["plan"]["sha256"] == plan["sha256"]:
                    self.save_ledger({**ledger, "inflight": None})
                return existing
            require(
                inflight is not None and inflight["plan"]["sha256"] == plan["sha256"], "integrity"
            )
            if outcome["outcome"] == "UNKNOWN":
                self.save_ledger({**ledger, "inflight": {**inflight, "status": "UNKNOWN"}})
                return {"status": "UNKNOWN", "plan_id": plan["id"], "retry_permitted": False}
            receipt = {
                "schema": "task-writeback-receipt/v1",
                "plan_id": plan["id"],
                "plan_sha256": plan["sha256"],
                "object_sha256": fingerprint(plan["object_id"]),
                "source_sha256": fingerprint(plan["source_id"]),
                "identity_sha256": fingerprint(plan["binding"]["identity_id"]),
                "operation_id": inflight["operation_id"],
                "status": outcome["outcome"],
                "fields": sorted(plan["changes"]),
                "changes_sha256": fingerprint(plan["changes"]),
                "before_sha256": fingerprint(plan["before"]),
                "expected_remote_revision_sha256": fingerprint(plan["expected_remote_revision"]),
                "new_remote_revision_sha256": fingerprint(outcome["revision"]),
                "at": utc_now(),
                "canonical_updated": False,
            }
            path = checked_path(
                self.store, f"{ROOT}/{plan['source_id']}/receipts/{plan['id']}.json"
            )
            old = self.audit(plan["source_id"], plan["id"])
            if old is None:
                self.store._atomic_json(path, receipt)
            else:
                require(
                    all(old[key] == value for key, value in receipt.items() if key != "at"),
                    "integrity",
                )
                receipt = old
            self.save_ledger({**ledger, "inflight": None})
            checked_path(self.store, f"{ROOT}/{plan['source_id']}/plans/{plan['id']}.json").unlink(
                missing_ok=True
            )
            return receipt

    def confirm(self, object_id, plan_id, *, expected_plan_sha256, confirmed):
        require(confirmed is True, "consent_required")
        obj, snapshot = self.object(object_id)
        source_id = snapshot["source_id"]
        with self.guard():
            receipt = self.audit(source_id, plan_id)
            if receipt is not None:
                require(
                    receipt["plan_sha256"] == expected_plan_sha256
                    and receipt["object_sha256"] == fingerprint(object_id),
                    "stale",
                )
                recorded = self.ledger(source_id)
                if (
                    recorded["inflight"] is not None
                    and recorded["inflight"]["plan"]["sha256"] == expected_plan_sha256
                ):
                    self.save_ledger({**recorded, "inflight": None})
                return receipt
            ledger = self.ledger(source_id)
            if ledger["inflight"] is not None:
                require(ledger["inflight"]["plan"]["id"] == plan_id, "unknown_outcome")
                require(ledger["inflight"]["plan"]["sha256"] == expected_plan_sha256, "stale")
                return {"status": "UNKNOWN", "plan_id": plan_id, "retry_permitted": False}
            plan = self.load_plan(source_id, plan_id)
            current, current_snapshot = self.object(object_id)
            require(
                plan["object_id"] == object_id
                and plan["sha256"] == expected_plan_sha256
                and time.time() <= plan["expires_at"]
                and current_snapshot["current"]
                and record_digest(current) == plan["local_sha256"]
                and self.binding(source_id) == plan["binding"],
                "stale",
            )
            operation = fingerprint(
                [self.store.read_config()["instance"]["id"], source_id, plan_id, plan["sha256"]]
            )
            # This single durable record is the dispatch linearization point.
            # Revoke cannot undo an already dispatched operation. Every restart,
            # double submission and uncertain outcome takes read-only recovery.
            self.save_ledger(
                {
                    **ledger,
                    "inflight": {"plan": plan, "operation_id": operation, "status": "DISPATCHED"},
                }
            )
        adapter = self.adapter(source_id)
        try:
            if adapter.epoch(plan["binding"]["identity_id"]) != plan["binding"]["credential_epoch"]:
                result = {"operation_id": operation, "outcome": "NOT_APPLIED", "revision": None}
            else:
                result = self.outcome(
                    adapter.compare_and_set(
                        plan["remote_id"],
                        expected_revision=plan["expected_remote_revision"],
                        changes=plan["changes"],
                        operation_id=operation,
                    ),
                    operation,
                )
        except (ValueError, OSError, TimeoutError):
            result = {"operation_id": operation, "outcome": "UNKNOWN", "revision": None}
        return self.finish(plan, result)

    def reconcile(self, object_id):
        _obj, snapshot = self.object(object_id)
        source_id = snapshot["source_id"]
        inflight = self.ledger(source_id)["inflight"]
        require(inflight is not None, "no_pending_operation")
        self.host.authority(source_id, "task_read")
        adapter, plan = self.adapter(source_id), inflight["plan"]
        require(plan["object_id"] == object_id, "stale")
        try:
            # An operation receipt, not coincidentally matching current fields,
            # must prove a terminal outcome. Missing proof remains UNKNOWN.
            value = adapter.operation(plan["remote_id"], operation_id=inflight["operation_id"])
            result = self.outcome(value, inflight["operation_id"])
        except (ValueError, OSError, TimeoutError):
            result = {
                "operation_id": inflight["operation_id"],
                "outcome": "UNKNOWN",
                "revision": None,
            }
        return self.finish(plan, result)

    def view(self, object_id):
        obj, snapshot = self.object(object_id)
        ledger = self.ledger(snapshot["source_id"])
        return {
            "object": obj,
            "source": snapshot,
            "capability": self.capability(snapshot["source_id"]),
            "consent": ledger["consent"],
            "consent_effective": ledger["consent"]["enabled"]
            and ledger["consent"]["device_binding"] == self.device_binding(),
            "inflight": (
                {
                    "plan_id": ledger["inflight"]["plan"]["id"],
                    "status": "UNKNOWN",
                    "retry_permitted": False,
                }
                if ledger["inflight"]
                else None
            ),
            "local_sha256": record_digest(obj),
        }
