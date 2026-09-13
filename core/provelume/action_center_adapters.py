"""Bounded, non-mutating projections of recorded Action Center evidence.

These are inventories of proposals, not scans of the user's files. Missing
derived output is never an extraction failure. Counts describe the records
actually read; unreadable, changing or bounded inventories cannot claim zero.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

import yaml

from .action_center_model import (
    QUEUES,
    ActionCenterError,
    bounded_json,
    digest,
    make_proposal,
    queue_observation,
)
from .duplicates import DuplicateCaseManager
from .folder_source_model import normalise_observer_record
from .hierarchy_model import canonical_hierarchy_errors
from .ingestion_runs import INGESTION_ITEM_STATUSES, INGESTION_RUN_STATUSES
from .ocr_contract import OCR_ERROR_MESSAGES
from .retention_model import canonical_disposition_errors
from .scheduler_model import utc_instant, validate_job_record
from .source_reconciliation_model import validate_reconciliation_run, validate_source_cursor
from .storage import InstanceStore
from .transcript_contract import TRANSCRIPT_ERROR_CODES

# Read budgets do not change any producer's safety limit. Exhaustion is partial.
MAX_RECORDS_PER_DIRECTORY = 500
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
MAX_PROPOSALS = 5_000
_ID = re.compile(r"[a-z][a-z0-9_]*_[0-9a-f]{32,64}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CANONICAL_IDS = {
    kind: re.compile(pattern)
    for kind, pattern in {
        "sources": r"src_[0-9a-f]{32}\Z",
        "documents": r"doc_[0-9a-f]{32}\Z",
        "versions": r"ver_[0-9a-f]{32}\Z",
        "originals": r"sha256_[0-9a-f]{64}\Z",
        "acquisitions": r"acq_[0-9a-f]{32}\Z",
    }.items()
}
_DOCUMENT_QUEUES = (
    "classification",
    "exact_duplicate",
    "probable_duplicate",
    "extraction_error",
    "retention",
    "source_change",
)
_INTAKE_QUEUES = ("intake", "extraction_error")


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _select(value: dict[str, Any], *fields: str) -> dict[str, Any]:
    return {field: value.get(field) for field in fields}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate producer record key")
        result[key] = value
    return result


def _semantic(value: Any) -> Any:
    """Exclude presentation/polling clocks, retaining all identity and state."""
    if isinstance(value, dict):
        return {
            key: _semantic(child)
            for key, child in value.items()
            if not key.endswith("_at") and key not in {"title", "name", "messages"}
        }
    if isinstance(value, list):
        return [_semantic(child) for child in value]
    return value


def _probable_evidence_matches(rule: str, evidence: dict[str, Any]) -> bool:
    """Validate the recorded rule inputs, without recalculating text similarity."""
    title, text = evidence.get("title_similarity"), evidence.get("text_similarity")
    if (
        any(type(value) not in (int, float) or not 0 <= value <= 1 for value in (title, text))
        or evidence.get("different_content_hashes") is not True
        or any(
            type(evidence.get(field)) is not int or not 1 <= evidence[field] <= 2_000
            for field in ("compared_title_tokens", "compared_text_tokens")
        )
    ):
        return False
    if rule == "same_normalised_title_and_related_text":
        return evidence.get("same_normalised_title") is True and text >= 0.50
    return rule == "similar_title_and_high_text_overlap" and title >= 0.60 and text >= 0.75


class _Reader:
    def __init__(self, store: InstanceStore):
        self.store = store
        self.reasons: dict[str, set[str]] = {queue: set() for queue in QUEUES}
        self.files: dict[Path, tuple[str | None, set[str]]] = {}
        self.directories: dict[Path, tuple[tuple[str, ...], set[str]]] = {}
        self.bytes_read = 0
        self.observed = {queue: 0 for queue in QUEUES}
        self.changed = False

    def problem(self, queues: tuple[str, ...], reason: str) -> None:
        for queue in queues:
            self.reasons[queue].add(reason)

    def _safe(self, path: Path) -> None:
        path.relative_to(self.store.paths.root)
        for selected in (path, *path.parents):
            if selected.is_symlink() or selected.is_junction():
                raise ValueError("linked evidence path")
            if selected == self.store.paths.root:
                break

    def _bytes(self, path: Path) -> bytes:
        self._safe(path)
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RECORD_BYTES:
            raise ValueError("record byte bound")
        with path.open("rb") as handle:
            raw = handle.read(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("record byte bound")
        return raw

    def record(
        self,
        path: Path,
        queues: tuple[str, ...],
        *,
        optional: bool = False,
        yaml_record: bool = False,
    ) -> dict[str, Any] | None:
        previous = self.files.get(path)
        owners = set(queues) | (previous[1] if previous else set())
        try:
            self._safe(path)
            if self.bytes_read >= MAX_SNAPSHOT_BYTES:
                self.problem(queues, "snapshot_byte_bound")
                return None
            if path.stat().st_size > MAX_SNAPSHOT_BYTES - self.bytes_read:
                self.problem(queues, "snapshot_byte_bound")
                return None
            raw = self._bytes(path)
            self.bytes_read += len(raw)
            if self.bytes_read > MAX_SNAPSHOT_BYTES:
                self.problem(queues, "snapshot_byte_bound")
                return None
            fingerprint = hashlib.sha256(raw).hexdigest()
            if previous and previous[0] != fingerprint:
                self.problem(tuple(owners), "snapshot_changed")
                self.changed = True
            self.files[path] = (fingerprint, owners)
            value = (
                yaml.safe_load(raw)
                if yaml_record
                else json.loads(raw, object_pairs_hook=_unique_object)
            )
            if not isinstance(value, dict):
                raise ValueError("record must be an object")
            bounded_json(value, maximum=MAX_RECORD_BYTES)
            return value
        except FileNotFoundError:
            self.files[path] = (None, owners)
            if not optional:
                self.problem(queues, "expected_record_missing")
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError, yaml.YAMLError):
            self.problem(queues, "record_invalid_or_unreadable")
        return None

    def _names(self, directory: Path) -> tuple[str, ...]:
        self._safe(directory)
        names: list[str] = []
        with os.scandir(directory) as entries:
            for entry in entries:
                # Count every entry: a directory full of unrelated files is bounded too.
                names.append(entry.name)
                if len(names) > MAX_RECORDS_PER_DIRECTORY:
                    break
        return tuple(sorted(names))

    def rows(
        self,
        directory: Path,
        queues: tuple[str, ...],
        *,
        identity: str = "id",
        required: bool = False,
        pattern: re.Pattern[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        try:
            names = self._names(directory)
        except FileNotFoundError:
            names = ()
            if required:
                self.problem(queues, "expected_inventory_missing")
        except (OSError, ValueError):
            self.problem(queues, "inventory_unreadable")
            return {}
        previous = self.directories.get(directory)
        self.directories[directory] = (names, set(queues) | (previous[1] if previous else set()))
        if len(names) > MAX_RECORDS_PER_DIRECTORY:
            self.problem(queues, "record_count_bound")
        result = {}
        for name in names[:MAX_RECORDS_PER_DIRECTORY]:
            if not name.endswith(".json"):
                continue
            path = directory / name
            row = self.record(path, queues)
            if row is None:
                continue
            identifier = row.get(identity)
            if (
                not _identifier(identifier)
                or identifier != path.stem
                or (pattern is not None and pattern.fullmatch(identifier) is None)
            ):
                self.problem(queues, "record_identity_invalid")
                continue
            result[identifier] = row
            for queue in queues:
                self.observed[queue] += 1
        return result

    def verify(self) -> None:
        """Bracket only recorded evidence; this does not pretend to be a transaction."""
        for path, (before, owners) in self.files.items():
            try:
                after = hashlib.sha256(self._bytes(path)).hexdigest()
            except FileNotFoundError:
                after = None
            except (OSError, ValueError):
                after = "unreadable"
            if after != before:
                self.changed = True
                self.problem(tuple(owners), "snapshot_changed")
        for path, (before, owners) in self.directories.items():
            try:
                after = self._names(path)
            except FileNotFoundError:
                after = ()
            except (OSError, ValueError):
                after = ("unreadable",)
            if after != before:
                self.changed = True
                self.problem(tuple(owners), "snapshot_changed")


class _Projection:
    def __init__(self, store: InstanceStore):
        self.store = store
        self.reader = _Reader(store)
        self.items: list[dict[str, Any]] = []
        self.canonical: dict[str, dict[str, dict[str, Any]]] = {}
        for kind in ("sources", "documents", "versions", "originals", "acquisitions"):
            self.canonical[kind] = self.reader.rows(
                store.paths.canonical_dir(kind),
                _DOCUMENT_QUEUES + ("intake",),
                required=True,
                pattern=_CANONICAL_IDS[kind],
            )
        self.config = (
            self.reader.record(
                store.paths.config, ("source_change", "extraction_error"), yaml_record=True
            )
            or {}
        )
        self.scheduler_jobs = self.reader.rows(
            store.paths.state / "scheduler" / "jobs", ("source_change", "extraction_error")
        )

    def emit(
        self,
        queue: str,
        producer: str,
        kind: str,
        reason: str,
        evidence: dict[str, Any],
        *,
        confidence: float | None = None,
        links: list[dict[str, str]] | None = None,
        semantic: Any = None,
        current: bool = True,
    ) -> None:
        if len(self.items) >= MAX_PROPOSALS:
            self.reader.problem((queue,), "proposal_count_bound")
            return
        proposal = {
            "kind": kind,
            "reason": reason,
            "confidence": confidence,
            "impact": (
                "rejects_proposal_only"
                if queue in {"exact_duplicate", "probable_duplicate"}
                else "records_inspection_only"
            ),
            "reversible": False,
            "choices": [],
        }
        try:
            actions = {
                "intake": ("acknowledge_evidence",),
                "extraction_error": ("acknowledge_evidence",),
                "source_change": ("acknowledge_evidence",),
                "exact_duplicate": ("reject_proposal",),
                "probable_duplicate": ("reject_proposal",),
            }
            candidate = make_proposal(
                queue,
                producer,
                proposal=proposal,
                evidence=evidence,
                domain_links=links or [],
                allowed_actions=actions.get(queue, ()) if current else (),
                revision_inputs=_semantic(
                    {"proposal": proposal, "input": (evidence if semantic is None else semantic)}
                ),
            )
            candidate["producer_current"] = current
            self.items.append(candidate)
        except ActionCenterError:
            self.reader.problem((queue,), "proposal_evidence_bound_or_invalid")

    def lineage(
        self, document_id: Any, queue: str, version_id: Any = None, *, historical: bool = False
    ) -> dict[str, Any] | None:
        document = (
            self.canonical["documents"].get(document_id) if _identifier(document_id) else None
        )
        selected_version = (
            version_id if historical else document.get("current_version_id") if document else None
        )
        version = (
            self.canonical["versions"].get(selected_version)
            if _identifier(selected_version)
            else None
        )
        original = self.canonical["originals"].get(version.get("original_id")) if version else None
        if (
            not document
            or not version
            or not original
            or version.get("document_id") != document_id
            or document.get("source_id") not in self.canonical["sources"]
            or not isinstance(version.get("content_hash"), str)
            or _HASH.fullmatch(version["content_hash"]) is None
            or original.get("sha256") != version["content_hash"]
            or type(version.get("size_bytes")) is not int
            or version["size_bytes"] < 0
            or original.get("size_bytes") != version["size_bytes"]
        ):
            self.reader.problem((queue,), "canonical_lineage_invalid_or_missing")
            return None
        if not historical and version_id is not None and version["id"] != version_id:
            self.reader.problem((queue,), "producer_input_stale")
            return None
        acquisitions = sorted(
            row["id"]
            for row in self.canonical["acquisitions"].values()
            if row.get("document_id") == document_id
            and row.get("version_id") == version["id"]
            and row.get("source_id") == document["source_id"]
            and row.get("content_hash") == version["content_hash"]
        )
        return {
            "source_id": document["source_id"],
            "document_id": document_id,
            "version_id": version["id"],
            "original_id": original["id"],
            "content_hash": version["content_hash"],
            "size_bytes": version["size_bytes"],
            "acquisition_ids": acquisitions,
            "original_bytes_verified": False,
        }

    @staticmethod
    def document_links(document_id: str) -> list[dict[str, str]]:
        return [
            {"href": f"/documents/{document_id}", "kind": "document"},
            {"href": f"/documents/{document_id}/provenance", "kind": "provenance"},
        ]

    def classification_retention(self) -> None:
        reader = self.reader
        documents = self.canonical["documents"]
        classifications = reader.rows(
            self.store.paths.canonical_dir("classifications"), ("classification",)
        )
        nodes = reader.rows(self.store.paths.canonical_dir("hierarchy"), ("classification",))
        dispositions = reader.rows(
            self.store.paths.canonical_dir("dispositions"), ("classification", "retention")
        )
        valid_classifications = not canonical_hierarchy_errors(nodes, classifications, documents)
        valid_dispositions = not canonical_disposition_errors(dispositions, documents)
        valid_classifications = valid_classifications and not reader.reasons["classification"]
        valid_dispositions = valid_dispositions and not reader.reasons["retention"]
        if not valid_classifications:
            reader.problem(("classification",), "classification_inventory_invalid")
        if not valid_dispositions:
            reader.problem(("classification", "retention"), "disposition_inventory_invalid")
        classified = {row.get("document_id") for row in classifications.values()}
        by_document = {row.get("document_id"): row for row in dispositions.values()}
        for document_id in documents:
            disposition = by_document.get(document_id)
            if not valid_dispositions:
                continue
            if disposition and disposition["status"] == "trashed":
                lineage = self.lineage(document_id, "retention")
                if lineage:
                    self.emit(
                        "retention",
                        disposition["id"],
                        "review_recoverable_trash",
                        "recorded_trashed",
                        {**lineage, "disposition": disposition},
                        links=self.document_links(document_id),
                    )
            elif (
                valid_classifications
                and document_id not in classified
                and (not disposition or disposition["library_visibility"] == "included")
            ):
                lineage = self.lineage(document_id, "classification")
                if lineage:
                    self.emit(
                        "classification",
                        document_id,
                        "needs_manual_placement",
                        "visible_unclassified",
                        {**lineage, "classification": None, "disposition": disposition},
                        links=self.document_links(document_id),
                    )

    def duplicates(self) -> None:
        queues = ("exact_duplicate", "probable_duplicate")
        cases = self.reader.rows(self.store.paths.state / "duplicates" / "cases", queues)
        for case_id, case in cases.items():
            if not DuplicateCaseManager._valid_case(case):
                self.reader.problem(queues, "duplicate_case_invalid")
                continue
            queue = "exact_duplicate" if case["kind"] == "exact" else "probable_duplicate"
            current = case["current"] and case["status"] == "open"
            snapshots = case["documents"]
            if (
                len(snapshots) < 2
                or any(not isinstance(row, dict) for row in snapshots)
                or len({row.get("document_id") for row in snapshots}) != len(snapshots)
            ):
                self.reader.problem((queue,), "duplicate_participants_invalid")
                continue
            lineage = [
                self.lineage(
                    row.get("document_id"), queue, row.get("version_id"), historical=not current
                )
                for row in snapshots
            ]
            if any(row is None for row in lineage):
                continue
            if any(
                row["content_hash"] != old.get("content_hash")
                for row, old in zip(lineage, snapshots, strict=True)
            ):
                self.reader.problem((queue,), "producer_input_stale")
                continue
            evidence = case["evidence"]
            if evidence.get("documents_total") != len(snapshots) or evidence.get(
                "documents_retained"
            ) != len(snapshots):
                self.reader.problem((queue,), "duplicate_participants_partial")
                continue
            hashes = {row["content_hash"] for row in lineage}
            confidence = case.get("confidence")
            if (
                type(confidence) not in (int, float)
                or not 0 <= confidence <= 1
                or (
                    queue == "exact_duplicate"
                    and (
                        len(hashes) != 1
                        or confidence != 1
                        or case.get("rule") != "same_current_content_hash"
                        or evidence.get("content_hash") not in hashes
                    )
                )
                or (
                    queue == "probable_duplicate"
                    and (
                        len(hashes) < 2
                        or not _probable_evidence_matches(case.get("rule"), evidence)
                    )
                )
            ):
                self.reader.problem((queue,), "duplicate_rule_invalid")
                continue
            inputs = {
                "lineage": lineage,
                "source_ids": sorted({row["source_id"] for row in lineage}),
                "rule": case.get("rule"),
                "evidence": evidence,
                "confidence": confidence,
            }
            self.emit(
                queue,
                case_id,
                "review_duplicate_evidence",
                str(case["rule"]),
                {
                    **inputs,
                    "case_id": case_id,
                    "scan_operation_id": case.get("scan_operation_id"),
                    "recommended_actions": case["recommended_actions"],
                },
                confidence=confidence,
                links=[{"href": f"/duplicates/{case_id}", "kind": "duplicate_case"}],
                semantic=inputs,
                current=current,
            )

    def intake(self) -> None:
        reader = self.reader
        root = self.store.paths.state / "ingestion"
        runs = reader.rows(root / "runs", _INTAKE_QUEUES)
        items = reader.rows(root / "items", _INTAKE_QUEUES)
        valid_items = {}
        for identifier, row in items.items():
            run = runs.get(row.get("run_id"))
            if (
                row.get("schema_version") != 1
                or row.get("status") not in INGESTION_ITEM_STATUSES
                or type(row.get("attempt")) is not int
                or row["attempt"] < 1
                or not run
                or row.get("source_id") != run.get("source_id")
            ):
                reader.problem(_INTAKE_QUEUES, "ingestion_item_invalid_or_unbound")
            else:
                valid_items[identifier] = row
        items = valid_items
        descendants: dict[str, list[str]] = {}
        for identifier, row in items.items():
            parent = row.get("retry_of_item_id")
            if parent:
                prior = items.get(parent)
                if (
                    not prior
                    or prior["attempt"] + 1 != row["attempt"]
                    or prior.get("source_id") != row.get("source_id")
                    or prior.get("locator") != row.get("locator")
                ):
                    reader.problem(_INTAKE_QUEUES, "retry_lineage_invalid_or_partial")
                else:
                    descendants.setdefault(parent, []).append(identifier)
        represented_acquisitions = {row.get("acquisition_id") for row in items.values()}
        for identifier, row in items.items():
            if row["status"] != "failed" or identifier in descendants:
                continue
            queue = "extraction_error" if row.get("error_code") == "extraction_failed" else "intake"
            attempts = [row]
            parent = row.get("retry_of_item_id")
            while parent in items and len(attempts) <= MAX_RECORDS_PER_DIRECTORY:
                previous = items[parent]
                if previous in attempts:
                    reader.problem((queue,), "retry_cycle")
                    break
                attempts.append(previous)
                parent = previous.get("retry_of_item_id")
            evidence = {
                "producer": "ingestion_item",
                **_select(
                    row,
                    "source_id",
                    "run_id",
                    "attempt",
                    "acquisition_id",
                    "outcome",
                    "retry_of_item_id",
                    "error_code",
                    "status",
                ),
                "item_id": identifier,
                "attempts": [
                    _select(
                        attempt,
                        "id",
                        "run_id",
                        "attempt",
                        "status",
                        "retry_of_item_id",
                        "acquisition_id",
                        "outcome",
                        "error_code",
                    )
                    for attempt in reversed(attempts)
                ],
            }
            acquisition = self.canonical["acquisitions"].get(row.get("acquisition_id"))
            if row.get("acquisition_id"):
                if not acquisition:
                    reader.problem((queue,), "acquisition_missing")
                    continue
                lineage = self.acquisition_lineage(acquisition, queue)
                if not lineage:
                    continue
                if queue == "extraction_error" and self._extraction_recovered(acquisition):
                    continue
                evidence.update(lineage)
            self.emit(
                queue,
                identifier,
                "review_failed_acquisition" if queue == "intake" else "review_extraction_error",
                row.get("error_code") or "ingestion_failed",
                evidence,
                links=[{"href": "/inbox", "kind": "intake"}],
            )
        run_items = {row["run_id"] for row in items.values()}
        retry_runs = {row.get("retry_of_run_id") for row in runs.values()}
        for run_id, run in runs.items():
            if run.get("schema_version") != 1 or run.get("status") not in INGESTION_RUN_STATUSES:
                reader.problem(_INTAKE_QUEUES, "ingestion_run_invalid")
            elif run["status"] == "failed" and run_id not in run_items and run_id not in retry_runs:
                if run.get("item_count") != 0:
                    reader.problem(_INTAKE_QUEUES, "run_items_missing")
                    continue
                self.emit(
                    "intake",
                    run_id,
                    "review_failed_acquisition",
                    run.get("error_code") or "ingestion_failed",
                    {
                        "producer": "ingestion_run",
                        **_select(run, "source_id", "status", "error_code", "retry_of_run_id"),
                        "run_id": run_id,
                    },
                    links=[{"href": "/inbox", "kind": "intake"}],
                )
        submissions = reader.rows(self.store.paths.state / "inbox" / "submissions", _INTAKE_QUEUES)
        legacy = reader.rows(self.store.paths.root / "inbox" / "submissions", _INTAKE_QUEUES)
        new_names = self.reader.directories.get(
            self.store.paths.state / "inbox" / "submissions", ((), set())
        )[0]
        retained = {key: value for key, value in legacy.items() if key + ".json" not in new_names}
        for identifier, submission in {**retained, **submissions}.items():
            if submission.get("schema_version") != 1 or submission.get("status") not in {
                "running",
                "completed",
                "completed_with_errors",
                "failed",
            }:
                reader.problem(_INTAKE_QUEUES, "submission_invalid")
                continue
            linked = submission.get("ingestion_run_id")
            if linked:
                if linked not in runs:
                    reader.problem(_INTAKE_QUEUES, "submission_run_missing")
                continue
            if submission["status"] in {"failed", "completed_with_errors"}:
                self.emit(
                    "intake",
                    identifier,
                    "review_failed_acquisition",
                    "submission_failed",
                    {
                        "producer": "inbox_submission",
                        "submission_id": identifier,
                        **_select(
                            submission, "source_id", "operation_id", "status", "failed_items"
                        ),
                    },
                    links=[{"href": "/inbox", "kind": "intake"}],
                )
        for acquisition in self.canonical["acquisitions"].values():
            if (
                acquisition.get("outcome") != "extraction_failed"
                or acquisition["id"] in represented_acquisitions
                or self._extraction_recovered(acquisition)
            ):
                continue
            lineage = self.acquisition_lineage(acquisition, "extraction_error")
            if lineage:
                self.emit(
                    "extraction_error",
                    acquisition["id"],
                    "review_extraction_error",
                    "extraction_failed",
                    {**lineage, "producer": "acquisition", "acquisition_id": acquisition["id"]},
                    links=self.document_links(lineage["document_id"]),
                )

    def acquisition_lineage(self, acquisition: dict[str, Any], queue: str) -> dict[str, Any] | None:
        lineage = self.lineage(acquisition.get("document_id"), queue, acquisition.get("version_id"))
        if lineage and (
            acquisition.get("source_id") != lineage["source_id"]
            or acquisition.get("content_hash") != lineage["content_hash"]
            or acquisition.get("original_id") not in {None, lineage["original_id"]}
        ):
            self.reader.problem((queue,), "acquisition_lineage_invalid")
            return None
        return lineage

    def _extraction_recovered(self, acquisition: dict[str, Any]) -> bool:
        return any(
            row.get("document_id") == acquisition.get("document_id")
            and row.get("source_id") == acquisition.get("source_id")
            and row.get("version_id") == acquisition.get("version_id")
            and row.get("content_hash") == acquisition.get("content_hash")
            and row.get("outcome") == "extraction_recovered"
            for row in self.canonical["acquisitions"].values()
        )

    def extraction_jobs(self) -> None:
        queue = ("extraction_error",)
        jobs = self.scheduler_jobs
        recipes: dict[str, list[dict[str, Any]]] = {}
        for kind, directory in (("ocr.execute", "ocr"), ("transcript.intake", "transcript-intake")):
            root = self.store.paths.state / directory
            runs = self.reader.rows(root / "runs", queue, identity="job_id")
            for job_id, run in runs.items():
                job = jobs.get(job_id)
                try:
                    job = validate_job_record(job)
                    if job["job_kind"] != kind or run.get("schema_version") != 1:
                        raise ValueError("job kind mismatch")
                except (ValueError, TypeError, KeyError):
                    self.reader.problem(queue, "extraction_job_invalid_or_missing")
                    continue
                state = run.get("state", run.get("status"))
                if state in {"running", "cancelled"}:
                    continue
                if state not in {"failed", "completed_with_errors", "succeeded", "completed"}:
                    self.reader.problem(queue, "extraction_run_state_invalid")
                    continue
                request_key = job.get("idempotency_key") if directory == "ocr" else job_id
                if (
                    not isinstance(request_key, str)
                    or re.fullmatch(r"[a-zA-Z0-9_-]{1,180}", request_key) is None
                ):
                    self.reader.problem(queue, "extraction_request_identity_invalid")
                    continue
                request = self.reader.record(root / "requests" / f"{request_key}.json", queue)
                if request is None:
                    continue
                succeeded = state in {"succeeded", "completed"}
                if not job["attempts"] or job["attempts"][-1]["completed_at"] is None:
                    self.reader.problem(queue, "extraction_attempt_incomplete")
                    continue
                evidence = {
                    "producer": kind,
                    "job_id": job_id,
                    "attempt": job["attempt"],
                    "attempts": job["attempts"],
                    "request_digest": digest(_semantic(request)),
                    "state": state,
                }
                if directory == "ocr":
                    version = self.canonical["versions"].get(run.get("version_id"))
                    lineage = self.lineage(
                        version.get("document_id") if version else None,
                        "extraction_error",
                        run.get("version_id"),
                    )
                    if not lineage:
                        continue
                    error = run.get("error")
                    if (
                        (
                            not succeeded
                            and (
                                not isinstance(error, dict)
                                or error.get("code") not in OCR_ERROR_MESSAGES
                            )
                        )
                        or (succeeded and (error is not None or not run.get("bundle_ref")))
                        or request.get("scheduler_key") != request_key
                        or request.get("version_id") != run.get("version_id")
                        or request.get("derivation_key") != run.get("derivation_key")
                        or run.get("original_sha256_before") != lineage["content_hash"]
                        or run.get("original_sha256_after") != lineage["content_hash"]
                    ):
                        self.reader.problem(queue, "extraction_run_binding_invalid")
                        continue
                    evidence.update(
                        {
                            **lineage,
                            "derivation_key": run["derivation_key"],
                            "error_code": None if succeeded else error["code"],
                        }
                    )
                    reason = None if succeeded else error["code"]
                    recipe = digest([kind, run["version_id"], run["derivation_key"]])
                    links = self.document_links(lineage["document_id"])
                else:
                    errors = run.get("error_codes")
                    if (
                        not isinstance(errors, list)
                        or (not succeeded and not errors)
                        or (succeeded and errors)
                        or any(code not in TRANSCRIPT_ERROR_CODES for code in errors)
                        or run.get("source_id") not in self.canonical["sources"]
                        or request.get("job_id") != job_id
                        or job["scope"].get("id") != run.get("source_id")
                        or request.get("source_id") != run.get("source_id")
                        or request.get("snapshot_sha256") != run.get("snapshot_sha256")
                    ):
                        self.reader.problem(queue, "extraction_run_binding_invalid")
                        continue
                    configured = self.config.get("transcript_sources", {}).get(run["source_id"])
                    if (
                        not isinstance(configured, dict)
                        or configured.get("config_revision") != request.get("config_revision")
                        or configured.get("lifecycle_state") != "active"
                    ):
                        self.reader.problem(queue, "transcript_input_stale")
                        continue
                    reason = None if succeeded else errors[0]
                    recipe = digest(
                        [
                            kind,
                            run["source_id"],
                            run["snapshot_sha256"],
                            request.get("settings_sha256"),
                            request.get("profile"),
                            request.get("config_revision"),
                        ]
                    )
                    evidence.update(
                        {
                            **_select(run, "source_id", "snapshot_sha256", "error_codes"),
                            "recipe_digest": digest(_semantic(request)),
                        }
                    )
                    links = [{"href": "/sources", "kind": "source"}]
                recipes.setdefault(recipe, []).append(
                    {
                        "job_id": job_id,
                        "succeeded": succeeded,
                        "reason": reason,
                        "evidence": evidence,
                        "links": links,
                        "completed_at": job["attempts"][-1]["completed_at"],
                    }
                )
        for records in recipes.values():
            records.sort(key=lambda row: (utc_instant(row["completed_at"]), row["job_id"]))
            latest = records[-1]
            if len(records) > 1 and (
                utc_instant(records[-2]["completed_at"]) == utc_instant(latest["completed_at"])
            ):
                self.reader.problem(queue, "extraction_recipe_order_unknown")
                continue
            if latest["succeeded"]:
                continue
            evidence = {
                **latest["evidence"],
                "related_jobs": [
                    {
                        "job_id": row["job_id"],
                        "state": row["evidence"]["state"],
                        "attempts": row["evidence"]["attempts"],
                        "request_digest": row["evidence"]["request_digest"],
                    }
                    for row in records
                ],
            }
            self.emit(
                "extraction_error",
                latest["job_id"],
                "review_extraction_error",
                latest["reason"],
                evidence,
                links=latest["links"],
            )

    def sources(self) -> None:
        from .source_reconciliation import SourceReconciliationManager

        queue = ("source_change",)
        root = self.store.paths.state
        observers = self.reader.rows(
            root / "folder-sources" / "observers", queue, identity="source_id"
        )
        cursors = self.reader.rows(
            root / "source-reconciliation" / "cursors", queue, identity="source_id"
        )
        runs = self.reader.rows(root / "source-reconciliation" / "runs", queue)
        validated_runs = {}
        for run_id, run in runs.items():
            try:
                validated_runs[run_id] = validate_reconciliation_run(run)
            except (ValueError, TypeError, KeyError):
                self.reader.problem(queue, "reconciliation_run_invalid")
        runs = validated_runs
        manager = SourceReconciliationManager(_RecordedStore(self))
        configured = self.config.get("sources", {})
        if not isinstance(configured, dict):
            self.reader.problem(queue, "source_configuration_invalid")
            return
        source_ids = (
            set(observers)
            | set(cursors)
            | {
                identifier
                for identifier, row in configured.items()
                if isinstance(row, dict) and isinstance(row.get("folder"), dict)
            }
        )
        for source_id in sorted(source_ids):
            if source_id not in self.canonical["sources"]:
                self.reader.problem(queue, "source_missing")
                continue
            cursor = cursors.get(source_id)
            for run in runs.values():
                prior = runs.get(cursor.get("last_run_id")) if cursor else None
                if (
                    run["source_id"] == source_id
                    and run["status"] == "scanning"
                    and (
                        not prior
                        or utc_instant(run["created_at"]) > utc_instant(prior["created_at"])
                    )
                ):
                    self.reader.problem(queue, "reconciliation_not_committed")
            if cursor:
                try:
                    cursor = validate_source_cursor(cursor)
                    if cursor["code"] == "never_reconciled":
                        cursor = None
                    elif cursor.get("last_run_id"):
                        run = validate_reconciliation_run(runs.get(cursor["last_run_id"]))
                        job = validate_job_record(self.scheduler_jobs.get(run["job_id"]))
                        _, config_hash, _ = manager._configuration(source_id)
                        _, canonical_hash = manager._canonical_rows(source_id)
                        if (
                            run["source_id"] != source_id
                            or job["job_kind"] != "maintenance.source_reconcile"
                            or job["scope"] != {"kind": "source", "id": source_id}
                            or run["status"] == "superseded"
                            or run["plan_revision"] != cursor["last_run_revision"]
                            or run["plan"]["configuration_fingerprint"] != config_hash
                            or run["plan"]["canonical_fingerprint"] != canonical_hash
                            or cursor["configuration_fingerprint"] != config_hash
                            or cursor["snapshot_fingerprint"] != run["plan"]["snapshot_fingerprint"]
                        ):
                            raise ValueError("reconciliation input is stale")
                        base = {
                            "source_id": source_id,
                            "run_id": run["id"],
                            "job_id": run["job_id"],
                            "attempt": job["attempt"],
                            "attempts": job["attempts"],
                            "plan_revision": run["plan_revision"],
                            "plan_digest": run["plan_digest"],
                            "cursor_revision": cursor["revision"],
                            "configuration_fingerprint": config_hash,
                            "canonical_fingerprint": canonical_hash,
                        }
                        for item in run["plan"]["items"][:MAX_RECORDS_PER_DIRECTORY]:
                            if item["classification"] != "current":
                                self.emit(
                                    "source_change",
                                    run["id"] + ":" + item["identity"],
                                    "review_source_change",
                                    item["classification"],
                                    {**base, "item": item},
                                    links=[{"href": "/sources", "kind": "source"}],
                                )
                        if len(run["plan"]["items"]) > MAX_RECORDS_PER_DIRECTORY:
                            self.reader.problem(queue, "plan_item_count_bound")
                        if run["plan"]["snapshot_state"] in {"missing", "error"}:
                            self.emit(
                                "source_change",
                                source_id,
                                "review_source_availability",
                                cursor["code"],
                                {**base, "state": cursor["state"], "code": cursor["code"]},
                                links=[{"href": "/sources", "kind": "source"}],
                            )
                        continue  # A valid plan owns this Source; do not duplicate its observer.
                except (ValueError, TypeError, KeyError, OSError):
                    self.reader.problem(queue, "reconciliation_invalid_or_stale")
                    continue
            observer = observers.get(source_id)
            if not observer:
                self.reader.problem(queue, "source_not_observed")
                continue
            try:
                observer = normalise_observer_record(observer)
            except (ValueError, TypeError):
                self.reader.problem(queue, "source_observer_invalid")
                continue
            if observer["phase"] == "unobserved" or observer["last_observed_at"] is None:
                self.reader.problem(queue, "source_not_observed")
                continue
            try:
                folder, config_hash, _ = manager._configuration(source_id)
            except (ValueError, OSError, KeyError):
                self.reader.problem(queue, "source_configuration_invalid")
                continue
            if folder["lifecycle_state"] == "paused":
                continue
            if folder["lifecycle_state"] != observer["lifecycle_state"]:
                self.reader.problem(queue, "source_observer_stale")
                continue
            delta = (
                observer["phase"] in {"quiescing", "ready"}
                and observer["pending_fingerprint"] != observer["ingested_fingerprint"]
            )
            unavailable = (
                observer["availability"] in {"missing", "attention"} or observer["last_error_code"]
            )
            if delta or unavailable:
                try:
                    _, config_hash, _ = manager._configuration(source_id)
                except (ValueError, OSError, KeyError):
                    self.reader.problem(queue, "source_configuration_invalid")
                    continue
                self.emit(
                    "source_change",
                    source_id,
                    "review_source_change" if delta else "review_source_availability",
                    "observed_delta" if delta else observer["last_error_code"] or "source_missing",
                    {
                        "source_id": source_id,
                        "observer": observer,
                        "configuration_fingerprint": config_hash,
                    },
                    links=[{"href": "/sources", "kind": "source"}],
                )


class _RecordedStore(InstanceStore):
    """Reuse owner validation against this bounded in-memory evidence only."""

    def __init__(self, projection: _Projection):
        self.paths = projection.store.paths
        self.projection = projection

    def read_config(self) -> dict[str, Any]:
        return self.projection.config

    def read_canonical(self, kind: str, record_id: str) -> dict[str, Any] | None:
        return self.projection.canonical.get(kind, {}).get(record_id)

    def list_canonical(self, kind: str) -> list[dict[str, Any]]:
        return list(self.projection.canonical.get(kind, {}).values())


def collect_proposals(store: InstanceStore) -> dict[str, Any]:
    """Return all eight bounded contributions without opening or mutating Instance state.

    The core adds its explicit version-conflict producer and durable decisions.
    Decisions must recollect under the owners' actual writer guards; bracketing
    detects an observed race but grants no write authority by itself.
    """
    projection = _Projection(store)
    for adapter, owners in (
        (projection.classification_retention, ("classification", "retention")),
        (projection.duplicates, ("exact_duplicate", "probable_duplicate")),
        (projection.intake, _INTAKE_QUEUES),
        (projection.extraction_jobs, ("extraction_error",)),
        (projection.sources, ("source_change",)),
    ):
        try:
            adapter()
        except (ValueError, TypeError, KeyError, OSError, RecursionError):
            projection.reader.problem(owners, "producer_record_invalid_or_unreadable")
    projection.reader.verify()
    queues = {}
    for queue in QUEUES:
        count = sum(item["queue"] == queue for item in projection.items)
        reasons = projection.reader.reasons[queue]
        queues[queue] = queue_observation(
            queue,
            complete=not reasons,
            observed_count=projection.reader.observed[queue],
            returned=count,
            matched_count=None if reasons else count,
            count_relation="unknown" if reasons else "exact",
            reason=",".join(sorted(reasons)) or None,
            bound={
                "records_per_directory": MAX_RECORDS_PER_DIRECTORY,
                "record_bytes": MAX_RECORD_BYTES,
                "snapshot_bytes": MAX_SNAPSHOT_BYTES,
                "proposals": MAX_PROPOSALS,
            },
            snapshot_changed="snapshot_changed" in reasons,
        )
    return {
        "items": sorted(projection.items, key=lambda item: (item["queue"], item["producer_id"])),
        "queues": queues,
    }
