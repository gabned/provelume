from __future__ import annotations

import json
import re
import unicodedata
from itertools import combinations
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .assurance import AssuranceLimitError, safe_canonical_records
from .operations import OperationLedger
from .storage import InstanceStore, utc_now

DUPLICATE_SCHEMA_VERSION = 1
MAX_DUPLICATE_DOCUMENTS = 2_000
MAX_CANDIDATE_PAIRS = 50_000
MAX_TEXT_CHARS_PER_DOCUMENT = 100_000
MAX_TEXT_TOKENS_PER_DOCUMENT = 2_000
MAX_CASE_DOCUMENTS = 500
MAX_SCAN_WARNINGS = 200
_CASE_ID = re.compile(r"dup_[0-9a-f]{32}\Z")
_TOKEN = re.compile(r"\w+", flags=re.UNICODE)


class DuplicateScanLimitError(RuntimeError):
    pass


def _normalised_title(value: str) -> str:
    stem = Path(value).stem
    normalised = unicodedata.normalize("NFKC", stem).casefold()
    return " ".join(_TOKEN.findall(normalised))


def _tokens(value: str, *, min_length: int) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(unicodedata.normalize("NFKC", value).casefold()):
        if len(token) < min_length or token in seen:
            continue
        seen.add(token)
        selected.append(token)
        if len(selected) >= MAX_TEXT_TOKENS_PER_DOCUMENT:
            break
    return tuple(selected)


