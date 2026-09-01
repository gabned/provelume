from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .connectors import ConnectorError, ConnectorManager
from .paths import portable_config_path
from .scheduler_model import SchedulerError, normalise_schedule, schedule_payload
from .storage import InstanceStore, utc_now
from .transcript_contract import (
    TRANSCRIPT_ADAPTER_ID,
    TRANSCRIPT_ADAPTER_VERSION,
    TRANSCRIPT_CONTRACT_SCHEMA_VERSION,
    TRANSCRIPT_PROFILE_EXTENSIONS,
    TRANSCRIPT_SELECTION_KINDS,
    TRANSCRIPT_SOURCE_SCHEDULE_MODES,
    TRANSCRIPT_SOURCE_STATES,
    TRANSCRIPT_SUPPORTED_PROFILES,
    TranscriptContractError,
    TranscriptSourceConfig,
    capability_report,
)

TRANSCRIPT_DEFINITION_KEY = "local-transcript"
TRANSCRIPT_DEFINITION_ID = f"connector_definition_{TRANSCRIPT_DEFINITION_KEY}"
MAX_TRANSCRIPT_SOURCE_NAME_CHARS = 120
MAX_TRANSCRIPT_SOURCE_PATH_CHARS = 4096
_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")
_INSTANCE_ID = re.compile(r"connector_instance_[0-9a-f]{32}\Z")


class TranscriptSourceError(TranscriptContractError):
    pass


class TranscriptSourceNotFound(TranscriptSourceError):
    def __init__(self) -> None:
        super().__init__("transcript_source_missing", "transcript Source not found")


def transcript_definition_manifest() -> dict[str, Any]:
    return {
        "adapter_key": TRANSCRIPT_DEFINITION_KEY,
        "adapter_version": TRANSCRIPT_ADAPTER_VERSION,
        "display_name": "Local transcript adapter",
        "provider": "provider-neutral-local",
        "conformance_profile": "provelume.connector.v1",
        "adapter_protocol_version": 1,
        "capabilities": [
            "manual_read",
            "scheduled_read",
            "source_selection",
            "transcript_read",
        ],
        "authorization_modes": ["none"],
        "source_kinds": ["transcript"],
        "data_categories": [
            "transcript.bytes",
            "transcript.cue",
            "transcript.metadata",
        ],
        "multi_instance": True,
        "network_access": "none",
    }


