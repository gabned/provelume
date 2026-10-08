"""Worker-only OS limits. Windows network isolation is explicitly NOT_RUN."""

from __future__ import annotations

import ctypes as c
import os

MEMORY = 3 * 1024**3


def check(condition, code):
    # This bootstrap must run before imports of the application dependency graph.
    # Import closed application errors only on failure, before any native load.
    if not condition:
        from .ai_models import ModelError

        raise ModelError(code)


def contain():
    if os.name == "nt":
        return _windows()
    return _linux()


def _linux():
    import resource

    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1117320736, 1117320736))

    # x86-64 only: check audit architecture before interpreting syscall numbers.
    # EPERM for socket operations, execution and process creation. clone is allowed
    # only with CLONE_THREAD. clone3 ENOSYS lets libc fall back to checked clone.
    class Filter(c.Structure):
        _fields_ = [("code", c.c_ushort), ("jt", c.c_ubyte), ("jf", c.c_ubyte), ("k", c.c_uint)]

    rows = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xC000003E), (0x06, 0, 0, 0x80000000), (0x20, 0, 0, 0)]
    # x32 shares AUDIT_ARCH_X86_64; do not let its syscall bit bypass the filter.
    rows.extend([(0x45, 0, 1, 0x40000000), (0x06, 0, 0, 0x50001)])
    for syscall in (
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        50,
        51,
        52,
        53,
        54,
        55,
        57,
        58,
        59,
        288,
        322,
        425,  # io_uring setup/enter/register can otherwise submit socket operations.
        426,
        427,
    ):
        rows.extend([(0x15, 0, 1, syscall), (0x06, 0, 0, 0x50001)])
    rows.extend(
        [
            (0x15, 0, 1, 435),
            (0x06, 0, 0, 0x50026),
            (0x15, 0, 3, 56),
            (0x20, 0, 0, 16),
            (0x45, 1, 0, 0x10000),
            (0x06, 0, 0, 0x50001),
            (0x06, 0, 0, 0x7FFF0000),
        ]
    )
    filters = (Filter * len(rows))(*(Filter(*row) for row in rows))

    class Program(c.Structure):
        _fields_ = [("len", c.c_ushort), ("filter", c.POINTER(Filter))]

    libc = c.CDLL(None, use_errno=True)
    check(libc.prctl(38, 1, 0, 0, 0) == 0, "compatibility")
    program = Program(len(rows), filters)
    check(libc.prctl(22, 2, c.byref(program), 0, 0) == 0, "compatibility")
    return None, {
        "memory": "RLIMIT_AS",
        "memory_bytes": MEMORY,
        "cpu": "sched_setaffinity:2",
        "processes": "seccomp:thread-clone-only",
        "network_control": "seccomp:socket-syscalls-EPERM",
        "network_observation": "NOT_RUN",
    }


def _windows():
    from ctypes import wintypes as w

    class Basic(c.Structure):
        _fields_ = [
            ("process_time", c.c_int64),
            ("job_time", c.c_int64),
            ("flags", w.DWORD),
            ("min_working", c.c_size_t),
            ("max_working", c.c_size_t),
            ("active", w.DWORD),
            ("affinity", c.c_size_t),
            ("priority", w.DWORD),
            ("scheduling", w.DWORD),
        ]

    class Extended(c.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", c.c_uint64 * 6),
            ("process_memory", c.c_size_t),
            ("job_memory", c.c_size_t),
            ("peak_process", c.c_size_t),
            ("peak_job", c.c_size_t),
        ]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.CreateJobObjectW.argtypes = [P := c.c_void_p, w.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, P, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.GetProcessAffinityMask.argtypes = [w.HANDLE, P, P]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    check(bool(job), "compatibility")
    process = kernel.GetCurrentProcess()
    process_mask, system_mask = c.c_size_t(), c.c_size_t()
    try:
        check(
            bool(
                kernel.GetProcessAffinityMask(process, c.byref(process_mask), c.byref(system_mask))
            ),
            "compatibility",
        )
        cpus = [1 << n for n in range(64) if process_mask.value & (1 << n)]
        check(len(cpus) >= 2, "compatibility")
        limits = Extended()
        # ACTIVE_PROCESS, AFFINITY, PRIORITY_CLASS, PROCESS_MEMORY, JOB_MEMORY,
        # KILL_ON_JOB_CLOSE. Inference yields to normal interactive work.
        limits.basic.flags = 0x8 | 0x10 | 0x20 | 0x100 | 0x200 | 0x2000
        limits.basic.active, limits.basic.affinity = 1, cpus[0] | cpus[1]
        limits.basic.priority = 0x4000  # BELOW_NORMAL_PRIORITY_CLASS
        limits.process_memory = limits.job_memory = MEMORY
        check(
            bool(kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits))),
            "compatibility",
        )
        check(bool(kernel.AssignProcessToJobObject(job, process)), "compatibility")
    except BaseException:
        kernel.CloseHandle(job)
        raise
    # Keep the handle open for the complete worker lifetime. Process exit closes it.
    return job, {
        "memory": "JobObject:committed-memory",
        "memory_bytes": MEMORY,
        "cpu": "JobObject:affinity:2",
        "priority": "JobObject:below-normal",
        "processes": "JobObject:active-process:1",
        "network_control": "NONE",
        "network_observation": "NOT_RUN",
    }


def memory_observation():
    if os.name != "nt":
        import resource

        with open("/proc/self/statm", encoding="ascii") as stream:
            rss = int(stream.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        return {"rss": rss, "peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    from ctypes import wintypes as w

    class Counters(c.Structure):
        _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [
            (n, c.c_size_t)
            for n in (
                "peak",
                "rss",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "page",
                "peak_page",
                "private",
            )
        ]

    row = Counters()
    row.cb = c.sizeof(row)
    kernel = c.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = w.HANDLE
    psapi = c.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.c_void_p, w.DWORD]
    check(
        bool(psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), c.byref(row), row.cb)), "state"
    )
    return {"rss": row.rss, "peak_rss": row.peak, "private_bytes": row.private}
