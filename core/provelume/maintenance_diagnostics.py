"""Reviewed content-free diagnostic snapshots; no automatic export or upload."""

from __future__ import annotations

import hashlib
import io
import os
import re
import zipfile
from pathlib import Path
from uuid import uuid4

from .maintenance_local_files import open_local_file, pinned_parent, write_local_bytes
from .maintenance_targets import (
    REF,
    SHA,
    LocalTargetRegistry,
    MaintenanceTargetError,
    canonical_bytes,
    revision,
    strict_json,
)
from .storage import InstanceStore, utc_now

CATEGORIES = ("build", "resources", "scheduler", "maintenance", "operations_summary")
MAX_PLAN_BYTES = 8 * 1024 * 1024
MAX_PLANS = 8
MAX_RECORDS = 100
PLAN_ID = re.compile(r"diagnostic_[0-9a-f]{32}\Z")
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
INSTANT = re.compile(r"[0-9T:.+Z-]{20,40}\Z")


def _number(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _states(category):
    from .maintenance_model import REINDEX_STATUSES
    from .operations import OPERATION_STATUSES
    from .scheduler_model import JOB_STATUSES

    return {
        "maintenance": set(REINDEX_STATUSES),
        "operations_summary": set(OPERATION_STATUSES),
        "scheduler": set(JOB_STATUSES),
    }[category]


def _valid_projection(category, value):
    from .resource_statistics_model import RESOURCE_CATEGORIES

    if not isinstance(value, dict):
        return False
    if value.get("coverage") == "unavailable" and set(value) == {"coverage", "reason"}:
        return value["reason"] in {"producer_absent", "producer_unreadable"}
    if category == "build":
        return (
            set(value) == {"coverage", "version", "commit"}
            and value["coverage"] == "complete"
            and (
                value["version"] is None
                or isinstance(value["version"], str)
                and re.fullmatch(r"\d+\.\d+\.\d+(?:[a-z0-9.+-]{1,30})?", value["version"])
            )
            and (
                value["commit"] is None
                or isinstance(value["commit"], str)
                and re.fullmatch(r"[0-9a-f]{40}", value["commit"])
            )
        )
    if category == "resources":
        return (
            set(value)
            == {"coverage", "snapshot_count", "categories", "source_observed_at", "source_revision"}
            and value["coverage"] == "complete"
            and isinstance(value["source_observed_at"], str)
            and INSTANT.fullmatch(value["source_observed_at"])
            and isinstance(value["source_revision"], str)
            and SHA.fullmatch(value["source_revision"])
            and _number(value["snapshot_count"]) is not None
            and isinstance(value["categories"], dict)
            and set(value["categories"]) == set(RESOURCE_CATEGORIES)
            and all(
                isinstance(row, dict)
                and set(row) == {"file_count", "byte_count"}
                and all(_number(n) is not None for n in row.values())
                for row in value["categories"].values()
            )
        )
    fields = {"coverage", "observed_count", "limit", "counts"}
    unavailable = value.get("coverage") == "unavailable"
    return (
        set(value) == fields | ({"reason"} if unavailable else {"invalid_count"})
        and value["coverage"] in {"complete", "partial", "unavailable"}
        and type(value["limit"]) is int
        and value["limit"] == MAX_RECORDS
        and _number(value["observed_count"]) is not None
        and value["observed_count"] <= MAX_RECORDS
        and (
            value["reason"] == "producer_absent"
            if unavailable
            else _number(value["invalid_count"]) is not None
        )
        and isinstance(value["counts"], dict)
        and set(value["counts"]) == _states(category) | {"other"}
        and all(_number(n) is not None and n <= MAX_RECORDS for n in value["counts"].values())
    )


def _validate_snapshot(value):
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "redaction_schema_version",
            "plan_ref",
            "instance_id",
            "observed_at",
            "categories",
            "omitted_categories",
            "not_a_backup",
        }
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["redaction_schema_version"]) is not int
        or value["redaction_schema_version"] != 1
        or not isinstance(value["plan_ref"], str)
        or not PLAN_ID.fullmatch(value["plan_ref"])
        or not isinstance(value["instance_id"], str)
        or not re.fullmatch(r"inst_[0-9a-f]{32}", value["instance_id"])
        or not isinstance(value["observed_at"], str)
        or not INSTANT.fullmatch(value["observed_at"])
        or value["not_a_backup"] is not True
        or not isinstance(value["categories"], dict)
        or not value["categories"]
        or not set(value["categories"]) <= set(CATEGORIES)
        or value["omitted_categories"] != [n for n in CATEGORIES if n not in value["categories"]]
        or not all(_valid_projection(n, row) for n, row in value["categories"].items())
    ):
        raise MaintenanceTargetError("invalid_private_state")


