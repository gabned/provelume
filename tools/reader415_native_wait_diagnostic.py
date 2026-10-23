"""Temporary, target-only observations. Ordinary pytest results remain authoritative.

Loaded by PYTEST_PLUGINS in both complete, unchanged Windows shard groups.
No retries, new child reader, forced Node exit, timeout change, or qualification.
"""

from __future__ import annotations

import ctypes
import hashlib
import inspect
import json
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

TARGET = (
    "tests/test_mobile_shell_contract.py::"
    "test_share_error_reads_only_existing_language_preference_and_falls_back_on_unavailable_store"
)
PARENT = "3c29ab05acef576d7dcdb4c0301200ee0d4bd078"
PLAN_PATH = "scripts/reader415_native_wait_plan.json"
ALLOWED = {
    ".github/workflows/reader415-native-wait-diagnostic.yml",
    "tools/reader415_native_wait_diagnostic.py",
    "tools/reader415_native_capture.py",
    PLAN_PATH,
}
ROOT = Path(__file__).resolve().parents[1]
STATE = {
    "errors": [],
    "error_count": 0,
    "target_invocations": 0,
    "status": "OBSERVABILITY_INCOMPLETE",
    "events": [],
    "samples": [],
}
OUT = None
PLAN = None
CONTROL_MODE = False
PLUGIN_ENVIRONMENT = None


def error(stage, exc):
    STATE["error_count"] += 1
    if len(STATE["errors"]) < 64:
        STATE["errors"].append(
            {"stage": stage, "type": type(exc).__name__, "message": str(exc)[:1024]}
        )


def observe(stage, function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except BaseException as exc:
        error(stage, exc)
        return None


def event(stage, **fields):
    if len(STATE["events"]) >= 64:
        error("parent_event_cap", RuntimeError("64 parent events exhausted"))
        return
    STATE["events"].append(
        {
            "stage": stage,
            "monotonic_ns": time.monotonic_ns(),
            "perf_counter_ns": time.perf_counter_ns(),
            "utc_epoch_ns": time.time_ns(),
            **fields,
        }
    )


def digest(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def retain_once(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)


def git(*arguments):
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *arguments],
        text=True,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
    ).strip()


def source_identity():
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(parents) == 2 and parents[1] == PARENT
    assert not git("status", "--porcelain", "--untracked-files=no")
    changes = git("diff", "--name-status", "--no-renames", PARENT, "HEAD").splitlines()
    assert {line.split("\t")[1] for line in changes} == ALLOWED
    assert all(line.startswith("A\t") for line in changes)
    assert parents[0] == os.environ["GITHUB_SHA"]
    assert os.environ["GITHUB_EVENT_NAME"] == "push"
    for relative, expected in PLAN["original_source_sha256"].items():
        assert digest(ROOT / relative)["sha256"] == expected
    assert digest(Path(__file__))["sha256"] == PLAN["plugin_sha256"]
    return {
        "head": parents[0],
        "parent": parents[1],
        "tree": git("rev-parse", "HEAD^{tree}"),
        "changes": changes,
        "original_source_sha256": PLAN["original_source_sha256"],
    }


def save_output(label, value):
    if value is None:
        return {"python_type": "NoneType", "value": None}
    if isinstance(value, bytes):
        raw, representation = value, "EXACT_PYTHON_BYTES_OBJECT"
    elif isinstance(value, str):
        raw, representation = (
            value.encode("utf-8", "surrogatepass"),
            "PYTHON_STR_UTF8_SURROGATEPASS_NOT_RAW_OS_PIPE_BYTES",
        )
    else:
        raise TypeError("Unexpected subprocess output object")
    path = OUT / (label + ".output")
    retain_once(path, raw)
    return {**digest(path), "python_type": type(value).__name__, "representation": representation}


def exception_record(exc):
    return {
        "python_type": type(exc).__name__,
        "object_id_in_this_process": id(exc),
        "message": str(exc),
        "timeout": getattr(exc, "timeout", None),
        "stdout": save_output("exception-stdout", getattr(exc, "stdout", None)),
        "stderr": save_output("exception-stderr", getattr(exc, "stderr", None)),
    }