def _instant(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TranscriptSourceError(
            "transcript_internal_error", f"invalid transcript Source {label}"
        )
    try:
        selected = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TranscriptSourceError(
            "transcript_internal_error", f"invalid transcript Source {label}"
        ) from exc
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise TranscriptSourceError(
            "transcript_internal_error", f"invalid transcript Source {label}"
        )
    return selected.astimezone(UTC).isoformat()


def _schedule(value: Any) -> dict[str, Any]:
    try:
        selected = normalise_schedule(value)
    except SchedulerError as exc:
        raise TranscriptSourceError(
            "transcript_internal_error", "invalid transcript Source schedule"
        ) from exc
    if selected["mode"] not in TRANSCRIPT_SOURCE_SCHEDULE_MODES:
        raise TranscriptSourceError(
            "transcript_internal_error",
            "transcript Sources support manual or interval schedules only",
        )
    return selected


def _normalise_config(source_id: str, value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "connector_instance_id",
        "profile",
        "selection_kind",
        "path",
        "selection_sha256",
        "state",
        "lifecycle_state",
        "schedule",
        "adapter_id",
        "adapter_version",
        "config_revision",
        "created_at",
        "updated_at",
        "removed_at",
    }
    if _SOURCE_ID.fullmatch(source_id) is None:
        raise TranscriptSourceNotFound()
    if not isinstance(value, Mapping) or set(value) != expected:
        raise TranscriptSourceError(
            "transcript_internal_error", "transcript Source configuration is incomplete"
        )
    instance_id = value.get("connector_instance_id")
    profile = value.get("profile")
    selection_kind = value.get("selection_kind")
    configured_path = value.get("path")
    selection_sha256 = value.get("selection_sha256")
    state = value.get("state")
    lifecycle = value.get("lifecycle_state")
    revision = value.get("config_revision")
    if (
        value.get("schema_version") != TRANSCRIPT_CONTRACT_SCHEMA_VERSION
        or not isinstance(instance_id, str)
        or _INSTANCE_ID.fullmatch(instance_id) is None
        or profile not in TRANSCRIPT_SUPPORTED_PROFILES
        or selection_kind not in TRANSCRIPT_SELECTION_KINDS
        or not isinstance(configured_path, str)
        or not configured_path
        or len(configured_path) > MAX_TRANSCRIPT_SOURCE_PATH_CHARS
        or "\x00" in configured_path
        or not isinstance(selection_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", selection_sha256) is None
        or state not in TRANSCRIPT_SOURCE_STATES
        or lifecycle not in {"active", "removed"}
        or type(revision) is not int
        or revision < 1
        or value.get("adapter_id") != TRANSCRIPT_ADAPTER_ID
        or value.get("adapter_version") != TRANSCRIPT_ADAPTER_VERSION
    ):
        raise TranscriptSourceError(
            "transcript_internal_error", "transcript Source configuration is invalid"
        )
    created_at = _instant(value.get("created_at"), "creation time")
    updated_at = _instant(value.get("updated_at"), "update time")
    removed_at = (
        None
        if value.get("removed_at") is None
        else _instant(value.get("removed_at"), "removal time")
    )
    if updated_at < created_at:
        raise TranscriptSourceError(
            "transcript_internal_error", "transcript Source update precedes creation"
        )
    if lifecycle == "removed":
        if removed_at is None or state != "disabled":
            raise TranscriptSourceError(
                "transcript_internal_error", "removed transcript Source tombstone is invalid"
            )
    elif removed_at is not None:
        raise TranscriptSourceError(
            "transcript_internal_error", "active transcript Source has a removal time"
        )
    return {
        "schema_version": TRANSCRIPT_CONTRACT_SCHEMA_VERSION,
        "connector_instance_id": instance_id,
        "profile": profile,
        "selection_kind": selection_kind,
        "path": configured_path,
        "selection_sha256": selection_sha256,
        "state": state,
        "lifecycle_state": lifecycle,
        "schedule": _schedule(value.get("schedule")),
        "adapter_id": TRANSCRIPT_ADAPTER_ID,
        "adapter_version": TRANSCRIPT_ADAPTER_VERSION,
        "config_revision": revision,
        "created_at": created_at,
        "updated_at": updated_at,
        "removed_at": removed_at,
    }


class TranscriptSourceManager:
    """Explicit local transcript Source configuration; construction is inert."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.connectors = ConnectorManager(store)

    @staticmethod
    def _name(value: str) -> str:
        if not isinstance(value, str):
            raise TranscriptSourceError(
                "transcript_internal_error", "transcript Source name must be text"
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise TranscriptSourceError(
                "transcript_internal_error", "transcript Source name contains control data"
            )
        selected = " ".join(value.strip().split())
        if not selected or len(selected) > MAX_TRANSCRIPT_SOURCE_NAME_CHARS:
            raise TranscriptSourceError(
                "transcript_internal_error",
                "transcript Source name must contain 1 to 120 characters",
            )
        return selected

    @staticmethod
    def _absolute_lexical(value: Path) -> Path:
        return Path(os.path.abspath(os.fspath(value)))

    def _validate_overlap(self, candidate: Path) -> None:
        instance = self.store.paths.root.resolve()
        try:
            candidate.relative_to(instance)
        except ValueError:
            pass
        else:
            raise TranscriptSourceError(
                "transcript_source_unsafe", "transcript Source overlaps the Instance"
            )
        try:
            instance.relative_to(candidate)
        except ValueError:
            return
        raise TranscriptSourceError(
            "transcript_source_unsafe", "transcript Source contains the Instance"
        )

    @staticmethod
    def _validate_components(candidate: Path) -> os.stat_result:
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        for component in (*reversed(candidate.parents), candidate):
            try:
                value = os.lstat(component)
            except FileNotFoundError as exc:
                raise TranscriptSourceError(
                    "transcript_source_missing", "transcript Source selection is missing"
                ) from exc
            except OSError as exc:
                raise TranscriptSourceError(
                    "transcript_source_unsafe", "transcript Source cannot be inspected safely"
                ) from exc
            attributes = int(getattr(value, "st_file_attributes", 0))
            if stat.S_ISLNK(value.st_mode) or attributes & reparse:
                raise TranscriptSourceError(
                    "transcript_source_unsafe",
                    "transcript Source cannot contain a link or reparse point",
                )
        return os.lstat(candidate)

    def selected_path(
        self,
        value: Path | str,
        *,
        selection_kind: str,
        profile: str,
        observe: bool = True,
    ) -> Path:
        if selection_kind not in TRANSCRIPT_SELECTION_KINDS:
            raise TranscriptSourceError(
                "transcript_source_unsafe", "transcript selection kind is unsupported"
            )
        if profile not in TRANSCRIPT_SUPPORTED_PROFILES:
            raise TranscriptSourceError(
                "transcript_profile_unsupported", "transcript profile is unsupported"
            )
        raw = os.fspath(value) if isinstance(value, (str, Path)) else ""
        if (
            not raw
            or raw != raw.strip()
            or len(raw) > MAX_TRANSCRIPT_SOURCE_PATH_CHARS
            or "\x00" in raw
            or raw.startswith(("//", "\\\\"))
        ):
            raise TranscriptSourceError(
                "transcript_source_unsafe", "transcript Source path is invalid"
            )
        unresolved = Path(raw).expanduser()
        if not unresolved.is_absolute():
            unresolved = self.store.paths.root / unresolved
        candidate = self._absolute_lexical(unresolved)
        self._validate_overlap(candidate)
        if observe:
            selected_stat = self._validate_components(candidate)
            expected = stat.S_ISREG if selection_kind == "file" else stat.S_ISDIR
            if not expected(selected_stat.st_mode):
                raise TranscriptSourceError(
                    "transcript_input_non_regular",
                    "transcript Source selection has the wrong type",
                )
            if selection_kind == "file":
                if selected_stat.st_nlink != 1:
                    raise TranscriptSourceError(
                        "transcript_source_unsafe",
                        "transcript Source file must not be a hard link",
                    )
                if candidate.suffix.casefold() not in TRANSCRIPT_PROFILE_EXTENSIONS[profile]:
                    raise TranscriptSourceError(
                        "transcript_profile_mismatch",
                        "transcript Source file does not match the selected profile",
                    )
        return candidate

    @staticmethod
    def _selection_digest(path: Path, selection_kind: str, profile: str) -> str:
        payload = json.dumps(
            {
                "path": os.path.normcase(os.fspath(path)),
                "selection_kind": selection_kind,
                "profile": profile,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def ensure_definition(self) -> dict[str, Any]:
        return self.connectors.register_definition(transcript_definition_manifest())

    def _configured(self, source_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(source_id, str) or _SOURCE_ID.fullmatch(source_id) is None:
            raise TranscriptSourceNotFound()
        configured = self.store.read_config().get("transcript_sources")
        item = configured.get(source_id) if isinstance(configured, Mapping) else None
        if not isinstance(item, Mapping):
            raise TranscriptSourceNotFound()
        selected = _normalise_config(source_id, item)
        connector_source = self.connectors.get_source(
            str(selected["connector_instance_id"]), source_id
        )
        connector_instance = self.connectors.get_instance(
            str(selected["connector_instance_id"])
        )
        if (
            connector_source is None
            or connector_instance is None
            or connector_source.get("source_kind") != "transcript"
            or connector_source.get("external_id")
            != f"selection:sha256:{selected['selection_sha256']}"
            or connector_instance.get("definition_id") != TRANSCRIPT_DEFINITION_ID
        ):
            raise TranscriptSourceError(
                "transcript_internal_error", "transcript connector identity is inconsistent"
            )
        return connector_source, selected

    def source_config(
        self, source_id: str, *, require_enabled: bool = False
    ) -> TranscriptSourceConfig:
        _source, item = self._configured(source_id)
        if item["lifecycle_state"] == "removed":
            raise TranscriptSourceError(
                "transcript_source_removed", "transcript Source was removed"
            )
        if require_enabled and item["state"] != "enabled":
            code = (
                "transcript_source_paused"
                if item["state"] == "paused"
                else "transcript_source_disabled"
            )
            raise TranscriptSourceError(code, "transcript Source is not enabled")
        path = self.selected_path(
            str(item["path"]),
            selection_kind=str(item["selection_kind"]),
            profile=str(item["profile"]),
        )
        return TranscriptSourceConfig(
            source_id=source_id,
            connector_instance_id=str(item["connector_instance_id"]),
            profile=str(item["profile"]),
            selection_kind=str(item["selection_kind"]),
            path=path,
            state=str(item["state"]),
            config_revision=int(item["config_revision"]),
        )

    def _write_item(self, source_id: str, value: Mapping[str, Any]) -> None:
        selected = _normalise_config(source_id, value)
        config = self.store.read_config()
        sources = config.get("transcript_sources")
        if not isinstance(sources, dict) or source_id not in sources:
            raise TranscriptSourceNotFound()
        sources[source_id] = selected
        self.store.write_config(config)

    def create(
        self,
        *,
        name: str,
        path: Path | str,
        profile: str,
        selection_kind: str,
    ) -> dict[str, Any]:
        selected_name = self._name(name)
        selected_path = self.selected_path(
            path, selection_kind=selection_kind, profile=profile
        )
        digest = self._selection_digest(selected_path, selection_kind, profile)
        self.ensure_definition()
        connector = self.connectors.create_instance(
            TRANSCRIPT_DEFINITION_ID,
            name=selected_name,
            provider_identity="provider-neutral-local",
            network_mode="disabled",
            allowed_origins=(),
            authorization_mode="none",
            scopes=(),
            credential_reference=None,
            enabled=False,
        )
        instance_id = str(connector["id"])
        source: dict[str, Any] | None = None
        try:
            source = self.connectors.add_source(
                instance_id,
                name=selected_name,
                source_kind="transcript",
                external_id=f"selection:sha256:{digest}",
                enabled=False,
            )
            source_id = str(source["id"])
            now = utc_now()
            record = _normalise_config(
                source_id,
                {
                    "schema_version": TRANSCRIPT_CONTRACT_SCHEMA_VERSION,
                    "connector_instance_id": instance_id,
                    "profile": profile,
                    "selection_kind": selection_kind,
                    "path": portable_config_path(self.store.paths.root, selected_path),
                    "selection_sha256": digest,
                    "state": "disabled",
                    "lifecycle_state": "active",
                    "schedule": schedule_payload(mode="manual", timezone="UTC"),
                    "adapter_id": TRANSCRIPT_ADAPTER_ID,
                    "adapter_version": TRANSCRIPT_ADAPTER_VERSION,
                    "config_revision": 1,
                    "created_at": now,
                    "updated_at": now,
                    "removed_at": None,
                },
            )
            config = self.store.read_config()
            sources = config.setdefault("transcript_sources", {})
            if not isinstance(sources, dict):
                raise TranscriptSourceError(
                    "transcript_internal_error",
                    "Instance transcript Sources configuration must be an object",
                )
            sources[source_id] = record
            self.store.write_config(config)
        except Exception:
            if source is not None:
                with suppress(ConnectorError):
                    self.connectors.remove_source(instance_id, str(source["id"]))
            with suppress(ConnectorError):
                self.connectors.remove_instance(instance_id)
            raise
        return self.local_view(source_id)

    def set_state(self, source_id: str, state: str) -> dict[str, Any]:
        _source, item = self._configured(source_id)
        if item["lifecycle_state"] != "active":
            raise TranscriptSourceError(
                "transcript_source_removed", "transcript Source was removed"
            )
        if state not in TRANSCRIPT_SOURCE_STATES:
            raise TranscriptSourceError(
                "transcript_internal_error", "transcript Source state is invalid"
            )
        if item["state"] == state:
            return self.public_view(source_id)
        instance_id = str(item["connector_instance_id"])
        if state == "enabled":
            self.source_config(source_id)
            self.connectors.enable_source(instance_id, source_id)
            self.connectors.enable_instance(instance_id)
        else:
            self.connectors.disable_instance(instance_id)
            self.connectors.disable_source(instance_id, source_id)
        self._write_item(source_id, {**item, "state": state, "updated_at": utc_now()})
        return self.public_view(source_id)

    def reconfigure(
        self,
        source_id: str,
        *,
        path: Path | str,
        profile: str,
        selection_kind: str,
    ) -> dict[str, Any]:
        _source, item = self._configured(source_id)
        if item["lifecycle_state"] != "active":
            raise TranscriptSourceError(
                "transcript_source_removed", "transcript Source was removed"
            )
        if item["state"] != "disabled":
            raise TranscriptSourceError(
                "transcript_disabled",
                "disable the transcript Source before reconfiguration",
            )
        selected_path = self.selected_path(
            path, selection_kind=selection_kind, profile=profile
        )
        digest = self._selection_digest(selected_path, selection_kind, profile)
        instance_id = str(item["connector_instance_id"])
        self.connectors.update_source(
            instance_id,
            source_id,
            external_id=f"selection:sha256:{digest}",
        )
        self._write_item(
            source_id,
            {
                **item,
                "profile": profile,
                "selection_kind": selection_kind,
                "path": portable_config_path(self.store.paths.root, selected_path),
                "selection_sha256": digest,
                "config_revision": int(item["config_revision"]) + 1,
                "updated_at": utc_now(),
            },
        )
        return self.local_view(source_id)

    def configure_schedule(
        self,
        source_id: str,
        *,
        mode: str,
        interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        _source, item = self._configured(source_id)
        if item["lifecycle_state"] != "active":
            raise TranscriptSourceError(
                "transcript_source_removed", "transcript Source was removed"
            )
        if mode not in TRANSCRIPT_SOURCE_SCHEDULE_MODES:
            raise TranscriptSourceError(
                "transcript_internal_error", "transcript Source schedule is unsupported"
            )
        try:
            selected = schedule_payload(
                mode=mode, timezone="UTC", interval_seconds=interval_seconds
            )
        except SchedulerError as exc:
            raise TranscriptSourceError(
                "transcript_internal_error", "transcript Source schedule is invalid"
            ) from exc
        self._write_item(
            source_id, {**item, "schedule": selected, "updated_at": utc_now()}
        )
        return self.public_view(source_id)

    def remove(self, source_id: str) -> dict[str, Any]:
        _source, item = self._configured(source_id)
        if item["lifecycle_state"] == "removed":
            return self.public_view(source_id)
        instance_id = str(item["connector_instance_id"])
        self.connectors.remove_source(instance_id, source_id)
        self.connectors.remove_instance(instance_id)
        now = utc_now()
        self._write_item(
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
        _source, item = self._configured(source_id)
        return {
            "schema_version": TRANSCRIPT_CONTRACT_SCHEMA_VERSION,
            "id": source_id,
            "connector_instance_id": item["connector_instance_id"],
            "kind": "transcript",
            "name": f"Transcript Source {source_id[-8:]}",
            "name_redacted": True,
            "profile": item["profile"],
            "selection_kind": item["selection_kind"],
            "selection_sha256": item["selection_sha256"],
            "state": item["state"],
            "lifecycle_state": item["lifecycle_state"],
            "schedule": dict(item["schedule"]),
            "config_revision": item["config_revision"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "removed_at": item["removed_at"],
            "explicit_selection": True,
            "recursive_discovery": False,
            "watcher": False,
            "network_access": "none",
        }

    def local_view(self, source_id: str) -> dict[str, Any]:
        connector, item = self._configured(source_id)
        path = self.selected_path(
            str(item["path"]),
            selection_kind=str(item["selection_kind"]),
            profile=str(item["profile"]),
            observe=False,
        )
        return {
            **self.public_view(source_id),
            "configured_name": connector["name"],
            "path": str(path),
        }

    def list_public(self, *, include_removed: bool = True) -> list[dict[str, Any]]:
        configured = self.store.read_config().get("transcript_sources")
        if not isinstance(configured, Mapping):
            return []
        result = [self.public_view(str(source_id)) for source_id in configured]
        if not include_removed:
            result = [item for item in result if item["lifecycle_state"] == "active"]
        return sorted(result, key=lambda item: str(item["id"]))

    def list_local(self, *, include_removed: bool = True) -> list[dict[str, Any]]:
        return [
            self.local_view(str(item["id"]))
            for item in self.list_public(include_removed=include_removed)
        ]

    def capability(self, source_id: str | None = None, *, local: bool = False) -> dict[str, Any]:
        result = capability_report()
        if source_id is None:
            return result
        _source, item = self._configured(source_id)
        view = self.local_view(source_id) if local else self.public_view(source_id)
        if item["lifecycle_state"] == "removed":
            available, state, reason = False, "source-removed", "transcript_source_removed"
        elif item["state"] != "enabled":
            available = False
            state = f"source-{item['state']}"
            reason = (
                "transcript_source_paused"
                if item["state"] == "paused"
                else "transcript_source_disabled"
            )
        else:
            try:
                self.source_config(source_id, require_enabled=True)
            except TranscriptContractError as exc:
                available, state, reason = False, "source-unavailable", exc.code
            else:
                available, state, reason = True, "ready", None
        return {**result, "available": available, "state": state, "reason": reason, "source": view}


__all__ = [
    "MAX_TRANSCRIPT_SOURCE_NAME_CHARS",
    "MAX_TRANSCRIPT_SOURCE_PATH_CHARS",
    "TRANSCRIPT_DEFINITION_ID",
    "TranscriptSourceError",
    "TranscriptSourceManager",
    "TranscriptSourceNotFound",
    "transcript_definition_manifest",
]
