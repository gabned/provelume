from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections.abc import Mapping
from pathlib import Path, PurePath
from typing import Any

from .resource_statistics_model import (
    MAX_RESOURCE_FILES,
    MAX_RESOURCE_SNAPSHOTS,
    RESOURCE_CATEGORIES,
    RESOURCE_STATISTICS_SCHEMA_VERSION,
    THRESHOLD_CODES,
    ResourceStatisticsChangedError,
    ResourceStatisticsIOError,
    ResourceStatisticsLimitError,
    ResourceStatisticsStateError,
    default_threshold_settings,
    empty_category_totals,
    normalise_threshold_limits,
    resource_snapshot_identifier,
    validate_resource_snapshot,
    validate_threshold_settings,
)
from .scheduler_model import SchedulerError, instant_text, utc_instant
from .storage import InstanceStore


class ResourceStatisticsManager:
    """Observe local Instance storage without reading content or enforcing policy."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.state / "resource-statistics"
        self.settings_path = self.root / "thresholds.json"
        self.snapshots = self.root / "snapshots"

    @staticmethod
    def _link_like(path: Path) -> bool:
        return path.is_symlink() or path.is_junction()

    def _check_state_parents(self) -> None:
        state = self.store.paths.state
        if self._link_like(state) or (state.exists() and not state.is_dir()):
            raise ResourceStatisticsStateError(
                "resource statistics state parent is unsafe"
            )
        if self._link_like(self.root) or (
            self.root.exists() and not self.root.is_dir()
        ):
            raise ResourceStatisticsStateError(
                "resource statistics state directory is unsafe"
            )

    def _instance_id(self) -> str:
        value = self.store.read_config().get("instance", {}).get("id")
        if not isinstance(value, str):
            raise ResourceStatisticsStateError(
                "resource statistics Instance identity is unavailable"
            )
        return value

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise ResourceStatisticsStateError(
                "resource statistics state is not a regular file"
            )
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResourceStatisticsStateError(
                "resource statistics state is unreadable"
            ) from exc
        if not isinstance(value, dict):
            raise ResourceStatisticsStateError(
                "resource statistics state must be an object"
            )
        return value

    def _ensure_root(self, *, snapshots: bool = False) -> None:
        self._check_state_parents()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir() or self._link_like(self.root):
            raise ResourceStatisticsStateError(
                "resource statistics state directory is invalid"
            )
        if snapshots:
            if self._link_like(self.snapshots) or (
                self.snapshots.exists() and not self.snapshots.is_dir()
            ):
                raise ResourceStatisticsStateError(
                    "resource snapshot directory is unsafe"
                )
            self.snapshots.mkdir(parents=True, exist_ok=True)
            if not self.snapshots.is_dir() or self._link_like(self.snapshots):
                raise ResourceStatisticsStateError(
                    "resource snapshot directory is invalid"
                )

    def threshold_settings(self) -> dict[str, Any]:
        instance_id = self._instance_id()
        self._check_state_parents()
        if not self.settings_path.exists() and not self._link_like(self.settings_path):
            return default_threshold_settings(instance_id)
        settings = validate_threshold_settings(self._read_json(self.settings_path))
        if settings["instance_id"] != instance_id:
            raise ResourceStatisticsStateError(
                "resource threshold settings belong to another Instance"
            )
        return settings

    def configure_thresholds(
        self,
        limits: Mapping[str, Any],
        *,
        now: Any = None,
    ) -> dict[str, Any]:
        selected_limits = normalise_threshold_limits(limits)
        current = self.threshold_settings()
        if current["limits"] == selected_limits and int(current["revision"]) > 0:
            return current
        settings = validate_threshold_settings(
            {
                "schema_version": RESOURCE_STATISTICS_SCHEMA_VERSION,
                "instance_id": self._instance_id(),
                "revision": int(current["revision"]) + 1,
                "updated_at": instant_text(now),
                "limits": selected_limits,
            }
        )
        self._ensure_root()
        if self._link_like(self.settings_path):
            raise ResourceStatisticsStateError(
                "resource threshold settings path is unsafe"
            )
        self.store._atomic_json(self.settings_path, settings)
        return settings

    @staticmethod
    def _category(relative: PurePath) -> str:
        parts = relative.parts
        if len(parts) == 1 and parts[0] in {
            "provelume.yml",
            "instance-manifest.json",
        }:
            return "configuration"
        if not parts:
            return "other"
        if parts[0] == "originals":
            return "canonical_originals"
        if parts[0] == "knowledge":
            return "canonical_records"
        if parts[0] in {"indexes", "library"} or parts[:2] == (
            "state",
            "derived",
        ):
            return "derived_assets"
        if parts[0] == "state":
            return "operational_state"
        if parts[0] == "inbox":
            return "managed_inbox"
        return "other"

    @staticmethod
    def _metadata_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            int(value.st_mode),
            int(value.st_size),
            int(value.st_mtime_ns),
            int(value.st_ctime_ns),
            int(value.st_dev),
            int(value.st_ino),
        )

    @staticmethod
    def _member_digest(rows: list[tuple[str, str]]) -> str:
        digest = hashlib.sha256()
        for name, kind in rows:
            encoded = os.fsencode(name)
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            digest.update(b"\0" + kind.encode("ascii") + b"\n")
        return digest.hexdigest()

    def _directory_member_digest(self, directory: Path, instance_root: Path) -> str:
        try:
            if self._link_like(directory) or directory.resolve(strict=True) != directory:
                raise ResourceStatisticsChangedError(
                    "Instance directory changed during resource observation"
                )
            if not directory.is_relative_to(instance_root):
                raise ResourceStatisticsStateError(
                    "resource observation escaped the Instance root"
                )
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
            rows: list[tuple[str, str]] = []
            for entry in entries:
                selected = Path(entry.path)
                if entry.is_symlink() or selected.is_junction():
                    continue
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(metadata.st_mode):
                    rows.append((entry.name, "directory"))
                elif stat.S_ISREG(metadata.st_mode):
                    rows.append((entry.name, "file"))
            return self._member_digest(rows)
        except FileNotFoundError as exc:
            raise ResourceStatisticsChangedError(
                "Instance files changed during resource observation"
            ) from exc
        except PermissionError as exc:
            raise ResourceStatisticsIOError(
                "Instance files are unreadable for resource observation"
            ) from exc
        except ResourceStatisticsStateError:
            raise
        except OSError as exc:
            raise ResourceStatisticsIOError(
                "Instance files could not be observed"
            ) from exc

    def _after_scan_walk(self) -> None:
        """Test seam before the stability barrier rechecks every observed entry."""

    def _scan(
        self,
        *,
        job_id: str | None = None,
    ) -> tuple[dict[str, dict[str, int]], int, int]:
        instance_root = self.store.paths.root
        try:
            resolved_root = instance_root.resolve(strict=True)
        except OSError as exc:
            raise ResourceStatisticsIOError(
                "Instance root is unavailable for resource observation"
            ) from exc
        categories = empty_category_totals()
        file_count = 0
        byte_count = 0
        pending = [instance_root]
        directory_members: dict[Path, str] = {}
        file_metadata: list[
            tuple[Path, tuple[int, int, int, int, int, int], bool]
        ] = []
        volatile_job = (
            self.store.paths.state / "scheduler" / "jobs" / f"{job_id}.json"
            if job_id is not None
            else None
        )
        while pending:
            directory = pending.pop()
            try:
                if self._link_like(directory) or directory.resolve(strict=True) != directory:
                    raise ResourceStatisticsChangedError(
                        "Instance directory changed during resource observation"
                    )
                if not directory.is_relative_to(resolved_root):
                    raise ResourceStatisticsStateError(
                        "resource observation escaped the Instance root"
                    )
                with os.scandir(directory) as iterator:
                    entries = sorted(iterator, key=lambda item: item.name)
            except FileNotFoundError as exc:
                raise ResourceStatisticsChangedError(
                    "Instance files changed during resource observation"
                ) from exc
            except PermissionError as exc:
                raise ResourceStatisticsIOError(
                    "Instance files are unreadable for resource observation"
                ) from exc
            except ResourceStatisticsStateError:
                raise
            except OSError as exc:
                raise ResourceStatisticsIOError(
                    "Instance files could not be observed"
                ) from exc
            member_rows: list[tuple[str, str]] = []
            for entry in entries:
                try:
                    selected = Path(entry.path)
                    if entry.is_symlink() or selected.is_junction():
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                except FileNotFoundError as exc:
                    raise ResourceStatisticsChangedError(
                        "Instance files changed during resource observation"
                    ) from exc
                except PermissionError as exc:
                    raise ResourceStatisticsIOError(
                        "Instance files are unreadable for resource observation"
                    ) from exc
                except OSError as exc:
                    raise ResourceStatisticsIOError(
                        "Instance files could not be observed"
                    ) from exc
                if stat.S_ISDIR(metadata.st_mode):
                    member_rows.append((entry.name, "directory"))
                    pending.append(selected)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    continue
                member_rows.append((entry.name, "file"))
                file_count += 1
                if file_count > MAX_RESOURCE_FILES:
                    raise ResourceStatisticsLimitError(
                        "Instance file count exceeds the resource observation bound"
                    )
                size = int(metadata.st_size)
                byte_count += size
                if byte_count > 2**63 - 1:
                    raise ResourceStatisticsLimitError(
                        "Instance byte count exceeds the resource observation bound"
                    )
                relative = selected.relative_to(instance_root)
                category = self._category(relative)
                categories[category]["file_count"] += 1
                categories[category]["byte_count"] += size
                file_metadata.append(
                    (
                        selected,
                        self._metadata_identity(metadata),
                        selected == volatile_job,
                    )
                )
            directory_members[directory] = self._member_digest(member_rows)

        self._after_scan_walk()
        for directory, expected in directory_members.items():
            if self._directory_member_digest(directory, resolved_root) != expected:
                raise ResourceStatisticsChangedError(
                    "Instance directory membership changed during resource observation"
                )
        for path, expected, heartbeat_volatile in file_metadata:
            try:
                if self._link_like(path):
                    raise ResourceStatisticsChangedError(
                        "Instance file changed during resource observation"
                    )
                observed = path.stat(follow_symlinks=False)
            except FileNotFoundError as exc:
                raise ResourceStatisticsChangedError(
                    "Instance files changed during resource observation"
                ) from exc
            except PermissionError as exc:
                raise ResourceStatisticsIOError(
                    "Instance files are unreadable for resource observation"
                ) from exc
            except ResourceStatisticsStateError:
                raise
            except OSError as exc:
                raise ResourceStatisticsIOError(
                    "Instance files could not be observed"
                ) from exc
            identity = self._metadata_identity(observed)
            stable_total_fields = identity[:2] == expected[:2]
            if not stat.S_ISREG(observed.st_mode) or not stable_total_fields:
                raise ResourceStatisticsChangedError(
                    "Instance file metadata changed during resource observation"
                )
            if not heartbeat_volatile and identity != expected:
                raise ResourceStatisticsChangedError(
                    "Instance file metadata changed during resource observation"
                )
        return categories, file_count, byte_count

    def _capacity(self) -> dict[str, int]:
        try:
            usage = shutil.disk_usage(self.store.paths.root)
        except OSError as exc:
            raise ResourceStatisticsIOError(
                "Instance capacity could not be observed"
            ) from exc
        values = {
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
        }
        if any(value < 0 or value > 2**63 - 1 for value in values.values()):
            raise ResourceStatisticsLimitError(
                "Instance capacity exceeds the supported observation bound"
            )
        reserved = values["total_bytes"] - values["used_bytes"] - values["free_bytes"]
        if reserved < 0:
            raise ResourceStatisticsStateError(
                "Instance capacity totals are inconsistent"
            )
        values["reserved_bytes"] = reserved
        return values

    @staticmethod
    def _evaluate(
        *,
        byte_count: int,
        free_bytes: int,
        settings: Mapping[str, Any],
    ) -> dict[str, Any]:
        limits = normalise_threshold_limits(settings["limits"])
        codes: list[str] = []
        free_critical = limits["minimum_free_bytes_critical"]
        free_warning = limits["minimum_free_bytes_warning"]
        if free_critical is not None and free_bytes <= free_critical:
            codes.append("minimum_free_bytes_critical")
        elif free_warning is not None and free_bytes <= free_warning:
            codes.append("minimum_free_bytes_warning")
        bytes_critical = limits["maximum_instance_bytes_critical"]
        bytes_warning = limits["maximum_instance_bytes_warning"]
        if bytes_critical is not None and byte_count >= bytes_critical:
            codes.append("maximum_instance_bytes_critical")
        elif bytes_warning is not None and byte_count >= bytes_warning:
            codes.append("maximum_instance_bytes_warning")
        codes = [code for code in THRESHOLD_CODES if code in set(codes)]
        state = (
            "critical"
            if any(code.endswith("_critical") for code in codes)
            else "warning"
            if codes
            else "ok"
        )
        return {
            "settings_revision": int(settings["revision"]),
            "limits": limits,
            "state": state,
            "codes": codes,
        }

    def _snapshot_path(self, snapshot_id: str) -> Path:
        if not resource_snapshot_identifier(snapshot_id):
            raise ResourceStatisticsStateError("resource snapshot ID is invalid")
        return self.snapshots / f"{snapshot_id}.json"

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        if not resource_snapshot_identifier(snapshot_id):
            return None
        self._check_state_parents()
        if self._link_like(self.snapshots) or (
            self.snapshots.exists() and not self.snapshots.is_dir()
        ):
            raise ResourceStatisticsStateError(
                "resource snapshot directory is unsafe"
            )
        path = self._snapshot_path(snapshot_id)
        if not path.exists() and not self._link_like(path):
            return None
        snapshot = validate_resource_snapshot(self._read_json(path))
        if path.stem != snapshot["id"]:
            raise ResourceStatisticsStateError(
                "resource snapshot filename does not match its record"
            )
        if snapshot["instance_id"] != self._instance_id():
            raise ResourceStatisticsStateError(
                "resource snapshot belongs to another Instance"
            )
        expected = self._evaluate(
            byte_count=int(snapshot["byte_count"]),
            free_bytes=int(snapshot["capacity"]["free_bytes"]),
            settings={
                "revision": snapshot["thresholds"]["settings_revision"],
                "limits": snapshot["thresholds"]["limits"],
            },
        )
        if snapshot["thresholds"] != expected:
            raise ResourceStatisticsStateError(
                "resource snapshot threshold evaluation is inconsistent"
            )
        return snapshot

    @staticmethod
    def _delta(
        current: Mapping[str, Any],
        previous: Mapping[str, Any],
    ) -> dict[str, Any]:
        elapsed = (
            utc_instant(str(current["observed_at"]))
            - utc_instant(str(previous["observed_at"]))
        ).total_seconds()
        return {
            "elapsed_seconds": max(0, int(elapsed)),
            "clock_reversed": elapsed < 0,
            "file_count": int(current["file_count"]) - int(previous["file_count"]),
            "byte_count": int(current["byte_count"]) - int(previous["byte_count"]),
            "free_bytes": int(current["capacity"]["free_bytes"])
            - int(previous["capacity"]["free_bytes"]),
            "categories": {
                category: {
                    "file_count": int(current["categories"][category]["file_count"])
                    - int(previous["categories"][category]["file_count"]),
                    "byte_count": int(current["categories"][category]["byte_count"])
                    - int(previous["categories"][category]["byte_count"]),
                }
                for category in RESOURCE_CATEGORIES
            },
        }

    def _all_snapshots(self) -> list[dict[str, Any]]:
        self._check_state_parents()
        if not self.snapshots.exists() and not self._link_like(self.snapshots):
            return []
        if self._link_like(self.snapshots) or not self.snapshots.is_dir():
            raise ResourceStatisticsStateError("resource snapshot directory is invalid")
        paths = sorted(self.snapshots.iterdir())
        if len(paths) > MAX_RESOURCE_SNAPSHOTS:
            raise ResourceStatisticsStateError(
                "resource snapshot history exceeds its safety bound"
            )
        snapshots: list[dict[str, Any]] = []
        for path in paths:
            if path.suffix != ".json":
                raise ResourceStatisticsStateError(
                    "resource snapshot history contains an unsupported entry"
                )
            snapshot = self.get_snapshot(path.stem)
            if snapshot is None:
                raise ResourceStatisticsStateError("resource snapshot disappeared")
            snapshots.append(snapshot)
        snapshots.sort(key=lambda item: int(item["sequence"]))
        seen_ids: set[str] = set()
        previous: dict[str, Any] | None = None
        for index, snapshot in enumerate(snapshots, start=1):
            snapshot_id = str(snapshot["id"])
            if snapshot_id in seen_ids or int(snapshot["sequence"]) != index:
                raise ResourceStatisticsStateError(
                    "resource snapshot sequence is not unique and contiguous"
                )
            seen_ids.add(snapshot_id)
            if previous is None:
                if snapshot["previous_snapshot_id"] is not None or snapshot["delta"] is not None:
                    raise ResourceStatisticsStateError(
                        "first resource snapshot has unexpected trend evidence"
                    )
            elif (
                snapshot["previous_snapshot_id"] != previous["id"]
                or snapshot["delta"] != self._delta(snapshot, previous)
            ):
                raise ResourceStatisticsStateError(
                    "resource snapshot trend chain is inconsistent"
                )
            previous = snapshot
        return snapshots

    def list_snapshots(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        return list(reversed(self._all_snapshots()))[: min(limit, 500)]

    def latest_snapshot(self) -> dict[str, Any] | None:
        snapshots = self._all_snapshots()
        return snapshots[-1] if snapshots else None

    @staticmethod
    def _job_observed_at(job: Mapping[str, Any]) -> str:
        attempts = job.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ResourceStatisticsStateError(
                "resource snapshot job has no execution attempt"
            )
        attempt = attempts[-1]
        if not isinstance(attempt, Mapping):
            raise ResourceStatisticsStateError(
                "resource snapshot job attempt is invalid"
            )
        try:
            return instant_text(attempt.get("started_at"))
        except SchedulerError as exc:
            raise ResourceStatisticsStateError(
                "resource snapshot job time is invalid"
            ) from exc

    def _write_snapshot(self, value: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = validate_resource_snapshot(value)
        self._ensure_root(snapshots=True)
        path = self._snapshot_path(str(snapshot["id"]))
        if path.exists() or self._link_like(path):
            existing = self.get_snapshot(str(snapshot["id"]))
            if existing != snapshot:
                raise ResourceStatisticsStateError(
                    "resource snapshot job already has different evidence"
                )
            return snapshot
        self.store._atomic_json(path, snapshot)
        return snapshot

    def _after_snapshot_write(self, snapshot: Mapping[str, Any]) -> None:
        """Test seam after the immutable sample and before the scheduler receipt."""

    def capture(self, job: Mapping[str, Any]) -> dict[str, Any]:
        instance_id = self._instance_id()
        if (
            job.get("job_kind") != "maintenance.resource_snapshot"
            or job.get("scope") != {"kind": "instance", "id": instance_id}
        ):
            raise ResourceStatisticsStateError(
                "scheduler job is not an Instance resource snapshot"
            )
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id.startswith("job_"):
            raise ResourceStatisticsStateError("resource snapshot job ID is invalid")
        snapshot_id = f"resource_{job_id.removeprefix('job_')}"
        existing = self.get_snapshot(snapshot_id)
        if existing is not None:
            if existing["job_id"] != job_id or existing["instance_id"] != instance_id:
                raise ResourceStatisticsStateError(
                    "resource snapshot replay binding is invalid"
                )
            return existing
        history = self._all_snapshots()
        if len(history) >= MAX_RESOURCE_SNAPSHOTS:
            raise ResourceStatisticsLimitError(
                "resource snapshot history reached its explicit safety bound"
            )
        categories, file_count, byte_count = self._scan(job_id=job_id)
        capacity = self._capacity()
        settings = self.threshold_settings()
        previous = history[-1] if history else None
        snapshot: dict[str, Any] = {
            "schema_version": RESOURCE_STATISTICS_SCHEMA_VERSION,
            "id": snapshot_id,
            "instance_id": instance_id,
            "job_id": job_id,
            "sequence": len(history) + 1,
            "observed_at": self._job_observed_at(job),
            "previous_snapshot_id": previous["id"] if previous is not None else None,
            "file_count": file_count,
            "byte_count": byte_count,
            "categories": categories,
            "capacity": capacity,
            "thresholds": self._evaluate(
                byte_count=byte_count,
                free_bytes=capacity["free_bytes"],
                settings=settings,
            ),
            "delta": None,
            "network_used": False,
            "canonical_mutation": False,
            "automatic_deletion": False,
        }
        if previous is not None:
            snapshot["delta"] = self._delta(snapshot, previous)
        written = self._write_snapshot(snapshot)
        self._after_snapshot_write(written)
        return written

    def status(self, *, history_limit: int = 30) -> dict[str, Any]:
        snapshots = self._all_snapshots()
        history = list(reversed(snapshots))[: min(max(history_limit, 0), 500)]
        return {
            "schema_version": RESOURCE_STATISTICS_SCHEMA_VERSION,
            "settings": self.threshold_settings(),
            "latest": snapshots[-1] if snapshots else None,
            "history": history,
            "snapshot_count": len(snapshots),
            "network_used": False,
            "canonical_mutation": False,
            "automatic_deletion": False,
        }


def resource_statistics_state_findings(store: InstanceStore) -> list[dict[str, str]]:
    """Validate durable resource observations without scanning Instance file content."""

    manager = ResourceStatisticsManager(store)
    if manager._link_like(store.paths.state) or (
        store.paths.state.exists() and not store.paths.state.is_dir()
    ):
        return [
            {
                "code": "resource_statistics_directory_invalid",
                "message": "Resource statistics state parent is invalid",
                "path": "state",
            }
        ]
    if not manager.root.exists() and not manager._link_like(manager.root):
        return []
    if manager._link_like(manager.root) or not manager.root.is_dir():
        return [
            {
                "code": "resource_statistics_directory_invalid",
                "message": "Resource statistics state root is invalid",
                "path": "state/resource-statistics",
            }
        ]
    findings: list[dict[str, str]] = []
    allowed = {manager.settings_path.name, manager.snapshots.name}
    for child in sorted(manager.root.iterdir()):
        if child.name not in allowed:
            findings.append(
                {
                    "code": "resource_statistics_record_invalid",
                    "message": "Resource statistics state contains an unsupported entry",
                    "path": child.relative_to(store.paths.root).as_posix(),
                }
            )
    try:
        settings = manager.threshold_settings()
    except ResourceStatisticsStateError as exc:
        settings = default_threshold_settings(manager._instance_id())
        findings.append(
            {
                "code": "resource_statistics_record_invalid",
                "message": str(exc),
                "path": "state/resource-statistics/thresholds.json",
            }
        )
    try:
        snapshots = manager._all_snapshots()
    except ResourceStatisticsStateError as exc:
        snapshots = []
        findings.append(
            {
                "code": "resource_statistics_record_invalid",
                "message": str(exc),
                "path": "state/resource-statistics/snapshots",
            }
        )
    from .scheduler import SchedulerStore

    scheduler = SchedulerStore(store)
    instance_id = manager._instance_id()
    for snapshot in snapshots:
        try:
            job = scheduler.get_job(str(snapshot["job_id"]))
        except (SchedulerError, OSError, UnicodeError, json.JSONDecodeError):
            job = None
        attempt_times = (
            {
                str(attempt["started_at"])
                for attempt in job["attempts"]
            }
            if job is not None
            else set()
        )
        binding_invalid = (
            job is None
            or job["job_kind"] != "maintenance.resource_snapshot"
            or job["scope"] != {"kind": "instance", "id": instance_id}
            or snapshot["observed_at"] not in attempt_times
            or int(snapshot["thresholds"]["settings_revision"])
            > int(settings["revision"])
        )
        if job is not None and job["status"] == "succeeded":
            binding_invalid = binding_invalid or (
                int(job["progress"]["processed"]) != int(snapshot["file_count"])
            )
        if job is not None and job["receipt_ref"] is not None:
            try:
                receipt = scheduler.get_receipt(Path(str(job["receipt_ref"])).stem)
            except (SchedulerError, OSError, UnicodeError, json.JSONDecodeError):
                receipt = None
            binding_invalid = binding_invalid or receipt is None or bool(
                receipt
                and (
                    receipt["network_used"]
                    or receipt["canonical_mutation"]
                    or receipt["automatic_deletion"]
                )
            )
        if binding_invalid:
            findings.append(
                {
                    "code": "resource_statistics_binding_invalid",
                    "message": "Resource snapshot durable binding is invalid",
                    "path": (
                        "state/resource-statistics/snapshots/"
                        f"{snapshot['id']}.json"
                    ),
                }
            )
    return findings


__all__ = ["ResourceStatisticsManager", "resource_statistics_state_findings"]
