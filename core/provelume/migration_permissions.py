"""Bounded same-host access metadata, never authority supplied by a portable archive."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import stat
import struct
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from .paths import native_path, safe_instance_path

MAX_PROFILE_BYTES = 16 * 1024 * 1024
MAX_PROFILE_ENTRIES = 200_000
MAX_METADATA_BYTES = 256 * 1024
PROVIDERS = {
    "posix": "posix-mode-owner-group-xattrs/v1",
    "nt": "windows-owner-group-dacl-readonly/v1",
}


class PermissionProfileError(ValueError):
    pass


def _require(value):
    if not value:
        raise PermissionProfileError("filesystem access metadata is unsupported or changed")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _encoded(raw):
    _require(len(raw) <= MAX_METADATA_BYTES)
    return base64.b64encode(raw).decode("ascii")


def _decoded(value):
    _require(isinstance(value, str) and len(value) <= 2 * MAX_METADATA_BYTES)
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise PermissionProfileError("invalid filesystem metadata encoding") from None
    _require(len(result) <= MAX_METADATA_BYTES and _encoded(result) == value)
    return result


@lru_cache(maxsize=1)
def _windows():
    from ctypes import wintypes as w

    a = ctypes.WinDLL("advapi32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    a.GetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    a.GetFileSecurityW.restype = w.BOOL
    a.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, w.LPVOID]
    a.SetFileSecurityW.restype = w.BOOL
    a.GetSecurityDescriptorLength.argtypes = [w.LPVOID]
    a.GetSecurityDescriptorLength.restype = w.DWORD
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        ctypes.POINTER(w.LPVOID),
        ctypes.POINTER(w.DWORD),
    ]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    k.LocalFree.argtypes = [w.LPVOID]
    k.LocalFree.restype = w.LPVOID
    k.GetFileAttributesW.argtypes = [w.LPCWSTR]
    k.GetFileAttributesW.restype = w.DWORD
    k.SetFileAttributesW.argtypes = [w.LPCWSTR, w.DWORD]
    k.SetFileAttributesW.restype = w.BOOL
    return a, k, w


def _descriptor_parts(raw):
    # Recovery input is parsed as bounded bytes, without native pointer dereferences.
    _require(len(raw) >= 20)
    revision, _reserved, control_bits, owner, group, sacl, dacl = struct.unpack_from(
        "<BBHIIII", raw
    )
    _require(revision == 1 and control_bits & 0x8000)
    for offset in (owner, group):
        _require(20 <= offset <= len(raw) - 8 and raw[offset] == 1)
        _require(raw[offset + 1] <= 15)
        _require(offset + 8 + 4 * raw[offset + 1] <= len(raw))
    for offset in (sacl, dacl):
        if not offset:
            continue
        _require(20 <= offset <= len(raw) - 8)
        acl_revision, _reserved, size, count, _reserved2 = struct.unpack_from("<BBHHH", raw, offset)
        _require(acl_revision in (2, 4) and 8 <= size <= len(raw) - offset)
        cursor = offset + 8
        for _ in range(count):
            _require(cursor + 4 <= offset + size)
            ace_size = struct.unpack_from("<H", raw, cursor + 2)[0]
            _require(ace_size >= 4 and ace_size % 4 == 0 and cursor + ace_size <= offset + size)
            cursor += ace_size
    return {
        "protected": bool(control_bits & 0x1000),
        "owner": _encoded(raw[owner : owner + 8 + 4 * raw[owner + 1]]),
        "group": _encoded(raw[group : group + 8 + 4 * raw[group + 1]]),
        "dacl_present": bool(control_bits & 4),
        "dacl": _encoded(raw[dacl : dacl + struct.unpack_from("<H", raw, dacl + 2)[0]])
        if dacl
        else None,
    }


def _windows_metadata(path):
    a, k, w = _windows()
    name = str(native_path(path))
    size = w.DWORD()
    a.GetFileSecurityW(name, 7, None, 0, ctypes.byref(size))
    _require(0 < size.value <= MAX_METADATA_BYTES)
    buffer = ctypes.create_string_buffer(size.value)
    _require(a.GetFileSecurityW(name, 7, buffer, size.value, ctypes.byref(size)))
    raw = buffer.raw[: size.value]
    attributes = k.GetFileAttributesW(name)
    _require(attributes != 0xFFFFFFFF and not attributes & 0x400)
    return {**_descriptor_parts(raw), "readonly": bool(attributes & 1), "descriptor": _encoded(raw)}


def _posix_metadata(path):
    info = path.stat(follow_symlinks=False)
    attributes = {}
    if hasattr(os, "listxattr"):
        for name in sorted(os.listxattr(path, follow_symlinks=False)):
            attributes[name] = _encoded(os.getxattr(path, name, follow_symlinks=False))
    return {
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "xattrs": attributes,
    }


def _paths(root):
    _require(root.is_dir() and not root.is_symlink() and not root.is_junction())
    _require(not any(p.is_symlink() or p.is_junction() for p in root.parents))
    result = [root]
    for path in root.rglob("*"):
        _require(len(result) < MAX_PROFILE_ENTRIES)
        result.append(path)
    result.sort()
    for path in result:
        _require(not path.is_symlink() and not path.is_junction())
        _require(stat.S_ISDIR(path.lstat().st_mode) or stat.S_ISREG(path.lstat().st_mode))
    return result


def capture_permissions(root):
    root = Path(root)
    _require(os.name in PROVIDERS)
    entries = []
    for path in _paths(root):
        metadata = _windows_metadata(path) if os.name == "nt" else _posix_metadata(path)
        _require(len(canonical(metadata)) <= MAX_METADATA_BYTES)
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "kind": "directory" if path.is_dir() else "file",
                "metadata": metadata,
            }
        )
    result = {
        "schema_version": 1,
        "provider": PROVIDERS[os.name],
        "entries": sorted(entries, key=lambda e: e["path"]),
    }
    _require(len(canonical(result)) <= MAX_PROFILE_BYTES)
    return result


def validate_profile(profile):
    _require(type(profile) is dict and set(profile) == {"schema_version", "provider", "entries"})
    _require(type(profile["schema_version"]) is int and profile["schema_version"] == 1)
    _require(profile["provider"] == PROVIDERS.get(os.name))
    _require(
        type(profile["entries"]) is list and 0 < len(profile["entries"]) <= MAX_PROFILE_ENTRIES
    )
    _require(len(canonical(profile)) <= MAX_PROFILE_BYTES)
    names = []
    for row in profile["entries"]:
        _require(type(row) is dict and set(row) == {"path", "kind", "metadata"})
        name = row["path"]
        _require(isinstance(name, str) and len(name.encode("utf-8")) <= 4096)
        if name != ".":
            # Use the established locator validation without touching a source path.
            from .paths import normalise_locator

            _require(normalise_locator(name) == name)
        _require(row["kind"] in {"directory", "file"})
        metadata = row["metadata"]
        _require(type(metadata) is dict and len(canonical(metadata)) <= MAX_METADATA_BYTES)
        if os.name == "nt":
            _require(
                set(metadata)
                == {"protected", "owner", "group", "dacl_present", "dacl", "readonly", "descriptor"}
            )
            _require(
                all(type(metadata[k]) is bool for k in ["protected", "dacl_present", "readonly"])
            )
            parts = _descriptor_parts(_decoded(metadata["descriptor"]))
            _require(parts == {k: metadata[k] for k in parts})
        else:
            _require(set(metadata) == {"mode", "uid", "gid", "xattrs"})
            _require(type(metadata["mode"]) is int and 0 <= metadata["mode"] <= 0o7777)
            _require(
                all(
                    type(metadata[k]) is int and 0 <= metadata[k] <= 0xFFFFFFFF
                    for k in ["uid", "gid"]
                )
            )
            _require(type(metadata["xattrs"]) is dict and len(metadata["xattrs"]) <= 128)
            for key, value in metadata["xattrs"].items():
                _require(isinstance(key, str) and 0 < len(key.encode()) <= 255 and "\0" not in key)
                _decoded(value)
        names.append(name)
    _require(names == sorted(set(names)) and names[0] == ".")
    _require(profile["entries"][0]["kind"] == "directory")
    directory_names = {r["path"] for r in profile["entries"] if r["kind"] == "directory"}
    _require(
        all(str(Path(n).parent).replace("\\", "/") in directory_names for n in names if n != ".")
    )


def permission_fingerprint(profile):
    validate_profile(profile)
    result = deepcopy(profile)
    for row in result["entries"]:
        # Self-relative buffer placement may change without changing access control.
        row["metadata"].pop("descriptor", None)
    return hashlib.sha256(canonical(result)).hexdigest()


@lru_cache(maxsize=1)
def _private_descriptor():
    a, k, w = _windows()
    descriptor, size = w.LPVOID(), w.DWORD()
    _require(
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "D:P(A;OICI;FA;;;OW)", 1, ctypes.byref(descriptor), ctypes.byref(size)
        )
    )
    try:
        raw = ctypes.string_at(descriptor, a.GetSecurityDescriptorLength(descriptor))
        offset = struct.unpack_from("<I", raw, 16)[0]
        _require(20 <= offset <= len(raw) - 8)
        size = struct.unpack_from("<H", raw, offset + 2)[0]
        _require(8 <= size <= len(raw) - offset)
        acl = raw[offset : offset + size]
        return raw, _encoded(acl)
    finally:
        k.LocalFree(descriptor)


def make_private(path):
    path = Path(path)
    _require(not path.is_symlink() and not path.is_junction())
    if os.name == "nt":
        a, _k, _w = _windows()
        buffer = ctypes.create_string_buffer(_private_descriptor()[0])
        _require(a.SetFileSecurityW(str(native_path(path)), 4 | 0x80000000, buffer))
    else:
        path.chmod(0o700 if path.is_dir() else 0o600, follow_symlinks=False)


def private_directory(path):
    path = Path(path)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        _require(path.is_dir() and not path.is_symlink() and not path.is_junction())
        if os.name == "nt":
            current = _windows_metadata(path)
            _require(current["protected"] and current["dacl"] == _private_descriptor()[1])
        else:
            info = path.stat(follow_symlinks=False)
            _require(stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.geteuid())
    else:
        make_private(path)


def protect_private_tree(root):
    for path in _paths(Path(root)):
        make_private(path)


def prepare_private_directories(root, source):
    validate_profile(source)
    root = Path(root)
    for row in sorted(source["entries"], key=lambda r: (r["path"].count("/"), r["path"])):
        if row["kind"] == "directory" and row["path"] != ".":
            path = safe_instance_path(root, row["path"])
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
    protect_private_tree(root)


def planned_permissions(root, source):
    """Overlay only independently captured, still-present source access metadata."""
    validate_profile(source)
    actual = capture_permissions(root)
    selected = {r["path"]: r for r in source["entries"]}
    aliases = {}
    if os.name == "nt":
        for row in source["entries"]:
            aliases.setdefault(row["path"].casefold(), []).append(row)
    for row in actual["entries"]:
        previous = selected.get(row["path"])
        if previous is None and os.name == "nt":
            # Established writers use canonical config/manifest spelling. Confirm
            # an alias through this private stage's native file identity, without
            # assuming every Unicode case fold is a Windows alias.
            current = safe_instance_path(root, row["path"])
            for candidate in aliases.get(row["path"].casefold(), []):
                alias = safe_instance_path(root, candidate["path"])
                if alias.exists() and os.path.samefile(alias, current):
                    _require(previous is None)
                    previous = candidate
        if previous is not None:
            _require(previous["kind"] == row["kind"])
            row["metadata"] = deepcopy(previous["metadata"])
    return actual


def apply_permissions(root, source):
    """Only private, unpublished stages may be passed here; never repair live metadata."""
    prepare_private_directories(root, source)
    expected = planned_permissions(root, source)
    for row in sorted(
        expected["entries"],
        key=lambda r: (r["path"].count("/"), r["kind"] != "directory", r["path"]),
    ):
        path = Path(root) if row["path"] == "." else safe_instance_path(root, row["path"])
        metadata = row["metadata"]
        if os.name == "nt":
            a, k, _w = _windows()
            name = str(native_path(path))
            attrs = k.GetFileAttributesW(name)
            _require(attrs != 0xFFFFFFFF)
            _require(k.SetFileAttributesW(name, attrs | 1 if metadata["readonly"] else attrs & ~1))
            raw = ctypes.create_string_buffer(_decoded(metadata["descriptor"]))
            _require(
                a.SetFileSecurityW(
                    name, 7 | (0x80000000 if metadata["protected"] else 0x20000000), raw
                )
            )
        else:
            info = path.stat(follow_symlinks=False)
            if (info.st_uid, info.st_gid) != (metadata["uid"], metadata["gid"]):
                os.chown(path, metadata["uid"], metadata["gid"], follow_symlinks=False)
            if hasattr(os, "listxattr"):
                current = {
                    n: os.getxattr(path, n, follow_symlinks=False)
                    for n in os.listxattr(path, follow_symlinks=False)
                }
                for name in set(current) - set(metadata["xattrs"]):
                    os.removexattr(path, name, follow_symlinks=False)
                for name, value in metadata["xattrs"].items():
                    desired = _decoded(value)
                    if current.get(name) != desired:
                        os.setxattr(path, name, desired, follow_symlinks=False)
            path.chmod(metadata["mode"], follow_symlinks=False)
    actual = capture_permissions(root)
    _require(permission_fingerprint(actual) == permission_fingerprint(expected))
    return actual
