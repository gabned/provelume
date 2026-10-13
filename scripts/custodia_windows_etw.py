"""Bounded OS observation on disposable Windows runners; no runtime authority."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def thread_snapshot():
    """Numeric PID/TID ownership only; never process arguments, names or data."""
    from ctypes import wintypes as w

    class ThreadEntry(ctypes.Structure):
        _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD),
                    ("th32ThreadID", w.DWORD), ("th32OwnerProcessID", w.DWORD),
                    ("tpBasePri", w.LONG), ("tpDeltaPri", w.LONG), ("dwFlags", w.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Thread32First.argtypes = kernel.Thread32Next.argtypes = [
        w.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.Thread32First.restype = kernel.Thread32Next.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(4, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise RuntimeError("ETW thread ownership observation unavailable")
    try:
        entry = ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        present = kernel.Thread32First(handle, ctypes.byref(entry))
        rows = []
        while present:
            rows.append({"tid": entry.th32ThreadID, "pid": entry.th32OwnerProcessID,
                         "base_priority": entry.tpBasePri})
            present = kernel.Thread32Next(handle, ctypes.byref(entry))
        if not rows:
            raise RuntimeError("Empty thread ownership observation")
        return rows
    finally:
        kernel.CloseHandle(handle)


class SchedulerCapture:
    """Three fixed en01–en04 windows; no background load or stop-on-green."""

    def __init__(self, directory, *, invoke=None, snapshot=None):
        if invoke is None and (os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true"):
            raise RuntimeError("ETW requires a disposable GitHub Windows runner")
        self.directory = Path(directory) / "scheduler"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.profile = Path(__file__).with_name("custodia-scheduler.wprp")
        self.invoke = invoke or self._invoke
        self.snapshot = snapshot or thread_snapshot
        self.sessions = []
        self.active = None

    def _invoke(self, values):
        result = subprocess.run(["wpr.exe", *values], capture_output=True, text=True,
                                timeout=60, check=False)
        with (self.directory / "wpr-control.log").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"operation": values[0], "exit_code": result.returncode,
                                  "stdout": result.stdout, "stderr": result.stderr}) + "\n")
        if result.returncode:
            # Never cancel or replace another recorder's session after a denial.
            raise RuntimeError("WPR observer operation failed; no automatic retry")

    def start(self, run, runtime):
        if self.active is not None or any(row["run"] == run for row in self.sessions):
            raise RuntimeError("Repeated or overlapping ETW window")
        row = {"run": run, "trace": f"run-{run}.etl", "purpose": "DIAGNOSTIC_ONLY",
               "start_qpc_ns": time.perf_counter_ns(), "threads_before": self.snapshot(),
               "worker_pid_before": runtime._process.pid if runtime.loaded else None}
        self.invoke(["-start", str(self.profile) + "!CustodiaScheduler"])
        self.active = row

    def stop(self, runtime):
        if self.active is None:
            return
        row = self.active
        row.update(stop_qpc_ns=time.perf_counter_ns(), threads_after=self.snapshot(),
                   worker_pid_after=runtime._process.pid if runtime.loaded else None,
                   request=runtime._request_id)
        path = self.directory / row["trace"]
        try:
            self.invoke(["-stop", str(path), "-skipPdbGen"])
            if path.exists():
                row.update(size_bytes=path.stat().st_size,
                           sha256=hashlib.sha256(path.read_bytes()).hexdigest(), status="OBSERVED")
            else:
                row["status"] = "MISSING_TRACE"
        except Exception:
            row["status"] = "STOP_FAILED"
            raise
        finally:
            self.active = None
            self.sessions.append(row)
            (self.directory / "sessions.json").write_text(
                json.dumps(self.sessions, indent=2) + "\n", encoding="utf-8")
