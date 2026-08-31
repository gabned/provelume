from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .atomic_commit import (
    EMAIL_INTAKE_TRANSACTION_PROFILE,
    AtomicCommitError,
    AtomicInstanceCommit,
)
from .domain import (
    EMAIL_EVIDENCE_SCHEMA_VERSION,
    Acquisition,
    Document,
    DocumentVersion,
    EmailAttachmentEvidence,
    EmailMessageEvidence,
    EmailMessageObservation,
    Original,
    ProvenanceEdge,
    as_record,
    email_attachment_evidence_id,
    email_message_evidence_id,
    email_message_observation_id,
)
from .email_bundle import (
    EMAIL_BUNDLE_GENERATOR,
    EMAIL_BUNDLE_KIND,
    EmailDerivedPlan,
    attachment_part_identity,
    build_email_bundle,
    observed_threads,
    stable_edge,
)
from .email_containers import adapter_for_profile
from .email_contract import (
    EMAIL_ADAPTER_ID,
    EMAIL_ADAPTER_VERSION,
    EMAIL_ERROR_CODES,
    EMAIL_PARSER_ID,
    EMAIL_PARSER_VERSION,
    EmailContractError,
    EmailLimits,
    ObservedMessageBytes,
    ParsedEmail,
    settings_fingerprint,
)
from .email_mime import StdlibEmailParser
from .email_sources import EmailSourceManager
from .instance_lifecycle import InstanceLifecycleManager
from .ocr_contract import OCR_SUPPORTED_INPUTS, ocr_settings_from_config
from .paths import UnsafePathError, safe_instance_path
from .scheduler import SchedulerStore, public_job_record
from .scheduler_model import SchedulerConflictError, SchedulerError, retry_payload
from .storage import InstanceStore, utc_now

EMAIL_JOB_SCHEMA_VERSION = 1
EMAIL_JOB_KIND = "email.intake"
EMAIL_CONTRACT_VERSION = "1"

_EMAIL_RUN_STATUSES = {"running", "completed", "completed_with_errors", "cancelled"}
_TERMINAL_SCHEDULER_STATUSES = {
    "succeeded",
    "failed",
    "cancelled",
    "manual_intervention",
}
_CHECKPOINT = Callable[[dict[str, int]], Mapping[str, Any]]


def _json_record(value: Any) -> bytes:
    selected = as_record(value) if not isinstance(value, Mapping) else dict(value)
    return (json.dumps(selected, indent=2, sort_keys=True) + "\n").encode()


def _document_id(message_id: str) -> str:
    return f"doc_{uuid5(NAMESPACE_URL, f'email-document:{message_id}').hex}"


def _version_id(document_id: str) -> str:
    return f"ver_{uuid5(NAMESPACE_URL, f'email-version:{document_id}:1').hex}"


def _acquisition_id(observation_id: str) -> str:
    return f"acq_{uuid5(NAMESPACE_URL, f'email-acquisition:{observation_id}').hex}"


def _rebuild_job_id(message_id: str, settings_sha256: str) -> str:
    value = f"email-derived-rebuild:{message_id}:{settings_sha256}"
    return f"job_{uuid5(NAMESPACE_URL, value).hex}"


def _item_idempotency_key(
    observed: ObservedMessageBytes,
    *,
    settings_sha256: str,
) -> str:
    fields = (
        observed.source_id,
        EMAIL_ADAPTER_ID,
        EMAIL_ADAPTER_VERSION,
        observed.container_identity_sha256,
        observed.snapshot_sha256,
        observed.locator_sha256,
        observed.sha256,
        str(observed.size_bytes),
        EMAIL_CONTRACT_VERSION,
        EMAIL_PARSER_ID,
        EMAIL_PARSER_VERSION,
        settings_sha256,
    )
    return hashlib.sha256("\x1f".join(fields).encode()).hexdigest()


def _original_record(
    digest: str,
    size_bytes: int,
    *,
    created_at: str,
) -> Original:
    return Original(
        id=f"sha256_{digest}",
        sha256=digest,
        size_bytes=size_bytes,
        storage_ref=f"originals/sha256/{digest[:2]}/{digest}",
        created_at=created_at,
    )


def _signature_matches(media_type: str, data: bytes) -> bool:
    if media_type == "application/pdf":
        return data.startswith(b"%PDF-")
    if media_type == "image/tiff":
        return data.startswith((b"II*\x00", b"MM\x00*"))
    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/bmp":
        return data.startswith(b"BM")
    return False


