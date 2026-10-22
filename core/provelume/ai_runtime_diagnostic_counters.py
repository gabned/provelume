"""Temporary read-only Windows process observations; no runtime authority or tuning.

Cycle counts remain native counts. They are not converted to time or frequency:
their interpretation depends on the processor and Windows implementation.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache

_GROUPS = ("cycles", "process_times", "io", "memory", "system_times")
_COUNTERS = {
    "cycles": ("process_cycles",),
    "process_times": ("kernel_100ns", "user_100ns"),
    "io": (
        "read_operations", "write_operations", "other_operations",
        "read_bytes", "write_bytes", "other_bytes",
    ),
    "system_times": ("idle_100ns", "kernel_100ns", "user_100ns"),
}
_MEMORY = ("page_faults", "working_set_bytes", "peak_working_set_bytes", "private_bytes")


def _unavailable(reason, *, error=None):
    value = {"status": "UNAVAILABLE", "reason": reason}
    if error is not None:
        value["error_type"] = type(error).__name__
        code = getattr(error, "winerror", None)
        if type(code) is int:
            value["win32_error"] = code
    return value


def _status(groups):
    available = sum(group.get("status") == "OBSERVED" for group in groups.values())
    return "OBSERVED" if available == len(_GROUPS) else "PARTIAL" if available else "UNAVAILABLE"


@lru_cache(maxsize=1)
def _windows_api():
    import ctypes as c
    from ctypes import wintypes as w

    class FileTime(c.Structure):
        _fields_ = [("low", w.DWORD), ("high", w.DWORD)]

        def ticks(self):
            return (self.high << 32) | self.low

    class IoCounters(c.Structure):
        _fields_ = [(name, c.c_uint64) for name in _COUNTERS["io"]]

    class MemoryCounters(c.Structure):
        _fields_ = [("cb", w.DWORD), ("page_faults", w.DWORD)] + [
            (name, c.c_size_t) for name in (
                "peak_working_set_bytes", "working_set_bytes", "peak_paged_pool_bytes",
                "paged_pool_bytes", "peak_nonpaged_pool_bytes", "nonpaged_pool_bytes",
                "pagefile_bytes", "peak_pagefile_bytes", "private_bytes",
            )
        ]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    psapi = c.WinDLL("psapi", use_last_error=True)

    def bind(library, name, result, *arguments):
        function = getattr(library, name)
        function.restype, function.argtypes = result, list(arguments)
        return function

    process = bind(kernel, "GetCurrentProcess", w.HANDLE)()
    functions = {
        "cycles": bind(kernel, "QueryProcessCycleTime", w.BOOL, w.HANDLE,
                       c.POINTER(c.c_uint64)),
        "process_times": bind(kernel, "GetProcessTimes", w.BOOL, w.HANDLE,
                              *([c.POINTER(FileTime)] * 4)),
        "io": bind(kernel, "GetProcessIoCounters", w.BOOL, w.HANDLE,
                   c.POINTER(IoCounters)),
        "memory": bind(psapi, "GetProcessMemoryInfo", w.BOOL, w.HANDLE,
                       c.POINTER(MemoryCounters), w.DWORD),
        "system_times": bind(kernel, "GetSystemTimes", w.BOOL,
                             *([c.POINTER(FileTime)] * 3)),
    }
    return c, process, functions, FileTime, IoCounters, MemoryCounters


def snapshot():
    """Observe this process only; every failed native group remains UNAVAILABLE."""
    if os.name != "nt":
        return _unavailable("WINDOWS_ONLY")
    try:
        c, process, functions, FileTime, IoCounters, MemoryCounters = _windows_api()
    except (OSError, AttributeError, TypeError) as error:
        return _unavailable("WINDOWS_API_UNAVAILABLE", error=error)

    groups = {}
    for name in _GROUPS:
        try:
            if name == "cycles":
                row = c.c_uint64()
                succeeded = functions[name](process, c.byref(row))
                values = {"process_cycles": row.value}
            elif name == "process_times":
                created, exited, kernel, user = (FileTime() for _ in range(4))
                succeeded = functions[name](process, c.byref(created), c.byref(exited),
                                            c.byref(kernel), c.byref(user))
                values = {"kernel_100ns": kernel.ticks(), "user_100ns": user.ticks()}
            elif name == "io":
                row = IoCounters()
                succeeded = functions[name](process, c.byref(row))
                values = {key: getattr(row, key) for key in _COUNTERS[name]}
            elif name == "memory":
                row = MemoryCounters()
                row.cb = c.sizeof(row)
                succeeded = functions[name](process, c.byref(row), row.cb)
                values = {key: getattr(row, key) for key in _MEMORY}
            else:
                idle, kernel, user = (FileTime() for _ in range(3))
                succeeded = functions[name](c.byref(idle), c.byref(kernel), c.byref(user))
                # The Windows kernel count includes idle time; retain it unmodified.
                values = {"idle_100ns": idle.ticks(), "kernel_100ns": kernel.ticks(),
                          "user_100ns": user.ticks()}
            if succeeded:
                groups[name] = {"status": "OBSERVED", **values}
            else:
                groups[name] = {"status": "UNAVAILABLE", "reason": "NATIVE_CALL_FAILED",
                                "win32_error": c.get_last_error()}
        except (OSError, AttributeError, TypeError, ValueError) as error:
            groups[name] = _unavailable("NATIVE_CALL_ERROR", error=error)
    return {"status": _status(groups), "pid": os.getpid(), "monotonic_ns": time.monotonic_ns(),
            "groups": groups}


def difference(before, after):
    """Subtract observed counters only; working-set gauges retain both endpoints."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return _unavailable("INVALID_SNAPSHOT")
    if before.get("status") == "UNAVAILABLE" or after.get("status") == "UNAVAILABLE":
        return {"status": "UNAVAILABLE", "reason": "SNAPSHOT_UNAVAILABLE",
                "before": before, "after": after}
    if (type(before.get("pid")) is not int or before["pid"] <= 0
            or type(after.get("pid")) is not int or after["pid"] != before["pid"]):
        return _unavailable("PROCESS_IDENTITY_MISMATCH")
    try:
        start, end = before["monotonic_ns"], after["monotonic_ns"]
        if type(start) is not int or type(end) is not int or end < start:
            return _unavailable("INVALID_SNAPSHOT_TIME")
        groups = {}
        for name in _GROUPS:
            first, last = before["groups"][name], after["groups"][name]
            if first.get("status") != "OBSERVED" or last.get("status") != "OBSERVED":
                groups[name] = {"status": "UNAVAILABLE", "reason": "COUNTER_UNAVAILABLE",
                                "before": first, "after": last}
                continue
            keys = _MEMORY if name == "memory" else _COUNTERS[name]
            if any(type(row[key]) is not int or row[key] < 0
                   for row in (first, last) for key in keys):
                groups[name] = _unavailable("INVALID_COUNTER")
                continue
            counters = ("page_faults",) if name == "memory" else keys
            if any(last[key] < first[key] for key in counters):
                # In particular, do not manufacture a 32-bit page-fault wrap count.
                groups[name] = {"status": "UNAVAILABLE", "reason": "COUNTER_DECREASED",
                                "before": first, "after": last}
                continue
            groups[name] = {"status": "OBSERVED", **{
                key + "_delta": last[key] - first[key] for key in keys
            }}
            if name == "memory":
                groups[name].update(before={key: first[key] for key in keys},
                                    after={key: last[key] for key in keys})
        return {"status": _status(groups), "pid": before["pid"], "wall_nanoseconds": end - start,
                "groups": groups}
    except (KeyError, TypeError, AttributeError):
        return _unavailable("INVALID_SNAPSHOT")
