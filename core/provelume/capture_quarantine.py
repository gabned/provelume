"""Recorded Capture quarantine/compensation; never moves or purges an Original."""

import json
import re
from datetime import timedelta
from uuid import UUID, uuid4

from .atomic_commit import (
    AtomicCommitLimits,
    AtomicCommitProfile,
    AtomicInstanceCommit,
    AtomicRecoveryHandler,
    _load_transaction_manifest,
    _validate_transaction_manifest,
    recover_atomic_transactions,
)
from .capture_adapter import CaptureAdapter
from .capture_authority import _owner_guard, _stamp
from .capture_journal import CaptureJournalError, _read, _safe, _unique
from .instance_lifecycle import InstanceLifecycleManager
from .storage import utc_now

PATH = "state/capture-quarantine.json"
PROFILE = AtomicCommitProfile(
    "submission-quarantine",
    "capture.quarantine",
    r"inst_[0-9a-f]{32}\Z",
    AtomicCommitLimits(1, 4 * 1024 * 1024, 4 * 1024 * 1024, 4 * 1024 * 1024, 8 * 1024 * 1024),
)


class CaptureQuarantine:
    def __init__(self, store):
        self.store = store
        self.lifecycle = InstanceLifecycleManager(store)
        self.instance_id = store.read_config()["instance"]["id"]

    def validate(self, value):
        try:
            if (
                set(value) != {"schema_version", "instance_id", "items", "events"}
                or type(value["schema_version"]) is not int
                or value["schema_version"] != 1
                or value["instance_id"] != self.instance_id
                or not isinstance(value["items"], dict)
                or len(value["items"]) > 128
                or not isinstance(value["events"], list)
                or len(value["events"]) > 4096
            ):
                raise ValueError()
            ids = set()
            event_ids = set()
            current = {}
            for event in value["events"]:
                if (
                    set(event) != {"id", "request_id", "scope", "action", "at", "retention_until"}
                    or not re.fullmatch(r"cq_[0-9a-f]{32}", event["id"])
                    or event["request_id"] in ids
                    or event["id"] in event_ids
                    or str(UUID(event["request_id"])) != event["request_id"]
                    or UUID(event["request_id"]).version != 4
                    or not re.fullmatch(r"capture_[0-9a-f]{64}", event["scope"])
                    or event["action"] not in {"quarantine", "undo"}
                ):
                    raise ValueError()
                ids.add(event["request_id"])
                event_ids.add(event["id"])
                at = _stamp(event["at"])
                if event["action"] == "quarantine":
                    if not 1 <= (_stamp(event["retention_until"]) - at).days <= 365:
                        raise ValueError()
                elif event["retention_until"] is not None:
                    raise ValueError()
                current[event["scope"]] = event
            if value["items"] != current:
                raise ValueError()
        except (TypeError, KeyError, ValueError, AttributeError) as exc:
            raise CaptureJournalError("Invalid Capture quarantine schema/history") from exc
        return value

    def read(self):
        path = self.store.paths.root / PATH
        _safe(path)
        if not path.exists():
            return dict(schema_version=1, instance_id=self.instance_id, items={}, events=[])
        return self.validate(json.loads(_read(path, 4 * 1024 * 1024), object_pairs_hook=_unique))

    def transition(self, scope, action, days, request_id, *, authorize_owner):
        if (
            not isinstance(scope, str)
            or not re.fullmatch(r"capture_[0-9a-f]{64}", scope)
            or action not in {"quarantine", "undo"}
            or type(days) is not int
            or not 1 <= days <= 365
        ):
            raise CaptureJournalError("Invalid Capture quarantine request")
        try:
            selected_id = UUID(request_id)
            if selected_id.version != 4 or str(selected_id) != request_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise CaptureJournalError("Quarantine requires an explicit UUID4 request") from exc
        _owner_guard(authorize_owner)
        with self.lifecycle._hold(purpose="capture-quarantine"):
            _owner_guard(authorize_owner)
            adapter = CaptureAdapter(self.store, authorize=lambda *a: None)
            found = next(
                (
                    r["receipt"]
                    for r in adapter.journal._inventory().values()
                    if r["receipt"]["id"] == scope
                ),
                None,
            )
            if found is None:
                raise CaptureJournalError("Capture submission unavailable")
            detail = adapter.detail(
                found["device_id"],
                found["metadata"]["client_submission_id"],
                channel=found["metadata"]["channel"],
            )
            if detail["acquisition"] is None:
                raise CaptureJournalError("Quarantine requires a committed acquisition")
            value = self.read()
            previous = next((r for r in value["events"] if r["request_id"] == request_id), None)
            if previous:
                if (
                    previous["scope"] != scope
                    or previous["action"] != action
                    or (
                        action == "quarantine"
                        and (_stamp(previous["retention_until"]) - _stamp(previous["at"])).days
                        != days
                    )
                ):
                    raise CaptureJournalError("Conflicting Capture quarantine request")
                return previous
            if len(value["events"]) >= 4096:
                raise CaptureJournalError("Capture quarantine history full")
            if action == "undo" and value["items"].get(scope, {}).get("action") != "quarantine":
                raise CaptureJournalError("No Capture quarantine to compensate")
            now = utc_now()
            event = dict(
                id="cq_" + uuid4().hex,
                request_id=request_id,
                scope=scope,
                action=action,
                at=now,
                retention_until=(_stamp(now) + timedelta(days=days)).isoformat()
                if action == "quarantine"
                else None,
            )
            value["items"][scope] = event
            value["events"].append(event)
            self.validate(value)
            transaction = AtomicInstanceCommit(
                self.store,
                self.lifecycle.control_root / "transactions",
                profile=PROFILE,
                owner_id=self.instance_id,
            )
            transaction.add(
                PATH, json.dumps(value, sort_keys=True, allow_nan=False).encode(), immutable=False
            )
            transaction.commit()
        return event


def recover_capture_quarantine_locked(store):
    manager = CaptureQuarantine(store)
    root = manager.lifecycle.control_root / "transactions"
    _safe(root)
    if not root.exists():
        return None
    for index, stage in enumerate(root.glob("submission-quarantine-*")):
        if index >= 128:
            raise CaptureJournalError("Capture quarantine recovery bound reached")
        manifest = _load_transaction_manifest(stage, max_entries=1, error_type=CaptureJournalError)
        if manifest is None:
            continue
        _validate_transaction_manifest(
            store, stage, manifest, profile=PROFILE, error_type=CaptureJournalError
        )
        if manifest["operation_id"] != manager.instance_id or len(manifest["entries"]) != 1:
            raise CaptureJournalError("Capture quarantine recovery identity rejected")
        entry = manifest["entries"][0]
        if entry["relative"] != PATH or entry["immutable"] is not False:
            raise CaptureJournalError("Capture quarantine recovery outside domain allowlist")
        for path in [stage / entry["candidate_ref"], store.paths.root / PATH] + (
            [stage / entry["preimage_ref"]] if entry["had_preimage"] else []
        ):
            if path.exists():
                manager.validate(
                    json.loads(_read(path, 4 * 1024 * 1024), object_pairs_hook=_unique)
                )
    return recover_atomic_transactions(
        store, manager.lifecycle.control_root, handlers=(AtomicRecoveryHandler(profile=PROFILE),)
    )
