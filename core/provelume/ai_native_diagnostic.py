"""Temporary opt-in native observations for the fixed S06 experiment only.

These helpers grant no authority and change no ordinary runtime default. Native
intervals include synchronization and callback overhead; they are not named
operation timings. Thread counters do not establish running, ready or wait state.
"""

from __future__ import annotations

import ctypes as c
import heapq
import os
import threading
import time
from contextlib import contextmanager
from functools import lru_cache


def _unavailable(reason, error=None):
    row = {"status": "UNAVAILABLE", "reason": reason}
    if error is not None:
        row["error_type"] = type(error).__name__
        code = getattr(error, "winerror", None)
        if type(code) is int:
            row["win32_error"] = code
    return row


@contextmanager
def blocktime(libomp, mode):
    """Observe default or temporarily set zero on the already verified libomp.

    The caller must keep inference and its idle window inside this context on
    the same native thread. No environment variable, thread count, affinity,
    priority, model or verification rule is changed here.
    """
    if os.name != "nt" or mode not in {"default", "blocktime0"}:
        raise ValueError("Unsupported native diagnostic mode")
    get = libomp.kmp_get_blocktime
    get.restype, get.argtypes = c.c_int, []
    set_value = libomp.kmp_set_blocktime
    set_value.restype, set_value.argtypes = None, [c.c_int]
    original = get()
    if original < 0:
        raise RuntimeError("Native blocktime unavailable")
    row = {"status": "OBSERVED", "mode": mode,
           "thread_id": threading.get_native_id(), "original_ms": original,
           "requested_ms": original if mode == "default" else 0,
           "restored": False}
    try:
        if mode == "blocktime0":
            set_value(0)
        row["observed_ms"] = get()
        if row["observed_ms"] != row["requested_ms"]:
            raise RuntimeError("Native blocktime readback mismatch")
        yield row
    finally:
        if mode == "blocktime0":
            set_value(original)
        row["restored_ms"] = get()
        row["restored"] = row["restored_ms"] == original
        if not row["restored"]:
            raise RuntimeError("Native blocktime restoration failed")


class NativeIntervals:
    """Bounded observations from the native after-node abort callback.

    The callback always returns false, including on an observation error. It
    requests no tensor materialization and does not split or change the graph.
    Call start immediately before a prefill decode, finish immediately after.
    """

    def __init__(self):
        self.active = False
        self.callback = c.CFUNCTYPE(c.c_bool, c.c_void_p)(self._after_node)

    def start(self):
        if self.active:
            raise RuntimeError("Native observation already active")
        self.count = 0
        self.errors = {}
        self.wall_top = []
        self.thread_top = []
        self.wall_sum = self.thread_sum = 0
        self.callback_wall = self.callback_thread = 0
        self.thread_id = threading.get_native_id()
        self.started = self.last_wall = time.monotonic_ns()
        self.last_thread = time.thread_time_ns()
        self.active = True

    @staticmethod
    def _top(heap, measure, index, wall, cpu):
        item = (measure, index, wall, cpu)
        if len(heap) < 16:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)

    def _after_node(self, _):
        if not self.active:
            return False
        try:
            wall, cpu = time.monotonic_ns(), time.thread_time_ns()
            if threading.get_native_id() != self.thread_id:
                raise RuntimeError("Native callback thread changed")
            interval_wall, interval_cpu = wall - self.last_wall, cpu - self.last_thread
            if interval_wall < 0 or interval_cpu < 0:
                raise RuntimeError("Native observation clock decreased")
            self.count += 1
            self.wall_sum += interval_wall
            self.thread_sum += interval_cpu
            self._top(self.wall_top, interval_wall, self.count, interval_wall, interval_cpu)
            self._top(self.thread_top, interval_cpu, self.count, interval_wall, interval_cpu)
            self.last_wall, self.last_thread = time.monotonic_ns(), time.thread_time_ns()
            self.callback_wall += self.last_wall - wall
            self.callback_thread += self.last_thread - cpu
        except BaseException as error:
            # Never let ctypes substitute an undefined C result for an escaped
            # Python exception; external authority/resource limits still apply.
            name = type(error).__name__
            self.errors[name] = self.errors.get(name, 0) + 1
        return False

    def finish(self):
        if not self.active:
            raise RuntimeError("Native observation inactive")
        self.active = False
        wall, cpu = time.monotonic_ns(), time.thread_time_ns()

        def rows(heap):
            return [{"interval_index": index, "wall_ns": duration, "thread_cpu_ns": thread}
                    for _, index, duration, thread in sorted(heap, reverse=True)]

        status = "PARTIAL" if self.errors else "OBSERVED" if self.count else "UNAVAILABLE"
        return {"status": status,
                "thread_id": self.thread_id, "interval_count": self.count,
                "decode_wall_ns": wall - self.started,
                "interval_wall_ns": self.wall_sum, "interval_thread_cpu_ns": self.thread_sum,
                "tail_wall_ns": wall - self.last_wall,
                "tail_thread_cpu_ns": cpu - self.last_thread,
                "callback_body_wall_ns": self.callback_wall,
                "callback_body_thread_cpu_ns": self.callback_thread,
                "top16_wall": rows(self.wall_top), "top16_thread_cpu": rows(self.thread_top),
                "errors": self.errors,
                "interpretation": "intervals include prior synchronization; no opcode attribution"}


