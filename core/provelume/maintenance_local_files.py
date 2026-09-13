"""Local file handles for explicit maintenance selections; no remote fallback."""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import stat
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4


class MaintenanceTargetError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def absolute_local_path(value: Path | str) -> Path:
    raw = str(value)
    path = Path(raw)
    if (
        not path.is_absolute()
        or "\x00" in raw
        or ".." in path.parts
        or raw.startswith(("\\\\", "//"))
        or "://" in raw
    ):
        raise MaintenanceTargetError("target_unsafe")
    if os.name == "nt":
        if (
            len(path.drive) != 2
            or ":" in raw[2:]
            or any(
                part.endswith((".", " "))
                or re.fullmatch(
                    r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]|CONIN\$|CONOUT\$)(?:\..*)?",
                    part,
                    re.IGNORECASE,
                )
                for part in path.parts[1:]
            )
        ):
            raise MaintenanceTargetError("target_unsafe")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kind = kernel.GetDriveTypeW(path.anchor)
        if kind == 4:
            raise MaintenanceTargetError("target_remote")
        if kind not in {2, 3, 5, 6}:
            raise MaintenanceTargetError("target_locality_unknown")
    elif os.name == "posix":
        # Linux mountinfo is a local kernel observation; unknown platforms fail closed.
        try:
            rows = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
            matches = []
            for row in rows:
                left, right = row.split(" - ", 1)
                mount = left.split()[4]
                for encoded, decoded in (("\\040", " "), ("\\011", "\t"), ("\\134", "\\")):
                    mount = mount.replace(encoded, decoded)
                if path.is_relative_to(Path(mount)):
                    matches.append((len(mount), right.split()[0]))
            filesystem = max(matches)[1] if matches else "unknown"
        except (OSError, ValueError, IndexError):
            filesystem = "unknown"
        if filesystem in {"nfs", "nfs4", "cifs", "smb3", "9p", "fuse.sshfs"}:
            raise MaintenanceTargetError("target_remote")
        if filesystem not in {"ext2", "ext3", "ext4", "xfs", "btrfs", "tmpfs", "overlay", "zfs"}:
            raise MaintenanceTargetError("target_locality_unknown")
    else:
        raise MaintenanceTargetError("target_locality_unknown")
    return path


def file_identity(handle: BinaryIO) -> dict[str, int]:
    info = os.fstat(handle.fileno())
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "size_bytes": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def stream_digest(handle: BinaryIO, maximum: int) -> tuple[str, int]:
    handle.seek(0)
    size = 0
    digest = hashlib.sha256()
    while block := handle.read(min(1024 * 1024, maximum + 1 - size)):
        size += len(block)
        if size > maximum:
            raise MaintenanceTargetError("target_size_bound")
        digest.update(block)
    handle.seek(0)
    return digest.hexdigest(), size


def _windows_open(path: Path, *, directory: bool, create: bool = False, lock: bool = False) -> int:
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # FILE_LIST_DIRECTORY participates in share-access checks. Attribute-only
    # handles do not deny rename, even when FILE_SHARE_DELETE is omitted.
    access = 0x1 if directory else 0xC0000000 if create or lock else 0x80000000
    share = 3 if directory or lock else 1  # Deny rename; archive reads also deny writers.
    handle = kernel.CreateFileW(
        str(path),
        access,
        share,
        None,
        4 if lock else 1 if create else 3,
        0x00200000 | (0x02000000 if directory else 0),
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in {2, 3}:
            raise FileNotFoundError(str(path))
        if error in {80, 183}:
            raise FileExistsError(str(path))
        raise MaintenanceTargetError("target_unavailable")
    info = (wintypes.DWORD * 13)()
    if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
        kernel.CloseHandle(handle)
        raise MaintenanceTargetError("target_unavailable")
    if info[0] & 0x400 or bool(info[0] & 0x10) != directory:
        kernel.CloseHandle(handle)
        raise MaintenanceTargetError("target_unsafe")
    try:
        return msvcrt.open_osfhandle(
            handle, os.O_BINARY | (os.O_RDWR if create or lock else os.O_RDONLY)
        )
    except Exception:
        kernel.CloseHandle(handle)
        raise


@contextmanager
def pinned_parent(value: Path | str):
    path = absolute_local_path(value)
    try:
        with ExitStack() as stack:
            if os.name == "nt":
                for parent in reversed((path.parent, *path.parent.parents)):
                    descriptor = _windows_open(parent, directory=True)
                    stack.callback(os.close, descriptor)
                yield path, None
            else:
                descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
                stack.callback(os.close, descriptor)
                for name in path.parent.parts[1:]:
                    descriptor = os.open(
                        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                    stack.callback(os.close, descriptor)
                yield path, descriptor
    except MaintenanceTargetError:
        raise
    except FileNotFoundError as exc:
        raise MaintenanceTargetError("target_missing") from exc
    except OSError as exc:
        raise MaintenanceTargetError("target_unsafe") from exc


@contextmanager
def open_local_file(value: Path | str):
    with pinned_parent(value) as (path, parent):
        try:
            descriptor = (
                _windows_open(path, directory=False)
                if os.name == "nt"
                else os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            )
            with os.fdopen(descriptor, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise MaintenanceTargetError("target_unsafe")
                yield handle
        except FileNotFoundError as exc:
            raise MaintenanceTargetError("target_missing") from exc
        except OSError as exc:
            raise MaintenanceTargetError("target_unavailable") from exc


@contextmanager
def open_local_lock(value: Path | str):
    with pinned_parent(value) as (path, parent):
        descriptor = (
            _windows_open(path, directory=False, lock=True)
            if os.name == "nt"
            else os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise MaintenanceTargetError("target_unsafe")
            yield descriptor
        finally:
            os.close(descriptor)


def write_local_bytes(value: Path | str, data: bytes, *, replace: bool = False) -> None:
    """Publish in a pinned parent; user exports never overwrite an existing entry."""
    with pinned_parent(value) as (path, parent):
        temporary = ".maintenance-" + uuid4().hex + ".tmp"
        try:
            descriptor = (
                _windows_open(path.parent / temporary, directory=False, create=True)
                if os.name == "nt"
                else os.open(
                    temporary,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent,
                )
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            if replace:
                if path.is_symlink() or path.is_junction():
                    raise MaintenanceTargetError("target_unsafe")
                if os.name == "nt":
                    os.replace(path.parent / temporary, path)
                else:
                    os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            elif os.name == "nt":
                os.link(path.parent / temporary, path)
            else:
                os.link(
                    temporary,
                    path.name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
        except FileExistsError as exc:
            raise MaintenanceTargetError("output_exists") from exc
        finally:
            if os.name == "nt":
                (path.parent / temporary).unlink(missing_ok=True)
            else:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent)
