from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from .domain import Source
from .folder_source_model import (
    FOLDER_SOURCE_SCHEMA_VERSION,
    MAX_FOLDER_PATH_CHARS,
    FolderSourceError,
    FolderSourceNotFound,
    folder_config_payload,
    new_observer_record,
    normalise_folder_config,
    normalise_observer_record,
)
from .ingest import (
    IngestionLimitError,
    IngestionRetryError,
    _iter_files,
    _refresh_after_ingestion,
    _retry_ingestion_run_locked,
    _run_ingestion_filesystem_locked,
)
from .ingestion_runs import IngestionLedger
from .paths import UnsafePathError, portable_config_path
from .scheduler_model import SchedulerError, instant_text, utc_instant
from .storage import InstanceStore, utc_now


class FolderSourceManager:
    """Durable, privacy-minimizing observation of explicit filesystem Sources.

    Mutating callers hold the Instance lifecycle lock. Mounted network folders are
    accessed only as user-configured filesystem paths; this module never opens a
    socket, obtains credentials or removes canonical or source files.
    """

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.state / "folder-sources"
        self.observers = self.root / "observers"

    @staticmethod
    def _name(value: str) -> str:
        selected = " ".join(value.strip().split())
        if not selected or len(selected) > 120:
            raise FolderSourceError("Source name must contain 1 to 120 characters")
        if any(ord(character) < 32 for character in selected):
            raise FolderSourceError("Source name contains a control character")
        return selected

    def _selected_path(self, value: Path | str) -> Path:
        text = str(value).strip()
        if not text or len(text) > MAX_FOLDER_PATH_CHARS or "\x00" in text:
            raise FolderSourceError("folder path is empty or unsupported")
        selected = Path(text).expanduser()
        if not selected.is_absolute():
            selected = self.store.paths.root / selected
        candidate = selected.resolve()
        instance_root = self.store.paths.root.resolve()
        try:
            instance_root.relative_to(candidate)
        except ValueError:
            pass
        else:
            raise FolderSourceError("folder Source cannot contain the Instance root")
        reserved = (
            self.store.paths.originals,
            self.store.paths.knowledge,
            self.store.paths.state,
            self.store.paths.indexes,
            self.store.paths.library,
        )
        for path in reserved:
            try:
                candidate.relative_to(path.resolve())
            except ValueError:
                continue
            raise FolderSourceError("folder Source overlaps reserved Instance storage")
        return candidate

    def _configured(self, source_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        source = self.store.read_canonical("sources", source_id)
        if source is None or source.get("kind") != "filesystem":
            raise FolderSourceNotFound(f"folder Source not found: {source_id}")
        sources = self.store.read_config().get("sources")
        item = sources.get(source_id) if isinstance(sources, Mapping) else None
        if not isinstance(item, Mapping) or item.get("kind") != "filesystem":
            raise FolderSourceError("folder Source configuration is missing")
        folder = normalise_folder_config(item.get("folder"))
        if not isinstance(item.get("path"), str):
            raise FolderSourceError("folder Source path is missing")
        return source, dict(item), folder

    def is_managed(self, source_id: str) -> bool:
        try:
            self._configured(source_id)
        except FolderSourceError:
            return False
        return True

    def register(
        self,
        path: Path | str,
        *,
        name: str,
        source_class: str = "local",
        lifecycle_state: str = "enabled",
        quiescence_seconds: int = 5,
        stable_observations: int = 2,
        max_file_bytes: int = 25 * 1024 * 1024,
        max_files: int = 1000,
    ) -> dict[str, Any]:
        selected_name = self._name(name)
        selected_path = self._selected_path(path)
        folder = folder_config_payload(
            source_class=source_class,
            lifecycle_state=lifecycle_state,
            quiescence_seconds=quiescence_seconds,
            stable_observations=stable_observations,
            max_file_bytes=max_file_bytes,
            max_files=max_files,
        )
        if source_class == "local" and not selected_path.exists():
            raise FolderSourceError("local folder Source must exist when registered")
        if selected_path.exists() and not (selected_path.is_file() or selected_path.is_dir()):
            raise FolderSourceError("folder Source path is not a regular file or directory")

        source_id = self.store.find_source_for_path(selected_path)
        if source_id is None:
            source_id = f"src_{uuid4().hex}"
            source = Source(
                id=source_id,
                kind="filesystem",
                name=selected_name,
                created_at=utc_now(),
            )
            self.store.write_source(source)
        else:
            existing = self.store.read_canonical("sources", source_id)
            if existing is None or existing.get("kind") != "filesystem":
                raise FolderSourceError("configured path belongs to an incompatible Source")
            current_sources = self.store.read_config().get("sources") or {}
            current = (
                current_sources.get(source_id) if isinstance(current_sources, Mapping) else None
            )
            if isinstance(current, Mapping) and current.get("folder") is not None:
                current_folder = normalise_folder_config(current["folder"])
                if (
                    str(existing.get("name")) != selected_name
                    or {**current_folder, "policy_id": None} != folder
                ):
                    raise FolderSourceError(
                        "folder Source already exists; update its state or scheduler "
                        "policy explicitly"
                    )
                return self.local_view(source_id)
            if str(existing.get("name")) != selected_name:
                self.store.write_source(
                    Source(
                        id=source_id,
                        kind="filesystem",
                        name=selected_name,
                        created_at=str(existing["created_at"]),
                    )
                )

        config = self.store.read_config()
        sources = config.setdefault("sources", {})
        if not isinstance(sources, dict):
            raise FolderSourceError("Instance Sources configuration must be an object")
        current = sources.get(source_id)
        preserved = dict(current) if isinstance(current, Mapping) else {}
        sources[source_id] = {
            **preserved,
            "kind": "filesystem",
            "name": selected_name,
            "path": portable_config_path(self.store.paths.root, selected_path),
            "folder": folder,
        }
        self.store.write_config(config)
        self._write_observer(new_observer_record(source_id, lifecycle_state=lifecycle_state))
        return self.local_view(source_id)

    def link_policy(self, source_id: str, policy_id: str) -> dict[str, Any]:
        _source, _item, folder = self._configured(source_id)
        updated_folder = normalise_folder_config({**folder, "policy_id": policy_id})
        config = self.store.read_config()
        sources = config.get("sources")
        if not isinstance(sources, dict) or not isinstance(sources.get(source_id), dict):
            raise FolderSourceError("folder Source configuration is missing")
        sources[source_id]["folder"] = updated_folder
        self.store.write_config(config)
        return self.public_view(source_id)

    def set_state(self, source_id: str, state: str) -> dict[str, Any]:
        _source, _item, folder = self._configured(source_id)
        if folder["lifecycle_state"] == state:
            return self.public_view(source_id)
        observer = self._read_observer(
            source_id,
            lifecycle_state=str(folder["lifecycle_state"]),
        )
        updated_folder = normalise_folder_config({**folder, "lifecycle_state": state})
        config = self.store.read_config()
        sources = config.get("sources")
        if not isinstance(sources, dict) or not isinstance(sources.get(source_id), dict):
            raise FolderSourceError("folder Source configuration is missing")
        sources[source_id]["folder"] = updated_folder
        self.store.write_config(config)
        observer = {
            **observer,
            "lifecycle_state": state,
            "phase": "paused" if state == "paused" else "unobserved",
            "active_run_id": None if state == "paused" else observer["active_run_id"],
            "updated_at": instant_text(None),
        }
        self._write_observer(observer)
        return self.public_view(source_id)

    def _observer_path(self, source_id: str) -> Path:
        return self.observers / f"{source_id}.json"

    def _read_observer(self, source_id: str, *, lifecycle_state: str) -> dict[str, Any]:
        path = self._observer_path(source_id)
        if not path.exists():
            return new_observer_record(source_id, lifecycle_state=lifecycle_state)
        if path.is_symlink() or not path.is_file():
            raise FolderSourceError("folder Source observer is not a regular file")
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FolderSourceError("folder Source observer is unreadable") from exc
        selected = normalise_observer_record(value)
        if selected["lifecycle_state"] != lifecycle_state:
            raise FolderSourceError(
                "folder Source observer lifecycle does not match its configuration"
            )
        return selected

    def _write_observer(self, value: Mapping[str, Any]) -> dict[str, Any]:
        selected = normalise_observer_record(value)
        self.observers.mkdir(parents=True, exist_ok=True)
        self.store._atomic_json(self._observer_path(str(selected["source_id"])), selected)
        return selected

    def observer(self, source_id: str) -> dict[str, Any]:
        _source, _item, folder = self._configured(source_id)
        return self._read_observer(
            source_id,
            lifecycle_state=str(folder["lifecycle_state"]),
        )

    def _snapshot(self, source_id: str, *, max_files: int) -> tuple[str, int, int]:
        path = self.store.source_path(source_id)
        if path is None:
            raise FolderSourceError("folder Source path is missing")
        selected = path.expanduser().resolve(strict=True)
        files = _iter_files(selected, max_files)
        rows: list[str] = []
        total_bytes = 0
        for locator, file_path in files:
            stat = file_path.stat()
            total_bytes += stat.st_size
            rows.append(
                json.dumps(
                    [locator, stat.st_size, stat.st_mtime_ns],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        digest = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
        return digest, len(files), total_bytes

    def _failure_observation(
        self,
        observer: Mapping[str, Any],
        *,
        now_text: str,
        availability: str,
        phase: str,
        error_code: str | None,
    ) -> dict[str, Any]:
        return self._write_observer(
            {
                **observer,
                "availability": availability,
                "phase": phase,
                "last_observed_at": now_text,
                "last_missing_at": now_text
                if availability == "missing"
                else observer["last_missing_at"],
                "pending_since": None,
                "pending_fingerprint": None,
                "stable_observations": 0,
                "file_count": 0,
                "total_bytes": 0,
                "active_run_id": observer["active_run_id"],
                "last_error_code": error_code,
                "updated_at": now_text,
                "network_used": False,
            }
        )

    def observe(
        self,
        source_id: str,
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        _source, _item, folder = self._configured(source_id)
        selected_now = utc_instant(now)
        now_text = instant_text(selected_now)
        observer = self._read_observer(
            source_id,
            lifecycle_state=str(folder["lifecycle_state"]),
        )
        if folder["lifecycle_state"] == "paused":
            return self._write_observer(
                {
                    **observer,
                    "lifecycle_state": "paused",
                    "phase": "paused",
                    "last_observed_at": now_text,
                    "active_run_id": None,
                    "last_error_code": None,
                    "updated_at": now_text,
                    "network_used": False,
                }
            )
        observer = {**observer, "lifecycle_state": "enabled"}
        try:
            fingerprint, file_count, total_bytes = self._snapshot(
                source_id,
                max_files=int(folder["max_files"]),
            )
        except FileNotFoundError:
            return self._failure_observation(
                observer,
                now_text=now_text,
                availability="missing",
                phase="missing",
                error_code=None,
            )
        except PermissionError:
            return self._failure_observation(
                observer,
                now_text=now_text,
                availability="attention",
                phase="attention",
                error_code="input_unreadable",
            )
        except IngestionLimitError:
            return self._failure_observation(
                observer,
                now_text=now_text,
                availability="attention",
                phase="attention",
                error_code="ingestion_limit",
            )
        except UnsafePathError:
            return self._failure_observation(
                observer,
                now_text=now_text,
                availability="attention",
                phase="attention",
                error_code="unsafe_path",
            )
        except OSError:
            return self._failure_observation(
                observer,
                now_text=now_text,
                availability="attention",
                phase="attention",
                error_code="input_io_error",
            )

        clock_reversed = False
        if observer["last_observed_at"] is not None:
            clock_reversed = selected_now < utc_instant(observer["last_observed_at"])
        changed = observer["pending_fingerprint"] != fingerprint
        if changed or clock_reversed:
            stable = 1
            pending_since = now_text
        else:
            stable = min(2**31 - 1, int(observer["stable_observations"]) + 1)
            pending_since = observer["pending_since"] or now_text
        elapsed = max(0.0, (selected_now - utc_instant(pending_since)).total_seconds())
        ready = stable >= int(folder["stable_observations"]) and elapsed >= int(
            folder["quiescence_seconds"]
        )
        phase = "quiescing"
        if ready:
            phase = "current" if observer["ingested_fingerprint"] == fingerprint else "ready"
        return self._write_observer(
            {
                **observer,
                "availability": "available",
                "phase": phase,
                "last_observed_at": now_text,
                "last_available_at": now_text,
                "pending_since": pending_since,
                "pending_fingerprint": fingerprint,
                "change_sequence": int(observer["change_sequence"]) + (1 if changed else 0),
                "stable_observations": stable,
                "file_count": file_count,
                "total_bytes": total_bytes,
                "clock_change_count": int(observer["clock_change_count"])
                + (1 if clock_reversed else 0),
                "active_run_id": (
                    None
                    if changed and observer["last_attempted_fingerprint"] != fingerprint
                    else observer["active_run_id"]
                ),
                "last_error_code": None,
                "updated_at": now_text,
                "network_used": folder["source_class"] == "network",
            }
        )

    @staticmethod
    def _run_id(source_id: str, sequence: int, fingerprint: str) -> str:
        value = f"provelume:folder-refresh:{source_id}:{sequence}:{fingerprint}"
        return f"run_{uuid5(NAMESPACE_URL, value).hex}"

    def refresh(
        self,
        source_id: str,
        *,
        scheduler_job_id: str | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        _source, _item, folder = self._configured(source_id)
        observed = self.observe(source_id, now=now)
        network_used = folder["source_class"] == "network"
        if observed["phase"] in {"paused", "missing", "quiescing", "current"}:
            replayed = (
                observed["phase"] == "current"
                and scheduler_job_id is not None
                and observed["last_scheduler_job_id"] == scheduler_job_id
                and observed["last_ingestion_run_id"] is not None
            )
            processed = 0
            canonical_mutation = False
            if replayed:
                detail = IngestionLedger(self.store).run_detail(
                    str(observed["last_ingestion_run_id"])
                )
                if detail is not None:
                    processed = int(detail["run"].get("completed_items", 0))
                    canonical_mutation = any(
                        isinstance(item.get("acquisition_id"), str) for item in detail["items"]
                    )
            return {
                "status": "replayed" if replayed else "skipped",
                "reason": "committed_replay" if replayed else observed["phase"],
                "observer": observed,
                "run": None,
                "progress": {
                    "processed": processed,
                    "skipped": 0 if replayed else 1,
                    "errors": 0,
                },
                "network_used": network_used,
                "canonical_mutation": canonical_mutation,
                "automatic_deletion": False,
            }
        if observed["phase"] != "ready" or observed["pending_fingerprint"] is None:
            return {
                "status": "failed",
                "reason": observed["last_error_code"] or "configuration_invalid",
                "observer": observed,
                "run": None,
                "progress": {"processed": 0, "skipped": 0, "errors": 1},
                "network_used": network_used,
                "canonical_mutation": False,
                "automatic_deletion": False,
            }
        target_fingerprint = str(
            observed["last_attempted_fingerprint"]
            if observed["active_run_id"] is not None
            and observed["last_attempted_fingerprint"] is not None
            else observed["pending_fingerprint"]
        )
        ledger = IngestionLedger(self.store)
        base_run_id = self._run_id(
            source_id,
            int(observed["change_sequence"]),
            target_fingerprint,
        )
        run_id = observed["active_run_id"]
        reserved_run_id: str | None = None
        prior_failure: dict[str, Any] | None = None
        retry_of_run_id: str | None = None
        if run_id is not None:
            active = ledger.get_run(str(run_id))
            if active is None:
                reserved_run_id = str(run_id)
                run_id = None
            elif active.get("status") in {
                "failed",
                "completed_with_errors",
            }:
                prior_failure = active
                run_id = None
            elif active is not None and isinstance(active.get("retry_of_run_id"), str):
                retry_of_run_id = str(active["retry_of_run_id"])
        if run_id is None and prior_failure is None:
            prior_id = observed["last_ingestion_run_id"]
            prior = ledger.get_run(str(prior_id)) if isinstance(prior_id, str) else None
            if (
                prior is not None
                and prior.get("status") in {"failed", "completed_with_errors"}
                and observed["last_attempted_fingerprint"] == target_fingerprint
            ):
                prior_failure = prior
        if run_id is None and prior_failure is None:
            base = ledger.get_run(base_run_id)
            if (
                base is not None
                and base.get("status") in {"failed", "completed_with_errors"}
                and observed["last_attempted_fingerprint"] == target_fingerprint
            ):
                prior_failure = base
        if run_id is None and prior_failure is not None:
            if reserved_run_id is not None:
                run_id = reserved_run_id
            else:
                seed = scheduler_job_id or uuid4().hex
                value = f"provelume:folder-refresh-retry:{prior_failure['id']}:{seed}"
                run_id = f"run_{uuid5(NAMESPACE_URL, value).hex}"
            if any(
                item.get("status") != "completed"
                for item in ledger.items_for_run(str(prior_failure["id"]))
            ):
                retry_of_run_id = str(prior_failure["id"])
        if run_id is None:
            run_id = base_run_id
        self._write_observer(
            {
                **observed,
                "phase": "refreshing",
                "active_run_id": run_id,
                "last_attempted_fingerprint": target_fingerprint,
                "last_scheduler_job_id": scheduler_job_id,
                "updated_at": instant_text(now),
                "network_used": network_used,
            }
        )
        path = self.store.source_path(source_id)
        if path is None:
            raise FolderSourceError("folder Source path is missing")
        try:
            if retry_of_run_id is not None:
                result = _retry_ingestion_run_locked(
                    self.store,
                    retry_of_run_id,
                    retry_run_id=str(run_id),
                    deterministic_acquisitions=True,
                )
            else:
                result = _run_ingestion_filesystem_locked(
                    self.store,
                    path,
                    max_file_bytes=int(folder["max_file_bytes"]),
                    max_files=int(folder["max_files"]),
                    run_id=str(run_id),
                )
        except IngestionRetryError as exc:
            raise FolderSourceError("durable folder Source retry is inconsistent") from exc
        _refresh_after_ingestion(self.store, result)
        post = self.observe(source_id, now=now)
        successful = result.run.status == "completed"
        unchanged_snapshot = post["pending_fingerprint"] == target_fingerprint
        if (
            not successful
            and post["phase"] == "missing"
            and result.run.item_count == 0
            and result.run.error_code == "input_missing"
        ):
            post = self._write_observer(
                {
                    **post,
                    "active_run_id": None,
                    "last_ingestion_run_id": result.run.id,
                    "last_scheduler_job_id": scheduler_job_id,
                    "last_error_code": None,
                    "updated_at": instant_text(now),
                    "network_used": network_used,
                }
            )
            return {
                "status": "skipped",
                "reason": "missing",
                "observer": post,
                "run": result.as_dict(),
                "progress": {"processed": 0, "skipped": 1, "errors": 0},
                "network_used": network_used,
                "canonical_mutation": False,
                "automatic_deletion": False,
            }
        if successful and unchanged_snapshot:
            post = self._write_observer(
                {
                    **post,
                    "phase": "current",
                    "ingested_fingerprint": target_fingerprint,
                    "active_run_id": None,
                    "last_ingestion_run_id": result.run.id,
                    "last_scheduler_job_id": scheduler_job_id,
                    "last_error_code": None,
                    "updated_at": instant_text(now),
                    "network_used": network_used,
                }
            )
        elif successful:
            post = self._write_observer(
                {
                    **post,
                    "phase": "quiescing",
                    "active_run_id": None,
                    "last_ingestion_run_id": result.run.id,
                    "last_scheduler_job_id": scheduler_job_id,
                    "last_error_code": "source_changed_during_refresh",
                    "updated_at": instant_text(now),
                    "network_used": network_used,
                }
            )
        else:
            post = self._write_observer(
                {
                    **post,
                    "availability": "attention",
                    "phase": "attention",
                    "active_run_id": None,
                    "last_ingestion_run_id": result.run.id,
                    "last_scheduler_job_id": scheduler_job_id,
                    "last_error_code": "ingestion_failed",
                    "updated_at": instant_text(now),
                    "network_used": network_used,
                }
            )
        failure_codes = {
            str(code)
            for code in [result.run.error_code, *(item.error_code for item in result.items)]
            if code is not None
        }
        transient_codes = {"input_io_error", "input_missing", "input_unreadable"}
        failure_reason = (
            "input_unreadable"
            if failure_codes
            and failure_codes <= transient_codes
            and "input_unreadable" in failure_codes
            else "input_io_error"
            if failure_codes and failure_codes <= transient_codes
            else "ingestion_failed"
        )
        return {
            "status": "refreshed" if successful else "failed",
            "reason": None if successful else failure_reason,
            "observer": post,
            "run": result.as_dict(),
            "progress": {
                "processed": int(result.run.completed_items),
                "skipped": 0,
                "errors": int(result.run.failed_items) + (0 if successful else 1),
            },
            "network_used": network_used,
            "canonical_mutation": bool(result.acquisitions),
            "automatic_deletion": False,
        }

    def public_view(self, source_id: str) -> dict[str, Any]:
        source, _item, folder = self._configured(source_id)
        observer = self._read_observer(
            source_id,
            lifecycle_state=str(folder["lifecycle_state"]),
        )
        return {
            "schema_version": FOLDER_SOURCE_SCHEMA_VERSION,
            "id": source_id,
            "name": source["name"],
            "kind": "filesystem",
            "managed_folder": True,
            "source_class": folder["source_class"],
            "lifecycle_state": folder["lifecycle_state"],
            "quiescence_seconds": folder["quiescence_seconds"],
            "stable_observations_required": folder["stable_observations"],
            "max_file_bytes": folder["max_file_bytes"],
            "max_files": folder["max_files"],
            "policy_id": folder["policy_id"],
            "observer": observer,
            "network_access": "mounted_filesystem"
            if folder["source_class"] == "network"
            else "none",
            "automatic_deletion": False,
        }

    def local_view(self, source_id: str) -> dict[str, Any]:
        result = self.public_view(source_id)
        path = self.store.source_path(source_id)
        return {**result, "path": str(path) if path is not None else None}

    def list_public(self) -> list[dict[str, Any]]:
        result = []
        for source in self.store.list_canonical("sources"):
            source_id = str(source.get("id", ""))
            if self.is_managed(source_id):
                result.append(self.public_view(source_id))
        return sorted(result, key=lambda item: (str(item["name"]).casefold(), item["id"]))


def folder_source_state_findings(store: InstanceStore) -> list[dict[str, str]]:
    """Validate managed Source config and durable observers without touching mounts."""

    manager = FolderSourceManager(store)
    from .scheduler import SchedulerStore

    scheduler = SchedulerStore(store)
    findings: list[dict[str, str]] = []
    sources = store.read_config().get("sources")
    if isinstance(sources, Mapping):
        for source_id, item in sources.items():
            if not isinstance(item, Mapping) or item.get("folder") is None:
                continue
            path = f"provelume.yml#sources.{source_id}.folder"
            try:
                _source, _item, folder = manager._configured(str(source_id))
                if not manager._observer_path(str(source_id)).is_file():
                    raise FolderSourceError("folder Source observer is missing")
                policy_id = folder["policy_id"]
                policy = (
                    scheduler.get_policy(str(policy_id))
                    if isinstance(policy_id, str)
                    else None
                )
                if policy is None:
                    raise FolderSourceError("folder Source scheduler policy is missing")
                if (
                    policy["job_kind"] != "source.refresh"
                    or policy["scope"]
                    != {"kind": "source", "id": str(source_id)}
                    or policy["state"] != folder["lifecycle_state"]
                ):
                    raise FolderSourceError(
                        "folder Source scheduler policy binding is inconsistent"
                    )
            except (FolderSourceError, SchedulerError) as exc:
                findings.append(
                    {"code": "folder_source_config_invalid", "message": str(exc), "path": path}
                )
    try:
        policies = scheduler.list_policies()
    except SchedulerError:
        policies = []
    managed_scope_counts: dict[str, int] = {}
    for policy in policies:
        if policy["job_kind"] == "source.refresh":
            selected_id = str(policy["scope"]["id"])
            managed_scope_counts[selected_id] = managed_scope_counts.get(selected_id, 0) + 1
    for source_id, count in managed_scope_counts.items():
        if manager.is_managed(source_id) and count > 1:
            findings.append(
                {
                    "code": "folder_source_policy_duplicate",
                    "message": "managed folder Source has more than one refresh policy",
                    "path": f"provelume.yml#sources.{source_id}.folder",
                }
            )
    if not manager.root.exists():
        return findings
    if manager.root.is_symlink() or not manager.root.is_dir():
        findings.append(
            {
                "code": "folder_source_state_invalid",
                "message": "folder Source state root is not a regular directory",
                "path": "state/folder-sources",
            }
        )
        return findings
    if not manager.observers.exists():
        return findings
    if manager.observers.is_symlink() or not manager.observers.is_dir():
        findings.append(
            {
                "code": "folder_source_state_invalid",
                "message": "folder Source observer root is not a regular directory",
                "path": "state/folder-sources/observers",
            }
        )
        return findings
    for path in sorted(manager.observers.glob("*.json")):
        relative = path.relative_to(store.paths.root).as_posix()
        try:
            if path.is_symlink() or not path.is_file():
                raise FolderSourceError("observer is not a regular file")
            with path.open("r", encoding="utf-8") as handle:
                record = normalise_observer_record(json.load(handle))
            if path.stem != record["source_id"]:
                raise FolderSourceError("observer filename does not match its Source ID")
            _source, _item, folder = manager._configured(str(record["source_id"]))
            if record["lifecycle_state"] != folder["lifecycle_state"]:
                raise FolderSourceError(
                    "folder Source observer lifecycle does not match its configuration"
                )
        except (FolderSourceError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(
                {"code": "folder_source_state_invalid", "message": str(exc), "path": relative}
            )
    return findings


__all__ = ["FolderSourceManager", "folder_source_state_findings"]
