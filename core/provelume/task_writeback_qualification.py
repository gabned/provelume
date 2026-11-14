"""Network-free conditional adapter for qualification; never a public provider grant."""

import json
from copy import deepcopy
from pathlib import Path
from threading import RLock

from .knowledge_object_contract import record_digest
from .productivity_contract import ReadPage, fingerprint, require
from .productivity_intake import ProductivityIntake
from .service import ProvelumeInstance
from .task_writeback import QUALIFICATION_KEY, QUALIFICATION_PROFILE, TaskWriteBack


class SyntheticConditionalTask:
    profile = QUALIFICATION_PROFILE

    def __init__(self):
        self.value = {
            "revision": "revision-1",
            "completed": False,
            "due": {"kind": "date", "value": "2026-11-07", "time_zone": None},
        }
        self.version, self.grant_epoch, self.cas_calls = 1, 1, 0
        self.read_calls, self.operation_calls, self.operations = 0, 0, {}
        self.mode, self.on_dispatch, self.lock = "normal", None, RLock()

    def epoch(self, identity):
        return fingerprint([identity, self.grant_epoch])

    def read(self, remote_id):
        require(remote_id == "synthetic-task")
        self.read_calls += 1
        return deepcopy(self.value)

    def actor_update(self, **fields):
        with self.lock:
            self.version += 1
            self.value = {
                **self.value,
                **deepcopy(fields),
                "revision": "revision-" + str(self.version),
            }

    def compare_and_set(self, remote_id, *, expected_revision, changes, operation_id):
        require(remote_id == "synthetic-task")
        with self.lock:
            self.cas_calls += 1
            if self.on_dispatch:
                self.on_dispatch()
            if self.mode == "crash":
                raise KeyboardInterrupt("synthetic dispatch interruption")
            if self.mode in {"unknown", "not_applied"}:
                self.operations[operation_id] = {
                    "operation_id": operation_id,
                    "outcome": "UNKNOWN" if self.mode == "unknown" else "NOT_APPLIED",
                    "revision": None,
                }
                raise TimeoutError()
            if expected_revision != self.value["revision"]:
                result = {
                    "operation_id": operation_id,
                    "outcome": "CONFLICT",
                    "revision": self.value["revision"],
                }
            else:
                self.actor_update(**changes)
                result = {
                    "operation_id": operation_id,
                    "outcome": "APPLIED",
                    "revision": self.value["revision"],
                }
            self.operations[operation_id] = result
            if self.mode == "after_send_timeout":
                raise TimeoutError()
            return deepcopy(result)

    def operation(self, remote_id, *, operation_id):
        require(remote_id == "synthetic-task")
        self.operation_calls += 1
        return deepcopy(
            self.operations.get(
                operation_id, {"operation_id": operation_id, "outcome": "UNKNOWN", "revision": None}
            )
        )


class SyntheticWriteBackFixture:
    def __init__(self, instance):
        self.instance, self.store = instance, instance.store
        self.remote = SyntheticConditionalTask()
        self.title = "Synthetic guarded task"
        definition = instance.connectors.register_definition(
            {
                "adapter_key": QUALIFICATION_KEY,
                "adapter_version": "1.0.0",
                "display_name": "Synthetic atomic task fixture",
                "provider": "synthetic",
                "conformance_profile": "provelume.connector.v1",
                "adapter_protocol_version": 1,
                "capabilities": ["manual_read", "source_selection", "task_read"],
                "authorization_modes": ["none"],
                "source_kinds": ["tasks"],
                "data_categories": ["task.content"],
                "multi_instance": True,
                "network_access": "none",
            }
        )
        self.identity = instance.connectors.create_instance(
            definition["id"], name="Synthetic identity", provider_identity="synthetic"
        )["id"]
        self.source = instance.connectors.add_source(
            self.identity,
            name="Synthetic atomic tasks",
            source_kind="tasks",
            external_id="synthetic-scope",
        )["id"]
        self.host = instance.productivity_connectors()
        self.host.consent(
            self.source,
            capabilities=["task_read"],
            mode="manual",
            expected_revision=0,
            confirmed=True,
        )
        self.engine = TaskWriteBack(self.store, _qualification_adapter=self.remote)
        self.acquire()

    def acquire(self):
        value = self.remote.value
        mapped = {
            "remote_id": "synthetic-task",
            "revision": value["revision"],
            "revision_kind": "version",
            "kind": "task",
            "title": self.title,
            "description": "Synthetic read snapshot",
            "state": "completed" if value["completed"] else "open",
            "due": value["due"],
            "starts": None,
            "ends": None,
            "provenance": {
                "container_ids": [],
                "parent_id": None,
                "assignees": [],
                "links": [],
                "comments": [],
                "uid": None,
                "recurrence_id": None,
                "recurrence": [],
            },
        }

        class Adapter:
            def read_page(self, **_request):
                raw = json.dumps(mapped).encode()
                return ReadPage(
                    (mapped,), checkpoint=fingerprint(mapped), originals=(raw,), response=raw
                )

        preview = self.host.preview(
            self.source,
            "task_read",
            Adapter(),
            expected_authority=self.host.authority(self.source, "task_read")["sha256"],
        )
        ProductivityIntake(self.store).accept(preview)
        self.object_id = next(
            row["id"]
            for row in self.store.list_canonical("objects")
            if row["origin"].get("source_id") == self.source
        )

    def consent(self):
        return self.engine.consent(
            self.source,
            enabled=True,
            fields=["completed", "due"],
            expected_revision=0,
            confirmed=True,
        )

    def prepare(self, requested):
        return self.engine.prepare(
            self.object_id,
            requested,
            expected_local_sha256=record_digest(
                self.store.read_canonical("objects", self.object_id)
            ),
            expected_consent_revision=self.engine.ledger(self.source)["consent"]["revision"],
        )


