from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .folder_source_model import FolderSourceError
from .folder_sources import FolderSourceManager
from .ingest import IngestionLimitError, _iter_files
from .paths import UnsafePathError, normalise_locator
from .scheduler_model import SchedulerError, instant_text
from .source_reconciliation_model import (
    MAX_RECONCILIATION_FILES,
    MAX_RECONCILIATION_PLAN_ITEMS,
    SOURCE_RECONCILIATION_SCHEMA_VERSION,
    SourceReconciliationAuthorizationError,
    SourceReconciliationIOError,
    SourceReconciliationLimitError,
    SourceReconciliationStateError,
    SourceReconciliationSupersededError,
    empty_reconciliation_counts,
    hash_payload,
    reconciliation_run_identifier,
    validate_reconciliation_plan,
    validate_reconciliation_run,
    validate_source_cursor,
)
from .storage import InstanceStore

SOURCE_RECONCILIATION_RUN_LIMIT = 10_000
SOURCE_RECONCILIATION_CURSOR_LIMIT = 10_000
_READ_CHUNK_BYTES = 1024 * 1024


class SourceReconciliationManager:
    """Durable, content-free reconciliation for one explicit managed Source.

    Reconciliation reads a user-configured filesystem Source and canonical evidence,
    but it never ingests, repairs, deletes or writes canonical records. Persisted item
    identities are Source-bound hashes; absolute and relative locators remain in memory.
    """

    def __init__(self, store: InstanceStore):
        self.store = store
        self.folder_sources = FolderSourceManager(store)
        self.root = store.paths.state / "source-reconciliation"
        self.cursors = self.root / "cursors"
        self.runs = self.root / "runs"

    @staticmethod
    def _source_identifier(source_id: Any) -> str:
        if (
            not isinstance(source_id, str)
            or len(source_id) != 36
            or not source_id.startswith("src_")
        ):
            raise SourceReconciliationStateError("Source reconciliation Source ID is invalid")
        try:
            int(source_id[4:], 16)
        except ValueError as exc:
            raise SourceReconciliationStateError(
                "Source reconciliation Source ID is invalid"
            ) from exc
        return source_id

    def _configuration(self, source_id: str) -> tuple[dict[str, Any], str, bool]:
        selected_id = self._source_identifier(source_id)
        try:
            _source, item, folder = self.folder_sources._configured(selected_id)
        except FolderSourceError as exc:
            raise SourceReconciliationStateError(
                "Source reconciliation requires a managed filesystem Source"
            ) from exc
        path = self.store.source_path(selected_id)
        if path is None:
            raise SourceReconciliationStateError(
                "Source reconciliation Source path is missing"
            )
        configuration_fingerprint = hash_payload(
            {
                "source_id": selected_id,
                "path": str(path.expanduser().absolute()),
                "source_class": folder["source_class"],
                "lifecycle_state": folder["lifecycle_state"],
                "max_file_bytes": folder["max_file_bytes"],
                "max_files": folder["max_files"],
                "kind": item["kind"],
            }
        )
        return folder, configuration_fingerprint, folder["source_class"] == "network"

    @staticmethod
    def _locator_identity(source_id: str, locator: str) -> str:
        return hashlib.sha256(f"{source_id}\0{locator}".encode()).hexdigest()

    def _canonical_rows(
        self,
        source_id: str,
    ) -> tuple[list[dict[str, Any]], str]:
        acquisitions = self.store.list_canonical("acquisitions")
        acquisition_evidence = {
            (
                acquisition["source_id"],
                acquisition["document_id"],
                acquisition["version_id"],
                acquisition["locator"],
                acquisition["content_hash"],
            )
            for acquisition in acquisitions
            if all(
                isinstance(acquisition.get(field), str)
                for field in (
                    "source_id",
                    "document_id",
                    "version_id",
                    "locator",
                    "content_hash",
                )
            )
        }
        rows: list[dict[str, Any]] = []
        locators: set[str] = set()
        for document in self.store.list_canonical("documents"):
            if document.get("source_id") != source_id:
                continue
            document_id = document.get("id")
            version_id = document.get("current_version_id")
            locator = document.get("locator")
            try:
                normalised_locator = (
                    normalise_locator(locator) if isinstance(locator, str) else None
                )
            except UnsafePathError as exc:
                raise SourceReconciliationStateError(
                    "Source reconciliation canonical Document locator is unsafe"
                ) from exc
            if (
                not isinstance(document_id, str)
                or not isinstance(version_id, str)
                or not isinstance(locator, str)
                or normalised_locator != locator
                or locator in locators
            ):
                raise SourceReconciliationStateError(
                    "Source reconciliation canonical Document evidence is invalid"
                )
            version = self.store.read_canonical("versions", version_id)
            if version is None or version.get("document_id") != document_id:
                raise SourceReconciliationStateError(
                    "Source reconciliation current Version evidence is missing"
                )
            content_hash = version.get("content_hash")
            size_bytes = version.get("size_bytes")
            original_id = version.get("original_id")
            original = (
                self.store.read_canonical("originals", original_id)
                if isinstance(original_id, str)
                else None
            )
            if (
                not isinstance(content_hash, str)
                or len(content_hash) != 64
                or type(size_bytes) is not int
                or size_bytes < 0
                or original is None
                or original.get("sha256") != content_hash
                or original.get("size_bytes") != size_bytes
            ):
                raise SourceReconciliationStateError(
                    "Source reconciliation Original evidence is invalid"
                )
            try:
                int(content_hash, 16)
            except ValueError as exc:
                raise SourceReconciliationStateError(
                    "Source reconciliation content digest is invalid"
                ) from exc
            if (
                source_id,
                document_id,
                version_id,
                locator,
                content_hash,
            ) not in acquisition_evidence:
                raise SourceReconciliationStateError(
                    "Source reconciliation Acquisition evidence is incomplete"
                )
            locators.add(locator)
            rows.append(
                {
                    "document_id": document_id,
                    "version_id": version_id,
                    "original_id": original_id,
                    "locator": locator,
                    "identity": self._locator_identity(source_id, locator),
                    "content_hash": content_hash,
                    "size_bytes": size_bytes,
                }
            )
            if len(rows) > MAX_RECONCILIATION_PLAN_ITEMS:
                raise SourceReconciliationLimitError(
                    "Source reconciliation canonical evidence exceeds its safety bound"
                )
        rows.sort(key=lambda item: (str(item["identity"]), str(item["document_id"])))
        fingerprint = hash_payload(
            [
                {
                    "document_id": row["document_id"],
                    "version_id": row["version_id"],
                    "original_id": row["original_id"],
                    "identity": row["identity"],
                    "content_hash": row["content_hash"],
                    "size_bytes": row["size_bytes"],
                }
                for row in rows
            ]
        )
        return rows, fingerprint

    def _scan_rows(
        self,
        source_id: str,
        *,
        max_files: int,
        max_file_bytes: int,
    ) -> list[dict[str, Any]]:
        path = self.store.source_path(source_id)
        if path is None:
            raise SourceReconciliationStateError(
                "Source reconciliation Source path is missing"
            )
        files = _iter_files(path, min(max_files, MAX_RECONCILIATION_FILES))
        rows: list[dict[str, Any]] = []
        total_bytes = 0
        for locator, selected_path in files:
            try:
                before = selected_path.stat()
                if before.st_size > max_file_bytes:
                    raise IngestionLimitError(
                        "Source reconciliation file exceeds its configured byte limit"
                    )
                digest = hashlib.sha256()
                with selected_path.open("rb") as handle:
                    while chunk := handle.read(_READ_CHUNK_BYTES):
                        digest.update(chunk)
                after = selected_path.stat()
            except FileNotFoundError as exc:
                if not path.exists():
                    raise
                raise SourceReconciliationSupersededError(
                    "Source item disappeared while reconciliation evidence was read"
                ) from exc
            if (
                before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
            ):
                raise SourceReconciliationSupersededError(
                    "Source changed while reconciliation evidence was read"
                )
            total_bytes += int(after.st_size)
            if total_bytes > 2**63 - 1:
                raise SourceReconciliationLimitError(
                    "Source reconciliation byte estimate exceeds its safety bound"
                )
            rows.append(
                {
                    "locator": locator,
                    "identity": self._locator_identity(source_id, locator),
                    "content_hash": digest.hexdigest(),
                    "size_bytes": int(after.st_size),
                }
            )
        rows.sort(key=lambda item: str(item["identity"]))
        identities = [str(item["identity"]) for item in rows]
        if len(identities) != len(set(identities)):
            raise SourceReconciliationStateError(
                "Source reconciliation observed duplicate locator identities"
            )
        return rows

    @staticmethod
    def _special_plan(
        *,
        source_id: str,
        configuration_fingerprint: str,
        canonical_fingerprint: str,
        snapshot_state: str,
        lifecycle_state: str,
        lifecycle_code: str,
    ) -> dict[str, Any]:
        return validate_reconciliation_plan(
            {
                "schema_version": SOURCE_RECONCILIATION_SCHEMA_VERSION,
                "source_id": source_id,
                "configuration_fingerprint": configuration_fingerprint,
                "canonical_fingerprint": canonical_fingerprint,
                "snapshot_fingerprint": hash_payload(
                    {
                        "source_id": source_id,
                        "configuration_fingerprint": configuration_fingerprint,
                        "canonical_fingerprint": canonical_fingerprint,
                        "snapshot_state": snapshot_state,
                    }
                ),
                "snapshot_state": snapshot_state,
                "items": [],
                "estimated_items": 0,
                "estimated_bytes": 0,
                "lifecycle_state": lifecycle_state,
                "lifecycle_code": lifecycle_code,
                "resync_required": lifecycle_code not in {"current", "source_paused"},
            }
        )

    def build_plan(self, source_id: str) -> tuple[dict[str, Any], bool]:
        selected_id = self._source_identifier(source_id)
        folder, configuration_fingerprint, network_used = self._configuration(selected_id)
        canonical_rows, canonical_fingerprint = self._canonical_rows(selected_id)
        if folder["lifecycle_state"] == "paused":
            return (
                self._special_plan(
                    source_id=selected_id,
                    configuration_fingerprint=configuration_fingerprint,
                    canonical_fingerprint=canonical_fingerprint,
                    snapshot_state="paused",
                    lifecycle_state="paused",
                    lifecycle_code="source_paused",
                ),
                network_used,
            )
        try:
            observed = self._scan_rows(
                selected_id,
                max_files=int(folder["max_files"]),
                max_file_bytes=int(folder["max_file_bytes"]),
            )
        except FileNotFoundError:
            source_path = self.store.source_path(selected_id)
            if source_path is not None and source_path.exists():
                return (
                    self._special_plan(
                        source_id=selected_id,
                        configuration_fingerprint=configuration_fingerprint,
                        canonical_fingerprint=canonical_fingerprint,
                        snapshot_state="superseded",
                        lifecycle_state="superseded",
                        lifecycle_code="source_changed",
                    ),
                    network_used,
                )
            return (
                self._special_plan(
                    source_id=selected_id,
                    configuration_fingerprint=configuration_fingerprint,
                    canonical_fingerprint=canonical_fingerprint,
                    snapshot_state="missing",
                    lifecycle_state="missing",
                    lifecycle_code="source_missing",
                ),
                network_used,
            )
        except PermissionError:
            return (
                self._special_plan(
                    source_id=selected_id,
                    configuration_fingerprint=configuration_fingerprint,
                    canonical_fingerprint=canonical_fingerprint,
                    snapshot_state="error",
                    lifecycle_state="reauthorization_required",
                    lifecycle_code="authorization_required",
                ),
                network_used,
            )
        except (IngestionLimitError, SourceReconciliationLimitError):
            return (
                self._special_plan(
                    source_id=selected_id,
                    configuration_fingerprint=configuration_fingerprint,
                    canonical_fingerprint=canonical_fingerprint,
                    snapshot_state="error",
                    lifecycle_state="error",
                    lifecycle_code="source_limit",
                ),
                network_used,
            )
        except UnsafePathError:
            return (
                self._special_plan(
                    source_id=selected_id,
                    configuration_fingerprint=configuration_fingerprint,
                    canonical_fingerprint=canonical_fingerprint,
                    snapshot_state="error",
                    lifecycle_state="error",
                    lifecycle_code="source_unsafe",
                ),
                network_used,
            )
        except SourceReconciliationSupersededError:
            return (
                self._special_plan(
                    source_id=selected_id,
                    configuration_fingerprint=configuration_fingerprint,
                    canonical_fingerprint=canonical_fingerprint,
                    snapshot_state="superseded",
                    lifecycle_state="superseded",
                    lifecycle_code="source_changed",
                ),
                network_used,
            )
        except OSError:
            return (
                self._special_plan(
                    source_id=selected_id,
                    configuration_fingerprint=configuration_fingerprint,
                    canonical_fingerprint=canonical_fingerprint,
                    snapshot_state="error",
                    lifecycle_state="error",
                    lifecycle_code="source_io",
                ),
                network_used,
            )

        canonical_by_locator = {str(row["locator"]): row for row in canonical_rows}
        observed_locators = {str(row["locator"]) for row in observed}
        unmatched_locators = set(canonical_by_locator) - observed_locators
        by_digest: dict[str, list[str]] = {}
        for row in canonical_rows:
            by_digest.setdefault(str(row["content_hash"]), []).append(str(row["locator"]))
        for locators in by_digest.values():
            locators.sort(key=lambda locator: self._locator_identity(selected_id, locator))

        items: list[dict[str, Any]] = []
        for row in observed:
            locator = str(row["locator"])
            content_hash = str(row["content_hash"])
            existing = canonical_by_locator.get(locator)
            if existing is not None:
                classification = (
                    "current"
                    if existing["content_hash"] == content_hash
                    else "changed"
                )
            else:
                rename_from = next(
                    (
                        candidate
                        for candidate in by_digest.get(content_hash, [])
                        if candidate in unmatched_locators
                    ),
                    None,
                )
                if rename_from is None:
                    classification = "untracked"
                else:
                    classification = "renamed"
                    unmatched_locators.remove(rename_from)
            items.append(
                {
                    "identity": row["identity"],
                    "content_hash": content_hash,
                    "size_bytes": row["size_bytes"],
                    "classification": classification,
                }
            )
        for locator in unmatched_locators:
            row = canonical_by_locator[locator]
            items.append(
                {
                    "identity": row["identity"],
                    "content_hash": row["content_hash"],
                    "size_bytes": row["size_bytes"],
                    "classification": "missing",
                }
            )
        items.sort(key=lambda item: str(item["identity"]))
        identities = [str(item["identity"]) for item in items]
        if len(identities) != len(set(identities)):
            raise SourceReconciliationStateError(
                "Source reconciliation plan contains duplicate identities"
            )
        snapshot_fingerprint = hash_payload(
            [
                {
                    "identity": row["identity"],
                    "content_hash": row["content_hash"],
                    "size_bytes": row["size_bytes"],
                }
                for row in observed
            ]
        )
        resync_required = any(item["classification"] != "current" for item in items)
        return (
            validate_reconciliation_plan(
                {
                    "schema_version": SOURCE_RECONCILIATION_SCHEMA_VERSION,
                    "source_id": selected_id,
                    "configuration_fingerprint": configuration_fingerprint,
                    "canonical_fingerprint": canonical_fingerprint,
                    "snapshot_fingerprint": snapshot_fingerprint,
                    "snapshot_state": "available",
                    "items": items,
                    "estimated_items": len(items),
                    "estimated_bytes": sum(int(row["size_bytes"]) for row in observed),
                    "lifecycle_state": "active",
                    "lifecycle_code": "resync_required" if resync_required else "current",
                    "resync_required": resync_required,
                }
            ),
            network_used,
        )

    def _cursor_path(self, source_id: str) -> Path:
        return self.cursors / f"{self._source_identifier(source_id)}.json"

    def _run_id(self, job_id: str) -> str:
        if not isinstance(job_id, str) or len(job_id) != 36 or not job_id.startswith("job_"):
            raise SourceReconciliationStateError("Source reconciliation job ID is invalid")
        try:
            int(job_id[4:], 16)
        except ValueError as exc:
            raise SourceReconciliationStateError(
                "Source reconciliation job ID is invalid"
            ) from exc
        return f"reconcile_{job_id.removeprefix('job_')}"

    def _run_path(self, run_id: str) -> Path:
        if not reconciliation_run_identifier(run_id):
            raise SourceReconciliationStateError("Source reconciliation run ID is invalid")
        return self.runs / f"{run_id}.json"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise SourceReconciliationStateError(
                "Source reconciliation state is not a regular file"
            )
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SourceReconciliationStateError(
                "Source reconciliation state is unreadable"
            ) from exc
        if not isinstance(value, dict):
            raise SourceReconciliationStateError(
                "Source reconciliation state must be an object"
            )
        return value

    def _write_run(self, value: Mapping[str, Any]) -> dict[str, Any]:
        selected = validate_reconciliation_run(value)
        if self.root.is_symlink() or self.runs.is_symlink():
            raise SourceReconciliationStateError(
                "Source reconciliation run directory is unsafe"
            )
        self.runs.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir() or not self.runs.is_dir():
            raise SourceReconciliationStateError(
                "Source reconciliation run directory is invalid"
            )
        self.store._atomic_json(self._run_path(str(selected["id"])), selected)
        return selected

    def _write_cursor(self, value: Mapping[str, Any]) -> dict[str, Any]:
        selected = validate_source_cursor(value)
        if self.root.is_symlink() or self.cursors.is_symlink():
            raise SourceReconciliationStateError(
                "Source reconciliation cursor directory is unsafe"
            )
        self.cursors.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir() or not self.cursors.is_dir():
            raise SourceReconciliationStateError(
                "Source reconciliation cursor directory is invalid"
            )
        self.store._atomic_json(
            self._cursor_path(str(selected["source_id"])),
            selected,
        )
        return selected

    def _default_cursor(self, source_id: str) -> dict[str, Any]:
        _folder, configuration_fingerprint, network_used = self._configuration(source_id)
        return validate_source_cursor(
            {
                "schema_version": SOURCE_RECONCILIATION_SCHEMA_VERSION,
                "source_id": source_id,
                "revision": 0,
                "state": "active",
                "code": "never_reconciled",
                "configuration_fingerprint": configuration_fingerprint,
                "snapshot_fingerprint": None,
                "last_attempt_at": None,
                "last_success_at": None,
                "last_job_id": None,
                "last_run_id": None,
                "last_run_revision": None,
                "counts": empty_reconciliation_counts(),
                "resync_required": False,
                "network_used": network_used,
                "canonical_mutation": False,
                "automatic_deletion": False,
            }
        )

    def cursor(self, source_id: str) -> dict[str, Any]:
        selected_id = self._source_identifier(source_id)
        self._configuration(selected_id)
        path = self._cursor_path(selected_id)
        if not path.exists() and not path.is_symlink():
            return self._default_cursor(selected_id)
        cursor = validate_source_cursor(self._read_json(path))
        if path.stem != cursor["source_id"]:
            raise SourceReconciliationStateError(
                "Source reconciliation cursor filename does not match its Source"
            )
        return cursor

    def list_cursors(self) -> list[dict[str, Any]]:
        return [
            self.cursor(str(source["id"]))
            for source in self.folder_sources.list_public()
        ]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if not reconciliation_run_identifier(run_id):
            return None
        path = self._run_path(run_id)
        if not path.exists() and not path.is_symlink():
            return None
        run = validate_reconciliation_run(self._read_json(path))
        if path.stem != run["id"]:
            raise SourceReconciliationStateError(
                "Source reconciliation filename does not match its run"
            )
        return run

    def run_for_job(self, job_id: str) -> dict[str, Any] | None:
        return self.get_run(self._run_id(job_id))

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        if self.runs.is_symlink() or (self.runs.exists() and not self.runs.is_dir()):
            raise SourceReconciliationStateError(
                "Source reconciliation run directory is invalid"
            )
        if not self.runs.exists():
            return []
        paths = sorted(self.runs.glob("reconcile_*.json"))
        if len(paths) > SOURCE_RECONCILIATION_RUN_LIMIT:
            raise SourceReconciliationStateError(
                "Source reconciliation run history exceeds its safety limit"
            )
        result = [self.get_run(path.stem) for path in paths]
        selected = [item for item in result if item is not None]
        selected.sort(
            key=lambda item: (str(item["updated_at"]), str(item["id"])),
            reverse=True,
        )
        return selected[: min(limit, 500)]

    @staticmethod
    def _new_run(
        *,
        job_id: str,
        source_id: str,
        plan: Mapping[str, Any],
        network_used: bool,
        base_progress: Mapping[str, int],
        revision: int,
        superseded_revisions: int,
        created_at: str,
    ) -> dict[str, Any]:
        selected_plan = validate_reconciliation_plan(plan)
        return validate_reconciliation_run(
            {
                "schema_version": SOURCE_RECONCILIATION_SCHEMA_VERSION,
                "id": f"reconcile_{job_id.removeprefix('job_')}",
                "job_id": job_id,
                "source_id": source_id,
                "status": "scanning",
                "plan_revision": revision,
                "plan": selected_plan,
                "plan_digest": hash_payload(selected_plan),
                "cursor": 0,
                "counts": empty_reconciliation_counts(),
                "base_progress": dict(base_progress),
                "superseded_revisions": superseded_revisions,
                "created_at": created_at,
                "updated_at": instant_text(),
                "completed_at": None,
                "network_used": network_used,
                "canonical_mutation": False,
                "automatic_deletion": False,
            }
        )

    @staticmethod
    def _within_progress(run: Mapping[str, Any]) -> dict[str, int]:
        plan = run["plan"]
        special_skip = int(
            run["status"] == "completed"
            and plan["snapshot_state"] in {"paused", "missing"}
        )
        terminal_error = int(run["status"] in {"failed", "superseded"})
        return {
            "processed": int(run["cursor"]),
            "skipped": special_skip,
            "errors": terminal_error,
        }

    def _absolute_progress(self, run: Mapping[str, Any]) -> dict[str, int]:
        within = self._within_progress(run)
        return {
            key: int(run["base_progress"][key]) + within[key]
            for key in within
        }

    def _rebase(
        self,
        run: Mapping[str, Any],
        progress: Mapping[str, int],
    ) -> dict[str, Any]:
        within = self._within_progress(run)
        observed = {key: int(progress[key]) for key in within}
        if (
            run["status"] == "completed"
            and run["plan"]["snapshot_state"] in {"paused", "missing"}
            and observed == run["base_progress"]
        ):
            # The terminal run/lifecycle cursor may be durable just before the
            # scheduler commits the single visible skipped result. Replay returns
            # that one delta to the journal without completing the run twice.
            return dict(run)
        rebased: dict[str, int] = {}
        for key, value in within.items():
            if observed[key] < value:
                raise SourceReconciliationStateError(
                    "Scheduler progress precedes Source reconciliation evidence"
                )
            rebased[key] = observed[key] - value
        if rebased == run["base_progress"]:
            return dict(run)
        return self._write_run(
            {**run, "base_progress": rebased, "updated_at": instant_text()}
        )

    @staticmethod
    def _advanced(run: Mapping[str, Any]) -> dict[str, Any] | None:
        cursor = int(run["cursor"])
        items = run["plan"]["items"]
        if run["status"] != "scanning" or cursor >= len(items):
            return None
        counts = dict(run["counts"])
        counts[str(items[cursor]["classification"])] += 1
        return {**run, "cursor": cursor + 1, "counts": counts}

    def _recover_scanning_progress(
        self,
        run: Mapping[str, Any],
        progress: Mapping[str, int],
    ) -> dict[str, Any]:
        before = self._absolute_progress(run)
        observed = {key: int(progress[key]) for key in before}
        if observed == before:
            return dict(run)
        advanced = self._advanced(run)
        if advanced is not None and observed == self._absolute_progress(advanced):
            return self._write_run(
                {
                    **advanced,
                    "base_progress": {
                        key: observed[key] - self._within_progress(advanced)[key]
                        for key in observed
                    },
                    "updated_at": instant_text(),
                }
            )
        raise SourceReconciliationStateError(
            "Scheduler progress and Source reconciliation cursor disagree"
        )

    def _cursor_state(self, run: Mapping[str, Any]) -> tuple[str, str, bool]:
        if run["status"] == "superseded":
            return "superseded", "source_changed", True
        plan = run["plan"]
        return (
            str(plan["lifecycle_state"]),
            str(plan["lifecycle_code"]),
            bool(plan["resync_required"]),
        )

    def _ensure_terminal_cursor(self, run: Mapping[str, Any]) -> dict[str, Any]:
        if run["status"] == "scanning":
            raise SourceReconciliationStateError(
                "Scanning Source reconciliation has no terminal cursor"
            )
        current = self.cursor(str(run["source_id"]))
        state, code, resync_required = self._cursor_state(run)
        bound = (
            current["last_run_id"] == run["id"]
            and current["last_run_revision"] == run["plan_revision"]
            and current["state"] == state
            and current["code"] == code
            and current["counts"] == run["counts"]
            and current["snapshot_fingerprint"] == run["plan"]["snapshot_fingerprint"]
            and current["configuration_fingerprint"]
            == run["plan"]["configuration_fingerprint"]
            and current["resync_required"] == resync_required
            and current["network_used"] == run["network_used"]
        )
        if bound:
            return current
        now = str(run["completed_at"])
        successful = (
            run["status"] == "completed"
            and run["plan"]["snapshot_state"] == "available"
        )
        return self._write_cursor(
            {
                "schema_version": SOURCE_RECONCILIATION_SCHEMA_VERSION,
                "source_id": run["source_id"],
                "revision": int(current["revision"]) + 1,
                "state": state,
                "code": code,
                "configuration_fingerprint": run["plan"][
                    "configuration_fingerprint"
                ],
                "snapshot_fingerprint": run["plan"]["snapshot_fingerprint"],
                "last_attempt_at": now,
                "last_success_at": now if successful else current["last_success_at"],
                "last_job_id": run["job_id"],
                "last_run_id": run["id"],
                "last_run_revision": run["plan_revision"],
                "counts": run["counts"],
                "resync_required": resync_required,
                "network_used": run["network_used"],
                "canonical_mutation": False,
                "automatic_deletion": False,
            }
        )

    def _finish_run(
        self,
        run: Mapping[str, Any],
        *,
        status: str,
    ) -> dict[str, Any]:
        completed = self._write_run(
            {
                **run,
                "status": status,
                "updated_at": instant_text(),
                "completed_at": instant_text(),
            }
        )
        self._after_run_terminal(completed)
        cursor = self._ensure_terminal_cursor(completed)
        self._after_terminal_state(completed, cursor)
        return completed

    def _replacement(
        self,
        existing: Mapping[str, Any],
        *,
        plan: Mapping[str, Any],
        network_used: bool,
        progress: Mapping[str, int],
        superseded: bool,
    ) -> dict[str, Any]:
        replacement = self._new_run(
            job_id=str(existing["job_id"]),
            source_id=str(existing["source_id"]),
            plan=plan,
            network_used=network_used,
            base_progress=progress,
            revision=int(existing["plan_revision"]) + 1,
            superseded_revisions=int(existing["superseded_revisions"])
            + int(superseded),
            created_at=str(existing["created_at"]),
        )
        return self._write_run(replacement)

    def _load_or_start(self, job: Mapping[str, Any]) -> dict[str, Any]:
        job_id = str(job["id"])
        source_id = self._source_identifier(job["scope"]["id"])
        existing = self.run_for_job(job_id)
        if existing is None:
            plan, network_used = self.build_plan(source_id)
            return self._write_run(
                self._new_run(
                    job_id=job_id,
                    source_id=source_id,
                    plan=plan,
                    network_used=network_used,
                    base_progress=job["progress"],
                    revision=1,
                    superseded_revisions=0,
                    created_at=instant_text(),
                )
            )
        if existing["job_id"] != job_id or existing["source_id"] != source_id:
            raise SourceReconciliationStateError(
                "Source reconciliation run scope changed after it was journaled"
            )
        if existing["status"] == "completed":
            self._ensure_terminal_cursor(existing)
            return self._rebase(existing, job["progress"])
        if existing["status"] in {"failed", "superseded"}:
            self._ensure_terminal_cursor(existing)
            plan, network_used = self.build_plan(source_id)
            return self._replacement(
                existing,
                plan=plan,
                network_used=network_used,
                progress=job["progress"],
                superseded=existing["status"] == "superseded",
            )
        plan, network_used = self.build_plan(source_id)
        if hash_payload(plan) != existing["plan_digest"]:
            terminal = self._finish_run(existing, status="superseded")
            return self._replacement(
                terminal,
                plan=plan,
                network_used=network_used,
                progress=job["progress"],
                superseded=True,
            )
        if network_used != existing["network_used"]:
            raise SourceReconciliationStateError(
                "Source reconciliation network classification changed unexpectedly"
            )
        return self._recover_scanning_progress(existing, job["progress"])

    def _after_scheduler_checkpoint(self, run: Mapping[str, Any]) -> None:
        """Test seam between the scheduler checkpoint and Source cursor."""

    def _after_item_checkpoint(self, run: Mapping[str, Any]) -> None:
        """Test seam after both per-item cursors are durable."""

    def _after_run_terminal(self, run: Mapping[str, Any]) -> None:
        """Test seam after the terminal run write and before lifecycle cursor."""

    def _after_terminal_state(
        self,
        run: Mapping[str, Any],
        cursor: Mapping[str, Any],
    ) -> None:
        """Test seam after durable lifecycle state and before scheduler receipt."""

    def execute(
        self,
        job: Mapping[str, Any],
        *,
        checkpoint: Callable[[dict[str, int]], Mapping[str, Any]],
    ) -> dict[str, int]:
        if (
            job.get("job_kind") != "maintenance.source_reconcile"
            or job.get("scope", {}).get("kind") != "source"
        ):
            raise SourceReconciliationStateError(
                "Scheduler job is not a Source reconciliation"
            )
        initial_progress = {key: int(job["progress"][key]) for key in job["progress"]}
        run = self._load_or_start(job)
        if run["status"] == "completed":
            final = self._absolute_progress(run)
            return {key: max(0, final[key] - initial_progress[key]) for key in final}

        snapshot_state = str(run["plan"]["snapshot_state"])
        if snapshot_state in {"paused", "missing"}:
            run = self._finish_run(run, status="completed")
            final = self._absolute_progress(run)
            return {key: max(0, final[key] - initial_progress[key]) for key in final}
        if snapshot_state == "error":
            run = self._finish_run(run, status="failed")
            code = str(run["plan"]["lifecycle_code"])
            if code == "authorization_required":
                raise SourceReconciliationAuthorizationError(code)
            if code in {"source_unreadable", "source_io"}:
                raise SourceReconciliationIOError(code)
            raise SourceReconciliationLimitError(code)
        if snapshot_state == "superseded":
            self._finish_run(run, status="superseded")
            raise SourceReconciliationSupersededError("source_changed")

        for offset in range(int(run["cursor"]), len(run["plan"]["items"])):
            item = run["plan"]["items"][offset]
            counts = dict(run["counts"])
            counts[str(item["classification"])] += 1
            absolute_progress = {
                "processed": int(run["base_progress"]["processed"]) + offset + 1,
                "skipped": int(run["base_progress"]["skipped"]),
                "errors": int(run["base_progress"]["errors"]),
            }
            checkpoint(absolute_progress)
            self._after_scheduler_checkpoint(run)
            run = self._write_run(
                {
                    **run,
                    "cursor": offset + 1,
                    "counts": counts,
                    "updated_at": instant_text(),
                }
            )
            self._after_item_checkpoint(run)

        final_plan, network_used = self.build_plan(str(run["source_id"]))
        if hash_payload(final_plan) != run["plan_digest"] or network_used != run["network_used"]:
            self._finish_run(run, status="superseded")
            raise SourceReconciliationSupersededError("source_changed")
        run = self._finish_run(run, status="completed")
        final = self._absolute_progress(run)
        return {key: max(0, final[key] - initial_progress[key]) for key in final}


