from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from .instance_lifecycle import InstanceLifecycleBusy, InstanceLifecycleManager
from .paths import safe_instance_path
from .qualification_contract import (
    DECISION_ACTIONS,
    DECISION_RESULT_STATES,
    EPISTEMIC_STATES,
    FINDING_TYPES,
    QUALIFICATION_ALGORITHM_ID,
    QUALIFICATION_ALGORITHM_VERSION,
    QUALIFICATION_SCHEMA_VERSION,
    WORKFLOW_STATES,
    QualificationError,
    QualificationLimits,
    normalise_actor_id,
    normalise_decision_payload,
    normalise_source_ids,
    qualification_matrix,
    sanitise_reason,
    validate_finding_id,
)
from .storage import InstanceStore, utc_now

QUALIFICATION_STATE_KIND = "cross-source-qualification"
QUALIFICATION_DECISION_KIND = "qualification-decisions"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{_digest(value)}"


def _instant(value: str) -> datetime:
    selected = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return selected.astimezone(UTC)


def _source_profile(
    store: InstanceStore,
    source: Mapping[str, Any],
) -> tuple[str, ...]:
    if source.get("kind") == "filesystem":
        return ("filesystem-document-v1",)
    if source.get("kind") == "email":
        return ("local-email-v1",)
    if source.get("kind") != "connector":
        return ()
    source_kind = source.get("source_kind")
    if source_kind == "gmail":
        return ("gmail-synthetic-v1",)
    if source_kind == "drive":
        return ("drive-synthetic-v1",)
    if source_kind != "transcript":
        return ()
    config = (store.read_config().get("transcript_sources") or {}).get(source.get("id"))
    profile = config.get("profile") if isinstance(config, Mapping) else None
    if profile == "srt-v1":
        return ("transcript-srt-v1",)
    if profile == "webvtt-v1":
        return ("transcript-webvtt-v1",)
    return ()


