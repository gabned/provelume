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
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath
from time import monotonic

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


class _PublicInventoryObservation:
    """In-memory progress only; no path, SID, file content or execution authority."""

    def __init__(self, deadline):
        self.started = self.stage_started = monotonic()
        self.deadline = deadline
        self.budget_at_entry_ms = int((deadline - self.started) * 1000)
        self.stage = "pin-root"
        self.files_total = self.grants_total = None
        self.files_verified = self.bytes_hashed = self.grants_completed = 0
        self.checkpoint_calls = 0
        self.timings = {"checkpoint": 0.0, "acl": 0.0}
        self.timings_complete = True

    def mark(self, stage):
        self.stage, self.stage_started = stage, monotonic()

    @contextmanager
    def measuring(self, kind):
        # Observation must not change either the call's exception or Win32 error.
        native_code = c.get_last_error() if os.name == "nt" else None
        started = None
        try:
            try:
                started = monotonic()
            except Exception:
                self.timings_complete = False
        finally:
            if native_code is not None:
                c.set_last_error(native_code)
        try:
            yield
        finally:
            native_code = c.get_last_error() if os.name == "nt" else None
            try:
                try:
                    if started is not None:
                        self._record_time(kind, started)
                except Exception:
                    self.timings_complete = False
            finally:
                if native_code is not None:
                    c.set_last_error(native_code)

    def _record_time(self, kind, started):
        elapsed = monotonic() - started
        if not 0 <= elapsed <= 86400:
            raise ValueError("observation_clock")
        self.timings[kind] += elapsed
        if kind == "checkpoint":
            self.checkpoint_calls += 1

    def snapshot(self):
        now = monotonic()
        result = {
            "stage": self.stage, "elapsed_ms": int((now - self.started) * 1000),
            "stage_elapsed_ms": int((now - self.stage_started) * 1000),
            "budget_at_entry_ms": self.budget_at_entry_ms,
            "budget_remaining_ms": int((self.deadline - now) * 1000),
            "files_total": self.files_total, "files_verified": self.files_verified,
            "bytes_hashed": self.bytes_hashed, "grants_total": self.grants_total,
            "grants_completed": self.grants_completed,
        }
        if self.timings_complete:
            result.update(checkpoint_calls=self.checkpoint_calls,
                          checkpoint_elapsed_ms=int(self.timings["checkpoint"] * 1000),
                          acl_elapsed_ms=int(self.timings["acl"] * 1000))
        return result


def pin_public_package(stack, executable, sid, *, cancel, deadline):
    progress = _PublicInventoryObservation(deadline)
    try:
        return _pin_public_package(stack, executable, sid, cancel=cancel,
                                   deadline=deadline, progress=progress)
    except BaseException as exc:
        # Keep the existing failure and native code, even if observation fails.
        native_code = c.get_last_error() if os.name == "nt" else None
        try:
            with suppress(Exception):
                exc.public_inventory = progress.snapshot()
        finally:
            if native_code is not None:
                c.set_last_error(native_code)
        raise


def _pin_public_package(stack, executable, sid, *, cancel, deadline, progress):
    from .ai_model_download import checkpoint
    from .ai_windows_acl import grant_public_read, pin_acl_path

    executable = Path(executable)
    check(executable.name == "Provelume.exe" and executable.is_absolute(), "compatibility")
    root = executable.parent
    root_handle = stack.enter_context(pin_acl_path(root, directory=True))
    progress.mark("read-manifest")
    expected = read_embedded_inventory()
    progress.mark("enumerate")
    files, directories = inventory(root, installed=True)
    check(directories == expected["directories"] and set(files) == set(expected["files"]),
          "untrusted")
    progress.files_total = len(files)
    progress.grants_total = len(files) + len(directories) + 2
    progress.mark("pin-directories")
    directories = [(root, root_handle)] + [
        (root / name, stack.enter_context(pin_acl_path(root / name, directory=True)))
        for name in directories]
    pinned = []
    # Verify every public byte before changing a single ACL. Keep the exact handles
    # until worker termination, including parents and the actual executable.
    for name, size in sorted(files.items()):
        progress.mark("pin-file")
        with progress.measuring("checkpoint"):
            checkpoint(cancel, deadline)
        handle = stack.enter_context(pin_acl_path(root / name, directory=False))
        pin = expected["files"][name]
        check(set(pin) == {"bytes", "sha256"} and size == pin["bytes"], "integrity")
        digest = hashlib.sha256()
        progress.mark("hash-file")
        while True:
            with progress.measuring("checkpoint"):
                checkpoint(cancel, deadline)
            block = os.read(handle, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            progress.bytes_hashed += len(block)
        check(digest.hexdigest() == pin["sha256"], "integrity")
        progress.files_verified += 1
        pinned.append(handle)
    progress.mark("pin-executable")
    executable_handle = stack.enter_context(pin_acl_path(executable, directory=False))
    for handle in [h for _, h in directories] + pinned + [executable_handle]:
        progress.mark("grant-acl")
        with progress.measuring("checkpoint"):
            checkpoint(cancel, deadline)
        with progress.measuring("acl"):
            grant_public_read(handle, sid)
        progress.grants_completed += 1
    return {"public_code_files": len(files) + 1, "public_code_inventory": hashlib.sha256(
        (json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()}
