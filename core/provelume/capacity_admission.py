"""Host-local, Instance-bound admission policy; never deletes or stops running work."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .instance_lifecycle import InstanceLifecycleManager
from .resource_statistics import ResourceStatisticsManager
from .resource_statistics_model import (
    ResourceStatisticsError,
    default_threshold_settings,
    validate_threshold_settings,
)
from .storage import InstanceStore

MODES = ("observe_only", "pause_on_critical", "paused")
MAX_POLICY_BYTES = 64 * 1024
MAX_POLICY_RECEIPTS = 128
_REQUEST = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")
_MISSING = object()


class CapacityAdmissionError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone")
    return result.astimezone(UTC)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _read_file(path: Path) -> Any:
    for parent in reversed((path, *path.parents)):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            return _MISSING
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise CapacityAdmissionError("capacity_policy_unsafe")

    def identity(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_POLICY_BYTES:
        raise CapacityAdmissionError("capacity_policy_invalid")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise CapacityAdmissionError("capacity_policy_changed")
        data = stream.read(MAX_POLICY_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (
        len(data) > MAX_POLICY_BYTES
        or identity(after) != identity(before)
        or identity(path.lstat()) != identity(before)
    ):
        raise CapacityAdmissionError("capacity_policy_changed")
    return json.loads(data, object_pairs_hook=_unique_object)


class CapacityAdmission:
    def __init__(self, store: InstanceStore):
        self.store = store
        self.lifecycle = InstanceLifecycleManager(store)
        self.path = self.lifecycle.control_root / "capacity-admission.json"
        self.resources = ResourceStatisticsManager(store)

    def _instance_id(self) -> str:
        return self.resources._instance_id()

    def _read(self) -> dict:
        try:
            value = _read_file(self.path)
            if value is _MISSING:
                return {
                    "schema_version": 1,
                    "instance_id": self._instance_id(),
                    "revision": 0,
                    "mode": "observe_only",
                    "receipts": [],
                    "last_wait": None,
                }
            if (
                not isinstance(value, dict)
                or set(value)
                != {"schema_version", "instance_id", "revision", "mode", "receipts", "last_wait"}
                or value["schema_version"] != 1
                or type(value["schema_version"]) is not int
                or value["instance_id"] != self._instance_id()
                or type(value["revision"]) is not int
                or not 0 <= value["revision"] <= MAX_POLICY_RECEIPTS
                or value["mode"] not in MODES
                or not isinstance(value["receipts"], list)
                or len(value["receipts"]) > MAX_POLICY_RECEIPTS
                or len(value["receipts"]) != value["revision"]
            ):
                raise ValueError("schema")
            seen = set()
            latest = None
            for revision, receipt in enumerate(value["receipts"], start=1):
                if (
                    not isinstance(receipt, dict)
                    or set(receipt) != {"request_id", "request_digest", "revision", "mode", "at"}
                    or not isinstance(receipt["request_id"], str)
                    or not _REQUEST.fullmatch(receipt["request_id"])
                    or receipt["request_id"] in seen
                    or not re.fullmatch(r"[0-9a-f]{64}", str(receipt["request_digest"]))
                    or type(receipt["revision"]) is not int
                    or receipt["revision"] != revision
                    or receipt["mode"] not in MODES
                ):
                    raise ValueError("receipt")
                if receipt["request_digest"] != _digest(
                    {"mode": receipt["mode"], "expected_revision": revision - 1}
                ):
                    raise ValueError("receipt binding")
                at = _instant(receipt["at"])
                if latest is not None and at < latest:
                    raise ValueError("receipt chronology")
                latest = at
                seen.add(receipt["request_id"])
            if value["mode"] != (
                value["receipts"][-1]["mode"] if value["receipts"] else "observe_only"
            ):
                raise ValueError("current mode")
            wait = value["last_wait"]
            if wait is not None:
                if (
                    not isinstance(wait, dict)
                    or set(wait) != {"reason", "observed_at", "required_bytes", "policy_revision"}
                    or wait["reason"]
                    not in {"manual_pause", "critical_capacity", "capacity_unavailable"}
                    or type(wait["required_bytes"]) is not int
                    or not 0 <= wait["required_bytes"] <= 2**63 - 1
                    or type(wait["policy_revision"]) is not int
                    or wait["policy_revision"] != value["revision"]
                ):
                    raise ValueError("wait")
                if (wait["reason"] == "manual_pause" and value["mode"] != "paused") or (
                    wait["reason"] != "manual_pause" and value["mode"] != "pause_on_critical"
                ):
                    raise ValueError("wait mode")
                if latest is not None and _instant(wait["observed_at"]) < latest:
                    raise ValueError("wait chronology")
                _instant(wait["observed_at"])
            return value
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise CapacityAdmissionError("capacity_policy_invalid") from exc

    def _write(self, value: dict) -> None:
        encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
        if len(encoded) > MAX_POLICY_BYTES:
            raise CapacityAdmissionError("capacity_policy_full")
        self.store._atomic_bytes(self.path, encoded)

    def _thresholds(self) -> dict:
        value = _read_file(self.resources.settings_path)
        settings = (
            default_threshold_settings(self._instance_id())
            if value is _MISSING
            else validate_threshold_settings(value)
        )
        if settings["instance_id"] != self._instance_id():
            raise CapacityAdmissionError("capacity_threshold_instance")
        return settings

    def status(self) -> dict:
        value = self._read()
        return {k: value[k] for k in ("instance_id", "revision", "mode", "last_wait")} | {
            "scope": "new_intake_admission",
            "host_local": True,
            "running_jobs_stopped": False,
            "automatic_deletion": False,
            "receipt_count": len(value["receipts"]),
            "receipt_limit": MAX_POLICY_RECEIPTS,
            "last_wait_is_live_capacity": False,
        }

    def configure(self, mode: str, *, expected_revision: int, request_id: str) -> dict:
        if (
            not isinstance(mode, str)
            or mode not in MODES
            or type(expected_revision) is not int
            or not 0 <= expected_revision <= MAX_POLICY_RECEIPTS
        ):
            raise CapacityAdmissionError("invalid_capacity_policy")
        if not isinstance(request_id, str) or not _REQUEST.fullmatch(request_id):
            raise CapacityAdmissionError("invalid_request")
        request_digest = _digest({"mode": mode, "expected_revision": expected_revision})
        # Reject redirected or invalid host state before even the guard writes
        # its operational metadata; re-read under the guard for CAS authority.
        self._read()
        with self.lifecycle._hold(purpose="capacity-admission-configure"):
            value = self._read()
            previous = next((r for r in value["receipts"] if r["request_id"] == request_id), None)
            if previous is not None:
                if previous["request_digest"] != request_digest:
                    raise CapacityAdmissionError("request_conflict")
                return {"receipt": previous, "replayed": True}
            if expected_revision != value["revision"]:
                raise CapacityAdmissionError("capacity_policy_stale")
            if len(value["receipts"]) >= MAX_POLICY_RECEIPTS:
                raise CapacityAdmissionError("capacity_policy_full")
            now = datetime.now(UTC).isoformat()
            if value["receipts"] and _instant(now) < _instant(value["receipts"][-1]["at"]):
                raise CapacityAdmissionError("capacity_clock_reversed")
            if value["last_wait"] and _instant(now) < _instant(value["last_wait"]["observed_at"]):
                raise CapacityAdmissionError("capacity_clock_reversed")
            value["revision"] += 1
            value["mode"] = mode
            value["last_wait"] = None
            receipt = {
                "request_id": request_id,
                "request_digest": request_digest,
                "revision": value["revision"],
                "mode": mode,
                "at": now,
            }
            value["receipts"].append(receipt)
            self._write(value)
            return {"receipt": receipt, "replayed": False}

    def _decision(self, policy: dict, required_bytes: int) -> dict:
        allowed, reason, observation = True, "observation_only", None
        if policy["mode"] == "paused":
            allowed, reason = False, "manual_pause"
        elif policy["mode"] == "pause_on_critical":
            try:
                settings = self._thresholds()
                if all(
                    settings["limits"][key] is None
                    for key in ("minimum_free_bytes_critical", "maximum_instance_bytes_critical")
                ):
                    raise CapacityAdmissionError("critical_limits_unconfigured")
                # Current metadata count is needed only when a size threshold is active.
                # Never turn an old snapshot into an admission-time size guarantee.
                size_limited = any(
                    settings["limits"][k] is not None
                    for k in ("maximum_instance_bytes_warning", "maximum_instance_bytes_critical")
                )
                byte_count = self.resources._scan()[2] if size_limited else 0
                capacity = self.resources._capacity()
                projected_bytes = byte_count + required_bytes
                if type(byte_count) is not int or not 0 <= projected_bytes <= 2**63 - 1:
                    raise CapacityAdmissionError("capacity_observation_bound")
                observation = self.resources._evaluate(
                    byte_count=projected_bytes,
                    free_bytes=max(0, capacity["free_bytes"] - required_bytes),
                    settings=settings,
                )
                if settings != self._thresholds():
                    raise CapacityAdmissionError("capacity_changed")
                allowed = (
                    observation["state"] != "critical" and required_bytes <= capacity["free_bytes"]
                )
                reason = "capacity_available" if allowed else "critical_capacity"
                observation = {
                    **observation,
                    "free_bytes": capacity["free_bytes"],
                    "instance_bytes": byte_count if size_limited else None,
                    "projected_free_bytes": max(0, capacity["free_bytes"] - required_bytes),
                    "projected_instance_bytes": projected_bytes if size_limited else None,
                    "evaluation_scope": "projected_after_required_bytes",
                }
            except (
                OSError,
                UnicodeError,
                ValueError,
                KeyError,
                TypeError,
                ResourceStatisticsError,
            ):
                allowed, reason, observation = False, "capacity_unavailable", None
        return {
            "instance_id": policy["instance_id"],
            "policy_revision": policy["revision"],
            "mode": policy["mode"],
            "allowed": allowed,
            "reason": reason,
            "required_bytes": required_bytes,
            "observation": observation,
            "observed_at": datetime.now(UTC).isoformat(),
            "scope": "new_intake_admission",
            "automatic_deletion": False,
            "running_jobs_stopped": False,
            "reusable_permit": False,
        }

    def check_admission(self, *, required_bytes: int = 0, record_wait: bool = False) -> dict:
        """Fresh check, not a reusable ticket. S06 calls at its serialized intake boundary.

        A denied check may record the current wait under the lifecycle guard. This
        field is a current observation, not a history or scheduler terminal receipt.
        """
        if (
            type(required_bytes) is not int
            or not 0 <= required_bytes <= 2**63 - 1
            or type(record_wait) is not bool
        ):
            raise CapacityAdmissionError("invalid_required_bytes")
        if not record_wait:
            policy = self._read()
            decision = self._decision(policy, required_bytes)
            if self._read() != policy:
                raise CapacityAdmissionError("capacity_policy_changed")
            return decision
        self._read()
        with self.lifecycle._hold(purpose="capacity-admission-check"):
            policy = self._read()
            decision = self._decision(policy, required_bytes)
            if self._read() != policy:
                raise CapacityAdmissionError("capacity_policy_changed")
            if policy["receipts"] and _instant(decision["observed_at"]) < _instant(
                policy["receipts"][-1]["at"]
            ):
                raise CapacityAdmissionError("capacity_clock_reversed")
            if policy["last_wait"] and _instant(decision["observed_at"]) < _instant(
                policy["last_wait"]["observed_at"]
            ):
                raise CapacityAdmissionError("capacity_clock_reversed")
            if not decision["allowed"]:
                policy["last_wait"] = {
                    k: decision[k]
                    for k in ("reason", "observed_at", "required_bytes", "policy_revision")
                }
                self._write(policy)
            elif policy["last_wait"] is not None:
                policy["last_wait"] = None
                self._write(policy)
            return decision
