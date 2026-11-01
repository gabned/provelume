"""Windows-only, handle-bound input exit. Unsupported hosts retain the input.

POSIX unlinkat cannot condition deletion on an open inode against an arbitrary
concurrent writer. Do not substitute an advisory lock or a check-then-unlink.
"""

import ctypes
import os
import stat
from contextlib import contextmanager
from functools import lru_cache

from .maintenance_local_files import (
    MaintenanceTargetError,
    _windows_file_api,
    directory_binding,
    file_identity,
    pinned_parent,
)


@lru_cache(maxsize=1)
def _disposition_api():
    from ctypes import wintypes

    function = _windows_file_api().SetFileInformationByHandle
    function.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    function.restype = wintypes.BOOL
    return function


@contextmanager
def guarded_input_exit(path, expected_identity):
    if os.name != "nt":
        raise MaintenanceTargetError("inbox_exit_platform_unqualified")
    import msvcrt
    from ctypes import wintypes

    with pinned_parent(path) as (path, _parent):
        kernel = _windows_file_api()
        # GENERIC_READ | DELETE, no sharing: refuse existing readers, writers and
        # deleters. OPEN_REPARSE_POINT inspects the selected entry itself.
        native = kernel.CreateFileW(str(path), 0x80010000, 0, None, 3, 0x00200000, None)
        if native == ctypes.c_void_p(-1).value:
            raise MaintenanceTargetError("inbox_input_unavailable")
        info = (wintypes.DWORD * 13)()
        if not kernel.GetFileInformationByHandle(native, ctypes.byref(info)):
            kernel.CloseHandle(native)
            raise MaintenanceTargetError("target_unavailable")
        if info[0] & (0x400 | 0x10) or info[10] != 1:
            kernel.CloseHandle(native)
            raise MaintenanceTargetError("target_unsafe")
        try:
            descriptor = msvcrt.open_osfhandle(native, os.O_BINARY | os.O_RDONLY)
        except BaseException:
            kernel.CloseHandle(native)
            raise
        with os.fdopen(descriptor, "rb") as handle:
            observed = os.fstat(handle.fileno())
            if (not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1
                    or file_identity(handle) != expected_identity):
                raise MaintenanceTargetError("inbox_input_changed")

            def remove():
                # FILE_DISPOSITION_INFO uses a one-byte BOOLEAN, not Win32 BOOL.
                disposition = ctypes.c_ubyte(1)
                if not _disposition_api()(native, 4, ctypes.byref(disposition), 1):
                    raise MaintenanceTargetError("inbox_disposition_failed")

            yield handle, remove
        # fdclose is the deletion boundary. A failure propagates; it is never
        # reported as a confirmed exit. No second path-based deletion is issued.


def remove_empty_directory(path, expected_binding):
    """Disposition of this exact directory; the kernel refuses a nonempty one."""
    if os.name != "nt":
        raise MaintenanceTargetError("inbox_exit_platform_unqualified")
    import msvcrt
    from ctypes import wintypes

    with pinned_parent(path) as (path, _parent):
        kernel = _windows_file_api()
        native = kernel.CreateFileW(str(path), 0x10001, 0, None, 3, 0x02200000, None)
        if native == ctypes.c_void_p(-1).value:
            raise MaintenanceTargetError("inbox_directory_unavailable")
        info = (wintypes.DWORD * 13)()
        if (not kernel.GetFileInformationByHandle(native, ctypes.byref(info))
                or info[0] & 0x400 or not info[0] & 0x10):
            kernel.CloseHandle(native)
            raise MaintenanceTargetError("target_unsafe")
        try:
            descriptor = msvcrt.open_osfhandle(native, os.O_BINARY | os.O_RDONLY)
        except BaseException:
            kernel.CloseHandle(native)
            raise
        try:
            if directory_binding(descriptor) != expected_binding:
                raise MaintenanceTargetError("target_changed")
            disposition = ctypes.c_ubyte(1)
            if not _disposition_api()(native, 4, ctypes.byref(disposition), 1):
                raise MaintenanceTargetError("inbox_directory_not_empty")
        finally:
            os.close(descriptor)
