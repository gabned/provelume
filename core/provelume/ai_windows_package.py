"""Closed public frozen-code inventory embedded in the running executable.

Only these verified public files receive read/execute access. Private Instance,
model-store, user-profile and arbitrary manually selected runtime paths do not.
"""

from __future__ import annotations

import ctypes as c
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

from .ai_runtime_limits import check

RESOURCE_ID = 0xC012
MAX_MANIFEST = 2 * 1024**2
MAX_FILES = 8192
MAX_BYTES = 512 * 1024**2
INSTALLER_FILES = frozenset({"unins000.exe", "unins000.dat"})


def inventory(root, *, installed=False):
    """Enumerate ordinary files without following a junction, symlink or hardlink."""
    root = Path(root)
    rows, directories, pending = {}, [], [root]
    total = 0
    while pending:
        directory = pending.pop()
        info = directory.lstat()
        check(stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
              "unsafe_path")
        for child in sorted(directory.iterdir()):
            info = child.lstat()
            relative = child.relative_to(root).as_posix()
            parts = PurePosixPath(relative).parts
            check(len(parts) <= 24 and len(relative) <= 1024, "limit")
            check(all(p not in (".", "..") and not p.endswith((".", " "))
                      and not any(ord(ch) < 32 or ch in '\\:*?"<>|' for ch in p)
                      for p in parts), "unsafe_path")
            check(not stat.S_ISLNK(info.st_mode)
                  and not getattr(info, "st_file_attributes", 0) & 0x400, "unsafe_path")
            if stat.S_ISDIR(info.st_mode):
                check(parts[0] == "_internal", "untrusted")
                directories.append(relative)
                pending.append(child)
            else:
                check(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe_path")
                if relative == "Provelume.exe":
                    continue  # The inventory is inside this running code, not a self-hash.
                if installed and relative in INSTALLER_FILES:
                    check(info.st_size <= 16 * 1024**2, "limit")
                    continue  # Inno creates these; the AI identity receives no access.
                check(parts[0] == "_internal", "untrusted")
                rows[relative] = info.st_size
                total += info.st_size
            check(len(rows) + len(directories) <= MAX_FILES and total <= MAX_BYTES, "limit")
    check(rows and len({p.casefold() for p in (*rows, *directories)})
          == len(rows) + len(directories), "untrusted")
    return rows, sorted(directories)


def build_inventory(root, commit):
    check(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "untrusted")
    files, directories = inventory(root)
    rows = {}
    for name, size in sorted(files.items()):
        with (Path(root) / name).open("rb") as stream:
            rows[name] = {"bytes": size,
                          "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
    value = {"schema_version": 1, "source_commit": commit,
             "files": rows, "directories": directories}
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    check(len(raw) <= MAX_MANIFEST, "limit")
    return raw


def read_embedded_inventory():
    from .ai_windows_api import P, libraries

    kernel, _, _, _ = libraries()
    module = kernel.GetModuleHandleW(None)
    resource = kernel.FindResourceW(module, P(RESOURCE_ID), P(10))
    check(resource, "untrusted")
    size = kernel.SizeofResource(module, resource)
    check(0 < size <= MAX_MANIFEST, "limit")
    loaded = kernel.LoadResource(module, resource)
    check(loaded, "untrusted")
    pointer = kernel.LockResource(loaded)
    check(pointer, "untrusted")
    raw = c.string_at(pointer, size)
    value = json.loads(raw)
    check(set(value) == {"schema_version", "source_commit", "files", "directories"}
          and value["schema_version"] == 1, "untrusted")
    check(raw == (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
          "untrusted")
    return value


def pin_public_package(stack, executable, sid, *, cancel, deadline):
    from .ai_model_download import checkpoint
    from .ai_windows_acl import grant_public_read, pin_acl_path

    executable = Path(executable)
    check(executable.name == "Provelume.exe" and executable.is_absolute(), "compatibility")
    root = executable.parent
    root_handle = stack.enter_context(pin_acl_path(root, directory=True))
    expected = read_embedded_inventory()
    files, directories = inventory(root, installed=True)
    check(directories == expected["directories"] and set(files) == set(expected["files"]),
          "untrusted")
    directories = [(root, root_handle)] + [
        (root / name, stack.enter_context(pin_acl_path(root / name, directory=True)))
        for name in directories]
    pinned = []
    # Verify every public byte before changing a single ACL. Keep the exact handles
    # until worker termination, including parents and the actual executable.
    for name, size in sorted(files.items()):
        checkpoint(cancel, deadline)
        handle = stack.enter_context(pin_acl_path(root / name, directory=False))
        pin = expected["files"][name]
        check(set(pin) == {"bytes", "sha256"} and size == pin["bytes"], "integrity")
        digest = hashlib.sha256()
        while True:
            checkpoint(cancel, deadline)
            block = os.read(handle, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        check(digest.hexdigest() == pin["sha256"], "integrity")
        pinned.append(handle)
    executable_handle = stack.enter_context(pin_acl_path(executable, directory=False))
    for handle in [h for _, h in directories] + pinned + [executable_handle]:
        checkpoint(cancel, deadline)
        grant_public_read(handle, sid)
    return {"public_code_files": len(files) + 1, "public_code_inventory": hashlib.sha256(
        (json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()}