class QualificationManager:
    """Deterministic derived findings and append-only human correction decisions."""

    def __init__(self, store: InstanceStore, *, recover: bool = True):
        self.store = store
        self.root = store.paths.state / QUALIFICATION_STATE_KIND
        self.jobs_root = self.root / "jobs"
        self.results_root = self.root / "results"
        self.source_root = self.root / "sources"
        if recover:
            self._recover_expired_leases()
            self._reconcile_source_checkpoints()

    def matrix(self) -> dict[str, Any]:
        return qualification_matrix()

    @staticmethod
    def limits() -> dict[str, Any]:
        return {
            "defaults": QualificationLimits().as_record(),
            "ceilings": QualificationLimits.ceilings(),
        }

    def _hold(self, purpose: str):
        return InstanceLifecycleManager(self.store)._hold(purpose=purpose)

    def _job_path(self, job_id: str) -> Path:
        if not job_id.startswith("qualification_job_"):
            raise QualificationError("qualification_not_found", "qualification job was not found")
        return self.jobs_root / f"{job_id}.json"

    def _source_path(self, source_id: str) -> Path:
        return self.source_root / f"{source_id}.json"

    def _result_path(self, job_id: str) -> Path:
        return self.results_root / job_id / "manifest.json"

    def _read_json(self, path: Path, *, maximum: int = 64 * 1024 * 1024) -> dict[str, Any]:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise QualificationError(
                "qualification_internal_error", "qualification state is unavailable"
            ) from exc
        if len(data) > maximum:
            raise QualificationError(
                "qualification_output_limit_exceeded", "qualification state exceeds its limit"
            )
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise QualificationError(
                "qualification_internal_error", "qualification state is invalid"
            ) from exc
        if not isinstance(value, dict):
            raise QualificationError(
                "qualification_internal_error", "qualification state is invalid"
            )
        return value

    def _write_json(self, path: Path, value: Mapping[str, Any]) -> None:
        self.store._atomic_json(path, dict(value))

    def _source_cursor(self, source_id: str) -> dict[str, Any]:
        path = self._source_path(source_id)
        if path.is_file():
            value = self._read_json(path, maximum=1024 * 1024)
            if (
                value.get("schema_version") == QUALIFICATION_SCHEMA_VERSION
                and value.get("source_id") == source_id
                and type(value.get("revision")) is int
                and int(value["revision"]) >= 0
                and isinstance(value.get("resync_required"), bool)
            ):
                return value
            raise QualificationError(
                "qualification_internal_error", "qualification Source checkpoint is invalid"
            )
        return {
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "source_id": source_id,
            "revision": 0,
            "last_job_id": None,
            "last_snapshot_fingerprint": None,
            "last_success_at": None,
            "resync_required": False,
        }

    def source_checkpoint(self, source_id: str) -> dict[str, Any]:
        if self.store.read_canonical("sources", source_id) is None:
            raise QualificationError(
                "qualification_invalid_source", "qualification Source was not found"
            )
        return self._source_cursor(source_id)

    def reset_source(self, source_id: str) -> dict[str, Any]:
        if self.store.read_canonical("sources", source_id) is None:
            raise QualificationError(
                "qualification_invalid_source", "qualification Source was not found"
            )
        try:
            with self._hold("qualification-source-resync"):
                current = self._source_cursor(source_id)
                result = {
                    **current,
                    "revision": int(current["revision"]) + 1,
                    "resync_required": True,
                }
                self._write_json(self._source_path(source_id), result)
                return result
        except InstanceLifecycleBusy as exc:
            raise QualificationError(
                "qualification_conflict", "another Instance operation is active"
            ) from exc

    def _source_snapshot(self, source_id: str) -> dict[str, Any]:
        source = self.store.read_canonical("sources", source_id)
        if source is None or source.get("lifecycle_state") == "removed":
            raise QualificationError(
                "qualification_invalid_source", "qualification Source is missing or removed"
            )
        config = self.store.read_config()
        configuration: Any = None
        if source.get("kind") == "email":
            configuration = (config.get("email_sources") or {}).get(source_id)
        elif source.get("source_kind") == "transcript":
            configuration = (config.get("transcript_sources") or {}).get(source_id)
        elif source.get("kind") == "filesystem":
            configuration = (config.get("folder_sources") or {}).get(source_id)
        elif source.get("kind") == "connector":
            configuration = {
                "source": source,
                "connector": self.store.read_canonical(
                    "connector-instances", str(source.get("connector_instance_id"))
                ),
            }
        cursor = self._source_cursor(source_id)
        profiles = _source_profile(self.store, source)
        return {
            "source_id": source_id,
            "source_fingerprint": _digest(source),
            "configuration_fingerprint": _digest(configuration),
            "cursor_revision": cursor["revision"],
            "profiles": list(profiles),
        }

    def _artifact_rows(self, version_id: str, *, maximum: int) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for artifact in self.store.list_derived_artifacts():
            if artifact.get("version_id") != version_id:
                continue
            payload_fingerprint = "unavailable"
            try:
                path = safe_instance_path(
                    self.store.paths.root, str(artifact.get("storage_ref", ""))
                )
                total = 0
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        total += len(chunk)
                        if total > maximum:
                            payload_fingerprint = "limit-exceeded"
                            break
                        digest.update(chunk)
                    else:
                        payload_fingerprint = f"sha256:{digest.hexdigest()}:{total}"
            except (OSError, ValueError):
                pass
            rows.append(
                {
                    "id": str(artifact.get("id")),
                    "kind": str(artifact.get("kind")),
                    "checksum": str(artifact.get("checksum")),
                    "storage_ref_digest": hashlib.sha256(
                        str(artifact.get("storage_ref", "")).encode("utf-8")
                    ).hexdigest(),
                    "payload_fingerprint": payload_fingerprint,
                }
            )
        return sorted(rows, key=lambda item: (item["kind"], item["id"]))

    def _object_rows(
        self, source_ids: Sequence[str], limits: QualificationLimits
    ) -> list[dict[str, Any]]:
        versions = {item["id"]: item for item in self.store.list_canonical("versions")}
        originals = {item["id"]: item for item in self.store.list_canonical("originals")}
        acquisitions_by_version: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in self.store.list_canonical("acquisitions"):
            if item.get("source_id") in source_ids:
                acquisitions_by_version[str(item.get("version_id"))].append(item)
        rows: list[dict[str, Any]] = []
        selected_documents = [
            item
            for item in self.store.list_canonical("documents")
            if item.get("source_id") in source_ids
        ]
        if len(selected_documents) > limits.max_objects:
            raise QualificationError(
                "qualification_limit_exceeded", "qualification object limit was exceeded"
            )
        for document in sorted(selected_documents, key=lambda item: str(item.get("id"))):
            version = versions.get(document.get("current_version_id"))
            if version is None:
                row = {
                    "kind": "document-version",
                    "id": str(document.get("current_version_id")),
                    "document_id": str(document.get("id")),
                    "source_id": str(document.get("source_id")),
                    "original_id": None,
                    "content_sha256": None,
                    "size_bytes": None,
                    "media_type": str(document.get("media_type", "unknown")),
                    "acquisition_times": [],
                    "artifacts": [],
                    "fingerprint": _digest({"document": document, "version": None}),
                }
                rows.append(row)
                continue
            original = originals.get(version.get("original_id"))
            acquisitions = acquisitions_by_version.get(str(version.get("id")), [])
            artifacts = self._artifact_rows(str(version["id"]), maximum=limits.max_temporary_bytes)
            row = {
                "kind": "document-version",
                "id": str(version["id"]),
                "document_id": str(document["id"]),
                "source_id": str(document["source_id"]),
                "original_id": version.get("original_id"),
                "content_sha256": version.get("content_hash"),
                "original_sha256": original.get("sha256") if original else None,
                "size_bytes": version.get("size_bytes"),
                "original_size_bytes": original.get("size_bytes") if original else None,
                "media_type": str(version.get("media_type", document.get("media_type", "unknown"))),
                "acquired_at": version.get("acquired_at"),
                "acquisition_times": [
                    {
                        "id": str(item.get("id")),
                        "observed_at": item.get("observed_at"),
                        "retrieved_at": item.get("retrieved_at"),
                    }
                    for item in sorted(acquisitions, key=lambda item: str(item.get("id")))
                ],
                "artifacts": artifacts,
                "fingerprint": _digest(
                    {
                        "document": document,
                        "version": version,
                        "original": original,
                        "acquisitions": acquisitions,
                        "artifacts": artifacts,
                    }
                ),
            }
            rows.append(row)
        return rows

    def _snapshot(self, source_ids: Sequence[str], limits: QualificationLimits) -> dict[str, Any]:
        sources = [self._source_snapshot(source_id) for source_id in source_ids]
        objects = self._object_rows(source_ids, limits)
        ocr_sources = {
            str(row["source_id"])
            for row in objects
            if any(
                artifact.get("kind") == "ocr_document_bundle"
                for artifact in row.get("artifacts", [])
            )
        }
        for source in sources:
            if source["source_id"] in ocr_sources:
                source["profiles"] = sorted({*source.get("profiles", []), "ocr-document-bundle-v1"})
        value = {
            "sources": sources,
            "objects": objects,
            "algorithm": {
                "id": QUALIFICATION_ALGORITHM_ID,
                "version": QUALIFICATION_ALGORITHM_VERSION,
            },
            "limits": limits.as_record(),
        }
        return {**value, "fingerprint": _digest(value)}

    def queue(
        self,
        source_ids: Sequence[str],
        *,
        limits: QualificationLimits | None = None,
        request_key: str | None = None,
    ) -> dict[str, Any]:
        selected_limits = limits or QualificationLimits()
        selected_sources = normalise_source_ids(source_ids, selected_limits)
        if request_key is not None and len(request_key) > 200:
            raise QualificationError(
                "qualification_limit_exceeded", "qualification request key is too long"
            )
        try:
            with self._hold("qualification-queue"):
                snapshot = self._snapshot(selected_sources, selected_limits)
                identity = {
                    "source_ids": selected_sources,
                    "snapshot_fingerprint": snapshot["fingerprint"],
                    "algorithm": snapshot["algorithm"],
                    "limits": selected_limits.as_record(),
                    "request_key_sha256": (
                        hashlib.sha256(request_key.encode("utf-8")).hexdigest()
                        if request_key
                        else None
                    ),
                }
                job_id = _stable_id("qualification_job", identity)
                existing = self.get_job(job_id, public=False)
                if existing is not None:
                    return {"job": self._public_job(existing), "replayed": True}
                now = utc_now()
                job = {
                    "schema_version": QUALIFICATION_SCHEMA_VERSION,
                    "id": job_id,
                    "kind": "cross-source.qualification",
                    "status": "queued",
                    "source_ids": list(selected_sources),
                    "snapshot": snapshot,
                    "attempt": 0,
                    "max_attempts": selected_limits.max_attempts,
                    "lease": None,
                    "cancel_requested": False,
                    "checkpoint": {"sequence": 0, "phase": "prepared", "cursor": 0},
                    "progress": {"processed": 0, "skipped": 0, "errors": 0},
                    "error_code": None,
                    "result_ref": None,
                    "created_at": now,
                    "updated_at": now,
                }
                self._write_json(self._job_path(job_id), job)
                return {"job": self._public_job(job), "replayed": False}
        except InstanceLifecycleBusy as exc:
            raise QualificationError(
                "qualification_conflict", "another Instance operation is active"
            ) from exc

    def _public_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value for key, value in job.items() if key not in {"snapshot", "cancel_requested"}
        } | {
            "lease": {
                "present": isinstance(job.get("lease"), Mapping),
                "owner": (
                    job["lease"].get("owner") if isinstance(job.get("lease"), Mapping) else None
                ),
                "expires_at": (
                    job["lease"].get("expires_at")
                    if isinstance(job.get("lease"), Mapping)
                    else None
                ),
            },
            "snapshot_fingerprint": job.get("snapshot", {}).get("fingerprint"),
            "limits": job.get("snapshot", {}).get("limits"),
            "algorithm": job.get("snapshot", {}).get("algorithm"),
        }

    def get_job(self, job_id: str, *, public: bool = True) -> dict[str, Any] | None:
        path = self._job_path(job_id)
        if not path.is_file():
            return None
        value = self._read_json(path)
        return self._public_job(value) if public else value

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise QualificationError(
                "qualification_limit_exceeded", "qualification job list limit is invalid"
            )
        if not self.jobs_root.exists():
            return []
        rows = [self._read_json(path) for path in self.jobs_root.glob("*.json")]
        rows.sort(key=lambda item: (str(item.get("created_at")), str(item.get("id"))), reverse=True)
        return [self._public_job(item) for item in rows[:limit]]

    def cancel(self, job_id: str) -> dict[str, Any]:
        try:
            with self._hold("qualification-cancel"):
                job = self.get_job(job_id, public=False)
                if job is None:
                    raise QualificationError(
                        "qualification_not_found", "qualification job was not found"
                    )
                if job["status"] == "queued":
                    job.update(
                        {
                            "status": "cancelled",
                            "error_code": "qualification_cancelled",
                            "updated_at": utc_now(),
                        }
                    )
                elif job["status"] == "running":
                    job["cancel_requested"] = True
                    job["updated_at"] = utc_now()
                self._write_json(self._job_path(job_id), job)
                return self._public_job(job)
        except InstanceLifecycleBusy as exc:
            raise QualificationError(
                "qualification_conflict", "another Instance operation is active"
            ) from exc

    def retry(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id, public=False)
        if job is None:
            raise QualificationError("qualification_not_found", "qualification job was not found")
        if job["status"] not in {"failed", "cancelled"}:
            raise QualificationError(
                "qualification_conflict", "only a failed or cancelled qualification can retry"
            )
        limits = QualificationLimits.from_mapping(job["snapshot"]["limits"])
        current = self._snapshot(job["source_ids"], limits)
        if current["fingerprint"] != job["snapshot"]["fingerprint"]:
            return self.queue(job["source_ids"], limits=limits)
        if int(job["attempt"]) >= int(job["max_attempts"]):
            raise QualificationError(
                "qualification_retry_exhausted", "qualification retry bound was exhausted"
            )
        try:
            with self._hold("qualification-retry"):
                job = self.get_job(job_id, public=False)
                assert job is not None
                job.update(
                    {
                        "status": "queued",
                        "lease": None,
                        "cancel_requested": False,
                        "error_code": None,
                        "updated_at": utc_now(),
                    }
                )
                self._write_json(self._job_path(job_id), job)
                return {"job": self._public_job(job), "replayed": True}
        except InstanceLifecycleBusy as exc:
            raise QualificationError(
                "qualification_conflict", "another Instance operation is active"
            ) from exc

    def _start(self, job_id: str) -> tuple[dict[str, Any], str]:
        try:
            with self._hold("qualification-start"):
                job = self.get_job(job_id, public=False)
                if job is None:
                    raise QualificationError(
                        "qualification_not_found", "qualification job was not found"
                    )
                if job["status"] == "succeeded":
                    return job, ""
                if job["status"] != "queued":
                    raise QualificationError(
                        "qualification_conflict", "qualification job is not queued"
                    )
                attempt = int(job["attempt"]) + 1
                if attempt > int(job["max_attempts"]):
                    raise QualificationError(
                        "qualification_retry_exhausted", "qualification retry bound was exhausted"
                    )
                token = f"qualification_lease_{uuid4().hex}"
                now = datetime.now(UTC)
                job.update(
                    {
                        "status": "running",
                        "attempt": attempt,
                        "lease": {
                            "token": token,
                            "owner": "local-service",
                            "heartbeat_at": now.isoformat(),
                            "expires_at": (
                                now
                                + timedelta(seconds=int(job["snapshot"]["limits"]["lease_seconds"]))
                            ).isoformat(),
                        },
                        "checkpoint": {
                            "sequence": int(job["checkpoint"]["sequence"]) + 1,
                            "phase": "executing",
                            "cursor": 0,
                        },
                        "updated_at": now.isoformat(),
                    }
                )
                self._write_json(self._job_path(job_id), job)
                return job, token
        except InstanceLifecycleBusy as exc:
            raise QualificationError(
                "qualification_conflict", "another Instance operation is active"
            ) from exc

    def _checkpoint(self, job_id: str, token: str, cursor: int) -> None:
        job = self.get_job(job_id, public=False)
        if job is None or not isinstance(job.get("lease"), Mapping):
            raise QualificationError(
                "qualification_lease_expired", "qualification lease is unavailable"
            )
        if job["lease"].get("token") != token:
            raise QualificationError(
                "qualification_lease_expired", "qualification lease ownership changed"
            )
        if job.get("cancel_requested"):
            raise QualificationError("qualification_cancelled", "qualification was cancelled")
        limits = QualificationLimits.from_mapping(job["snapshot"]["limits"])
        now = datetime.now(UTC)
        job["lease"] = {
            **job["lease"],
            "heartbeat_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=limits.lease_seconds)).isoformat(),
        }
        job["checkpoint"] = {
            "sequence": int(job["checkpoint"]["sequence"]) + 1,
            "phase": "executing",
            "cursor": cursor,
        }
        job["progress"] = {"processed": cursor, "skipped": 0, "errors": 0}
        job["updated_at"] = now.isoformat()
        self._write_json(self._job_path(job_id), job)

    @staticmethod
    def _reference(row: Mapping[str, Any]) -> dict[str, str]:
        return {
            "kind": str(row["kind"]),
            "id": str(row["id"]),
            "source_id": str(row["source_id"]),
            "fingerprint": str(row["fingerprint"]),
        }

    def _finding(
        self,
        *,
        finding_type: str,
        rows: Sequence[Mapping[str, Any]],
        evidence: Mapping[str, Any],
        rule_id: str,
        epistemic_state: str,
        confidence_kind: str,
        confidence_value: float | None,
        job: Mapping[str, Any],
    ) -> dict[str, Any]:
        if finding_type not in FINDING_TYPES or epistemic_state not in EPISTEMIC_STATES:
            raise QualificationError(
                "qualification_internal_error", "qualification rule emitted an unknown value"
            )
        limits = QualificationLimits.from_mapping(job["snapshot"]["limits"])
        evidence_value = dict(evidence)
        if len(_json_bytes(evidence_value)) > limits.max_evidence_bytes:
            raise QualificationError(
                "qualification_output_limit_exceeded", "qualification evidence exceeds its limit"
            )
        references = sorted(
            [self._reference(row) for row in rows],
            key=lambda item: (item["source_id"], item["kind"], item["id"]),
        )
        source_ids = sorted({item["source_id"] for item in references})
        source_snapshot_fingerprints = {
            str(source["source_id"]): _digest(source)
            for source in job["snapshot"]["sources"]
            if source.get("source_id") in source_ids
        }
        identity = {
            "finding_type": finding_type,
            "finding_version": 1,
            "source_ids": source_ids,
            "object_refs": references,
            "evidence": evidence_value,
            "rule": {"id": rule_id, "version": "1.0.0"},
            "algorithm": job["snapshot"]["algorithm"],
        }
        return {
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "id": _stable_id("finding", identity),
            **identity,
            "epistemic_state": epistemic_state,
            "confidence": {"kind": confidence_kind, "value": confidence_value},
            "workflow_state": "open",
            "provenance": {
                "qualification_job_id": job["id"],
                "snapshot_fingerprint": job["snapshot"]["fingerprint"],
                "source_snapshot_fingerprints": source_snapshot_fingerprints,
                "network_used": False,
                "provider_mutation": False,
                "canonical_source_mutation": False,
                "automatic_merge": False,
            },
            "observed_at": job["updated_at"],
            "limits": limits.as_record(),
        }

    def _participant_hashes(self, source_ids: Sequence[str], limit: int) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {source_id: set() for source_id in source_ids}
        # Email address values and transcript speaker labels are read only in memory. Only a
        # normalized SHA-256 observation is returned to the finding provider.
        from .email_bundle import EMAIL_BUNDLE_KIND
        from .transcript_jobs import TranscriptJobManager

        email_manifests: list[dict[str, Any]] = []
        for artifact in self.store.list_derived_artifacts():
            if artifact.get("kind") != EMAIL_BUNDLE_KIND:
                continue
            try:
                path = safe_instance_path(self.store.paths.root, str(artifact.get("storage_ref")))
                data = path.read_bytes()
                if len(data) > 16 * 1024 * 1024:
                    continue
                if hashlib.sha256(data).hexdigest() != artifact.get("checksum"):
                    continue
                manifest = json.loads(data.decode("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                continue
            if isinstance(manifest, dict):
                email_manifests.append(manifest)
            if len(email_manifests) >= min(limit, 500):
                break
        for message in email_manifests:
            source_id = str(message.get("message", {}).get("source_id"))
            if source_id not in result:
                continue
            envelope = message.get("envelope")
            stack = [envelope]
            while stack:
                value = stack.pop()
                if isinstance(value, Mapping):
                    username = value.get("username")
                    domain = value.get("domain")
                    if (
                        isinstance(username, str)
                        and isinstance(domain, str)
                        and username.strip()
                        and domain.strip()
                    ):
                        normalized = f"{username.strip()}@{domain.strip()}".casefold()
                        result[source_id].add(
                            hashlib.sha256(f"participant\0{normalized}".encode()).hexdigest()
                        )
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
                elif isinstance(value, str) and "@" in value:
                    normalized = value.strip().casefold()
                    result[source_id].add(
                        hashlib.sha256(f"participant\0{normalized}".encode()).hexdigest()
                    )
        transcripts = TranscriptJobManager(self.store)
        for revision in transcripts.list_revisions(limit=min(limit, 500)):
            source_id = str(revision.get("source_id"))
            if source_id not in result:
                continue
            detail = transcripts.get_revision(str(revision["id"]), include_content=True)
            if detail is None:
                continue
            for cue in detail.get("cues", []):
                label = cue.get("speaker_label") if isinstance(cue, Mapping) else None
                if isinstance(label, str) and label.strip():
                    normalized = label.strip().casefold()
                    result[source_id].add(
                        hashlib.sha256(f"participant\0{normalized}".encode()).hexdigest()
                    )
        return result

    def _generate_findings(
        self,
        job: Mapping[str, Any],
        *,
        checkpoint: Callable[[int], None],
    ) -> list[dict[str, Any]]:
        limits = QualificationLimits.from_mapping(job["snapshot"]["limits"])
        rows = list(job["snapshot"]["objects"])
        started = monotonic()
        findings: list[dict[str, Any]] = []
        relations = 0

        def check_bounds() -> None:
            if monotonic() - started > limits.max_job_seconds:
                raise QualificationError(
                    "qualification_limit_exceeded", "qualification duration limit was exceeded"
                )
            if len(findings) > limits.max_findings or relations > limits.max_candidate_relations:
                raise QualificationError(
                    "qualification_limit_exceeded", "qualification candidate limit was exceeded"
                )
            if len(_json_bytes(findings)) > limits.max_output_bytes:
                raise QualificationError(
                    "qualification_output_limit_exceeded", "qualification output was amplified"
                )

        by_digest: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_size_media: dict[tuple[Any, str], list[dict[str, Any]]] = defaultdict(list)
        for index, row in enumerate(rows, start=1):
            digest = row.get("content_sha256")
            if isinstance(digest, str):
                by_digest[digest].append(row)
            by_size_media[(row.get("size_bytes"), str(row.get("media_type")))].append(row)
            mismatch = (
                row.get("content_sha256") is None
                or row.get("original_sha256") is None
                or row.get("content_sha256") != row.get("original_sha256")
                or row.get("size_bytes") != row.get("original_size_bytes")
            )
            if mismatch:
                findings.append(
                    self._finding(
                        finding_type="checksum-provenance-incompatible",
                        rows=[row],
                        evidence={"code": "canonical-original-binding-mismatch"},
                        rule_id="canonical-original-binding-v1",
                        epistemic_state="incompatible",
                        confidence_kind="deterministic-check",
                        confidence_value=1.0,
                        job=job,
                    )
                )
            artifacts = row.get("artifacts", [])
            if not artifacts:
                findings.append(
                    self._finding(
                        finding_type="representation-missing",
                        rows=[row],
                        evidence={"code": "no-current-derived-representation"},
                        rule_id="representation-presence-v1",
                        epistemic_state="requires-human-review",
                        confidence_kind="deterministic-check",
                        confidence_value=1.0,
                        job=job,
                    )
                )
            else:
                artifact_kinds: dict[str, int] = defaultdict(int)
                for artifact in artifacts:
                    artifact_kinds[str(artifact.get("kind"))] += 1
                for artifact_kind, count in sorted(artifact_kinds.items()):
                    if count > 1:
                        findings.append(
                            self._finding(
                                finding_type="representation-obsolete",
                                rows=[row],
                                evidence={
                                    "code": "multiple-current-representations-for-recipe",
                                    "artifact_kind": artifact_kind,
                                    "occurrence_count": count,
                                },
                                rule_id="representation-cardinality-v1",
                                epistemic_state="requires-human-review",
                                confidence_kind="deterministic-check",
                                confidence_value=1.0,
                                job=job,
                            )
                        )
                for artifact in artifacts:
                    record = self.store.read_canonical("versions", str(row["id"]))
                    artifact_record = next(
                        (
                            item
                            for item in self.store.list_derived_artifacts()
                            if item.get("id") == artifact.get("id")
                        ),
                        None,
                    )
                    path: Path | None = None
                    if artifact_record is not None:
                        try:
                            path = safe_instance_path(
                                self.store.paths.root, str(artifact_record.get("storage_ref"))
                            )
                        except ValueError:
                            path = None
                    if record is None or path is None or not path.is_file():
                        findings.append(
                            self._finding(
                                finding_type="representation-not-reconstructible",
                                rows=[row],
                                evidence={
                                    "code": "derived-payload-unavailable",
                                    "artifact_kind": artifact.get("kind"),
                                },
                                rule_id="representation-integrity-v1",
                                epistemic_state="incompatible",
                                confidence_kind="deterministic-check",
                                confidence_value=1.0,
                                job=job,
                            )
                        )
                    elif hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("checksum"):
                        findings.append(
                            self._finding(
                                finding_type="representation-recipe-inconsistent",
                                rows=[row],
                                evidence={
                                    "code": "derived-checksum-mismatch",
                                    "artifact_kind": artifact.get("kind"),
                                },
                                rule_id="representation-integrity-v1",
                                epistemic_state="incompatible",
                                confidence_kind="deterministic-check",
                                confidence_value=1.0,
                                job=job,
                            )
                        )
            for acquisition in row.get("acquisition_times", []):
                observed = acquisition.get("observed_at")
                acquired = row.get("acquired_at")
                try:
                    inconsistent = (
                        isinstance(observed, str)
                        and isinstance(acquired, str)
                        and abs((_instant(observed) - _instant(acquired)).total_seconds())
                        > 366 * 24 * 60 * 60
                    )
                except ValueError:
                    inconsistent = True
                if inconsistent:
                    findings.append(
                        self._finding(
                            finding_type="timestamp-inconsistent",
                            rows=[row],
                            evidence={"code": "observation-acquisition-time-discordant"},
                            rule_id="timestamp-consistency-v1",
                            epistemic_state="requires-human-review",
                            confidence_kind="deterministic-check",
                            confidence_value=1.0,
                            job=job,
                        )
                    )
            if index % limits.max_batch_size == 0:
                checkpoint(index)
                check_bounds()

        for digest, group in sorted(by_digest.items()):
            selected_sources = {str(row["source_id"]) for row in group}
            if len(selected_sources) < 2:
                continue
            relations += len(group) * (len(group) - 1) // 2
            findings.append(
                self._finding(
                    finding_type="possible-exact-byte-duplicate",
                    rows=group,
                    evidence={
                        "code": "exact-byte-sha256-match",
                        "content_sha256": digest,
                        "occurrence_count": len(group),
                    },
                    rule_id="cross-source-exact-byte-v1",
                    epistemic_state="deterministic-observation",
                    confidence_kind="exact-byte-match-not-identity",
                    confidence_value=1.0,
                    job=job,
                )
            )
            media_types = sorted({str(row.get("media_type")) for row in group})
            if len(media_types) > 1:
                findings.append(
                    self._finding(
                        finding_type="observed-metadata-inconsistent",
                        rows=group,
                        evidence={
                            "code": "same-bytes-distinct-media-observations",
                            "media_type_digests": [
                                hashlib.sha256(item.encode()).hexdigest() for item in media_types
                            ],
                        },
                        rule_id="exact-byte-metadata-consistency-v1",
                        epistemic_state="requires-human-review",
                        confidence_kind="deterministic-check",
                        confidence_value=1.0,
                        job=job,
                    )
                )
            formats = sorted(
                {
                    str(artifact.get("kind"))
                    for row in group
                    for artifact in row.get("artifacts", [])
                }
            )
            if len(formats) > 1:
                findings.append(
                    self._finding(
                        finding_type="language-format-discordant",
                        rows=group,
                        evidence={
                            "code": "same-bytes-distinct-derived-formats",
                            "format_digests": [
                                hashlib.sha256(item.encode()).hexdigest() for item in formats
                            ],
                        },
                        rule_id="derived-format-observation-v1",
                        epistemic_state="possible",
                        confidence_kind="bounded-heuristic",
                        confidence_value=0.6,
                        job=job,
                    )
                )
            findings.append(
                self._finding(
                    finding_type="possible-same-event-document-content",
                    rows=group,
                    evidence={
                        "code": "exact-byte-cross-source-content-reference",
                        "content_sha256": digest,
                        "source_count": len(selected_sources),
                    },
                    rule_id="cross-source-content-reference-v1",
                    epistemic_state="possible",
                    confidence_kind="content-match-not-event-or-identity",
                    confidence_value=None,
                    job=job,
                )
            )
            check_bounds()

        for (_size, _media), group in sorted(
            by_size_media.items(), key=lambda item: (str(item[0][0]), item[0][1])
        ):
            distinct_sources = {str(row["source_id"]) for row in group}
            distinct_digests = {str(row.get("content_sha256")) for row in group}
            if len(distinct_sources) < 2 or len(distinct_digests) < 2:
                continue
            for left_index, left in enumerate(group):
                for right in group[left_index + 1 :]:
                    if left["source_id"] == right["source_id"]:
                        continue
                    relations += 1
                    findings.append(
                        self._finding(
                            finding_type="possible-revision-relation",
                            rows=[left, right],
                            evidence={
                                "code": "equal-size-and-media-different-bytes",
                                "size_bytes": left.get("size_bytes"),
                                "media_type_digest": hashlib.sha256(
                                    str(left.get("media_type")).encode()
                                ).hexdigest(),
                            },
                            rule_id="bounded-revision-candidate-v1",
                            epistemic_state="possible",
                            confidence_kind="bounded-heuristic",
                            confidence_value=0.25,
                            job=job,
                        )
                    )
                    check_bounds()

        participant_sources: dict[str, set[str]] = defaultdict(set)
        for source_id, digests in self._participant_hashes(
            job["source_ids"], limits.max_objects
        ).items():
            for digest in digests:
                participant_sources[digest].add(source_id)
        row_by_source = defaultdict(list)
        for row in rows:
            row_by_source[str(row["source_id"])].append(row)
        for digest, source_set in sorted(participant_sources.items()):
            if len(source_set) < 2:
                continue
            participant_rows = [
                row_by_source[source_id][0]
                for source_id in sorted(source_set)
                if row_by_source[source_id]
            ]
            if len(participant_rows) < 2:
                continue
            findings.append(
                self._finding(
                    finding_type="possible-participant-homonym",
                    rows=participant_rows,
                    evidence={
                        "code": "same-normalized-participant-observation",
                        "observation_sha256": digest,
                        "source_count": len(source_set),
                    },
                    rule_id="participant-observation-hash-v1",
                    epistemic_state="possible",
                    confidence_kind="not-identity-evidence",
                    confidence_value=None,
                    job=job,
                )
            )
            check_bounds()

        for source in job["snapshot"]["sources"]:
            profiles = source.get("profiles", [])
            if not profiles or any(
                profile in {"gmail-synthetic-v1", "drive-synthetic-v1"} for profile in profiles
            ):
                rows_for_source = row_by_source.get(str(source["source_id"]), [])
                references = rows_for_source[:1]
                if not references:
                    references = [
                        {
                            "kind": "source",
                            "id": source["source_id"],
                            "source_id": source["source_id"],
                            "fingerprint": source["source_fingerprint"],
                        }
                    ]
                findings.append(
                    self._finding(
                        finding_type="qualification-required",
                        rows=references,
                        evidence={
                            "code": (
                                "real-provider-qualification-unavailable"
                                if profiles
                                else "source-profile-unqualified"
                            ),
                            "profile_digests": [
                                hashlib.sha256(str(item).encode()).hexdigest() for item in profiles
                            ],
                        },
                        rule_id="closed-qualification-matrix-v1",
                        epistemic_state="unqualified",
                        confidence_kind="matrix-claim",
                        confidence_value=1.0,
                        job=job,
                    )
                )
                check_bounds()

        finding_by_id = {item["id"]: item for item in findings}
        return [finding_by_id[key] for key in sorted(finding_by_id)]

    def _complete_results(self) -> list[dict[str, Any]]:
        if not self.results_root.exists():
            return []
        rows: list[dict[str, Any]] = []
        for path in self.results_root.glob("qualification_job_*/manifest.json"):
            try:
                value = self._read_json(path)
            except QualificationError:
                continue
            if value.get("status") == "complete" and value.get("complete") is True:
                rows.append(value)
        rows.sort(key=lambda item: (str(item.get("completed_at")), str(item.get("job_id"))))
        return rows

    def _publish_result(
        self,
        job: Mapping[str, Any],
        findings: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        existing = self._result_path(str(job["id"]))
        if existing.is_file():
            return self._read_json(existing)
        previous = [
            item
            for item in self._complete_results()
            if item.get("source_ids") == job.get("source_ids")
        ]
        latest = previous[-1] if previous else None
        previous_ids = {str(item.get("id")) for item in (latest or {}).get("findings", [])}
        current_ids = {str(item.get("id")) for item in findings}
        manifest = {
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "kind": "cross-source-qualification-result",
            "status": "complete",
            "complete": True,
            "job_id": job["id"],
            "source_ids": job["source_ids"],
            "snapshot_fingerprint": job["snapshot"]["fingerprint"],
            "algorithm": job["snapshot"]["algorithm"],
            "limits": job["snapshot"]["limits"],
            "findings": list(findings),
            "finding_count": len(findings),
            "superseded_finding_ids": sorted(previous_ids - current_ids),
            "completed_at": utc_now(),
            "network_used": False,
            "provider_mutation": False,
            "canonical_source_mutation": False,
            "automatic_merge": False,
            "private_content_included": False,
        }
        encoded = _json_bytes(manifest)
        limits = QualificationLimits.from_mapping(job["snapshot"]["limits"])
        if len(encoded) > limits.max_output_bytes:
            raise QualificationError(
                "qualification_output_limit_exceeded", "qualification result exceeds its limit"
            )
        self.results_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{job['id']}.", dir=self.results_root))
        target = self.results_root / str(job["id"])
        try:
            (stage / "manifest.json").write_bytes(encoded)
            if target.exists():
                return self._read_json(target / "manifest.json")
            os.replace(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
        return manifest

    def _finish(
        self,
        job_id: str,
        token: str,
        *,
        status: str,
        error_code: str | None,
        result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            with self._hold("qualification-finish"):
                job = self.get_job(job_id, public=False)
                if job is None or not isinstance(job.get("lease"), Mapping):
                    raise QualificationError(
                        "qualification_lease_expired", "qualification lease is unavailable"
                    )
                if job["lease"].get("token") != token:
                    raise QualificationError(
                        "qualification_lease_expired", "qualification lease ownership changed"
                    )
                processed = int(job["checkpoint"]["cursor"])
                if result is not None:
                    processed = int(result.get("finding_count", processed))
                job.update(
                    {
                        "status": status,
                        "lease": None,
                        "cancel_requested": False,
                        "checkpoint": {
                            "sequence": int(job["checkpoint"]["sequence"]) + 1,
                            "phase": "committed" if status == "succeeded" else "failed",
                            "cursor": processed,
                        },
                        "progress": {
                            "processed": processed if status == "succeeded" else 0,
                            "skipped": 0,
                            "errors": 0 if status == "succeeded" else 1,
                        },
                        "error_code": error_code,
                        "result_ref": (
                            f"state/{QUALIFICATION_STATE_KIND}/results/{job_id}/manifest.json"
                            if result is not None
                            else None
                        ),
                        "updated_at": utc_now(),
                    }
                )
                self._write_json(self._job_path(job_id), job)
                if result is not None:
                    for source_id in job["source_ids"]:
                        cursor = self._source_cursor(source_id)
                        cursor.update(
                            {
                                "last_job_id": job_id,
                                "last_snapshot_fingerprint": job["snapshot"]["fingerprint"],
                                "last_success_at": result["completed_at"],
                                "resync_required": False,
                            }
                        )
                        self._write_json(self._source_path(source_id), cursor)
                return self._public_job(job)
        except InstanceLifecycleBusy as exc:
            raise QualificationError(
                "qualification_conflict", "another Instance operation is active"
            ) from exc

    def run(
        self,
        job_id: str,
        *,
        before_commit: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        job, token = self._start(job_id)
        if not token:
            return self._public_job(job)
        try:
            findings = self._generate_findings(
                job,
                checkpoint=lambda cursor: self._checkpoint(job_id, token, cursor),
            )
            self._checkpoint(job_id, token, len(job["snapshot"]["objects"]))
            if before_commit is not None:
                before_commit()
            current_job = self.get_job(job_id, public=False)
            if current_job is None or current_job.get("cancel_requested"):
                raise QualificationError("qualification_cancelled", "qualification was cancelled")
            limits = QualificationLimits.from_mapping(job["snapshot"]["limits"])
            current_snapshot = self._snapshot(job["source_ids"], limits)
            if current_snapshot["fingerprint"] != job["snapshot"]["fingerprint"]:
                raise QualificationError(
                    "qualification_input_changed",
                    "qualification inputs changed before complete publication",
                )
            result = self._publish_result(job, findings)
            return self._finish(job_id, token, status="succeeded", error_code=None, result=result)
        except QualificationError as exc:
            status = "cancelled" if exc.code == "qualification_cancelled" else "failed"
            self._finish(job_id, token, status=status, error_code=exc.code, result=None)
            return self.get_job(job_id) or {}
        except Exception:
            self._finish(
                job_id,
                token,
                status="failed",
                error_code="qualification_internal_error",
                result=None,
            )
            raise

    def rebuild(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id, public=False)
        if job is None:
            raise QualificationError("qualification_not_found", "qualification job was not found")
        limits = QualificationLimits.from_mapping(job["snapshot"]["limits"])
        return self.queue(job["source_ids"], limits=limits)

    def _decisions(self, finding_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.store.list_canonical(QUALIFICATION_DECISION_KIND)
        if finding_id is not None:
            rows = [item for item in rows if item.get("finding_id") == finding_id]
        rows.sort(key=lambda item: (int(item.get("revision", 0)), str(item.get("id"))))
        return rows

    def _finding_index(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        superseded: set[str] = set()
        for result in self._complete_results():
            superseded.update(str(item) for item in result.get("superseded_finding_ids", []))
            for finding in result.get("findings", []):
                if isinstance(finding, Mapping):
                    finding_id = str(finding.get("id"))
                    superseded.discard(finding_id)
                    index[finding_id] = dict(finding)
        decisions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for decision in self._decisions():
            decisions[str(decision.get("finding_id"))].append(decision)
        for finding_id, finding in index.items():
            history = decisions.get(finding_id, [])
            state = str(history[-1]["resulting_state"]) if history else "open"
            if finding_id in superseded:
                state = "superseded"
            finding["workflow_state"] = state
            finding["decision_revision"] = len(history)
            finding["superseded"] = finding_id in superseded
        return index

    def list_findings(
        self,
        *,
        source_id: str | None = None,
        finding_type: str | None = None,
        workflow_state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise QualificationError(
                "qualification_limit_exceeded", "qualification finding list limit is invalid"
            )
        if finding_type is not None and finding_type not in FINDING_TYPES:
            raise QualificationError(
                "qualification_not_found", "qualification finding type is unsupported"
            )
        if workflow_state is not None and workflow_state not in WORKFLOW_STATES:
            raise QualificationError(
                "qualification_not_found", "qualification workflow state is unsupported"
            )
        rows = list(self._finding_index().values())
        if source_id is not None:
            rows = [item for item in rows if source_id in item.get("source_ids", [])]
        if finding_type is not None:
            rows = [item for item in rows if item.get("finding_type") == finding_type]
        if workflow_state is not None:
            rows = [item for item in rows if item.get("workflow_state") == workflow_state]
        rows.sort(key=lambda item: str(item.get("id")))
        return rows[:limit]

    def get_finding(self, finding_id: str) -> dict[str, Any] | None:
        selected = validate_finding_id(finding_id)
        finding = self._finding_index().get(selected)
        if finding is None:
            return None
        return {**finding, "decisions": self._decisions(selected)}

    def _finding_is_current(self, finding: Mapping[str, Any]) -> bool:
        source_ids = list(finding.get("source_ids", []))
        limits = QualificationLimits.from_mapping(finding.get("limits"))
        try:
            snapshot = self._snapshot(source_ids, limits)
        except QualificationError:
            return False
        expected_sources = finding.get("provenance", {}).get("source_snapshot_fingerprints")
        current_sources = {
            str(source["source_id"]): _digest(source) for source in snapshot["sources"]
        }
        if not isinstance(expected_sources, Mapping) or current_sources != expected_sources:
            return False
        current_objects = {
            (str(row["kind"]), str(row["id"]), str(row["source_id"])): str(row["fingerprint"])
            for row in snapshot["objects"]
        }
        return all(
            current_objects.get(
                (
                    str(reference["kind"]),
                    str(reference["id"]),
                    str(reference["source_id"]),
                )
            )
            == reference.get("fingerprint")
            for reference in finding.get("object_refs", [])
            if reference.get("kind") != "source"
        )

    def decide(
        self,
        finding_id: str,
        *,
        action: str,
        actor_id: str,
        reason: str,
        expected_revision: int,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected_finding_id = validate_finding_id(finding_id)
        if action not in DECISION_ACTIONS:
            raise QualificationError(
                "qualification_invalid_decision", "qualification decision action is unsupported"
            )
        finding = self._finding_index().get(selected_finding_id)
        if finding is None:
            raise QualificationError(
                "qualification_not_found", "qualification finding was not found"
            )
        if finding.get("superseded"):
            raise QualificationError(
                "qualification_reference_stale", "qualification finding has been superseded"
            )
        if not self._finding_is_current(finding):
            raise QualificationError(
                "qualification_reference_stale", "qualification finding references stale input"
            )
        limits = QualificationLimits.from_mapping(finding["limits"])
        actor = normalise_actor_id(actor_id)
        selected_reason = sanitise_reason(reason, limits)
        selected_payload = normalise_decision_payload(action, payload)
        finding_object_ids = {str(item["id"]) for item in finding["object_refs"]}
        for object_id in selected_payload.get("object_ids", []):
            if object_id not in finding_object_ids:
                raise QualificationError(
                    "qualification_reference_stale",
                    "decision object reference is outside the finding",
                )
        try:
            with self._hold("qualification-decision"):
                history = self._decisions(selected_finding_id)
                if type(expected_revision) is not int or expected_revision != len(history):
                    raise QualificationError(
                        "qualification_conflict", "qualification decision revision is stale"
                    )
                target_id = selected_payload.get(
                    "target_decision_id", selected_payload.get("supersedes_decision_id")
                )
                if target_id is not None and target_id not in {item["id"] for item in history}:
                    raise QualificationError(
                        "qualification_reference_stale", "target decision is not in this history"
                    )
                revision = len(history) + 1
                identity = {
                    "finding_id": selected_finding_id,
                    "revision": revision,
                    "action": action,
                    "actor_id": actor,
                    "reason_sha256": hashlib.sha256(selected_reason.encode()).hexdigest(),
                    "payload": selected_payload,
                }
                decision = {
                    "schema_version": QUALIFICATION_SCHEMA_VERSION,
                    "id": _stable_id("decision", identity),
                    "finding_id": selected_finding_id,
                    "finding_identity_sha256": hashlib.sha256(
                        _json_bytes(
                            {
                                "finding_type": finding["finding_type"],
                                "object_refs": finding["object_refs"],
                                "evidence": finding["evidence"],
                            }
                        )
                    ).hexdigest(),
                    "revision": revision,
                    "action": action,
                    "resulting_state": DECISION_RESULT_STATES[action],
                    "actor_id": actor,
                    "reason": selected_reason,
                    "payload": selected_payload,
                    "provenance": {
                        "source_ids": finding["source_ids"],
                        "qualification_job_id": finding["provenance"]["qualification_job_id"],
                        "snapshot_fingerprint": finding["provenance"]["snapshot_fingerprint"],
                        "originals_modified": False,
                        "provider_objects_modified": False,
                        "source_observations_modified": False,
                        "automatic_propagation": False,
                    },
                    "created_at": utc_now(),
                }
                self.store._atomic_json(
                    self.store.paths.canonical_dir(QUALIFICATION_DECISION_KIND)
                    / f"{decision['id']}.json",
                    decision,
                )
                return decision
        except InstanceLifecycleBusy as exc:
            raise QualificationError(
                "qualification_conflict", "another Instance operation is active"
            ) from exc

    def list_decisions(self, finding_id: str | None = None) -> list[dict[str, Any]]:
        if finding_id is not None:
            validate_finding_id(finding_id)
        return self._decisions(finding_id)

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        return self.store.read_canonical(QUALIFICATION_DECISION_KIND, decision_id)

    def _recover_expired_leases(self) -> None:
        try:
            with self._hold("qualification-lease-recovery"):
                self._recover_expired_leases_locked()
        except InstanceLifecycleBusy:
            return

    def _recover_expired_leases_locked(self) -> None:
        if not self.jobs_root.exists():
            return
        now = datetime.now(UTC)
        for path in self.jobs_root.glob("*.json"):
            try:
                job = self._read_json(path)
                lease = job.get("lease")
                if job.get("status") != "running" or not isinstance(lease, Mapping):
                    continue
                if _instant(str(lease.get("expires_at"))) > now:
                    continue
                if int(job.get("attempt", 0)) >= int(job.get("max_attempts", 0)):
                    job["status"] = "failed"
                    job["error_code"] = "qualification_retry_exhausted"
                else:
                    job["status"] = "queued"
                    job["error_code"] = "qualification_lease_expired"
                job["lease"] = None
                job["updated_at"] = now.isoformat()
                self._write_json(path, job)
            except (QualificationError, ValueError, TypeError):
                continue

    def _reconcile_source_checkpoints(self) -> None:
        try:
            with self._hold("qualification-checkpoint-recovery"):
                self._reconcile_source_checkpoints_locked()
        except InstanceLifecycleBusy:
            return

    def _reconcile_source_checkpoints_locked(self) -> None:
        latest_by_source: dict[str, dict[str, Any]] = {}
        for result in self._complete_results():
            for source_id in result.get("source_ids", []):
                latest_by_source[str(source_id)] = result
        for source_id, result in latest_by_source.items():
            try:
                cursor = self._source_cursor(source_id)
            except QualificationError:
                continue
            if cursor.get("last_job_id") == result.get("job_id"):
                continue
            cursor.update(
                {
                    "last_job_id": result["job_id"],
                    "last_snapshot_fingerprint": result["snapshot_fingerprint"],
                    "last_success_at": result["completed_at"],
                    "resync_required": False,
                }
            )
            self._write_json(self._source_path(source_id), cursor)


def qualification_state_findings(
    store: InstanceStore,
    records: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    manager = QualificationManager(store, recover=False)
    source_ids = set(records.get("sources", {}))
    finding_ids = set(manager._finding_index())
    for job in manager.list_jobs(limit=500):
        path = f"state/{QUALIFICATION_STATE_KIND}/jobs/{job['id']}.json"
        if (
            job.get("schema_version") != QUALIFICATION_SCHEMA_VERSION
            or job.get("kind") != "cross-source.qualification"
            or job.get("status") not in {"queued", "running", "succeeded", "failed", "cancelled"}
            or not set(job.get("source_ids", [])).issubset(source_ids)
            or job.get("algorithm", {}).get("id") != QUALIFICATION_ALGORITHM_ID
        ):
            errors.append(
                {
                    "code": "qualification_job_invalid",
                    "message": "Qualification job state is invalid",
                    "path": path,
                }
            )
    for decision_id, decision in records.get(QUALIFICATION_DECISION_KIND, {}).items():
        path = f"knowledge/{QUALIFICATION_DECISION_KIND}/{decision_id}.json"
        try:
            valid_finding_id = validate_finding_id(decision.get("finding_id")) is not None
        except QualificationError:
            valid_finding_id = False
        valid = (
            decision.get("schema_version") == QUALIFICATION_SCHEMA_VERSION
            and decision.get("id") == decision_id
            and valid_finding_id
            and (
                decision.get("finding_id") in finding_ids
                or isinstance(decision.get("finding_identity_sha256"), str)
                and len(decision["finding_identity_sha256"]) == 64
            )
            and decision.get("action") in DECISION_ACTIONS
            and decision.get("resulting_state") in WORKFLOW_STATES
            and isinstance(decision.get("reason"), str)
            and isinstance(decision.get("provenance"), Mapping)
            and decision["provenance"].get("originals_modified") is False
            and decision["provenance"].get("provider_objects_modified") is False
            and decision["provenance"].get("automatic_propagation") is False
        )
        if not valid:
            errors.append(
                {
                    "code": "qualification_decision_invalid",
                    "message": "Qualification decision history is invalid",
                    "path": path,
                }
            )
    return errors


__all__ = [
    "QUALIFICATION_DECISION_KIND",
    "QUALIFICATION_STATE_KIND",
    "QualificationManager",
    "qualification_state_findings",
]
