"""Per-read SHA-256 state; no model-byte or verification-result cache."""

from __future__ import annotations

import ctypes
import hashlib
import os
from contextlib import contextmanager, suppress

from .ai_models import check

_WINDOWS = os.name == "nt"


class WindowsSha256:
    """Use the system SHA-256 provider without changing the digest contract."""

    def __init__(self):
        self.algorithm = ctypes.c_void_p()
        self.handle = ctypes.c_void_p()
        self.library = ctypes.WinDLL("bcrypt.dll", winmode=0x00000800,
                                     use_last_error=True)  # System32 only.
        lib = self.library
        lib.BCryptOpenAlgorithmProvider.argtypes = [
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint32]
        lib.BCryptGetProperty.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_uint32]
        lib.BCryptCreateHash.argtypes = [ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        lib.BCryptHashData.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32]
        lib.BCryptFinishHash.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32]
        lib.BCryptDestroyHash.argtypes = [ctypes.c_void_p]
        lib.BCryptCloseAlgorithmProvider.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        for name in ("BCryptOpenAlgorithmProvider", "BCryptGetProperty",
                     "BCryptCreateHash", "BCryptHashData", "BCryptFinishHash",
                     "BCryptDestroyHash", "BCryptCloseAlgorithmProvider"):
            getattr(lib, name).restype = ctypes.c_int32
        try:
            check(lib.BCryptOpenAlgorithmProvider(
                ctypes.byref(self.algorithm), "SHA256", None, 0) == 0, "compatibility")
            length = self._property("ObjectLength")
            check(0 < length <= 4096 and self._property("HashDigestLength") == 32,
                  "compatibility")
            self.object = (ctypes.c_ubyte * length)()
            check(lib.BCryptCreateHash(self.algorithm, ctypes.byref(self.handle),
                self.object, length, None, 0, 0) == 0, "compatibility")
        except BaseException:
            self.close()
            raise

    def _property(self, name):
        value, count = ctypes.c_uint32(), ctypes.c_uint32()
        check(self.library.BCryptGetProperty(self.algorithm, name,
            ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(count), 0) == 0
            and count.value == ctypes.sizeof(value), "compatibility")
        return value.value

    def update(self, block):
        check(type(block) is bytes and len(block) <= 1024 * 1024, "limit")
        check(bool(self.handle.value), "state")
        # Explicit length includes embedded NULs; the bytes remain alive for this
        # synchronous call and no second MiB-sized copy is retained.
        check(self.library.BCryptHashData(self.handle, ctypes.c_char_p(block),
            len(block), 0) == 0, "integrity")

    def hexdigest(self):
        check(bool(self.handle.value), "state")
        value = (ctypes.c_ubyte * 32)()
        check(self.library.BCryptFinishHash(self.handle, value, 32, 0) == 0, "integrity")
        return bytes(value).hex()

    def close(self):
        if self.handle.value:
            self.library.BCryptDestroyHash(self.handle)
            self.handle = ctypes.c_void_p()
        if self.algorithm.value:
            self.library.BCryptCloseAlgorithmProvider(self.algorithm, 0)
            self.algorithm = ctypes.c_void_p()


@contextmanager
def model_digest():
    selected = None
    if _WINDOWS:
        # A missing platform API keeps the original full-file SHA-256 path.
        with suppress(OSError, AttributeError):
            selected = WindowsSha256()
    if selected is None:
        yield hashlib.sha256()
    else:
        try:
            yield selected
        finally:
            selected.close()