def qualify_task_writeback(root):
    from .build_info import current_build_info

    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    instance = ProvelumeInstance.initialise(root / "Synthetic Space")
    fixture = SyntheticWriteBackFixture(instance)
    fixture.consent()
    plan = fixture.prepare(
        {"completed": True, "due": {"kind": "date", "value": "2026-11-08", "time_zone": None}}
    )
    before = instance.store.knowledge_fingerprint()
    receipt = fixture.engine.confirm(
        fixture.object_id, plan["id"], expected_plan_sha256=plan["sha256"], confirmed=True
    )
    require(
        receipt["status"] == "APPLIED"
        and fixture.remote.cas_calls == 1
        and instance.store.knowledge_fingerprint() == before,
        "qualification",
    )
    replay = fixture.engine.confirm(
        fixture.object_id, plan["id"], expected_plan_sha256=plan["sha256"], confirmed=True
    )
    require(replay == receipt and fixture.remote.cas_calls == 1, "qualification")
    fixture.acquire()  # Independent ordinary Source read, never a fabricated manual edit.
    obj = instance.store.read_canonical("objects", fixture.object_id)
    require(
        obj["state"] == "completed" and obj["body"]["due_date"] == "2026-11-08", "qualification"
    )
    plan = fixture.prepare({"due": {"kind": "date", "value": "2026-11-10", "time_zone": None}})
    fixture.remote.mode = "after_send_timeout"
    unknown = fixture.engine.confirm(
        fixture.object_id, plan["id"], expected_plan_sha256=plan["sha256"], confirmed=True
    )
    require(unknown["status"] == "UNKNOWN", "qualification")
    recovered = fixture.engine.reconcile(fixture.object_id)
    require(recovered["status"] == "APPLIED" and fixture.remote.cas_calls == 2, "qualification")
    fixture.acquire()
    archive = root / "Synthetic Portable.zip"
    instance.export_portable(archive, derived_state="rebuild")
    restored = ProvelumeInstance.initialise(root / "Restored Space")
    restored.import_portable(archive)
    require(
        restored.object_services().get(fixture.object_id)["provider_snapshot"]["current"],
        "qualification",
    )
    return {
        "schema": "provelume-task-writeback-qualification/v1",
        "result": "PASS",
        "build": current_build_info(),
        "execution_adapter": QUALIFICATION_PROFILE,
        "network_used": False,
        "closed_diff_confirmation": "PASS",
        "atomic_conflict": "SYNTHETIC_ONLY",
        "replay_single_dispatch": "PASS",
        "unknown_readonly_reconciliation": "PASS",
        "canonical_observation_after_separate_read": "PASS",
        "offline_portable": "PASS",
        "public_provider_writeback": "NOT_QUALIFIED",
        "release_gate": "DEFERRED_BY_MAINTAINER",
        "release_scope": "ASANA_TUDUDI_READ_ONLY_0_15_0",
        "scope_decision": "https://github.com/gabned/provelume/issues/383#issuecomment-6711131611",
        "windows_11_pro_25h2_manual": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
