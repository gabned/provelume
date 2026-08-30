from __future__ import annotations

import json
import os
import shutil
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .index import (
    GENERATION_METADATA_TABLE,
    _connection,
    _create_search_table,
    _database_path,
    _documents_and_versions,
    _insert_document,
    _knowledge_fingerprint,
    _metadata,
    _metadata_path,
    _read_embedded_metadata,
    _read_metadata,
)
from .maintenance_model import (
    MAINTENANCE_CATALOG,
    MAINTENANCE_SCHEMA_VERSION,
    MaintenanceInsufficientSpaceError,
    MaintenanceStateError,
    MaintenanceUnavailableError,
    maintenance_action,
    plan_digest,
    reindex_mode_for_job_kind,
    reindex_run_identifier,
    validate_reindex_plan,
    validate_reindex_run,
)
from .paths import safe_instance_path
from .scheduler_model import instant_text
from .storage import InstanceStore

MINIMUM_REINDEX_TEMPORARY_BYTES = 1024 * 1024
REINDEX_RUN_LIMIT = 10_000


class MaintenanceManager:
    """Expose a closed maintenance catalogue and resumable derived FTS generations."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.state / "maintenance"
        self.runs = self.root / "reindex-runs"
        self.candidates = store.paths.indexes / "reindex-candidates"

    def catalog(self, *, policies: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        selected_policies = policies or []
        result = []
        for definition in MAINTENANCE_CATALOG:
            item = dict(definition)
            kind = item.get("scheduler_job_kind")
            item["policies"] = [
                policy
                for policy in selected_policies
                if kind is not None and policy.get("job_kind") == kind
            ]
            item["network_used"] = False
            item["canonical_mutation"] = False
            item["automatic_deletion"] = False
            result.append(item)
        return result

    def action(
        self,
        action_id: str,
        *,
        policies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        definition = maintenance_action(action_id)
        kind = definition.get("scheduler_job_kind")
        definition["policies"] = [
            policy
            for policy in policies or []
            if kind is not None and policy.get("job_kind") == kind
        ]
        definition["network_used"] = False
        definition["canonical_mutation"] = False
        definition["automatic_deletion"] = False
        return definition

    @staticmethod
    def _document_bytes(store: InstanceStore, documents: Mapping[str, str]) -> int:
        total = 0
        for version_id in documents.values():
            version = store.read_canonical("versions", version_id)
            if version is None:
                continue
            original = store.read_canonical("originals", str(version.get("original_id", "")))
            if original is not None and type(original.get("size_bytes")) is int:
                total += max(0, int(original["size_bytes"]))
        return total

    def _rows_for_documents(
        self,
        documents: Mapping[str, str],
        *,
        require_current: bool,
    ) -> list[tuple[Any, ...]]:
        by_id = {
            str(document["id"]): document
            for document in self.store.list_canonical("documents")
        }
        rows: list[tuple[Any, ...]] = []
        for document_id, version_id in sorted(documents.items()):
            document = by_id.get(document_id)
            if document is None or (
                require_current and document.get("current_version_id") != version_id
            ):
                raise MaintenanceStateError(
                    "reindex plan no longer matches canonical state"
                )
            version = self.store.read_canonical("versions", version_id)
            if version is None or version.get("document_id") != document_id:
                raise MaintenanceStateError("reindex Version is missing")
            artifact = self.store.derived_artifact_for_version(version_id)
            if artifact is None:
                continue
            rows.append(
                (
                    document_id,
                    version_id,
                    document["source_id"],
                    document["media_type"],
                    version["acquired_at"],
                    document["title"],
                    self.store.read_derived_text(artifact),
                )
            )
        return rows

    def _active_index_matches_metadata(self, metadata: Mapping[str, Any]) -> bool:
        previous = {
            str(key): str(value) for key, value in metadata["documents"].items()
        }
        if metadata.get("knowledge_fingerprint") != _knowledge_fingerprint(previous):
            return False
        try:
            expected = self._rows_for_documents(previous, require_current=False)
            connection = _connection(_database_path(self.store))
            try:
                observed = [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT document_id, version_id, source_id, media_type, acquired_at, "
                        "title, content FROM search ORDER BY document_id, version_id, rowid"
                    ).fetchall()
                ]
            finally:
                connection.close()
        except (KeyError, MaintenanceStateError, OSError, sqlite3.Error):
            return False
        return (
            observed == expected
            and len(observed) == int(metadata.get("documents_indexed", -1))
        )

    def plan_reindex(self, mode: str) -> dict[str, Any]:
        selected_mode = mode.strip().lower()
        if selected_mode not in {"full", "incremental"}:
            raise MaintenanceStateError("unsupported reindex mode")
        documents, current = _documents_and_versions(self.store)
        current = {key: current[key] for key in sorted(current)}
        current_ids = set(current)
        strategy = "full"
        baseline: dict[str, str] = {}
        selected_ids = sorted(current_ids)
        active_metadata = _read_metadata(self.store)
        if (
            selected_mode == "incremental"
            and active_metadata is not None
            and _database_path(self.store).is_file()
            and self._active_index_matches_metadata(active_metadata)
        ):
            previous = {
                str(key): str(value)
                for key, value in active_metadata["documents"].items()
            }
            strategy = "incremental"
            baseline = {key: previous[key] for key in sorted(previous)}
            selected_ids = sorted(
                document_id
                for document_id in set(previous) | current_ids
                if previous.get(document_id) != current.get(document_id)
            )
        selected_documents = {
            document_id: current[document_id]
            for document_id in selected_ids
            if document_id in current
        }
        estimated_bytes = self._document_bytes(self.store, selected_documents)
        active_bytes = 0
        if strategy == "incremental" and _database_path(self.store).is_file():
            active_bytes = _database_path(self.store).stat().st_size
        temporary_required = max(
            MINIMUM_REINDEX_TEMPORARY_BYTES,
            active_bytes + estimated_bytes * 2 + 64 * 1024,
        )
        space_path = self.store.paths.indexes
        while not space_path.exists() and space_path != self.store.paths.root:
            space_path = space_path.parent
        free_bytes = shutil.disk_usage(space_path).free
        return validate_reindex_plan({
            "requested_mode": selected_mode,
            "strategy": strategy,
            "canonical_fingerprint": self.store.knowledge_fingerprint(),
            "knowledge_fingerprint": _knowledge_fingerprint(current),
            "documents": current,
            "baseline_documents": baseline,
            "selected_document_ids": selected_ids,
            "estimated_items": len(selected_ids),
            "estimated_bytes": estimated_bytes,
            "temporary_bytes_required": temporary_required,
            "free_bytes_observed": free_bytes,
        })

    def plan_action(self, action_id: str) -> dict[str, Any]:
        definition = maintenance_action(action_id)
        if not definition["available"]:
            raise MaintenanceUnavailableError(str(definition["unavailable_reason"]))
        kind = str(definition["scheduler_job_kind"])
        if not kind.startswith("search.reindex"):
            raise MaintenanceUnavailableError("dry_run_not_supported")
        plan = self.plan_reindex(reindex_mode_for_job_kind(kind))
        return {
            "schema_version": MAINTENANCE_SCHEMA_VERSION,
            "action_id": action_id,
            "plan": plan,
            "ready": plan["free_bytes_observed"] >= plan["temporary_bytes_required"],
            "network_used": False,
            "canonical_mutation": False,
            "automatic_deletion": False,
        }

    @staticmethod
    def _run_id(job_id: str) -> str:
        if not job_id.startswith("job_") or len(job_id) != 36:
            raise MaintenanceStateError("reindex job ID is invalid")
        return f"reindex_{job_id.removeprefix('job_')}"

    def _run_path(self, run_id: str) -> Path:
        if not reindex_run_identifier(run_id):
            raise MaintenanceStateError("reindex run ID is invalid")
        return self.runs / f"{run_id}.json"

    def _read_run_path(self, path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise MaintenanceStateError("reindex run is not a regular file")
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise MaintenanceStateError("reindex run is unreadable") from exc
        record = validate_reindex_run(value)
        if path.stem != record["id"]:
            raise MaintenanceStateError("reindex filename does not match its record")
        return record

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if not reindex_run_identifier(run_id):
            return None
        path = self._run_path(run_id)
        return self._read_run_path(path) if path.exists() or path.is_symlink() else None

    def run_for_job(self, job_id: str) -> dict[str, Any] | None:
        return self.get_run(self._run_id(job_id))

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        if self.runs.is_symlink() or (
            self.runs.exists() and not self.runs.is_dir()
        ):
            raise MaintenanceStateError("reindex run directory is invalid")
        if not self.runs.exists():
            return []
        paths = sorted(self.runs.glob("reindex_*.json"))
        if len(paths) > REINDEX_RUN_LIMIT:
            raise MaintenanceStateError("reindex run history exceeds its safety limit")
        result = [self._read_run_path(path) for path in paths]
        result.sort(
            key=lambda item: (str(item["updated_at"]), str(item["id"])),
            reverse=True,
        )
        return result[: min(limit, 500)]

    def _write_run(self, record: Mapping[str, Any]) -> dict[str, Any]:
        selected = validate_reindex_run(record)
        if self.root.is_symlink() or self.runs.is_symlink():
            raise MaintenanceStateError("maintenance run directory is unsafe")
        self.runs.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir() or not self.runs.is_dir():
            raise MaintenanceStateError("maintenance run directory is invalid")
        self.store._atomic_json(self._run_path(str(selected["id"])), selected)
        return selected

    def _candidate_paths(self, record: Mapping[str, Any]) -> tuple[Path, Path]:
        if self.store.paths.indexes.is_symlink() or self.candidates.is_symlink():
            raise MaintenanceStateError("reindex candidate directory is unsafe")
        database = safe_instance_path(
            self.store.paths.root,
            str(record["candidate"]["database_ref"]),
        )
        metadata = safe_instance_path(
            self.store.paths.root,
            str(record["candidate"]["metadata_ref"]),
        )
        candidate_root = self.candidates.resolve()
        if database.parent != candidate_root or metadata.parent != candidate_root:
            raise MaintenanceStateError("reindex candidate reference was redirected")
        return database, metadata

    @staticmethod
    def _generation_id(job_id: str, revision: int, digest: str) -> str:
        import hashlib

        identity = hashlib.sha256(f"{job_id}:{revision}:{digest}".encode()).hexdigest()
        return f"generation_{identity[:32]}"

    def _new_record(
        self,
        *,
        job_id: str,
        mode: str,
        base_progress: Mapping[str, int],
        revision: int,
        created_at: str,
    ) -> dict[str, Any]:
        plan = self.plan_reindex(mode)
        if plan["free_bytes_observed"] < plan["temporary_bytes_required"]:
            raise MaintenanceInsufficientSpaceError(
                "reindex temporary-space preflight failed"
            )
        digest = plan_digest(plan)
        run_id = self._run_id(job_id)
        generation_id = self._generation_id(job_id, revision, digest)
        prefix = f"{run_id}-r{revision}-{generation_id.removeprefix('generation_')}"
        now = instant_text()
        return validate_reindex_run(
            {
                "schema_version": MAINTENANCE_SCHEMA_VERSION,
                "id": run_id,
                "job_id": job_id,
                "status": "building",
                "plan_revision": revision,
                "generation_id": generation_id,
                "plan_digest": digest,
                "plan": plan,
                "candidate": {
                    "database_ref": f"indexes/reindex-candidates/{prefix}.sqlite3",
                    "metadata_ref": f"indexes/reindex-candidates/{prefix}.json",
                },
                "cursor": 0,
                "indexed": 0,
                "skipped": 0,
                "errors": 0,
                "base_progress": dict(base_progress),
                "created_at": created_at,
                "updated_at": now,
                "completed_at": None,
                "network_used": False,
                "canonical_mutation": False,
                "automatic_deletion": False,
            }
        )

    def _create_candidate(self, record: Mapping[str, Any]) -> None:
        database, metadata = self._candidate_paths(record)
        database.parent.mkdir(parents=True, exist_ok=True)
        database.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        if record["plan"]["strategy"] == "incremental":
            source = _connection(_database_path(self.store))
            destination = _connection(database)
            try:
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
                source.close()
        else:
            connection = _connection(database)
            try:
                _create_search_table(connection)
                connection.commit()
            finally:
                connection.close()
        with database.open("r+b") as handle:
            os.fsync(handle.fileno())

    def _active_generation_matches(self, record: Mapping[str, Any]) -> bool:
        metadata = self._embedded_generation_metadata(_database_path(self.store))
        if metadata is None or not (
            metadata.get("generation_id") == record["generation_id"]
            and metadata.get("job_id") == record["job_id"]
            and metadata.get("plan_digest") == record["plan_digest"]
            and metadata.get("documents") == record["plan"]["documents"]
        ):
            return False
        try:
            matches, _count = self._database_matches(
                _database_path(self.store),
                record["plan"]["documents"],
            )
        except (MaintenanceStateError, OSError):
            return False
        return matches

    @staticmethod
    def _embedded_generation_metadata(database: Path) -> dict[str, Any] | None:
        return _read_embedded_metadata(database)

    @staticmethod
    def _embed_generation_metadata(database: Path, metadata: Mapping[str, Any]) -> None:
        payload = json.dumps(
            dict(metadata),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        connection = _connection(database)
        try:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {GENERATION_METADATA_TABLE} ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)"
            )
            connection.execute(
                f"INSERT OR REPLACE INTO {GENERATION_METADATA_TABLE}(id, payload) "
                "VALUES (1, ?)",
                (payload,),
            )
            connection.commit()
        finally:
            connection.close()
        with database.open("r+b") as handle:
            os.fsync(handle.fileno())

    def _reconcile_active_metadata(self, record: Mapping[str, Any]) -> None:
        metadata = self._embedded_generation_metadata(_database_path(self.store))
        if metadata is None or (
            metadata.get("generation_id") != record["generation_id"]
            or metadata.get("job_id") != record["job_id"]
            or metadata.get("plan_digest") != record["plan_digest"]
        ):
            raise MaintenanceStateError("active reindex generation evidence is incomplete")
        _candidate_database, candidate_metadata = self._candidate_paths(record)
        candidate_value: dict[str, Any] | None = None
        if candidate_metadata.is_file():
            try:
                with candidate_metadata.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                candidate_value = loaded if isinstance(loaded, dict) else None
            except (json.JSONDecodeError, OSError):
                candidate_value = None
        if candidate_value == metadata:
            os.replace(candidate_metadata, _metadata_path(self.store))
        else:
            self.store._atomic_json(_metadata_path(self.store), metadata)

    def _after_database_activation(self, record: Mapping[str, Any]) -> None:
        """Test seam for a process stop between database and sidecar activation."""

    def _activate_generation(
        self,
        record: Mapping[str, Any],
        database: Path,
        metadata_candidate: Path,
        metadata: Mapping[str, Any],
    ) -> None:
        self._embed_generation_metadata(database, metadata)
        os.replace(database, _database_path(self.store))
        self._after_database_activation(record)
        os.replace(metadata_candidate, _metadata_path(self.store))

    def _prefix_matches(self, record: Mapping[str, Any]) -> bool:
        database, _metadata_candidate = self._candidate_paths(record)
        if not database.is_file():
            return False
        selected = record["plan"]["selected_document_ids"][: int(record["cursor"])]
        documents = record["plan"]["documents"]
        try:
            candidate_documents = dict(record["plan"]["baseline_documents"])
            for document_id in selected:
                if document_id in documents:
                    candidate_documents[document_id] = documents[document_id]
                else:
                    candidate_documents.pop(document_id, None)
            expected_rows = self._rows_for_documents(
                candidate_documents,
                require_current=False,
            )
            connection = _connection(database)
            try:
                rows = connection.execute(
                    "SELECT document_id, version_id, source_id, media_type, acquired_at, "
                    "title, content FROM search ORDER BY document_id, version_id, rowid"
                ).fetchall()
                return [tuple(row) for row in rows] == expected_rows
            finally:
                connection.close()
        except (KeyError, MaintenanceStateError, OSError, UnicodeError, ValueError, sqlite3.Error):
            return False

    def _restart(
        self,
        record: Mapping[str, Any],
        *,
        mode: str,
        base_progress: Mapping[str, int],
    ) -> dict[str, Any]:
        old_database, old_metadata = self._candidate_paths(record)
        old_database.unlink(missing_ok=True)
        old_metadata.unlink(missing_ok=True)
        replacement = self._new_record(
            job_id=str(record["job_id"]),
            mode=mode,
            base_progress=base_progress,
            revision=int(record["plan_revision"]) + 1,
            created_at=str(record["created_at"]),
        )
        replacement = self._write_run(replacement)
        self._create_candidate(replacement)
        return replacement

    def _load_or_start(
        self,
        *,
        job_id: str,
        mode: str,
        progress: Mapping[str, int],
    ) -> dict[str, Any]:
        existing = self.run_for_job(job_id)
        if existing is None:
            record = self._new_record(
                job_id=job_id,
                mode=mode,
                base_progress=progress,
                revision=1,
                created_at=instant_text(),
            )
            record = self._write_run(record)
            self._create_candidate(record)
            return record
        if existing["plan"]["requested_mode"] != mode:
            raise MaintenanceStateError("reindex job mode changed after it was journaled")
        within_run = {
            "processed": int(existing["indexed"]),
            "skipped": int(existing["skipped"]),
            "errors": int(existing["errors"]),
        }
        rebased = {
            key: max(
                int(existing["base_progress"][key]),
                int(progress[key]) - within_run[key],
            )
            for key in existing["base_progress"]
        }
        if rebased != existing["base_progress"]:
            existing = self._write_run(
                {
                    **existing,
                    "base_progress": rebased,
                    "updated_at": instant_text(),
                }
            )
        if existing["status"] == "completed":
            return existing
        current_plan = self.plan_reindex(mode)
        if (
            current_plan["canonical_fingerprint"]
            != existing["plan"]["canonical_fingerprint"]
            or current_plan["knowledge_fingerprint"]
            != existing["plan"]["knowledge_fingerprint"]
        ):
            return self._restart(existing, mode=mode, base_progress=progress)
        if (
            current_plan["free_bytes_observed"]
            < existing["plan"]["temporary_bytes_required"]
        ):
            raise MaintenanceInsufficientSpaceError(
                "reindex temporary-space preflight failed during recovery"
            )
        if self._active_generation_matches(existing):
            self._reconcile_active_metadata(existing)
            return self._write_run(
                {
                    **existing,
                    "status": "completed",
                    "updated_at": instant_text(),
                    "completed_at": instant_text(),
                }
            )
        database, _metadata_candidate = self._candidate_paths(existing)
        if not database.is_file() or not self._prefix_matches(existing):
            return self._restart(existing, mode=mode, base_progress=progress)
        return existing

    def _expected_rows(self, documents: Mapping[str, str]) -> list[tuple[Any, ...]]:
        return self._rows_for_documents(documents, require_current=True)

    def _database_matches(
        self,
        database: Path,
        documents: Mapping[str, str],
    ) -> tuple[bool, int]:
        expected = self._expected_rows(documents)
        try:
            connection = _connection(database)
            try:
                observed = [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT document_id, version_id, source_id, media_type, acquired_at, "
                        "title, content FROM search ORDER BY document_id, version_id, rowid"
                    ).fetchall()
                ]
            finally:
                connection.close()
        except sqlite3.Error:
            return False, 0
        return observed == expected, len(expected)

    def _candidate_matches(self, record: Mapping[str, Any]) -> tuple[bool, int]:
        database, _metadata_candidate = self._candidate_paths(record)
        return self._database_matches(database, record["plan"]["documents"])

    def _after_item_checkpoint(self, record: Mapping[str, Any]) -> None:
        """Test seam for synthetic crash boundaries; production execution is a no-op."""

    def execute_reindex(
        self,
        job: Mapping[str, Any],
        *,
        checkpoint: Callable[[dict[str, int]], Mapping[str, Any]],
    ) -> dict[str, int]:
        mode = reindex_mode_for_job_kind(str(job["job_kind"]))
        canonical_before = self.store.knowledge_fingerprint()
        record = self._load_or_start(
            job_id=str(job["id"]),
            mode=mode,
            progress=job["progress"],
        )
        initial_progress = {key: int(job["progress"][key]) for key in job["progress"]}
        if record["status"] != "completed":
            database, metadata_candidate = self._candidate_paths(record)
            documents = record["plan"]["documents"]
            selected = record["plan"]["selected_document_ids"]
            by_id = {
                str(document["id"]): document
                for document in _documents_and_versions(self.store)[0]
            }
            connection = _connection(database)
            try:
                for offset in range(int(record["cursor"]), len(selected)):
                    document_id = str(selected[offset])
                    connection.execute(
                        "DELETE FROM search WHERE document_id = ?",
                        (document_id,),
                    )
                    indexed = False
                    expected_version = documents.get(document_id)
                    document = by_id.get(document_id)
                    if expected_version is not None:
                        if (
                            document is None
                            or str(document.get("current_version_id")) != expected_version
                        ):
                            raise MaintenanceStateError(
                                "reindex plan changed while its generation was building"
                            )
                        indexed = _insert_document(
                            connection,
                            self.store,
                            document,
                            recover_missing_derived=True,
                        )
                    connection.commit()
                    with database.open("r+b") as handle:
                        os.fsync(handle.fileno())
                    next_indexed = int(record["indexed"]) + int(indexed)
                    next_skipped = int(record["skipped"]) + int(not indexed)
                    absolute_progress = {
                        "processed": int(record["base_progress"]["processed"])
                        + next_indexed,
                        "skipped": int(record["base_progress"]["skipped"])
                        + next_skipped,
                        "errors": int(record["base_progress"]["errors"]),
                    }
                    checkpoint(absolute_progress)
                    record = self._write_run(
                        {
                            **record,
                            "cursor": offset + 1,
                            "indexed": next_indexed,
                            "skipped": next_skipped,
                            "updated_at": instant_text(),
                        }
                    )
                    self._after_item_checkpoint(record)
            finally:
                connection.close()
            record = self._write_run(
                {**record, "status": "validating", "updated_at": instant_text()}
            )
            matches, indexed_count = self._candidate_matches(record)
            if not matches:
                raise MaintenanceStateError("reindex candidate validation failed")
            metadata = _metadata(dict(documents), indexed_count)
            metadata.update(
                {
                    "generation_id": record["generation_id"],
                    "job_id": record["job_id"],
                    "build_mode": record["plan"]["requested_mode"],
                    "build_strategy": record["plan"]["strategy"],
                    "plan_digest": record["plan_digest"],
                }
            )
            self.store._atomic_json(metadata_candidate, metadata)
            record = self._write_run(
                {**record, "status": "activating", "updated_at": instant_text()}
            )
            self._activate_generation(
                record,
                database,
                metadata_candidate,
                metadata,
            )
            if not self._active_generation_matches(record):
                raise MaintenanceStateError("activated reindex generation failed validation")
            self._reconcile_active_metadata(record)
            record = self._write_run(
                {
                    **record,
                    "status": "completed",
                    "updated_at": instant_text(),
                    "completed_at": instant_text(),
                }
            )
        if self.store.knowledge_fingerprint() != canonical_before:
            raise MaintenanceStateError("reindex changed canonical knowledge")
        final_progress = {
            "processed": int(record["base_progress"]["processed"])
            + int(record["indexed"]),
            "skipped": int(record["base_progress"]["skipped"])
            + int(record["skipped"]),
            "errors": int(record["base_progress"]["errors"]) + int(record["errors"]),
        }
        return {
            key: max(0, final_progress[key] - initial_progress[key])
            for key in final_progress
        }


def maintenance_state_findings(store: InstanceStore) -> list[dict[str, str]]:
    manager = MaintenanceManager(store)
    if not manager.root.exists() and not manager.root.is_symlink():
        return []
    findings: list[dict[str, str]] = []
    allowed = {manager.runs.name}
    if manager.root.is_symlink() or not manager.root.is_dir():
        return [
            {
                "code": "maintenance_directory_invalid",
                "message": "maintenance state root is invalid",
                "path": "state/maintenance",
            }
        ]
    for child in sorted(manager.root.iterdir()):
        if child.name not in allowed:
            findings.append(
                {
                    "code": "maintenance_record_invalid",
                    "message": "maintenance state contains an unsupported entry",
                    "path": child.relative_to(store.paths.root).as_posix(),
                }
            )
    if manager.runs.exists() or manager.runs.is_symlink():
        if manager.runs.is_symlink() or not manager.runs.is_dir():
            findings.append(
                {
                    "code": "maintenance_directory_invalid",
                    "message": "maintenance reindex run directory is invalid",
                    "path": "state/maintenance/reindex-runs",
                }
            )
        else:
            for path in sorted(manager.runs.iterdir()):
                relative = path.relative_to(store.paths.root).as_posix()
                if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                    findings.append(
                        {
                            "code": "maintenance_record_invalid",
                            "message": "maintenance reindex run is not a regular JSON file",
                            "path": relative,
                        }
                    )
                    continue
                try:
                    manager._read_run_path(path)
                except MaintenanceStateError:
                    findings.append(
                        {
                            "code": "maintenance_record_invalid",
                            "message": "maintenance reindex run is invalid",
                            "path": relative,
                        }
                    )
    return findings


__all__ = ["MaintenanceManager", "maintenance_state_findings"]
