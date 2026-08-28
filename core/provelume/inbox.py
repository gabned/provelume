from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from .domain import Source
from .extractors import extractor_for
from .index import rebuild_search_index
from .ingest import (
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_FILES,
    _close_run,
    _new_item,
    _new_run,
    _process_item,
)
from .ingestion_runs import IngestionLedger
from .operations import OperationLedger
from .paths import UnsafePathError, normalise_locator
from .storage import InstanceStore, utc_now

INBOX_SCHEMA_VERSION = 1
INBOX_SOURCE_NAME = "Local Inbox"
_SUBMISSION_ID = re.compile(r"inbox_[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class InboxSubmission:
    schema_version: int
    id: str
    operation_id: str
    ingestion_run_id: str | None
    source_id: str
    status: str
    mode: str
    input_name: str
    created_at: str
    completed_at: str | None
    total_items: int
    completed_items: int
    failed_items: int
    items: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["items"] = [dict(item) for item in self.items]
        return value


class InboxManager:
    """Safe local capture into an Instance-owned Inbox Source."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.root / "inbox"
        self.drop = self.root / "drop"
        self.items = self.root / "items"
        self.submissions = self.root / "submissions"
        self.operations = OperationLedger(store)

    def ensure(self) -> None:
        for path in (self.drop, self.items, self.submissions):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _lexical_absolute(path: Path) -> Path:
        return Path(os.path.abspath(path.expanduser()))

    def _source_id(self) -> str:
        self.ensure()
        existing = self.store.find_source_for_path(self.items)
        if existing is not None:
            return existing
        instance_id = str(self.store.read_config()["instance"]["id"])
        value = f"provelume:{instance_id}:local-inbox"
        source_id = f"src_{uuid5(NAMESPACE_URL, value).hex}"
        if self.store.read_canonical("sources", source_id) is None:
            self.store.write_source(
                Source(
                    id=source_id,
                    kind="filesystem",
                    name=INBOX_SOURCE_NAME,
                    created_at=utc_now(),
                )
            )
        self.store.register_source_path(
            source_id,
            self.items,
            name=INBOX_SOURCE_NAME,
        )
        return source_id

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _files(
        cls,
        source: Path,
        max_files: int,
    ) -> list[tuple[str, Path, Path]]:
        lexical = cls._lexical_absolute(source)
        canonical = lexical.resolve(strict=True)
        if canonical.is_file():
            lexical_root = lexical.parent
            canonical_root = canonical.parent
            candidates = [lexical]
        elif canonical.is_dir():
            lexical_root = lexical
            canonical_root = canonical
            candidates = sorted(
                (path for path in lexical.rglob("*") if path.is_file()),
                key=lambda path: path.as_posix(),
            )
        else:
            raise ValueError("submitted path is not a file or directory")

        accepted: list[tuple[str, Path, Path]] = []
        for lexical_candidate in candidates:
            resolved = lexical_candidate.resolve(strict=True)
            if not resolved.is_file():
                continue
            try:
                resolved.relative_to(canonical_root)
            except ValueError as exc:
                raise UnsafePathError("submitted symlink escapes its source root") from exc
            relative = normalise_locator(
                lexical_candidate.relative_to(lexical_root).as_posix()
            )
            if extractor_for(Path(relative)) is None:
                continue
            accepted.append((relative, resolved, lexical_candidate))
            if len(accepted) > max_files:
                raise ValueError(
                    f"submission exceeds the {max_files}-file safety limit"
                )
        return accepted

    @staticmethod
    def _copy_verified(source: Path, target: Path) -> str:
        digest_before = InboxManager._digest(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        digest_after = InboxManager._digest(source)
        staged_digest = InboxManager._digest(target)
        if not digest_before == digest_after == staged_digest:
            target.unlink(missing_ok=True)
            raise RuntimeError("source changed while it was copied into the Inbox")
        return staged_digest

    def _write_submission(self, submission: InboxSubmission) -> None:
        self.ensure()
        self.store._atomic_json(
            self.submissions / f"{submission.id}.json",
            submission.as_dict(),
        )

    def list_submissions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or not self.submissions.exists():
            return []
        records = []
        for path in self.submissions.glob("inbox_*.json"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    value = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if (
                isinstance(value, dict)
                and _SUBMISSION_ID.fullmatch(str(value.get("id", ""))) is not None
                and isinstance(value.get("created_at"), str)
            ):
                records.append(value)
        records.sort(
            key=lambda item: (
                str(item.get("created_at", "")),
                str(item.get("id", "")),
            ),
            reverse=True,
        )
        return records[: min(limit, 500)]

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        if _SUBMISSION_ID.fullmatch(submission_id) is None:
            return None
        path = self.submissions / f"{submission_id}.json"
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _remove_if_unchanged(source: Path, expected_sha256: str) -> bool:
        try:
            if not source.is_file():
                return False
            if InboxManager._digest(source) != expected_sha256:
                return False
            source.unlink()
        except OSError:
            return False
        return True

    @classmethod
    def _remove_empty_parents(cls, path: Path, stop: Path) -> None:
        current = cls._lexical_absolute(path.parent)
        boundary = cls._lexical_absolute(stop)
        try:
            current.relative_to(boundary)
        except ValueError:
            return
        while current != boundary and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _verified_original_exists(self, digest: str, staged_path: Path) -> bool:
        original = self.store.read_canonical("originals", f"sha256_{digest}")
        if original is None:
            return False
        return self.store.original_bytes(original["id"]) == staged_path.read_bytes()

    def _start_operation(
        self,
        source: Path,
        submission_id: str,
        source_id: str,
        move_after_commit: bool,
    ):
        operation = self.operations.start(
            "inbox.submit",
            f"Capture {source.name}",
            summary="Copy submitted files into the local Inbox and acquire exact bytes.",
            related={"submission_id": submission_id, "source_id": source_id},
        )
        self.operations.append(
            operation.id,
            "inbox.enumeration_started",
            "Enumerating supported local files.",
            details={
                "mode": "move_after_commit" if move_after_commit else "copy"
            },
        )
        return operation

    def submit(
        self,
        source_path: Path | str,
        *,
        move_after_commit: bool = False,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> dict[str, Any]:
        self.ensure()
        source = self._lexical_absolute(Path(source_path))
        canonical = source.resolve(strict=True)
        source_root = source.parent if canonical.is_file() else source
        source_id = self._source_id()
        submission_id = f"inbox_{uuid4().hex}"
        operation = self._start_operation(
            source,
            submission_id,
            source_id,
            move_after_commit,
        )

        try:
            candidates = self._files(source, max_files)
            staged: list[tuple[str, Path, Path, str]] = []
            submission_items: list[dict[str, Any]] = []
            for relative, copy_source, removal_source in candidates:
                size = copy_source.stat().st_size
                locator = normalise_locator(f"{submission_id}/{relative}")
                if size > max_file_bytes:
                    submission_items.append(
                        {
                            "locator": locator,
                            "status": "failed",
                            "error_code": "file_too_large",
                            "error": (
                                f"{relative} exceeds the configured byte safety limit"
                            ),
                            "sha256": None,
                            "acquisition_id": None,
                            "moved_source": False,
                        }
                    )
                    self.operations.append(
                        operation.id,
                        "inbox.item_rejected",
                        f"{relative} exceeded the byte safety limit.",
                        level="warning",
                        details={"locator": locator, "size_bytes": size},
                    )
                    continue
                target = self.items / Path(*PurePosixPath(locator).parts)
                try:
                    staged_digest = self._copy_verified(copy_source, target)
                except RuntimeError as exc:
                    submission_items.append(
                        {
                            "locator": locator,
                            "status": "failed",
                            "error_code": "copy_verification_failed",
                            "error": str(exc),
                            "sha256": None,
                            "acquisition_id": None,
                            "moved_source": False,
                        }
                    )
                    self.operations.append(
                        operation.id,
                        "inbox.copy_verification_failed",
                        f"Exact-byte staging failed for {relative}.",
                        level="warning",
                        details={"locator": locator},
                    )
                    continue
                staged.append((locator, target, removal_source, staged_digest))
                self.operations.append(
                    operation.id,
                    "inbox.item_staged",
                    f"Copied and hash-verified {relative}.",
                    details={
                        "locator": locator,
                        "sha256": staged_digest,
                        "size_bytes": size,
                    },
                )

            ledger = IngestionLedger(self.store)
            run = _new_run(
                ledger,
                source_id=source_id,
                max_file_bytes=max_file_bytes,
                max_files=max_files,
            )
            ingestion_items = [
                _new_item(
                    ledger,
                    run_id=run.id,
                    source_id=source_id,
                    locator=locator,
                )
                for locator, _target, _external, _digest in staged
            ]
            run = replace(run, item_count=len(ingestion_items))
            ledger.write_run(run)
            for item in ingestion_items:
                ledger.write_item(item)

            finished = []
            acquisitions = []
            for item, (_locator, target, removal_source, expected_digest) in zip(
                ingestion_items,
                staged,
                strict=True,
            ):
                result_item, acquisition = _process_item(
                    self.store,
                    ledger,
                    item,
                    lambda selected=target: selected,
                    max_file_bytes=max_file_bytes,
                    retry_extraction=False,
                )
                moved = False
                if acquisition is not None and result_item.status == "completed":
                    if not self._verified_original_exists(expected_digest, target):
                        raise RuntimeError(
                            "committed Original failed exact-byte verification"
                        )
                    if move_after_commit:
                        moved = self._remove_if_unchanged(
                            removal_source,
                            expected_digest,
                        )
                        if moved:
                            self._remove_empty_parents(removal_source, source_root)
                        else:
                            self.operations.append(
                                operation.id,
                                "inbox.source_not_moved",
                                (
                                    "The submitted source changed after staging and "
                                    "was not removed."
                                ),
                                level="warning",
                                details={"locator": item.locator},
                            )
                    acquisitions.append(acquisition)
                finished.append(result_item)
                submission_items.append(
                    {
                        "locator": item.locator,
                        "status": result_item.status,
                        "error_code": result_item.error_code,
                        "error": result_item.error,
                        "sha256": expected_digest,
                        "acquisition_id": result_item.acquisition_id,
                        "moved_source": moved,
                    }
                )
                self.operations.append(
                    operation.id,
                    (
                        "inbox.item_completed"
                        if result_item.status == "completed"
                        else "inbox.item_failed"
                    ),
                    f"{item.locator} finished as {result_item.status}.",
                    level=(
                        "info" if result_item.status == "completed" else "warning"
                    ),
                    details={
                        "locator": item.locator,
                        "outcome": result_item.outcome,
                        "acquisition_id": result_item.acquisition_id,
                    },
                )

            closed_run = _close_run(ledger, run, finished)
            indexed = rebuild_search_index(
                self.store,
                recover_missing_derived=False,
            )
            completed_count = sum(
                item["status"] == "completed" for item in submission_items
            )
            failed_count = len(submission_items) - completed_count
            if failed_count and completed_count:
                status = "completed_with_errors"
            elif failed_count:
                status = "failed"
            else:
                status = "completed"
            submission = InboxSubmission(
                schema_version=INBOX_SCHEMA_VERSION,
                id=submission_id,
                operation_id=operation.id,
                ingestion_run_id=closed_run.id,
                source_id=source_id,
                status=status,
                mode="move_after_commit" if move_after_commit else "copy",
                input_name=source.name,
                created_at=operation.started_at,
                completed_at=utc_now(),
                total_items=len(submission_items),
                completed_items=completed_count,
                failed_items=failed_count,
                items=tuple(
                    sorted(submission_items, key=lambda item: item["locator"])
                ),
            )
            self._write_submission(submission)
            self.operations.close(
                operation.id,
                status=status,
                summary=(
                    f"Captured {completed_count} of {len(submission_items)} "
                    f"supported items; {indexed} documents are searchable."
                ),
                metrics={
                    "items_total": len(submission_items),
                    "items_completed": completed_count,
                    "items_failed": failed_count,
                    "documents_indexed": indexed,
                    "sources_removed": sum(
                        bool(item["moved_source"]) for item in submission_items
                    ),
                },
            )
            return {
                "submission": submission.as_dict(),
                "run": asdict(closed_run),
                "items": [asdict(item) for item in finished],
                "acquisitions": [asdict(item) for item in acquisitions],
            }
        except Exception as exc:
            current = self.operations.get_record(operation.id)
            if current is not None and current.status == "running":
                self.operations.append(
                    operation.id,
                    "inbox.submission_failed",
                    "Inbox submission failed before completion.",
                    level="error",
                    details={"error_type": exc.__class__.__name__},
                )
                self.operations.close(
                    operation.id,
                    status="failed",
                    summary="Inbox submission failed.",
                    error_code="inbox_submission_failed",
                    error=exc.__class__.__name__,
                )
            raise

    def process_drop(
        self,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> dict[str, Any]:
        self.ensure()
        return self.submit(
            self.drop,
            move_after_commit=True,
            max_file_bytes=max_file_bytes,
            max_files=max_files,
        )

    def summary(self) -> dict[str, Any]:
        submissions = self.list_submissions(limit=500)
        drop_files = (
            sum(1 for path in self.drop.rglob("*") if path.is_file())
            if self.drop.exists()
            else 0
        )
        return {
            "schema_version": INBOX_SCHEMA_VERSION,
            "drop_locator": "inbox/drop",
            "drop_files": drop_files,
            "submissions": len(submissions),
            "completed": sum(
                item.get("status") == "completed" for item in submissions
            ),
            "attention": sum(
                item.get("status") in {"failed", "completed_with_errors"}
                for item in submissions
            ),
        }
