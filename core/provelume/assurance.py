from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from .domain import (
    EMAIL_EVIDENCE_SCHEMA_VERSION,
    email_attachment_evidence_id,
    email_message_evidence_id,
    email_message_observation_id,
)
from .operations import OperationLedger
from .paths import safe_instance_path
from .storage import InstanceStore

ASSURANCE_SCHEMA_VERSION = 1
MAX_ASSURANCE_RECORDS_PER_KIND = 10_000
MAX_ASSURANCE_FINDINGS = 1_000
_REPORT_ID = re.compile(r"assurance_[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class AssuranceLimitError(RuntimeError):
    pass


def safe_canonical_records(
    store: InstanceStore,
    kind: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read bounded canonical records without one malformed file aborting a check."""

    directory = store.paths.canonical_dir(kind)
    if not directory.exists():
        return [], []
    paths = sorted(directory.glob("*.json"), key=lambda item: item.name)
    if len(paths) > MAX_ASSURANCE_RECORDS_PER_KIND:
        raise AssuranceLimitError(
            f"{kind} exceeds the {MAX_ASSURANCE_RECORDS_PER_KIND}-record safety limit"
        )
    records: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            findings.append(
                {
                    "severity": "error",
                    "code": "canonical_record_unreadable",
                    "message": f"Unreadable canonical {kind} record: {path.name}",
                    "related": {"kind": kind, "record": path.name},
                }
            )
            continue
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            findings.append(
                {
                    "severity": "error",
                    "code": "canonical_record_invalid",
                    "message": f"Invalid canonical {kind} record: {path.name}",
                    "related": {"kind": kind, "record": path.name},
                }
            )
            continue
        if path.stem != value["id"]:
            findings.append(
                {
                    "severity": "error",
                    "code": "canonical_identity_mismatch",
                    "message": (
                        f"Canonical {kind} filename and ID do not match: {path.name}"
                    ),
                    "related": {
                        "kind": kind,
                        "record": path.name,
                        "record_id": str(value["id"]),
                    },
                }
            )
            continue
        records.append(value)
    return records, findings


class OriginalAssuranceManager:
    """Verify canonical references and Original bytes without repairing state."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.reports = store.paths.state / "assurance" / "reports"
        self.operations = OperationLedger(store)

    @staticmethod
    def _finding(
        severity: str,
        code: str,
        message: str,
        related: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "severity": severity,
            "code": code[:120],
            "message": message[:2000],
            "related": {
                str(key)[:120]: str(value)[:500]
                for key, value in sorted((related or {}).items())
            },
        }

    @staticmethod
    def _mapping(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(record["id"]): record for record in records}

    def _load_all(
        self,
    ) -> tuple[dict[str, dict[str, dict[str, Any]]], list[dict[str, Any]]]:
        result: dict[str, dict[str, dict[str, Any]]] = {}
        findings: list[dict[str, Any]] = []
        for kind in (
            "sources",
            "originals",
            "documents",
            "versions",
            "acquisitions",
            "email-messages",
            "email-observations",
            "email-attachments",
        ):
            records, issues = safe_canonical_records(self.store, kind)
            result[kind] = self._mapping(records)
            findings.extend(issues)
        return result, findings

    def _verify_original(
        self,
        original_id: str,
        original: dict[str, Any],
        findings: list[dict[str, Any]],
    ) -> bool:
        digest = original_id.removeprefix("sha256_")
        expected_ref = (
            f"originals/sha256/{digest[:2]}/{digest}"
            if _SHA256.fullmatch(digest)
            else ""
        )
        if (
            not original_id.startswith("sha256_")
            or _SHA256.fullmatch(digest) is None
            or original.get("sha256") != digest
            or original.get("storage_ref") != expected_ref
        ):
            findings.append(
                self._finding(
                    "error",
                    "original_identity_invalid",
                    f"Original identity or storage reference is invalid: {original_id}",
                    {"original_id": original_id},
                )
            )
            return False
        try:
            data = safe_instance_path(self.store.paths.root, expected_ref).read_bytes()
        except (OSError, ValueError):
            findings.append(
                self._finding(
                    "error",
                    "original_bytes_unavailable",
                    f"Original bytes are unavailable: {original_id}",
                    {"original_id": original_id},
                )
            )
            return False
        try:
            declared_size = int(original.get("size_bytes"))
        except (TypeError, ValueError):
            declared_size = -1
        if hashlib.sha256(data).hexdigest() != digest:
            findings.append(
                self._finding(
                    "error",
                    "original_hash_mismatch",
                    f"Original SHA-256 does not match its identity: {original_id}",
                    {"original_id": original_id},
                )
            )
            return False
        if len(data) != declared_size:
            findings.append(
                self._finding(
                    "error",
                    "original_size_mismatch",
                    f"Original size does not match its record: {original_id}",
                    {"original_id": original_id},
                )
            )
            return False
        return True

    def _verify_versions(
        self,
        records: dict[str, dict[str, dict[str, Any]]],
        findings: list[dict[str, Any]],
    ) -> tuple[dict[str, int], dict[str, int]]:
        documents = records["documents"]
        originals = records["originals"]
        original_refs = {key: 0 for key in originals}
        version_acquisitions = {key: 0 for key in records["versions"]}
        for version_id, version in sorted(records["versions"].items()):
            document_id = str(version.get("document_id", ""))
            original_id = str(version.get("original_id", ""))
            original = originals.get(original_id)
            if document_id not in documents:
                findings.append(
                    self._finding(
                        "error",
                        "version_document_missing",
                        f"DocumentVersion has no Document: {version_id}",
                        {"version_id": version_id, "document_id": document_id},
                    )
                )
            if original is None:
                findings.append(
                    self._finding(
                        "error",
                        "version_original_missing",
                        f"DocumentVersion has no Original: {version_id}",
                        {"version_id": version_id, "original_id": original_id},
                    )
                )
                continue
            original_refs[original_id] += 1
            try:
                version_size = int(version.get("size_bytes"))
                original_size = int(original.get("size_bytes"))
            except (TypeError, ValueError):
                version_size, original_size = -1, -2
            if (
                version.get("content_hash") != original.get("sha256")
                or version_size != original_size
            ):
                findings.append(
                    self._finding(
                        "error",
                        "version_original_mismatch",
                        f"DocumentVersion and Original disagree: {version_id}",
                        {"version_id": version_id, "original_id": original_id},
                    )
                )
        return original_refs, version_acquisitions

    def _verify_documents(
        self,
        records: dict[str, dict[str, dict[str, Any]]],
        findings: list[dict[str, Any]],
    ) -> None:
        for document_id, document in sorted(records["documents"].items()):
            source_id = str(document.get("source_id", ""))
            current_id = str(document.get("current_version_id", ""))
            current = records["versions"].get(current_id)
            if source_id not in records["sources"]:
                findings.append(
                    self._finding(
                        "error",
                        "document_source_missing",
                        f"Document has no Source: {document_id}",
                        {"document_id": document_id, "source_id": source_id},
                    )
                )
            if current is None or current.get("document_id") != document_id:
                findings.append(
                    self._finding(
                        "error",
                        "document_current_version_invalid",
                        f"Document current Version is invalid: {document_id}",
                        {"document_id": document_id, "version_id": current_id},
                    )
                )

    def _verify_acquisitions(
        self,
        records: dict[str, dict[str, dict[str, Any]]],
        version_acquisitions: dict[str, int],
        findings: list[dict[str, Any]],
    ) -> None:
        for acquisition_id, acquisition in sorted(records["acquisitions"].items()):
            source_id = str(acquisition.get("source_id", ""))
            document_id = str(acquisition.get("document_id", ""))
            version_id = str(acquisition.get("version_id", ""))
            version = records["versions"].get(version_id)
            if source_id not in records["sources"]:
                findings.append(
                    self._finding(
                        "error",
                        "acquisition_source_missing",
                        f"Acquisition has no Source: {acquisition_id}",
                        {"acquisition_id": acquisition_id, "source_id": source_id},
                    )
                )
            if document_id not in records["documents"]:
                findings.append(
                    self._finding(
                        "error",
                        "acquisition_document_missing",
                        f"Acquisition has no Document: {acquisition_id}",
                        {
                            "acquisition_id": acquisition_id,
                            "document_id": document_id,
                        },
                    )
                )
            if version is None or version.get("document_id") != document_id:
                findings.append(
                    self._finding(
                        "error",
                        "acquisition_version_invalid",
                        f"Acquisition Version is invalid: {acquisition_id}",
                        {"acquisition_id": acquisition_id, "version_id": version_id},
                    )
                )
                continue
            version_acquisitions[version_id] += 1
            if acquisition.get("content_hash") != version.get("content_hash"):
                findings.append(
                    self._finding(
                        "error",
                        "acquisition_hash_mismatch",
                        f"Acquisition and Version hashes disagree: {acquisition_id}",
                        {"acquisition_id": acquisition_id, "version_id": version_id},
                    )
                )

    def _verify_email_messages(
        self,
        records: dict[str, dict[str, dict[str, Any]]],
        findings: list[dict[str, Any]],
    ) -> None:
        for message_id, message in sorted(records["email-messages"].items()):
            source_id = str(message.get("source_id", ""))
            document_id = str(message.get("document_id", ""))
            version_id = str(message.get("version_id", ""))
            original_id = str(message.get("original_id", ""))
            digest = str(message.get("original_sha256", ""))
            try:
                size = int(message.get("size_bytes"))
            except (TypeError, ValueError):
                size = -1
            source = records["sources"].get(source_id)
            document = records["documents"].get(document_id)
            version = records["versions"].get(version_id)
            original = records["originals"].get(original_id)
            if (
                message.get("schema_version") != EMAIL_EVIDENCE_SCHEMA_VERSION
                or message_id
                != email_message_evidence_id(source_id, digest, size)
                or original_id != f"sha256_{digest}"
                or source is None
                or source.get("kind") != "email"
                or document is None
                or document.get("source_id") != source_id
                or version is None
                or version.get("document_id") != document_id
                or version.get("original_id") != original_id
                or version.get("content_hash") != digest
                or version.get("size_bytes") != size
                or original is None
                or original.get("sha256") != digest
                or original.get("size_bytes") != size
            ):
                findings.append(
                    self._finding(
                        "error",
                        "email_message_evidence_invalid",
                        f"Email message evidence is invalid: {message_id}",
                        {"email_message_id": message_id},
                    )
                )

    def _verify_email_observations(
        self,
        records: dict[str, dict[str, dict[str, Any]]],
        findings: list[dict[str, Any]],
    ) -> None:
        for observation_id, observation in sorted(
            records["email-observations"].items()
        ):
            source_id = str(observation.get("source_id", ""))
            message_id = str(observation.get("message_id", ""))
            acquisition_id = str(observation.get("acquisition_id", ""))
            message = records["email-messages"].get(message_id)
            acquisition = records["acquisitions"].get(acquisition_id)
            try:
                size = int(message.get("size_bytes")) if message is not None else -1
            except (TypeError, ValueError):
                size = -1
            valid = (
                observation.get("schema_version") == EMAIL_EVIDENCE_SCHEMA_VERSION
                and message is not None
                and observation_id
                == email_message_observation_id(
                    source_id,
                    str(observation.get("adapter_id", "")),
                    str(observation.get("adapter_version", "")),
                    str(observation.get("container_identity_sha256", "")),
                    str(observation.get("container_snapshot_sha256", "")),
                    str(observation.get("locator_sha256", "")),
                    str(message.get("original_sha256", "")),
                    size,
                    str(observation.get("settings_sha256", "")),
                )
                and message.get("source_id") == source_id
                and acquisition is not None
                and acquisition.get("source_id") == source_id
                and acquisition.get("document_id") == message.get("document_id")
                and acquisition.get("version_id") == message.get("version_id")
                and acquisition.get("content_hash") == message.get("original_sha256")
                and acquisition.get("original_id") == message.get("original_id")
            )
            if not valid:
                findings.append(
                    self._finding(
                        "error",
                        "email_observation_evidence_invalid",
                        f"Email observation evidence is invalid: {observation_id}",
                        {"email_observation_id": observation_id},
                    )
                )

    def _verify_email_attachments(
        self,
        records: dict[str, dict[str, dict[str, Any]]],
        original_refs: dict[str, int],
        findings: list[dict[str, Any]],
    ) -> None:
        for attachment_id, attachment in sorted(
            records["email-attachments"].items()
        ):
            source_id = str(attachment.get("source_id", ""))
            parent_message_id = str(attachment.get("parent_message_id", ""))
            parent_document_id = str(attachment.get("parent_document_id", ""))
            parent_version_id = str(attachment.get("parent_version_id", ""))
            part_identity = str(attachment.get("part_identity_sha256", ""))
            original_id = str(attachment.get("original_id", ""))
            digest = str(attachment.get("original_sha256", ""))
            try:
                size = int(attachment.get("size_bytes"))
            except (TypeError, ValueError):
                size = -1
            parent = records["email-messages"].get(parent_message_id)
            original = records["originals"].get(original_id)
            valid = (
                attachment.get("schema_version") == EMAIL_EVIDENCE_SCHEMA_VERSION
                and attachment_id
                == email_attachment_evidence_id(
                    source_id,
                    parent_message_id,
                    part_identity,
                    digest,
                    size,
                )
                and original_id == f"sha256_{digest}"
                and parent is not None
                and parent.get("source_id") == source_id
                and parent.get("document_id") == parent_document_id
                and parent.get("version_id") == parent_version_id
                and original is not None
                and original.get("sha256") == digest
                and original.get("size_bytes") == size
            )
            if not valid:
                findings.append(
                    self._finding(
                        "error",
                        "email_attachment_evidence_invalid",
                        f"Email attachment evidence is invalid: {attachment_id}",
                        {"email_attachment_id": attachment_id},
                    )
                )
                continue
            original_refs[original_id] += 1

    def check(self) -> dict[str, Any]:
        operation = self.operations.start(
            "assurance.originals",
            "Verify canonical knowledge and Originals",
            summary=(
                "Verify canonical references plus exact Original hash, size and storage identity."
            ),
        )
        report_id = f"assurance_{uuid4().hex}"
        findings: list[dict[str, Any]] = []
        try:
            records, parse_findings = self._load_all()
            findings.extend(parse_findings)
            self.operations.append(
                operation.id,
                "assurance.records_loaded",
                "Loaded bounded canonical records for verification.",
                details={
                    kind: len(records[kind])
                    for kind in (
                        "sources",
                        "originals",
                        "documents",
                        "versions",
                        "acquisitions",
                        "email-messages",
                        "email-observations",
                        "email-attachments",
                    )
                },
            )
            verified = sum(
                self._verify_original(original_id, original, findings)
                for original_id, original in sorted(records["originals"].items())
            )
            original_refs, version_acquisitions = self._verify_versions(
                records,
                findings,
            )
            self._verify_documents(records, findings)
            self._verify_acquisitions(records, version_acquisitions, findings)
            self._verify_email_messages(records, findings)
            self._verify_email_observations(records, findings)
            self._verify_email_attachments(records, original_refs, findings)
            for original_id, count in sorted(original_refs.items()):
                if count == 0:
                    findings.append(
                        self._finding(
                            "warning",
                            "original_unreferenced",
                            f"Original has no DocumentVersion: {original_id}",
                            {"original_id": original_id},
                        )
                    )
            for version_id, count in sorted(version_acquisitions.items()):
                if count == 0:
                    findings.append(
                        self._finding(
                            "warning",
                            "version_without_acquisition",
                            f"DocumentVersion has no Acquisition: {version_id}",
                            {"version_id": version_id},
                        )
                    )

            total_findings = len(findings)
            omitted = max(0, total_findings - (MAX_ASSURANCE_FINDINGS - 1))
            if omitted:
                findings = findings[: MAX_ASSURANCE_FINDINGS - 1]
                findings.append(
                    self._finding(
                        "warning",
                        "findings_truncated",
                        f"Assurance omitted {omitted} findings after its safety limit.",
                    )
                )
            attention = sum(
                item["severity"] in {"error", "warning"} for item in findings
            )
            status = "healthy" if attention == 0 else "attention"
            operation_status = (
                "completed" if attention == 0 else "completed_with_errors"
            )
            metrics = {
                "sources": len(records["sources"]),
                "originals": len(records["originals"]),
                "originals_verified": verified,
                "shared_originals": sum(count > 1 for count in original_refs.values()),
                "documents": len(records["documents"]),
                "versions": len(records["versions"]),
                "acquisitions": len(records["acquisitions"]),
                "email_messages": len(records["email-messages"]),
                "email_observations": len(records["email-observations"]),
                "email_attachments": len(records["email-attachments"]),
                "findings": len(findings),
                "attention_findings": attention,
                "findings_truncated": omitted,
            }
            closed = self.operations.close(
                operation.id,
                status=operation_status,
                summary=(
                    f"Verified {verified} Originals with {attention} retained attention "
                    "findings; no repair was attempted."
                ),
                metrics=metrics,
            )
            report = {
                "schema_version": ASSURANCE_SCHEMA_VERSION,
                "id": report_id,
                "operation_id": operation.id,
                "status": status,
                "started_at": operation.started_at,
                "completed_at": closed.completed_at,
                "summary": closed.summary,
                "metrics": metrics,
                "findings": findings,
                "automatic_repair": "none",
            }
            self.reports.mkdir(parents=True, exist_ok=True)
            self.store._atomic_json(self.reports / f"{report_id}.json", report)
            return report
        except Exception as exc:
            current = self.operations.get_record(operation.id)
            if current is not None and current.status == "running":
                self.operations.append(
                    operation.id,
                    "assurance.failed",
                    "Original assurance failed before a complete report was committed.",
                    level="error",
                    details={"error_type": exc.__class__.__name__},
                )
                self.operations.close(
                    operation.id,
                    status="failed",
                    summary="Original assurance failed.",
                    error_code="assurance_failed",
                    error=exc.__class__.__name__,
                )
            raise

    @staticmethod
    def _valid_report(value: Any) -> bool:
        return (
            isinstance(value, dict)
            and value.get("schema_version") == ASSURANCE_SCHEMA_VERSION
            and _REPORT_ID.fullmatch(str(value.get("id", ""))) is not None
            and value.get("status") in {"healthy", "attention"}
            and isinstance(value.get("findings"), list)
            and isinstance(value.get("metrics"), dict)
            and value.get("automatic_repair") == "none"
        )

    def list_reports(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or not self.reports.exists():
            return []
        result = []
        for path in self.reports.glob("assurance_*.json"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    value = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if self._valid_report(value) and path.stem == value["id"]:
                result.append(value)
        result.sort(
            key=lambda item: (
                str(item.get("completed_at", "")),
                str(item["id"]),
            ),
            reverse=True,
        )
        return result[: min(limit, 500)]

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        if _REPORT_ID.fullmatch(report_id) is None:
            return None
        path = self.reports / f"{report_id}.json"
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if self._valid_report(value) and value["id"] == report_id:
            return value
        return None

    def latest(self) -> dict[str, Any] | None:
        reports = self.list_reports(limit=1)
        return reports[0] if reports else None
