"""Optional kernel path validation after the caller's fresh component checks."""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import stat
import sys
from functools import lru_cache
from pathlib import Path

_OPENAT2 = 437  # Linux x86-64 and arm64 syscall ABI.
_AT_FDCWD = -100
_RESOLVE_NO_MAGICLINKS = 0x02
_RESOLVE_NO_SYMLINKS = 0x04


class _OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64),
                ("resolve", ctypes.c_uint64)]


@lru_cache(maxsize=1)
def _syscall():
    # Cache the immutable libc entry point, never a path observation/result.
    function = ctypes.CDLL(None, use_errno=True).syscall
    function.restype = ctypes.c_long
    return function


def kernel_no_links(path: Path) -> bool:
    """Check the entire existing prefix without following links or reading files.

    Linux openat2 resolves components atomically with NO_SYMLINKS/NO_MAGICLINKS.
    Missing final components are permitted only below a verified directory.
    False selects the caller's original resolver on unsupported kernels/hosts;
    an observed unsafe path never selects that fallback. No result is cached.
    """
    if (sys.platform != "linux" or os.name != "posix"
            or platform.machine().lower() not in {"x86_64", "amd64", "aarch64"}
            or not hasattr(os, "O_PATH")):
        return False

    syscall = _syscall()
    how = _OpenHow(os.O_PATH | os.O_CLOEXEC, 0,
                   _RESOLVE_NO_SYMLINKS | _RESOLVE_NO_MAGICLINKS)
    current = path
    while True:
        descriptor = syscall(ctypes.c_long(_OPENAT2), ctypes.c_int(_AT_FDCWD),
                             ctypes.c_char_p(os.fsencode(current)),
                             ctypes.byref(how), ctypes.c_size_t(ctypes.sizeof(how)))
        if descriptor >= 0:
            try:
                if current != path and not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    raise OSError(errno.ENOTDIR, "Unsafe target parent")
                return True
            finally:
                os.close(descriptor)
        failure = ctypes.get_errno()
        if failure in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.EPERM}:
            return False
        if failure == errno.ENOENT and current != current.parent:
            current = current.parent
            continue
        raise OSError(failure, "Kernel target validation failed")
