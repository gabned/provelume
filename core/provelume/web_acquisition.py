from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from contextlib import suppress
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

from .connectors import ConnectorManager
from .derived import EXTRACTED_TEXT_SCHEMA
from .domain import (
    Acquisition,
    DerivedArtifact,
    Document,
    DocumentVersion,
    Original,
    ProvenanceEdge,
)
from .extractors import ExtractionError, ExtractionResult, extract_web_readable_text
from .instance_lifecycle import InstanceLifecycleManager
from .operations import OperationEvent, OperationLedger, OperationRecord
from .paths import safe_instance_path
from .storage import InstanceStore, utc_now
from .web_transport import (
    GuardedWebRequest,
    GuardedWebResponse,
    GuardedWebTransport,
    WebTransportError,
)

MANUAL_WEB_ACQUISITION_SCHEMA_VERSION = 1
MANUAL_WEB_ACQUISITION_KIND = "manual_web"
MANUAL_WEB_OPERATION_KIND = "connector.web.acquire"
MANUAL_WEB_TRANSACTION_SCHEMA_VERSION = 1
_TRANSACTION_DIRECTORY = re.compile(r"manual-web-[0-9a-f]{32}\Z")
_OPERATION_ID = re.compile(r"op_[0-9a-f]{32}\Z")
_JOURNAL_FILE = re.compile(r"(?:candidates|preimages)/[0-9]{4}\.bin\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ManualWebAcquisitionError(RuntimeError):
    code = "manual_web_acquisition_failed"
    safe_message = "Manual web acquisition failed closed."

    def __init__(self) -> None:
        super().__init__(self.safe_message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.safe_message}


class ManualWebResponseError(ManualWebAcquisitionError):
    code = "manual_web_response_not_acquirable"
    safe_message = "The guarded response cannot create a manual acquisition."


class ManualWebIntegrityError(ManualWebAcquisitionError):
    code = "manual_web_canonical_integrity_failed"
    safe_message = "Existing canonical state rejected the manual acquisition."


class ManualWebAtomicityError(ManualWebAcquisitionError):
    code = "manual_web_atomic_commit_failed"
    safe_message = "Manual web acquisition rolled back before completion."


class _AtomicInstanceCommit:
    """Durably journal a bounded multi-file Instance commit before live replacement."""

    def __init__(
        self,
        store: InstanceStore,
        stage_parent: Path,
        *,
        operation_id: str,
    ):
        self.store = store
        self.stage_parent = stage_parent
        self.operation_id = operation_id
        self._writes: dict[str, tuple[bytes, bool]] = {}

    def add(self, relative: str, data: bytes, *, immutable: bool) -> None:
        target = safe_instance_path(self.store.paths.root, relative)
        selected = target.relative_to(self.store.paths.root).as_posix()
        current = self._writes.get(selected)
        candidate = (bytes(data), immutable)
        if current is not None and current != candidate:
            raise ManualWebIntegrityError
        self._writes[selected] = candidate

    def _prepare(self) -> tuple[Path, dict[str, Any]]:
        self.stage_parent.mkdir(parents=True, exist_ok=True)
        transaction_id = f"manual-web-{uuid4().hex}"
        stage = self.stage_parent / transaction_id
        stage.mkdir()
        try:
            entries: list[dict[str, Any]] = []
            for index, (relative, (data, immutable)) in enumerate(
                sorted(self._writes.items())
            ):
                target = safe_instance_path(self.store.paths.root, relative)
                if target.is_symlink():
                    raise ManualWebIntegrityError
                if target.exists() and not target.is_file():
                    raise ManualWebIntegrityError
                before = target.read_bytes() if target.is_file() else None
                if before is not None and immutable and before != data:
                    raise ManualWebIntegrityError
                if before == data:
                    continue
                candidate_ref = f"candidates/{index:04d}.bin"
                self.store._atomic_bytes(stage / candidate_ref, data)
                preimage_ref = (
                    f"preimages/{index:04d}.bin" if before is not None else None
                )
                if before is not None and preimage_ref is not None:
                    self.store._atomic_bytes(stage / preimage_ref, before)
                entries.append(
                    {
                        "relative": relative,
                        "immutable": immutable,
                        "had_preimage": before is not None,
                        "preimage_ref": preimage_ref,
                        "preimage_sha256": (
                            hashlib.sha256(before).hexdigest()
                            if before is not None
                            else None
                        ),
                        "candidate_ref": candidate_ref,
                        "candidate_sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
            if not entries:
                raise ManualWebIntegrityError
            manifest = {
                "schema_version": MANUAL_WEB_TRANSACTION_SCHEMA_VERSION,
                "transaction_id": transaction_id,
                "kind": MANUAL_WEB_OPERATION_KIND,
                "status": "prepared",
                "operation_id": self.operation_id,
                "prepared_at": utc_now(),
                "committed_at": None,
                "entries": entries,
            }
            self.store._atomic_json(stage / "manifest.json", manifest)
            _fsync_directory(stage)
            _fsync_directory(self.stage_parent)
            return stage, manifest
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    def commit(self) -> None:
        try:
            stage, manifest = self._prepare()
        except ManualWebAcquisitionError:
            raise
        except Exception:
            raise ManualWebAtomicityError from None
        try:
            for entry in manifest["entries"]:
                target = safe_instance_path(
                    self.store.paths.root,
                    str(entry["relative"]),
                )
                before = target.read_bytes() if target.is_file() else None
                expected_before = (
                    _journal_bytes(stage, str(entry["preimage_ref"]))
                    if entry["had_preimage"]
                    else None
                )
                if before != expected_before:
                    raise ManualWebAtomicityError
                candidate = _journal_path(stage, str(entry["candidate_ref"]))
                data = candidate.read_bytes()
                if hashlib.sha256(data).hexdigest() != entry["candidate_sha256"]:
                    raise ManualWebAtomicityError
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(candidate, target)
                _fsync_directory(target.parent)
            committed = {
                **manifest,
                "status": "committed",
                "committed_at": utc_now(),
            }
            self.store._atomic_json(stage / "manifest.json", committed)
            _fsync_directory(stage)
        except Exception as exc:
            try:
                _rollback_prepared_transaction(self.store, stage, manifest)
                shutil.rmtree(stage)
                _fsync_directory(self.stage_parent)
            except Exception:
                raise ManualWebAtomicityError from None
            if isinstance(exc, ManualWebAcquisitionError):
                raise
            raise ManualWebAtomicityError from None
        shutil.rmtree(stage, ignore_errors=True)
        # A durable committed marker makes later journal cleanup recoverable on open.
        with suppress(OSError):
            _fsync_directory(self.stage_parent)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _journal_path(stage: Path, relative: str) -> Path:
    if _JOURNAL_FILE.fullmatch(relative) is None:
        raise ManualWebAtomicityError
    return safe_instance_path(stage, relative)


def _journal_bytes(stage: Path, relative: str) -> bytes:
    path = _journal_path(stage, relative)
    if not path.is_file() or path.is_symlink():
        raise ManualWebAtomicityError
    return path.read_bytes()


def _load_transaction_manifest(stage: Path) -> dict[str, Any] | None:
    path = stage / "manifest.json"
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise ManualWebAtomicityError
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ManualWebAtomicityError from None
    if not isinstance(value, dict):
        raise ManualWebAtomicityError
    return value


def _validate_transaction_manifest(
    store: InstanceStore,
    stage: Path,
    manifest: dict[str, Any],
) -> None:
    if set(manifest) != {
        "schema_version",
        "transaction_id",
        "kind",
        "status",
        "operation_id",
        "prepared_at",
        "committed_at",
        "entries",
    }:
        raise ManualWebAtomicityError
    status = manifest.get("status")
    if (
        manifest.get("schema_version") != MANUAL_WEB_TRANSACTION_SCHEMA_VERSION
        or manifest.get("transaction_id") != stage.name
        or _TRANSACTION_DIRECTORY.fullmatch(stage.name) is None
        or manifest.get("kind") != MANUAL_WEB_OPERATION_KIND
        or _OPERATION_ID.fullmatch(str(manifest.get("operation_id"))) is None
        or status not in {"prepared", "committed"}
        or not isinstance(manifest.get("prepared_at"), str)
        or (status == "prepared" and manifest.get("committed_at") is not None)
        or (status == "committed" and not isinstance(manifest.get("committed_at"), str))
    ):
        raise ManualWebAtomicityError
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 2048:
        raise ManualWebAtomicityError
    seen: set[str] = set()
    candidate_refs: set[str] = set()
    preimage_refs: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "relative",
            "immutable",
            "had_preimage",
            "preimage_ref",
            "preimage_sha256",
            "candidate_ref",
            "candidate_sha256",
        }:
            raise ManualWebAtomicityError
        relative = entry.get("relative")
        if not isinstance(relative, str) or relative in seen:
            raise ManualWebAtomicityError
        safe_instance_path(store.paths.root, relative)
        seen.add(relative)
        candidate_ref = entry.get("candidate_ref")
        if (
            type(entry.get("immutable")) is not bool
            or type(entry.get("had_preimage")) is not bool
            or not isinstance(candidate_ref, str)
            or not candidate_ref.startswith("candidates/")
            or _JOURNAL_FILE.fullmatch(candidate_ref) is None
            or candidate_ref in candidate_refs
            or _SHA256.fullmatch(str(entry.get("candidate_sha256"))) is None
        ):
            raise ManualWebAtomicityError
        candidate_refs.add(candidate_ref)
        if entry["had_preimage"]:
            preimage_ref = entry.get("preimage_ref")
            if (
                not isinstance(preimage_ref, str)
                or not preimage_ref.startswith("preimages/")
                or _JOURNAL_FILE.fullmatch(preimage_ref) is None
                or preimage_ref in preimage_refs
                or _SHA256.fullmatch(str(entry.get("preimage_sha256"))) is None
            ):
                raise ManualWebAtomicityError
            preimage_refs.add(preimage_ref)
        elif entry.get("preimage_ref") is not None or entry.get(
            "preimage_sha256"
        ) is not None:
            raise ManualWebAtomicityError


def _rollback_prepared_transaction(
    store: InstanceStore,
    stage: Path,
    manifest: dict[str, Any],
) -> None:
    for entry in reversed(manifest["entries"]):
        target = safe_instance_path(store.paths.root, str(entry["relative"]))
        if entry["had_preimage"]:
            before = _journal_bytes(stage, str(entry["preimage_ref"]))
            if hashlib.sha256(before).hexdigest() != entry["preimage_sha256"]:
                raise ManualWebAtomicityError
            store._atomic_bytes(target, before)
            _fsync_directory(target.parent)
        else:
            existed = target.exists()
            target.unlink(missing_ok=True)
            if existed:
                _fsync_directory(target.parent)


def _close_interrupted_operation(store: InstanceStore, operation_id: str) -> None:
    ledger = OperationLedger(store)
    current = ledger.get_record(operation_id)
    if current is None:
        raise ManualWebAtomicityError
    if current.status == "failed":
        return
    if current.status != "running":
        raise ManualWebAtomicityError
    ledger.append(
        operation_id,
        "manual_web.interrupted_rollback",
        "Interrupted manual web acquisition was rolled back during Instance open.",
        level="error",
        details={"canonical_records_created": 0, "originals_deleted": 0},
    )
    ledger.close(
        operation_id,
        status="failed",
        summary="Interrupted manual web acquisition recovered without canonical partial state.",
        metrics={"canonical_records_created": 0, "originals_deleted": 0},
        error_code="manual_web_interrupted_rollback",
        error="Interrupted manual web acquisition was rolled back safely.",
    )


def recover_manual_web_transactions(
    store: InstanceStore,
    control_root: Path,
) -> dict[str, Any] | None:
    """Recover prepared S05 journals before an Instance is validated or used."""

    root = control_root / "transactions"
    if not root.exists():
        return None
    if not root.is_dir() or root.is_symlink():
        raise ManualWebAtomicityError
    rolled_back = 0
    committed_cleanups = 0
    for stage in sorted(root.glob("manual-web-*")):
        if not stage.is_dir() or stage.is_symlink():
            raise ManualWebAtomicityError
        manifest = _load_transaction_manifest(stage)
        if manifest is None:
            shutil.rmtree(stage)
            continue
        _validate_transaction_manifest(store, stage, manifest)
        if manifest["status"] == "prepared":
            _rollback_prepared_transaction(store, stage, manifest)
            _close_interrupted_operation(store, str(manifest["operation_id"]))
            rolled_back += 1
        else:
            for entry in manifest["entries"]:
                target = safe_instance_path(store.paths.root, str(entry["relative"]))
                if (
                    not target.is_file()
                    or target.is_symlink()
                    or hashlib.sha256(target.read_bytes()).hexdigest()
                    != entry["candidate_sha256"]
                ):
                    raise ManualWebAtomicityError
            committed_cleanups += 1
        shutil.rmtree(stage)
    _fsync_directory(root)
    if not rolled_back and not committed_cleanups:
        return None
    return {
        "schema_version": MANUAL_WEB_TRANSACTION_SCHEMA_VERSION,
        "status": "recovered",
        "rolled_back": rolled_back,
        "committed_cleanups": committed_cleanups,
    }


def _json_bytes(value: Any) -> bytes:
    payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _stable_document_id(source_id: str, canonical_url: str) -> str:
    value = f"provelume:web-document:{source_id}:{canonical_url}"
    return f"doc_{uuid5(NAMESPACE_URL, value).hex}"


def _stable_version_id(document_id: str, digest: str) -> str:
    return f"ver_{uuid5(NAMESPACE_URL, f'provelume:{document_id}:{digest}').hex}"


def _title(canonical_url: str) -> str:
    parsed = urlsplit(canonical_url)
    selected = PurePosixPath(parsed.path).name or parsed.hostname or "Web document"
    selected = "".join(character for character in selected if ord(character) >= 0x20)
    return selected[:300] or "Web document"


def _edge(
    from_kind: str,
    from_id: str,
    relation: str,
    to_kind: str,
    to_id: str,
    *,
    created_at: str,
) -> ProvenanceEdge:
    value = f"{from_kind}:{from_id}:{relation}:{to_kind}:{to_id}"
    return ProvenanceEdge(
        id=f"edge_{uuid5(NAMESPACE_URL, value).hex}",
        from_kind=from_kind,
        from_id=from_id,
        relation=relation,
        to_kind=to_kind,
        to_id=to_id,
        created_at=created_at,
    )


def _derived(
    version_id: str,
    extraction: ExtractionResult,
    *,
    created_at: str,
) -> tuple[DerivedArtifact, bytes]:
    key = f"{version_id}:extracted_text:{extraction.generator}:{EXTRACTED_TEXT_SCHEMA}"
    artifact_id = f"derived_{uuid5(NAMESPACE_URL, key).hex}"
    data = extraction.text.encode("utf-8")
    return (
        DerivedArtifact(
            id=artifact_id,
            version_id=version_id,
            kind="extracted_text",
            generator=extraction.generator,
            generator_version=extraction.generator_version,
            storage_ref=f"state/derived/text/{artifact_id}.txt",
            checksum=hashlib.sha256(data).hexdigest(),
            created_at=created_at,
        ),
        data,
    )


class ManualWebAcquisitionManager:
    """Acquire one explicitly requested guarded-web response into canonical knowledge."""

    def __init__(
        self,
        store: InstanceStore,
        connectors: ConnectorManager,
        transport: GuardedWebTransport,
    ):
        self.store = store
        self.connectors = connectors
        self.transport = transport
        self.lifecycle = InstanceLifecycleManager(store)
        self.operations = OperationLedger(store)

    @staticmethod
    def _operation_view(record: OperationRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "status": record.status,
            "completed_at": record.completed_at,
        }

    def _close_failed(
        self,
        operation: OperationRecord,
        error: WebTransportError | ManualWebAcquisitionError,
    ) -> None:
        try:
            current = self.operations.get_record(operation.id)
            if current is None or current.status != "running":
                return
            code = error.code
            message = error.safe_message
            details: dict[str, Any] = {"network_requested": True}
            if isinstance(error, WebTransportError):
                details["retryable"] = error.retryable
            self.operations.append(
                operation.id,
                code,
                message,
                level="error",
                details=details,
            )
            self.operations.close(
                operation.id,
                status="failed",
                summary="Manual web acquisition failed without canonical partial state.",
                metrics={"canonical_records_created": 0, "originals_deleted": 0},
                error_code=code,
                error=message,
            )
        except (OSError, RuntimeError, ValueError):
            return

    def _previous_acquisition(
        self,
        source_id: str,
        canonical_url: str,
    ) -> dict[str, Any] | None:
        matches = [
            item
            for item in self.store.list_canonical("acquisitions")
            if item.get("acquisition_kind") == MANUAL_WEB_ACQUISITION_KIND
            and item.get("source_id") == source_id
            and item.get("requested_url") == canonical_url
        ]
        return max(
            matches,
            key=lambda item: (str(item.get("retrieved_at", "")), str(item["id"])),
            default=None,
        )

    def _stage_canonical(
        self,
        transaction: _AtomicInstanceCommit,
        kind: str,
        record: Any,
        *,
        immutable: bool,
    ) -> None:
        transaction.add(
            f"knowledge/{kind}/{record.id}.json",
            _json_bytes(record),
            immutable=immutable,
        )

    def _stage_edge(
        self,
        transaction: _AtomicInstanceCommit,
        edge: ProvenanceEdge,
    ) -> dict[str, Any]:
        existing = self.store.read_canonical("provenance", edge.id)
        if existing is not None:
            expected = asdict(edge)
            expected["created_at"] = existing.get("created_at")
            if existing != expected:
                raise ManualWebIntegrityError
            return existing
        self._stage_canonical(transaction, "provenance", edge, immutable=True)
        return asdict(edge)

    def _detail_payload(
        self,
        acquisition: dict[str, Any],
        document: dict[str, Any],
        version: dict[str, Any],
        original: dict[str, Any],
        artifact: dict[str, Any] | None,
        provenance: list[dict[str, Any]],
    ) -> dict[str, Any]:
        provenance.sort(key=lambda item: (str(item["created_at"]), str(item["id"])))
        return {
            "schema_version": MANUAL_WEB_ACQUISITION_SCHEMA_VERSION,
            "status": "completed",
            "acquisition": acquisition,
            "summary": self._summary(acquisition),
            "document": document,
            "version": version,
            "original": original,
            "derived": {
                "status": str(acquisition["derived_status"]),
                "artifact": artifact,
                "rebuildable": True,
                "replaces_original": False,
            },
            "provenance": provenance,
            "idempotency": {
                "scope": "canonical_content",
                "acquisition_per_successful_request": True,
                "replay": acquisition.get("replay_of_acquisition_id") is not None,
                "replay_of_acquisition_id": acquisition.get(
                    "replay_of_acquisition_id"
                ),
                "exact_duplicate": bool(acquisition.get("exact_duplicate")),
                "canonical_outcome": str(acquisition["outcome"]),
            },
        }

    def _terminal_operation(
        self,
        operation_id: str,
        acquisition: Acquisition,
        effects: dict[str, Any],
    ) -> OperationRecord:
        current = self.operations.get_record(operation_id)
        if current is None or current.status != "running":
            raise ManualWebIntegrityError
        events = list(current.events)
        if acquisition.derived_status == "unavailable":
            events.append(
                OperationEvent(
                    at=utc_now(),
                    level="warning",
                    code="manual_web.derived_unavailable",
                    message=(
                        "No deterministic readable text was created; the Original remains retained."
                    ),
                    details={"media_type": acquisition.media_type},
                )
            )
        events.append(
            OperationEvent(
                at=utc_now(),
                level="info",
                code="manual_web.committed",
                message=(
                    "Canonical acquisition and exact Original bindings were committed."
                ),
                details={
                    "acquisition_id": acquisition.id,
                    "document_id": acquisition.document_id,
                    "version_id": acquisition.version_id,
                    "original_id": acquisition.original_id,
                    "original_action": (
                        "created" if effects["original_created"] else "reused"
                    ),
                },
            )
        )
        closed = replace(
            current,
            status="completed",
            completed_at=utc_now(),
            summary=(
                "Manual web acquisition completed with immutable Original preservation."
            ),
            metrics={
                "acquisitions_created": 1,
                "documents_created": int(effects["document_created"]),
                "versions_created": int(effects["version_created"]),
                "originals_created": int(effects["original_created"]),
                "derived_artifacts_created": int(effects["derived_created"]),
                "originals_deleted": 0,
                "originals_overwritten": 0,
            },
            error_code=None,
            error=None,
            events=tuple(events),
        )
        self.operations._validate_record(closed)
        return closed

    def _plan_commit(
        self,
        request: GuardedWebRequest,
        response: GuardedWebResponse,
        canonical_url: str,
        authorized_origins: tuple[str, ...],
        retrieved_at: str,
        operation_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], OperationRecord]:
        if response.status != 200 or response.not_modified or response.content_type is None:
            raise ManualWebResponseError
        data = response.body
        digest = hashlib.sha256(data).hexdigest()
        original_id = f"sha256_{digest}"
        original_ref = f"originals/sha256/{digest[:2]}/{digest}"
        existing_original = self.store.read_canonical("originals", original_id)
        if existing_original is not None:
            if (
                existing_original.get("sha256") != digest
                or existing_original.get("size_bytes") != len(data)
                or existing_original.get("storage_ref") != original_ref
            ):
                raise ManualWebIntegrityError
            try:
                if self.store.original_bytes(original_id) != data:
                    raise ManualWebIntegrityError
            except (KeyError, OSError, ValueError):
                raise ManualWebIntegrityError from None
            original = Original(**existing_original)
        else:
            original = Original(
                id=original_id,
                sha256=digest,
                size_bytes=len(data),
                storage_ref=original_ref,
                created_at=retrieved_at,
            )

        existing_document = self.store.find_document(request.source_id, canonical_url)
        document_id = (
            str(existing_document["id"])
            if existing_document is not None
            else _stable_document_id(request.source_id, canonical_url)
        )
        if (
            existing_document is None
            and self.store.read_canonical("documents", document_id) is not None
        ):
            raise ManualWebIntegrityError
        versions = self.store.versions_for_document(document_id)
        matching = next(
            (item for item in versions if item.get("content_hash") == digest),
            None,
        )
        if matching is None:
            version_id = _stable_version_id(document_id, digest)
            version = DocumentVersion(
                id=version_id,
                document_id=document_id,
                sequence=max((int(item["sequence"]) for item in versions), default=0) + 1,
                content_hash=digest,
                original_id=original.id,
                media_type=response.content_type,
                size_bytes=len(data),
                acquired_at=retrieved_at,
            )
            version_preexisting = False
        else:
            if (
                matching.get("document_id") != document_id
                or matching.get("original_id") != original.id
                or matching.get("size_bytes") != len(data)
            ):
                raise ManualWebIntegrityError
            version = DocumentVersion(**matching)
            version_id = version.id
            version_preexisting = True

        if existing_document is None:
            outcome = "created"
            document = Document(
                id=document_id,
                source_id=request.source_id,
                locator=canonical_url,
                title=_title(canonical_url),
                media_type=version.media_type,
                created_at=retrieved_at,
                current_version_id=version_id,
            )
        else:
            if (
                existing_document.get("source_id") != request.source_id
                or existing_document.get("locator") != canonical_url
            ):
                raise ManualWebIntegrityError
            current = self.store.read_canonical(
                "versions",
                str(existing_document.get("current_version_id", "")),
            )
            if current is None:
                raise ManualWebIntegrityError
            outcome = (
                "unchanged"
                if current.get("content_hash") == digest
                else "version_reused"
                if version_preexisting
                else "version_created"
            )
            document = Document(
                **{
                    **existing_document,
                    "media_type": version.media_type,
                    "current_version_id": version_id,
                }
            )

        existing_artifact = self.store.derived_artifact_for_version(version_id)
        artifact: DerivedArtifact | None = None
        artifact_data: bytes | None = None
        derived_status = "unavailable"
        if existing_artifact is not None:
            artifact = DerivedArtifact(**existing_artifact)
            try:
                artifact_data = safe_instance_path(
                    self.store.paths.root,
                    artifact.storage_ref,
                ).read_bytes()
            except OSError:
                artifact_data = None
            if (
                artifact_data is not None
                and hashlib.sha256(artifact_data).hexdigest() == artifact.checksum
            ):
                derived_status = "reused"
            else:
                artifact = None
                artifact_data = None
        else:
            try:
                extraction = extract_web_readable_text(response.content_type, data)
            except ExtractionError:
                extraction = None
            if extraction is not None:
                artifact, artifact_data = _derived(
                    version_id,
                    extraction,
                    created_at=retrieved_at,
                )
                derived_status = "created"

        previous = self._previous_acquisition(request.source_id, canonical_url)
        exact_duplicate = existing_original is not None
        acquisition = Acquisition(
            id=f"acq_{uuid4().hex}",
            source_id=request.source_id,
            locator=canonical_url,
            observed_at=retrieved_at,
            content_hash=digest,
            outcome=outcome,
            document_id=document_id,
            version_id=version_id,
            error=None,
            schema_version=MANUAL_WEB_ACQUISITION_SCHEMA_VERSION,
            acquisition_kind=MANUAL_WEB_ACQUISITION_KIND,
            connector_instance_id=request.connector_instance_id,
            requested_url=canonical_url,
            final_url=response.final_url,
            retrieved_at=retrieved_at,
            media_type=response.content_type,
            original_id=original.id,
            http_status=response.status,
            content_encoding=response.content_encoding,
            response_size_bytes=len(data),
            authorized_origins=authorized_origins,
            replay_of_acquisition_id=(str(previous["id"]) if previous else None),
            exact_duplicate=exact_duplicate,
            derived_status=derived_status,
            derived_artifact_id=artifact.id if artifact is not None else None,
        )

        stage_parent = self.lifecycle.control_root / "transactions"
        transaction = _AtomicInstanceCommit(
            self.store,
            stage_parent,
            operation_id=operation_id,
        )
        transaction.add(original.storage_ref, data, immutable=True)
        if existing_original is None:
            self._stage_canonical(transaction, "originals", original, immutable=True)
        if not version_preexisting:
            self._stage_canonical(transaction, "versions", version, immutable=True)
        self._stage_canonical(transaction, "documents", document, immutable=False)

        edges = (
            _edge(
                "source",
                request.source_id,
                "observed",
                "acquisition",
                acquisition.id,
                created_at=retrieved_at,
            ),
            _edge(
                "connector_instance",
                request.connector_instance_id,
                "acquired_via",
                "acquisition",
                acquisition.id,
                created_at=retrieved_at,
            ),
            _edge(
                "acquisition",
                acquisition.id,
                "captured",
                "original",
                original.id,
                created_at=retrieved_at,
            ),
            _edge(
                "acquisition",
                acquisition.id,
                "matched",
                "version",
                version_id,
                created_at=retrieved_at,
            ),
            _edge(
                "original",
                original.id,
                "materialized_as",
                "version",
                version_id,
                created_at=retrieved_at,
            ),
            _edge(
                "version",
                version_id,
                "version_of",
                "document",
                document_id,
                created_at=retrieved_at,
            ),
        )
        provenance = [self._stage_edge(transaction, edge) for edge in edges]

        if artifact is not None and artifact_data is not None and derived_status == "created":
            transaction.add(artifact.storage_ref, artifact_data, immutable=True)
            transaction.add(
                f"state/derived/artifacts/{artifact.id}.json",
                _json_bytes(artifact),
                immutable=True,
            )
            derived_edge = _edge(
                "version",
                version_id,
                "extracted_to",
                "derived_artifact",
                artifact.id,
                created_at=retrieved_at,
            )
            transaction.add(
                f"state/derived/provenance/{derived_edge.id}.json",
                _json_bytes(derived_edge),
                immutable=True,
            )
            provenance.append(asdict(derived_edge))
        elif artifact is not None:
            provenance.extend(
                edge
                for edge in self.store.list_derived_provenance()
                if edge.get("from_id") == version_id
                and edge.get("to_id") == artifact.id
            )

        self._stage_canonical(transaction, "acquisitions", acquisition, immutable=True)
        effects = {
            "document_created": existing_document is None,
            "version_created": not version_preexisting,
            "original_created": existing_original is None,
            "derived_created": derived_status == "created",
            "exact_duplicate": exact_duplicate,
            "replay": previous is not None,
        }
        closed = self._terminal_operation(operation_id, acquisition, effects)
        transaction.add(
            f"state/operations/records/{closed.id}.json",
            _json_bytes(closed),
            immutable=False,
        )
        detail = self._detail_payload(
            {
                **asdict(acquisition),
                "authorized_origins": list(authorized_origins),
            },
            asdict(document),
            asdict(version),
            asdict(original),
            asdict(artifact) if artifact is not None else None,
            provenance,
        )
        transaction.commit()
        return detail, effects, closed

    def acquire(self, request: GuardedWebRequest) -> dict[str, Any]:
        operation = self.operations.start(
            MANUAL_WEB_OPERATION_KIND,
            "Acquire one guarded web Source",
            summary="Execute one explicit guarded request and commit its canonical result.",
            related={
                "connector_instance_id": request.connector_instance_id,
                "source_id": request.source_id,
            },
        )
        try:
            self.operations.append(
                operation.id,
                "manual_web.requested",
                "An explicit manual web acquisition was requested.",
                details={"network_authorization": "explicit"},
            )
            response = self.transport.fetch(request)
            self.operations.append(
                operation.id,
                "manual_web.transport_completed",
                "Guarded web transport returned one bounded response.",
                details={
                    "http_status": response.status,
                    "media_type": response.content_type,
                    "redirects": response.redirects,
                    "resources": response.resources,
                    "response_size_bytes": len(response.body),
                },
            )
            retrieved_at = utc_now()
            with (
                self.lifecycle._hold(purpose="manual-web-acquisition"),
                self.connectors.policy_commit_guard(
                    purpose="manual-web-acquisition-commit"
                ),
            ):
                authority = self.transport.current_authority(
                    request,
                    final_url=response.final_url,
                )
                detail, _effects, closed = self._plan_commit(
                    request,
                    response,
                    authority.canonical_url,
                    authority.allowed_origins,
                    retrieved_at,
                    operation.id,
                )
            return {
                **detail,
                "operation": self._operation_view(closed),
                "network_attempted": True,
                "original_verified": True,
            }
        except (WebTransportError, ManualWebAcquisitionError) as exc:
            self._close_failed(operation, exc)
            raise
        except Exception:
            error = ManualWebAcquisitionError()
            self._close_failed(operation, error)
            raise error from None

    def _summary(self, acquisition: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": MANUAL_WEB_ACQUISITION_SCHEMA_VERSION,
            "id": str(acquisition["id"]),
            "status": "completed",
            "outcome": str(acquisition["outcome"]),
            "retrieved_at": str(acquisition["retrieved_at"]),
            "requested_url": str(acquisition["requested_url"]),
            "final_url": str(acquisition["final_url"]),
            "media_type": str(acquisition["media_type"]),
            "content_hash": str(acquisition["content_hash"]),
            "response_size_bytes": int(acquisition["response_size_bytes"]),
            "document_id": str(acquisition["document_id"]),
            "version_id": str(acquisition["version_id"]),
            "original_id": str(acquisition["original_id"]),
            "replay_of_acquisition_id": acquisition.get("replay_of_acquisition_id"),
            "exact_duplicate": bool(acquisition.get("exact_duplicate")),
            "derived_status": str(acquisition["derived_status"]),
            "derived_artifact_id": acquisition.get("derived_artifact_id"),
        }

    def list(
        self,
        connector_instance_id: str,
        source_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise ValueError("manual web acquisition limit is outside the supported range")
        selected = [
            item
            for item in self.store.list_canonical("acquisitions")
            if item.get("acquisition_kind") == MANUAL_WEB_ACQUISITION_KIND
            and item.get("connector_instance_id") == connector_instance_id
            and item.get("source_id") == source_id
        ]
        selected.sort(
            key=lambda item: (str(item.get("retrieved_at", "")), str(item["id"])),
            reverse=True,
        )
        return [self._summary(item) for item in selected[:limit]]

    def get(
        self,
        connector_instance_id: str,
        source_id: str,
        acquisition_id: str,
    ) -> dict[str, Any] | None:
        acquisition = self.store.read_canonical("acquisitions", acquisition_id)
        if (
            acquisition is None
            or acquisition.get("acquisition_kind") != MANUAL_WEB_ACQUISITION_KIND
            or acquisition.get("connector_instance_id") != connector_instance_id
            or acquisition.get("source_id") != source_id
        ):
            return None
        document = self.store.read_canonical(
            "documents",
            str(acquisition["document_id"]),
        )
        version = self.store.read_canonical("versions", str(acquisition["version_id"]))
        original = self.store.read_canonical("originals", str(acquisition["original_id"]))
        if document is None or version is None or original is None:
            raise ManualWebIntegrityError
        artifact = None
        artifact_id = acquisition.get("derived_artifact_id")
        if isinstance(artifact_id, str):
            artifact = next(
                (
                    item
                    for item in self.store.list_derived_artifacts()
                    if item.get("id") == artifact_id
                ),
                None,
            )
        involved = {
            acquisition_id,
            connector_instance_id,
            source_id,
            str(document["id"]),
            str(version["id"]),
            str(original["id"]),
        }
        if isinstance(artifact_id, str):
            involved.add(artifact_id)
        provenance = [
            edge
            for edge in (
                self.store.list_canonical("provenance")
                + self.store.list_derived_provenance()
            )
            if edge.get("from_id") in involved and edge.get("to_id") in involved
        ]
        return self._detail_payload(
            acquisition,
            document,
            version,
            original,
            artifact,
            provenance,
        )


__all__ = [
    "MANUAL_WEB_ACQUISITION_KIND",
    "MANUAL_WEB_ACQUISITION_SCHEMA_VERSION",
    "MANUAL_WEB_OPERATION_KIND",
    "MANUAL_WEB_TRANSACTION_SCHEMA_VERSION",
    "ManualWebAcquisitionError",
    "ManualWebAcquisitionManager",
    "ManualWebAtomicityError",
    "ManualWebIntegrityError",
    "ManualWebResponseError",
    "recover_manual_web_transactions",
]