def native_snapshot(process_handle, threads):
    """Query existing handles only; API errors stay absent/error, never synthetic zero."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE(int(process_handle))
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.GetThreadTimes.argtypes = kernel.GetProcessTimes.argtypes
    kernel.GetThreadTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    kernel.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IoCounters)]
    kernel.GetProcessIoCounters.restype = wintypes.BOOL

    def times(function, selected):
        fields = [wintypes.FILETIME() for _ in range(4)]
        if not function(selected, *(ctypes.byref(value) for value in fields)):
            return {"available": False, "winerror": ctypes.get_last_error()}
        return {
            "available": True,
            **dict(
                zip(
                    (
                        "creation_filetime_100ns",
                        "exit_filetime_100ns",
                        "kernel_100ns",
                        "user_100ns",
                    ),
                    [(value.dwHighDateTime << 32) | value.dwLowDateTime for value in fields],
                    strict=True,
                )
            ),
        }

    result = {"process_times": times(kernel.GetProcessTimes, handle), "reader_threads": []}
    counters = IoCounters()
    if kernel.GetProcessIoCounters(handle, ctypes.byref(counters)):
        result["process_io"] = {
            "available": True,
            **{name: getattr(counters, name) for name, _ in counters._fields_},
        }
    else:
        result["process_io"] = {"available": False, "winerror": ctypes.get_last_error()}
    for name, thread in threads:
        row = {"stream": name, "created": thread is not None}
        if thread is not None:
            row.update(
                observed_monotonic_ns=time.monotonic_ns(),
                observed_perf_counter_ns=time.perf_counter_ns(),
                alive=thread.is_alive(),
                python_ident=thread.ident,
                native_id=thread.native_id,
            )
            if not row["alive"]:
                row["times"] = {"available": False, "reason": "ENDED_READER_NO_TID_REUSE_QUERY"}
                result["reader_threads"].append(row)
                continue
            selected = kernel.OpenThread(0x0800, False, thread.native_id or 0)
            if selected:
                try:
                    row["times"] = times(kernel.GetThreadTimes, selected)
                finally:
                    if not kernel.CloseHandle(selected):
                        row["close_error"] = ctypes.get_last_error()
            else:
                row["times"] = {"available": False, "winerror": ctypes.get_last_error()}
            row["alive_after_native_query"] = thread.is_alive()
            row["times_identity_stable_during_query"] = row["alive_after_native_query"]
        result["reader_threads"].append(row)
    return result


def extended_native_snapshot(process_handle, child_pid):
    """Point-in-time Windows counters; unavailable, partial and reused IDs stay explicit."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE(int(process_handle))
    attempts = {}

    def api(name, arguments, result):
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result

        def call(*values):
            attempts[name] = attempts.get(name, 0) + 1
            return function(*values)

        return call

    close = api("CloseHandle", [wintypes.HANDLE], wintypes.BOOL)
    system_times = api("GetSystemTimes", [ctypes.POINTER(wintypes.FILETIME)] * 3, wintypes.BOOL)
    process_id = api("GetProcessId", [wintypes.HANDLE], wintypes.DWORD)
    process_times = api(
        "GetProcessTimes",
        [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4,
        wintypes.BOOL,
    )
    thread_times = api(
        "GetThreadTimes", [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL
    )
    open_thread = api(
        "OpenThread", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
    )
    thread_owner = api("GetProcessIdOfThread", [wintypes.HANDLE], wintypes.DWORD)
    group_count = api("GetActiveProcessorGroupCount", [], wintypes.WORD)
    processor_count = api("GetActiveProcessorCount", [wintypes.WORD], wintypes.DWORD)

    def filetimes(function, selected):
        values = [wintypes.FILETIME() for _ in range(4)]
        if not function(selected, *(ctypes.byref(value) for value in values)):
            return {"available": False, "winerror": ctypes.get_last_error()}
        return {
            "available": True,
            **dict(
                zip(
                    (
                        "creation_filetime_100ns",
                        "exit_filetime_100ns",
                        "kernel_100ns",
                        "user_100ns",
                    ),
                    [(value.dwHighDateTime << 32) | value.dwLowDateTime for value in values],
                    strict=True,
                )
            ),
        }

    actual_pid = int(process_id(handle))
    pid_error = ctypes.get_last_error() if not actual_pid else None
    result = {
        "extended_api_attempts": attempts,
        "api_attempts_scope": (
            "EXTENDED_ONLY_EXCLUDES_BASE_PROCESS_IO_AND_READER_APIS_NOT_TOTAL_ROUND_COUNT"
        ),
        "process_id_from_handle": actual_pid,
        "process_id_query": {"available": bool(actual_pid), "winerror": pid_error},
        "process_identity": filetimes(process_times, handle),
    }
    result["original_process_identity_verified"] = (
        result["process_id_from_handle"] == child_pid
        and result["process_identity"].get("available") is True
        and result["process_identity"].get("creation_filetime_100ns", 0) > 0
    )
    system = [wintypes.FILETIME() for _ in range(3)]
    if system_times(*(ctypes.byref(value) for value in system)):
        result["system_times"] = {
            "available": True,
            "kernel_includes_idle": True,
            "scope": "SYSTEM_PROCESSOR_GROUP_APPLICABILITY_NOT_NODE_SCHEDULER_CAUSE",
            **dict(
                zip(
                    ("idle_100ns", "kernel_100ns", "user_100ns"),
                    [(value.dwHighDateTime << 32) | value.dwLowDateTime for value in system],
                    strict=True,
                )
            ),
        }
    else:
        result["system_times"] = {"available": False, "winerror": ctypes.get_last_error()}
    groups = int(group_count())
    group_error = ctypes.get_last_error() if not groups else None
    processors = int(processor_count(0xFFFF))
    processor_error = ctypes.get_last_error() if not processors else None
    result["processor_groups"] = {
        "available": groups > 0 and processors > 0,
        "active_groups": groups,
        "group_query_winerror": group_error,
        "python_cpu_count": os.cpu_count(),
        "all_groups_active_processors": processors,
        "processor_query_winerror": processor_error,
        "multi_group_GetSystemTimes_scope_unverified": groups != 1,
    }

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "ullTotalPhys",
                "ullAvailPhys",
                "ullTotalPageFile",
                "ullAvailPageFile",
                "ullTotalVirtual",
                "ullAvailVirtual",
                "ullAvailExtendedVirtual",
            )
        ]

    memory = MemoryStatus()
    memory.dwLength = ctypes.sizeof(memory)
    global_memory = api("GlobalMemoryStatusEx", [ctypes.POINTER(MemoryStatus)], wintypes.BOOL)
    if global_memory(ctypes.byref(memory)):
        result["global_memory"] = {
            "available": True,
            **{name: getattr(memory, name) for name, _ in memory._fields_},
        }
    else:
        result["global_memory"] = {"available": False, "winerror": ctypes.get_last_error()}

    class ProcessMemory(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
                "PrivateUsage",
            )
        ]

    try:
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemory),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = ProcessMemory()
        counters.cb = ctypes.sizeof(counters)
        attempts["GetProcessMemoryInfo"] = 1
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            result["child_memory"] = {
                "available": True,
                "PageFaultCount_is_not_hard_fault_count": True,
                **{name: getattr(counters, name) for name, _ in counters._fields_},
            }
        else:
            result["child_memory"] = {"available": False, "winerror": ctypes.get_last_error()}
    except BaseException as exc:
        result["child_memory"] = {
            "available": False,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }

    class ThreadEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    create_snapshot = api(
        "CreateToolhelp32Snapshot", [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE
    )
    first = api("Thread32First", [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)], wintypes.BOOL)
    following = api("Thread32Next", [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)], wintypes.BOOL)
    inventory = {
        "available": False,
        "complete_point_in_time_enumeration": False,
        "system_row_cap": 4096,
        "child_thread_cap": 64,
        "rows_examined": 0,
        "threads": [],
        "transient_threads_not_historically_covered": True,
        "errors": [],
    }
    result["child_threads"] = inventory
    if not result["original_process_identity_verified"]:
        inventory["errors"].append({"stage": "unverified_original_process_birth_identity"})
    selected = create_snapshot(0x00000004, 0)
    if selected == ctypes.c_void_p(-1).value or not selected:
        inventory["winerror"] = ctypes.get_last_error()
        return result
    try:
        entry = ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = first(selected, ctypes.byref(entry))
        while found:
            inventory["rows_examined"] += 1
            if entry.th32OwnerProcessID == child_pid:
                if len(inventory["threads"]) >= 64:
                    inventory["errors"].append(
                        {"stage": "child_thread_cap", "tid": int(entry.th32ThreadID)}
                    )
                else:
                    row = {
                        "tid": int(entry.th32ThreadID),
                        "snapshot_owner_pid": int(entry.th32OwnerProcessID),
                        "parent_process_creation_filetime_100ns": result["process_identity"].get(
                            "creation_filetime_100ns"
                        ),
                    }
                    inventory["threads"].append(row)
                    thread = open_thread(0x0800, False, entry.th32ThreadID)
                    if thread:
                        try:
                            row["owner_pid_from_handle"] = int(thread_owner(thread))
                            row["owner_pid_query"] = {
                                "available": bool(row["owner_pid_from_handle"]),
                                "winerror": ctypes.get_last_error()
                                if not row["owner_pid_from_handle"]
                                else None,
                            }
                            row["times"] = filetimes(thread_times, thread)
                            row["identity_verified"] = (
                                result["original_process_identity_verified"]
                                and row["owner_pid_from_handle"] == child_pid
                                and row["times"]["available"]
                                and row["times"].get("creation_filetime_100ns", 0) > 0
                            )
                            if not row["identity_verified"]:
                                inventory["errors"].append(
                                    {"stage": "thread_identity", "tid": row["tid"]}
                                )
                        finally:
                            if not close(thread):
                                inventory["errors"].append(
                                    {"stage": "close_thread", "winerror": ctypes.get_last_error()}
                                )
                    else:
                        row.update(identity_verified=False, winerror=ctypes.get_last_error())
                        inventory["errors"].append(
                            {"stage": "open_thread", "tid": row["tid"], "winerror": row["winerror"]}
                        )
            if inventory["rows_examined"] >= 4096:
                inventory["errors"].append({"stage": "system_thread_enumeration_cap"})
                break
            entry.dwSize = ctypes.sizeof(entry)
            found = following(selected, ctypes.byref(entry))
        if not found:
            final_error = ctypes.get_last_error()
            if final_error != 18:
                inventory["errors"].append({"stage": "enumeration_end", "winerror": final_error})
            else:
                inventory["available"] = True
                if not inventory["threads"]:
                    inventory["errors"].append(
                        {"stage": "no_child_threads_observed_no_complete_coverage_claim"}
                    )
                inventory["complete_point_in_time_enumeration"] = not inventory["errors"]
    finally:
        if not close(selected):
            inventory["errors"].append(
                {"stage": "close_snapshot", "winerror": ctypes.get_last_error()}
            )
            inventory["complete_point_in_time_enumeration"] = False
    return result


