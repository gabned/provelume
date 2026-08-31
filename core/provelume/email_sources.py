from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from .domain import Source, as_record
from .email_contract import (
    EMAIL_ADAPTER_ID,
    EMAIL_ADAPTER_VERSION,
    EMAIL_CONTRACT_SCHEMA_VERSION,
    EMAIL_ERROR_CODES,
    EMAIL_PROFILE_FORMATS,
    EMAIL_SOURCE_STATES,
    EMAIL_SUPPORTED_PROFILES,
    EMAIL_UNSUPPORTED_PROFILES,
    EmailContractError,
    EmailLimits,
    EmailSourceConfig,
    capability_report,
    mailbox_format_for_profile,
)
from .paths import portable_config_path
from .scheduler_model import SchedulerError, normalise_schedule, schedule_payload
from .storage import InstanceStore, utc_now

EMAIL_SOURCE_LIFECYCLE_STATES = ("active", "removed")
EMAIL_SOURCE_SCHEDULE_MODES = ("manual", "interval")
MAX_EMAIL_SOURCE_NAME_CHARS = 120
MAX_EMAIL_SOURCE_PATH_CHARS = 4096
_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")


class EmailSourceError(ValueError):
    """A path-free local email Source configuration failure."""

    def __init__(self, message: str, *, code: str = "email_internal_error"):
        if code not in EMAIL_ERROR_CODES:
            raise ValueError("email Source error code is outside the closed registry")
        super().__init__(message)
        self.code = code


class EmailSourceNotFound(EmailSourceError):
    def __init__(self, source_id: str):
        del source_id
        super().__init__(
            "email Source not found",
            code="email_source_missing",
        )


