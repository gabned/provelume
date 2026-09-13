"""Foreground notification projection and explicit acknowledgement of exact item revisions.

Reads are pure. The small acknowledgement journal is transport metadata, never a
review queue, a decision store, a permission grant or an outward delivery adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .scheduler_model import utc_instant
from .shell_settings import (
    MAX_SETTINGS_REVISION,
    LoadedSettings,
    ShellSettingsError,
    _acquire_os_lock,
    _atomic_json,
    _guard_path,
    _release_os_lock,
)

MAX_NOTIFICATION_ITEMS = 100
MAX_ACKNOWLEDGED_ITEMS = 512
MAX_ACK_RECEIPTS = 32
MAX_NOTIFICATION_JOURNAL_BYTES = 64 * 1024
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_INSTANCE = re.compile(r"inst_[0-9a-f]{32}\Z")
_ITEM = re.compile(r"aci_[0-9a-f]{32}\Z")


class NotificationError(ValueError):
    code = "notification_invalid"


class NotificationStale(NotificationError):
    code = "stale_notification"


class NotificationJournalError(NotificationError):
    code = "notification_journal_invalid"


class NotificationCapacityError(NotificationError):
    code = "notification_journal_full"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _revision(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_SETTINGS_REVISION


def _hash(value: Any) -> bool:
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


class NotificationService:
    def __init__(self, instance_root: Path | str, instance_id: str):
        if not isinstance(instance_id, str) or _INSTANCE.fullmatch(instance_id) is None:
            raise NotificationError("invalid notification Instance identity")
        self.instance_root = Path(instance_root).expanduser().absolute()
        self.instance_id = instance_id
        self.path = self.instance_root / "state/action-center/notifications.json"

    def _identity(self) -> None:
        try:
            path = _guard_path(self.instance_root / "instance-manifest.json", allow_missing=False)
            if path.stat().st_size > MAX_NOTIFICATION_JOURNAL_BYTES:
                raise ValueError("oversized Instance manifest")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest["instance"]["id"] != self.instance_id:
                raise ValueError("Instance mismatch")
        except (OSError, ValueError, KeyError, TypeError, ShellSettingsError) as exc:
            raise NotificationError("notification Instance identity could not be verified") from exc

    def _members(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        self._identity()
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("instance_id") != self.instance_id
            or not _hash(snapshot.get("revision"))
            or type(snapshot.get("complete")) is not bool
            or snapshot.get("count_relation") not in {"exact", "at_least", "unknown"}
            or (
                snapshot.get("total") is not None
                and (type(snapshot["total"]) is not int or snapshot["total"] < 0)
            )
            or not isinstance(snapshot.get("items"), list)
            or len(snapshot["items"]) > MAX_NOTIFICATION_ITEMS
        ):
            raise NotificationError("invalid authoritative notification snapshot")
        if snapshot["complete"] != (snapshot.get("total") is not None):
            raise NotificationError("notification snapshot count completeness is inconsistent")
        if snapshot["complete"] != (snapshot["count_relation"] == "exact"):
            raise NotificationError("notification snapshot count relation is inconsistent")
        members = []
        seen = set()
        for item in snapshot["items"]:
            if (
                not isinstance(item, dict)
                or item.get("instance_id") != self.instance_id
                or not isinstance(item.get("id"), str)
                or _ITEM.fullmatch(item["id"]) is None
                or not _hash(item.get("revision"))
                or item["id"] in seen
            ):
                raise NotificationError("invalid notification item reference")
            seen.add(item["id"])
            if item.get("review_state") != "awaiting_review":
                continue
            members.append(
                {
                    "item_id": item["id"],
                    "revision": item["revision"],
                    "href": f"/attention/items/{item['id']}?"
                    + urlencode({"instance_id": self.instance_id, "revision": item["revision"]}),
                }
            )
        return sorted(members, key=lambda member: member["item_id"])

    def _key(self, member: dict[str, str]) -> str:
        return _digest([self.instance_id, member["item_id"], member["revision"], "in_app"])

    def _load(self) -> dict[str, Any]:
        try:
            path = _guard_path(self.path, allow_missing=True)
            if not path.exists():
                return {
                    "schema_version": 1,
                    "instance_id": self.instance_id,
                    "revision": 0,
                    "acknowledged": [],
                    "receipts": [],
                    "last_acknowledged_at": None,
                    "last_reset": None,
                }
            if path.stat().st_size > MAX_NOTIFICATION_JOURNAL_BYTES:
                raise ValueError("journal size limit")
            value = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or set(value)
                != {
                    "schema_version",
                    "instance_id",
                    "revision",
                    "acknowledged",
                    "receipts",
                    "last_acknowledged_at",
                    "last_reset",
                }
                or type(value["schema_version"]) is not int
                or value["schema_version"] != 1
                or value["instance_id"] != self.instance_id
                or not _revision(value["revision"])
                or not isinstance(value["acknowledged"], list)
                or len(value["acknowledged"]) > MAX_ACKNOWLEDGED_ITEMS
                or not all(_hash(key) for key in value["acknowledged"])
                or len(set(value["acknowledged"])) != len(value["acknowledged"])
                or not isinstance(value["receipts"], list)
                or len(value["receipts"]) > MAX_ACK_RECEIPTS
            ):
                raise ValueError("journal contract")
            reset = value["last_reset"]
            reset_revision = 0
            if reset is not None:
                if (
                    not isinstance(reset, dict)
                    or set(reset)
                    != {
                        "schema_version",
                        "revision",
                        "previous_revision",
                        "settings_revision",
                        "reset_at",
                        "previous_sha256",
                        "previous_acknowledged_count",
                        "previous_receipt_count",
                        "redelivery_confirmed",
                    }
                    or type(reset["schema_version"]) is not int
                    or reset["schema_version"] != 1
                    or not _revision(reset["revision"])
                    or not 1 <= reset["revision"] <= value["revision"]
                    or not _revision(reset["previous_revision"])
                    or reset["previous_revision"] + 1 != reset["revision"]
                    or not _revision(reset["settings_revision"])
                    or not _hash(reset["previous_sha256"])
                    or type(reset["previous_acknowledged_count"]) is not int
                    or not 0 <= reset["previous_acknowledged_count"] <= MAX_ACKNOWLEDGED_ITEMS
                    or type(reset["previous_receipt_count"]) is not int
                    or not 0 <= reset["previous_receipt_count"] <= MAX_ACK_RECEIPTS
                    or reset["redelivery_confirmed"] is not True
                    or not isinstance(reset["reset_at"], str)
                    or utc_instant(reset["reset_at"]).isoformat() != reset["reset_at"]
                ):
                    raise ValueError("journal reset receipt")
                reset_revision = reset["revision"]
            previous = reset_revision
            seen = set()
            for receipt in value["receipts"]:
                if (
                    not isinstance(receipt, dict)
                    or set(receipt)
                    != {
                        "batch_id",
                        "revision",
                        "previous_revision",
                        "settings_revision",
                        "count",
                        "acknowledged_at",
                    }
                    or not _hash(receipt["batch_id"])
                    or receipt["batch_id"] in seen
                    or not _revision(receipt["revision"])
                    or not previous < receipt["revision"] <= value["revision"]
                    or not _revision(receipt["previous_revision"])
                    or receipt["previous_revision"] + 1 != receipt["revision"]
                    or not _revision(receipt["settings_revision"])
                    or type(receipt["count"]) is not int
                    or not 1 <= receipt["count"] <= MAX_NOTIFICATION_ITEMS
                    or not isinstance(receipt["acknowledged_at"], str)
                    or utc_instant(receipt["acknowledged_at"]).isoformat()
                    != receipt["acknowledged_at"]
                ):
                    raise ValueError("journal receipt")
                previous = receipt["revision"]
                seen.add(receipt["batch_id"])
            if value["receipts"]:
                if (
                    value["receipts"][-1]["revision"] != value["revision"]
                    or value["last_acknowledged_at"] != value["receipts"][-1]["acknowledged_at"]
                    or sum(row["count"] for row in value["receipts"]) > len(value["acknowledged"])
                ):
                    raise ValueError("journal head receipt")
            elif (
                value["revision"] != reset_revision
                or value["acknowledged"]
                or value["last_acknowledged_at"] is not None
            ):
                raise ValueError("journal initial state")
            return value
        except (OSError, ValueError, TypeError, KeyError, ShellSettingsError) as exc:
            raise NotificationJournalError(
                "notification acknowledgement journal is unavailable"
            ) from exc

    @contextmanager
    def _hold(self):
        path = _guard_path(self.path, allow_missing=True)
        lock = _guard_path(path.with_suffix(".json.lock"), allow_missing=True)
        lock.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        held = False
        try:
            _acquire_os_lock(descriptor)
            held = True
            yield
        finally:
            try:
                if held:
                    _release_os_lock(descriptor)
            finally:
                os.close(descriptor)

    def preview(
        self, snapshot: dict[str, Any], loaded_settings: LoadedSettings, *, now: Any = None
    ) -> dict[str, Any]:
        """Pure bounded foreground read; no receipt, settings or lockfile is created."""
        members = self._members(snapshot)
        settings = loaded_settings.settings.normalized()
        preferences = settings.notifications
        invalid = loaded_settings.warning == "settings_invalid_using_safe_defaults"
        instant = utc_instant(now)
        result: dict[str, Any] = {
            "schema_version": 1,
            "instance_id": self.instance_id,
            "state": "empty",
            "channels": preferences.channel_states(invalid_settings=invalid),
            "preferences": preferences.as_payload(),
            "batch_id": None,
            "items": [],
            "count": 0,
            "queue_count": snapshot["total"],
            "count_relation": snapshot["count_relation"],
            "snapshot_revision": snapshot["revision"],
            "snapshot_complete": snapshot["complete"],
            "journal_revision": None,
            "acknowledged_count": 0,
            "last_reset": None,
            "settings_revision": settings.revision,
            "next_eligible_at": None,
            "message_key": "notification.preview",
            "message_args": {"count": 0},
            "foreground_only": True,
            "outward_delivery_attempted": False,
            "network_used": False,
        }
        if invalid:
            return {**result, "state": "unavailable", "error_code": "invalid_configuration"}
        if not snapshot["complete"] and not members:
            return {**result, "state": "unavailable", "error_code": "snapshot_unavailable"}
        try:
            journal = self._load()
        except NotificationJournalError as exc:
            return {**result, "state": "unavailable", "error_code": exc.code}
        pending = [member for member in members if self._key(member) not in journal["acknowledged"]]
        result.update(
            journal_revision=journal["revision"],
            acknowledged_count=len(journal["acknowledged"]),
            last_reset=journal["last_reset"],
            items=pending,
            count=len(pending),
            message_args={"count": len(pending)},
        )
        if not preferences.in_app:
            return {
                **result,
                "state": "disabled",
                "items": [],
                "count": 0,
                "message_args": {"count": 0},
            }
        if not pending:
            return result
        if (
            len(journal["acknowledged"]) + len(pending) > MAX_ACKNOWLEDGED_ITEMS
            or journal["revision"] == MAX_SETTINGS_REVISION
        ):
            return {**result, "state": "unavailable", "error_code": "notification_journal_full"}
        result["batch_id"] = _digest(
            {
                "instance_id": self.instance_id,
                "settings_revision": settings.revision,
                "preferences": preferences.digest(),
                "members": [[m["item_id"], m["revision"]] for m in pending],
            }
        )
        due = instant
        state = "ready"
        if journal["last_acknowledged_at"] is not None:
            last = utc_instant(journal["last_acknowledged_at"])
            due = max(due, last + timedelta(seconds=preferences.aggregation_seconds))
            if last > instant:
                state = "clock_reversed"
            elif due > instant:
                state = "aggregating"
        quiet_due = preferences.next_eligible_at(due)
        if quiet_due > due:
            state = "deferred_quiet"
        due = max(due, quiet_due)
        result.update(state=state, next_eligible_at=due.isoformat())
        return result

    def acknowledge(
        self,
        snapshot: dict[str, Any],
        loaded_settings: LoadedSettings,
        *,
        batch_id: str,
        expected_revision: int,
        expected_settings_revision: int,
        now: Any = None,
    ) -> dict[str, Any]:
        """HTTP owner supplies CSRF/nonce protection and a fresh server snapshot."""
        self._members(snapshot)
        if (
            not _hash(batch_id)
            or not _revision(expected_revision)
            or not _revision(expected_settings_revision)
        ):
            raise NotificationError("invalid notification acknowledgement")
        if (
            loaded_settings.warning == "settings_invalid_using_safe_defaults"
            or loaded_settings.settings.revision != expected_settings_revision
        ):
            raise NotificationStale("notification preferences changed; reload before acknowledging")
        with self._hold():
            journal = self._load()
            for receipt in journal["receipts"]:
                if receipt["batch_id"] == batch_id:
                    if (
                        receipt["previous_revision"] != expected_revision
                        or receipt["settings_revision"] != expected_settings_revision
                    ):
                        raise NotificationStale("notification acknowledgement is stale")
                    return {
                        "status": "acknowledged",
                        "receipt": receipt,
                        "journal_revision": journal["revision"],
                        "replayed": True,
                    }
            if journal["revision"] != expected_revision:
                raise NotificationStale(
                    "notification acknowledgements changed; reload before retrying"
                )
            view = self.preview(snapshot, loaded_settings, now=now)
            if view.get("error_code") == "notification_journal_full":
                raise NotificationCapacityError(
                    "notification acknowledgement history reached its bound"
                )
            if view["state"] != "ready" or view["batch_id"] != batch_id:
                raise NotificationStale(
                    "notification batch changed or is unavailable; reload before retrying"
                )
            keys = sorted(
                set(journal["acknowledged"]) | {self._key(member) for member in view["items"]}
            )
            if len(keys) > MAX_ACKNOWLEDGED_ITEMS or journal["revision"] == MAX_SETTINGS_REVISION:
                raise NotificationCapacityError(
                    "notification acknowledgement history reached its bound"
                )
            receipt = {
                "batch_id": batch_id,
                "revision": journal["revision"] + 1,
                "previous_revision": journal["revision"],
                "settings_revision": expected_settings_revision,
                "count": view["count"],
                "acknowledged_at": utc_instant(now).isoformat(),
            }
            candidate = {
                **journal,
                "revision": receipt["revision"],
                "acknowledged": keys,
                "receipts": (journal["receipts"] + [receipt])[-MAX_ACK_RECEIPTS:],
                "last_acknowledged_at": receipt["acknowledged_at"],
            }
            _atomic_json(self.path, candidate, maximum=MAX_NOTIFICATION_JOURNAL_BYTES)
            return {
                "status": "acknowledged",
                "receipt": receipt,
                "journal_revision": candidate["revision"],
                "replayed": False,
            }

    def reset_acknowledgements(
        self,
        loaded_settings: LoadedSettings,
        *,
        expected_revision: int,
        expected_settings_revision: int,
        confirm_redelivery: bool,
        now: Any = None,
    ) -> dict[str, Any]:
        """Explicit metadata-only recovery; unchanged items become notifiable again."""
        self._identity()
        if (
            not _revision(expected_revision)
            or not _revision(expected_settings_revision)
            or confirm_redelivery is not True
        ):
            raise NotificationError("notification reset requires explicit redelivery confirmation")
        if (
            loaded_settings.warning == "settings_invalid_using_safe_defaults"
            or loaded_settings.settings.revision != expected_settings_revision
        ):
            raise NotificationStale("notification preferences changed; reload before resetting")
        with self._hold():
            journal = self._load()
            previous_reset = journal["last_reset"]
            if (
                previous_reset is not None
                and previous_reset["previous_revision"] == expected_revision
                and previous_reset["settings_revision"] == expected_settings_revision
            ):
                return {
                    "status": "reset",
                    "receipt": previous_reset,
                    "journal_revision": journal["revision"],
                    "replayed": True,
                }
            if journal["revision"] != expected_revision:
                raise NotificationStale("notification history changed; reload before resetting")
            if journal["revision"] == MAX_SETTINGS_REVISION:
                raise NotificationCapacityError("notification journal revision limit reached")
            receipt = {
                "schema_version": 1,
                "revision": journal["revision"] + 1,
                "previous_revision": journal["revision"],
                "settings_revision": expected_settings_revision,
                "reset_at": utc_instant(now).isoformat(),
                "previous_sha256": _digest(journal),
                "previous_acknowledged_count": len(journal["acknowledged"]),
                "previous_receipt_count": len(journal["receipts"]),
                "redelivery_confirmed": True,
            }
            candidate = {
                **journal,
                "revision": receipt["revision"],
                "acknowledged": [],
                "receipts": [],
                "last_acknowledged_at": None,
                "last_reset": receipt,
            }
            _atomic_json(self.path, candidate, maximum=MAX_NOTIFICATION_JOURNAL_BYTES)
            return {
                "status": "reset",
                "receipt": receipt,
                "journal_revision": candidate["revision"],
                "replayed": False,
            }
