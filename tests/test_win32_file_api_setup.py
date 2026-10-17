"""Setup reuse must retain fresh native calls, locality, bytes and ownership."""

import ctypes
import importlib.util
import os
import sys
import threading
from pathlib import PureWindowsPath
from types import SimpleNamespace

import pytest

from provelume import maintenance_local_files as files


def clear_bindings():
    for name in ("_windows_drive_type_api", "_windows_file_api"):
        function = getattr(files, name, None)
        if function is not None:
            function.cache_clear()


@pytest.fixture
def native(monkeypatch):
    clear_bindings()
    state = SimpleNamespace(loads=0, prototypes=0, symbols=0, events=[], handles={},
                            create_error=None, info_ok=True, reparse=False,
                            drive_types=[3], transfer_error=None, error=0, fail_load=False)

    class Function:
        def __init__(self, name):
            self.name = name

        def __setattr__(self, name, value):
            if name in {"argtypes", "restype"}:
                state.prototypes += 1
            object.__setattr__(self, name, value)

        def __call__(self, *args):
            state.events.append((self.name, args))
            if self.name == "GetDriveTypeW":
                if len(state.drive_types) > 1:
                    return state.drive_types.pop(0)
                return state.drive_types[0]
            if self.name == "CreateFileW":
                if state.create_error is not None:
                    state.error = state.create_error
                    return ctypes.c_void_p(-1).value
                handle = 100 + len(state.handles)
                state.handles[handle] = bool(args[5] & 0x02000000)
                return handle
            if self.name == "GetFileInformationByHandle":
                args[1]._obj[0] = ((0x10 if state.handles[args[0]] else 0)
                                  | (0x400 if state.reparse else 0))
                return int(state.info_ok)
            assert self.name == "CloseHandle"
            return 1

    class Kernel:
        def __init__(self):
            self.functions = {}

        def __getattr__(self, name):
            assert name in {"GetDriveTypeW", "CreateFileW",
                            "GetFileInformationByHandle", "CloseHandle"}
            if name not in self.functions:
                state.symbols += 1
                self.functions[name] = Function(name)
            return self.functions[name]

    def load(name, *, use_last_error):
        assert name == "kernel32" and use_last_error is True
        state.loads += 1
        if state.fail_load:
            raise OSError("synthetic loading failure")
        return Kernel()

    def transfer(handle, flags):
        state.events.append(("CRT", (handle, flags)))
        if state.transfer_error is not None:
            raise state.transfer_error
        return handle + 10000

    monkeypatch.setattr(files.ctypes, "WinDLL", load, raising=False)
    monkeypatch.setattr(files.ctypes, "get_last_error", lambda: state.error, raising=False)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(open_osfhandle=transfer))
    monkeypatch.setattr(files, "os", SimpleNamespace(name="nt", O_BINARY=0x8000,
                                                     O_RDONLY=os.O_RDONLY, O_RDWR=os.O_RDWR))
    monkeypatch.setattr(files, "Path", PureWindowsPath)
    yield state
    clear_bindings()


def events(state, name):
    return [args for kind, args in state.events if kind == name]


def test_setup_is_reused_but_all_opens_metadata_and_transfers_stay_fresh(native):
    handles = [files._windows_open(PureWindowsPath("C:/synthetic/public.bin"), directory=False)
               for _ in range(64)]
    assert len(set(handles)) == 64
    assert all(len(events(native, name)) == 64 for name in
               ("CreateFileW", "GetFileInformationByHandle", "CRT"))
    assert all(args[1:] == (0x80000000, 1, None, 3, 0x00200000, None)
               for args in events(native, "CreateFileW"))
    assert native.loads == 1 and native.symbols == 3 and native.prototypes == 4


