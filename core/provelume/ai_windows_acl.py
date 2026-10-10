"""Handle-bound read/execute grants for a verified public frozen inventory only."""

from __future__ import annotations

import ctypes as c
import os
from contextlib import contextmanager

from .ai_runtime_limits import check
from .ai_windows_api import D, P, libraries

READ_EXECUTE = 0x1200A9


class Trustee(c.Structure):
    _fields_ = [("multiple", P), ("operation", c.c_int32), ("form", c.c_int32),
                ("type", c.c_int32), ("name", P)]


class Access(c.Structure):
    _fields_ = [("permissions", D), ("mode", c.c_int32), ("inheritance", D),
                ("trustee", Trustee)]


@contextmanager
def pin_acl_path(path, *, directory):
    import msvcrt

    from .maintenance_local_files import pinned_parent

    kernel, _, _, _ = libraries()
    # Lock ancestors before capture. Retain only the selected handle after capture;
    # all public directories are independently pinned by the package owner.
    with pinned_parent(path) as (pinned, _):
        handle = kernel.CreateFileW(str(pinned), 0x1 | 0x80 | 0x20000 | 0x40000, 1,
                                    None, 3, 0x00200000 | (0x02000000 if directory else 0), None)
        check(handle != P(-1).value, "unsafe_path")
        try:
            info = (D * 13)()
            get = kernel.GetFileInformationByHandle
            get.argtypes, get.restype = [P, P], c.c_int32
            check(get(handle, c.byref(info)), "unsafe_path")
            check(not info[0] & 0x400 and bool(info[0] & 0x10) == directory, "unsafe_path")
            check(directory or info[10] == 1, "unsafe_path")  # nNumberOfLinks.
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def grant_public_read(descriptor, sid):
    import msvcrt

    kernel, advapi, _, _ = libraries()
    handle = msvcrt.get_osfhandle(descriptor)
    acl, security = P(), P()
    check(advapi.GetSecurityInfo(handle, 1, 4, None, None, c.byref(acl), None,
                                c.byref(security)) == 0, "compatibility")
    new_acl = P()
    try:
        check(acl, "compatibility")
        # ACL header: revision, padding, size, ACE count, padding.
        count = (c.c_uint16 * 4).from_address(acl.value)[2]
        found = 0
        for index in range(count):
            ace = P()
            check(advapi.GetAce(acl, index, c.byref(ace)), "compatibility")
            kind, flags = (c.c_uint8 * 2).from_address(ace.value)
            size = c.c_uint16.from_address(ace.value + 2).value
            if kind not in (0, 1) or size < 12:
                continue
            identity = P(ace.value + 8)
            check(advapi.IsValidSid(identity), "compatibility")
            if advapi.EqualSid(identity, sid):
                mask = D.from_address(ace.value + 4).value
                check(kind == 0 and not flags & 0x0F and mask & ~READ_EXECUTE == 0,
                      "compatibility")
                found |= mask
        if found == READ_EXECUTE:
            return
        access = Access(READ_EXECUTE, 1, 0, Trustee(None, 0, 0, 5, sid))
        check(advapi.SetEntriesInAclW(1, c.byref(access), acl, c.byref(new_acl)) == 0,
              "compatibility")
        check(advapi.SetSecurityInfo(handle, 1, 4, None, None, new_acl, None) == 0,
              "compatibility")
    finally:
        if new_acl:
            kernel.LocalFree(new_acl)
        if security:
            kernel.LocalFree(security)
