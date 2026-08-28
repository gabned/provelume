from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .domain import Source
from .operations import OperationLedger
from .paths import portable_config_path, resolve_config_path
from .storage import InstanceStore

FOLDER_SETTINGS_SCHEMA_VERSION = 1
DEFAULT_INBOX_NAME = "Local Inbox"
DEFAULT_DROP_PATH = "inbox/drop"
DEFAULT_MANAGED_PATH = "inbox/items"
MAX_INBOX_NAME_CHARS = 120


class FolderSettingsError(ValueError):
    pass


class FolderOverlapError(FolderSettingsError):
    pass


class ManagedFolderRelocationRequired(FolderSettingsError):
    pass


@dataclass(frozen=True, slots=True)
class InboxFolderSettings:
    schema_version: int
    name: str
    drop_configured: str
    managed_configured: str
    drop_path: Path
    managed_path: Path


def inbox_source_id(store: InstanceStore) -> str:
    instance_id = str(store.read_config()["instance"]["id"])
    value = f"provelume:{instance_id}:local-inbox"
    return f"src_{uuid5(NAMESPACE_URL, value).hex}"


def _contains_or_equals(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _paths_overlap(left: Path, right: Path) -> bool:
    return _contains_or_equals(left, right) or _contains_or_equals(right, left)


class FolderSettingsManager:
    """Validate and persist user-selected local Inbox folders."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.operations = OperationLedger(store)

    @property
    def _reserved_directories(self) -> tuple[Path, ...]:
        return (
            self.store.paths.originals,
            self.store.paths.knowledge,
            self.store.paths.state,
            self.store.paths.indexes,
        )

    def _configured_path(self, value: str) -> Path:
        selected = value.strip()
        if not selected:
            raise FolderSettingsError("folder path cannot be empty")
        return resolve_config_path(self.store.paths.root, selected)

    def _portable_path(self, path: Path) -> str:
        root = self.store.paths.root.resolve()
        selected = path.expanduser().resolve()
        try:
            selected.relative_to(root)
        except ValueError:
            return str(selected)
        return portable_config_path(root, selected)

    @staticmethod
    def _validated_name(value: str) -> str:
        selected = " ".join(value.strip().split())
        if not selected:
            raise FolderSettingsError("Inbox name cannot be empty")
        if len(selected) > MAX_INBOX_NAME_CHARS:
            raise FolderSettingsError(
                f"Inbox name exceeds {MAX_INBOX_NAME_CHARS} characters"
            )
        if any(ord(character) < 32 for character in selected):
            raise FolderSettingsError("Inbox name contains a control character")
        return selected

    def _validate_pair(self, drop: Path, managed: Path) -> None:
        root = self.store.paths.root.resolve()
        drop = drop.resolve()
        managed = managed.resolve()
        for label, candidate in (("Drop", drop), ("managed", managed)):
            if candidate == root or _contains_or_equals(candidate, root):
                raise FolderOverlapError(
                    f"{label} folder cannot be the Instance root or contain it"
                )
            for reserved in self._reserved_directories:
                reserved = reserved.resolve()
                if _paths_overlap(candidate, reserved):
                    raise FolderOverlapError(
                        f"{label} folder overlaps reserved Instance storage"
                    )
            if candidate == self.store.paths.config.resolve():
                raise FolderOverlapError(
                    f"{label} folder cannot be the Instance configuration file"
                )
        if _paths_overlap(drop, managed):
            raise FolderOverlapError(
                "Drop and managed-copy folders must be separate and non-nested"
            )

    @staticmethod
    def _ensure_writable_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise FolderSettingsError(f"configured folder is not a directory: {path}")
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".provelume-folder-check-",
                dir=path,
                delete=False,
            ) as handle:
                temporary_name = handle.name
                handle.write(b"provelume-folder-check\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise FolderSettingsError(
                f"configured folder is not writable: {path}"
            ) from exc
        finally:
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink()
                except OSError:
                    pass

    def read(self) -> InboxFolderSettings:
        config = self.store.read_config()
        folders = config.get("folders")
        if folders is None:
            inbox: dict[str, Any] = {}
        elif not isinstance(folders, dict):
            raise FolderSettingsError("Instance folder settings must be an object")
        else:
            value = folders.get("inbox")
            if value is None:
                inbox = {}
            elif not isinstance(value, dict):
                raise FolderSettingsError("Inbox folder settings must be an object")
            else:
                inbox = value
        schema_version = inbox.get("schema_version", FOLDER_SETTINGS_SCHEMA_VERSION)
        if (
            type(schema_version) is not int
            or schema_version != FOLDER_SETTINGS_SCHEMA_VERSION
        ):
            raise FolderSettingsError("unsupported Inbox folder-settings schema")
        name = self._validated_name(str(inbox.get("name", DEFAULT_INBOX_NAME)))
        drop_configured = str(inbox.get("drop_path", DEFAULT_DROP_PATH))
        managed_configured = str(inbox.get("managed_path", DEFAULT_MANAGED_PATH))
        drop = self._configured_path(drop_configured)
        managed = self._configured_path(managed_configured)
        self._validate_pair(drop, managed)
        return InboxFolderSettings(
            schema_version=FOLDER_SETTINGS_SCHEMA_VERSION,
            name=name,
            drop_configured=drop_configured,
            managed_configured=managed_configured,
            drop_path=drop,
            managed_path=managed,
        )

    def _managed_folder_has_knowledge(self) -> bool:
        source_id = inbox_source_id(self.store)
        return any(
            item.get("source_id") == source_id
            for item in self.store.list_canonical("documents")
        ) or any(
            item.get("source_id") == source_id
            for item in self.store.list_canonical("acquisitions")
        )

    def _scope(self, path: Path) -> str:
        try:
            path.resolve().relative_to(self.store.paths.root.resolve())
        except ValueError:
            return "external"
        return "instance"

    def _path_view(self, path: Path, configured: str, *, redact_external: bool) -> dict[str, Any]:
        selected = path.resolve()
        scope = self._scope(selected)
        if scope == "instance":
            display = portable_config_path(self.store.paths.root, selected)
            physical_path: str | None = str(selected)
        else:
            display = selected.name or selected.anchor or "external-folder"
            physical_path = None if redact_external else str(selected)
        available = selected.is_dir()
        writable = available and os.access(selected, os.W_OK | os.X_OK)
        result: dict[str, Any] = {
            "scope": scope,
            "display": display,
            "configured": configured if scope == "instance" else None,
            "available": available,
            "writable": writable,
        }
        if not redact_external:
            result["path"] = physical_path
        return result

    def local_view(self) -> dict[str, Any]:
        settings = self.read()
        return {
            "schema_version": FOLDER_SETTINGS_SCHEMA_VERSION,
            "name": settings.name,
            "drop": self._path_view(
                settings.drop_path,
                settings.drop_configured,
                redact_external=False,
            ),
            "managed": self._path_view(
                settings.managed_path,
                settings.managed_configured,
                redact_external=False,
            ),
            "managed_relocation_allowed": not self._managed_folder_has_knowledge(),
            "canonical_storage": "instance",
        }

    def public_view(self) -> dict[str, Any]:
        settings = self.read()
        return {
            "schema_version": FOLDER_SETTINGS_SCHEMA_VERSION,
            "name": settings.name,
            "drop": self._path_view(
                settings.drop_path,
                settings.drop_configured,
                redact_external=True,
            ),
            "managed": self._path_view(
                settings.managed_path,
                settings.managed_configured,
                redact_external=True,
            ),
            "managed_relocation_allowed": not self._managed_folder_has_knowledge(),
            "canonical_storage": "instance",
        }

    def ensure_paths(self) -> InboxFolderSettings:
        settings = self.read()
        self._ensure_writable_directory(settings.drop_path)
        self._ensure_writable_directory(settings.managed_path)
        return settings

    def configure(
        self,
        *,
        name: str | None = None,
        drop_path: Path | str | None = None,
        managed_path: Path | str | None = None,
    ) -> dict[str, Any]:
        current = self.read()
        selected_name = self._validated_name(name if name is not None else current.name)
        selected_drop = (
            Path(drop_path).expanduser().resolve()
            if drop_path is not None
            else current.drop_path
        )
        selected_managed = (
            Path(managed_path).expanduser().resolve()
            if managed_path is not None
            else current.managed_path
        )
        self._validate_pair(selected_drop, selected_managed)
        if (
            selected_managed != current.managed_path
            and self._managed_folder_has_knowledge()
        ):
            raise ManagedFolderRelocationRequired(
                "managed-copy folder cannot move after Inbox acquisitions; "
                "a verified relocation workflow is required"
            )

        operation = self.operations.start(
            "settings.folders",
            "Configure Inbox folders",
            summary="Validate and save local Inbox folder settings.",
            related={"source_id": inbox_source_id(self.store)},
        )
        try:
            self._ensure_writable_directory(selected_drop)
            self._ensure_writable_directory(selected_managed)
            config = self.store.read_config()
            old_config = self.store.read_config()
            folders = config.setdefault("folders", {})
            if not isinstance(folders, dict):
                raise FolderSettingsError("Instance folder settings must be an object")
            folders["inbox"] = {
                "schema_version": FOLDER_SETTINGS_SCHEMA_VERSION,
                "name": selected_name,
                "drop_path": self._portable_path(selected_drop),
                "managed_path": self._portable_path(selected_managed),
            }
            source_id = inbox_source_id(self.store)
            source_record = self.store.read_canonical("sources", source_id)
            sources = config.setdefault("sources", {})
            if not isinstance(sources, dict):
                raise FolderSettingsError("Instance Sources configuration must be an object")
            if source_record is not None or source_id in sources:
                sources[source_id] = {
                    "kind": "filesystem",
                    "name": selected_name,
                    "path": self._portable_path(selected_managed),
                }
            self.store.write_config(config)
            if source_record is not None:
                try:
                    self.store.write_source(
                        Source(
                            id=source_id,
                            kind="filesystem",
                            name=selected_name,
                            created_at=str(source_record["created_at"]),
                        )
                    )
                except Exception:
                    self.store.write_config(old_config)
                    raise
            self.operations.append(
                operation.id,
                "settings.folders_saved",
                "Saved validated Inbox folder settings.",
                details={
                    "name_changed": selected_name != current.name,
                    "drop_scope": self._scope(selected_drop),
                    "managed_scope": self._scope(selected_managed),
                    "drop_changed": selected_drop != current.drop_path,
                    "managed_changed": selected_managed != current.managed_path,
                },
            )
            closed = self.operations.close(
                operation.id,
                status="completed",
                summary="Inbox folder settings were validated and saved.",
                metrics={
                    "name_changed": int(selected_name != current.name),
                    "drop_changed": int(selected_drop != current.drop_path),
                    "managed_changed": int(selected_managed != current.managed_path),
                    "external_folders": sum(
                        self._scope(path) == "external"
                        for path in (selected_drop, selected_managed)
                    ),
                },
            )
            return {
                "settings": self.local_view(),
                "operation": {
                    "id": closed.id,
                    "status": closed.status,
                    "completed_at": closed.completed_at,
                },
            }
        except Exception as exc:
            current_operation = self.operations.get_record(operation.id)
            if current_operation is not None and current_operation.status == "running":
                self.operations.append(
                    operation.id,
                    "settings.folders_failed",
                    "Inbox folder settings were not changed.",
                    level="error",
                    details={"error_type": exc.__class__.__name__},
                )
                self.operations.close(
                    operation.id,
                    status="failed",
                    summary="Inbox folder settings were not changed.",
                    error_code="folder_settings_failed",
                    error=exc.__class__.__name__,
                )
            raise