class DiagnosticExportService:
    def __init__(self, store: InstanceStore):
        self.store = store
        self.targets = LocalTargetRegistry(store)
        self.root = self.targets.root / "diagnostic-plans"

    def _records(self, relative, states, *, validator=None):
        directory = self.store.paths.root / relative
        counts = {state: 0 for state in states}
        counts["other"] = 0
        seen = 0
        invalid = 0
        complete = True
        try:
            with (
                pinned_parent(directory / ".inventory") as (probe, parent),
                os.scandir(probe.parent if os.name == "nt" else parent) as entries,
            ):
                for entry in entries:
                    seen += 1
                    if seen > MAX_RECORDS:
                        complete = False
                        break
                    if not entry.name.endswith(".json"):
                        invalid += 1
                        continue
                    try:
                        with open_local_file(directory / entry.name) as handle:
                            raw = handle.read(256 * 1024 + 1)
                        if len(raw) > 256 * 1024:
                            raise ValueError("bound")
                        value = strict_json(raw)
                        if not isinstance(value, dict):
                            raise ValueError("shape")
                        if validator is not None:
                            value = validator(value)
                        state = value.get("status")
                        counts[state if state in states else "other"] += 1
                    except (OSError, ValueError, KeyError, TypeError):
                        invalid += 1
        except MaintenanceTargetError as error:
            if error.code != "target_missing":
                raise
            # Absence is explicit; it is not a positive observation of an empty journal.
            return {
                "coverage": "unavailable",
                "reason": "producer_absent",
                "observed_count": 0,
                "limit": MAX_RECORDS,
                "counts": counts,
            }
        return {
            "coverage": "complete" if complete and not invalid else "partial",
            "observed_count": min(seen, MAX_RECORDS),
            "limit": MAX_RECORDS,
            "invalid_count": invalid,
            "counts": counts,
        }

    def _read(self, category):
        if category == "build":
            from .about import current_about

            about = current_about()
            version = about.get("version", "")
            commit = about.get("commit", "")
            return {
                "coverage": "complete",
                "version": version
                if isinstance(version, str)
                and re.fullmatch(r"\d+\.\d+\.\d+(?:[a-z0-9.+-]{1,30})?", version)
                else None,
                "commit": commit
                if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit)
                else None,
            }
        if category == "scheduler":
            from .scheduler_model import JOB_STATUSES, validate_job_record

            return self._records(
                "state/scheduler/jobs", JOB_STATUSES, validator=validate_job_record
            )
        if category == "maintenance":
            from .maintenance_model import REINDEX_STATUSES, validate_reindex_run

            return self._records(
                "state/maintenance/reindex-runs", REINDEX_STATUSES, validator=validate_reindex_run
            )
        if category == "operations_summary":
            from .operations import OPERATION_STATUSES, OperationLedger

            def validate(value):
                record = OperationLedger._record_from_payload(value)
                OperationLedger._validate_record(record)
                return {"status": record.status}

            return self._records("state/operations/records", OPERATION_STATUSES, validator=validate)
        from .resource_statistics import ResourceStatisticsManager
        from .resource_statistics_model import RESOURCE_CATEGORIES

        current = ResourceStatisticsManager(self.store).status(history_limit=0)
        latest = current.get("latest")
        if not isinstance(latest, dict):
            return {"coverage": "unavailable", "reason": "producer_absent"}
        categories = latest.get("categories", {})
        return {
            "coverage": "complete",
            "snapshot_count": _number(current.get("snapshot_count")),
            "source_observed_at": latest["observed_at"],
            "source_revision": revision(latest),
            "categories": {
                name: {
                    key: _number(categories.get(name, {}).get(key))
                    for key in ("file_count", "byte_count")
                }
                for name in RESOURCE_CATEGORIES
            },
        }

    def _path(self, plan_ref):
        if not isinstance(plan_ref, str) or not PLAN_ID.fullmatch(plan_ref):
            raise MaintenanceTargetError("invalid_input")
        return self.root / (plan_ref + ".json")

    def _load(self, plan_ref, expected_revision):
        with open_local_file(self._path(plan_ref)) as handle:
            raw = handle.read(MAX_PLAN_BYTES + 1)
        if len(raw) > MAX_PLAN_BYTES:
            raise MaintenanceTargetError("invalid_private_state")
        value = strict_json(raw)
        if isinstance(value, dict) and "snapshot" in value:
            _validate_snapshot(value["snapshot"])
        if (
            not isinstance(value, dict)
            or set(value) != {"snapshot", "revision", "receipts"}
            or value["revision"] != expected_revision
            or revision(value["snapshot"]) != expected_revision
            or value["snapshot"].get("instance_id") != self.targets.instance_id
            or value["snapshot"].get("plan_ref") != plan_ref
            or not isinstance(value["receipts"], dict)
            or len(value["receipts"]) > 8
        ):
            raise MaintenanceTargetError("plan_stale")
        for key, entry in value["receipts"].items():
            if (
                not REQUEST_ID.fullmatch(key)
                or not isinstance(entry, dict)
                or set(entry) != {"binding", "state", "receipt"}
                or entry["state"] not in {"prepared", "exported"}
                or not isinstance(entry["binding"], str)
                or not SHA.fullmatch(entry["binding"])
                or not isinstance(entry["receipt"], dict)
            ):
                raise MaintenanceTargetError("invalid_private_state")
            receipt = entry["receipt"]
            if (
                set(receipt)
                != {
                    "status",
                    "instance_id",
                    "plan_ref",
                    "plan_revision",
                    "target_ref",
                    "archive_sha256",
                    "size_bytes",
                    "member_count",
                    "created_at",
                    "observation_at",
                    "not_a_backup",
                }
                or receipt["status"] != "exported"
                or receipt["instance_id"] != self.targets.instance_id
                or receipt["plan_ref"] != plan_ref
                or receipt["plan_revision"] != expected_revision
                or not isinstance(receipt["target_ref"], str)
                or not REF.fullmatch(receipt["target_ref"])
                or not isinstance(receipt["archive_sha256"], str)
                or not SHA.fullmatch(receipt["archive_sha256"])
                or _number(receipt["size_bytes"]) is None
                or receipt["size_bytes"] > MAX_PLAN_BYTES
                or type(receipt["member_count"]) is not int
                or receipt["member_count"] != len(value["snapshot"]["categories"]) + 1
                or not isinstance(receipt["created_at"], str)
                or not INSTANT.fullmatch(receipt["created_at"])
                or receipt["observation_at"] != value["snapshot"]["observed_at"]
                or receipt["not_a_backup"] is not True
            ):
                raise MaintenanceTargetError("invalid_private_state")
        return value

    def preview(self, categories=None):
        selected = list(CATEGORIES) if categories is None else categories
        if (
            not isinstance(selected, (list, tuple))
            or not selected
            or len(selected) > len(CATEGORIES)
            or any(not isinstance(name, str) or name not in CATEGORIES for name in selected)
            or len(set(selected)) != len(selected)
        ):
            raise MaintenanceTargetError("invalid_input")
        selected = [name for name in CATEGORIES if name in selected]
        payload = {}
        for name in selected:
            try:
                payload[name] = self._read(name)
            except (OSError, ValueError, KeyError, TypeError):
                payload[name] = {"coverage": "unavailable", "reason": "producer_unreadable"}
        snapshot = {
            "schema_version": 1,
            "redaction_schema_version": 1,
            "plan_ref": "diagnostic_" + uuid4().hex,
            "instance_id": self.targets.instance_id,
            "observed_at": utc_now(),
            "categories": payload,
            "omitted_categories": [name for name in CATEGORIES if name not in selected],
            "not_a_backup": True,
        }
        _validate_snapshot(snapshot)
        digest = revision(snapshot)
        value = {"snapshot": snapshot, "revision": digest, "receipts": {}}
        raw = canonical_bytes(value)
        if len(raw) > MAX_PLAN_BYTES:
            raise MaintenanceTargetError("diagnostic_size_bound")
        with self.targets.hold():
            with pinned_parent(self.root):
                self.root.mkdir(mode=0o700, exist_ok=True)
            with pinned_parent(self.root / ".inventory"):
                if sum(1 for _ in self.root.iterdir()) >= MAX_PLANS:
                    raise MaintenanceTargetError("diagnostic_capacity")
            write_local_bytes(self._path(snapshot["plan_ref"]), raw)
        return {
            "plan_ref": snapshot["plan_ref"],
            "revision": digest,
            "instance_id": self.targets.instance_id,
            "categories": selected,
            "member_count": len(selected) + 1,
            "estimated_bytes": len(self._bundle(snapshot)),
            "coverage": {name: row["coverage"] for name, row in payload.items()},
            "observed_at": snapshot["observed_at"],
            "omitted_categories": snapshot["omitted_categories"],
        }

    def status(self):
        """Pure bounded recovery inventory of reviewed plans and delivery metadata."""
        plans = []
        invalid = 0
        complete = True
        try:
            with (
                pinned_parent(self.root / ".inventory") as (probe, parent),
                os.scandir(probe.parent if parent is None else parent) as entries,
            ):
                for index, entry in enumerate(entries):
                    if index >= MAX_PLANS:
                        complete = False
                        break
                    name = entry.name.removesuffix(".json")
                    try:
                        if not entry.name.endswith(".json") or not PLAN_ID.fullmatch(name):
                            raise MaintenanceTargetError("invalid_private_state")
                        with open_local_file(self._path(name)) as handle:
                            raw = handle.read(MAX_PLAN_BYTES + 1)
                        if len(raw) > MAX_PLAN_BYTES:
                            raise MaintenanceTargetError("invalid_private_state")
                        value = strict_json(raw)
                        value = self._load(name, value["revision"])
                        snapshot = value["snapshot"]
                        plans.append(
                            {
                                "plan_ref": name,
                                "revision": value["revision"],
                                "instance_id": self.targets.instance_id,
                                "categories": [
                                    n for n in CATEGORIES if n in snapshot["categories"]
                                ],
                                "member_count": len(snapshot["categories"]) + 1,
                                "estimated_bytes": len(self._bundle(snapshot)),
                                "observed_at": snapshot["observed_at"],
                                "coverage": {
                                    n: row["coverage"] for n, row in snapshot["categories"].items()
                                },
                                "omitted_categories": snapshot["omitted_categories"],
                                "receipts": [
                                    {
                                        "state": row["state"],
                                        **{
                                            key: row["receipt"][key]
                                            for key in (
                                                "target_ref",
                                                "archive_sha256",
                                                "size_bytes",
                                                "created_at",
                                            )
                                        },
                                    }
                                    for row in value["receipts"].values()
                                ],
                            }
                        )
                    except (ValueError, OSError, TypeError, KeyError):
                        invalid += 1
        except MaintenanceTargetError as exc:
            if exc.code != "target_missing":
                raise
        return {
            "instance_id": self.targets.instance_id,
            "plans": plans,
            "capacity": MAX_PLANS,
            "complete": complete and not invalid,
            "invalid_count": invalid,
        }

    @staticmethod
    def _bundle(snapshot):
        _validate_snapshot(snapshot)
        members = {
            name + ".json": canonical_bytes(value) for name, value in snapshot["categories"].items()
        }
        manifest = {key: value for key, value in snapshot.items() if key != "categories"}
        manifest["members"] = [
            {"path": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(members.items())
        ]
        members["manifest.json"] = canonical_bytes(manifest)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, raw in sorted(members.items()):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o100600 << 16
                archive.writestr(info, raw)
        if len(output.getvalue()) > MAX_PLAN_BYTES:
            raise MaintenanceTargetError("diagnostic_size_bound")
        return output.getvalue()

    def export(
        self,
        plan_ref,
        expected_revision,
        target_ref,
        expected_target_revision,
        *,
        confirm,
        request_key,
    ):
        if (
            confirm is not True
            or not isinstance(request_key, str)
            or not REQUEST_ID.fullmatch(request_key)
        ):
            raise MaintenanceTargetError("invalid_input")
        # One metadata lock protects replay and publication, without introducing a queue.
        with self.targets.hold():
            value = self._load(plan_ref, expected_revision)
            binding = revision(
                {
                    "plan_ref": plan_ref,
                    "revision": expected_revision,
                    "target_ref": target_ref,
                    "target_revision": expected_target_revision,
                }
            )
            previous = value["receipts"].get(request_key)
            if previous:
                if previous["binding"] != binding:
                    raise MaintenanceTargetError("request_conflict")
                if previous["state"] == "exported":
                    return {**previous["receipt"], "replayed": True}
                # Publication and receipt cannot form one filesystem transaction.
                # A prepared request is never presented as a completed export.
                raise MaintenanceTargetError("export_outcome_uncertain")
            if len(value["receipts"]) >= 8:
                raise MaintenanceTargetError("diagnostic_capacity")
            row = self.targets.resolve(target_ref, expected_target_revision, "diagnostic_write")
            destination = Path(row["locator"])
            with pinned_parent(destination) as (_, parent):
                info = destination.parent.stat() if parent is None else os.fstat(parent)
                if row["identity"] != {"device": info.st_dev, "inode": info.st_ino}:
                    raise MaintenanceTargetError("target_stale")
                archive = self._bundle(value["snapshot"])
            receipt = {
                "status": "exported",
                "instance_id": self.targets.instance_id,
                "plan_ref": plan_ref,
                "plan_revision": expected_revision,
                "target_ref": target_ref,
                "archive_sha256": hashlib.sha256(archive).hexdigest(),
                "size_bytes": len(archive),
                "member_count": len(value["snapshot"]["categories"]) + 1,
                "created_at": utc_now(),
                "observation_at": value["snapshot"]["observed_at"],
                "not_a_backup": True,
            }
            value["receipts"][request_key] = {
                "binding": binding,
                "receipt": receipt,
                "state": "prepared",
            }
            write_local_bytes(self._path(plan_ref), canonical_bytes(value), replace=True)
            # The destination is checked again under its pinned parents at publication.
            with pinned_parent(destination) as (_, parent):
                info = destination.parent.stat() if parent is None else os.fstat(parent)
                if row["identity"] != {"device": info.st_dev, "inode": info.st_ino}:
                    raise MaintenanceTargetError("target_stale")
                write_local_bytes(destination, archive)
            value["receipts"][request_key]["state"] = "exported"
            try:
                write_local_bytes(self._path(plan_ref), canonical_bytes(value), replace=True)
            except (OSError, MaintenanceTargetError) as exc:
                raise MaintenanceTargetError("export_outcome_uncertain") from exc
            return {**receipt, "replayed": False}

    def forget(self, plan_ref, expected_revision, *, confirm):
        if confirm is not True:
            raise MaintenanceTargetError("invalid_input")
        with self.targets.hold():
            self._load(plan_ref, expected_revision)
            with pinned_parent(self._path(plan_ref)) as (path, parent):
                if parent is None:
                    path.unlink()
                else:
                    os.unlink(path.name, dir_fd=parent)
        return {"status": "forgotten", "plan_ref": plan_ref, "exported_files_deleted": False}