class EmailJobManager:
    """Durable, explicit orchestration for provider-neutral local email intake.

    Constructing the manager is deliberately inert: the email state tree is created
    only by an explicit queue, cancellation, removal, rebuild, or claimed execution.
    """

    def __init__(self, store: InstanceStore):
        self.store = store
        self.sources = EmailSourceManager(store)
        self.scheduler = SchedulerStore(store)
        self.parser = StdlibEmailParser()
        self.root = store.paths.state / "email-intake"
        self.requests = self.root / "requests"
        self.runs = self.root / "runs"
        self.work = self.root / "work"
        self.cancellations = self.root / "cancellations"
        self.removals = self.root / "removals"

    def _read_json(self, path: Path, *, limit: int = 2 * 1024 * 1024) -> dict[str, Any]:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
                raise EmailContractError(
                    "email_internal_error", "email intake state is invalid"
                )
            value = json.loads(path.read_text(encoding="utf-8"))
        except EmailContractError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EmailContractError(
                "email_internal_error", "email intake state is unreadable"
            ) from exc
        if not isinstance(value, dict):
            raise EmailContractError(
                "email_internal_error", "email intake state must be an object"
            )
        return value

    def _write_json(self, path: Path, value: Mapping[str, Any]) -> None:
        self.store._atomic_json(path, dict(value))

    def _write_immutable_json(self, path: Path, value: Mapping[str, Any]) -> None:
        selected = dict(value)
        if path.exists():
            if self._read_json(path) != selected:
                raise EmailContractError(
                    "email_internal_error", "email intake request is immutable"
                )
            return
        self._write_json(path, selected)

    def _policy_for_source(self, source_id: str) -> dict[str, Any] | None:
        matches = [
            item
            for item in self.scheduler.list_policies()
            if item["job_kind"] == EMAIL_JOB_KIND
            and item["scope"] == {"kind": "source", "id": source_id}
        ]
        if len(matches) > 1:
            raise EmailContractError(
                "email_internal_error", "email Source has multiple scheduler policies"
            )
        return matches[0] if matches else None

    def sync_policy(self, source_id: str) -> dict[str, Any]:
        source = self.sources.public_view(source_id)
        schedule = dict(source["schedule"])
        enabled = (
            source["lifecycle_state"] == "active"
            and source["state"] == "enabled"
            and schedule["mode"] == "interval"
        )
        state = "enabled" if enabled else "disabled"
        current = self._policy_for_source(source_id)
        if current is None:
            return self.scheduler.create_policy(
                job_kind=EMAIL_JOB_KIND,
                scope={"kind": "source", "id": source_id},
                state=state,
                schedule=schedule,
                retry=retry_payload(max_attempts=3, base_seconds=30, max_seconds=300),
            )
        if current["state"] == state and current["schedule"] == schedule:
            return current
        return self.scheduler.update_policy(
            str(current["id"]),
            state=state,
            schedule=schedule,
        )

    @staticmethod
    def _request_record(
        job_id: str,
        source_id: str,
        snapshot: Any,
        limits: EmailLimits,
    ) -> dict[str, Any]:
        return {
            "schema_version": EMAIL_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            "source_id": source_id,
            "mailbox_format": snapshot.mailbox_format,
            "profile": snapshot.profile,
            "container_identity_sha256": snapshot.container_identity_sha256,
            "container_snapshot_sha256": snapshot.snapshot_sha256,
            "message_count": snapshot.message_count,
            "total_bytes": snapshot.total_bytes,
            "adapter_id": EMAIL_ADAPTER_ID,
            "adapter_version": EMAIL_ADAPTER_VERSION,
            "parser_id": EMAIL_PARSER_ID,
            "parser_version": EMAIL_PARSER_VERSION,
            "contract_version": EMAIL_CONTRACT_VERSION,
            "settings_sha256": settings_fingerprint(limits),
            "limits": limits.as_record(),
            "requested_at": utc_now(),
            "network_used": False,
            "runtime_downloads": False,
            "remote_fallback": False,
        }

    def _snapshot_request(
        self,
        job_id: str,
        source_id: str,
        *,
        limits: EmailLimits | None = None,
    ) -> tuple[dict[str, Any], Any, Any]:
        selected = limits or EmailLimits()
        config = self.sources.source_config(source_id, require_enabled=True)
        adapter = adapter_for_profile(config)
        snapshot = adapter.snapshot(limits=selected)
        request = self._request_record(job_id, source_id, snapshot, selected)
        return request, adapter, snapshot

    def queue(
        self,
        source_id: str,
        *,
        request_key: str | None = None,
    ) -> dict[str, Any]:
        limits = EmailLimits()
        config = self.sources.source_config(source_id, require_enabled=True)
        adapter = adapter_for_profile(config)
        snapshot = adapter.snapshot(limits=limits)
        policy = self.sync_policy(source_id)
        identity_material = (
            f"{source_id}\x1f{snapshot.container_identity_sha256}\x1f"
            f"{snapshot.snapshot_sha256}\x1f{EMAIL_ADAPTER_ID}\x1f"
            f"{EMAIL_ADAPTER_VERSION}\x1f{EMAIL_PARSER_ID}\x1f"
            f"{EMAIL_PARSER_VERSION}\x1f{EMAIL_CONTRACT_VERSION}\x1f"
            f"{settings_fingerprint(limits)}"
        )
        if request_key is not None:
            caller_key = request_key.strip()
            if not caller_key or len(caller_key) > 200:
                raise EmailContractError(
                    "email_internal_error", "email intake idempotency key is invalid"
                )
            identity_material = f"{identity_material}\x1f{caller_key}"
        provisional_key = hashlib.sha256(identity_material.encode()).hexdigest()
        try:
            queued = self.scheduler.run_now(
                str(policy["id"]),
                request_key=provisional_key,
            )
        except SchedulerError as exc:
            raise EmailContractError(
                "email_internal_error", "email intake could not be queued"
            ) from exc
        job = queued["job"]
        request = self._request_record(str(job["id"]), source_id, snapshot, limits)
        request_path = self.requests / f"{job['id']}.json"
        if request_path.is_file():
            current = self._read_json(request_path)
            stable_fields = set(request) - {"requested_at"}
            if any(current.get(key) != request.get(key) for key in stable_fields):
                raise EmailContractError(
                    "email_internal_error", "email intake request is immutable"
                )
            request = current
        else:
            self._write_immutable_json(request_path, request)
        return {
            "schema_version": EMAIL_JOB_SCHEMA_VERSION,
            "created": bool(queued["created"]),
            "job": public_job_record(job),
            "request": {
                key: request[key]
                for key in (
                    "source_id",
                    "mailbox_format",
                    "profile",
                    "container_identity_sha256",
                    "container_snapshot_sha256",
                    "message_count",
                    "total_bytes",
                    "settings_sha256",
                    "network_used",
                )
            },
        }

    def _request_for_job(self, job: Mapping[str, Any]) -> tuple[dict[str, Any], Any, Any]:
        job_id = str(job["id"])
        source_id = str(job["scope"]["id"])
        path = self.requests / f"{job_id}.json"
        if path.is_file():
            request = self._read_json(path)
            limits = EmailLimits.from_mapping(request.get("limits"))
            config = self.sources.source_config(source_id, require_enabled=True)
            adapter = adapter_for_profile(config)
            snapshot = adapter.snapshot(limits=limits)
            if (
                request.get("job_id") != job_id
                or request.get("source_id") != source_id
                or request.get("container_identity_sha256")
                != snapshot.container_identity_sha256
                or request.get("container_snapshot_sha256") != snapshot.snapshot_sha256
                or request.get("settings_sha256") != settings_fingerprint(limits)
            ):
                raise EmailContractError(
                    "email_input_changed", "email Source changed after intake was queued"
                )
            return request, adapter, snapshot

        if job.get("reason") not in {"scheduled", "coalesced", "catch_up", "manual"}:
            raise EmailContractError(
                "email_internal_error", "email intake request is missing"
            )
        request, adapter, snapshot = self._snapshot_request(job_id, source_id)
        self._write_immutable_json(path, request)
        return request, adapter, snapshot

    def _cancel_requested(self, job_id: str) -> bool:
        path = self.cancellations / f"{job_id}.json"
        if not path.exists():
            return False
        value = self._read_json(path, limit=64 * 1024)
        if set(value) != {"schema_version", "job_id", "requested_at"} or value.get(
            "job_id"
        ) != job_id:
            raise EmailContractError(
                "email_internal_error", "email cancellation marker is invalid"
            )
        return True

    def _manifests(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for artifact in self.store.list_derived_artifacts():
            if (
                artifact.get("kind") != EMAIL_BUNDLE_KIND
                or artifact.get("generator") != EMAIL_BUNDLE_GENERATOR
            ):
                continue
            try:
                path = safe_instance_path(self.store.paths.root, artifact["storage_ref"])
                payload = path.read_bytes()
            except (KeyError, OSError, UnsafePathError):
                continue
            if (
                path.is_symlink()
                or hashlib.sha256(payload).hexdigest() != artifact.get("checksum")
            ):
                continue
            try:
                value = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(value, dict)
                and value.get("kind") == EMAIL_BUNDLE_KIND
                and value.get("status") == "complete"
                and value.get("complete") is True
                and value.get("active_content_executed") is False
                and value.get("network_used") is False
            ):
                result.append(value)
        return result

    def _stage_record(
        self,
        transaction: AtomicInstanceCommit,
        kind: str,
        value: Any,
        *,
        immutable: bool = True,
    ) -> None:
        transaction.add(
            f"knowledge/{kind}/{value.id}.json",
            _json_record(value),
            immutable=immutable,
        )

    def _stage_edge(
        self,
        transaction: AtomicInstanceCommit,
        edge: ProvenanceEdge,
        *,
        derived: bool = False,
    ) -> None:
        directory = (
            self.store.paths.derived_provenance
            if derived
            else self.store.paths.canonical_dir("provenance")
        )
        existing_path = directory / f"{edge.id}.json"
        if existing_path.is_file():
            current = self._read_json(existing_path)
            expected = asdict(edge)
            expected["created_at"] = current.get("created_at")
            if current != expected:
                raise EmailContractError(
                    "email_internal_error", "email provenance identity is inconsistent"
                )
            return
        relative = (
            f"state/derived/provenance/{edge.id}.json"
            if derived
            else f"knowledge/provenance/{edge.id}.json"
        )
        transaction.add(relative, _json_record(edge), immutable=True)

    def _attachment_rows(
        self,
        parsed: ParsedEmail,
        *,
        source_id: str,
        message_id: str,
        document_id: str,
        version_id: str,
        accepted_at: str,
    ) -> tuple[list[dict[str, Any]], list[tuple[EmailAttachmentEvidence, bytes, Original]]]:
        settings = ocr_settings_from_config(self.store.read_config())
        rows: list[dict[str, Any]] = []
        values: list[tuple[EmailAttachmentEvidence, bytes, Original]] = []
        for attachment in parsed.attachments:
            part_identity = attachment_part_identity(
                attachment.part_id, attachment.part_path
            )
            attachment_id = email_attachment_evidence_id(
                source_id,
                message_id,
                part_identity,
                attachment.sha256,
                attachment.size_bytes,
            )
            original = _original_record(
                attachment.sha256,
                attachment.size_bytes,
                created_at=accepted_at,
            )
            evidence = EmailAttachmentEvidence(
                schema_version=EMAIL_EVIDENCE_SCHEMA_VERSION,
                id=attachment_id,
                source_id=source_id,
                parent_message_id=message_id,
                parent_document_id=document_id,
                parent_version_id=version_id,
                part_identity_sha256=part_identity,
                original_id=original.id,
                original_sha256=attachment.sha256,
                size_bytes=attachment.size_bytes,
                accepted_at=accepted_at,
            )
            media_supported = attachment.media_type in OCR_SUPPORTED_INPUTS
            signature_matches = _signature_matches(
                attachment.media_type, attachment.data[:16]
            )
            rows.append(
                {
                    "id": attachment_id,
                    "part_id": attachment.part_id,
                    "part_path": attachment.part_path,
                    "part_identity_sha256": part_identity,
                    "original_id": original.id,
                    "sha256": attachment.sha256,
                    "size_bytes": attachment.size_bytes,
                    "media_type": attachment.media_type,
                    "disposition": attachment.disposition,
                    "content_id": attachment.content_id,
                    "filename": attachment.filename,
                    "filename_is_untrusted": attachment.filename is not None,
                    "original_authoritative": True,
                    "ocr": {
                        "eligible": media_supported and signature_matches,
                        "media_type_supported": media_supported,
                        "signature_matches": signature_matches,
                        "configured_mode": settings.mode,
                        "execution_requested": False,
                        "execution_started": False,
                    },
                }
            )
            values.append((evidence, attachment.data, original))
        return rows, values

    def _bundle_plan(
        self,
        parsed: ParsedEmail,
        observed: ObservedMessageBytes,
        *,
        job_id: str,
        message_id: str,
        observation_id: str,
        acquisition_id: str,
        document_id: str,
        version_id: str,
        original_id: str,
        settings_sha256: str,
        attachment_rows: Sequence[Mapping[str, Any]],
    ) -> EmailDerivedPlan:
        arguments = {
            "parsed": parsed,
            "job_id": job_id,
            "source_id": observed.source_id,
            "message_id": message_id,
            "observation_id": observation_id,
            "acquisition_id": acquisition_id,
            "document_id": document_id,
            "version_id": version_id,
            "original_id": original_id,
            "observed_at": observed.observed_at,
            "acquired_at": observed.acquired_at,
            "container_identity_sha256": observed.container_identity_sha256,
            "snapshot_sha256": observed.snapshot_sha256,
            "locator_sha256": observed.locator_sha256,
            "filesystem_identity_sha256": observed.filesystem.fingerprint(),
            "filesystem_mtime_ns": observed.filesystem.mtime_ns,
            "adapter": {
                "adapter_id": EMAIL_ADAPTER_ID,
                "adapter_version": EMAIL_ADAPTER_VERSION,
                "network_access": "none",
            },
            "settings_sha256": settings_sha256,
            "attachments": attachment_rows,
        }
        preliminary = build_email_bundle(**arguments)
        manifests = [
            item
            for item in self._manifests()
            if item.get("message", {}).get("id") != message_id
        ]
        _threads, observations = observed_threads([*manifests, preliminary.manifest])
        thread = observations.get(message_id)
        warning_codes = list(thread.get("warning_codes", [])) if thread else []
        return build_email_bundle(
            **arguments,
            identity_warnings=warning_codes,
            thread_observation=thread,
        )

    def _commit_message(
        self,
        *,
        job_id: str,
        observed: ObservedMessageBytes,
        parsed: ParsedEmail,
        settings_sha256: str,
        recheck: Callable[[], Any],
        attachment_checkpoint: Callable[[str, int], None] | None = None,
    ) -> tuple[str, str]:
        message_id = email_message_evidence_id(
            observed.source_id, observed.sha256, observed.size_bytes
        )
        observation_id = email_message_observation_id(
            observed.source_id,
            EMAIL_ADAPTER_ID,
            EMAIL_ADAPTER_VERSION,
            observed.container_identity_sha256,
            observed.snapshot_sha256,
            observed.locator_sha256,
            observed.sha256,
            observed.size_bytes,
            settings_sha256,
        )
        if self.store.read_canonical("email-observations", observation_id) is not None:
            return "skipped", message_id

        acquired_at = observed.acquired_at
        acquisition_id = _acquisition_id(observation_id)
        document_id = _document_id(message_id)
        version_id = _version_id(document_id)
        original = _original_record(
            observed.sha256, observed.size_bytes, created_at=acquired_at
        )
        existing_message = self.store.read_canonical("email-messages", message_id)
        first_acquired_at = (
            str(existing_message["first_acquired_at"])
            if existing_message is not None
            else acquired_at
        )
        message = EmailMessageEvidence(
            schema_version=EMAIL_EVIDENCE_SCHEMA_VERSION,
            id=message_id,
            source_id=observed.source_id,
            document_id=document_id,
            version_id=version_id,
            original_id=original.id,
            original_sha256=observed.sha256,
            size_bytes=observed.size_bytes,
            adapter_id=EMAIL_ADAPTER_ID,
            adapter_version=EMAIL_ADAPTER_VERSION,
            parser_id=EMAIL_PARSER_ID,
            parser_version=EMAIL_PARSER_VERSION,
            contract_version=EMAIL_CONTRACT_VERSION,
            settings_sha256=settings_sha256,
            first_acquired_at=first_acquired_at,
        )
        if existing_message is not None and existing_message != asdict(message):
            raise EmailContractError(
                "email_internal_error", "email message evidence is inconsistent"
            )
        observation = EmailMessageObservation(
            schema_version=EMAIL_EVIDENCE_SCHEMA_VERSION,
            id=observation_id,
            source_id=observed.source_id,
            message_id=message_id,
            acquisition_id=acquisition_id,
            container_identity_sha256=observed.container_identity_sha256,
            container_snapshot_sha256=observed.snapshot_sha256,
            locator_sha256=observed.locator_sha256,
            filesystem_identity_sha256=observed.filesystem.fingerprint(),
            filesystem_mtime_ns=observed.filesystem.mtime_ns,
            observed_at=observed.observed_at,
            acquired_at=acquired_at,
            adapter_id=EMAIL_ADAPTER_ID,
            adapter_version=EMAIL_ADAPTER_VERSION,
            settings_sha256=settings_sha256,
        )
        acquisition = Acquisition(
            id=acquisition_id,
            source_id=observed.source_id,
            locator=f"email-locator:sha256:{observed.locator_sha256}",
            observed_at=observed.observed_at,
            content_hash=observed.sha256,
            outcome="unchanged" if existing_message is not None else "created",
            document_id=document_id,
            version_id=version_id,
            error=None,
            acquisition_kind="local_email",
            media_type="message/rfc822",
            original_id=original.id,
            response_size_bytes=observed.size_bytes,
            exact_duplicate=existing_message is not None,
        )
        document = Document(
            id=document_id,
            source_id=observed.source_id,
            locator=f"email-message:{message_id}",
            title=f"Local email message {message_id}",
            media_type="message/rfc822",
            created_at=first_acquired_at,
            current_version_id=version_id,
        )
        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            sequence=1,
            content_hash=observed.sha256,
            original_id=original.id,
            media_type="message/rfc822",
            size_bytes=observed.size_bytes,
            acquired_at=first_acquired_at,
        )
        attachment_rows, attachment_values = self._attachment_rows(
            parsed,
            source_id=observed.source_id,
            message_id=message_id,
            document_id=document_id,
            version_id=version_id,
            accepted_at=first_acquired_at,
        )
        plan = self._bundle_plan(
            parsed,
            observed,
            job_id=job_id,
            message_id=message_id,
            observation_id=observation_id,
            acquisition_id=acquisition_id,
            document_id=document_id,
            version_id=version_id,
            original_id=original.id,
            settings_sha256=settings_sha256,
            attachment_rows=attachment_rows,
        )

        recheck()
        transaction = AtomicInstanceCommit(
            self.store,
            InstanceLifecycleManager(self.store).control_root / "transactions",
            profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
            owner_id=job_id,
        )
        transaction.add(original.storage_ref, observed.data, immutable=True)
        if self.store.read_canonical("originals", original.id) is None:
            self._stage_record(transaction, "originals", original)
        if existing_message is None:
            self._stage_record(transaction, "documents", document)
            self._stage_record(transaction, "versions", version)
            self._stage_record(transaction, "email-messages", message)
        self._stage_record(transaction, "acquisitions", acquisition)
        self._stage_record(transaction, "email-observations", observation)

        for index, (evidence, data, child_original) in enumerate(attachment_values):
            transaction.add(child_original.storage_ref, data, immutable=True)
            if self.store.read_canonical("originals", child_original.id) is None:
                self._stage_record(transaction, "originals", child_original)
            existing_attachment = self.store.read_canonical(
                "email-attachments", evidence.id
            )
            if existing_attachment is None:
                self._stage_record(transaction, "email-attachments", evidence)
            elif existing_attachment != asdict(evidence):
                raise EmailContractError(
                    "email_internal_error", "email attachment evidence is inconsistent"
                )
            if attachment_checkpoint is not None:
                attachment_checkpoint(evidence.id, index + 1)

        edges = [
            stable_edge(
                "source",
                observed.source_id,
                "observed",
                "acquisition",
                acquisition_id,
                created_at=acquired_at,
            ),
            stable_edge(
                "acquisition",
                acquisition_id,
                "captured",
                "original",
                original.id,
                created_at=acquired_at,
            ),
            stable_edge(
                "acquisition",
                acquisition_id,
                "matched",
                "version",
                version_id,
                created_at=acquired_at,
            ),
            stable_edge(
                "original",
                original.id,
                "materialized_as",
                "version",
                version_id,
                created_at=first_acquired_at,
            ),
            stable_edge(
                "version",
                version_id,
                "version_of",
                "document",
                document_id,
                created_at=first_acquired_at,
            ),
            stable_edge(
                "acquisition",
                acquisition_id,
                "observed_as",
                "email_message",
                message_id,
                created_at=acquired_at,
            ),
        ]
        for edge in edges:
            self._stage_edge(transaction, edge)
        for evidence, _data, child_original in attachment_values:
            self._stage_edge(
                transaction,
                stable_edge(
                    "email_message",
                    message_id,
                    "contained",
                    "email_attachment",
                    evidence.id,
                    created_at=first_acquired_at,
                ),
            )
            self._stage_edge(
                transaction,
                stable_edge(
                    "email_attachment",
                    evidence.id,
                    "materialized_as",
                    "original",
                    child_original.id,
                    created_at=first_acquired_at,
                ),
            )

        bundle_exists = any(
            item.get("version_id") == version_id
            and item.get("kind") == EMAIL_BUNDLE_KIND
            and item.get("generator") == EMAIL_BUNDLE_GENERATOR
            for item in self.store.list_derived_artifacts()
        )
        if not bundle_exists:
            transaction.add(plan.manifest_relative, plan.manifest_bytes, immutable=True)
            transaction.add(
                f"state/derived/artifacts/{plan.bundle_artifact.id}.json",
                _json_record(plan.bundle_artifact),
                immutable=True,
            )
            if plan.body_relative is not None and plan.body_bytes is not None:
                transaction.add(plan.body_relative, plan.body_bytes, immutable=True)
            if plan.text_artifact is not None:
                transaction.add(
                    f"state/derived/artifacts/{plan.text_artifact.id}.json",
                    _json_record(plan.text_artifact),
                    immutable=True,
                )
            for edge in plan.derived_edges:
                self._stage_edge(transaction, edge, derived=True)
        try:
            transaction.commit()
        except AtomicCommitError as exc:
            raise EmailContractError(
                "email_internal_error", "email acquisition failed its atomic promotion"
            ) from exc
        self._refresh_index_after_derived_change(document_id)
        return "processed", message_id

    def _work_record(
        self,
        job_id: str,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        path = self.work / f"{job_id}.json"
        if path.is_file():
            value = self._read_json(path)
            if (
                value.get("schema_version") != EMAIL_JOB_SCHEMA_VERSION
                or value.get("job_id") != job_id
                or value.get("source_id") != request.get("source_id")
                or value.get("container_snapshot_sha256")
                != request.get("container_snapshot_sha256")
                or value.get("settings_sha256") != request.get("settings_sha256")
                or not isinstance(value.get("items"), dict)
            ):
                raise EmailContractError(
                    "email_internal_error", "email intake work journal is invalid"
                )
            return value
        return {
            "schema_version": EMAIL_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            "source_id": request["source_id"],
            "container_snapshot_sha256": request["container_snapshot_sha256"],
            "settings_sha256": request["settings_sha256"],
            "items": {},
            "updated_at": utc_now(),
            "network_used": False,
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
        if status not in _EMAIL_RUN_STATUSES:
            raise EmailContractError(
                "email_internal_error", "email intake run status is invalid"
            )
        selected_codes = [
            code for code in dict.fromkeys(error_codes) if code in EMAIL_ERROR_CODES
        ]
        value = {
            "schema_version": EMAIL_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            "source_id": request["source_id"],
            "container_identity_sha256": request["container_identity_sha256"],
            "container_snapshot_sha256": request["container_snapshot_sha256"],
            "settings_sha256": request["settings_sha256"],
            "status": status,
            "progress": dict(progress),
            "error_codes": selected_codes,
            "updated_at": utc_now(),
            "network_used": False,
            "automatic_deletion": False,
        }
        self._write_json(self.runs / f"{job_id}.json", value)
        return value

    def execute(
        self,
        job: Mapping[str, Any],
        *,
        checkpoint: _CHECKPOINT | None = None,
    ) -> dict[str, int]:
        if (
            job.get("job_kind") != EMAIL_JOB_KIND
            or job.get("status") != "running"
            or not isinstance(job.get("lease"), Mapping)
        ):
            raise EmailContractError(
                "email_internal_error", "email scheduler job is not claimed"
            )
        job_id = str(job["id"])
        request, adapter, snapshot = self._request_for_job(job)
        limits = EmailLimits.from_mapping(request["limits"])
        settings_sha256 = settings_fingerprint(limits)
        if settings_sha256 != request["settings_sha256"]:
            raise EmailContractError(
                "email_internal_error", "email intake settings identity is invalid"
            )
        work = self._work_record(job_id, request)
        progress = {
            "processed": sum(
                1
                for item in work["items"].values()
                if isinstance(item, Mapping) and item.get("status") == "processed"
            ),
            "skipped": sum(
                1
                for item in work["items"].values()
                if isinstance(item, Mapping) and item.get("status") == "skipped"
            ),
            "errors": sum(
                1
                for item in work["items"].values()
                if isinstance(item, Mapping) and item.get("status") == "error"
            ),
        }
        scheduler_progress = job.get("progress", {})
        if any(
            int(scheduler_progress.get(key, 0)) > progress[key]
            for key in ("processed", "skipped", "errors")
        ):
            raise EmailContractError(
                "email_internal_error",
                "email scheduler progress exceeds its durable work journal",
            )
        decoded_bytes = sum(
            int(item.get("decoded_bytes", 0))
            for item in work["items"].values()
            if isinstance(item, Mapping)
            and item.get("status") in {"processed", "skipped"}
        )
        errors = [
            str(item["error_code"])
            for item in work["items"].values()
            if isinstance(item, Mapping)
            and item.get("status") == "error"
            and item.get("error_code") in EMAIL_ERROR_CODES
        ]
        self._write_run(
            job_id,
            request,
            status="running",
            progress=progress,
            error_codes=errors,
        )
        deadline = time.monotonic() + limits.max_seconds_per_job

        for candidate in snapshot.candidates:
            if self._cancel_requested(job_id):
                self._write_run(
                    job_id,
                    request,
                    status="cancelled",
                    progress=progress,
                    error_codes=[*errors, "email_cancelled"],
                )
                raise EmailContractError(
                    "email_cancelled", "email intake was cancelled cooperatively"
                )
            if time.monotonic() >= deadline:
                self._write_run(
                    job_id,
                    request,
                    status="running",
                    progress=progress,
                    error_codes=[*errors, "email_timeout"],
                )
                raise EmailContractError(
                    "email_timeout", "email intake job deadline was exceeded"
                )
            locator_key = str(candidate.locator_sha256)
            prior = work["items"].get(locator_key)
            if isinstance(prior, Mapping) and prior.get("status") in {
                "processed",
                "skipped",
            }:
                continue
            try:
                observed = adapter.read_exact(candidate, limits=limits)
                item_key = _item_idempotency_key(
                    observed, settings_sha256=settings_sha256
                )
                message_deadline = min(
                    deadline,
                    time.monotonic() + limits.max_seconds_per_message,
                )
                parsed = self.parser.parse(
                    observed.data,
                    limits=limits,
                    deadline=message_deadline,
                )
                if (
                    parsed.total_decoded_bytes
                    > limits.max_decoded_bytes_per_run - decoded_bytes
                ):
                    raise EmailContractError(
                        "email_decoded_limit_exceeded",
                        "email run decoded-byte limit was exceeded",
                    )

                def attachment_checkpoint(
                    attachment_id: str,
                    sequence: int,
                    *,
                    selected_locator: str = locator_key,
                    selected_key: str = item_key,
                    selected_observed: ObservedMessageBytes = observed,
                    selected_parsed: ParsedEmail = parsed,
                ) -> None:
                    work["items"][selected_locator] = {
                        "idempotency_key": selected_key,
                        "status": "prepared",
                        "message_sha256": selected_observed.sha256,
                        "message_size_bytes": selected_observed.size_bytes,
                        "decoded_bytes": selected_parsed.total_decoded_bytes,
                        "attachment_checkpoint": {
                            "sequence": sequence,
                            "attachment_id": attachment_id,
                            "status": "prepared",
                        },
                    }
                    self._write_work(job_id, work)

                outcome, message_id = self._commit_message(
                    job_id=job_id,
                    observed=observed,
                    parsed=parsed,
                    settings_sha256=settings_sha256,
                    recheck=lambda: adapter.recheck(snapshot, limits=limits),
                    attachment_checkpoint=attachment_checkpoint,
                )
                decoded_bytes += parsed.total_decoded_bytes
                progress[outcome] += 1
                work["items"][locator_key] = {
                    "idempotency_key": item_key,
                    "status": outcome,
                    "message_id": message_id,
                    "message_sha256": observed.sha256,
                    "message_size_bytes": observed.size_bytes,
                    "decoded_bytes": parsed.total_decoded_bytes,
                    "attachment_checkpoint": {
                        "sequence": len(parsed.attachments),
                        "status": "committed",
                    },
                }
                self._write_work(job_id, work)
            except EmailContractError as exc:
                if exc.code in {"email_cancelled", "email_timeout"}:
                    raise
                errors.append(exc.code)
                progress["errors"] += 1
                work["items"][locator_key] = {
                    "status": "error",
                    "error_code": exc.code,
                }
                self._write_work(job_id, work)
                if progress["errors"] > limits.max_errors_per_run:
                    raise EmailContractError(
                        "email_message_limit_exceeded",
                        "email run error limit was exceeded",
                    ) from exc
            if checkpoint is not None:
                checkpoint(dict(progress))

        final_status = "completed_with_errors" if progress["errors"] else "completed"
        self._write_run(
            job_id,
            request,
            status=final_status,
            progress=progress,
            error_codes=errors,
        )
        return progress

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.scheduler.get_job(job_id)
        if job is None or job.get("job_kind") != EMAIL_JOB_KIND:
            raise EmailContractError("email_internal_error", "email job was not found")
        if job["status"] == "running":
            marker = {
                "schema_version": EMAIL_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "requested_at": utc_now(),
            }
            self._write_immutable_json(
                self.cancellations / f"{job_id}.json", marker
            )
            return {
                "schema_version": EMAIL_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "status": "cancellation_requested",
            }
        if job["status"] in _TERMINAL_SCHEDULER_STATUSES:
            return public_job_record(job)
        try:
            return public_job_record(self.scheduler.cancel(job_id))
        except SchedulerConflictError as exc:
            raise EmailContractError(
                "email_internal_error", "email job cancellation conflicted"
            ) from exc

    def _run_for_job(self, job_id: str) -> dict[str, Any] | None:
        path = self.runs / f"{job_id}.json"
        return self._read_json(path) if path.is_file() else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.scheduler.get_job(job_id)
        if job is None or job.get("job_kind") != EMAIL_JOB_KIND:
            return None
        return {**public_job_record(job), "intake_run": self._run_for_job(job_id)}

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        selected = [
            item
            for item in self.scheduler.list_jobs(limit=500)
            if item.get("job_kind") == EMAIL_JOB_KIND
        ]
        return [
            {
                **public_job_record(item),
                "intake_run": self._run_for_job(str(item["id"])),
            }
            for item in selected[: max(0, min(limit, 500))]
        ]

    def _bundle_for_message(self, message_id: str) -> dict[str, Any] | None:
        matches = [
            item
            for item in self._manifests()
            if item.get("message", {}).get("id") == message_id
        ]
        if len(matches) > 1:
            matches.sort(
                key=lambda item: (
                    str(item.get("timestamps", {}).get("acquired_at", "")),
                    str(item.get("derivation_key", "")),
                ),
                reverse=True,
            )
        return matches[0] if matches else None

    def _message_summary(
        self,
        message: Mapping[str, Any],
        manifest: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        message_id = str(message["id"])
        observations = [
            item
            for item in self.store.list_canonical("email-observations")
            if item.get("message_id") == message_id
        ]
        result: dict[str, Any] = {
            "schema_version": EMAIL_JOB_SCHEMA_VERSION,
            "id": message_id,
            "source_id": message["source_id"],
            "document_id": message["document_id"],
            "version_id": message["version_id"],
            "original_id": message["original_id"],
            "original_sha256": message["original_sha256"],
            "size_bytes": message["size_bytes"],
            "first_acquired_at": message["first_acquired_at"],
            "observation_count": len(observations),
            "derived_status": "available" if manifest is not None else "removed",
            "original_authoritative": True,
            "network_used": False,
        }
        if manifest is not None:
            result.update(
                {
                    "timestamps": manifest.get("timestamps"),
                    "envelope": manifest.get("envelope"),
                    "declared_identity": manifest.get("declared_identity"),
                    "body": manifest.get("body"),
                    "mime_tree": manifest.get("mime_tree"),
                    "attachments": manifest.get("attachments"),
                    "thread_observation": manifest.get("thread_observation"),
                    "parser": manifest.get("parser"),
                    "adapter": manifest.get("adapter"),
                    "warnings": manifest.get("warnings"),
                    "identity_warnings": manifest.get("identity_warnings"),
                    "active_content_executed": False,
                    "remote_fetch": False,
                }
            )
        return result

    def list_messages(
        self,
        *,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        manifests = {
            str(item["message"]["id"]): item
            for item in self._manifests()
            if isinstance(item.get("message"), Mapping)
        }
        values = [
            item
            for item in self.store.list_canonical("email-messages")
            if source_id is None or item.get("source_id") == source_id
        ]
        values.sort(
            key=lambda item: (str(item["first_acquired_at"]), str(item["id"])),
            reverse=True,
        )
        return [
            self._message_summary(item, manifests.get(str(item["id"])))
            for item in values[: max(0, min(limit, 500))]
        ]

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        message = self.store.read_canonical("email-messages", message_id)
        if message is None:
            return None
        return self._message_summary(message, self._bundle_for_message(message_id))

    def list_threads(
        self,
        *,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        threads, observations = observed_threads(self._manifests())
        result = []
        for thread in threads:
            if source_id is not None and thread["source_id"] != source_id:
                continue
            result.append(
                {
                    **thread,
                    "observations": {
                        message_id: observations[message_id]
                        for message_id in thread["message_ids"]
                        if message_id in observations
                    },
                }
            )
        result.sort(key=lambda item: str(item["id"]))
        return result[: max(0, min(limit, 500))]

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.list_threads(limit=500) if item["id"] == thread_id),
            None,
        )

    def _attachment_manifest_rows(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for manifest in self._manifests():
            message = manifest.get("message")
            for row in manifest.get("attachments", []):
                if isinstance(row, Mapping) and isinstance(row.get("id"), str):
                    result[str(row["id"])] = {
                        **dict(row),
                        "message_id": (
                            message.get("id") if isinstance(message, Mapping) else None
                        ),
                    }
        return result

    def list_attachments(
        self,
        *,
        message_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self._attachment_manifest_rows()
        values = []
        for evidence in self.store.list_canonical("email-attachments"):
            if message_id is not None and evidence.get("parent_message_id") != message_id:
                continue
            derived = rows.get(str(evidence["id"]))
            values.append(
                {
                    **evidence,
                    "derived_status": "available" if derived is not None else "removed",
                    "representation": derived,
                    "original_authoritative": True,
                    "execution_started": False,
                }
            )
        values.sort(key=lambda item: (str(item["accepted_at"]), str(item["id"])))
        return values[: max(0, min(limit, 500))]

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        evidence = self.store.read_canonical("email-attachments", attachment_id)
        if evidence is None:
            return None
        derived = self._attachment_manifest_rows().get(attachment_id)
        return {
            **evidence,
            "derived_status": "available" if derived is not None else "removed",
            "representation": derived,
            "original_authoritative": True,
            "execution_started": False,
        }

    def _derived_records_for_message(
        self, message: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        version_id = str(message["version_id"])
        artifacts = [
            item
            for item in self.store.list_derived_artifacts()
            if item.get("version_id") == version_id
            and item.get("generator") == EMAIL_BUNDLE_GENERATOR
            and item.get("kind") in {EMAIL_BUNDLE_KIND, "extracted_text"}
        ]
        artifact_ids = {str(item["id"]) for item in artifacts}
        edges = [
            item
            for item in self.store.list_derived_provenance()
            if item.get("from_id") in artifact_ids
            or item.get("to_id") in artifact_ids
            or (
                item.get("from_kind") == "email_message"
                and item.get("from_id") == message["id"]
                and item.get("relation") == "represented_by"
            )
        ]
        return artifacts, edges

    def _verified_artifact_path(self, artifact: Mapping[str, Any]) -> Path:
        try:
            path = safe_instance_path(self.store.paths.root, artifact["storage_ref"])
            payload = path.read_bytes()
        except (KeyError, OSError, UnsafePathError) as exc:
            raise EmailContractError(
                "email_derived_invalid", "email derived artifact is unavailable"
            ) from exc
        if (
            path.is_symlink()
            or not path.is_file()
            or hashlib.sha256(payload).hexdigest() != artifact.get("checksum")
        ):
            raise EmailContractError(
                "email_derived_invalid", "email derived artifact failed verification"
            )
        return path

    @staticmethod
    def _remove_empty_parents(path: Path, stop: Path) -> None:
        current = path
        while current != stop and stop in current.parents:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def remove_derived(self, message_id: str) -> dict[str, Any]:
        message = self.store.read_canonical("email-messages", message_id)
        if message is None:
            raise EmailContractError(
                "email_derived_invalid", "email message was not found"
            )
        manifest = self._bundle_for_message(message_id)
        artifacts, edges = self._derived_records_for_message(message)
        if not artifacts:
            return {
                "schema_version": EMAIL_JOB_SCHEMA_VERSION,
                "message_id": message_id,
                "status": "already_removed",
                "removed_artifacts": 0,
                "originals_changed": 0,
                "canonical_records_changed": 0,
            }
        paths = [(item, self._verified_artifact_path(item)) for item in artifacts]
        observation_id = None
        limits: Mapping[str, Any] | None = None
        if manifest is not None:
            message_binding = manifest.get("message")
            parser = manifest.get("parser")
            if isinstance(message_binding, Mapping):
                observation_id = message_binding.get("observation_id")
            if isinstance(parser, Mapping) and isinstance(parser.get("limits"), Mapping):
                limits = dict(parser["limits"])
        removal = {
            "schema_version": EMAIL_JOB_SCHEMA_VERSION,
            "message_id": message_id,
            "version_id": message["version_id"],
            "observation_id": observation_id,
            "settings_sha256": message["settings_sha256"],
            "limits": limits,
            "artifact_ids": sorted(str(item["id"]) for item in artifacts),
            "status": "prepared",
            "prepared_at": utc_now(),
            "completed_at": None,
            "network_used": False,
            "originals_changed": 0,
            "canonical_records_changed": 0,
        }
        removal_path = self.removals / f"{message_id}.json"
        self._write_json(removal_path, removal)
        for artifact, path in paths:
            with suppress(FileNotFoundError):
                path.unlink()
            metadata = self.store.paths.derived_artifacts / f"{artifact['id']}.json"
            with suppress(FileNotFoundError):
                metadata.unlink()
            if artifact.get("kind") == EMAIL_BUNDLE_KIND:
                stop = self.store.paths.state / "derived" / "email-messages"
                self._remove_empty_parents(path.parent, stop)
        for edge in edges:
            edge_path = self.store.paths.derived_provenance / f"{edge['id']}.json"
            with suppress(FileNotFoundError):
                edge_path.unlink()
        completed = {
            **removal,
            "status": "completed",
            "completed_at": utc_now(),
        }
        self._write_json(removal_path, completed)
        self._refresh_index_after_derived_change(str(message["document_id"]))
        return {
            "schema_version": EMAIL_JOB_SCHEMA_VERSION,
            "message_id": message_id,
            "status": "removed",
            "removed_artifacts": len(artifacts),
            "removed_provenance_edges": len(edges),
            "originals_changed": 0,
            "canonical_records_changed": 0,
            "rebuildable": limits is not None,
        }

    def _limits_for_rebuild(
        self,
        message: Mapping[str, Any],
        removal: Mapping[str, Any] | None,
    ) -> EmailLimits:
        if removal is not None and isinstance(removal.get("limits"), Mapping):
            selected = EmailLimits.from_mapping(removal["limits"])
            if settings_fingerprint(selected) == message.get("settings_sha256"):
                return selected
        if self.requests.is_dir() and not self.requests.is_symlink():
            for path in sorted(self.requests.glob("*.json")):
                request = self._read_json(path)
                if (
                    request.get("source_id") != message.get("source_id")
                    or request.get("settings_sha256") != message.get("settings_sha256")
                    or not isinstance(request.get("limits"), Mapping)
                ):
                    continue
                selected = EmailLimits.from_mapping(request["limits"])
                if settings_fingerprint(selected) == message.get("settings_sha256"):
                    return selected
        raise EmailContractError(
            "email_derived_invalid",
            "email derivation settings are unavailable for verified rebuild",
        )

    def _observation_for_rebuild(
        self,
        message_id: str,
        removal: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        selected_id = removal.get("observation_id") if removal is not None else None
        if isinstance(selected_id, str):
            selected = self.store.read_canonical("email-observations", selected_id)
            if selected is not None and selected.get("message_id") == message_id:
                return selected
        values = [
            item
            for item in self.store.list_canonical("email-observations")
            if item.get("message_id") == message_id
        ]
        if not values:
            raise EmailContractError(
                "email_derived_invalid", "email observation is unavailable for rebuild"
            )
        values.sort(key=lambda item: (str(item["acquired_at"]), str(item["id"])))
        return values[0]

    def _plan_rebuild(
        self,
        *,
        message: Mapping[str, Any],
        observation: Mapping[str, Any],
        parsed: ParsedEmail,
        limits: EmailLimits,
        attachment_rows: Sequence[Mapping[str, Any]],
    ) -> EmailDerivedPlan:
        job_id = _rebuild_job_id(str(message["id"]), str(message["settings_sha256"]))
        arguments = {
            "parsed": parsed,
            "job_id": job_id,
            "source_id": message["source_id"],
            "message_id": message["id"],
            "observation_id": observation["id"],
            "acquisition_id": observation["acquisition_id"],
            "document_id": message["document_id"],
            "version_id": message["version_id"],
            "original_id": message["original_id"],
            "observed_at": observation["observed_at"],
            "acquired_at": observation["acquired_at"],
            "container_identity_sha256": observation["container_identity_sha256"],
            "snapshot_sha256": observation["container_snapshot_sha256"],
            "locator_sha256": observation["locator_sha256"],
            "filesystem_identity_sha256": observation["filesystem_identity_sha256"],
            "filesystem_mtime_ns": observation["filesystem_mtime_ns"],
            "adapter": {
                "adapter_id": observation["adapter_id"],
                "adapter_version": observation["adapter_version"],
                "network_access": "none",
            },
            "settings_sha256": settings_fingerprint(limits),
            "attachments": attachment_rows,
        }
        preliminary = build_email_bundle(**arguments)
        manifests = [
            item
            for item in self._manifests()
            if item.get("message", {}).get("id") != message["id"]
        ]
        _threads, observations = observed_threads([*manifests, preliminary.manifest])
        thread = observations.get(str(message["id"]))
        warnings = list(thread.get("warning_codes", [])) if thread else []
        return build_email_bundle(
            **arguments,
            identity_warnings=warnings,
            thread_observation=thread,
        )

    def rebuild_derived(self, message_id: str) -> dict[str, Any]:
        message = self.store.read_canonical("email-messages", message_id)
        if message is None:
            raise EmailContractError(
                "email_derived_invalid", "email message was not found"
            )
        if self._bundle_for_message(message_id) is not None:
            return {
                "schema_version": EMAIL_JOB_SCHEMA_VERSION,
                "message_id": message_id,
                "status": "already_available",
                "originals_changed": 0,
                "canonical_records_changed": 0,
            }
        removal_path = self.removals / f"{message_id}.json"
        removal = self._read_json(removal_path) if removal_path.is_file() else None
        limits = self._limits_for_rebuild(message, removal)
        observation = self._observation_for_rebuild(message_id, removal)
        try:
            original_bytes = self.store.original_bytes(str(message["original_id"]))
        except (KeyError, OSError) as exc:
            raise EmailContractError(
                "email_derived_invalid", "email Original is unavailable for rebuild"
            ) from exc
        if (
            len(original_bytes) != message["size_bytes"]
            or hashlib.sha256(original_bytes).hexdigest()
            != message["original_sha256"]
        ):
            raise EmailContractError(
                "email_derived_invalid", "email Original failed rebuild verification"
            )
        parsed = self.parser.parse(original_bytes, limits=limits)
        attachment_rows, attachment_values = self._attachment_rows(
            parsed,
            source_id=str(message["source_id"]),
            message_id=message_id,
            document_id=str(message["document_id"]),
            version_id=str(message["version_id"]),
            accepted_at=str(message["first_acquired_at"]),
        )
        for evidence, data, original in attachment_values:
            current = self.store.read_canonical("email-attachments", evidence.id)
            original_record = self.store.read_canonical("originals", original.id)
            try:
                stored = self.store.original_bytes(original.id)
            except (KeyError, OSError) as exc:
                raise EmailContractError(
                    "email_derived_invalid",
                    "email attachment Original is unavailable for rebuild",
                ) from exc
            if (
                current != asdict(evidence)
                or original_record is None
                or stored != data
                or hashlib.sha256(stored).hexdigest() != original.sha256
            ):
                raise EmailContractError(
                    "email_derived_invalid",
                    "email attachment evidence failed rebuild verification",
                )
        plan = self._plan_rebuild(
            message=message,
            observation=observation,
            parsed=parsed,
            limits=limits,
            attachment_rows=attachment_rows,
        )
        owner_id = _rebuild_job_id(message_id, str(message["settings_sha256"]))
        transaction = AtomicInstanceCommit(
            self.store,
            InstanceLifecycleManager(self.store).control_root / "transactions",
            profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
            owner_id=owner_id,
        )
        transaction.add(plan.manifest_relative, plan.manifest_bytes, immutable=True)
        transaction.add(
            f"state/derived/artifacts/{plan.bundle_artifact.id}.json",
            _json_record(plan.bundle_artifact),
            immutable=True,
        )
        if plan.body_relative is not None and plan.body_bytes is not None:
            transaction.add(plan.body_relative, plan.body_bytes, immutable=True)
        if plan.text_artifact is not None:
            transaction.add(
                f"state/derived/artifacts/{plan.text_artifact.id}.json",
                _json_record(plan.text_artifact),
                immutable=True,
            )
        for edge in plan.derived_edges:
            self._stage_edge(transaction, edge, derived=True)
        try:
            transaction.commit()
        except AtomicCommitError as exc:
            raise EmailContractError(
                "email_internal_error", "email rebuild failed its atomic promotion"
            ) from exc
        if removal is not None:
            self._write_json(
                removal_path,
                {
                    **removal,
                    "status": "rebuilt",
                    "rebuilt_at": utc_now(),
                },
            )
        self._refresh_index_after_derived_change(str(message["document_id"]))
        return {
            "schema_version": EMAIL_JOB_SCHEMA_VERSION,
            "message_id": message_id,
            "status": "rebuilt",
            "bundle_artifact_id": plan.bundle_artifact.id,
            "body_artifact_id": (
                plan.text_artifact.id if plan.text_artifact is not None else None
            ),
            "originals_changed": 0,
            "canonical_records_changed": 0,
            "network_used": False,
        }

    def _refresh_index_after_derived_change(
        self,
        document_id: str | None = None,
    ) -> None:
        index_path = self.store.paths.indexes / "search.sqlite3"
        metadata_path = self.store.paths.indexes / "search.meta.json"
        if not index_path.exists() and not metadata_path.exists():
            return
        from .index import rebuild_search_index, refresh_search_index

        if document_id is None:
            rebuild_search_index(self.store, recover_missing_derived=False)
        else:
            refresh_search_index(
                self.store,
                [document_id],
                recover_missing_derived=False,
            )


__all__ = [
    "EMAIL_CONTRACT_VERSION",
    "EMAIL_JOB_KIND",
    "EMAIL_JOB_SCHEMA_VERSION",
    "EmailJobManager",
]
