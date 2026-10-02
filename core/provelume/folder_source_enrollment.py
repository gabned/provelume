"""Bounded, read-only qualification of an explicitly selected filesystem path."""

from __future__ import annotations

import errno
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from typing import Any

from .catalog_registry import exported_catalogs, resolve_language
from .folder_source_model import MAX_FOLDER_PATH_CHARS, SOURCE_CLASSES, FolderSourceError

VALIDATION_TIMEOUT_SECONDS = 5.0
_VALIDATION_SLOTS = BoundedSemaphore(2)

_diagnostic_catalogs = exported_catalogs('folder_source_enrollment.DIAGNOSTICS')
DIAGNOSTICS = {key: (_diagnostic_catalogs["en"][key], _diagnostic_catalogs["it"][key])
               for key in _diagnostic_catalogs["en"]}


def diagnostic_message(code: str, language: str = "en") -> str:
    return _diagnostic_catalogs[resolve_language(language)][code]


class FolderSourceEnrollmentError(FolderSourceError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(diagnostic_message(code))


def classify_path(value: Path | str, *, platform: str | None = None) -> str:
    """Reject unsupported selectors before performing any filesystem operation."""
    text = str(value).strip()
    platform = os.name if platform is None else platform
    if (
        not text
        or len(text) > MAX_FOLDER_PATH_CHARS
        or any(ord(c) < 32 for c in text)
        or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text)
    ):
        raise FolderSourceEnrollmentError("unsupported_path")
    windows = text.replace("/", "\\")
    if windows.startswith(("\\\\?\\", "\\\\.\\")):
        raise FolderSourceEnrollmentError("unsupported_path")
    unc = windows.startswith("\\\\")
    drive = bool(re.match(r"^[a-zA-Z]:", text))
    if unc or drive:
        pure = PureWindowsPath(windows)
        if not pure.is_absolute():
            raise FolderSourceEnrollmentError("unsupported_path")
        if unc:
            authority = pure.drive[2:].split("\\")
            if (
                len(authority) != 2
                or any(x in {"", ".", ".."} for x in authority)
                or any(c in pure.drive for c in "@:<>|?*")
            ):
                raise FolderSourceEnrollmentError("unsupported_path")
        for part in pure.parts[1:]:
            if part in {".", ".."}:
                continue
            stem = part.split(".", 1)[0].upper()
            if (
                any(c in part for c in '<>:"|?*')
                or part.endswith((".", " "))
                or stem in {"CON", "PRN", "AUX", "NUL"}
                or re.fullmatch(r"(?:COM|LPT)[1-9]", stem)
            ):
                raise FolderSourceEnrollmentError("unsupported_path")
        if platform != "nt":
            raise FolderSourceEnrollmentError("unsupported_platform")
        return "unc" if unc else "windows_drive"
    if ":" in text or (platform == "nt" and windows.startswith("\\")):
        raise FolderSourceEnrollmentError("unsupported_path")
    if platform == "nt":
        for part in PureWindowsPath(windows).parts:
            stem = part.split(".", 1)[0].upper()
            if part not in {".", ".."} and (
                any(c in part for c in '<>:"|?*')
                or part.endswith((".", " "))
                or stem in {"CON", "PRN", "AUX", "NUL"}
                or re.fullmatch(r"(?:COM|LPT)[1-9]", stem)
            ):
                raise FolderSourceEnrollmentError("unsupported_path")
    return "native"


def diagnose_os_error(
    error: OSError,
    *,
    source_class: str,
    path_kind: str,
    drive_visible: bool | None = None,
) -> str:
    winerror = getattr(error, "winerror", None)
    if winerror in {86, 1219, 1244, 1312, 1326, 1327, 1328, 1329, 1330, 1331, 1909, 2202}:
        return "windows_session_required"
    if (
        winerror in {5, 65}
        or isinstance(error, PermissionError)
        or error.errno in {errno.EACCES, errno.EPERM}
    ):
        return "permission_denied"
    if winerror in {87, 123, 161, 206} or error.errno in {errno.ENOTDIR, errno.ELOOP}:
        return "unsupported_path"
    if source_class == "removable":
        return "mount_unavailable"
    if source_class == "network" or path_kind == "unc":
        if path_kind == "windows_drive" and drive_visible is False:
            return "mapped_drive_unavailable"
        return "network_unreachable"
    return "path_unavailable"


