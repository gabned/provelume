from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

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
                    "message": f"Canonical {kind} filename and ID do not match: {path.name}",
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
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

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
    def _map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(record["id"]): record for record in records}

    def _load_all(
        self,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        kinds = ("sources", "originals", "documents", "versions", "acquisitions")
        records: dict[str, list[dict[str, Any]]] = {}
        findings: list[dict[str, Any]] = []
        for kind in kinds:
            selected, issues = safe_canonical_records(self.store, kind)
            records[kind] = selected
            findings.extend(issues)
        return records, findings

    def _verify_original(
        self,
        original_id: str,
        original: dict[str, Any],
        findings: list[dict[str, Any]],
    ) -> bool:
        expected_digest = original_id.removeprefix("sha256_")
        expected_ref = (
            f"originals/sha256/{expected_digest[:2]}/{expected_digest}"
            if _SHA256.fullmatch(expected_digest)
            else ""
        )
        storage_ref = original.get("storage_ref")
        if (
            not original_id.startswith("sha256_")
            or _SHA256.fullmatch(expected_digest) is None
            or original.get("sha256") != expected_digest
            or storage_ref != expected_ref
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
            path = safe_instance_path(self.store.paths.root, expected_ref)
            data = path.read_bytes()
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
        if self._sha256(data) != expected_digest:
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
            sources = self._map(records["sources"])
            originals = self._map(records["originals"])
            documents = self._map(records["documents"])
            versions = self._map(records["versions"])
            acquisitions = self._map(records["acquisitions"])
            original_references = {key: 0 for key in originals}
            version_acquisitions = {key: 0 for key in versions}

            self.operations.append(
                operation.id,
                "assurance.records_loaded",
                "Loaded bounded canonical records for verification.",
                details={
                    "sources": len(sources),
                    "originals": len(originals),
                    "documents": len(documents),
                    "versions": len(versions),
                    "acquisitions": len(acquisitions),
                    "parse_findings": len(parse_findings),
                },
            )

            verified_originals = sum(
                self._verify_original(original_id, original, findings)
                for original_id, original in sorted(originals.items())
            )

            for version_id, version in sorted(versions.items()):
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
                original_references[original_id] += 1
                try:
                    version_size = int(version.get("size_bytes"))
                    original_size = int(original.get("size_bytes"))
                except (TypeError, ValueError):
                    version_size = -1
                    original_size = -2
                if (
                    version.get("content_hash") != original.get("sha256")
                    or version_size != original_size
                ):
                    findings.append(
                        self._finding(
                            "error",
                            "version_original_mismatch",
                            f"DocumentVersion and Original identities disagree: {version_id}",
                            {"version_id": version_id, "original_id": original_id},
                        )
                    )

            for document_id, document in sorted(documents.items()):
                source_id = str(document.get("source_id", ""))
                current_version_id = str(document.get("current_version_id", ""))
                current = versions.get(current_version_id)
                if source_id not in sources:
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
                            (
                                "Document current Version is missing or belongs elsewhere: "
                                f"{document_id}"
                            ),
                            {
                                "document_id": document_id,
                                "version_id": current_version_id,
                            },
                        )
                    )

            for acquisition_id, acquisition in sorted(acquisitions.items()):
                source_id = str(acquisition.get("source_id", ""))
                document_id = str(acquisition.get("document_id", ""))
                version_id = str(acquisition.get("version_id", ""))
                version = versions.get(version_id)
                if source_id not in sources:
                    findings.append(
                        self._finding(
                            "error",
                            "acquisition_source_missing",
                            f"Acquisition has no Source: {acquisition_id}",
                            {"acquisition_id": acquisition_id, "source_id": source_id},
                        )
                    )
                if document_id not in documents:
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
                            (
                                "Acquisition Version is missing or belongs elsewhere: "
                                f"{acquisition_id}"
                            ),
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

            for original_id, count in sorted(original_references.items()):
                if count == 0:
                    findings.append(
                        self._finding(
                            "warning",
                            "original_unreferenced",
                            f"Original is not referenced by any DocumentVersion: {original_id}",
                            {"original_id": original_id},
                        )
                    )
            for version_id, count in sorted(version_acquisitions.items()):
                if count == 0 and versions[version_id].get("document_id") in documents:
                    findings.append(
                        self._finding(
                            "warning",
                            "version_without_acquisition",
                            f"DocumentVersion has no Acquisition evidence: {version_id}",
                            {"version_id": version_id},
                        )
                    )

            total_findings = len(findings)
            findings_truncated = max(0, total_findings - MAX_ASSURANCE_FINDINGS)
            if findings_truncated:
                omitted = total_findings - (MAX_ASSURANCE_FINDINGS - 1)
                findings = findings[: MAX_ASSURANCE_FINDINGS - 1]
                findings.append(
                    self._finding(
                        "warning",
                        "findings_truncated",
                        (
                            f"Assurance retained {MAX_ASSURANCE_FINDINGS - 1} findings "
                            f"and omitted {omitted}."
                        ),
                    )
                )
            attention = sum(
                item["severity"] in {"error", "warning"} for item in findings
            )
            shared_originals = sum(count > 1 for count in original_references.values())
            report_status = "healthy" if attention == 0 else "attention"
            operation_status = "completed" if attention == 0 else "completed_with_errors"
            closed = self.operations.close(
                operation.id,
                status=operation_status,
                summary=(
                    f"Verified {verified_originals} Originals with {attention} retained "
                    "attention findings; no repair was attempted."
                ),
                metrics={
                    "sources": len(sources),
                    "originals": len(originals),
                    "originals_verified": verified_originals,
                    "shared_originals": shared_originals,
                    "documents": len(documents),
                    "versions": len(versions),
                    "acquisitions": len(acquisitions),
                    "findings": len(findings),
                    "attention_findings": attention,
                    "findings_truncated": findings_truncated,
                },
            )
            report = {
                "schema_version": ASSURANCE_SCHEMA_VERSION,
                "id": report_id,
                "operation_id": operation.id,
                "status": report_status,
                "started_at": operation.started_at,
                "completed_at": closed.completed_at,
                "summary": closed.summary,
                "metrics": dict(closed.metrics),
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
            key=lambda item: (str(item.get("completed_at", "")), str(item["id"])),
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
        return value if self._valid_report(value) and value["id"] == report_id else None

    def latest(self) -> dict[str, Any] | None:
        reports = self.list_reports(limit=1)
        return reports[0] if reports else None
