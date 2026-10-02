"""Portable host preferences and atomic, revision-bound reset/import/undo."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .catalog_registry import format_number, message, registry
from .notification_preferences import NotificationPreferences
from .shell_settings import (
    INTERFACE_MODES,
    LANGUAGES,
    MAX_PREFERENCES_BYTES,
    THEMES,
    UPDATE_CHANNELS,
    InterfaceModeChange,
    LauncherSettings,
    ShellPortUnavailable,
    ShellPreferencesError,
    ShellSettingsManager,
    configure_login_startup,
    default_settings,
    probe_port,
    validate_port,
)

PREFERENCE_FIELDS = frozenset(
    {
        "endpoint_port",
        "tray_enabled",
        "login_startup",
        "theme",
        "language",
        "interface_mode",
        "check_on_start",
        "update_channel",
        "notifications",
    }
)
RESET_SCOPES = {
    "appearance_language": frozenset({"theme", "language", "interface_mode"}),
    "notifications_background": frozenset(
        {
            "notifications",
            "tray_enabled",
            "login_startup",
            "check_on_start",
        }
    ),
    "all": PREFERENCE_FIELDS,
}


def preference_payload(settings: LauncherSettings) -> dict[str, Any]:
    selected = settings.normalized()
    return {
        "schema_version": 2,
        "kind": "provelume-shell-preferences",
        **{key: getattr(selected, key) for key in PREFERENCE_FIELDS - {"notifications"}},
        "notifications": selected.notifications.as_payload(),
    }


def preference_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def preference_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(preference_bytes(payload)).hexdigest()


def preference_display(key: str, value: Any, language: str) -> str:
    if type(value) is bool:
        return message(language, "common.yes" if value else "common.no")
    if key == "theme":
        return message(language, "shell.theme." + value)
    if key == "language":
        return (
            message(language, "common.language_system")
            if value == "system"
            else next(row["label"] for row in registry()["languages"] if row["id"] == value)
        )
    if key == "interface_mode":
        return message(language, "shell.interface." + value)
    if key == "endpoint_port":
        return str(value)
    if key == "notifications":

        def yes(selected):
            return message(language, "common.yes" if selected else "common.no")

        parts = [
            message(language, "action." + channel) + ": " + yes(enabled)
            for channel, enabled in value["channels"].items()
        ]
        quiet = value["quiet_hours"]
        parts.append(
            message(language, "action.quiet")
            + ": "
            + yes(quiet["enabled"])
            + f" ({quiet['start']}–{quiet['end']}, {quiet['timezone']})"
        )
        parts.append(
            message(language, "action.aggregation")
            + ": "
            + format_number(value["aggregation_seconds"], language)
        )
        return "; ".join(parts)
    return str(value)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ShellPreferencesError("duplicate preference key")
        result[key] = value
    return result


def parse_preferences(raw: bytes, *, current: LauncherSettings) -> dict[str, Any]:
    if len(raw) > MAX_PREFERENCES_BYTES:
        raise ShellPreferencesError("preferences import exceeds the size limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ShellPreferencesError("preferences import is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ShellPreferencesError("preferences import must be an object")
    version = value.get("schema_version")
    if type(version) is not int or version not in {1, 2}:
        raise ShellPreferencesError("unsupported preferences schema")
    fields = (
        PREFERENCE_FIELDS
        if version == 2
        else PREFERENCE_FIELDS
        - {
            "interface_mode",
            "check_on_start",
            "update_channel",
            "notifications",
        }
    )
    if set(value) != fields | {"schema_version", "kind"}:
        raise ShellPreferencesError("preferences import fields are invalid")
    if value.get("kind") != "provelume-shell-preferences":
        raise ShellPreferencesError("preferences import kind is invalid")
    result = {**preference_payload(current), **value, "schema_version": 2}
    if any(
        type(result[key]) is not bool
        for key in (
            "tray_enabled",
            "login_startup",
            "check_on_start",
        )
    ):
        raise ShellPreferencesError("preference switches must be booleans")
    for key, allowed in (
        ("theme", THEMES),
        ("language", LANGUAGES),
        ("interface_mode", INTERFACE_MODES),
        ("update_channel", UPDATE_CHANNELS),
    ):
        if not isinstance(result[key], str) or result[key] not in allowed:
            raise ShellPreferencesError("preference enum is invalid")
    result["endpoint_port"] = validate_port(result["endpoint_port"])
    result["notifications"] = NotificationPreferences.from_payload(
        result["notifications"]
    ).as_payload()
    return result


def reset_preview(current: LauncherSettings, scope: str) -> dict[str, Any]:
    if scope not in RESET_SCOPES:
        raise ShellPreferencesError("unsupported preference reset scope")
    before = preference_payload(current)
    defaults = preference_payload(default_settings())
    after = {**before, **{key: defaults[key] for key in RESET_SCOPES[scope]}}
    return {
        "scope": scope,
        "revision": current.revision,
        "before": before,
        "after": after,
        "changed_fields": sorted(key for key in PREFERENCE_FIELDS if before[key] != after[key]),
        "preserved": ["knowledge", "credentials", "sources", "history", "backups", "instance"],
        "restart_required": after["endpoint_port"] != current.endpoint_port,
    }


def apply_preferences(
    manager: ShellSettingsManager,
    payload: dict[str, Any],
    *,
    expected_revision: int,
    source: str = "local_browser",
    expected_digest: str | None = None,
) -> LauncherSettings:
    # Validate again within the OS lock; an import preview grants no authority.
    def change(current):
        if (
            expected_digest is not None
            and preference_digest(preference_payload(current)) != expected_digest
        ):
            raise ShellPreferencesError("preferences changed after preview")
        if manager.load().warning == "settings_invalid_using_safe_defaults":
            raise ShellPreferencesError(
                "repair invalid launcher settings before changing preferences"
            )
        selected = parse_preferences(preference_bytes(payload), current=current)
        if (
            selected["endpoint_port"] != current.endpoint_port
            and not probe_port(selected["endpoint_port"])["available"]
        ):
            raise ShellPortUnavailable("requested loopback port is already occupied")
        notifications = NotificationPreferences.from_payload(selected["notifications"])
        revision = current.revision + 1
        mode_changed = selected["interface_mode"] != current.interface_mode
        notification_changed = notifications != current.notifications
        mode_receipt = (
            InterfaceModeChange(
                revision=revision,
                recorded_at_utc=datetime.now(UTC).isoformat(),
                from_mode=current.interface_mode,
                to_mode=selected["interface_mode"],
                changed=mode_changed,
                source=source,
            )
            if mode_changed
            else current.interface_mode_change
        )
        notification_receipt = (
            {
                "schema_version": 1,
                "revision": revision,
                "recorded_at_utc": datetime.now(UTC).isoformat(),
                "source": source,
                "previous_sha256": current.notifications.digest(),
                "sha256": notifications.digest(),
                "changed": True,
            }
            if notification_changed
            else current.notifications_change
        )
        return replace(
            current,
            **{key: selected[key] for key in PREFERENCE_FIELDS - {"notifications"}},
            notifications=notifications,
            notifications_change=notification_receipt,
            interface_mode_change=mode_receipt,
            revision=revision,
            schema_version=max(
                current.schema_version, 4 if notification_receipt else 3 if mode_receipt else 2
            ),
            last_good_port=(
                current.endpoint_port
                if selected["endpoint_port"] != current.endpoint_port
                else current.last_good_port
            ),
            restart_required=current.restart_required
            or selected["endpoint_port"] != current.endpoint_port,
        )

    def startup(candidate):
        # mutate has persisted candidate by this point. The before value is captured
        # under the same lock by change below, not inferred from the new document.
        if candidate.login_startup != previous_startup[0]:
            if os.name != "nt" or not bool(getattr(sys, "frozen", False)):
                raise ShellPreferencesError("login startup requires installed Windows")
            try:
                configure_login_startup(candidate.login_startup)
            except Exception:
                configure_login_startup(previous_startup[0])
                raise

    previous_startup = []

    def locked_change(current):
        previous_startup.append(current.login_startup)
        return change(current)

    return manager.mutate(locked_change, expected_revision=expected_revision, post_commit=startup)