@lru_cache(maxsize=1)
def _thread_api():
    from ctypes import wintypes as w

    class Entry(c.Structure):
        _fields_ = [(name, kind) for name, kind in (
            ("size", w.DWORD), ("usage", w.DWORD), ("thread_id", w.DWORD),
            ("owner_pid", w.DWORD), ("base_priority", w.LONG),
            ("delta_priority", w.LONG), ("flags", w.DWORD))]

    class FileTime(c.Structure):
        _fields_ = [("low", w.DWORD), ("high", w.DWORD)]

        def ticks(self):
            return self.low | (self.high << 32)

    kernel = c.WinDLL("kernel32", use_last_error=True)

    def bind(name, result, *arguments):
        function = getattr(kernel, name)
        function.restype, function.argtypes = result, list(arguments)
        return function

    functions = {
        "snapshot": bind("CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD),
        "first": bind("Thread32First", w.BOOL, w.HANDLE, c.POINTER(Entry)),
        "next": bind("Thread32Next", w.BOOL, w.HANDLE, c.POINTER(Entry)),
        "open": bind("OpenThread", w.HANDLE, w.DWORD, w.BOOL, w.DWORD),
        "pid": bind("GetProcessIdOfThread", w.DWORD, w.HANDLE),
        "times": bind("GetThreadTimes", w.BOOL, w.HANDLE,
                      *([c.POINTER(FileTime)] * 4)),
        "cycles": bind("QueryThreadCycleTime", w.BOOL, w.HANDLE, c.POINTER(c.c_uint64)),
        "priority": bind("GetThreadPriority", c.c_int, w.HANDLE),
        "close": bind("CloseHandle", w.BOOL, w.HANDLE),
    }
    return functions, Entry, FileTime


def _one_thread(functions, FileTime, identifier):
    handle = functions["open"](0x0800, False, identifier)  # QUERY_LIMITED_INFORMATION only
    if not handle:
        return {"status": "UNAVAILABLE", "reason": "OPEN_THREAD_FAILED",
                "win32_error": c.get_last_error()}
    try:
        if functions["pid"](handle) != os.getpid():
            return _unavailable("THREAD_OWNER_CHANGED")
        created, exited, kernel, user = (FileTime() for _ in range(4))
        if not functions["times"](handle, c.byref(created), c.byref(exited),
                                  c.byref(kernel), c.byref(user)):
            return {"status": "UNAVAILABLE", "reason": "THREAD_TIMES_FAILED",
                    "win32_error": c.get_last_error()}
        cycles = c.c_uint64()
        if not functions["cycles"](handle, c.byref(cycles)):
            return {"status": "UNAVAILABLE", "reason": "THREAD_CYCLES_FAILED",
                    "win32_error": c.get_last_error()}
        priority = functions["priority"](handle)
        if priority == 0x7FFFFFFF:
            return {"status": "UNAVAILABLE", "reason": "THREAD_PRIORITY_FAILED",
                    "win32_error": c.get_last_error()}
        return {"status": "OBSERVED", "created_100ns": created.ticks(),
                "exited_100ns": exited.ticks(), "kernel_100ns": kernel.ticks(),
                "user_100ns": user.ticks(), "cycles": cycles.value, "priority": priority}
    finally:
        functions["close"](handle)


def thread_snapshot():
    """Retain own-PID thread identities/counters; do not suspend or tune threads."""
    if os.name != "nt":
        return _unavailable("WINDOWS_ONLY")
    started = time.monotonic_ns()
    try:
        functions, Entry, FileTime = _thread_api()
        handle = functions["snapshot"](4, 0)  # TH32CS_SNAPTHREAD
        if handle == c.c_void_p(-1).value:
            return {"status": "UNAVAILABLE", "reason": "THREAD_SNAPSHOT_FAILED",
                    "win32_error": c.get_last_error()}
        rows = {}
        enumeration_error = None
        try:
            entry = Entry()
            entry.size = c.sizeof(entry)
            more = functions["first"](handle, c.byref(entry))
            while more:
                if entry.owner_pid == os.getpid():
                    if len(rows) >= 4096:
                        enumeration_error = "THREAD_LIMIT"
                        break
                    rows[str(entry.thread_id)] = _one_thread(functions, FileTime, entry.thread_id)
                entry.size = c.sizeof(entry)
                more = functions["next"](handle, c.byref(entry))
            if not more and c.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                enumeration_error = c.get_last_error()
        finally:
            functions["close"](handle)
        complete = enumeration_error is None and bool(rows)
        observed = complete and all(row["status"] == "OBSERVED" for row in rows.values())
        return {"status": "OBSERVED" if observed else "PARTIAL", "pid": os.getpid(),
                "started_ns": started, "completed_ns": time.monotonic_ns(),
                "threads": rows, "enumeration_error": enumeration_error}
    except (OSError, AttributeError, TypeError, ValueError) as error:
        return _unavailable("THREAD_API_ERROR", error)


def thread_difference(before, after):
    """Subtract only same-created observed threads, retaining every endpoint."""
    if (not isinstance(before, dict) or not isinstance(after, dict)
            or before.get("pid") != os.getpid() or after.get("pid") != os.getpid()
            or before.get("status") not in {"OBSERVED", "PARTIAL"}
            or after.get("status") not in {"OBSERVED", "PARTIAL"}):
        return {"status": "UNAVAILABLE", "reason": "SNAPSHOT_UNAVAILABLE",
                "before": before, "after": after}
    rows = {}
    for identifier in sorted(set(before["threads"]) | set(after["threads"]), key=int):
        first, last = before["threads"].get(identifier), after["threads"].get(identifier)
        reason = None
        if first is None:
            reason = "NEW_THREAD"
        elif last is None:
            reason = "EXITED_THREAD"
        elif first.get("status") != "OBSERVED" or last.get("status") != "OBSERVED":
            reason = "COUNTER_UNAVAILABLE"
        elif first["created_100ns"] != last["created_100ns"]:
            reason = "THREAD_ID_REUSED"
        elif any(last[key] < first[key] for key in ("kernel_100ns", "user_100ns", "cycles")):
            reason = "COUNTER_DECREASED"
        if reason:
            rows[identifier] = {"status": "UNAVAILABLE", "reason": reason,
                                "before": first, "after": last}
        else:
            rows[identifier] = {"status": "OBSERVED", "created_100ns": first["created_100ns"],
                                **{key + "_delta": last[key] - first[key]
                                   for key in ("kernel_100ns", "user_100ns", "cycles")},
                                "priority_before": first["priority"],
                                "priority_after": last["priority"]}
    observed = (before["status"] == after["status"] == "OBSERVED"
                and all(row["status"] == "OBSERVED" for row in rows.values()))
    return {"status": "OBSERVED" if observed else "PARTIAL", "pid": os.getpid(),
            "threads": rows, "before": before, "after": after,
            "interpretation": "own-thread accounting only; scheduling state unobserved"}


def observe_request(engine, request, emit):
    """Explicit diagnostic branch: native work plus a fixed 300ms idle window."""
    from .ai_llama import P, bind
    from .ai_runtime_diagnostic_counters import difference, snapshot

    mode = request["diagnostic_blocktime"]
    intervals = NativeIntervals()
    set_abort = bind(engine.lib, "llama_set_abort_callback", None, P, P, P)
    engine._native_intervals = intervals
    try:
        with blocktime(engine._dependencies[0], mode) as setting:
            set_abort(engine.context, c.cast(intervals.callback, P), None)
            result = engine.generate(request["prompt"], emit, scope=request.get("scope"),
                                     response_format=request.get("response_format"))
            set_abort(engine.context, None, None)
            # No inference, hashing or helper busy loop in this planned window.
            # Account all own native worker CPU while the request thread sleeps.
            thread_before = thread_snapshot()
            before = snapshot()
            started = time.monotonic()
            time.sleep(0.3)
            elapsed = time.monotonic() - started
            after = snapshot()
            thread_after = thread_snapshot()
            result["diagnostic_native"] = {
                "status": "DIAGNOSTIC", "qualification": "NOT_QUALIFIED",
                "blocktime": setting, "idle_planned_seconds": 0.3,
                "idle_wall_seconds": elapsed,
                "idle_process_counters": difference(before, after),
                "idle_thread_counters": thread_difference(thread_before, thread_after),
            }
        return result
    finally:
        set_abort(engine.context, None, None)
        del engine._native_intervals