def windows_drive_visible(value: Path | str) -> bool | None:
    """Inspect this Windows session's drive namespace without opening a mount."""
    drive = PureWindowsPath(str(value)).drive.upper()
    listdrives = getattr(os, "listdrives", None)
    if not re.fullmatch(r"[A-Z]:", drive) or listdrives is None:
        return None
    try:
        return drive in {PureWindowsPath(item).drive.upper() for item in listdrives()}
    except OSError:
        return None


@dataclass(frozen=True)
class EnrollmentCheck:
    code: str
    path_kind: str
    source_class: str
    path: Path | None = None
    configured_path: str | None = None
    existing_source_id: str | None = None

    def public(self, language: str = "en") -> dict[str, Any]:
        return {
            "schema_version": 1,
            "can_enroll": self.code == "ok",
            "diagnostic_code": self.code,
            "message": diagnostic_message(self.code, language),
            "path_kind": self.path_kind,
            "source_class": self.source_class,
            "existing_source_id": self.existing_source_id,
        }


def _path_key(root: Path, value: Path | str) -> str:
    path = Path(value)
    return os.path.normcase(os.path.abspath(path if path.is_absolute() else root / path))


def qualify_folder_path(
    value: Path | str,
    *,
    source_class: str,
    instance_root: Path,
    resolver: Callable[[Path | str], Path],
    configured_sources: Mapping[str, Any],
) -> EnrollmentCheck:
    source_class = source_class if source_class in SOURCE_CLASSES else "unsupported"
    try:
        kind = classify_path(value)
        if source_class not in SOURCE_CLASSES or (kind == "unc" and source_class != "network"):
            raise FolderSourceEnrollmentError("unsupported_path")
    except FolderSourceEnrollmentError as exc:
        return EnrollmentCheck(exc.code, "unsupported", source_class)
    if not _VALIDATION_SLOTS.acquire(blocking=False):
        return EnrollmentCheck("validation_busy", kind, source_class)
    outcomes: Queue[EnrollmentCheck] = Queue(maxsize=1)

    def probe() -> None:
        try:
            selected = resolver(value).resolve(strict=True)
            mode = selected.stat().st_mode
            if stat.S_ISDIR(mode):
                # Open the root, without recursively scanning or reading document content.
                with os.scandir(selected) as entries:
                    next(entries, None)
            elif stat.S_ISREG(mode):
                with selected.open("rb"):
                    pass
            else:
                raise FolderSourceEnrollmentError("unsupported_path")
            key = _path_key(instance_root, selected)
            existing = next(
                (
                    str(source_id)
                    for source_id, item in configured_sources.items()
                    if isinstance(item, Mapping)
                    and isinstance(item.get("path"), str)
                    and _path_key(instance_root, item["path"]) == key
                ),
                None,
            )
            try:
                portable = os.path.relpath(selected, start=instance_root).replace("\\", "/")
            except ValueError:
                portable = str(selected)
            result = EnrollmentCheck("ok", kind, source_class, selected, portable, existing)
        except FolderSourceEnrollmentError as exc:
            result = EnrollmentCheck(exc.code, kind, source_class)
        except FolderSourceError:
            result = EnrollmentCheck("unsafe_path", kind, source_class)
        except OSError as exc:
            visible = windows_drive_visible(value) if kind == "windows_drive" else None
            code = diagnose_os_error(
                exc, source_class=source_class, path_kind=kind, drive_visible=visible
            )
            result = EnrollmentCheck(code, kind, source_class)
        except (ValueError, RuntimeError):
            result = EnrollmentCheck("unsupported_path", kind, source_class)
        except Exception:
            # Do not send an arbitrary exception (which may contain a path) to
            # the thread exception logger or to a public diagnostic surface.
            result = EnrollmentCheck("validation_failed", kind, source_class)
        finally:
            _VALIDATION_SLOTS.release()
        outcomes.put(result)

    worker = Thread(target=probe, name="provelume-folder-validation", daemon=True)
    try:
        worker.start()
    except RuntimeError:
        _VALIDATION_SLOTS.release()
        return EnrollmentCheck("validation_busy", kind, source_class)
    try:
        return outcomes.get(timeout=VALIDATION_TIMEOUT_SECONDS)
    except Empty:
        # A late worker is read-only: it cannot enroll or resume any Source.
        return EnrollmentCheck("validation_timeout", kind, source_class)
