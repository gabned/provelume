"""Closed Windows ABI for the installed, capability-free AI worker."""

from __future__ import annotations

import ctypes as c
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from .ai_runtime_limits import check

P, D, B, W, H = c.c_void_p, c.c_uint32, c.c_int32, c.c_wchar_p, c.c_void_p
SIZE = c.c_size_t


def local_app_data():
    """Resolve the current user's OS profile root, without copying ambient env.

    AppContainer creation needs LOCALAPPDATA even with an explicit Unicode
    environment. The path is not an access grant: only the verified public
    inventory receives read/execute ACLs, never this private parent directory.
    """
    shell = c.WinDLL("shell32", use_last_error=True)
    ole = c.WinDLL("ole32", use_last_error=True)
    folder = c.create_string_buffer(UUID("F1B32785-6FBA-4FCF-9D55-7B8E7F157091").bytes_le)
    result = W()
    get = bind(shell, "SHGetKnownFolderPath", c.c_int32, P, D, H, P)
    free = bind(ole, "CoTaskMemFree", None, P)
    check(get(folder, 0, None, c.byref(result)) == 0, "compatibility")
    try:
        value = result.value
        check(value and len(value) <= 32767 and Path(value).is_absolute()
              and not value.startswith("\\\\"), "compatibility")
        return value
    finally:
        free(c.cast(result, P))


class SidAttributes(c.Structure):
    _fields_ = [("sid", P), ("attributes", D)]


class Capabilities(c.Structure):
    _fields_ = [("sid", P), ("capabilities", P), ("count", D), ("reserved", D)]


class JobBasic(c.Structure):
    _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", D),
                ("min_working", SIZE), ("max_working", SIZE), ("active", D),
                ("affinity", SIZE), ("priority", D), ("scheduling", D)]


class JobExtended(c.Structure):
    _fields_ = [("basic", JobBasic), ("io", c.c_uint64 * 6), ("process_memory", SIZE),
                ("job_memory", SIZE), ("peak_process", SIZE), ("peak_job", SIZE)]


class Startup(c.Structure):
    _fields_ = [("cb", D), ("reserved", W), ("desktop", W), ("title", W)] + [
        (name, D) for name in ("x", "y", "x_size", "y_size", "x_chars", "y_chars",
                               "fill", "flags")] + [
        ("show", c.c_uint16), ("reserved_bytes", c.c_uint16), ("reserved_data", P),
        ("stdin", H), ("stdout", H), ("stderr", H)]


class StartupExtended(c.Structure):
    _fields_ = [("startup", Startup), ("attributes", P)]


class ProcessInfo(c.Structure):
    _fields_ = [("process", H), ("thread", H), ("pid", D), ("tid", D)]


def bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype, function.argtypes = result, list(arguments)
    return function


@lru_cache(maxsize=1)
def libraries():
    kernel = c.WinDLL("kernel32", use_last_error=True)
    advapi = c.WinDLL("advapi32", use_last_error=True)
    userenv = c.WinDLL("userenv", use_last_error=True)
    firewall = c.WinDLL("FirewallAPI", use_last_error=True)
    for name, result, args in (
        ("CloseHandle", B, (H,)), ("GetCurrentProcess", H, ()),
        ("GetProcessHeap", H, ()), ("HeapFree", B, (H, D, P)), ("LocalFree", P, (P,)),
        ("CreateJobObjectW", H, (P, W)),
        ("SetInformationJobObject", B, (H, c.c_int, P, D)),
        ("QueryInformationJobObject", B, (H, c.c_int, P, D, P)),
        ("IsProcessInJob", B, (H, H, P)),
        ("GetProcessAffinityMask", B, (H, P, P)),
        ("DuplicateHandle", B, (H, H, H, P, D, B, D)),
        ("SetHandleInformation", B, (H, D, D)),
        ("InitializeProcThreadAttributeList", B, (P, D, D, P)),
        ("UpdateProcThreadAttribute", B, (P, D, SIZE, P, SIZE, P, P)),
        ("DeleteProcThreadAttributeList", None, (P,)),
        ("CreateProcessW", B, (W, W, P, P, B, D, P, W, P, P)),
        ("ResumeThread", D, (H,)), ("WaitForSingleObject", D, (H, D)),
        ("GetExitCodeProcess", B, (H, P)), ("TerminateJobObject", B, (H, D)),
        ("CreateFileW", H, (W, D, D, P, D, D, H)),
        ("GetFileType", D, (H,)), ("GetStdHandle", H, (c.c_int32,)),
        ("GetModuleHandleW", H, (W,)), ("FindResourceW", H, (H, P, P)),
        ("SizeofResource", D, (H, H)), ("LoadResource", H, (H, H)),
        ("LockResource", P, (H,)),
    ):
        bind(kernel, name, result, *args)
    for name, result, args in (
        ("OpenProcessToken", B, (H, D, P)),
        ("GetTokenInformation", B, (H, c.c_int, P, D, P)),
        ("EqualSid", B, (P, P)), ("IsValidSid", B, (P,)), ("FreeSid", P, (P,)),
        ("GetSecurityInfo", D, (H, D, D, P, P, P, P, P)),
        ("SetSecurityInfo", D, (H, D, D, P, P, P, P)),
        ("SetEntriesInAclW", D, (D, P, P, P)), ("GetAce", B, (P, D, P)),
    ):
        bind(advapi, name, result, *args)
    bind(userenv, "CreateAppContainerProfile", c.c_int32, W, W, W, P, D, P)
    bind(userenv, "DeriveAppContainerSidFromAppContainerName", c.c_int32, W, P)
    bind(userenv, "DeleteAppContainerProfile", c.c_int32, W)
    bind(firewall, "NetworkIsolationGetAppContainerConfig", D, P, P)
    return kernel, advapi, userenv, firewall


