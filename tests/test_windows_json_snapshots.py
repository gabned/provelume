"""Mutable snapshots share atomic publication; errors and ownership remain explicit."""

import ctypes
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from provelume import storage
from provelume.paths import native_path


@pytest.mark.parametrize("failure", [None, "open", "convert", "wrap", "read"])
def test_windows_snapshot_handle_ownership_and_fail_closed_errors(tmp_path, monkeypatch, failure):
    path = tmp_path / "public.json"
    payload = b'{"revision":1}'
    path.write_bytes(payload)
    calls, descriptors = [], []
    original_fdopen = os.fdopen

    def create(*args):
        calls.append(("open", args))
        return ctypes.c_void_p(-1).value if failure == "open" else 123

    def close(handle):
        calls.append(("close", handle))
        return True

    def winerror(code):
        error = PermissionError("synthetic access denied")
        error.winerror = code
        return error

    def convert(handle, flags):
        calls.append(("convert", handle, flags))
        if failure == "convert":
            raise OSError("synthetic conversion failure")
        descriptor = os.open(path, os.O_RDONLY)
        descriptors.append(descriptor)
        return descriptor

    def wrap(descriptor, mode):
        if failure == "wrap":
            raise OSError("synthetic wrapper failure")
        stream = original_fdopen(descriptor, mode)
        if failure != "read":
            return stream

        class BrokenRead:
            def __enter__(self):
                return self

            def read(self):
                raise OSError("synthetic read failure")

            def __exit__(self, *args):
                return stream.__exit__(*args)

        return BrokenRead()

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: SimpleNamespace(
        CreateFileW=create, CloseHandle=close), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(ctypes, "WinError", winerror, raising=False)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(open_osfhandle=convert))
    monkeypatch.setattr(os, "O_BINARY", 0x8000, raising=False)
    monkeypatch.setattr(os, "O_NOINHERIT", 0x80, raising=False)
    monkeypatch.setattr(os, "fdopen", wrap)
    if failure:
        with pytest.raises(OSError):
            storage._windows_snapshot_bytes(path)
    else:
        assert storage._windows_snapshot_bytes(path) == payload
    assert calls[0] == ("open", (str(native_path(path)), 0x80000000, 7, None, 3, 0x80, None))
    assert sum(row[0] == "open" for row in calls) == 1  # Never retry or broaden access.
    assert sum(row[0] == "close" for row in calls) == (1 if failure == "convert" else 0)
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    if failure != "open":
        assert calls[1] == ("convert", 123, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)


@contextmanager
def delete_access(path):
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(native_path(path)), 0x10000, 7, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        yield
    finally:
        assert kernel.CloseHandle(handle)


@pytest.mark.skipif(os.name != "nt", reason="actual Windows share-access check")
def test_windows_reader_accepts_existing_delete_access_with_legacy_negative_control(tmp_path):
    path = tmp_path / "public.json"
    path.write_text('{"revision":1}', encoding="utf-8")
    with delete_access(path):
        # The preceding production reader uses CRT sharing without DELETE.
        with pytest.raises(PermissionError):
            native_path(path).read_bytes()
        assert storage.read_json_snapshot(path) == {"revision": 1}
    assert storage.read_json_snapshot(path) == {"revision": 1}


@pytest.mark.skipif(os.name != "nt", reason="actual Windows MoveFileEx denial and close")
def test_windows_open_snapshot_retains_writer_denial_then_allows_publication(tmp_path, monkeypatch):
    path, replacement = tmp_path / "public.json", tmp_path / "replacement.json"
    path.write_text('{"revision":1}', encoding="utf-8")
    replacement.write_text('{"revision":2}', encoding="utf-8")
    original_fdopen = os.fdopen
    denials = []

    def observed_read(descriptor, mode):
        stream = original_fdopen(descriptor, mode)

        class OpenSnapshot:
            def __enter__(self):
                stream.__enter__()
                return self

            def read(self):
                # Sharing DELETE permits a reader to coexist with a writer's
                # handle; it does not give MoveFileEx POSIX rename semantics.
                with pytest.raises(PermissionError) as denied:
                    storage.replace_file(replacement, path)
                denials.append(denied.value.winerror)
                assert replacement.exists()
                return stream.read()

            def __exit__(self, *args):
                return stream.__exit__(*args)

        return OpenSnapshot()

    monkeypatch.setattr(os, "fdopen", observed_read)
    assert storage.read_json_snapshot(path) == {"revision": 1}
    assert denials == [5]
    assert json.loads(path.read_bytes()) == {"revision": 1}
    storage.replace_file(replacement, path)  # The reader's actual handle is closed.
    assert not replacement.exists()
    assert json.loads(path.read_bytes()) == {"revision": 2}


@pytest.mark.skipif(os.name != "nt", reason="actual Windows simultaneous readers and writer")
def test_windows_snapshots_during_repeated_atomic_publication(tmp_path):
    path = tmp_path / "public.json"
    storage.InstanceStore._atomic_text(path, json.dumps({"revision": 0, "complete": True}))

    def publish():
        for revision in range(1, 33):
            storage.InstanceStore._atomic_text(path, json.dumps({
                "revision": revision, "complete": True,
            }))

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(publish)
        for _ in range(128):
            row = storage.read_json_snapshot(path)
            assert set(row) == {"revision", "complete"}
            assert type(row["revision"]) is int and 0 <= row["revision"] <= 32
            assert row["complete"] is True
        writer.result(timeout=5)
    assert storage.read_json_snapshot(path) == {"revision": 32, "complete": True}


@pytest.mark.parametrize("payload,error", [(b"not json", json.JSONDecodeError),
                                           (b"\xff", UnicodeDecodeError)])
def test_snapshot_decode_errors_are_not_hidden(tmp_path, payload, error):
    path = tmp_path / "public.json"
    path.write_bytes(payload)
    with pytest.raises(error):
        storage.read_json_snapshot(path)
