"""Guarded submission and separately committed, replayable Capture acquisition."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from .atomic_commit import (
    AtomicCommitLimits,
    AtomicCommitProfile,
    AtomicInstanceCommit,
    AtomicRecoveryHandler,
    _load_transaction_manifest,
    _validate_transaction_manifest,
    recover_atomic_transactions,
)
from .capacity_admission import CapacityAdmission
from .capture_journal import MAX_RECORDS, CaptureJournal, CaptureJournalError, _read, _safe, _unique
from .capture_payloads import extract_capture_payload, validate_capture_payload
from .capture_requests import capture_scope_key
from .domain import Acquisition, Document, DocumentVersion, Original, Source
from .extractors import ExtractionError
from .hierarchy import HierarchyManager
from .index import refresh_search_index
from .review_intake import route_committed_acquisitions_locked
from .storage import utc_now
from .web_acquisition import _derived, _edge

PROFILE = AtomicCommitProfile(
    key="capture-acquisition",
    kind="capture.acquire",
    owner_id_pattern=r"capture_[0-9a-f]{64}\Z",
    limits=AtomicCommitLimits(20, 32 * 1024 * 1024, 40 * 1024 * 1024, 1, 40 * 1024 * 1024),
)
Authority = Callable[[str, str, str | None], None]


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _identity(prefix, value):
    return prefix + uuid5(NAMESPACE_URL, value).hex


class CaptureAdapter:
    def __init__(self, store, *, authorize: Authority):
        self.store = store
        self.journal = CaptureJournal(store)
        self.authorize = authorize

    def _guard(self, device, channel, reference=None):
        if self.authorize(device, channel, reference) is not None:
            raise PermissionError("Capture authority must explicitly guard the operation")

    def _admit(self, size):
        result = CapacityAdmission(self.store).check_admission(required_bytes=size)
        if not result["allowed"]:
            raise CaptureJournalError("Capture capacity admission denied: " + result["reason"])

    def submit(self, device, payload, metadata, *, channel):
        self._guard(device, channel)

        def validate(data, value):
            validate_capture_payload(data, value)
            hierarchy = HierarchyManager(self.store)
            for field in ("area_id", "project_id"):
                if field in value:
                    node = hierarchy.get_node(value[field])
                    if node is None or node["kind"] != field.removesuffix("_id"):
                        raise CaptureJournalError("Capture proposal reference is unavailable")
                    self._guard(device, channel, value[field])

        return self.journal.submit(
            device,
            payload,
            metadata,
            transport_channel=channel,
            authorize=lambda d: self._guard(d, channel),
            validate_payload=validate,
            admission=self._admit,
        )

    def _record(self, relative):
        path = self.store.paths.root / relative
        _safe(path)
        value = (
            json.loads(_read(path, 8 * 1024 * 1024), object_pairs_hook=_unique)
            if path.exists()
            else None
        )
        if value is not None and not isinstance(value, dict):
            raise CaptureJournalError("Invalid Capture referenced record")
        return value

    def _coordinates(self, submission, payload):
        scope = submission["id"]
        instance_id = self.journal._instance_id()
        source = _identity("src_", f"provelume:{instance_id}:capture:{submission['device_id']}")
        document = _identity("doc_", f"provelume:{source}:{scope}")
        digest = hashlib.sha256(payload).hexdigest()
        return dict(
            source_id=source,
            acquisition_id=_identity("acq_", f"provelume:capture:{instance_id}:{scope}"),
            document_id=document,
            version_id=_identity("ver_", f"provelume:{document}:{digest}"),
            original_id="sha256_" + digest,
            payload_sha256=digest,
        )

    def _validate_receipt(self, value, submission, payload):
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "instance_id",
            "submission_id",
            "device_id",
            "source_id",
            "acquisition_id",
            "document_id",
            "version_id",
            "original_id",
            "payload_sha256",
            "media_type",
            "received_at",
            "acquired_at",
            "status",
            "processing",
        }:
            raise CaptureJournalError("Invalid Capture acquisition receipt")
        selected = validate_capture_payload(payload, submission["metadata"])
        try:
            stamp = datetime.fromisoformat(value["acquired_at"])
            processing = value["processing"]
            valid = (
                type(value["schema_version"]) is int
                and value["schema_version"] == 1
                and value["instance_id"] == self.journal._instance_id()
                and value["submission_id"] == submission["id"]
                and value["device_id"] == submission["device_id"]
                and value["received_at"] == submission["received_at"]
                and value["media_type"] == selected.media_type
                and value["status"] == "acquired"
                and stamp.tzinfo is not None
                and stamp >= datetime.fromisoformat(submission["received_at"])
                and set(processing) == {"status", "reason", "artifact_id"}
                and processing["status"] in {"completed", "attention"}
                and (processing["status"] == "completed") is (processing["artifact_id"] is not None)
                and processing["reason"]
                == (None if processing["status"] == "completed" else "text_extraction_unavailable")
                and all(value[k] == v for k, v in self._coordinates(submission, payload).items())
            )
            if not valid:
                raise ValueError()
        except (ValueError, TypeError, KeyError) as exc:
            raise CaptureJournalError("Invalid Capture acquisition binding") from exc
        return value

    def _submission_locked(self, device, client):
        scope = capture_scope_key(device, client)
        value = self.journal._inventory().get(f"state/capture/{device}/{scope}.json")
        if value is None:
            raise CaptureJournalError("Capture submission is not committed")
        return value["receipt"], base64.b64decode(value["payload_base64"], validate=True)

    def _assure(self, receipt, submission, payload, *, candidates=None):
        self._validate_receipt(receipt, submission, payload)
        candidates = candidates or {}

        def read(relative, maximum):
            return _read(candidates.get(relative, self.store.paths.root / relative), maximum)

        def record(relative):
            if relative in candidates:
                return json.loads(read(relative, 8 * 1024 * 1024), object_pairs_hook=_unique)
            return self._record(relative)

        acquisition = record(f"knowledge/acquisitions/{receipt['acquisition_id']}.json")
        version = record(f"knowledge/versions/{receipt['version_id']}.json")
        original = record(f"knowledge/originals/{receipt['original_id']}.json")
        source = record(f"knowledge/sources/{receipt['source_id']}.json")
        document = record(f"knowledge/documents/{receipt['document_id']}.json")
        if (
            acquisition is None
            or version is None
            or original is None
            or source is None
            or document is None
            or source.get("id") != receipt["source_id"]
            or source.get("kind") != "capture"
            or document.get("source_id") != receipt["source_id"]
            or document.get("locator") != submission["id"]
            or acquisition.get("id") != receipt["acquisition_id"]
            or type(acquisition.get("schema_version")) is not int
            or acquisition["schema_version"] != 1
            or version.get("id") != receipt["version_id"]
            or original.get("id") != receipt["original_id"]
            or any(
                acquisition.get(k) != receipt[k]
                for k in ("source_id", "document_id", "version_id", "original_id", "media_type")
            )
            or acquisition.get("locator") != submission["id"]
            or acquisition.get("content_hash") != receipt["payload_sha256"]
            or acquisition.get("acquisition_kind") != "capture"
            or acquisition.get("observed_at") != receipt["acquired_at"]
            or version.get("document_id") != receipt["document_id"]
            or version.get("original_id") != receipt["original_id"]
            or version.get("content_hash") != receipt["payload_sha256"]
            or original.get("storage_ref")
            != f"originals/sha256/{receipt['payload_sha256'][:2]}/{receipt['payload_sha256']}"
            or original.get("sha256") != receipt["payload_sha256"]
            or original.get("size_bytes") != len(payload)
            or read(original["storage_ref"], 25 * 1024 * 1024) != payload
        ):
            raise CaptureJournalError("Capture acquired Original or provenance is unavailable")
        for origin, oid, relation, target, tid in (
            ("source", receipt["source_id"], "observed", "acquisition", receipt["acquisition_id"]),
            (
                "capture_submission",
                submission["id"],
                "delivered",
                "acquisition",
                receipt["acquisition_id"],
            ),
            (
                "acquisition",
                receipt["acquisition_id"],
                "captured",
                "original",
                receipt["original_id"],
            ),
            (
                "original",
                receipt["original_id"],
                "materialized_as",
                "version",
                receipt["version_id"],
            ),
            ("version", receipt["version_id"], "version_of", "document", receipt["document_id"]),
        ):
            expected = asdict(
                _edge(origin, oid, relation, target, tid, created_at=receipt["acquired_at"])
            )
            if record(f"knowledge/provenance/{expected['id']}.json") != expected:
                raise CaptureJournalError("Capture provenance is unavailable")
        artifact_id = receipt["processing"]["artifact_id"]
        if artifact_id is not None:
            expected_edge = asdict(
                _edge(
                    "version",
                    receipt["version_id"],
                    "extracted_to",
                    "derived_artifact",
                    artifact_id,
                    created_at=receipt["acquired_at"],
                )
            )
            if record(f"state/derived/provenance/{expected_edge['id']}.json") != expected_edge:
                raise CaptureJournalError("Capture derived provenance is unavailable")
            artifact = record(f"state/derived/artifacts/{artifact_id}.json")
            expected_ref = f"state/derived/text/{artifact_id}.txt"
            if (
                artifact is None
                or artifact.get("id") != artifact_id
                or artifact.get("version_id") != receipt["version_id"]
                or artifact.get("storage_ref") != expected_ref
                or hashlib.sha256(read(expected_ref, 2 * 1024 * 1024)).hexdigest()
                != artifact.get("checksum")
                or acquisition.get("derived_artifact_id") != artifact_id
            ):
                raise CaptureJournalError("Capture derived artifact is unavailable")
        return receipt

    def detail(self, device, client, *, channel):
        submission = self.journal.lookup(
            device, client, authorize=lambda d: self._guard(d, channel)
        )
        if submission is None:
            return None
        if submission["metadata"]["channel"] != channel:
            raise PermissionError("Capture channel does not own this receipt")
        value = self.journal._inventory()[f"state/capture/{device}/{submission['id']}.json"]
        payload = base64.b64decode(value["payload_base64"], validate=True)
        acquired = self._record(f"state/capture-processing/{submission['id']}.json")
        if acquired is not None:
            self._assure(acquired, submission, payload)
        self.journal._read_ready()
        self._guard(device, channel)
        return {"submission": submission, "acquisition": acquired}

    def process(self, device, client, *, channel):
        self._guard(device, channel)
        with self.journal.lifecycle._hold(purpose="capture-acquire"):
            self._guard(device, channel)
            submission, payload = self._submission_locked(device, client)
            if submission["metadata"]["channel"] != channel:
                raise PermissionError("Capture channel does not own this submission")
            relative = f"state/capture-processing/{submission['id']}.json"
            receipt = self._record(relative)
            if receipt is not None:
                self._assure(receipt, submission, payload)
            else:
                receipt = self._acquire_locked(submission, payload, relative)
            acquisition = self._record(f"knowledge/acquisitions/{receipt['acquisition_id']}.json")
            routing = route_committed_acquisitions_locked(self.store, [acquisition])
        # Search projection follows canonical commit; failure never rolls it back.
        try:
            refresh_search_index(self.store, [receipt["document_id"]])
            index = "refreshed"
        except (OSError, ValueError, RuntimeError):
            index = "attention"
        return {"receipt": receipt, "review_routing": routing, "search_index": index}

    def _acquire_locked(self, submission, payload, relative):
        selected = validate_capture_payload(payload, submission["metadata"])
        self._admit(len(payload) * 3 + 4 * 1024 * 1024)
        now = utc_now()
        ids = self._coordinates(submission, payload)
        digest = ids["payload_sha256"]
        writes = {}

        def canonical(kind, value):
            row = asdict(value)
            writes[f"knowledge/{kind}/{value.id}.json"] = _json(row)

        source = self._record(f"knowledge/sources/{ids['source_id']}.json")
        if source is None:
            canonical(
                "sources",
                Source(ids["source_id"], "capture", "Capture " + submission["device_id"], now),
            )
        elif source.get("id") != ids["source_id"] or source.get("kind") != "capture":
            raise CaptureJournalError("Capture Source identity conflict")
        original = self._record(f"knowledge/originals/{ids['original_id']}.json")
        storage_ref = f"originals/sha256/{digest[:2]}/{digest}"
        if original is None:
            canonical(
                "originals", Original(ids["original_id"], digest, len(payload), storage_ref, now)
            )
        elif (
            original.get("sha256") != digest
            or original.get("storage_ref") != storage_ref
            or original.get("size_bytes") != len(payload)
        ):
            raise CaptureJournalError("Capture Original identity conflict")
        writes[storage_ref] = payload
        canonical(
            "documents",
            Document(
                ids["document_id"],
                ids["source_id"],
                submission["id"],
                selected.filename,
                selected.media_type,
                now,
                ids["version_id"],
            ),
        )
        canonical(
            "versions",
            DocumentVersion(
                ids["version_id"],
                ids["document_id"],
                1,
                digest,
                ids["original_id"],
                selected.media_type,
                len(payload),
                now,
            ),
        )
        processing = dict(
            status="attention", reason="text_extraction_unavailable", artifact_id=None
        )
        try:
            extraction = extract_capture_payload(payload, selected)
            artifact, data = _derived(ids["version_id"], extraction, created_at=now)
            writes[artifact.storage_ref] = data
            writes[f"state/derived/artifacts/{artifact.id}.json"] = _json(asdict(artifact))
            edge = _edge(
                "version",
                ids["version_id"],
                "extracted_to",
                "derived_artifact",
                artifact.id,
                created_at=now,
            )
            writes[f"state/derived/provenance/{edge.id}.json"] = _json(asdict(edge))
            processing = dict(status="completed", reason=None, artifact_id=artifact.id)
        except ExtractionError:
            pass
        canonical(
            "acquisitions",
            Acquisition(
                id=ids["acquisition_id"],
                source_id=ids["source_id"],
                locator=submission["id"],
                observed_at=now,
                content_hash=digest,
                outcome="created",
                document_id=ids["document_id"],
                version_id=ids["version_id"],
                acquisition_kind="capture",
                media_type=selected.media_type,
                original_id=ids["original_id"],
                response_size_bytes=len(payload),
                derived_status="created" if processing["status"] == "completed" else "unavailable",
                derived_artifact_id=processing["artifact_id"],
            ),
        )
        for origin, origin_id, relation, target, target_id in (
            ("source", ids["source_id"], "observed", "acquisition", ids["acquisition_id"]),
            (
                "capture_submission",
                submission["id"],
                "delivered",
                "acquisition",
                ids["acquisition_id"],
            ),
            ("acquisition", ids["acquisition_id"], "captured", "original", ids["original_id"]),
            ("original", ids["original_id"], "materialized_as", "version", ids["version_id"]),
            ("version", ids["version_id"], "version_of", "document", ids["document_id"]),
        ):
            canonical(
                "provenance", _edge(origin, origin_id, relation, target, target_id, created_at=now)
            )
        receipt = dict(
            schema_version=1,
            instance_id=self.journal._instance_id(),
            submission_id=submission["id"],
            device_id=submission["device_id"],
            **ids,
            media_type=selected.media_type,
            received_at=submission["received_at"],
            acquired_at=now,
            status="acquired",
            processing=processing,
        )
        self._validate_receipt(receipt, submission, payload)
        writes[relative] = _json(receipt)
        _allow_paths(receipt, set(writes))
        transaction = AtomicInstanceCommit(
            self.store,
            self.journal.lifecycle.control_root / "transactions",
            profile=PROFILE,
            owner_id=submission["id"],
        )
        for path, data in writes.items():
            transaction.add(path, data, immutable=True)
        transaction.commit()
        return self._assure(receipt, submission, payload)


def _allow_paths(receipt, paths):
    digest = receipt["payload_sha256"]
    scope = receipt["submission_id"]
    allowed = {f"state/capture-processing/{scope}.json", f"originals/sha256/{digest[:2]}/{digest}"}
    for kind, key in (
        ("sources", "source_id"),
        ("originals", "original_id"),
        ("documents", "document_id"),
        ("versions", "version_id"),
        ("acquisitions", "acquisition_id"),
    ):
        allowed.add(f"knowledge/{kind}/{receipt[key]}.json")
    for origin, oid, relation, target, tid in (
        ("source", receipt["source_id"], "observed", "acquisition", receipt["acquisition_id"]),
        ("capture_submission", scope, "delivered", "acquisition", receipt["acquisition_id"]),
        ("acquisition", receipt["acquisition_id"], "captured", "original", receipt["original_id"]),
        ("original", receipt["original_id"], "materialized_as", "version", receipt["version_id"]),
        ("version", receipt["version_id"], "version_of", "document", receipt["document_id"]),
    ):
        edge = _edge(origin, oid, relation, target, tid, created_at=receipt["acquired_at"])
        allowed.add(f"knowledge/provenance/{edge.id}.json")
    artifact = receipt["processing"]["artifact_id"]
    if artifact is not None:
        if not isinstance(artifact, str) or not re.fullmatch(r"derived_[0-9a-f]{32}", artifact):
            raise CaptureJournalError("Invalid Capture derived identity")
        allowed |= {
            f"state/derived/text/{artifact}.txt",
            f"state/derived/artifacts/{artifact}.json",
        }
        edge = _edge(
            "version",
            receipt["version_id"],
            "extracted_to",
            "derived_artifact",
            artifact,
            created_at=receipt["acquired_at"],
        )
        allowed.add(f"state/derived/provenance/{edge.id}.json")
    if not paths <= allowed:
        raise CaptureJournalError("Capture acquisition outside domain allowlist")
    return allowed


def recover_capture_acquisitions_locked(store):
    adapter = CaptureAdapter(store, authorize=lambda *a: None)
    root = adapter.journal.lifecycle.control_root / "transactions"
    _safe(root)
    if not root.exists():
        return None
    for index, stage in enumerate(root.glob("capture-acquisition-*")):
        if index >= MAX_RECORDS or not PROFILE.transaction_pattern.fullmatch(stage.name):
            raise CaptureJournalError("Invalid Capture acquisition recovery inventory")
        manifest = _load_transaction_manifest(
            stage, max_entries=PROFILE.limits.max_entries, error_type=CaptureJournalError
        )
        if manifest is None:
            continue
        _validate_transaction_manifest(
            store, stage, manifest, profile=PROFILE, error_type=CaptureJournalError
        )
        scope = manifest["operation_id"]
        paths = set()
        candidates = {}
        value = None
        for entry in manifest["entries"]:
            if entry["immutable"] is not True or entry["had_preimage"] is not False:
                raise CaptureJournalError(
                    "Capture acquisition cannot overwrite existing domain state"
                )
            paths.add(entry["relative"])
            candidate = stage / entry["candidate_ref"]
            if candidate.exists():
                candidates[entry["relative"]] = candidate
            if entry["relative"] == f"state/capture-processing/{scope}.json":
                path = stage / entry["candidate_ref"]
                if not path.exists():
                    path = store.paths.root / entry["relative"]
                value = json.loads(_read(path, 8 * 1024 * 1024), object_pairs_hook=_unique)
        if value is None:
            raise CaptureJournalError("Capture recovery requires its acquisition receipt")
        device = value["device_id"]
        found = next(
            (
                v
                for v in adapter.journal._inventory().values()
                if v["receipt"]["id"] == scope and v["receipt"]["device_id"] == device
            ),
            None,
        )
        if found is None:
            raise CaptureJournalError("Capture recovery submission is unavailable")
        adapter._validate_receipt(
            value, found["receipt"], base64.b64decode(found["payload_base64"], validate=True)
        )
        _allow_paths(value, paths)
        adapter._assure(
            value,
            found["receipt"],
            base64.b64decode(found["payload_base64"], validate=True),
            candidates=candidates,
        )
    return recover_atomic_transactions(
        store,
        adapter.journal.lifecycle.control_root,
        handlers=(AtomicRecoveryHandler(profile=PROFILE),),
    )