def no_loopback_exemption(sid):
    kernel, advapi, _, firewall = libraries()
    count, entries = D(), P()
    check(firewall.NetworkIsolationGetAppContainerConfig(c.byref(count), c.byref(entries)) == 0,
          "compatibility")
    try:
        check(count.value <= 65536 and (bool(entries) or count.value == 0), "compatibility")
        values = c.cast(entries, c.POINTER(SidAttributes))
        for index in range(count.value):
            check(advapi.IsValidSid(values[index].sid), "compatibility")
            check(not advapi.EqualSid(values[index].sid, sid), "compatibility")
    finally:
        # SDK ownership: each SID, then its containing array, from the process heap.
        if entries:
            values = c.cast(entries, c.POINTER(SidAttributes))
            for index in range(count.value):
                kernel.HeapFree(kernel.GetProcessHeap(), 0, values[index].sid)
            kernel.HeapFree(kernel.GetProcessHeap(), 0, entries)


def verify_token(process, *, expected_sid=None, observe_loopback=True):
    kernel, advapi, _, _ = libraries()
    token = H()
    check(advapi.OpenProcessToken(process, 0x0008, c.byref(token)), "compatibility")
    try:
        def info(kind):
            size = D()
            check(not advapi.GetTokenInformation(token, kind, None, 0, c.byref(size))
                  and c.get_last_error() == 122 and 0 < size.value <= 65536, "compatibility")
            buffer = c.create_string_buffer(size.value)
            check(advapi.GetTokenInformation(token, kind, buffer, size.value, c.byref(size)),
                  "compatibility")
            return buffer

        container = info(29)  # TokenIsAppContainer.
        check(D.from_buffer(container).value == 1, "compatibility")
        capabilities = info(30)  # TOKEN_GROUPS count followed by SID_AND_ATTRIBUTES.
        check(D.from_buffer(capabilities).value == 0, "compatibility")
        identity = info(31)  # TOKEN_APPCONTAINER_INFORMATION.
        sid = P.from_buffer(identity).value
        check(sid and advapi.IsValidSid(sid), "compatibility")
        if expected_sid is not None:
            check(advapi.EqualSid(sid, expected_sid), "compatibility")
        if observe_loopback:
            no_loopback_exemption(sid)
        return {"network_control": ("AppContainer:no-capabilities-no-loopback-exemption"
                                    if observe_loopback else "AppContainer:no-capabilities"),
                "token_appcontainer": True, "token_capabilities": 0,
                "loopback_exemption": False if observe_loopback else "NOT_OBSERVED"}
    finally:
        kernel.CloseHandle(token)


def create_job():
    from .ai_runtime_cpu import windows_pair
    from .ai_runtime_limits import MEMORY

    kernel, _, _, _ = libraries()
    allowed, system = SIZE(), SIZE()
    check(kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), c.byref(allowed),
                                       c.byref(system)), "compatibility")
    cpus, topology = windows_pair(kernel, allowed.value)
    limits = JobExtended()
    limits.basic.flags = 0x8 | 0x10 | 0x20 | 0x100 | 0x200 | 0x2000
    limits.basic.active, limits.basic.affinity = 1, sum(1 << cpu for cpu in cpus)
    limits.basic.priority = 0x4000
    limits.process_memory = limits.job_memory = MEMORY
    job = kernel.CreateJobObjectW(None, None)
    check(job, "compatibility")
    if not kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)):
        kernel.CloseHandle(job)
        check(False, "compatibility")
    return job, topology


def verify_job(process, job=None):
    from .ai_runtime_limits import MEMORY

    kernel, _, _, _ = libraries()
    member = B()
    check(kernel.IsProcessInJob(process, job, c.byref(member)) and member.value, "compatibility")
    limits = JobExtended()
    check(kernel.QueryInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits), None),
          "compatibility")
    required = 0x8 | 0x10 | 0x20 | 0x100 | 0x200 | 0x2000
    check(limits.basic.flags & required == required and limits.basic.active == 1
          and limits.basic.affinity.bit_count() == 2 and limits.basic.priority == 0x4000
          and limits.process_memory == limits.job_memory == MEMORY, "compatibility")
    return {"memory": "JobObject:committed-memory", "memory_bytes": MEMORY,
            "cpu": "JobObject:affinity:2", "priority": "JobObject:below-normal",
            "processes": "JobObject:active-process:1", "job_at_creation": True,
            "parent_owned_job": True}
