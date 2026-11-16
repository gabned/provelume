"""One-way native folder publication from complete immutable S16 generations."""

from __future__ import annotations

import os
import shutil
from uuid import uuid4

from .maintenance_local_files import open_local_file
from .mirror_contract import (
    MAX_GENERATIONS,
    fingerprint,
    raw,
    require,
)
from .mirror_folder_files import MAX_TARGET_BYTES, MAX_TARGET_FILES, configuration, folder_root
from .mirrors import Mirrors


def intended_pointer(plan, folder_plan):
    return {
        "schema": "provelume-folder-active/v1",
        "generation": plan["generation"],
        "manifest_sha256": plan["generation"],
        "inventory_sha256": folder_plan["inventory_sha256"],
        "operation_id": plan["id"],
        "previous_pointer_sha256": fingerprint(folder_plan["active_pointer"]),
    }


class FolderMirrors:
    def __init__(self, store, *, mirrors=None):
        self.store = store
        self.mirrors = mirrors or Mirrors(store)

    def status(self):
        return {
            "profile": "folder-local/v1",
            "network_used": False,
            "process_used": False,
            "credentials_read": False,
            "target_probed": False,
            "publication": "LOCAL_PRIVATE_MANUAL_OR_SCHEDULED",
        }

    def context(self, destination_id, *, scheduled=False, inspection_operation=None):
        row, authority = self.mirrors.authority(
            destination_id, scheduled=scheduled, _inspection_operation=inspection_operation
        )
        identity = authority["identity"]
        require(identity["profile"] == "folder", "folder_profile_not_qualified")
        grant = self.mirrors._grant(identity)
        require(grant["credential"] == {"reference": ""}, "folder_credentials")
        target = configuration(grant["destinations"][destination_id]["target"])
        return row, authority, target

    def tree(self, row, target, **options):
        return folder_root(
            target,
            store=self.store,
            device=self.mirrors.device(),
            destination_sha256=row["destination_sha256"],
            **options,
        )

    @staticmethod
    def observation(row, tree, pointer, payload):
        return {
            "destination_sha256": row["destination_sha256"],
            "visibility": "private",
            "writable": True,
            "inventory": payload,
            "revision": fingerprint([tree.binding, tree.marker, tree.profile, pointer]),
        }

    def initialize_local(self, destination_id, *, expected_destination_sha256, confirmed):
        require(confirmed is True, "consent_required")
        with self.mirrors.guard():
            row, _authority, target = self.context(destination_id)
            require(row["destination_sha256"] == expected_destination_sha256, "stale")
            with self.tree(row, target, fresh=True) as tree:
                return {
                    "status": "initialized",
                    "root_sha256": fingerprint(tree.binding),
                    "destination_sha256": row["destination_sha256"],
                    "filesystem_profile": tree.profile,
                    "network_used": False,
                    "process_used": False,
                    "canonical_mutation": False,
                }

    def prepare(
        self, destination_id, *, expected_revision, confirmed, scheduled=False, _deadline=None
    ):
        require(confirmed is True, "consent_required")
        with self.mirrors.guard():
            row, _authority, target = self.context(destination_id, scheduled=scheduled)
            require(row["revision"] == expected_revision, "stale")
            with self.tree(row, target, deadline=_deadline) as tree:
                pointer, payload = tree.active()
                plan = self.mirrors._preview_locked(
                    destination_id,
                    self.observation(row, tree, pointer, payload),
                    expected_revision=expected_revision,
                    scheduled=scheduled,
                    _deadline=tree.deadline,
                )
                folder_plan = {
                    "schema": "provelume-folder-plan/v1",
                    "plan_id": plan["id"],
                    "original_plan_sha256": plan["plan_sha256"],
                    "root_sha256": fingerprint(tree.binding),
                    "marker": tree.marker,
                    "filesystem_profile": tree.profile,
                    "active_pointer": pointer,
                    "inventory_sha256": fingerprint(plan["manifest"]["inventory"]),
                    "destination_storage": tree.audit(),
                }
                self.mirrors._save("folder/plans/" + plan["id"] + ".json", folder_plan)
                return {
                    **plan,
                    "folder_plan": folder_plan,
                    "folder_plan_sha256": fingerprint(folder_plan),
                    "publication": "PREVIEW_ONLY",
                }

    def folder_plan(self, plan_id):
        plan = self.mirrors.plan(plan_id)
        folder_plan = self.mirrors._load("folder/plans/" + plan_id + ".json")
        require(
            type(folder_plan) is dict
            and folder_plan.get("schema") == "provelume-folder-plan/v1"
            and folder_plan.get("plan_id") == plan_id
            and folder_plan.get("original_plan_sha256")
            == fingerprint({**plan, "state": "prepared"}),
            "folder_plan",
        )
        return plan, folder_plan

    @staticmethod
    def binding_matches(tree, folder_plan):
        return (
            fingerprint(tree.binding) == folder_plan["root_sha256"]
            and tree.marker == folder_plan["marker"]
            and tree.profile == folder_plan["filesystem_profile"]
        )

    @staticmethod
    def proof(tree, pointer, *, noop, recovery=False):
        return {
            "profile": "folder-local/v1",
            "root_sha256": fingerprint(tree.binding),
            "namespace": tree.marker["namespace"],
            "active_pointer_sha256": fingerprint(pointer),
            "activation_written": not noop,
            "filesystem_profile": tree.profile,
            "evidence_mode": "reconciled_current_state" if recovery else "direct_verified",
            "publication_time": None,
        }

    def transfer(self, tree, plan, folder_plan):
        """Exactly one staging/activation attempt. All failures retain their original bytes."""
        manifest = self.mirrors.snapshots.verify(plan["generation"])
        storage = tree.audit()
        stage = "staging/" + plan["id"] + "-" + uuid4().hex
        final = "generations/" + plan["generation"]
        exists = tree.exists(final)
        if exists:
            tree.generation(final, plan["generation"])
        else:
            require(
                len(storage["generations"]) + len(storage["staging"]) < MAX_GENERATIONS,
                "folder_storage_limit",
            )
            require(
                storage["files"] + len(manifest["inventory"]) + 2 <= MAX_TARGET_FILES
                and storage["bytes"] + manifest["total_bytes"] + len(raw(manifest)) + 4096
                <= MAX_TARGET_BYTES,
                "folder_storage_limit",
            )
            require(
                shutil.disk_usage(tree.root).free
                >= manifest["total_bytes"] + len(raw(manifest)) + 4096,
                "folder_disk_full",
            )
            tree.mkdir(stage)
            for item in manifest["inventory"]:
                source = self.mirrors.snapshots.root() / plan["generation"] / item["path"]
                # Guarded completed source handles; never follow an Original/Source alias.
                with (
                    open_local_file(source) as incoming,
                    tree.file(stage + "/" + item["path"], create=True) as outgoing,
                ):
                    count = 0
                    while chunk := incoming.read(1024 * 1024):
                        tree.check()
                        count += len(chunk)
                        require(count <= item["size_bytes"], "integrity")
                        outgoing.write(chunk)
                    require(count == item["size_bytes"], "integrity")
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
            tree.write(stage + "/manifest.json", raw(manifest))
            tree.generation(stage, plan["generation"])
            tree.sync_directories(stage)
            tree.rename(stage, final)
        pointer = intended_pointer(plan, folder_plan)
        temporary = "staging/activate-" + plan["id"] + ".json"
        tree.write(temporary, raw(pointer))
        require(tree.active()[0] == folder_plan["active_pointer"], "destination_changed")
        tree.rename(temporary, "active.json", replace=True)
        return pointer

    def publish(
        self,
        plan_id,
        *,
        expected_plan_sha256,
        expected_folder_plan_sha256,
        confirmed,
        _deadline=None,
    ):
        require(confirmed is True and self.mirrors.access()["enabled"], "consent_required")
        with self.mirrors.guard():
            plan, folder_plan = self.folder_plan(plan_id)
            require(
                folder_plan["original_plan_sha256"] == expected_plan_sha256
                and fingerprint(folder_plan) == expected_folder_plan_sha256,
                "stale",
            )
            historical = self.mirrors._recover_terminal_locked(plan_id)
            if historical is not None:
                return {
                    "receipt": historical,
                    "historical": True,
                    "process_used": False,
                    "live_destination_checked": False,
                }
            row, authority, target = self.context(plan["destination_id"])
            require(plan["state"] == "prepared" and authority == plan["authority"], "stale")
            with self.tree(row, target, deadline=_deadline) as tree:
                require(self.binding_matches(tree, folder_plan), "folder_target_changed")
                pointer, payload = tree.active()
                require(pointer == folder_plan["active_pointer"], "destination_changed")
                observation = self.observation(row, tree, pointer, payload)
                # The external claim is durable before the first destination copy.
                self.mirrors._claim_locked(
                    plan_id,
                    transport_sha256=fingerprint(folder_plan),
                    expected_plan_sha256=expected_plan_sha256,
                    observation=observation,
                    confirmed=True,
                )
                try:
                    noop = pointer is not None and pointer["generation"] == plan["generation"]
                    candidate = pointer if noop else self.transfer(tree, plan, folder_plan)
                    actual, after = tree.active()
                    require(actual == candidate, "outcome_unknown")
                    tree.audit()
                    require(
                        self.mirrors.authority(
                            plan["destination_id"], _inspection_operation=plan_id
                        )[1]
                        == {**authority, "operation_serial": authority["operation_serial"] + 1},
                        "stale",
                    )
                    receipt = self.mirrors._complete_locked(
                        plan_id,
                        operation_id=plan_id,
                        observation=self.observation(row, tree, actual, after),
                        transport_proof=self.proof(tree, actual, noop=noop),
                    )
                    return {
                        "receipt": receipt,
                        "historical": False,
                        "process_used": False,
                        "network_used": False,
                        "live_destination_checked": True,
                    }
                except (OSError, ValueError):
                    self.mirrors._unknown_locked(plan_id)
                    raise

    def reconcile(self, plan_id, *, confirmed):
        require(confirmed is True and self.mirrors.access()["enabled"], "consent_required")
        with self.mirrors.guard():
            plan, folder_plan = self.folder_plan(plan_id)
            historical = self.mirrors._recover_terminal_locked(plan_id)
            if historical is not None:
                return {
                    "receipt": historical,
                    "historical": True,
                    "process_used": False,
                    "live_destination_checked": False,
                    "resend_allowed": False,
                }
            row, authority, target = self.context(
                plan["destination_id"], inspection_operation=plan_id
            )
            pending = self.mirrors.operation_ledger(row["id"], epoch=authority["grant_epoch"])[
                "inflight"
            ]
            require(pending.get("transport_sha256") == fingerprint(folder_plan), "stale")
            require(
                {**authority, "operation_serial": plan["authority"]["operation_serial"]}
                == plan["authority"]
                and authority["operation_serial"] == plan["authority"]["operation_serial"] + 1,
                "stale",
            )
            with self.tree(row, target) as tree:
                require(self.binding_matches(tree, folder_plan), "folder_target_changed")
                pointer, payload = tree.active()
                noop = (
                    folder_plan["active_pointer"] is not None
                    and folder_plan["active_pointer"]["generation"] == plan["generation"]
                )
                candidate = (
                    folder_plan["active_pointer"] if noop else intended_pointer(plan, folder_plan)
                )
                if pointer != candidate:
                    return {
                        "outcome": "UNKNOWN",
                        "resend_allowed": False,
                        "process_used": False,
                        "network_used": False,
                        "live_destination_checked": True,
                    }
                receipt = self.mirrors._complete_locked(
                    plan_id,
                    operation_id=plan_id,
                    observation=self.observation(row, tree, pointer, payload),
                    transport_proof=self.proof(tree, pointer, noop=noop, recovery=True),
                )
                return {
                    "receipt": receipt,
                    "historical": False,
                    "process_used": False,
                    "network_used": False,
                    "live_destination_checked": True,
                    "resend_allowed": False,
                }
