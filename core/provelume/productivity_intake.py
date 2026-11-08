"""Idempotent read intake: exact response Originals, canonical Versions, bounded projections.

Remote task/event projections are attributed read models, distinct from manually
authored Entitas objects. A checkpoint is published only after every item commits.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from uuid import NAMESPACE_URL, uuid4, uuid5

from .atomic_commit import PRODUCTIVITY_INTAKE_TRANSACTION_PROFILE, AtomicInstanceCommit
from .domain import Acquisition, Document, DocumentVersion, Original
from .instance_lifecycle import InstanceLifecycleManager
from .productivity_connectors import ROOT, ProductivityConnectors
from .productivity_contract import fingerprint, require, validate_item
from .review_decisions import checked_path, read_json
from .storage import utc_now


def _identifier(prefix, value):
    return prefix + "_" + uuid5(NAMESPACE_URL, value).hex


def _bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


class ProductivityIntake:
    def __init__(self, store):
        self.store = store
        self.manager = ProductivityConnectors(store)

    def checkpoint(self, source_id):
        self.manager._records(source_id)
        return read_json(self.store, f"{ROOT}/{source_id}/sync.json")

    def _commit(self, source_id, item, raw, media_type, authority, *, response_only=False):
        require(type(raw) is bytes and 0 < len(raw) <= 2 * 1024 * 1024, "original_required")
        if not response_only:
            validate_item(item)
        stamp, raw_hash = utc_now(), hashlib.sha256(raw).hexdigest()
        namespace = "productivity-response:" if response_only else "productivity:"
        document_id = _identifier("doc", namespace + source_id + ":" + item["remote_id"])
        item_hash = fingerprint(item)
        previous = self.store.read_canonical("documents", document_id)
        if previous is not None:
            current_version = previous["current_version_id"]
            observation = read_json(
                self.store, f"{ROOT}/{source_id}/observations/{document_id}/{current_version}.json"
            )
            require(
                observation is not None
                and observation["item_sha256"] == fingerprint(observation["item"]),
                "integrity",
            )
            if observation["item_sha256"] == item_hash:
                require(
                    hashlib.sha256(
                        self.store.original_bytes("sha256_" + observation["original_sha256"])
                    ).hexdigest()
                    == observation["original_sha256"],
                    "integrity",
                )
                changed = False
                if not response_only:
                    from .productivity_objects import project_connector_object

                    changed = project_connector_object(self.store, source_id, document_id,
                                                       current_version, item)
                return {
                    "document_id": document_id,
                    "version_id": current_version,
                    "status": "imported" if changed else "unchanged",
                }
        version_id = _identifier(
            "ver",
            fingerprint(
                [
                    document_id,
                    item_hash,
                    raw_hash,
                    previous["current_version_id"] if previous else None,
                ]
            ),
        )
        observation_path = f"{ROOT}/{source_id}/observations/{document_id}/{version_id}.json"
        versions = self.store.versions_for_document(document_id)
        original = Original(
            id="sha256_" + raw_hash,
            sha256=raw_hash,
            size_bytes=len(raw),
            storage_ref=f"originals/sha256/{raw_hash[:2]}/{raw_hash}",
            created_at=stamp,
        )
        original_record = self.store.read_canonical("originals", original.id) or asdict(original)
        require(
            all(
                original_record[key] == asdict(original)[key]
                for key in ("id", "sha256", "size_bytes", "storage_ref")
            ),
            "integrity",
        )
        document = Document(
            id=document_id,
            source_id=source_id,
            locator=namespace + "sha256:" + fingerprint(item["remote_id"]),
            title=item["title"] or "Calendar event",
            media_type=media_type,
            created_at=previous["created_at"] if previous else stamp,
            current_version_id=version_id,
        )
        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            sequence=max((row["sequence"] for row in versions), default=0) + 1,
            content_hash=raw_hash,
            original_id=original.id,
            media_type=media_type,
            size_bytes=len(raw),
            acquired_at=stamp,
        )
        acquisition = Acquisition(
            id=_identifier("acq", version_id),
            source_id=source_id,
            locator=document.locator,
            observed_at=stamp,
            content_hash=raw_hash,
            outcome="updated" if previous else "created",
            document_id=document_id,
            version_id=version_id,
            error=None,
            acquisition_kind="productivity_readonly",
            media_type=media_type,
            original_id=original.id,
            response_size_bytes=len(raw),
            exact_duplicate=False,
        )
        observation = {
            "schema": "productivity-observation/v1",
            "source_id": source_id,
            "document_id": document_id,
            "version_id": version_id,
            "original_sha256": raw_hash,
            "item_sha256": item_hash,
            "item": item,
            "authority": authority,
        }
        transaction = AtomicInstanceCommit(
            self.store,
            InstanceLifecycleManager(self.store).control_root / "transactions",
            profile=PRODUCTIVITY_INTAKE_TRANSACTION_PROFILE,
            owner_id="productivity_" + uuid4().hex,
        )
        transaction.add(original.storage_ref, raw, immutable=True)
        for kind, record, immutable in (
            ("originals", original_record, True),
            ("documents", asdict(document), False),
            ("versions", asdict(version), True),
            ("acquisitions", asdict(acquisition), True),
        ):
            transaction.add(
                f"knowledge/{kind}/{record['id']}.json", _bytes(record), immutable=immutable
            )
        transaction.add(observation_path, _bytes(observation), immutable=True)
        transaction.commit()
        if not response_only:
            from .productivity_objects import project_connector_object

            project_connector_object(self.store, source_id, document_id, version_id, item)
        return {"document_id": document_id, "version_id": version_id, "status": "imported"}

    def accept(self, preview, *, cancelled=lambda: False, recheck=lambda: None, binding=None):
        with InstanceLifecycleManager(self.store)._hold(purpose="productivity-intake"):
            return self.accept_locked(
                preview, cancelled=cancelled, recheck=recheck, binding=binding
            )

    def accept_locked(
        self, preview, *, cancelled=lambda: False, recheck=lambda: None, binding=None
    ):
        """Complete Source snapshot; caller already owns the lifecycle barrier."""
        require(preview["schema"] == "productivity-read-preview/v1", "incomplete")
        result = self._import_locked(preview, cancelled=cancelled, recheck=recheck)
        authority = preview["authority"]
        source_id = authority["source_id"]
        with self.manager.connectors.policy_commit_guard(purpose="productivity-checkpoint"):
            require(not cancelled(), "cancelled")
            require(
                self.manager.authority(
                    source_id, authority["capability"], scheduled=authority["scheduled"]
                )
                == authority,
                "stale",
            )
            recheck()
            previous = self.checkpoint(source_id)
            active = (
                dict(previous.get("active_versions", {}))
                if previous and preview["snapshot_mode"] == "delta"
                else {}
            )
            active.update({row["document_id"]: row["version_id"] for row in result["results"]})
            receipt = {
                "schema": "productivity-sync/v1",
                "source_id": source_id,
                "authority": authority,
                "binding": binding,
                "snapshot_mode": preview["snapshot_mode"],
                "active_versions": active,
                "source_snapshots": result["source_snapshots"],
                "checkpoint": preview["checkpoint"],
                "preview_sha256": preview["sha256"],
                "results": result["results"],
                "completed_at": utc_now(),
            }
            self.store._atomic_json(
                checked_path(self.store, f"{ROOT}/{source_id}/sync.json"), receipt
            )
        return {**result, "checkpoint_advanced": True, "scope": "source"}

    def import_page_locked(self, preview, *, cancelled=lambda: False, recheck=lambda: None):
        """One page only; producer must publish its cursor after these durable imports."""
        require(preview["schema"] == "productivity-page-preview/v1", "incomplete")
        return {
            **self._import_locked(preview, cancelled=cancelled, recheck=recheck),
            "scope": "page",
        }

    def _import_locked(self, preview, *, cancelled, recheck):
        authority = preview["authority"]
        from .productivity_connectors import preview_digest

        require(preview["sha256"] == preview_digest(preview), "integrity")
        require(len(preview["items"]) == len(preview["_originals"]), "original_required")
        source_id = authority["source_id"]
        results, snapshots, deadline = [], [], time.monotonic() + 60
        for raw, media_type in preview["_responses"]:
            require(not cancelled(), "cancelled")
            require(time.monotonic() < deadline, "deadline")
            with self.manager.connectors.policy_commit_guard(purpose="productivity-response"):
                require(
                    self.manager.authority(
                        source_id, authority["capability"], scheduled=authority["scheduled"]
                    )
                    == authority,
                    "stale",
                )
                recheck()
                response_item = {
                    "remote_id": hashlib.sha256(raw).hexdigest(),
                    "title": "Source snapshot",
                }
                snapshots.append(
                    self._commit(
                        source_id, response_item, raw, media_type, authority, response_only=True
                    )
                )
        for item, (raw, media_type) in zip(preview["items"], preview["_originals"], strict=True):
            require(not cancelled(), "cancelled")
            require(time.monotonic() < deadline, "deadline")
            with self.manager.connectors.policy_commit_guard(purpose="productivity-intake"):
                require(
                    self.manager.authority(
                        source_id, authority["capability"], scheduled=authority["scheduled"]
                    )
                    == authority,
                    "stale",
                )
                recheck()
                results.append(self._commit(source_id, item, raw, media_type, authority))
        return {
            "status": "succeeded",
            "count": len(results),
            "results": results,
            "checkpoint_advanced": False,
            "provider_write": False,
            "source_snapshots": snapshots,
        }

    def records(self, source_id):
        self.manager._records(source_id)
        result = []
        receipt = self.checkpoint(source_id)
        active = receipt.get("active_versions", {}) if receipt else {}
        generation = None
        if receipt and receipt.get("schema") == "productivity-generation/v1":
            from .productivity_generations import ProductivityGenerations

            generation = ProductivityGenerations(self.store, source_id)
        for document in self.store.list_canonical("documents"):
            if document["source_id"] != source_id or not document["locator"].startswith(
                "productivity:sha256:"
            ):
                continue
            version_id = document["current_version_id"]
            observation = read_json(
                self.store, f"{ROOT}/{source_id}/observations/{document['id']}/{version_id}.json"
            )
            require(
                observation is not None
                and observation["source_id"] == source_id
                and observation["version_id"] == version_id
                and observation["item_sha256"] == fingerprint(observation["item"]),
                "integrity",
            )
            validate_item(observation["item"])
            version = self.store.read_canonical("versions", version_id)
            require(
                version is not None and version["content_hash"] == observation["original_sha256"],
                "integrity",
            )
            result.append(
                {
                    **observation,
                    "availability": (
                        "in_completed_snapshot"
                        if (
                            generation.contains(document["id"], version_id)
                            if generation
                            else active.get(document["id"]) == version_id
                        )
                        else "not_in_completed_snapshot"
                    ),
                }
            )
        return result
