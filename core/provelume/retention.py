from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from .domain import DocumentDisposition
from .index import rebuild_search_index, refresh_search_index
from .instance_backup import default_backup_directory
from .instance_lifecycle import InstanceLifecycleManager
from .instance_validation import inspect_instance
from .library_projection import LibraryProjectionManager
from .library_projection_model import MAX_LIBRARY_DOCUMENTS
from .operations import OperationLedger
from .paths import normalise_locator
from .retention_model import (
    DISPOSITION_SCHEMA_VERSION,
    PurgeAuthorizationError,
    PurgeTransactionError,
    RetentionConflictError,
    RetentionIntegrityError,
    RetentionNotFoundError,
    default_disposition,
    disposition_id,
    disposition_records,
    disposition_view,
    effective_dispositions,
)
from .storage import InstanceStore, utc_now

RETENTION_RECEIPT_SCHEMA_VERSION = 1
PURGE_PREVIEW_SCHEMA_VERSION = 1
PURGE_RECEIPT_SCHEMA_VERSION = 1
PURGE_PREVIEW_TTL = timedelta(minutes=15)
MAX_PURGE_FILES = 100_000
MAX_PURGE_STATE_SCAN_BYTES = 16 * 1024 * 1024
MAX_PURGE_PREVIEWS = 200
MAX_MANAGED_BACKUPS = 10_000
_DOCUMENT_ID = re.compile(r"doc_[0-9a-f]{32}\Z")
_OPERATION_ID = re.compile(r"op_[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PURGE_STAGE = re.compile(r"state/locks/\.purge-stage-[0-9a-f]{32}\Z")


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identity_hash(document_id: str) -> str:
    return hashlib.sha256(document_id.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _unsafe_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


class DocumentRetentionManager:
    """Distinct archive, projection, trash and confirmed live-Instance purge."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.lifecycle = InstanceLifecycleManager(store)
        self.operations = OperationLedger(store)
        self.library = LibraryProjectionManager(store)
        self.control_root = self.lifecycle.control_root / "retention"
        self.preview_root = self.control_root / "purge-previews"
        self.pending_path = self.control_root / "pending-purge.json"
        self.receipt_root = store.paths.state / "retention" / "purge-receipts"

    def get(self, document_id: str) -> dict[str, Any] | None:
        if _DOCUMENT_ID.fullmatch(document_id) is None:
            return None
        if self.store.read_canonical("documents", document_id) is None:
            return None
        recorded = disposition_records(self.store).get(document_id)
        selected = recorded or default_disposition(document_id)
        return disposition_view(
            {
                **selected,
                "recorded": recorded is not None,
            }
        )

    def list(self, *, status: str = "all") -> list[dict[str, Any]]:
        if status not in {"active", "archived", "trashed", "all"}:
            raise ValueError("unsupported disposition filter")
        result = [
            selected
            for selected in effective_dispositions(self.store).values()
            if status == "all" or selected["status"] == status
        ]
        return sorted(result, key=lambda item: str(item["document_id"]))

    def _live_target(self, relative: str) -> Path:
        try:
            selected = normalise_locator(relative)
        except ValueError as exc:
            raise PurgeTransactionError("purge target path is invalid") from exc
        if selected != relative:
            raise PurgeTransactionError("purge target path is not normalized")
        current = self.store.paths.root
        for part in PurePosixPath(selected).parts:
            current = current / part
            if _unsafe_link(current):
                raise PurgeTransactionError("purge target path contains an unsafe link")
        try:
            current.resolve().relative_to(self.store.paths.root)
        except ValueError as exc:
            raise PurgeTransactionError("purge target path escapes the Instance") from exc
        return current

    @staticmethod
    def _transition_target(
        current: dict[str, Any],
        action: str,
    ) -> tuple[str, str, str | None, str | None]:
        status = str(current["status"])
        visibility = str(current["library_visibility"])
        restore_status = current.get("restore_status")
        restore_visibility = current.get("restore_library_visibility")
        if action == "archive":
            if status == "trashed":
                raise RetentionConflictError("trashed Document must be restored first")
            return "archived", visibility, None, None
        if action == "unarchive":
            if status == "trashed":
                raise RetentionConflictError("trashed Document must be restored first")
            return "active", visibility, None, None
        if action == "remove_from_library":
            if status == "trashed":
                raise RetentionConflictError("trashed Document is already outside the library")
            return status, "excluded", None, None
        if action == "restore_to_library":
            if status == "trashed":
                raise RetentionConflictError("trashed Document must be restored first")
            return status, "included", None, None
        if action == "trash":
            if status == "trashed":
                return status, visibility, restore_status, restore_visibility
            return "trashed", "excluded", status, visibility
        if action == "restore_from_trash":
            if status != "trashed":
                raise RetentionConflictError("Document is not in recoverable trash")
            return (
                str(restore_status),
                str(restore_visibility),
                None,
                None,
            )
        raise ValueError(f"unsupported retention action: {action}")

    def _sync_document_derived(self, document_id: str) -> None:
        refresh_search_index(
            self.store,
            [document_id],
            recover_missing_derived=False,
        )
        self.library.rebuild(max_documents=MAX_LIBRARY_DOCUMENTS)

    def _restore_disposition_bytes(
        self,
        path: Path,
        previous: bytes | None,
    ) -> None:
        if previous is None:
            path.unlink(missing_ok=True)
            return
        self.store._atomic_bytes(path, previous)

    def _transition(self, document_id: str, action: str) -> dict[str, Any]:
        if _DOCUMENT_ID.fullmatch(document_id) is None:
            raise RetentionNotFoundError(f"document not found: {document_id}")
        with self.lifecycle._hold(purpose=f"document-{action}"):
            self._recover_pending_locked()
            document = self.store.read_canonical("documents", document_id)
            if document is None:
                raise RetentionNotFoundError(f"document not found: {document_id}")
            recorded = disposition_records(self.store).get(document_id)
            current = disposition_view(
                {
                    **(recorded or default_disposition(document_id)),
                    "recorded": recorded is not None,
                }
            )
            target = self._transition_target(current, action)
            existing = (
                str(current["status"]),
                str(current["library_visibility"]),
                current.get("restore_status"),
                current.get("restore_library_visibility"),
            )
            if target == existing:
                return {
                    "schema_version": RETENTION_RECEIPT_SCHEMA_VERSION,
                    "status": "completed",
                    "action": action,
                    "changed": False,
                    "document_id": document_id,
                    "disposition": current,
                    "originals_deleted": 0,
                    "canonical_records_deleted": 0,
                    "operation": None,
                }

            operation = self.operations.start(
                f"document.{action}",
                f"Apply Document retention action: {action}",
                summary="Update canonical disposition and synchronized derived views.",
                related={"document_identity_sha256": _identity_hash(document_id)},
            )
            path = self.store.paths.canonical_dir("dispositions") / (
                f"{disposition_id(document_id)}.json"
            )
            previous = path.read_bytes() if path.is_file() else None
            now = utc_now()
            disposition = DocumentDisposition(
                schema_version=DISPOSITION_SCHEMA_VERSION,
                id=disposition_id(document_id),
                document_id=document_id,
                status=target[0],
                library_visibility=target[1],
                restore_status=target[2],
                restore_library_visibility=target[3],
                revision=int(current["revision"]) + 1,
                created_at=(
                    str(current["created_at"])
                    if current.get("created_at")
                    else now
                ),
                updated_at=now,
                last_operation_id=operation.id,
            )
            try:
                self.store.write_disposition(disposition)
                self._sync_document_derived(document_id)
            except Exception as exc:
                self._restore_disposition_bytes(path, previous)
                try:
                    self._sync_document_derived(document_id)
                except Exception as rollback_exc:
                    self.operations.close(
                        operation.id,
                        status="failed",
                        summary="Disposition rollback could not restore synchronized views.",
                        error_code="retention_rollback_failed",
                        error=str(rollback_exc),
                    )
                    raise RetentionIntegrityError(
                        "retention action failed and derived rollback could not be verified"
                    ) from rollback_exc
                self.operations.close(
                    operation.id,
                    status="failed",
                    summary="Disposition action was rolled back.",
                    error_code="retention_action_failed",
                    error=str(exc),
                )
                raise
            closed = self.operations.close(
                operation.id,
                status="completed",
                summary="Canonical disposition and derived views were committed.",
                metrics={
                    "canonical_records_changed": 1,
                    "originals_deleted": 0,
                },
            )
            selected = self.get(document_id)
            return {
                "schema_version": RETENTION_RECEIPT_SCHEMA_VERSION,
                "status": "completed",
                "action": action,
                "changed": True,
                "document_id": document_id,
                "disposition": selected,
                "originals_deleted": 0,
                "canonical_records_deleted": 0,
                "operation": self.operations._payload(closed),
            }

    def archive(self, document_id: str) -> dict[str, Any]:
        return self._transition(document_id, "archive")

    def unarchive(self, document_id: str) -> dict[str, Any]:
        return self._transition(document_id, "unarchive")

    def remove_from_library(self, document_id: str) -> dict[str, Any]:
        return self._transition(document_id, "remove_from_library")

    def restore_to_library(self, document_id: str) -> dict[str, Any]:
        return self._transition(document_id, "restore_to_library")

    def trash(self, document_id: str) -> dict[str, Any]:
        return self._transition(document_id, "trash")

    def restore_from_trash(self, document_id: str) -> dict[str, Any]:
        return self._transition(document_id, "restore_from_trash")

    def _managed_backup_count(self) -> int:
        directory = default_backup_directory(self.store)
        if not directory.is_dir():
            return 0
        count = 0
        for path in directory.glob("*.zip"):
            if path.is_file():
                count += 1
                if count > MAX_MANAGED_BACKUPS:
                    raise PurgeTransactionError("managed backup count exceeds safety limit")
        return count

    def _lineage(self, document_id: str) -> dict[str, Any]:
        document = self.store.read_canonical("documents", document_id)
        if document is None:
            raise RetentionNotFoundError(f"document not found: {document_id}")
        versions = self.store.versions_for_document(document_id)
        version_ids = {str(item["id"]) for item in versions}
        acquisitions = [
            item
            for item in self.store.list_canonical("acquisitions")
            if item.get("document_id") == document_id
        ]
        acquisition_ids = {str(item["id"]) for item in acquisitions}
        classifications = [
            item
            for item in self.store.list_canonical("classifications")
            if item.get("document_id") == document_id
        ]
        dispositions = [
            item
            for item in self.store.list_canonical("dispositions")
            if item.get("document_id") == document_id
        ]
        original_ids = {str(item["original_id"]) for item in versions}
        remaining_versions = [
            item
            for item in self.store.list_canonical("versions")
            if str(item["id"]) not in version_ids
        ]
        removable_original_ids = {
            original_id
            for original_id in original_ids
            if not any(
                item.get("original_id") == original_id
                for item in remaining_versions
            )
        }
        originals = [
            item
            for item in self.store.list_canonical("originals")
            if item.get("id") in removable_original_ids
        ]
        endpoint_ids = {
            ("document", document_id),
            *(("version", item) for item in version_ids),
            *(("acquisition", item) for item in acquisition_ids),
            *(("original", item) for item in removable_original_ids),
        }
        provenance = [
            item
            for item in self.store.list_canonical("provenance")
            if (str(item.get("from_kind")), str(item.get("from_id"))) in endpoint_ids
            or (str(item.get("to_kind")), str(item.get("to_id"))) in endpoint_ids
        ]
        artifacts = [
            item
            for item in self.store.list_derived_artifacts()
            if item.get("version_id") in version_ids
        ]
        artifact_ids = {str(item["id"]) for item in artifacts}
        derived_endpoint_ids = {
            *(("version", item) for item in version_ids),
            *(("artifact", item) for item in artifact_ids),
            *(("derived_artifact", item) for item in artifact_ids),
        }
        derived_provenance = [
            item
            for item in self.store.list_derived_provenance()
            if (str(item.get("from_kind")), str(item.get("from_id")))
            in derived_endpoint_ids
            or (str(item.get("to_kind")), str(item.get("to_id")))
            in derived_endpoint_ids
        ]
        return {
            "document": document,
            "versions": versions,
            "version_ids": version_ids,
            "acquisitions": acquisitions,
            "classifications": classifications,
            "dispositions": dispositions,
            "originals": originals,
            "shared_originals": len(original_ids - removable_original_ids),
            "provenance": provenance,
            "artifacts": artifacts,
            "derived_provenance": derived_provenance,
        }

    def _purge_targets(
        self,
        document_id: str,
        lineage: dict[str, Any],
    ) -> tuple[dict[str, str], int, int]:
        targets: dict[str, str] = {}

        def add(path: Path, category: str) -> None:
            if not path.exists():
                return
            try:
                relative = path.relative_to(self.store.paths.root).as_posix()
            except ValueError as exc:
                raise PurgeTransactionError("purge target is outside the Instance") from exc
            selected = self._live_target(relative)
            if not selected.is_file():
                raise PurgeTransactionError("purge target is not a safe regular file")
            targets[relative] = category
            if len(targets) > MAX_PURGE_FILES:
                raise PurgeTransactionError("purge target count exceeds safety limit")

        canonical = {
            "documents": [lineage["document"]],
            "versions": lineage["versions"],
            "acquisitions": lineage["acquisitions"],
            "classifications": lineage["classifications"],
            "dispositions": lineage["dispositions"],
            "originals": lineage["originals"],
            "provenance": lineage["provenance"],
        }
        for kind, records in canonical.items():
            for record in records:
                add(
                    self.store.paths.canonical_dir(kind) / f"{record['id']}.json",
                    f"canonical:{kind}",
                )
        original_bytes = 0
        for original in lineage["originals"]:
            relative = normalise_locator(str(original["storage_ref"]))
            path = self.store.paths.root.joinpath(
                *PurePosixPath(relative).parts,
            )
            add(path, "original_bytes")
            original_bytes += int(original["size_bytes"])
        for artifact in lineage["artifacts"]:
            add(
                self.store.paths.derived_artifacts / f"{artifact['id']}.json",
                "derived_artifact_record",
            )
            try:
                relative = normalise_locator(str(artifact["storage_ref"]))
                add(
                    self.store.paths.root.joinpath(
                        *PurePosixPath(relative).parts,
                    ),
                    "derived_artifact_bytes",
                )
            except (KeyError, ValueError):
                raise PurgeTransactionError("derived artifact path is invalid") from None
        for edge in lineage["derived_provenance"]:
            add(
                self.store.paths.derived_provenance / f"{edge['id']}.json",
                "derived_provenance",
            )
        for version_id in lineage["version_ids"]:
            bundle_root = self.store.paths.state / "derived" / "bundles" / version_id
            if bundle_root.exists() and (_unsafe_link(bundle_root) or not bundle_root.is_dir()):
                raise PurgeTransactionError("document bundle path is unsafe")
            if bundle_root.is_dir():
                for path in bundle_root.rglob("*"):
                    if path.is_file() or _unsafe_link(path):
                        add(path, "document_bundle")
        state_root = self.store.paths.state
        identity = document_id.encode("utf-8")
        state_files_not_content_scanned = 0
        if state_root.is_dir():
            for path in state_root.rglob("*"):
                try:
                    relative = path.relative_to(self.store.paths.root)
                except ValueError:
                    continue
                if relative.parts[:2] == ("state", "locks"):
                    continue
                if relative.parts[:3] == ("state", "retention", "purge-receipts"):
                    continue
                relative_text = relative.as_posix()
                if not path.is_file() or relative_text in targets:
                    continue
                if _unsafe_link(path):
                    raise PurgeTransactionError("Instance state contains an unsafe link")
                try:
                    if path.stat().st_size > MAX_PURGE_STATE_SCAN_BYTES:
                        state_files_not_content_scanned += 1
                        continue
                    if identity in path.read_bytes():
                        add(path, "operational_identity_record")
                except OSError as exc:
                    raise PurgeTransactionError("Instance state cannot be inspected") from exc
        return targets, original_bytes, state_files_not_content_scanned

    def _impact(
        self,
        document_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        lineage = self._lineage(document_id)
        targets, original_bytes, state_files_not_content_scanned = self._purge_targets(
            document_id,
            lineage,
        )
        inventory = []
        for relative, category in sorted(targets.items()):
            path = self._live_target(relative)
            inventory.append(
                {
                    "path": relative,
                    "category": category,
                    "size_bytes": path.stat().st_size,
                    "sha256": _file_sha256(path),
                }
            )
        categories: dict[str, int] = {}
        for category in targets.values():
            categories[category] = categories.get(category, 0) + 1
        managed_backups = self._managed_backup_count()
        public = {
            "document_id": document_id,
            "title": str(lineage["document"]["title"]),
            "versions": len(lineage["versions"]),
            "acquisitions": len(lineage["acquisitions"]),
            "canonical_records": sum(
                count
                for category, count in categories.items()
                if category.startswith("canonical:")
            ),
            "original_files": categories.get("original_bytes", 0),
            "original_bytes": original_bytes,
            "shared_originals_retained": int(lineage["shared_originals"]),
            "derived_and_operational_files": sum(
                count
                for category, count in categories.items()
                if not category.startswith("canonical:")
                and category != "original_bytes"
            ),
            "managed_backup_archives_observed": managed_backups,
            "state_files_not_content_scanned": state_files_not_content_scanned,
            "boundaries": {
                "live_instance": (
                    "targeted canonical lineage, Originals and identified local "
                    "derived or operational references"
                ),
                "large_operational_state_files": (
                    "not content-scanned"
                    if state_files_not_content_scanned
                    else "none observed"
                ),
                "configured_source_files": "not modified",
                "managed_backup_archives": (
                    "may retain pre-purge content" if managed_backups else "none observed"
                ),
                "external_backups_and_replicas": "not observable",
                "broader_erasure_claimed": False,
            },
            "network_used": False,
            "ai_used": False,
            "target_inventory_sha256": _json_hash(inventory),
        }
        public["impact_digest"] = _json_hash(public)
        return public, inventory

    @staticmethod
    def _parse_time(value: str) -> datetime:
        selected = datetime.fromisoformat(value)
        if selected.tzinfo is None:
            raise ValueError("timestamp must include a time zone")
        return selected.astimezone(UTC)

    def _cleanup_previews(self) -> None:
        if not self.preview_root.is_dir():
            return
        now = datetime.now(UTC)
        paths = sorted(self.preview_root.glob("*.json"))
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                expired = now >= self._parse_time(str(value["expires_at"]))
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                expired = True
            if expired:
                path.unlink(missing_ok=True)
        remaining = sorted(self.preview_root.glob("*.json"))
        if len(remaining) >= MAX_PURGE_PREVIEWS:
            raise PurgeAuthorizationError("too many active purge previews")

    def purge_preview(self, document_id: str) -> dict[str, Any]:
        with self.lifecycle._hold(purpose="document-purge-preview"):
            self._recover_pending_locked()
            disposition = self.get(document_id)
            if disposition is None:
                raise RetentionNotFoundError(f"document not found: {document_id}")
            if disposition["status"] != "trashed":
                raise RetentionConflictError(
                    "Document must be in recoverable trash before purge preview"
                )
            validation = inspect_instance(self.store.paths.root, deep=True)
            if validation["status"] != "valid":
                raise RetentionIntegrityError(
                    "Instance validation failed before purge preview"
                )
            impact, _targets = self._impact(document_id)
            token = f"purge_{secrets.token_urlsafe(32)}"
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            now = datetime.now(UTC)
            expires = now + PURGE_PREVIEW_TTL
            self._cleanup_previews()
            payload = {
                "schema_version": PURGE_PREVIEW_SCHEMA_VERSION,
                "kind": "provelume-purge-preview",
                "token_sha256": token_hash,
                "document_id": document_id,
                "disposition_revision": int(disposition["revision"]),
                "canonical_fingerprint": validation["content_fingerprint"],
                "impact_digest": impact["impact_digest"],
                "target_inventory_sha256": impact["target_inventory_sha256"],
                "created_at": now.isoformat(),
                "expires_at": expires.isoformat(),
            }
            self.preview_root.mkdir(parents=True, exist_ok=True)
            self.store._atomic_json(self.preview_root / f"{token_hash}.json", payload)
            return {
                "schema_version": PURGE_PREVIEW_SCHEMA_VERSION,
                "status": "confirmation_required",
                "document_id": document_id,
                "confirmation_token": token,
                "expires_at": expires.isoformat(),
                "impact": impact,
                "required_acknowledgement": (
                    "Purge is limited to the live Instance and cannot prove erasure "
                    "from backups, replicas or configured source files."
                ),
            }

    def _preview(self, document_id: str, token: str) -> dict[str, Any]:
        selected = token.strip()
        if not selected or len(selected) > 500:
            raise PurgeAuthorizationError("purge confirmation token is invalid")
        token_hash = hashlib.sha256(selected.encode("utf-8")).hexdigest()
        path = self.preview_root / f"{token_hash}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PurgeAuthorizationError(
                "purge confirmation token is missing or invalid"
            ) from exc
        expected_keys = {
            "schema_version",
            "kind",
            "token_sha256",
            "document_id",
            "disposition_revision",
            "canonical_fingerprint",
            "impact_digest",
            "target_inventory_sha256",
            "created_at",
            "expires_at",
        }
        if (
            not isinstance(value, dict)
            or set(value) != expected_keys
            or value.get("schema_version") != PURGE_PREVIEW_SCHEMA_VERSION
            or value.get("kind") != "provelume-purge-preview"
            or value.get("token_sha256") != token_hash
            or value.get("document_id") != document_id
            or _DOCUMENT_ID.fullmatch(str(value.get("document_id", ""))) is None
            or type(value.get("disposition_revision")) is not int
            or int(value["disposition_revision"]) < 1
            or _SHA256.fullmatch(str(value.get("canonical_fingerprint", ""))) is None
            or _SHA256.fullmatch(str(value.get("impact_digest", ""))) is None
            or _SHA256.fullmatch(str(value.get("target_inventory_sha256", "")))
            is None
            or not isinstance(value.get("created_at"), str)
            or not isinstance(value.get("expires_at"), str)
        ):
            raise PurgeAuthorizationError("purge confirmation token is not bound to target")
        try:
            created_at = self._parse_time(value["created_at"])
            expires_at = self._parse_time(value["expires_at"])
        except ValueError as exc:
            raise PurgeAuthorizationError("purge confirmation timing is invalid") from exc
        if expires_at - created_at != PURGE_PREVIEW_TTL:
            raise PurgeAuthorizationError("purge confirmation timing is invalid")
        if datetime.now(UTC) >= expires_at:
            path.unlink(missing_ok=True)
            raise PurgeAuthorizationError("purge confirmation token has expired")
        return value

    def _receipt_path(self, token_hash: str) -> Path:
        return self.receipt_root / f"{token_hash}.json"

    @staticmethod
    def _valid_count(value: Any) -> bool:
        return type(value) is int and value >= 0

    def _valid_receipt(
        self,
        value: Any,
        *,
        token_hash: str,
        document_id: str | None,
        status: str,
    ) -> bool:
        if not isinstance(value, dict):
            return False
        expected_keys = {
            "schema_version",
            "kind",
            "status",
            "operation_id",
            "completed_at",
            "document_identity_sha256",
            "confirmation_token_sha256",
            "impact_digest",
            "live_instance",
            "boundaries",
            "network_used",
            "ai_used",
        }
        live_keys = {
            "canonical_records_removed",
            "original_files_removed",
            "original_bytes_removed",
            "derived_and_operational_files_removed",
            "shared_originals_retained",
        }
        boundary_keys = {
            "configured_source_files_modified",
            "managed_backup_archives_observed",
            "managed_backup_archives_modified",
            "large_operational_state_files_not_content_scanned",
            "external_backups_and_replicas",
            "broader_erasure_claimed",
        }
        live = value.get("live_instance")
        boundaries = value.get("boundaries")
        identity = value.get("document_identity_sha256")
        completed_at = value.get("completed_at")
        if (
            set(value) != expected_keys
            or value.get("schema_version") != PURGE_RECEIPT_SCHEMA_VERSION
            or value.get("kind") != "provelume-live-instance-purge-receipt"
            or value.get("status") != status
            or _OPERATION_ID.fullmatch(str(value.get("operation_id", ""))) is None
            or _SHA256.fullmatch(str(identity or "")) is None
            or (
                document_id is not None
                and identity != _identity_hash(document_id)
            )
            or value.get("confirmation_token_sha256") != token_hash
            or _SHA256.fullmatch(token_hash) is None
            or _SHA256.fullmatch(str(value.get("impact_digest", ""))) is None
            or not isinstance(live, dict)
            or set(live) != live_keys
            or not all(self._valid_count(live[key]) for key in live_keys)
            or not isinstance(boundaries, dict)
            or set(boundaries) != boundary_keys
            or boundaries.get("configured_source_files_modified") is not False
            or not self._valid_count(
                boundaries.get("managed_backup_archives_observed")
            )
            or boundaries.get("managed_backup_archives_modified") != 0
            or not self._valid_count(
                boundaries.get(
                    "large_operational_state_files_not_content_scanned"
                )
            )
            or boundaries.get("external_backups_and_replicas") != "not_observable"
            or boundaries.get("broader_erasure_claimed") is not False
            or value.get("network_used") is not False
            or value.get("ai_used") is not False
        ):
            return False
        if status == "pending":
            return completed_at is None
        if not isinstance(completed_at, str):
            return False
        try:
            self._parse_time(completed_at)
        except ValueError:
            return False
        return True

    def _read_receipt(
        self,
        token_hash: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        path = self._receipt_path(token_hash)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not self._valid_receipt(
            value,
            token_hash=token_hash,
            document_id=document_id,
            status="completed",
        ):
            return None
        return value

    def _pending(self) -> dict[str, Any] | None:
        if not self.pending_path.is_file():
            return None
        try:
            value = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PurgeTransactionError("pending purge evidence is unreadable") from exc
        required = {
            "schema_version",
            "kind",
            "phase",
            "document_id",
            "operation_id",
            "confirmation_token_sha256",
            "preview_path",
            "stage_relative",
            "targets",
            "receipt",
        }
        if (
            not isinstance(value, dict)
            or set(value) != required
            or value.get("schema_version") != PURGE_RECEIPT_SCHEMA_VERSION
            or value.get("kind") != "provelume-pending-purge"
            or value.get("phase") not in {"prepared", "committed"}
            or not isinstance(value.get("targets"), list)
            or not isinstance(value.get("receipt"), dict)
        ):
            raise PurgeTransactionError("pending purge evidence is invalid")
        document_id = value.get("document_id")
        operation_id = value.get("operation_id")
        token_hash = value.get("confirmation_token_sha256")
        targets = value.get("targets")
        try:
            stage_relative = normalise_locator(str(value["stage_relative"]))
        except ValueError as exc:
            raise PurgeTransactionError("pending purge stage path is invalid") from exc
        if (
            stage_relative != value["stage_relative"]
            or _PURGE_STAGE.fullmatch(stage_relative) is None
            or _DOCUMENT_ID.fullmatch(str(document_id or "")) is None
            or _OPERATION_ID.fullmatch(str(operation_id or "")) is None
            or _SHA256.fullmatch(str(token_hash or "")) is None
            or value.get("preview_path")
            != str(self.preview_root / f"{token_hash}.json")
            or not targets
            or len(targets) > MAX_PURGE_FILES
            or not self._valid_receipt(
                value["receipt"],
                token_hash=str(token_hash),
                document_id=str(document_id),
                status="pending",
            )
            or value["receipt"].get("operation_id") != operation_id
        ):
            raise PurgeTransactionError("pending purge evidence is invalid")
        target_paths: list[str] = []
        for target in targets:
            if (
                not isinstance(target, dict)
                or set(target) != {"path", "category", "size_bytes", "sha256"}
                or not isinstance(target.get("path"), str)
                or not isinstance(target.get("category"), str)
                or not str(target["category"]).strip()
                or len(str(target["category"])) > 120
                or not self._valid_count(target.get("size_bytes"))
                or _SHA256.fullmatch(str(target.get("sha256", ""))) is None
            ):
                raise PurgeTransactionError("pending purge target is invalid")
            try:
                selected = normalise_locator(target["path"])
            except ValueError as exc:
                raise PurgeTransactionError("pending purge target is invalid") from exc
            parts = PurePosixPath(selected).parts
            if (
                selected != target["path"]
                or parts[:2] == ("state", "locks")
                or parts[:3] == ("state", "retention", "purge-receipts")
            ):
                raise PurgeTransactionError("pending purge target is invalid")
            target_paths.append(selected)
        if target_paths != sorted(set(target_paths)):
            raise PurgeTransactionError("pending purge targets are not sorted and unique")
        return value

    def _stage_path(self, pending: dict[str, Any]) -> Path:
        relative = str(pending["stage_relative"])
        stage = self._live_target(relative)
        parent = self._live_target("state/locks")
        if not parent.is_dir() or stage.parent != parent:
            raise PurgeTransactionError("pending purge stage path is invalid")
        return stage

    @staticmethod
    def _staged_target(stage: Path, relative: str) -> Path:
        target = stage
        for part in PurePosixPath(relative).parts:
            target = target / part
            if _unsafe_link(target):
                raise PurgeTransactionError("staged purge target is unsafe")
        if target.exists():
            try:
                target.resolve().relative_to(stage.resolve())
            except ValueError as exc:
                raise PurgeTransactionError("staged purge target is unsafe") from exc
            if _unsafe_link(target) or not target.is_file():
                raise PurgeTransactionError("staged purge target is unsafe")
        return target

    @staticmethod
    def _target_path(target: dict[str, Any]) -> str:
        return str(target["path"])

    @staticmethod
    def _matches_target(path: Path, target: dict[str, Any]) -> bool:
        try:
            return (
                path.stat().st_size == int(target["size_bytes"])
                and _file_sha256(path) == target["sha256"]
            )
        except OSError:
            return False

    def _verify_staged_targets(
        self,
        pending: dict[str, Any],
        *,
        require_all: bool,
    ) -> None:
        stage = self._stage_path(pending)
        if not stage.exists():
            if require_all:
                raise PurgeTransactionError("purge staging area is missing")
            return
        if not stage.is_dir():
            raise PurgeTransactionError("purge staging area is invalid")
        expected = {
            self._target_path(target): target for target in pending["targets"]
        }
        found: set[str] = set()
        for path in stage.rglob("*"):
            relative = path.relative_to(stage).as_posix()
            if _unsafe_link(path):
                raise PurgeTransactionError("purge staging area contains an unsafe link")
            if path.is_dir():
                continue
            target = expected.get(relative)
            if target is None or not path.is_file():
                raise PurgeTransactionError("purge staging area contains an unknown file")
            if not self._matches_target(path, target):
                raise PurgeTransactionError("staged purge target changed before commit")
            found.add(relative)
        if require_all and found != set(expected):
            raise PurgeTransactionError("purge staging inventory is incomplete")

    def _verify_live_targets_absent(self, pending: dict[str, Any]) -> None:
        for target in pending["targets"]:
            if self._live_target(self._target_path(target)).exists():
                raise PurgeTransactionError(
                    "purge target was recreated before commit"
                )

    def _stage_targets(self, pending: dict[str, Any]) -> None:
        stage = self._stage_path(pending)
        stage.mkdir(parents=True, exist_ok=False)
        for target_spec in pending["targets"]:
            selected = self._target_path(target_spec)
            source = self._live_target(selected)
            if not source.is_file() or not self._matches_target(source, target_spec):
                raise PurgeTransactionError("purge target changed before commit")
            target = self._staged_target(stage, selected)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)

    def _restore_prepared(self, pending: dict[str, Any], *, error: str) -> None:
        stage = self._stage_path(pending)
        self._verify_staged_targets(pending, require_all=False)
        for target_spec in reversed(pending["targets"]):
            selected = self._target_path(target_spec)
            staged = self._staged_target(stage, selected)
            if not staged.exists():
                continue
            live = self._live_target(selected)
            if live.exists():
                raise PurgeTransactionError(
                    "purge rollback target was unexpectedly recreated"
                )
            live.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, live)
        if stage.exists():
            shutil.rmtree(stage)
        rebuild_search_index(self.store, recover_missing_derived=False)
        self.library.rebuild(max_documents=MAX_LIBRARY_DOCUMENTS)
        operation = self.operations.get_record(str(pending["operation_id"]))
        if operation is not None and operation.status == "running":
            self.operations.close(
                operation.id,
                status="failed",
                summary="Interrupted purge was rolled back before commit.",
                error_code="purge_rolled_back",
                error=error,
            )
        self.pending_path.unlink(missing_ok=True)

    def _finalize_committed(self, pending: dict[str, Any]) -> dict[str, Any]:
        receipt = {
            **pending["receipt"],
            "status": "completed",
            "completed_at": utc_now(),
        }
        token_hash = str(pending["confirmation_token_sha256"])
        if not self._valid_receipt(
            receipt,
            token_hash=token_hash,
            document_id=str(pending["document_id"]),
            status="completed",
        ):
            raise PurgeTransactionError("completed purge receipt is invalid")
        stage = self._stage_path(pending)
        if stage.exists():
            self._verify_staged_targets(pending, require_all=False)
            shutil.rmtree(stage)
        rebuild_search_index(self.store, recover_missing_derived=False)
        self.library.rebuild(max_documents=MAX_LIBRARY_DOCUMENTS)
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.store._atomic_json(self._receipt_path(token_hash), receipt)
        operation = self.operations.get_record(str(pending["operation_id"]))
        if operation is not None and operation.status == "running":
            self.operations.close(
                operation.id,
                status="completed",
                summary="Confirmed live-Instance purge completed.",
                metrics={
                    "canonical_records_removed": int(
                        receipt["live_instance"]["canonical_records_removed"]
                    ),
                    "original_files_removed": int(
                        receipt["live_instance"]["original_files_removed"]
                    ),
                    "original_bytes_removed": int(
                        receipt["live_instance"]["original_bytes_removed"]
                    ),
                },
            )
        Path(str(pending["preview_path"])).unlink(missing_ok=True)
        self.pending_path.unlink(missing_ok=True)
        return receipt

    def _recover_pending_locked(self) -> dict[str, Any] | None:
        pending = self._pending()
        if pending is None:
            return None
        if pending["phase"] == "committed":
            receipt = self._finalize_committed(pending)
            return {"action": "completed_committed_purge", "receipt": receipt}
        self._restore_prepared(pending, error="interrupted before purge commit")
        return {"action": "restored_pre_purge_state", "receipt": None}

    def recover_pending(self) -> dict[str, Any] | None:
        if not self.pending_path.exists():
            return None
        with self.lifecycle._hold(purpose="document-purge-recovery"):
            return self._recover_pending_locked()

    def purge(
        self,
        document_id: str,
        confirmation_token: str,
        *,
        acknowledge_boundaries: bool = False,
    ) -> dict[str, Any]:
        if not acknowledge_boundaries:
            raise PurgeAuthorizationError(
                "explicit acknowledgement of backup, replica and source boundaries is required"
            )
        if _DOCUMENT_ID.fullmatch(document_id) is None:
            raise RetentionNotFoundError(f"document not found: {document_id}")
        selected_token = confirmation_token.strip()
        if not selected_token or len(selected_token) > 500:
            raise PurgeAuthorizationError("purge confirmation token is invalid")
        token_hash = hashlib.sha256(selected_token.encode("utf-8")).hexdigest()
        with self.lifecycle._hold(purpose="document-permanent-purge"):
            recovery = self._recover_pending_locked()
            if recovery and recovery.get("receipt"):
                recovered_receipt = recovery["receipt"]
                if (
                    recovered_receipt.get("confirmation_token_sha256") == token_hash
                    and recovered_receipt.get("document_identity_sha256")
                    == _identity_hash(document_id)
                ):
                    return {"status": "already_completed", "receipt": recovered_receipt}
            existing_receipt = self._read_receipt(token_hash, document_id)
            document = self.store.read_canonical("documents", document_id)
            if document is None:
                if existing_receipt is not None:
                    return {"status": "already_completed", "receipt": existing_receipt}
                raise RetentionNotFoundError(f"document not found: {document_id}")
            preview = self._preview(document_id, selected_token)
            disposition = self.get(document_id)
            if disposition is None or disposition["status"] != "trashed":
                raise RetentionConflictError(
                    "Document must remain in recoverable trash until purge commit"
                )
            validation = inspect_instance(self.store.paths.root, deep=True)
            if validation["status"] != "valid":
                raise RetentionIntegrityError("Instance validation failed before purge")
            impact, targets = self._impact(document_id)
            if (
                preview["canonical_fingerprint"] != validation["content_fingerprint"]
                or preview["disposition_revision"] != disposition["revision"]
                or preview["impact_digest"] != impact["impact_digest"]
                or preview["target_inventory_sha256"]
                != impact["target_inventory_sha256"]
            ):
                raise PurgeAuthorizationError(
                    "purge preview is stale; generate and confirm a new impact preview"
                )
            lock_area = self._live_target("state/locks")
            if lock_area.exists() and not lock_area.is_dir():
                raise PurgeTransactionError("purge lock area is invalid")
            lock_area.mkdir(parents=True, exist_ok=True)
            operation = self.operations.start(
                "document.permanent_purge",
                "Permanently purge one trashed Document from the live Instance",
                summary="Execute a preview-bound and explicitly acknowledged live-Instance purge.",
                related={"document_identity_sha256": _identity_hash(document_id)},
            )
            stage_relative = f"state/locks/.purge-stage-{uuid4().hex}"
            receipt = {
                "schema_version": PURGE_RECEIPT_SCHEMA_VERSION,
                "kind": "provelume-live-instance-purge-receipt",
                "status": "pending",
                "operation_id": operation.id,
                "completed_at": None,
                "document_identity_sha256": _identity_hash(document_id),
                "confirmation_token_sha256": token_hash,
                "impact_digest": impact["impact_digest"],
                "live_instance": {
                    "canonical_records_removed": impact["canonical_records"],
                    "original_files_removed": impact["original_files"],
                    "original_bytes_removed": impact["original_bytes"],
                    "derived_and_operational_files_removed": impact[
                        "derived_and_operational_files"
                    ],
                    "shared_originals_retained": impact[
                        "shared_originals_retained"
                    ],
                },
                "boundaries": {
                    "configured_source_files_modified": False,
                    "managed_backup_archives_observed": impact[
                        "managed_backup_archives_observed"
                    ],
                    "managed_backup_archives_modified": 0,
                    "large_operational_state_files_not_content_scanned": impact[
                        "state_files_not_content_scanned"
                    ],
                    "external_backups_and_replicas": "not_observable",
                    "broader_erasure_claimed": False,
                },
                "network_used": False,
                "ai_used": False,
            }
            pending = {
                "schema_version": PURGE_RECEIPT_SCHEMA_VERSION,
                "kind": "provelume-pending-purge",
                "phase": "prepared",
                "document_id": document_id,
                "operation_id": operation.id,
                "confirmation_token_sha256": token_hash,
                "preview_path": str(self.preview_root / f"{token_hash}.json"),
                "stage_relative": stage_relative,
                "targets": targets,
                "receipt": receipt,
            }
            try:
                self.control_root.mkdir(parents=True, exist_ok=True)
                self.store._atomic_json(self.pending_path, pending)
            except Exception as exc:
                self.operations.close(
                    operation.id,
                    status="failed",
                    summary="Purge preparation failed before any target was staged.",
                    error_code="purge_preparation_failed",
                    error=str(exc),
                )
                raise
            try:
                self._stage_targets(pending)
                self._verify_staged_targets(pending, require_all=True)
                self._verify_live_targets_absent(pending)
                residual = inspect_instance(self.store.paths.root, deep=True)
                if residual["status"] != "valid":
                    raise PurgeTransactionError(
                        "purged staging state failed live Instance validation"
                    )
                rebuild_search_index(self.store, recover_missing_derived=False)
                self.library.rebuild(max_documents=MAX_LIBRARY_DOCUMENTS)
                self._verify_live_targets_absent(pending)
                pending["phase"] = "committed"
                self.store._atomic_json(self.pending_path, pending)
            except Exception as exc:
                latest = self._pending()
                if latest is not None and latest["phase"] == "prepared":
                    self._restore_prepared(latest, error=str(exc))
                raise
            completed = self._finalize_committed(pending)
            return {"status": "completed", "receipt": completed}
