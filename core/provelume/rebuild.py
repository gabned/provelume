from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from .bundles import (
    DEFAULT_MAX_BUNDLE_DOCUMENTS,
    BundleBuildError,
    DocumentBundleManager,
)
from .duplicates import DuplicateCaseManager, DuplicateScanLimitError
from .index import index_status, rebuild_search_index
from .locks import InstanceLockManager, InstanceLockUnavailable
from .operations import OperationLedger
from .paths import safe_instance_path
from .storage import InstanceStore

REBUILD_SCHEMA_VERSION = 1
REBUILD_LOCK_NAME = "derived-rebuild"
REBUILD_MODES = frozenset({"incremental", "full", "agreement"})
_REPORT_ID = re.compile(r"rebuild_[0-9a-f]{32}\Z")


class RebuildLimitError(RuntimeError):
    pass


class RebuildInvariantError(RuntimeError):
    pass


def _hash_json(value: Any) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DerivedRebuildManager:
    """Coordinate bounded derived-state rebuilds under one Instance lock."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.reports = store.paths.state / "rebuild" / "reports"
        self.operations = OperationLedger(store)
        self.locks = InstanceLockManager(store)
        self.bundles = DocumentBundleManager(store)
        self.duplicates = DuplicateCaseManager(store)

    def lock_status(self) -> dict[str, Any]:
        held = self.locks.inspect(REBUILD_LOCK_NAME)
        if held is not None:
            return held
        return {
            "schema_version": 1,
            "name": REBUILD_LOCK_NAME,
            "held": False,
            "status": "available",
            "purpose": None,
            "acquired_at": None,
        }

    @staticmethod
    def _safe_bundle_ref(reference: str, version_id: str) -> bool:
        parts = PurePosixPath(reference).parts
        prefix = ("state", "derived", "bundles", version_id)
        return len(parts) > len(prefix) and parts[: len(prefix)] == prefix

    def _verified_blob(
        self,
        reference: str,
        expected_sha256: str,
        *,
        expected_size: int | None = None,
    ) -> bytes | None:
        try:
            path = safe_instance_path(self.store.paths.root, reference)
            data = path.read_bytes()
        except (OSError, ValueError):
            return None
        if _sha256(data) != expected_sha256:
            return None
        if expected_size is not None and len(data) != expected_size:
            return None
        return data

    def _bundle_validation(
        self,
        document: dict[str, Any],
        version: dict[str, Any],
    ) -> tuple[bool, str | None, str | None]:
        record = self.bundles.get(str(version["id"]))
        if record is None:
            return False, None, "missing_or_invalid_manifest"
        artifact = record["artifact"]
        manifest = record["manifest"]
        version_id = str(version["id"])
        if (
            manifest.get("document_id") != document["id"]
            or manifest.get("version_id") != version_id
            or manifest.get("source_content_sha256") != version["content_hash"]
            or not isinstance(manifest.get("output_fingerprint"), str)
        ):
            return False, None, "identity_mismatch"
        manifest_ref = str(artifact.get("storage_ref", ""))
        if not self._safe_bundle_ref(manifest_ref, version_id):
            return False, None, "manifest_path_invalid"
        checksum = str(artifact.get("checksum", ""))
        if self._verified_blob(manifest_ref, checksum) is None:
            return False, None, "manifest_checksum_mismatch"

        markdown = manifest.get("markdown")
        page_map = manifest.get("page_map")
        assets = manifest.get("assets")
        if (
            not isinstance(markdown, dict)
            or not isinstance(page_map, dict)
            or not isinstance(assets, list)
        ):
            return False, None, "manifest_structure_invalid"
        try:
            markdown_ref = str(markdown["storage_ref"])
            markdown_hash = str(markdown["sha256"])
            markdown_size = int(markdown["size_bytes"])
            page_map_ref = str(page_map["storage_ref"])
            page_map_hash = str(page_map["sha256"])
            page_count = int(page_map["pages"])
        except (KeyError, TypeError, ValueError):
            return False, None, "manifest_structure_invalid"
        if not self._safe_bundle_ref(markdown_ref, version_id):
            return False, None, "markdown_path_invalid"
        if self._verified_blob(
            markdown_ref,
            markdown_hash,
            expected_size=markdown_size,
        ) is None:
            return False, None, "markdown_checksum_mismatch"
        if not self._safe_bundle_ref(page_map_ref, version_id):
            return False, None, "page_map_path_invalid"
        page_map_bytes = self._verified_blob(page_map_ref, page_map_hash)
        if page_map_bytes is None:
            return False, None, "page_map_checksum_mismatch"
        try:
            page_map_value = json.loads(page_map_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, None, "page_map_invalid"
        if (
            not isinstance(page_map_value, dict)
            or page_map_value.get("version_id") != version_id
            or not isinstance(page_map_value.get("pages"), list)
            or len(page_map_value["pages"]) != page_count
        ):
            return False, None, "page_map_invalid"

        for asset in assets:
            if not isinstance(asset, dict):
                return False, None, "asset_invalid"
            try:
                reference = str(asset["storage_ref"])
                digest = str(asset["sha256"])
                size = int(asset["size_bytes"])
            except (KeyError, TypeError, ValueError):
                return False, None, "asset_invalid"
            if not self._safe_bundle_ref(reference, version_id):
                return False, None, "asset_path_invalid"
            if self._verified_blob(reference, digest, expected_size=size) is None:
                return False, None, "asset_checksum_mismatch"
        return True, str(manifest["output_fingerprint"]), None

    def _discard_bundle(self, version_id: str) -> None:
        path = self.bundles.root / version_id
        if path.exists():
            shutil.rmtree(path)

    def _documents(
        self,
        *,
        max_documents: int,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        documents = self.store.list_canonical("documents")
        if len(documents) > max_documents:
            raise RebuildLimitError(
                f"Instance exceeds the {max_documents}-document rebuild safety limit"
            )
        result = []
        for document in documents:
            version = self.store.read_canonical(
                "versions",
                str(document["current_version_id"]),
            )
            if version is None:
                raise RebuildInvariantError(
                    f"Document has no readable current Version: {document['id']}"
                )
            result.append((document, version))
        result.sort(key=lambda item: str(item[0]["id"]))
        return result

    def _run_pass(
        self,
        mode: str,
        *,
        operation_id: str,
        max_documents: int,
    ) -> dict[str, Any]:
        documents = self._documents(max_documents=max_documents)
        bundles_built = 0
        bundles_recovered = 0
        bundle_warnings = 0
        for document, version in documents:
            valid, _fingerprint, reason = self._bundle_validation(document, version)
            should_build = mode == "full" or not valid
            if not should_build:
                continue
            if not valid:
                self._discard_bundle(str(version["id"]))
                bundles_recovered += 1
                self.operations.append(
                    operation_id,
                    "rebuild.bundle_recovery_required",
                    "A missing or invalid document bundle will be rebuilt.",
                    level="warning",
                    details={
                        "document_id": document["id"],
                        "version_id": version["id"],
                        "reason": reason,
                    },
                )
            built = self.bundles.build_version(
                str(version["id"]),
                parent_operation_id=operation_id,
            )
            bundles_built += 1
            if built["operation"]["status"] == "completed_with_errors":
                bundle_warnings += int(
                    built["operation"].get("metrics", {}).get("warnings", 0)
                )

        missing_text = any(
            self.store.derived_artifact_for_version(
                str(version["id"]),
                "extracted_text",
            )
            is None
            for _document, version in documents
        )
        previous_index_status = index_status(self.store)
        index_rebuilt = (
            mode == "full"
            or previous_index_status != "ready"
            or missing_text
        )
        documents_indexed = None
        if index_rebuilt:
            documents_indexed = rebuild_search_index(
                self.store,
                recover_missing_derived=True,
            )
            self.operations.append(
                operation_id,
                "rebuild.index_committed",
                "Rebuilt the local full-text search index.",
                details={
                    "documents_indexed": documents_indexed,
                    "previous_status": previous_index_status,
                },
            )

        duplicate_result = self.duplicates.scan()
        self.operations.append(
            operation_id,
            "rebuild.duplicates_refreshed",
            "Refreshed exact and probable duplicate evidence.",
            details={
                "duplicate_operation_id": duplicate_result["operation"]["id"],
                "exact_cases": len(duplicate_result["exact"]),
                "probable_cases": len(duplicate_result["probable"]),
                "warnings": len(duplicate_result["warnings"]),
            },
        )
        return {
            "mode": mode,
            "documents": len(documents),
            "bundles_built": bundles_built,
            "bundles_recovered": bundles_recovered,
            "bundle_warnings": bundle_warnings,
            "index_rebuilt": index_rebuilt,
            "documents_indexed": documents_indexed,
            "duplicate_operation_id": duplicate_result["operation"]["id"],
            "exact_cases": len(duplicate_result["exact"]),
            "probable_cases": len(duplicate_result["probable"]),
            "duplicate_warnings": len(duplicate_result["warnings"]),
        }

    def _index_component(self) -> dict[str, Any]:
        status = index_status(self.store)
        metadata_path = self.store.paths.indexes / "search.meta.json"
        metadata: dict[str, Any] = {}
        if metadata_path.is_file():
            try:
                with metadata_path.open("r", encoding="utf-8") as handle:
                    value = json.load(handle)
                if isinstance(value, dict):
                    metadata = {
                        key: value.get(key)
                        for key in (
                            "schema_version",
                            "knowledge_fingerprint",
                            "documents_indexed",
                        )
                    }
            except (OSError, json.JSONDecodeError):
                metadata = {}
        return {"status": status, "metadata": metadata}

    def _snapshot(
        self,
        *,
        max_documents: int,
    ) -> dict[str, Any]:
        documents = self._documents(max_documents=max_documents)
        document_rows = []
        bundle_rows = []
        current_version_ids = set()
        for document, version in documents:
            version_id = str(version["id"])
            current_version_ids.add(version_id)
            document_rows.append(
                {
                    "document_id": document["id"],
                    "version_id": version_id,
                    "content_hash": version["content_hash"],
                }
            )
            valid, fingerprint, reason = self._bundle_validation(document, version)
            bundle_rows.append(
                {
                    "document_id": document["id"],
                    "version_id": version_id,
                    "valid": valid,
                    "output_fingerprint": fingerprint,
                    "reason": reason,
                }
            )

        artifact_rows = []
        for artifact in self.store.list_derived_artifacts():
            if artifact.get("version_id") not in current_version_ids:
                continue
            artifact_rows.append(
                {
                    key: artifact.get(key)
                    for key in (
                        "id",
                        "version_id",
                        "kind",
                        "generator",
                        "generator_version",
                        "storage_ref",
                        "checksum",
                    )
                }
            )
        artifact_rows.sort(
            key=lambda item: (
                str(item.get("version_id", "")),
                str(item.get("kind", "")),
                str(item.get("id", "")),
            )
        )

        duplicate_rows = []
        for case in self.duplicates.list_cases(current=True, limit=1000):
            duplicate_rows.append(
                {
                    "id": case["id"],
                    "kind": case["kind"],
                    "rule": case["rule"],
                    "confidence": case["confidence"],
                    "document_ids": sorted(
                        str(item["document_id"])
                        for item in case["documents"]
                    ),
                }
            )
        duplicate_rows.sort(key=lambda item: str(item["id"]))
        components = {
            "canonical": self.store.knowledge_fingerprint(),
            "documents": _hash_json(document_rows),
            "bundles": _hash_json(bundle_rows),
            "derived_artifacts": _hash_json(artifact_rows),
            "index": _hash_json(self._index_component()),
            "duplicates": _hash_json(duplicate_rows),
        }
        return {
            "fingerprint": _hash_json(components),
            "components": components,
            "counts": {
                "documents": len(document_rows),
                "bundles": len(bundle_rows),
                "valid_bundles": sum(item["valid"] for item in bundle_rows),
                "derived_artifacts": len(artifact_rows),
                "duplicate_cases": len(duplicate_rows),
            },
        }

    def _write_report(self, report: dict[str, Any]) -> None:
        self.reports.mkdir(parents=True, exist_ok=True)
        self.store._atomic_json(
            self.reports / f"{report['id']}.json",
            report,
        )

    def run(
        self,
        mode: str,
        *,
        max_documents: int = DEFAULT_MAX_BUNDLE_DOCUMENTS,
    ) -> dict[str, Any]:
        selected_mode = mode.strip().lower()
        if selected_mode not in REBUILD_MODES:
            raise ValueError(f"unsupported rebuild mode: {mode}")
        if max_documents < 1:
            raise ValueError("max_documents must be positive")
        report_id = f"rebuild_{uuid4().hex}"
        operation = self.operations.start(
            "rebuild.derived",
            f"Run {selected_mode} derived-state rebuild",
            summary=(
                "Coordinate document bundles, full-text index and duplicate evidence "
                "without mutating canonical knowledge."
            ),
            related={"rebuild_report_id": report_id, "lock": REBUILD_LOCK_NAME},
        )
        lease = None
        try:
            lease = self.locks.acquire(
                REBUILD_LOCK_NAME,
                purpose=f"derived rebuild: {selected_mode}",
            )
            self.operations.append(
                operation.id,
                "rebuild.lock_acquired",
                "Acquired the exclusive derived-state rebuild lock.",
                details={"lock": REBUILD_LOCK_NAME, "mode": selected_mode},
            )
            canonical_before = self.store.knowledge_fingerprint()
            passes = []
            agreement: bool | None = None
            if selected_mode == "agreement":
                passes.append(
                    self._run_pass(
                        "incremental",
                        operation_id=operation.id,
                        max_documents=max_documents,
                    )
                )
                incremental_snapshot = self._snapshot(
                    max_documents=max_documents,
                )
                passes.append(
                    self._run_pass(
                        "full",
                        operation_id=operation.id,
                        max_documents=max_documents,
                    )
                )
                final_snapshot = self._snapshot(max_documents=max_documents)
                agreement = (
                    incremental_snapshot["fingerprint"]
                    == final_snapshot["fingerprint"]
                )
                self.operations.append(
                    operation.id,
                    "rebuild.agreement_checked",
                    "Compared incremental and full derived-state fingerprints.",
                    level="info" if agreement else "error",
                    details={
                        "agreement": agreement,
                        "incremental_fingerprint": incremental_snapshot["fingerprint"],
                        "full_fingerprint": final_snapshot["fingerprint"],
                    },
                )
            else:
                passes.append(
                    self._run_pass(
                        selected_mode,
                        operation_id=operation.id,
                        max_documents=max_documents,
                    )
                )
                incremental_snapshot = None
                final_snapshot = self._snapshot(max_documents=max_documents)

            canonical_after = self.store.knowledge_fingerprint()
            if canonical_after != canonical_before:
                raise RebuildInvariantError(
                    "derived rebuild changed the canonical knowledge fingerprint"
                )
            all_bundles_valid = (
                final_snapshot["counts"]["valid_bundles"]
                == final_snapshot["counts"]["documents"]
            )
            index_ready = self._index_component()["status"] == "ready"
            status = "completed"
            if agreement is False or not all_bundles_valid or not index_ready:
                status = "completed_with_errors"
            warning_count = sum(
                int(item["bundle_warnings"])
                + int(item["duplicate_warnings"])
                for item in passes
            )
            if warning_count and status == "completed":
                status = "completed_with_errors"
            metrics = {
                "passes": len(passes),
                "documents": final_snapshot["counts"]["documents"],
                "valid_bundles": final_snapshot["counts"]["valid_bundles"],
                "bundles_built": sum(item["bundles_built"] for item in passes),
                "bundles_recovered": sum(
                    item["bundles_recovered"] for item in passes
                ),
                "index_rebuilds": sum(bool(item["index_rebuilt"]) for item in passes),
                "duplicate_scans": len(passes),
                "warnings": warning_count,
                "agreement": int(agreement is True),
            }
            closed = self.operations.close(
                operation.id,
                status=status,
                summary=(
                    f"Completed {selected_mode} rebuild with "
                    f"{metrics['valid_bundles']}/{metrics['documents']} valid bundles."
                ),
                metrics=metrics,
                error_code=(
                    "rebuild_agreement_failed" if agreement is False else None
                ),
                error=(
                    "Incremental and full derived-state fingerprints differ."
                    if agreement is False
                    else None
                ),
            )
            report = {
                "schema_version": REBUILD_SCHEMA_VERSION,
                "id": report_id,
                "operation_id": operation.id,
                "mode": selected_mode,
                "status": status,
                "started_at": operation.started_at,
                "completed_at": closed.completed_at,
                "summary": closed.summary,
                "lock_name": REBUILD_LOCK_NAME,
                "canonical_before": canonical_before,
                "canonical_after": canonical_after,
                "canonical_mutation": "none",
                "incremental_snapshot": incremental_snapshot,
                "final_snapshot": final_snapshot,
                "agreement": agreement,
                "passes": passes,
                "metrics": metrics,
            }
            self._write_report(report)
            return report
        except (
            BundleBuildError,
            DuplicateScanLimitError,
            InstanceLockUnavailable,
            RebuildInvariantError,
            RebuildLimitError,
            OSError,
            ValueError,
        ) as exc:
            current = self.operations.get_record(operation.id)
            if current is not None and current.status == "running":
                self.operations.append(
                    operation.id,
                    "rebuild.failed",
                    "Derived-state rebuild failed before a valid report was committed.",
                    level="error",
                    details={"error_type": exc.__class__.__name__},
                )
                self.operations.close(
                    operation.id,
                    status="failed",
                    summary="Derived-state rebuild failed.",
                    error_code="derived_rebuild_failed",
                    error=exc.__class__.__name__,
                )
            raise
        finally:
            if lease is not None:
                self.locks.release(lease)

    @staticmethod
    def _valid_report(value: Any) -> bool:
        return (
            isinstance(value, dict)
            and value.get("schema_version") == REBUILD_SCHEMA_VERSION
            and _REPORT_ID.fullmatch(str(value.get("id", ""))) is not None
            and value.get("mode") in REBUILD_MODES
            and value.get("status") in {
                "completed",
                "completed_with_errors",
            }
            and value.get("canonical_mutation") == "none"
            and isinstance(value.get("passes"), list)
            and isinstance(value.get("metrics"), dict)
            and isinstance(value.get("final_snapshot"), dict)
        )

    def list_reports(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or not self.reports.exists():
            return []
        result = []
        for path in self.reports.glob("rebuild_*.json"):
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

    def summary(self) -> dict[str, Any]:
        reports = self.list_reports(limit=500)
        return {
            "schema_version": REBUILD_SCHEMA_VERSION,
            "status": "ready" if reports else "not_run",
            "lock": self.lock_status(),
            "reports": len(reports),
            "latest": reports[0] if reports else None,
            "agreement_reports": sum(
                item.get("mode") == "agreement" for item in reports
            ),
            "successful_agreements": sum(
                item.get("mode") == "agreement" and item.get("agreement") is True
                for item in reports
            ),
        }
