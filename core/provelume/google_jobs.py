from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .atomic_commit import (
    GOOGLE_INTAKE_TRANSACTION_PROFILE,
    AtomicCommitError,
    AtomicInstanceCommit,
)
from .domain import (
    Acquisition,
    Document,
    DocumentVersion,
    Original,
    as_record,
    email_message_evidence_id,
)
from .email_contract import EmailLimits, FilesystemIdentity, ObservedMessageBytes
from .email_jobs import EmailJobManager
from .google_adapters import GoogleApiAdapter
from .google_contract import (
    GOOGLE_ADAPTER_ID,
    GOOGLE_ADAPTER_VERSION,
    GOOGLE_ERROR_CODES,
    GOOGLE_JOB_KIND,
    GoogleContractError,
    GoogleItem,
    GoogleLimits,
    GoogleProviderAdapter,
)
from .google_sources import GoogleSourceManager
from .instance_lifecycle import InstanceLifecycleManager
from .scheduler import SchedulerStore, public_job_record
from .scheduler_model import SchedulerConflictError, SchedulerError, retry_payload
from .storage import InstanceStore, utc_now

GOOGLE_JOB_SCHEMA_VERSION = 1
_TERMINAL_STATUSES = {"succeeded", "failed", "manual_intervention", "cancelled"}
_CHECKPOINT = Callable[[dict[str, int]], Mapping[str, Any]]


def _json_bytes(value: Any) -> bytes:
    selected = as_record(value) if not isinstance(value, Mapping) else dict(value)
    return (json.dumps(selected, indent=2, sort_keys=True) + "\n").encode()


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{uuid5(NAMESPACE_URL, value).hex}"


def _original(item: GoogleItem, acquired_at: str) -> Original:
    digest = item.payload_sha256
    return Original(
        id=f"sha256_{digest}",
        sha256=digest,
        size_bytes=len(item.payload),
        storage_ref=f"originals/sha256/{digest[:2]}/{digest}",
        created_at=acquired_at,
    )