@pytest.mark.parametrize("new_kind,code", [(4, "target_remote"), (0, "target_locality_unknown")])
def test_reused_function_still_queries_and_refuses_changed_locality(native, new_kind, code):
    native.drive_types = [3, new_kind]
    target = PureWindowsPath("C:/synthetic/public.bin")
    assert files.absolute_local_path(target) == target
    with pytest.raises(files.MaintenanceTargetError, match=code):
        files.absolute_local_path(target)
    assert len(events(native, "GetDriveTypeW")) == 2
    assert not events(native, "CreateFileW") and native.loads == 1


def test_reused_api_rechecks_handle_attributes_and_closes_a_reparse_point(native):
    target = PureWindowsPath("C:/synthetic/public.bin")
    files._windows_open(target, directory=False)
    native.reparse = True
    with pytest.raises(files.MaintenanceTargetError, match="target_unsafe"):
        files._windows_open(target, directory=False)
    assert (len(events(native, "CreateFileW"))
            == len(events(native, "GetFileInformationByHandle")) == 2)
    assert len(events(native, "CRT")) == len(events(native, "CloseHandle")) == 1


@pytest.mark.parametrize("code,exception", [(2, FileNotFoundError), (3, FileNotFoundError),
                                          (80, FileExistsError), (183, FileExistsError),
                                          (5, files.MaintenanceTargetError)])
def test_fresh_create_errors_keep_the_original_mapping_and_no_descriptor(native, code, exception):
    native.create_error = code
    with pytest.raises(exception):
        files._windows_open(PureWindowsPath("C:/synthetic/absent.bin"), directory=False)
    assert [name for name, _ in native.events] == ["CreateFileW"]


def test_failed_handle_inspection_closes_once_without_transferring_ownership(native):
    native.info_ok = False
    with pytest.raises(files.MaintenanceTargetError, match="target_unavailable"):
        files._windows_open(PureWindowsPath("C:/synthetic/public.bin"), directory=False)
    assert [name for name, _ in native.events] == [
        "CreateFileW", "GetFileInformationByHandle", "CloseHandle"]


def test_failed_crt_transfer_preserves_exception_identity_and_closes_once(native):
    original = OSError("synthetic transfer failure")
    native.transfer_error = original
    with pytest.raises(OSError) as failure:
        files._windows_open(PureWindowsPath("C:/synthetic/public.bin"), directory=False)
    assert failure.value is original
    assert [name for name, _ in native.events] == [
        "CreateFileW", "GetFileInformationByHandle", "CRT", "CloseHandle"]


def test_failed_api_construction_is_not_memoized_or_retried_within_a_call(native):
    target = PureWindowsPath("C:/synthetic/public.bin")
    native.fail_load = True
    with pytest.raises(OSError, match="synthetic loading failure"):
        files._windows_open(target, directory=False)
    assert native.loads == 1 and not native.events
    native.fail_load = False
    files._windows_open(target, directory=False)
    assert native.loads == 2 and len(events(native, "CreateFileW")) == 1


def test_module_import_does_not_load_a_windows_library(native):
    spec = importlib.util.spec_from_file_location("inert_file_api_control", files.__file__)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert native.loads == 0 and not native.events


@pytest.mark.skipif(os.name != "nt", reason="Actual Win32 fresh file handles")
def test_actual_windows_reads_replacement_bytes_with_reused_api(tmp_path):
    target = tmp_path / "current.bin"
    target.write_bytes(b"first public fixture")
    with files.open_local_file(target) as stream:
        assert stream.read() == b"first public fixture"
    api = files._windows_file_api()
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"second public fixture")
    os.replace(replacement, target)
    with files.open_local_file(target) as stream:
        assert stream.read() == b"second public fixture"
    assert files._windows_file_api() is api


@pytest.mark.skipif(os.name != "nt", reason="Actual ctypes thread-local Win32 error state")
def test_actual_windows_hot_binding_lookup_preserves_each_threads_error():
    api = files._windows_file_api()
    answers = {}

    def observe(value):
        ctypes.set_last_error(value)
        assert files._windows_file_api() is api
        answers[value] = ctypes.get_last_error()

    threads = [threading.Thread(target=observe, args=(value,)) for value in (203, 5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert answers == {203: 203, 5: 5}