def observed_run(arguments, **kwargs):
    """Execute actual runtime run.__code__, replacing ONLY its private Popen binding."""
    try:
        assert kwargs == {"cwd": ROOT, "capture_output": True, "text": True, "timeout": 30}
        assert isinstance(arguments, list) and len(arguments) == 2
        script = Path(arguments[1])
        assert script.suffix == ".mjs"
        assert script.parent == (OUT if CONTROL_MODE else ROOT / ".agent/node-tests")
    except BaseException as exc:
        error("run_shape", exc)
        return subprocess.run(arguments, **kwargs)
    observe(
        "copy_actual_mjs", lambda: retain_once(OUT / "actual-instrumented.mjs", script.read_bytes())
    )
    observe(
        "run_enter",
        event,
        "SUBPROCESS_RUN_ENTER",
        argv=arguments,
        kwargs={**kwargs, "cwd": str(kwargs["cwd"])},
        inherited_stdin=True,
    )

    class ObservedPopen(subprocess.Popen):
        def __init__(self, *args, **options):
            observe("popen_before", event, "POPEN_ENTER")
            super().__init__(*args, **options)
            self._diag_monitor = None
            self._diag_stop = observe("create_monitor_stop", threading.Event)
            observe("popen_after", event, "POPEN_RETURN", pid=self.pid)

            def sample(stage):
                wall, highres, cpu = (
                    time.monotonic_ns(),
                    time.perf_counter_ns(),
                    time.thread_time_ns(),
                )
                poll_before = self.poll()
                poll_before_at = time.monotonic_ns()
                poll_before_perf = time.perf_counter_ns()
                data = native_snapshot(
                    self._handle,
                    [
                        (name, getattr(self, name + "_thread", None))
                        for name in ("stdout", "stderr")
                    ],
                )
                data["extended_native"] = observe(
                    "extended_native_snapshot", extended_native_snapshot, self._handle, self.pid
                )
                poll_after = self.poll()
                poll_after_at = time.monotonic_ns()
                poll_after_perf = time.perf_counter_ns()
                data.update(
                    stage=stage,
                    monotonic_ns=wall,
                    perf_counter_ns=highres,
                    utc_epoch_ns=time.time_ns(),
                    parent_process_cpu_ns=time.process_time_ns(),
                    poll_before_returncode=poll_before,
                    poll_before_monotonic_ns=poll_before_at,
                    poll_before_perf_counter_ns=poll_before_perf,
                    poll_after_returncode=poll_after,
                    poll_after_monotonic_ns=poll_after_at,
                    poll_after_perf_counter_ns=poll_after_perf,
                    observer_wall_ns=time.monotonic_ns() - wall,
                    observer_perf_counter_ns=time.perf_counter_ns() - highres,
                    observer_thread_cpu_ns=time.thread_time_ns() - cpu,
                )
                return data

            self._diag_sample = sample

            def monitor():
                import msvcrt

                from reader415_native_capture import bounded_capture, process_birth

                last_signature, last_progress = None, time.perf_counter_ns()
                capture_attempted = False
                due = time.monotonic_ns()
                due_perf = time.perf_counter_ns()
                for ordinal in range(121):
                    if self._diag_stop.wait(max(0, (due - time.monotonic_ns()) / 1e9)):
                        return
                    row = observe("sample", sample, "PERIODIC")
                    if row is not None:
                        row.update(
                            ordinal=ordinal,
                            scheduled_monotonic_ns=due,
                            lag_ns=row["monotonic_ns"] - due,
                            scheduled_perf_counter_ns=due_perf,
                            perf_counter_lag_ns=row["perf_counter_ns"] - due_perf,
                        )
                    due += 250_000_000
                    due_perf += 250_000_000
                    now = time.monotonic_ns()
                    missed = max(0, (now - due) // 250_000_000 + 1) if now > due else 0
                    due += missed * 250_000_000
                    due_perf += missed * 250_000_000
                    if row is not None:
                        row["missed_next_ticks"] = missed
                        STATE["samples"].append(row)
                    marker = OUT / "node-markers.jsonl"
                    signature = marker.stat().st_size if marker.exists() else 0
                    now_parent = time.perf_counter_ns()
                    if signature != last_signature:
                        last_signature, last_progress = signature, now_parent
                    if (
                        not capture_attempted
                        and now_parent - last_progress >= 5_000_000_000
                        and not self._diag_stop.is_set()
                    ):
                        capture_attempted = True

                        def capture_once(
                            now_parent=now_parent,
                            last_progress=last_progress,
                            signature=signature,
                            row=row,
                        ):
                            # A durable exclusive request precedes the sole capture episode.
                            record = {
                                "trigger_perf_ns": now_parent,
                                "last_progress_perf_ns": last_progress,
                                "parent_clock": "perf_counter_ns",
                                "stalled_ns": now_parent - last_progress,
                                "last_marker_bytes": signature,
                                "pid": self.pid,
                                "poll_before": self.poll(),
                            }
                            retain_once(
                                OUT / "native-trigger.json", (json.dumps(record) + "\n").encode()
                            )
                            readers = []
                            for r in (row or {}).get("reader_threads", []):
                                if r.get("alive_after_native_query") and r.get("times", {}).get(
                                    "available"
                                ):
                                    readers.append(
                                        {
                                            "tid": r["native_id"],
                                            "birth": r["times"]["creation_filetime_100ns"],
                                        }
                                    )
                            request = {
                                "pid": self.pid,
                                "birth": process_birth(self._handle),
                                "parent_pid": os.getpid(),
                                "parent_birth": process_birth(-1),
                                "readers": readers,
                                "pipes": [
                                    {"stream": label, "handle": msvcrt.get_osfhandle(pipe.fileno())}
                                    for label, pipe in (
                                        ("stdout", self.stdout),
                                        ("stderr", self.stderr),
                                    )
                                ],
                            }
                            STATE["native_capture"] = bounded_capture(
                                request, OUT / "native-capture"
                            )

                        observe("single_native_capture", capture_once)
                if not self._diag_stop.is_set():
                    error(
                        "sampling_cap",
                        RuntimeError("121 periodic samples exhausted; one reserved for pre-kill"),
                    )

            def start():
                self._diag_monitor = threading.Thread(
                    target=lambda: observe("monitor_loop", monitor),
                    daemon=True,
                    name="reader415-node-observer",
                )
                self._diag_monitor.start()

            if self._diag_stop is not None:
                observe("start_monitor", start)

        def communicate(self, *args, **options):
            observe("communicate_enter", event, "COMMUNICATE_ENTER", timeout=options.get("timeout"))
            try:
                return super().communicate(*args, **options)
            except subprocess.TimeoutExpired as exc:
                value = observe("prekill_sample", self._diag_sample, "TIMEOUT_BEFORE_RUN_KILL")
                STATE["timeout_before_kill"] = value
                observe("timeout", event, "TIMEOUT_BEFORE_RUN_KILL", exception_id=id(exc))

                def checkpoint():
                    wall, highres, cpu = (
                        time.monotonic_ns(),
                        time.perf_counter_ns(),
                        time.thread_time_ns(),
                    )
                    retain_once(
                        OUT / "timeout-before-kill.json",
                        (json.dumps(STATE, indent=2) + "\n").encode("utf-8"),
                    )
                    STATE["timeout_checkpoint_cost"] = {
                        "wall_ns": time.monotonic_ns() - wall,
                        "perf_counter_ns": time.perf_counter_ns() - highres,
                        "caller_thread_cpu_ns": time.thread_time_ns() - cpu,
                    }

                observe("prekill_checkpoint", checkpoint)
                raise
            finally:
                observe("communicate_leave", event, "COMMUNICATE_LEAVE")

        def kill(self):
            observe(
                "kill_before",
                lambda: event("RUN_KILL_ENTER", pid=self.pid, poll_returncode=self.poll()),
            )
            return super().kill()

        def __exit__(self, *args):
            try:
                return super().__exit__(*args)
            finally:

                def stop():
                    if self._diag_stop is not None:
                        self._diag_stop.set()
                    if self._diag_monitor is not None:
                        self._diag_monitor.join(timeout=0.5)
                        STATE["monitor_alive_after_cleanup"] = self._diag_monitor.is_alive()
                        if self._diag_monitor.is_alive():
                            error(
                                "monitor_cleanup", RuntimeError("Monitor did not stop within0.5s")
                            )
                    observe("popen_exit", event, "POPEN_CONTEXT_EXIT", returncode=self.returncode)

                observe("monitor_cleanup", stop)

    actual = subprocess.run
    try:
        assert not actual.__code__.co_freevars and actual.__closure__ is None
        environment = {**actual.__globals__, "Popen": ObservedPopen}
        clone = types.FunctionType(
            actual.__code__, environment, actual.__name__, actual.__defaults__, actual.__closure__
        )
        clone.__kwdefaults__ = actual.__kwdefaults__
        assert clone.__code__ is actual.__code__ and actual.__globals__["Popen"] is subprocess.Popen
        STATE["stdlib_run"] = {
            "same_code_object": True,
            "global_override_only": ["Popen"],
            "kwdefaults_retained": clone.__kwdefaults__ == actual.__kwdefaults__,
            "source_sha256": hashlib.sha256(inspect.getsource(actual).encode()).hexdigest(),
        }
    except BaseException as exc:
        error("clone_actual_run", exc)
        return actual(arguments, **kwargs)
    try:
        result = clone(arguments, **kwargs)
    except BaseException as exc:

        def retain(selected):
            STATE["original_exception"] = exception_record(selected)

        observe("exception_record", retain, exc)
        raise
    else:
        observe(
            "result_outputs",
            lambda: STATE.update(
                result={
                    "returncode": result.returncode,
                    "stdout": save_output("result-stdout", result.stdout),
                    "stderr": save_output("result-stderr", result.stderr),
                }
            ),
        )
        return result


NODE_PREAMBLE = r"""
const __rd_path=__MARKER_PATH__;
let __rd_fd=null,__rd_count=0,__rd_previous=null,__rd_errors=0;
try{__rd_fd=__rd_open(__rd_path,'wx');}catch(__rd_e){__rd_errors++;}
function __rd_event(stage,extra={}){
 try{
  if(__rd_fd===null||__rd_count>=48)return;
  const begin=process.hrtime.bigint(),cpu=process.cpuUsage();
  const row={stage,ordinal:__rd_count++,pid:process.pid,ppid:process.ppid,
   hrtime_ns:String(begin),utc:new Date().toISOString(),node_version:process.version,
   cpu_usage_us:cpu,
   previous_marker_write_cost:__rd_previous,observer_errors:__rd_errors,...extra};
  if(['USER_MODULE_BODY_ENTERED','ASSERTIONS_DONE','BEFORE_EXIT','EXIT'].includes(stage)){
   row.active_resource_types=typeof process.getActiveResourcesInfo==='function'
    ?process.getActiveResourcesInfo():null;
  }
  const body=JSON.stringify(row)+'\n';
  __rd_write(__rd_fd,body);
  __rd_previous={wall_ns:String(process.hrtime.bigint()-begin),cpu_us:process.cpuUsage(cpu),
   bytes:Buffer.byteLength(body)};
 }catch(__rd_e){__rd_errors++;}
}
process.on('beforeExit',code=>__rd_event('BEFORE_EXIT',{code}));
process.on('exit',code=>{
 __rd_event('EXIT',{code});try{if(__rd_fd!==null)__rd_close(__rd_fd);}catch(__rd_e){}
});
process.on('uncaughtExceptionMonitor',(e,origin)=>__rd_event('UNCAUGHT_EXCEPTION_MONITOR',
 {origin,error_name:e?.name,error_message:String(e?.message).slice(0,1024)}));
__rd_event('USER_MODULE_BODY_ENTERED');
"""


def instrument(script):
    assert (
        "__rd_" not in script
        and hashlib.sha256(script.encode()).hexdigest() == PLAN["target_script_sha256"]
    )
    original = OUT / "original-target-script.mjs"
    retain_once(original, script.encode("utf-8"))
    marker = OUT / "node-markers.jsonl"
    replacements = [
        (
            "import {readFileSync} from 'node:fs';",
            "import {readFileSync,openSync as __rd_open,writeSync as __rd_write,"
            "closeSync as __rd_close} from 'node:fs';\n"
            + NODE_PREAMBLE.replace("__MARKER_PATH__", json.dumps(str(marker))),
        ),
        (
            "const scope={URL,Response,TextEncoder,setTimeout,clearTimeout,",
            "__rd_event('SCOPE_CONSTRUCTION_ENTER');\n"
            "let __rd_url,__rd_response;\nconst scope={URL:(()=>{"
            "__rd_event('URL_LOOKUP_ENTER');"
            "let before=null,cpu=null;try{before=process.hrtime.bigint();"
            "cpu=process.cpuUsage();}catch(e){__rd_errors++;}"
            "let value;try{value=URL;}catch(original){"
            "__rd_event('URL_LOOKUP_RAISED');throw original;}"
            "try{const after=process.hrtime.bigint(),after_cpu=process.cpuUsage();"
            "__rd_event('URL_LOOKUP_RETURN',{lookup_hrtime_ns:String(after),lookup_cpu_usage_us:after_cpu,"
            "lookup_before_hrtime_ns:before===null?null:String(before),lookup_before_cpu_usage_us:cpu});"
            "}catch(e){__rd_errors++;}__rd_url=value;return value;})(),Response:(()=>{"
            "__rd_event('RESPONSE_LOOKUP_ENTER');"
            "let before=null,cpu=null;try{before=process.hrtime.bigint();"
            "cpu=process.cpuUsage();}catch(e){__rd_errors++;}"
            "let value;try{value=Response;}catch(original){"
            "__rd_event('RESPONSE_LOOKUP_RAISED');throw original;}"
            "try{const after=process.hrtime.bigint(),after_cpu=process.cpuUsage();"
            "const d=Object.getOwnPropertyDescriptor(globalThis,'Response');"
            "const descriptor=d?{own:true,configurable:d.configurable,enumerable:d.enumerable,"
            "kind:Object.hasOwn(d,'value')?'data':'accessor',value_type:typeof d.value,"
            "getter_type:typeof d.get,setter_type:typeof d.set,writable:d.writable}:{own:false};"
            "__rd_event('RESPONSE_LOOKUP_RETURN',{lookup_hrtime_ns:String(after),lookup_cpu_usage_us:after_cpu,"
            "lookup_before_hrtime_ns:before===null?null:String(before),lookup_before_cpu_usage_us:cpu,descriptor});"
            "}catch(e){__rd_errors++;}__rd_response=value;return value;})(),"
            "TextEncoder,setTimeout,clearTimeout,",
        ),
        (
            "vm.createContext(scope);vm.runInContext(",
            "__rd_event('SCOPE_READY_RESPONSE_EXPOSED',{captured_url_identity:scope.URL===__rd_url,"
            "captured_constructor_identity:scope.Response===__rd_response});scope.__rd_event=__rd_event;\n"
            "__rd_event('VM_ENTER');vm.createContext(scope);vm.runInContext(",
        ),
        (
            "';self.test={shareLanguage,shareError};',scope);",
            "';{const original=shareLanguage;let count=0;shareLanguage=function(...args){"
            'const ordinal=++count;__rd_event("LANGUAGE_ENTER",{call:ordinal});let result;'
            "try{result=original.apply(this,args);}catch(error){"
            '__rd_event("LANGUAGE_RAISED",{call:ordinal});throw error;}'
            'return result.then(value=>{__rd_event("LANGUAGE_RETURN",{call:ordinal});'
            'return value;},error=>{__rd_event("LANGUAGE_RAISED",{call:ordinal});throw error;});};}'
            "self.test={shareLanguage,shareError};',scope);\n__rd_event('VM_READY');",
        ),
        (
            "assert.match(await response.text(),/Partajare/);",
            "__rd_event('RESPONSE_TEXT_ENTER');const __rd_text=await response.text();"
            "__rd_event('RESPONSE_TEXT_RETURN');assert.match(__rd_text,/Partajare/);",
        ),
        (
            "console.log(JSON.stringify({preference_only:true,no_database_creation:true,localized_error:true}));",
            "__rd_event('ASSERTIONS_DONE');__rd_event('STDOUT_BEFORE');\nconsole.log(JSON.stringify({preference_only:true,no_database_creation:true,localized_error:true}));\n__rd_event('STDOUT_AFTER',{writable_need_drain:process.stdout.writableNeedDrain});",
        ),
    ]
    for before, after in replacements:
        assert script.count(before) == 1, before
        script = script.replace(before, after)
    retain_once(OUT / "instrumented-target-template.mjs", script.encode("utf-8"))
    return script


def clock_information():
    return {
        name: {
            "implementation": value.implementation,
            "resolution_seconds": value.resolution,
            "monotonic": value.monotonic,
            "adjustable": value.adjustable,
        }
        for name in ("monotonic", "perf_counter", "process_time", "thread_time")
        for value in [time.get_clock_info(name)]
    }


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Remove only this already-loaded temporary plugin from future test children."""
    global PLUGIN_ENVIRONMENT

    def remove_own_environment():
        global PLUGIN_ENVIRONMENT
        present = "PYTEST_PLUGINS" in os.environ
        previous = os.environ.get("PYTEST_PLUGINS")
        selected = "reader415_native_wait_diagnostic"
        parts = previous.split(",") if previous is not None else []
        remaining = [part for part in parts if part.strip() != selected]
        removed = len(parts) != len(remaining)
        PLUGIN_ENVIRONMENT = {"present": present, "value": previous, "removed_own_entry": removed}
        if removed:
            if remaining:
                os.environ["PYTEST_PLUGINS"] = ",".join(remaining)
            else:
                os.environ.pop("PYTEST_PLUGINS", None)
        STATE["temporary_plugin_environment"] = {
            "before": {"present": present, "value": previous},
            "after_configure": {
                "present": "PYTEST_PLUGINS" in os.environ,
                "value": os.environ.get("PYTEST_PLUGINS"),
            },
            "removed_only_exact_entry": selected,
            "removed": removed,
            "restoration_phase": "PYTEST_UNCONFIGURE_AFTER_TEST_AND_SESSION_TEARDOWN",
        }

    observe("remove_own_plugin_environment", remove_own_environment)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    def restore_environment():
        if PLUGIN_ENVIRONMENT is None:
            return
        before = {
            "present": "PYTEST_PLUGINS" in os.environ,
            "value": os.environ.get("PYTEST_PLUGINS"),
        }
        if PLUGIN_ENVIRONMENT["present"]:
            os.environ["PYTEST_PLUGINS"] = PLUGIN_ENVIRONMENT["value"]
        else:
            os.environ.pop("PYTEST_PLUGINS", None)
        record = {
            "phase": "PYTEST_UNCONFIGURE_AFTER_TEST_AND_SESSION_TEARDOWN",
            "before_restore": before,
            "after_restore": {
                "present": "PYTEST_PLUGINS" in os.environ,
                "value": os.environ.get("PYTEST_PLUGINS"),
            },
            "original": PLUGIN_ENVIRONMENT,
            "perf_counter_ns": time.perf_counter_ns(),
            "utc_epoch_ns": time.time_ns(),
        }
        STATE["plugin_environment_restored"] = record
        if OUT is not None:
            retain_once(
                OUT / "environment-restoration.json", (json.dumps(record, indent=2) + "\n").encode()
            )

    try:
        observe("restore_plugin_environment_at_unconfigure", restore_environment)
    finally:
        final_clock = observe("unconfigure_final_clock", time.perf_counter_ns)
        record = {
            "phase": "FINAL_PYTEST_UNCONFIGURE_AFTER_OBSERVATIONS",
            "status": "COMPLETE" if not STATE["error_count"] else "OBSERVABILITY_INCOMPLETE",
            "error_count": STATE["error_count"],
            "errors": list(STATE["errors"]),
            "actual_environment": {
                "present": "PYTEST_PLUGINS" in os.environ,
                "value": os.environ.get("PYTEST_PLUGINS"),
            },
            "original_environment": PLUGIN_ENVIRONMENT,
            "restore_record": STATE.get("plugin_environment_restored"),
            "perf_counter_ns": final_clock,
            "qualification": "NOT_GRANTED",
        }

        def persist_final():
            if OUT is None:
                raise RuntimeError("No observation directory exists for the final restore record")
            retain_once(
                OUT / "unconfigure-final.json", (json.dumps(record, indent=2) + "\n").encode()
            )

        observe("persist_unconfigure_final", persist_final)
        if STATE["error_count"] or OUT is None:
            record.update(
                status="OBSERVABILITY_INCOMPLETE",
                error_count=STATE["error_count"],
                errors=list(STATE["errors"]),
            )
            observe(
                "unconfigure_final_stderr",
                print,
                "READER415_UNCONFIGURE_FINAL=" + json.dumps(record),
                file=sys.stderr,
            )


def pytest_sessionstart(session):
    global OUT, PLAN

    def prepare():
        global OUT, PLAN
        base = Path(os.environ["READER415_NODE_BOUNDARY_OUTPUT"])
        OUT = base / ("pytest-" + str(os.getpid()))
        OUT.mkdir(parents=True, exist_ok=False)
        PLAN = json.loads((ROOT / PLAN_PATH).read_text(encoding="utf-8"))
        assert PLAN["schema"] == "reader415-native-wait-plan/v1"
        STATE.update(
            schema="reader415-node-boundary-observations/v3",
            source_before=source_identity(),
            python=sys.version,
            platform=sys.platform,
            scope="DIAGNOSTIC_ONLY_NOT_QUALIFICATION",
            run_id=os.environ["GITHUB_RUN_ID"],
            run_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
            github_event=os.environ["GITHUB_EVENT_NAME"],
            argv=sys.argv,
            stdlib_run_source=inspect.getsource(subprocess.run),
            clock_information=clock_information(),
            status_semantics="MECHANICAL_COLLECTION_ONLY_EACH_FIELD_AVAILABILITY_AND_COVERAGE_REMAIN_EXPLICIT_NOT_ALL_COUNTERS_COMPLETE",
        )
        assert sys.platform == "win32"

    observe("session_prepare", prepare)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    if item.nodeid != TARGET or PLAN is None or OUT is None:
        yield
        return

    def prepare_binding():
        original = item.module.node
        globals_map = original.__globals__
        old_subprocess = globals_map["subprocess"]
        STATE["target_invocations"] += 1
        STATE["original_node_alias_identity"] = id(original)
        return original, globals_map, old_subprocess

    binding = observe("prepare_target_binding", prepare_binding)
    if binding is None:
        yield
        return
    original, globals_map, old_subprocess = binding

    def wrapper(script, *args):
        STATE["helper_invocations"] = STATE.get("helper_invocations", 0) + 1
        if STATE["helper_invocations"] != 1:
            error("target_repeated", RuntimeError("Unexpected additional target invocation"))
            return original(script, *args)
        observe("helper_enter", event, "ORIGINAL_HELPER_ENTER")
        modified = observe("instrument", instrument, script)
        if modified is None:
            return original(script, *args)

        def install_proxy():
            globals_map["subprocess"] = types.SimpleNamespace(run=observed_run)

        observe("install_subprocess_proxy", install_proxy)
        try:
            return original(modified, *args)
        finally:
            observe("restore_subprocess", globals_map.__setitem__, "subprocess", old_subprocess)
            observe("helper_leave", event, "ORIGINAL_HELPER_LEAVE")

    observe("install_node_alias", setattr, item.module, "node", wrapper)
    try:
        yield
    finally:
        observe("restore_node_alias", setattr, item.module, "node", original)
        observe("restore_subprocess_final", globals_map.__setitem__, "subprocess", old_subprocess)
        STATE["bindings_restored"] = (
            item.module.node is original and globals_map["subprocess"] is old_subprocess
        )


def finish_observations(exitstatus=None, finalize=None):
    def markers():
        if STATE["target_invocations"]:
            marker = OUT / "node-markers.jsonl"
            if marker.exists():
                assert marker.stat().st_size <= 128 * 1024
                STATE["node_marker_file"] = digest(marker)
                rows = [
                    json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()
                ]
                assert len(rows) <= 48
                STATE["node_markers"] = rows
                if any(row.get("observer_errors") for row in rows):
                    error("node_observer", RuntimeError("Node reported instrumentation errors"))
            else:
                error(
                    "node_marker_file", FileNotFoundError("No Node progress markers were recorded")
                )

    def metrics():
        value = STATE.get("timeout_before_kill")
        if STATE.get("original_exception", {}).get("python_type") == "TimeoutExpired":
            if value is None:
                raise RuntimeError("Required pre-kill snapshot was not recorded")
            if not all(value[key]["available"] for key in ("process_times", "process_io")):
                raise RuntimeError(
                    "Required pre-kill process metrics unavailable; raw errors retained"
                )
            if any(
                row.get("alive_after_native_query") and not row.get("times", {}).get("available")
                for row in value["reader_threads"]
            ):
                raise RuntimeError("A live reader's pre-kill CPU metrics are unavailable")
            extended = value.get("extended_native")
            if extended is None or not all(
                extended.get(key, {}).get("available")
                for key in ("system_times", "global_memory", "child_memory", "process_identity")
            ):
                raise RuntimeError(
                    "Required pre-kill extended counters unavailable; raw errors retained"
                )
            if not extended.get("child_threads", {}).get("complete_point_in_time_enumeration"):
                raise RuntimeError(
                    "Pre-kill child thread census partial; no full-history coverage claim"
                )

    def persist():
        retain_once(OUT / "observations.json", (json.dumps(STATE, indent=2) + "\n").encode("utf-8"))

    try:
        if exitstatus is not None:
            STATE["ordinary_pytest_exitstatus"] = int(exitstatus)
        STATE["source_after"] = observe("source_after", source_identity)
        observe("node_marker_parse", markers)
        observe("prekill_metric_availability", metrics)
        if finalize is not None:
            observe("artificial_control_classification", finalize, STATE)
        versions = {row["node_version"] for row in STATE.get("node_markers", [])}
        drift = sys.version_info[:3] != (3, 12, 10) or bool(versions - {"v22.23.4"})
        STATE["runtime_comparability"] = (
            "NONCOMPARABLE_RUNTIME_DRIFT"
            if drift
            else (
                "MATCHES_HISTORICAL"
                if versions
                else "NODE_RUNTIME_NOT_OBSERVED_IN_THIS_PYTEST_PROCESS"
            )
        )
        STATE["node_versions_observed_in_this_pytest_process"] = sorted(versions)
    except BaseException as exc:
        error("session_finish", exc)
    finally:
        STATE["status"] = "COMPLETE" if not STATE["error_count"] else "OBSERVABILITY_INCOMPLETE"
        STATE["qualification"] = "NOT_GRANTED"
        observe("persist_observations", persist)
        if STATE["error_count"]:
            observe(
                "last_resort_error_log",
                print,
                "READER415_DIAGNOSTIC_ERRORS=" + json.dumps(STATE["errors"]),
                file=sys.stderr,
            )


def pytest_sessionfinish(session, exitstatus):
    finish_observations(exitstatus)