def _jaccard(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


class DuplicateCaseManager:
    """Detect exact and probable duplicates without merging or deleting knowledge."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.cases = store.paths.state / "duplicates" / "cases"
        self.operations = OperationLedger(store)

    @staticmethod
    def _case_id(kind: str, identity: str) -> str:
        value = f"provelume:duplicate:{DUPLICATE_SCHEMA_VERSION}:{kind}:{identity}"
        return f"dup_{uuid5(NAMESPACE_URL, value).hex}"

    @staticmethod
    def _valid_case(value: Any) -> bool:
        return (
            isinstance(value, dict)
            and value.get("schema_version") == DUPLICATE_SCHEMA_VERSION
            and _CASE_ID.fullmatch(str(value.get("id", ""))) is not None
            and value.get("kind") in {"exact", "probable"}
            and value.get("status") in {"open", "not_current"}
            and isinstance(value.get("documents"), list)
            and isinstance(value.get("evidence"), dict)
            and isinstance(value.get("recommended_actions"), list)
        )

    def _read_case(self, path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not self._valid_case(value) or path.stem != value["id"]:
            return None
        return value

    def list_cases(
        self,
        *,
        kind: str | None = None,
        current: bool | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if limit < 1 or not self.cases.exists():
            return []
        records = []
        for path in self.cases.glob("dup_*.json"):
            record = self._read_case(path)
            if record is None:
                continue
            if kind and record["kind"] != kind:
                continue
            if current is not None and bool(record.get("current")) is not current:
                continue
            records.append(record)
        records.sort(
            key=lambda item: (
                bool(item.get("current")),
                str(item.get("last_seen_at", "")),
                str(item["id"]),
            ),
            reverse=True,
        )
        return records[: min(limit, 500)]

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        if _CASE_ID.fullmatch(case_id) is None:
            return None
        path = self.cases / f"{case_id}.json"
        return self._read_case(path) if path.is_file() else None

    def _existing_map(self) -> dict[str, dict[str, Any]]:
        return {record["id"]: record for record in self.list_cases(limit=500)}

    @staticmethod
    def _safe_extracted_text(
        store: InstanceStore,
        version_id: str,
    ) -> tuple[str, str | None]:
        try:
            artifact = store.derived_artifact_for_version(version_id)
            if artifact is None:
                return "", "derived_text_missing"
            text = store.read_derived_text(artifact)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return "", "derived_text_unreadable"
        return text[:MAX_TEXT_CHARS_PER_DOCUMENT], None

    @staticmethod
    def _document_snapshot(
        document: dict[str, Any],
        version: dict[str, Any],
        acquisition_count: int,
    ) -> dict[str, Any]:
        return {
            "document_id": str(document["id"]),
            "source_id": str(document["source_id"]),
            "locator": str(document["locator"]),
            "title": str(document["title"]),
            "media_type": str(document["media_type"]),
            "version_id": str(version["id"]),
            "content_hash": str(version["content_hash"]),
            "size_bytes": int(version["size_bytes"]),
            "acquisition_count": acquisition_count,
        }

    @staticmethod
    def _probable_rule(
        left_title: tuple[str, ...],
        right_title: tuple[str, ...],
        left_text: tuple[str, ...],
        right_text: tuple[str, ...],
        left_normalised_title: str,
        right_normalised_title: str,
    ) -> tuple[bool, float, float, float, str]:
        title_similarity = _jaccard(left_title, right_title)
        text_similarity = _jaccard(left_text, right_text)
        same_title = bool(left_normalised_title) and (
            left_normalised_title == right_normalised_title
        )
        if same_title and text_similarity >= 0.50:
            matched = True
            rule = "same_normalised_title_and_related_text"
        elif title_similarity >= 0.60 and text_similarity >= 0.75:
            matched = True
            rule = "similar_title_and_high_text_overlap"
        else:
            matched = False
            rule = "below_threshold"
        confidence = round((0.40 * title_similarity) + (0.60 * text_similarity), 4)
        return matched, confidence, title_similarity, text_similarity, rule

    def _write_case(self, record: dict[str, Any]) -> None:
        if not self._valid_case(record):
            raise ValueError("invalid duplicate case")
        self.cases.mkdir(parents=True, exist_ok=True)
        self.store._atomic_json(self.cases / f"{record['id']}.json", record)

    def _case_record(
        self,
        *,
        case_id: str,
        kind: str,
        rule: str,
        confidence: float,
        documents: list[dict[str, Any]],
        evidence: dict[str, Any],
        existing: dict[str, Any] | None,
        operation_id: str,
        now: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": DUPLICATE_SCHEMA_VERSION,
            "id": case_id,
            "kind": kind,
            "status": "open",
            "current": True,
            "rule": rule,
            "confidence": round(confidence, 4),
            "first_seen_at": (
                str(existing["first_seen_at"])
                if existing and existing.get("first_seen_at")
                else now
            ),
            "last_seen_at": now,
            "last_scanned_at": now,
            "scan_operation_id": operation_id,
            "documents": documents[:MAX_CASE_DOCUMENTS],
            "evidence": evidence,
            "recommended_actions": (
                ["keep_separate", "link_occurrences", "review_as_version"]
                if kind == "exact"
                else ["keep_separate", "mark_related", "review_as_version"]
            ),
            "automatic_action": "none",
        }

    def scan(self) -> dict[str, Any]:
        operation = self.operations.start(
            "duplicate.scan",
            "Scan exact and probable duplicates",
            summary=(
                "Detect explainable duplicate candidates without merging, moving or deleting."
            ),
        )
        now = utc_now()
        warnings: list[dict[str, str]] = []
        try:
            documents, document_findings = safe_canonical_records(
                self.store,
                "documents",
            )
            versions, version_findings = safe_canonical_records(
                self.store,
                "versions",
            )
            acquisitions, acquisition_findings = safe_canonical_records(
                self.store,
                "acquisitions",
            )
            warnings.extend(
                {
                    "code": str(item["code"]),
                    "message": str(item["message"]),
                }
                for item in (
                    document_findings + version_findings + acquisition_findings
                )
            )
            if len(documents) > MAX_DUPLICATE_DOCUMENTS:
                raise DuplicateScanLimitError(
                    f"Instance exceeds the {MAX_DUPLICATE_DOCUMENTS}-document scan limit"
                )
            version_map = {str(item["id"]): item for item in versions}
            acquisition_counts: dict[str, int] = {}
            for acquisition in acquisitions:
                document_id = str(acquisition.get("document_id", ""))
                acquisition_counts[document_id] = (
                    acquisition_counts.get(document_id, 0) + 1
                )

            current: list[dict[str, Any]] = []
            for document in sorted(documents, key=lambda item: str(item["id"])):
                version = version_map.get(str(document.get("current_version_id", "")))
                if version is None or version.get("document_id") != document.get("id"):
                    warnings.append(
                        {
                            "code": "document_current_version_invalid",
                            "message": (
                                f"Skipped Document with invalid current Version: {document['id']}"
                            ),
                        }
                    )
                    continue
                snapshot = self._document_snapshot(
                    document,
                    version,
                    acquisition_counts.get(str(document["id"]), 0),
                )
                normalised_title = _normalised_title(snapshot["title"])
                title_tokens = _tokens(normalised_title, min_length=2)
                text, text_warning = self._safe_extracted_text(
                    self.store,
                    snapshot["version_id"],
                )
                if text_warning:
                    warnings.append(
                        {
                            "code": text_warning,
                            "message": (
                                f"Probable-duplicate text was unavailable for "
                                f"Document {snapshot['document_id']}."
                            ),
                        }
                    )
                current.append(
                    {
                        "snapshot": snapshot,
                        "normalised_title": normalised_title,
                        "title_tokens": title_tokens,
                        "text_tokens": _tokens(text, min_length=3),
                    }
                )

            self.operations.append(
                operation.id,
                "duplicate.records_loaded",
                "Loaded bounded current Document evidence.",
                details={
                    "documents": len(current),
                    "versions": len(versions),
                    "acquisitions": len(acquisitions),
                    "warnings": len(warnings),
                },
            )

            existing = self._existing_map()
            seen: set[str] = set()
            exact_cases: list[dict[str, Any]] = []
            groups: dict[str, list[dict[str, Any]]] = {}
            for item in current:
                groups.setdefault(item["snapshot"]["content_hash"], []).append(item)
            for content_hash, group in sorted(groups.items()):
                if len(group) < 2:
                    continue
                case_id = self._case_id("exact", content_hash)
                documents_for_case = [item["snapshot"] for item in group]
                case = self._case_record(
                    case_id=case_id,
                    kind="exact",
                    rule="same_current_content_hash",
                    confidence=1.0,
                    documents=documents_for_case,
                    evidence={
                        "content_hash": content_hash,
                        "document_count": len(documents_for_case),
                        "distinct_sources": len(
                            {item["source_id"] for item in documents_for_case}
                        ),
                        "shared_content_addressed_original_expected": True,
                    },
                    existing=existing.get(case_id),
                    operation_id=operation.id,
                    now=now,
                )
                self._write_case(case)
                seen.add(case_id)
                exact_cases.append(case)

            token_buckets: dict[str, list[int]] = {}
            for index, item in enumerate(current):
                for token in item["title_tokens"]:
                    token_buckets.setdefault(token, []).append(index)
            seen_pairs: set[tuple[int, int]] = set()
            candidate_pairs = 0
            pair_limit_reached = False
            probable_cases: list[dict[str, Any]] = []
            for token in sorted(token_buckets):
                indexes = sorted(set(token_buckets[token]))
                for left_index, right_index in combinations(indexes, 2):
                    pair = (left_index, right_index)
                    if pair in seen_pairs:
                        continue
                    if candidate_pairs >= MAX_CANDIDATE_PAIRS:
                        pair_limit_reached = True
                        break
                    seen_pairs.add(pair)
                    candidate_pairs += 1
                    left = current[left_index]
                    right = current[right_index]
                    if (
                        left["snapshot"]["content_hash"]
                        == right["snapshot"]["content_hash"]
                    ):
                        continue
                    if not left["text_tokens"] or not right["text_tokens"]:
                        continue
                    matched, confidence, title_similarity, text_similarity, rule = (
                        self._probable_rule(
                            left["title_tokens"],
                            right["title_tokens"],
                            left["text_tokens"],
                            right["text_tokens"],
                            left["normalised_title"],
                            right["normalised_title"],
                        )
                    )
                    if not matched:
                        continue
                    document_ids = sorted(
                        [
                            left["snapshot"]["document_id"],
                            right["snapshot"]["document_id"],
                        ]
                    )
                    identity = ":".join(document_ids)
                    case_id = self._case_id("probable", identity)
                    ordered = sorted(
                        [left["snapshot"], right["snapshot"]],
                        key=lambda item: item["document_id"],
                    )
                    case = self._case_record(
                        case_id=case_id,
                        kind="probable",
                        rule=rule,
                        confidence=confidence,
                        documents=ordered,
                        evidence={
                            "title_similarity": round(title_similarity, 4),
                            "text_similarity": round(text_similarity, 4),
                            "same_normalised_title": (
                                left["normalised_title"]
                                == right["normalised_title"]
                            ),
                            "different_content_hashes": True,
                            "compared_title_tokens": min(
                                len(left["title_tokens"]),
                                len(right["title_tokens"]),
                            ),
                            "compared_text_tokens": min(
                                len(left["text_tokens"]),
                                len(right["text_tokens"]),
                            ),
                        },
                        existing=existing.get(case_id),
                        operation_id=operation.id,
                        now=now,
                    )
                    self._write_case(case)
                    seen.add(case_id)
                    probable_cases.append(case)
                if pair_limit_reached:
                    break
            if pair_limit_reached:
                warnings.append(
                    {
                        "code": "candidate_pair_limit_reached",
                        "message": (
                            f"Probable-duplicate comparison stopped at "
                            f"{MAX_CANDIDATE_PAIRS} candidate pairs."
                        ),
                    }
                )

            stale_cases = 0
            for case_id, record in existing.items():
                if case_id in seen or not bool(record.get("current")):
                    continue
                stale = {
                    **record,
                    "status": "not_current",
                    "current": False,
                    "last_scanned_at": now,
                    "scan_operation_id": operation.id,
                    "automatic_action": "none",
                }
                self._write_case(stale)
                stale_cases += 1

            warnings = warnings[:MAX_SCAN_WARNINGS]
            status = "completed_with_errors" if warnings else "completed"
            self.operations.append(
                operation.id,
                "duplicate.scan_completed",
                "Completed exact and probable duplicate detection.",
                details={
                    "exact_cases": len(exact_cases),
                    "probable_cases": len(probable_cases),
                    "stale_cases": stale_cases,
                    "candidate_pairs": candidate_pairs,
                    "warnings": len(warnings),
                },
            )
            closed = self.operations.close(
                operation.id,
                status=status,
                summary=(
                    f"Found {len(exact_cases)} exact and {len(probable_cases)} "
                    "probable current duplicate cases; no automatic action was taken."
                ),
                metrics={
                    "documents_scanned": len(current),
                    "exact_cases": len(exact_cases),
                    "probable_cases": len(probable_cases),
                    "stale_cases": stale_cases,
                    "candidate_pairs": candidate_pairs,
                    "warnings": len(warnings),
                },
            )
            return {
                "operation": {
                    **closed.__dict__
                } if hasattr(closed, "__dict__") else {
                    "id": closed.id,
                    "kind": closed.kind,
                    "status": closed.status,
                    "summary": closed.summary,
                    "metrics": dict(closed.metrics),
                },
                "exact": exact_cases,
                "probable": probable_cases,
                "stale_cases": stale_cases,
                "warnings": warnings,
            }
        except (AssuranceLimitError, DuplicateScanLimitError):
            current_operation = self.operations.get_record(operation.id)
            if current_operation is not None and current_operation.status == "running":
                self.operations.close(
                    operation.id,
                    status="failed",
                    summary="Duplicate scan exceeded a safety limit.",
                    error_code="duplicate_scan_limit",
                    error="DuplicateScanLimitError",
                )
            raise
        except Exception as exc:
            current_operation = self.operations.get_record(operation.id)
            if current_operation is not None and current_operation.status == "running":
                self.operations.append(
                    operation.id,
                    "duplicate.scan_failed",
                    "Duplicate scan failed before completion.",
                    level="error",
                    details={"error_type": exc.__class__.__name__},
                )
                self.operations.close(
                    operation.id,
                    status="failed",
                    summary="Duplicate scan failed.",
                    error_code="duplicate_scan_failed",
                    error=exc.__class__.__name__,
                )
            raise