def source_reconciliation_state_findings(store: InstanceStore) -> list[dict[str, str]]:
    """Validate reconciliation cursors/runs without reading configured Source paths."""

    manager = SourceReconciliationManager(store)
    if not manager.root.exists() and not manager.root.is_symlink():
        return []
    findings: list[dict[str, str]] = []
    if manager.root.is_symlink() or not manager.root.is_dir():
        return [
            {
                "code": "source_reconciliation_directory_invalid",
                "message": "Source reconciliation state root is invalid",
                "path": "state/source-reconciliation",
            }
        ]
    allowed = {manager.cursors.name, manager.runs.name}
    for child in sorted(manager.root.iterdir()):
        if child.name not in allowed:
            findings.append(
                {
                    "code": "source_reconciliation_record_invalid",
                    "message": "Source reconciliation state contains an unsupported entry",
                    "path": child.relative_to(store.paths.root).as_posix(),
                }
            )
    cursors: dict[str, dict[str, Any]] = {}
    runs: dict[str, dict[str, Any]] = {}
    for label, directory, validator, limit in (
        (
            "cursor",
            manager.cursors,
            validate_source_cursor,
            SOURCE_RECONCILIATION_CURSOR_LIMIT,
        ),
        (
            "run",
            manager.runs,
            validate_reconciliation_run,
            SOURCE_RECONCILIATION_RUN_LIMIT,
        ),
    ):
        if not directory.exists() and not directory.is_symlink():
            continue
        if directory.is_symlink() or not directory.is_dir():
            findings.append(
                {
                    "code": "source_reconciliation_directory_invalid",
                    "message": f"Source reconciliation {label} directory is invalid",
                    "path": directory.relative_to(store.paths.root).as_posix(),
                }
            )
            continue
        paths = sorted(directory.iterdir())
        if len(paths) > limit:
            findings.append(
                {
                    "code": "source_reconciliation_record_invalid",
                    "message": f"Source reconciliation {label} bound was exceeded",
                    "path": directory.relative_to(store.paths.root).as_posix(),
                }
            )
            continue
        selected = cursors if label == "cursor" else runs
        for path in paths:
            relative = path.relative_to(store.paths.root).as_posix()
            try:
                if path.suffix != ".json":
                    raise SourceReconciliationStateError(
                        "Source reconciliation record is not JSON"
                    )
                record = validator(manager._read_json(path))
                expected_id = record["source_id"] if label == "cursor" else record["id"]
                if path.stem != expected_id:
                    raise SourceReconciliationStateError(
                        "Source reconciliation filename does not match its record"
                    )
                selected[str(expected_id)] = record
            except SourceReconciliationStateError as exc:
                findings.append(
                    {
                        "code": "source_reconciliation_record_invalid",
                        "message": str(exc),
                        "path": relative,
                    }
                )
    from .scheduler import SchedulerStore

    scheduler = SchedulerStore(store)
    jobs_by_run: dict[str, dict[str, Any] | None] = {}
    for run in runs.values():
        try:
            job = scheduler.get_job(str(run["job_id"]))
        except (SchedulerError, OSError, UnicodeError, json.JSONDecodeError):
            job = None
        jobs_by_run[str(run["id"])] = job
        if (
            not manager.folder_sources.is_managed(str(run["source_id"]))
            or job is None
            or job["job_kind"] != "maintenance.source_reconcile"
            or job["scope"] != {"kind": "source", "id": run["source_id"]}
        ):
            findings.append(
                {
                    "code": "source_reconciliation_binding_invalid",
                    "message": "Source reconciliation run binding is invalid",
                    "path": f"state/source-reconciliation/runs/{run['id']}.json",
                }
            )
    for cursor in cursors.values():
        run = runs.get(str(cursor["last_run_id"]))
        binding_invalid = (
            not manager.folder_sources.is_managed(str(cursor["source_id"]))
            or run is None
            or run["source_id"] != cursor["source_id"]
            or cursor["last_run_revision"] is None
            or int(cursor["last_run_revision"]) > int(run["plan_revision"])
        )
        if not binding_invalid and run is not None:
            cursor_revision = int(cursor["last_run_revision"])
            run_revision = int(run["plan_revision"])
            if cursor_revision < run_revision:
                job = jobs_by_run.get(str(run["id"]))
                binding_invalid = (
                    run["status"] != "scanning"
                    or job is None
                    or job["status"] not in {"queued", "running", "retry_wait"}
                )
            else:
                state, code, resync_required = manager._cursor_state(run)
                successful = (
                    run["status"] == "completed"
                    and run["plan"]["snapshot_state"] == "available"
                )
                binding_invalid = (
                    run["status"] == "scanning"
                    or cursor["state"] != state
                    or cursor["code"] != code
                    or cursor["configuration_fingerprint"]
                    != run["plan"]["configuration_fingerprint"]
                    or cursor["snapshot_fingerprint"]
                    != run["plan"]["snapshot_fingerprint"]
                    or cursor["last_attempt_at"] != run["completed_at"]
                    or (successful and cursor["last_success_at"] != run["completed_at"])
                    or cursor["counts"] != run["counts"]
                    or cursor["resync_required"] != resync_required
                    or cursor["network_used"] != run["network_used"]
                )
        if binding_invalid:
            findings.append(
                {
                    "code": "source_reconciliation_binding_invalid",
                    "message": "Source reconciliation cursor binding is invalid",
                    "path": (
                        "state/source-reconciliation/cursors/"
                        f"{cursor['source_id']}.json"
                    ),
                }
            )
    return findings


__all__ = [
    "SourceReconciliationManager",
    "source_reconciliation_state_findings",
]