def _normalise_instant(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise EmailSourceError(f"invalid email Source {label}")
    try:
        selected = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EmailSourceError(f"invalid email Source {label}") from exc
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise EmailSourceError(f"invalid email Source {label}")
    return selected.astimezone(UTC).isoformat()


def _normalise_schedule(value: Any) -> dict[str, Any]:
    try:
        selected = normalise_schedule(value)
    except SchedulerError as exc:
        raise EmailSourceError("invalid email Source schedule") from exc
    if selected["mode"] not in EMAIL_SOURCE_SCHEDULE_MODES:
        raise EmailSourceError("email Sources support manual or interval schedules only")
    return selected


def _normalise_config(source_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(source_id, str) or _SOURCE_ID.fullmatch(source_id) is None:
        raise EmailSourceNotFound(str(source_id))
    expected = {
        "schema_version",
        "mailbox_format",
        "profile",
        "path",
        "state",
        "lifecycle_state",
        "schedule",
        "adapter_id",
        "adapter_version",
        "created_at",
        "updated_at",
        "removed_at",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise EmailSourceError("email Source configuration fields are incomplete")
    profile = value.get("profile")
    if not isinstance(profile, str):
        raise EmailSourceError(
            "email Source profile is unsupported",
            code="email_profile_unsupported",
        )
    try:
        mailbox_format = mailbox_format_for_profile(profile)
    except EmailContractError as exc:
        raise EmailSourceError(str(exc), code=exc.code) from exc
    if value.get("mailbox_format") != mailbox_format:
        raise EmailSourceError(
            "email Source format does not match its profile",
            code="email_profile_unsupported",
        )
    state = value.get("state")
    lifecycle_state = value.get("lifecycle_state")
    if (
        value.get("schema_version") != EMAIL_CONTRACT_SCHEMA_VERSION
        or state not in EMAIL_SOURCE_STATES
        or lifecycle_state not in EMAIL_SOURCE_LIFECYCLE_STATES
        or value.get("adapter_id") != EMAIL_ADAPTER_ID
        or value.get("adapter_version") != EMAIL_ADAPTER_VERSION
    ):
        raise EmailSourceError("email Source configuration identity is invalid")
    configured_path = value.get("path")
    if (
        not isinstance(configured_path, str)
        or not configured_path
        or len(configured_path) > MAX_EMAIL_SOURCE_PATH_CHARS
        or "\x00" in configured_path
    ):
        raise EmailSourceError(
            "email Source path is invalid",
            code="email_source_unsafe",
        )
    created_at = _normalise_instant(value.get("created_at"), "creation time")
    updated_at = _normalise_instant(value.get("updated_at"), "update time")
    removed_value = value.get("removed_at")
    removed_at = (
        None
        if removed_value is None
        else _normalise_instant(removed_value, "removal time")
    )
    if updated_at < created_at:
        raise EmailSourceError("email Source update precedes its creation")
    if lifecycle_state == "active":
        if removed_at is not None:
            raise EmailSourceError("active email Source has a removal time")
    elif removed_at is None or state != "disabled" or removed_at < created_at:
        raise EmailSourceError("removed email Source tombstone is invalid")
    return {
        "schema_version": EMAIL_CONTRACT_SCHEMA_VERSION,
        "mailbox_format": mailbox_format,
        "profile": profile,
        "path": configured_path,
        "state": state,
        "lifecycle_state": lifecycle_state,
        "schedule": _normalise_schedule(value.get("schedule")),
        "adapter_id": EMAIL_ADAPTER_ID,
        "adapter_version": EMAIL_ADAPTER_VERSION,
        "created_at": created_at,
        "updated_at": updated_at,
        "removed_at": removed_at,
    }


class EmailSourceManager:
    """Configure explicit local email Sources without observing or ingesting them.

    Mutating callers hold the Instance lifecycle lock. This manager never creates a
    scheduler policy, enumerates a mailbox, starts intake, opens a socket, or removes
    canonical data. A removed Source remains a durable configuration tombstone.
    """

    def __init__(self, store: InstanceStore):
        self.store = store

    @staticmethod
    def _absolute_lexical_path(value: Path) -> Path:
        """Make a path absolute without following a Source-controlled link."""

        return Path(os.path.abspath(os.fspath(value)))

    def _validate_instance_overlap(self, candidate: Path) -> None:
        instance_root = self.store.paths.root.resolve()
        try:
            candidate.relative_to(instance_root)
        except ValueError:
            pass
        else:
            raise EmailSourceError(
                "email Source cannot overlap the Instance root",
                code="email_source_unsafe",
            )
        try:
            instance_root.relative_to(candidate)
        except ValueError:
            return
        raise EmailSourceError(
            "email Source cannot contain the Instance root",
            code="email_source_unsafe",
        )

    @staticmethod
    def _validate_existing_path_components(candidate: Path) -> None:
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        for component in (*reversed(candidate.parents), candidate):
            try:
                value = os.lstat(component)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise EmailSourceError(
                    "email Source path cannot be inspected safely",
                    code="email_source_unsafe",
                ) from exc
            file_attributes = int(getattr(value, "st_file_attributes", 0))
            if stat.S_ISLNK(value.st_mode) or file_attributes & reparse_point:
                raise EmailSourceError(
                    "email Source path cannot contain a link or reparse point",
                    code="email_source_unsafe",
                )

    @staticmethod
    def _name(value: str) -> str:
        if not isinstance(value, str):
            raise EmailSourceError("email Source name must be text")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise EmailSourceError("email Source name contains a control character")
        selected = " ".join(value.strip().split())
        if not selected or len(selected) > MAX_EMAIL_SOURCE_NAME_CHARS:
            raise EmailSourceError(
                "email Source name must contain 1 to 120 characters"
            )
        return selected

    @staticmethod
    def _remove_exact_created_record(path: Path, expected: bytes) -> bool:
        """Compensate only a byte-exact regular record created by this call."""

        try:
            if (
                not path.is_file()
                or path.is_symlink()
                or path.read_bytes() != expected
            ):
                return False
            path.unlink()
        except OSError:
            return False
        return True

    def _selected_path(self, value: Path | str) -> Path:
        if not isinstance(value, (str, Path)):
            raise EmailSourceError(
                "email Source path is invalid",
                code="email_source_unsafe",
            )
        raw = str(value)
        text = raw.strip()
        if (
            not text
            or text != raw
            or len(text) > MAX_EMAIL_SOURCE_PATH_CHARS
            or "\x00" in text
        ):
            raise EmailSourceError(
                "email Source path is invalid",
                code="email_source_unsafe",
            )
        unresolved = Path(text).expanduser()
        if not unresolved.is_absolute():
            unresolved = self.store.paths.root / unresolved
        candidate = self._absolute_lexical_path(unresolved)
        self._validate_instance_overlap(candidate)
        self._validate_existing_path_components(candidate)
        return candidate

    def _configured_path_without_observation(self, configured: str) -> Path:
        selected = Path(configured).expanduser()
        if not selected.is_absolute():
            selected = self.store.paths.root / selected
        candidate = self._absolute_lexical_path(selected)
        self._validate_instance_overlap(candidate)
        return candidate

    def _configured(self, source_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(source_id, str) or _SOURCE_ID.fullmatch(source_id) is None:
            raise EmailSourceNotFound(str(source_id))
        source = self.store.read_canonical("sources", source_id)
        if source is None or source.get("kind") != "email":
            raise EmailSourceNotFound(source_id)
        configured = self.store.read_config().get("email_sources")
        item = configured.get(source_id) if isinstance(configured, Mapping) else None
        if not isinstance(item, Mapping):
            raise EmailSourceError("email Source configuration is missing")
        normalised = _normalise_config(source_id, item)
        if (
            set(source) != {"id", "kind", "name", "created_at"}
            or source.get("id") != source_id
            or source.get("created_at") != normalised["created_at"]
            or self._name(source.get("name")) != source.get("name")
        ):
            raise EmailSourceError("canonical email Source identity is inconsistent")
        return source, normalised

    def _source_config(
        self,
        source_id: str,
        item: Mapping[str, Any],
        *,
        validate_local_path: bool = True,
    ) -> EmailSourceConfig:
        if validate_local_path:
            selected_path = self._selected_path(str(item["path"]))
        else:
            selected_path = self._configured_path_without_observation(
                str(item["path"])
            )
        try:
            source_config = EmailSourceConfig(
                source_id=source_id,
                mailbox_format=str(item["mailbox_format"]),
                profile=str(item["profile"]),
                path=selected_path,
                state=str(item["state"]),
                adapter_id=str(item["adapter_id"]),
                adapter_version=str(item["adapter_version"]),
            )
        except EmailContractError as exc:
            raise EmailSourceError(str(exc), code=exc.code) from exc
        return source_config

    def source_config(
        self,
        source_id: str,
        *,
        require_enabled: bool = False,
    ) -> EmailSourceConfig:
        """Return the path-bearing local adapter configuration for explicit work."""

        _source, item = self._configured(source_id)
        self._require_active(item)
        if require_enabled:
            if item["state"] == "disabled":
                raise EmailSourceError(
                    "email Source is disabled",
                    code="email_source_disabled",
                )
            if item["state"] == "paused":
                raise EmailSourceError(
                    "email Source is paused",
                    code="email_source_paused",
                )
        return self._source_config(source_id, item, validate_local_path=True)

    def create(
        self,
        *,
        name: str,
        path: Path | str,
        profile: str,
    ) -> dict[str, Any]:
        selected_name = self._name(name)
        if profile in EMAIL_UNSUPPORTED_PROFILES or profile not in EMAIL_SUPPORTED_PROFILES:
            raise EmailSourceError(
                "email Source profile is unsupported",
                code="email_profile_unsupported",
            )
        try:
            mailbox_format = mailbox_format_for_profile(profile)
        except EmailContractError as exc:
            raise EmailSourceError(str(exc), code=exc.code) from exc
        selected_path = self._selected_path(path)
        now = utc_now()
        source_id = f"src_{uuid4().hex}"
        record = {
            "schema_version": EMAIL_CONTRACT_SCHEMA_VERSION,
            "mailbox_format": mailbox_format,
            "profile": profile,
            "path": portable_config_path(self.store.paths.root, selected_path),
            "state": "disabled",
            "lifecycle_state": "active",
            "schedule": schedule_payload(mode="manual", timezone="UTC"),
            "adapter_id": EMAIL_ADAPTER_ID,
            "adapter_version": EMAIL_ADAPTER_VERSION,
            "created_at": now,
            "updated_at": now,
            "removed_at": None,
        }
        selected = _normalise_config(source_id, record)
        config = self.store.read_config()
        sources = config.setdefault("email_sources", {})
        if not isinstance(sources, dict):
            raise EmailSourceError("Instance email Sources configuration must be an object")
        if source_id in sources or self.store.read_canonical("sources", source_id) is not None:
            raise EmailSourceError("email Source identity already exists")

        source = Source(
            id=source_id,
            kind="email",
            name=selected_name,
            created_at=now,
        )
        sources[source_id] = selected
        previous_config = self.store.paths.config.read_bytes()
        candidate_config = yaml.safe_dump(config, sort_keys=False).encode("utf-8")
        source_path = self.store.paths.canonical_dir("sources") / f"{source_id}.json"
        expected_source = (
            json.dumps(as_record(source), indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        try:
            self.store.write_source(source)
        except Exception:
            self._remove_exact_created_record(source_path, expected_source)
            raise
        try:
            self.store.write_config(config)
        except Exception:
            # The strong multi-file transaction belongs to intake promotion.  Source
            # registration instead compensates its just-created immutable record.  We
            # only remove bytes whose exact identity we created and restore config only
            # when it contains our exact candidate, never an unrelated concurrent edit.
            try:
                current_config = self.store.paths.config.read_bytes()
                if current_config == candidate_config:
                    self.store._atomic_bytes(
                        self.store.paths.config,
                        previous_config,
                    )
                    current_config = previous_config
                if current_config == previous_config:
                    self._remove_exact_created_record(
                        source_path,
                        expected_source,
                    )
            except OSError:
                pass
            raise
        return self.local_view(source_id)

    def _write_config_item(self, source_id: str, value: Mapping[str, Any]) -> None:
        selected = _normalise_config(source_id, value)
        config = self.store.read_config()
        sources = config.get("email_sources")
        if not isinstance(sources, dict) or not isinstance(sources.get(source_id), dict):
            raise EmailSourceError("email Source configuration is missing")
        sources[source_id] = selected
        self.store.write_config(config)

    @staticmethod
    def _require_active(item: Mapping[str, Any]) -> None:
        if item.get("lifecycle_state") != "active":
            raise EmailSourceError(
                "email Source was removed",
                code="email_source_removed",
            )

    def set_state(self, source_id: str, state: str) -> dict[str, Any]:
        _source, item = self._configured(source_id)
        self._require_active(item)
        if state not in EMAIL_SOURCE_STATES:
            raise EmailSourceError("email Source state is invalid")
        if item["state"] == state:
            return self.public_view(source_id)
        self._write_config_item(
            source_id,
            {**item, "state": state, "updated_at": utc_now()},
        )
        return self.public_view(source_id)

    def enable(self, source_id: str) -> dict[str, Any]:
        return self.set_state(source_id, "enabled")

    def pause(self, source_id: str) -> dict[str, Any]:
        return self.set_state(source_id, "paused")

    def disable(self, source_id: str) -> dict[str, Any]:
        return self.set_state(source_id, "disabled")

    def configure_schedule(
        self,
        source_id: str,
        *,
        mode: str,
        interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        _source, item = self._configured(source_id)
        self._require_active(item)
        if mode not in EMAIL_SOURCE_SCHEDULE_MODES:
            raise EmailSourceError(
                "email Sources support manual or interval schedules only"
            )
        try:
            schedule = schedule_payload(
                mode=mode,
                timezone="UTC",
                interval_seconds=interval_seconds,
            )
        except SchedulerError as exc:
            raise EmailSourceError("invalid email Source schedule") from exc
        self._write_config_item(
            source_id,
            {**item, "schedule": schedule, "updated_at": utc_now()},
        )
        return self.public_view(source_id)

    def remove(self, source_id: str) -> dict[str, Any]:
        _source, item = self._configured(source_id)
        if item["lifecycle_state"] == "removed":
            return self.public_view(source_id)
        now = utc_now()
        self._write_config_item(
            source_id,
            {
                **item,
                "state": "disabled",
                "lifecycle_state": "removed",
                "removed_at": now,
                "updated_at": now,
            },
        )
        return self.public_view(source_id)

    def public_view(self, source_id: str) -> dict[str, Any]:
        source, item = self._configured(source_id)
        source_config = self._source_config(
            source_id,
            item,
            validate_local_path=False,
        )
        return {
            **source_config.public_record(),
            "id": source_id,
            "name": source["name"],
            "kind": "email",
            "lifecycle_state": item["lifecycle_state"],
            "schedule": dict(item["schedule"]),
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "removed_at": item["removed_at"],
            "autodiscovery": False,
            "automatic_activity": False,
        }

    def local_view(self, source_id: str) -> dict[str, Any]:
        result = self.public_view(source_id)
        _source, item = self._configured(source_id)
        source_config = self._source_config(
            source_id,
            item,
            validate_local_path=False,
        )
        return {**result, "path": str(source_config.path)}

    get_public = public_view
    get_local = local_view

    def list_public(self, *, include_removed: bool = True) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        configured = self.store.read_config().get("email_sources")
        if not isinstance(configured, Mapping):
            return result
        for source_id in configured:
            view = self.public_view(str(source_id))
            if include_removed or view["lifecycle_state"] == "active":
                result.append(view)
        return sorted(result, key=lambda item: (str(item["name"]).casefold(), item["id"]))

    def list_local(self, *, include_removed: bool = True) -> list[dict[str, Any]]:
        return [
            self.local_view(str(item["id"]))
            for item in self.list_public(include_removed=include_removed)
        ]

    def capability(
        self,
        source_id: str | None = None,
        *,
        local: bool = False,
        limits: EmailLimits | None = None,
    ) -> dict[str, Any]:
        if source_id is None:
            profiles = [
                capability_report(mailbox_format, profile, limits=limits).as_record()
                for profile, mailbox_format in EMAIL_PROFILE_FORMATS.items()
            ]
            profiles.extend(
                capability_report(profile, profile, limits=limits).as_record()
                for profile in EMAIL_UNSUPPORTED_PROFILES
            )
            return {
                "schema_version": EMAIL_CONTRACT_SCHEMA_VERSION,
                "available": any(item["available"] for item in profiles),
                "profiles": profiles,
                "network_access": "none",
                "runtime_downloads": False,
                "remote_fallback": False,
                "autodiscovery": False,
                "automatic_activity": False,
            }

        _source, item = self._configured(source_id)
        source_config = self._source_config(source_id, item, validate_local_path=False)
        adapter = capability_report(
            source_config.mailbox_format,
            source_config.profile,
            limits=limits,
        )
        probe_record: dict[str, Any] | None = None
        if item["lifecycle_state"] == "removed":
            available = False
            state = "source-removed"
            reason = "email_source_removed"
        else:
            if source_config.state == "disabled":
                available = False
                state = "source-disabled"
                reason = "email_source_disabled"
            elif source_config.state == "paused":
                available = False
                state = "source-paused"
                reason = "email_source_paused"
            elif not adapter.available:
                available = False
                state = "adapter-unavailable"
                reason = adapter.reason
            else:
                try:
                    configured_for_probe = self._source_config(
                        source_id,
                        item,
                        validate_local_path=True,
                    )
                except EmailSourceError as exc:
                    available = False
                    state = "source-unavailable"
                    reason = exc.code
                else:
                    from .email_containers import adapter_for_profile

                    probe = adapter_for_profile(configured_for_probe).probe()
                    probe_record = probe.as_record()
                    if not probe.available:
                        available = False
                        state = "source-unavailable"
                        reason = probe.reason
                    else:
                        available = True
                        state = "ready"
                        reason = None
        view = self.local_view(source_id) if local else self.public_view(source_id)
        return {
            "schema_version": EMAIL_CONTRACT_SCHEMA_VERSION,
            "available": available,
            "state": state,
            "reason": reason,
            "source": view,
            "adapter": adapter.as_record(),
            "probe": probe_record,
            "network_access": "none",
            "runtime_downloads": False,
            "remote_fallback": False,
            "autodiscovery": False,
            "automatic_activity": False,
        }


__all__ = [
    "EMAIL_SOURCE_LIFECYCLE_STATES",
    "EMAIL_SOURCE_SCHEDULE_MODES",
    "EmailSourceError",
    "EmailSourceManager",
    "EmailSourceNotFound",
    "MAX_EMAIL_SOURCE_NAME_CHARS",
    "MAX_EMAIL_SOURCE_PATH_CHARS",
]
