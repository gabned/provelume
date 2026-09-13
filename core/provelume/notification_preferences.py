"""Closed, content-minimizing notification preferences; no delivery or permission requests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .scheduler_model import SchedulerError, resolve_local_time, utc_instant

NOTIFICATION_CHANNELS = ("in_app", "host_desktop", "browser", "pwa")


class NotificationPreferencesError(ValueError):
    code = "notification_preferences_invalid"


@dataclass(frozen=True, slots=True)
class NotificationPreferences:
    in_app: bool = True
    host_desktop: bool = False
    browser: bool = False
    pwa: bool = False
    quiet_enabled: bool = False
    quiet_start: str = "22:00"
    quiet_end: str = "08:00"
    timezone: str = "UTC"
    aggregation_seconds: int = 60

    def normalized(self) -> NotificationPreferences:
        if not isinstance(self.timezone, str) or self.timezone != self.timezone.strip():
            raise NotificationPreferencesError("notification timezone must be an exact IANA name")
        if any(
            type(getattr(self, key)) is not bool
            for key in (*NOTIFICATION_CHANNELS, "quiet_enabled")
        ):
            raise NotificationPreferencesError("notification switches must be booleans")
        if type(self.aggregation_seconds) is not int or not 1 <= self.aggregation_seconds <= 3600:
            raise NotificationPreferencesError("notification aggregation must be 1 to 3600 seconds")
        if self.quiet_start == self.quiet_end:
            raise NotificationPreferencesError("notification quiet hours cannot cover a full day")
        try:
            for clock in (self.quiet_start, self.quiet_end):
                resolve_local_time(
                    utc_instant("2026-01-01T00:00:00Z").date(),
                    clock,
                    timezone=self.timezone,
                    dst_policy="latest",
                )
        except (SchedulerError, TypeError, ValueError) as exc:
            raise NotificationPreferencesError("notification quiet hours are invalid") from exc
        return self

    def as_payload(self) -> dict[str, Any]:
        value = self.normalized()
        return {
            "schema_version": 1,
            "channels": {key: getattr(value, key) for key in NOTIFICATION_CHANNELS},
            "preview": "counts_only",
            "quiet_hours": {
                "enabled": value.quiet_enabled,
                "start": value.quiet_start,
                "end": value.quiet_end,
                "timezone": value.timezone,
            },
            "aggregation_seconds": value.aggregation_seconds,
        }

    @classmethod
    def from_payload(cls, value: Any) -> NotificationPreferences:
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "channels",
            "preview",
            "quiet_hours",
            "aggregation_seconds",
        }:
            raise NotificationPreferencesError("notification preference fields are invalid")
        channels, quiet = value["channels"], value["quiet_hours"]
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["preview"] != "counts_only"
            or not isinstance(channels, dict)
            or set(channels) != set(NOTIFICATION_CHANNELS)
            or not isinstance(quiet, dict)
            or set(quiet) != {"enabled", "start", "end", "timezone"}
        ):
            raise NotificationPreferencesError("notification preference contract is invalid")
        return cls(
            **channels,
            quiet_enabled=quiet["enabled"],
            quiet_start=quiet["start"],
            quiet_end=quiet["end"],
            timezone=quiet["timezone"],
            aggregation_seconds=value["aggregation_seconds"],
        ).normalized()

    @classmethod
    def from_internal(cls, value: Any) -> NotificationPreferences:
        """Support desktop asdict reconstruction without widening the wire schema."""
        if isinstance(value, cls):
            return value.normalized()
        if isinstance(value, dict) and set(value) == set(asdict(cls())):
            return cls(**value).normalized()
        raise NotificationPreferencesError("notification preferences are invalid")

    def digest(self) -> str:
        raw = json.dumps(self.as_payload(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    def channel_states(self, *, invalid_settings: bool = False) -> dict[str, dict[str, Any]]:
        self.normalized()
        return {
            channel: {
                "requested": getattr(self, channel),
                "supported": channel == "in_app",
                "permission": "not_required" if channel == "in_app" else "unknown",
                "enabled": channel == "in_app" and self.in_app and not invalid_settings,
                "state": (
                    "invalid_configuration"
                    if invalid_settings
                    else "integration_pending"
                    if channel != "in_app"
                    else "available"
                    if self.in_app
                    else "disabled"
                ),
                "integration_owner": {
                    "in_app": "S03",
                    "host_desktop": "S09",
                    "browser": "S06/S09",
                    "pwa": "S06/S07/S09",
                }[channel],
            }
            for channel in NOTIFICATION_CHANNELS
        }

    def next_eligible_at(self, now: Any) -> Any:
        """Quiet hours use real intervals, including the entire repeated DST end interval."""
        self.normalized()
        instant = utc_instant(now)
        if not self.quiet_enabled:
            return instant
        local_date = instant.astimezone(ZoneInfo(self.timezone)).date()
        for start_date in (local_date - timedelta(days=1), local_date):
            end_date = start_date + timedelta(days=self.quiet_start > self.quiet_end)
            start = resolve_local_time(
                start_date, self.quiet_start, timezone=self.timezone, dst_policy="earliest"
            )
            if start is None:
                start = resolve_local_time(
                    start_date, self.quiet_start, timezone=self.timezone, dst_policy="shift_forward"
                )
            end = resolve_local_time(
                end_date, self.quiet_end, timezone=self.timezone, dst_policy="latest"
            )
            if end is None:
                end = resolve_local_time(
                    end_date, self.quiet_end, timezone=self.timezone, dst_policy="shift_forward"
                )
            if start is not None and end is not None and start <= instant < end:
                return end
        return instant


def notification_change(
    value: Any, *, revision: int, preferences: NotificationPreferences
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "revision",
        "recorded_at_utc",
        "source",
        "previous_sha256",
        "sha256",
        "changed",
    }:
        raise NotificationPreferencesError("notification change receipt fields are invalid")
    hashes = (value["previous_sha256"], value["sha256"])
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["revision"]) is not int
        or not 1 <= value["revision"] <= revision
        or value["source"] not in {"local_browser", "local_process"}
        or any(
            not isinstance(h, str) or len(h) != 64 or any(c not in "0123456789abcdef" for c in h)
            for h in hashes
        )
        or value["sha256"] != preferences.digest()
        or type(value["changed"]) is not bool
        or value["changed"] != (hashes[0] != hashes[1])
    ):
        raise NotificationPreferencesError("notification change receipt is invalid")
    try:
        timestamp = value["recorded_at_utc"]
        if not isinstance(timestamp, str) or not 20 <= len(timestamp) <= 40:
            raise ValueError("invalid receipt time")
        parsed = utc_instant(timestamp)
        if parsed.isoformat() != timestamp:
            raise ValueError("receipt time must use canonical UTC")
    except (SchedulerError, ValueError) as exc:
        raise NotificationPreferencesError("notification change receipt time is invalid") from exc
    return dict(value)