class GoogleJobManager:
    """Bounded, resumable orchestration for independently scoped Google Sources."""

    def __init__(
        self,
        store: InstanceStore,
        *,
        adapter: GoogleProviderAdapter | None = None,
    ):
        self.store = store
        self.sources = GoogleSourceManager(store)
        self.scheduler = SchedulerStore(store)
        self.adapter = adapter or GoogleApiAdapter()
        self.email = EmailJobManager(store)
        self.root = store.paths.state / "google-adapters" / "jobs"
        self.requests = self.root / "requests"
        self.runs = self.root / "runs"
        self.work = self.root / "work"
        self.cancellations = self.root / "cancellations"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
                raise GoogleContractError("google_internal_error", "Google job state is invalid")
            value = json.loads(path.read_text(encoding="utf-8"))
        except GoogleContractError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GoogleContractError(
                "google_internal_error", "Google job state is unreadable"
            ) from exc
        if not isinstance(value, dict):
            raise GoogleContractError("google_internal_error", "Google job state must be an object")
        return value

    def _write_json(self, path: Path, value: Mapping[str, Any]) -> None:
        self.store._atomic_json(path, dict(value))

    def _write_immutable(self, path: Path, value: Mapping[str, Any]) -> None:
        selected = dict(value)
        if path.is_file():
            if self._read_json(path) != selected:
                raise GoogleContractError(
                    "google_internal_error", "Google job request is immutable"
                )
            return
        self._write_json(path, selected)

    def _policy_for_source(self, source_id: str) -> dict[str, Any] | None:
        values = [
            item
            for item in self.scheduler.list_policies()
            if item["job_kind"] == GOOGLE_JOB_KIND
            and item["scope"] == {"kind": "source", "id": source_id}
        ]
        if len(values) > 1:
            raise GoogleContractError(
                "google_internal_error", "Google Source has multiple policies"
            )
        return values[0] if values else None

    def sync_policy(self, source_id: str) -> dict[str, Any]:
        source = self.sources.source_view(source_id)
        schedule = source["schedule"]
        state = (
            "enabled"
            if source["state"] == "enabled"
            and source["lifecycle_state"] == "active"
            and schedule["mode"] == "interval"
            else "disabled"
        )
        current = self._policy_for_source(source_id)
        if current is None:
            return self.scheduler.create_policy(
                job_kind=GOOGLE_JOB_KIND,
                scope={"kind": "source", "id": source_id},
                state=state,
                schedule=schedule,
                retry=retry_payload(max_attempts=3, base_seconds=30, max_seconds=600),
            )
        if current["state"] == state and current["schedule"] == schedule:
            return current
        return self.scheduler.update_policy(str(current["id"]), state=state, schedule=schedule)

    def _request_record(self, job_id: str, source_id: str, limits: GoogleLimits) -> dict[str, Any]:
        source = self.sources.source_record(source_id, require_enabled=True)
        instance, capability, _ = self.sources.effective_execution_context(source_id)
        fingerprints = self.sources.configuration_fingerprints(source_id)
        return {
            "schema_version": GOOGLE_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            "source_id": source_id,
            "connector_instance_id": source["connector_instance_id"],
            "capability": source["capability"],
            "adapter_id": GOOGLE_ADAPTER_ID,
            "adapter_version": GOOGLE_ADAPTER_VERSION,
            "source_fingerprint": fingerprints["source"],
            "capability_fingerprint": fingerprints["capability"],
            "capability_revision": fingerprints["capability_revision"],
            "cursor_revision": fingerprints["cursor_revision"],
            "selection_sha256": source["selection_sha256"],
            "limits": limits.as_record(),
            "allowed_origins": list(instance["allowed_origins"]),
            "scope": list(capability["scope"]),
            "requested_at": utc_now(),
            "network_access": "explicit_only",
            "network_used": True,
            "provider_write": False,
            "real_google_qualified": False,
        }

    def queue(self, source_id: str, *, request_key: str | None = None) -> dict[str, Any]:
        limits = GoogleLimits()
        provisional = self._request_record("job_" + "0" * 32, source_id, limits)
        policy = self.sync_policy(source_id)
        identity = hashlib.sha256(
            json.dumps(
                {
                    "source": provisional["source_fingerprint"],
                    "capability": provisional["capability_fingerprint"],
                    "cursor_revision": provisional["cursor_revision"],
                    "request_key": request_key,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        try:
            queued = self.scheduler.run_now(
                str(policy["id"]),
                request_key=identity if request_key is not None else None,
            )
        except SchedulerError as exc:
            raise GoogleContractError(
                "google_internal_error", "Google intake could not be queued"
            ) from exc
        job = queued["job"]
        request = self._request_record(str(job["id"]), source_id, limits)
        path = self.requests / f"{job['id']}.json"
        if path.is_file():
            current = self._read_json(path)
            stable = set(request) - {"requested_at"}
            if any(current.get(key) != request.get(key) for key in stable):
                raise GoogleContractError("google_input_changed", "Google intake request changed")
            request = current
        else:
            self._write_immutable(path, request)
        return {
            "schema_version": GOOGLE_JOB_SCHEMA_VERSION,
            "created": bool(queued["created"]),
            "job": public_job_record(job),
            "request": {
                key: request[key]
                for key in (
                    "source_id",
                    "connector_instance_id",
                    "capability",
                    "source_fingerprint",
                    "capability_fingerprint",
                    "cursor_revision",
                    "selection_sha256",
                    "network_access",
                    "network_used",
                    "provider_write",
                    "real_google_qualified",
                )
            },
        }

    def _request_for_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        job_id = str(job["id"])
        source_id = str(job["scope"]["id"])
        path = self.requests / f"{job_id}.json"
        if not path.is_file():
            if job.get("reason") not in {"scheduled", "coalesced", "catch_up"}:
                raise GoogleContractError(
                    "google_internal_error", "Google intake request is missing"
                )
            self._write_immutable(path, self._request_record(job_id, source_id, GoogleLimits()))
        request = self._read_json(path)
        current = self.sources.configuration_fingerprints(source_id)
        if (
            request.get("job_id") != job_id
            or request.get("source_id") != source_id
            or request.get("source_fingerprint") != current["source"]
            or request.get("capability_fingerprint") != current["capability"]
            or request.get("capability_revision") != current["capability_revision"]
            or request.get("cursor_revision") != current["cursor_revision"]
        ):
            raise GoogleContractError(
                "google_input_changed", "Google Source changed after intake was queued"
            )
        return request

    def _cancel_requested(self, job_id: str) -> bool:
        path = self.cancellations / f"{job_id}.json"
        return path.is_file() and self._read_json(path).get("job_id") == job_id

    def _work_record(self, job_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        path = self.work / f"{job_id}.json"
        if path.is_file():
            value = self._read_json(path)
            if (
                value.get("job_id") != job_id
                or value.get("source_id") != request["source_id"]
                or not isinstance(value.get("items"), dict)
            ):
                raise GoogleContractError("google_internal_error", "Google work journal is invalid")
            return value
        return {
            "schema_version": GOOGLE_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            "source_id": request["source_id"],
            "items": {},
            "updated_at": utc_now(),
        }

    def _write_work(self, job_id: str, value: dict[str, Any]) -> None:
        value["updated_at"] = utc_now()
        self._write_json(self.work / f"{job_id}.json", value)

    def _write_run(
        self,
        job_id: str,
        request: Mapping[str, Any],
        *,
        status: str,
        progress: Mapping[str, int],
        error_codes: Sequence[str] = (),
    ) -> dict[str, Any]:
        value = {
            "schema_version": GOOGLE_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            "source_id": request["source_id"],
            "connector_instance_id": request["connector_instance_id"],
            "capability": request["capability"],
            "status": status,
            "progress": dict(progress),
            "error_codes": [
                code for code in dict.fromkeys(error_codes) if code in GOOGLE_ERROR_CODES
            ],
            "updated_at": utc_now(),
            "network_used": True,
            "provider_write": False,
            "private_content_recorded": False,
            "real_google_qualified": False,
        }
        self._write_json(self.runs / f"{job_id}.json", value)
        return value

    @staticmethod
    def _item_key(source_id: str, item: GoogleItem) -> str:
        return hashlib.sha256(
            json.dumps(
                {"source_id": source_id, **item.identity_record()},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def _commit_gmail(
        self, job_id: str, source_id: str, item: GoogleItem, acquired_at: str
    ) -> tuple[str, str]:
        identity = item.identity_record()
        observed = ObservedMessageBytes(
            source_id=source_id,
            mailbox_format="gmail",
            profile="google-api-readonly-v1",
            container_identity_sha256=hashlib.sha256(
                f"google-gmail-source:{source_id}".encode()
            ).hexdigest(),
            snapshot_sha256=hashlib.sha256(
                f"google-gmail-revision:{identity['provider_revision_ref_sha256']}".encode()
            ).hexdigest(),
            locator_sha256=str(identity["provider_item_ref_sha256"]),
            filesystem=FilesystemIdentity(
                device=0,
                inode=0,
                size_bytes=len(item.payload),
                mtime_ns=0,
                ctime_ns=0,
                link_count=1,
                file_attributes=0,
            ),
            observed_at=item.provider_observed_at or acquired_at,
            acquired_at=acquired_at,
            sha256=item.payload_sha256,
            size_bytes=len(item.payload),
            data=item.payload,
        )
        limits = EmailLimits()
        parsed = self.email.parser.parse(item.payload, limits=limits)
        observation_id = _stable_id(
            "google_gmail_observation",
            f"{source_id}:{identity['provider_item_ref_sha256']}:{identity['provider_revision_ref_sha256']}:{item.payload_sha256}",
        )
        provider_observation = {
            "provider_item_ref_sha256": identity["provider_item_ref_sha256"],
            "provider_revision_ref_sha256": identity["provider_revision_ref_sha256"],
            "provider_thread_ref_sha256": identity["provider_thread_ref_sha256"],
            "provider_label_ref_sha256": identity["provider_label_ref_sha256"],
            "provider_observed_at": identity["provider_observed_at"],
            "authoritative": False,
            "source_scoped": True,
        }
        canonical_observation = {
            "schema_version": 1,
            "id": observation_id,
            "source_id": source_id,
            "message_id": email_message_evidence_id(
                source_id, item.payload_sha256, len(item.payload)
            ),
            **provider_observation,
            "accepted_at": acquired_at,
        }
        settings_sha256 = hashlib.sha256(
            json.dumps(limits.as_record(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return self.email._commit_message(
            job_id=job_id,
            observed=observed,
            parsed=parsed,
            settings_sha256=settings_sha256,
            recheck=lambda: None,
            adapter_id=GOOGLE_ADAPTER_ID,
            adapter_version=GOOGLE_ADAPTER_VERSION,
            acquisition_kind="google_gmail_readonly",
            document_title_prefix="Google Gmail message",
            network_access="explicit_only",
            provider_observation=provider_observation,
            network_used=True,
            remote_fetch=True,
            extra_canonical_records=(("google-gmail-observations", canonical_observation),),
            transaction_profile=GOOGLE_INTAKE_TRANSACTION_PROFILE,
        )

    def _commit_drive(
        self, job_id: str, source_id: str, item: GoogleItem, acquired_at: str
    ) -> tuple[str, str]:
        identity = item.identity_record()
        provider_file = str(identity["provider_item_ref_sha256"])
        provider_revision = str(identity["provider_revision_ref_sha256"])
        document_id = _stable_id("doc", f"google-drive-file:{source_id}:{provider_file}")
        version_id = _stable_id(
            "ver", f"google-drive-revision:{source_id}:{provider_file}:{provider_revision}"
        )
        original = _original(item, acquired_at)
        acquisition_id = _stable_id(
            "acq",
            f"google-drive-acquisition:{source_id}:{provider_file}:{provider_revision}:{item.payload_sha256}",
        )
        revision_id = _stable_id(
            "google_drive_revision",
            f"{source_id}:{provider_file}:{provider_revision}:{item.payload_sha256}",
        )
        if self.store.read_canonical("google-drive-revisions", revision_id) is not None:
            return "skipped", document_id
        previous = [
            value
            for value in self.store.list_canonical("google-drive-revisions")
            if value.get("source_id") == source_id
            and value.get("provider_file_ref_sha256") == provider_file
        ]
        sequence = 1 + max((int(value["sequence"]) for value in previous), default=0)
        document = Document(
            id=document_id,
            source_id=source_id,
            locator=f"google-drive-file:sha256:{provider_file}",
            title=f"Google Drive file {document_id}",
            media_type=item.media_type,
            created_at=min((str(value["accepted_at"]) for value in previous), default=acquired_at),
            current_version_id=version_id,
        )
        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            sequence=sequence,
            content_hash=item.payload_sha256,
            original_id=original.id,
            media_type=item.media_type,
            size_bytes=len(item.payload),
            acquired_at=acquired_at,
        )
        acquisition = Acquisition(
            id=acquisition_id,
            source_id=source_id,
            locator=f"google-drive-item:sha256:{provider_file}",
            observed_at=item.provider_observed_at or acquired_at,
            content_hash=item.payload_sha256,
            outcome="updated" if previous else "created",
            document_id=document_id,
            version_id=version_id,
            error=None,
            acquisition_kind="google_drive_readonly",
            media_type=item.media_type,
            original_id=original.id,
            response_size_bytes=len(item.payload),
            exact_duplicate=False,
        )
        file_record = {
            "schema_version": 1,
            "id": _stable_id("google_drive_file", f"{source_id}:{provider_file}"),
            "source_id": source_id,
            "document_id": document_id,
            "provider_file_ref_sha256": provider_file,
            "current_revision_id": revision_id,
            "provider_neutral_identity": True,
            "updated_at": acquired_at,
        }
        revision_record = {
            "schema_version": 1,
            "id": revision_id,
            "source_id": source_id,
            "document_id": document_id,
            "version_id": version_id,
            "original_id": original.id,
            "acquisition_id": acquisition_id,
            "provider_file_ref_sha256": provider_file,
            "provider_revision_ref_sha256": provider_revision,
            "sequence": sequence,
            "source_format": identity["source_format"] or item.media_type,
            "export_format": identity["export_format"],
            "google_native": identity["google_native"],
            "media_type": item.media_type,
            "checksum_sha256": item.payload_sha256,
            "size_bytes": len(item.payload),
            "provider_observed_at": item.provider_observed_at,
            "accepted_at": acquired_at,
            "exact_byte_original": True,
            "provider_write": False,
        }
        transaction = AtomicInstanceCommit(
            self.store,
            InstanceLifecycleManager(self.store).control_root / "transactions",
            profile=GOOGLE_INTAKE_TRANSACTION_PROFILE,
            owner_id=job_id,
        )
        transaction.add(original.storage_ref, item.payload, immutable=True)
        for kind, record, immutable in (
            ("originals", asdict(original), True),
            ("documents", asdict(document), False),
            ("versions", asdict(version), True),
            ("acquisitions", asdict(acquisition), True),
            ("google-drive-files", file_record, False),
            ("google-drive-revisions", revision_record, True),
        ):
            transaction.add(
                f"knowledge/{kind}/{record['id']}.json", _json_bytes(record), immutable=immutable
            )
        try:
            transaction.commit()
        except AtomicCommitError as exc:
            raise GoogleContractError(
                "google_internal_error", "Google Drive item promotion failed"
            ) from exc
        return "processed", document_id

    def execute(
        self, job: Mapping[str, Any], *, checkpoint: _CHECKPOINT | None = None
    ) -> dict[str, int]:
        if (
            job.get("job_kind") != GOOGLE_JOB_KIND
            or job.get("status") != "running"
            or not isinstance(job.get("lease"), Mapping)
        ):
            raise GoogleContractError(
                "google_internal_error", "Google scheduler job is not claimed"
            )
        job_id = str(job["id"])
        request = self._request_for_job(job)
        limits = GoogleLimits.from_mapping(request["limits"])
        instance, capability, source = self.sources.effective_execution_context(
            str(request["source_id"])
        )
        work = self._work_record(job_id, request)
        progress = {
            "processed": sum(
                1 for value in work["items"].values() if value.get("status") == "processed"
            ),
            "skipped": sum(
                1 for value in work["items"].values() if value.get("status") == "skipped"
            ),
            "errors": sum(1 for value in work["items"].values() if value.get("status") == "error"),
        }
        errors = [
            str(value["error_code"])
            for value in work["items"].values()
            if value.get("status") == "error" and value.get("error_code") in GOOGLE_ERROR_CODES
        ]
        self._write_run(job_id, request, status="running", progress=progress, error_codes=errors)
        cursor = source["cursor"].get("provider_cursor")
        base_ordinal = 0 if cursor is None else int(source["cursor"]["page_ordinal"])
        pages = 0
        total_bytes = 0
        while True:
            if self._cancel_requested(job_id):
                self._write_run(
                    job_id,
                    request,
                    status="cancelled",
                    progress=progress,
                    error_codes=[*errors, "google_cancelled"],
                )
                raise GoogleContractError("google_cancelled", "Google intake was cancelled")
            if pages >= limits.max_pages_per_run:
                raise GoogleContractError(
                    "google_backfill_limit_exceeded", "Google page bound was reached"
                )
            page = self.adapter.fetch_page(
                instance=instance,
                capability=capability,
                source=source,
                cursor=cursor,
                limits=limits,
            )
            pages += 1
            fingerprint = page.fingerprint()
            ordinal = base_ordinal + pages
            previous_fingerprints = list(source["cursor"]["page_fingerprints"])
            if (
                len(previous_fingerprints) >= ordinal
                and previous_fingerprints[ordinal - 1] != fingerprint
            ):
                raise GoogleContractError("google_cursor_invalidated", "Google replay page changed")
            if (
                len(previous_fingerprints) < ordinal
                and len(previous_fingerprints) < limits.max_page_fingerprints
            ):
                previous_fingerprints.append(fingerprint)
            for item in page.items:
                if len(work["items"]) >= limits.max_items_per_run:
                    raise GoogleContractError(
                        "google_backfill_limit_exceeded", "Google item bound was reached"
                    )
                if len(item.payload) > limits.max_item_bytes:
                    raise GoogleContractError(
                        "google_payload_limit_exceeded", "Google item byte bound was reached"
                    )
                total_bytes += len(item.payload)
                if total_bytes > limits.max_total_bytes_per_run:
                    raise GoogleContractError(
                        "google_payload_limit_exceeded", "Google run byte bound was reached"
                    )
                key = self._item_key(str(request["source_id"]), item)
                if work["items"].get(key, {}).get("status") in {"processed", "skipped"}:
                    continue
                try:
                    if request["capability"] == "gmail":
                        status, canonical_id = self._commit_gmail(
                            job_id, str(request["source_id"]), item, utc_now()
                        )
                    else:
                        status, canonical_id = self._commit_drive(
                            job_id, str(request["source_id"]), item, utc_now()
                        )
                    work["items"][key] = {
                        "status": status,
                        "canonical_id": canonical_id,
                        "payload_sha256": item.payload_sha256,
                        "size_bytes": len(item.payload),
                    }
                    progress[status] += 1
                except GoogleContractError as exc:
                    work["items"][key] = {"status": "error", "error_code": exc.code}
                    progress["errors"] += 1
                    errors.append(exc.code)
                    if progress["errors"] >= limits.max_error_count:
                        raise
                self._write_work(job_id, work)
                if checkpoint is not None:
                    checkpoint(progress)
            now = utc_now()
            next_cursor = page.next_cursor
            updated_cursor = {
                **source["cursor"],
                "provider_cursor": next_cursor,
                "page_ordinal": ordinal,
                "page_fingerprints": previous_fingerprints,
                "resync_required": False,
                "last_attempt_at": now,
                "last_success_at": now,
                "last_status": "complete" if next_cursor is None else "checkpointed",
            }
            self.sources.update_cursor(
                str(request["source_id"]),
                cursor=updated_cursor,
                health={"status": "ready", "code": "google_read_succeeded", "checked_at": now},
            )
            source = self.sources.source_record(str(request["source_id"]))
            cursor = next_cursor
            if cursor is None:
                break
        status = "completed_with_errors" if progress["errors"] else "completed"
        self._write_run(job_id, request, status=status, progress=progress, error_codes=errors)
        return progress

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.scheduler.get_job(job_id)
        if job is None or job.get("job_kind") != GOOGLE_JOB_KIND:
            raise GoogleContractError("google_internal_error", "Google job was not found")
        if job["status"] == "running":
            marker = {
                "schema_version": GOOGLE_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "requested_at": utc_now(),
            }
            self._write_immutable(self.cancellations / f"{job_id}.json", marker)
            return {"job_id": job_id, "status": "cancellation_requested"}
        if job["status"] in _TERMINAL_STATUSES:
            return public_job_record(job)
        try:
            return public_job_record(self.scheduler.cancel(job_id))
        except SchedulerConflictError as exc:
            raise GoogleContractError(
                "google_internal_error", "Google job cancellation conflicted"
            ) from exc

    def _run_for_job(self, job_id: str) -> dict[str, Any] | None:
        path = self.runs / f"{job_id}.json"
        return self._read_json(path) if path.is_file() else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.scheduler.get_job(job_id)
        if job is None or job.get("job_kind") != GOOGLE_JOB_KIND:
            return None
        return {**public_job_record(job), "google_run": self._run_for_job(job_id)}

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        jobs = [
            job
            for job in self.scheduler.list_jobs(limit=500)
            if job.get("job_kind") == GOOGLE_JOB_KIND
        ]
        return [
            {**public_job_record(job), "google_run": self._run_for_job(str(job["id"]))}
            for job in jobs[: max(0, min(limit, 500))]
        ]

    def list_gmail_observations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_canonical("google-gmail-observations")[:limit]

    def list_drive_revisions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_canonical("google-drive-revisions")[:limit]


__all__ = ["GOOGLE_JOB_SCHEMA_VERSION", "GoogleJobManager"]
