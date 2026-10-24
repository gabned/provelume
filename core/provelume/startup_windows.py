"""Attempt-scoped Windows stop event and owned process Job; no global lock/state."""

from __future__ import annotations

import ctypes as c
import threading
from functools import lru_cache


@lru_cache(maxsize=1)
def _api():
    from ctypes import wintypes as w

    kernel = c.WinDLL("kernel32", use_last_error=True)
    for name, result, args in (
        ("CreateEventW", w.HANDLE, [c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]),
        ("OpenEventW", w.HANDLE, [w.DWORD, w.BOOL, w.LPCWSTR]),
        ("SetEvent", w.BOOL, [w.HANDLE]),
        ("WaitForSingleObject", w.DWORD, [w.HANDLE, w.DWORD]),
        ("CreateJobObjectW", w.HANDLE, [c.c_void_p, w.LPCWSTR]),
        ("SetInformationJobObject", w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]),
        ("QueryInformationJobObject", w.BOOL,
         [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]),
        ("AssignProcessToJobObject", w.BOOL, [w.HANDLE, w.HANDLE]),
        ("TerminateJobObject", w.BOOL, [w.HANDLE, w.DWORD]),
        ("CloseHandle", w.BOOL, [w.HANDLE]),
    ):
        fn = getattr(kernel, name)
        fn.restype, fn.argtypes = result, args
    return kernel


class _BasicLimits(c.Structure):
    _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", c.c_uint32),
                ("minimum_working_set", c.c_size_t), ("maximum_working_set", c.c_size_t),
                ("active_process_limit", c.c_uint32), ("affinity", c.c_size_t),
                ("priority", c.c_uint32), ("scheduling", c.c_uint32)]


class _IoCounters(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in (
        "read_operations", "write_operations", "other_operations", "read_bytes", "write_bytes",
        "other_bytes",
    )]


class _ExtendedLimits(c.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", _IoCounters), ("process_memory", c.c_size_t),
                ("job_memory", c.c_size_t), ("peak_process_memory", c.c_size_t),
                ("peak_job_memory", c.c_size_t)]


class _Accounting(c.Structure):
    _fields_ = [("user", c.c_int64), ("kernel", c.c_int64), ("period_user", c.c_int64),
                ("period_kernel", c.c_int64), ("faults", c.c_uint32),
                ("total", c.c_uint32), ("active", c.c_uint32), ("terminated", c.c_uint32)]


def _check(result):
    if not result:
        # Fixed message only; no event name, handle, PID, path, key or raw OS text.
        raise OSError("startup Windows control unavailable")
    return result


class OwnedWindowsControl:
    def __init__(self):
        # Construction has no native effects. The worker must retain this owner
        # before preparation can acquire even the first handle.
        self._event = self._job = None

    def prepare(self, name):
        if self._event is not None or self._job is not None:
            raise OSError("startup control already prepared")
        kernel = _api()
        self._event = _check(kernel.CreateEventW(None, True, False, name))
        if c.get_last_error() == 183:
            raise OSError("startup event already exists")
        self._job = _check(kernel.CreateJobObjectW(None, None))
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no CPU/memory/process-count limits.
        _check(kernel.SetInformationJobObject(self._job, 9, c.byref(limits), c.sizeof(limits)))

    def assign(self, process):
        # Assignment precedes bootstrap delivery, hence every application worker.
        # The supported frozen runtime is onedir, with this process as the backend.
        _check(_api().AssignProcessToJobObject(self._job, int(process._handle)))

    def request_stop(self):
        _check(_api().SetEvent(self._event))

    def terminate(self):
        _check(_api().TerminateJobObject(self._job, 1))

    def process_count(self):
        info = _Accounting()
        _check(_api().QueryInformationJobObject(self._job, 1, c.byref(info), c.sizeof(info), None))
        return int(info.active)

    def empty(self):
        return self.process_count() == 0

    def close(self):
        for attribute in ("_event", "_job"):
            handle = getattr(self, attribute, None)
            if handle is not None:
                if not _api().CloseHandle(handle):
                    # Invalid now is an observed absent handle; never retry its
                    # numeric value after another thread could reuse it.
                    if c.get_last_error() == 6:
                        setattr(self, attribute, None)
                    raise OSError("startup Windows handle close unconfirmed")
                setattr(self, attribute, None)


class ChildStopSignal:
    def __init__(self, name):
        self._handle = _check(_api().OpenEventW(0x100000, False, name))  # SYNCHRONIZE only.

    def close(self):
        if self._handle is not None:
            _check(_api().CloseHandle(self._handle))
            self._handle = None

    def run(self, server):
        done = threading.Event()
        error = threading.Event()

        def watch():
            while not done.is_set():
                result = _api().WaitForSingleObject(self._handle, 100)
                if result == 0:
                    server.should_exit = True
                    return
                if result != 258:  # WAIT_TIMEOUT
                    error.set()
                    server.should_exit = True
                    return

        worker = threading.Thread(target=watch, name="ProvelumeOwnedStop", daemon=True)
        worker.start()
        try:
            server.run()
        finally:
            done.set()
            # Never close a native wait handle while its owned waiter is active.
            # The parent retains its bounded escalation over the whole Job.
            while worker.is_alive():
                worker.join(timeout=0.25)
            self.close()
        return not error.is_set()
