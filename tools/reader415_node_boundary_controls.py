"""Two artificial observer controls; never ordinary tests or qualification.

The controller imports only the standard library. Each contained worker imports
the shared diagnostic plugin (and therefore pytest), without pytest.main, test
collection or application imports. Only the artificial stdout-holder uses unref.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

KINDS = ("busy35", "stdout-held35")
WORK_SECONDS = 90
CLEANUP_SECONDS = 20
ROOT = Path(__file__).resolve().parents[1]


def issue(exc):
    return {
        "type": type(exc).__name__, "message": str(exc)[:2048],
        "winerror": getattr(exc, "winerror", None), "errno": getattr(exc, "errno", None),
    }


def retain(path, data):
    with path.open("xb") as stream:
        stream.write(data)
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def document(path, value):
    return retain(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def persisted_file(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Required retained evidence is not a regular file: " + str(path))
    data = path.read_bytes()
    if not data:
        raise RuntimeError("Required retained evidence is empty: " + str(path))
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class Job:
    """One owned process tree. No breakaway, priority or resource overrides."""

    def __init__(self):
        kernel = self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_size_t

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", pointer),
                ("MaximumWorkingSetSize", pointer),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", pointer),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", pointer), ("JobMemoryLimit", pointer),
                ("PeakProcessMemoryUsed", pointer), ("PeakJobMemoryUsed", pointer),
            ]

        class ProcessList(ctypes.Structure):
            _fields_ = [
                ("NumberOfAssignedProcesses", wintypes.DWORD),
                ("NumberOfProcessIdsInList", wintypes.DWORD),
                ("ProcessIdList", pointer * 64),
            ]

        self.ExtendedLimits, self.ProcessList = ExtendedLimits, ProcessList
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        kernel.SetHandleInformation.restype = wintypes.BOOL
        kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetHandleInformation.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.IsProcessInJob.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL),
        ]
        kernel.IsProcessInJob.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.handle, self.process_handles = None, {}
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.check(kernel.SetHandleInformation(self.handle, 1, 0))
            flags = wintypes.DWORD()
            self.check(kernel.GetHandleInformation(self.handle, ctypes.byref(flags)))
            if flags.value & 1:
                raise RuntimeError("Job handle unexpectedly inheritable")
            limits = ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE only.
            self.check(kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ))
            observed = ExtendedLimits()
            self.check(kernel.QueryInformationJobObject(
                self.handle, 9, ctypes.byref(observed), ctypes.sizeof(observed), None
            ))
            if observed.BasicLimitInformation.LimitFlags != 0x2000:
                raise RuntimeError("Unexpected Job limit flags")
            self.readback = {"handle_inheritable": False, "limit_flags": 0x2000}
        except BaseException:
            kernel.CloseHandle(self.handle)
            self.handle = None
            raise

    @staticmethod
    def check(value):
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, worker):
        self.check(self.kernel.AssignProcessToJobObject(
            self.handle, wintypes.HANDLE(int(worker._handle))
        ))
        member = wintypes.BOOL()
        self.check(self.kernel.IsProcessInJob(
            wintypes.HANDLE(int(worker._handle)), self.handle, ctypes.byref(member)
        ))
        if not member.value:
            raise RuntimeError("Worker is not a member of this exact Job")
        return {"worker_pid": worker.pid, "is_process_in_this_exact_job": True}

    def times(self, handle):
        values = [wintypes.FILETIME() for _ in range(4)]
        self.check(self.kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)))
        return dict(zip(
            ("creation_filetime_100ns", "exit_filetime_100ns", "kernel_100ns", "user_100ns"),
            [(value.dwHighDateTime << 32) | value.dwLowDateTime for value in values], strict=True,
        ))

    def census(self):
        started, cpu = time.perf_counter_ns(), time.thread_time_ns()
        rows = self.ProcessList()
        self.check(self.kernel.QueryInformationJobObject(
            self.handle, 3, ctypes.byref(rows), ctypes.sizeof(rows), None
        ))
        if rows.NumberOfProcessIdsInList > 64 or rows.NumberOfAssignedProcesses > 64:
            raise RuntimeError("Job process census exceeded 64 processes")
        pids = list(rows.ProcessIdList[:rows.NumberOfProcessIdsInList])
        identities = []
        for pid in pids:
            row = {"pid": pid}
            try:
                if pid not in self.process_handles:
                    handle = self.kernel.OpenProcess(0x1000 | 0x100000, False, pid)
                    self.check(handle)
                    self.process_handles[pid] = handle
                row.update(self.times(self.process_handles[pid]))
                row["identity_scope"] = (
                    "RETAINED_FIRST_SEEN_HANDLE_NOT_CONTEMPORARY_PID_BIRTH_PROOF"
                    if row["exit_filetime_100ns"] else "RETAINED_FIRST_SEEN_LIVE_HANDLE"
                )
            except BaseException as exc:
                row["identity_error"] = issue(exc)
            identities.append(row)
        return {"perf_counter_ns": started, "assigned_processes": rows.NumberOfAssignedProcesses,
                "listed_processes": rows.NumberOfProcessIdsInList, "identities": identities,
                "observer_perf_elapsed_ns": time.perf_counter_ns() - started,
                "observer_thread_cpu_ns": time.thread_time_ns() - cpu}

    def terminate(self):
        self.check(self.kernel.TerminateJobObject(self.handle, 124))

    def close(self):
        failures = []
        for pid, handle in self.process_handles.items():
            try:
                self.check(self.kernel.CloseHandle(handle))
            except BaseException as exc:
                failures.append({"pid": pid, **issue(exc)})
        if self.handle:
            try:
                self.check(self.kernel.CloseHandle(self.handle))
                self.handle = None
            except BaseException as exc:
                failures.append({"job": True, **issue(exc)})
        return failures


def classify(kind, state):
    """Categories describe ordered observations, not causes or observer completion."""
    value = state.get("timeout_before_kill")
    if not isinstance(value, dict):
        return "UNKNOWN_NO_PREKILL_SNAPSHOT"
    process = value.get("process_times", {})
    if not process.get("available"):
        return "UNKNOWN_PROCESS_IDENTITY_UNAVAILABLE"
    born = process.get("creation_filetime_100ns")
    if not isinstance(born, int) or born <= 0:
        return "UNKNOWN_POSITIVE_PROCESS_BIRTH_UNAVAILABLE"
    if kind == "busy35" and value.get("poll_before_returncode") is None:
        previous = [row.get("process_times", {}) for row in state.get("samples", [])]
        previous = [
            row for row in previous
            if row.get("available") and row.get("creation_filetime_100ns") == born
        ]
        if previous and any(
            process["kernel_100ns"] + process["user_100ns"]
            > row["kernel_100ns"] + row["user_100ns"] for row in previous
        ):
            return "RUNNING_WITH_CPU_DELTA"
        return "UNKNOWN_NO_CREATION_BOUND_POSITIVE_CPU_DELTA"
    if kind == "stdout-held35" and value.get("poll_before_returncode") is not None:
        exited = process.get("exit_filetime_100ns")
        if not isinstance(exited, int) or exited <= 0:
            return "UNKNOWN_POSITIVE_PROCESS_EXIT_TIME_UNAVAILABLE"
        stages = {row.get("stage") for row in state.get("node_markers", [])}
        if not {"CONTROL_HOLDER_SPAWNED", "EXIT"}.issubset(stages):
            return "UNKNOWN_NODE_EXIT_OR_HOLDER_MARKER_MISSING"
        current = [
            row for row in value.get("reader_threads", [])
            if row.get("stream") == "stdout" and row.get("alive")
            and row.get("alive_after_native_query") and row.get("times", {}).get("available")
        ]
        for reader in current:
            identity = (reader.get("native_id"), reader["times"].get("creation_filetime_100ns"))
            for sample in state.get("samples", []):
                if (
                    sample.get("poll_before_returncode") is None
                    or sample.get("process_times", {}).get("creation_filetime_100ns") != born
                    or sample["monotonic_ns"] >= value["monotonic_ns"]
                ):
                    continue
                for old in sample.get("reader_threads", []):
                    if (
                        old.get("stream") == "stdout" and old.get("alive")
                        and old.get("alive_after_native_query")
                        and old.get("times", {}).get("available")
                        and (old.get("native_id"), old["times"].get("creation_filetime_100ns"))
                        == identity
                    ):
                        return "EXITED_NODE_STDOUT_READER_ALIVE_STABLE_BIRTH"
    return "UNKNOWN_REQUIRED_PATTERN_NOT_OBSERVED"


def worker(kind, output):
    # Only this contained worker imports pytest indirectly via the shared observer.
    import msvcrt

    import reader415_node_boundary_diagnostic as observer

    if sys.stdin.readline() != "GO\n":
        return 2
    sys.stdin.close()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    kernel.SetStdHandle.restype = wintypes.BOOL
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    # The handshake never reaches Node: this is control-only stdin rebinding.
    with open(os.devnull, "rb") as null_input:
        selected = wintypes.HANDLE(msvcrt.get_osfhandle(null_input.fileno()))
        Job.check(kernel.SetStdHandle(wintypes.DWORD(-10 & 0xFFFFFFFF), selected))
        if kernel.GetStdHandle(wintypes.DWORD(-10 & 0xFFFFFFFF)) != selected.value:
            raise RuntimeError("Control worker stdin did not rebind to NUL")
        observer.begin_control(output, kind)
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node runtime unavailable")
        preamble = (
            "import {openSync as __rd_open,writeSync as __rd_write,"
            "closeSync as __rd_close} from 'node:fs';\n"
            + observer.NODE_PREAMBLE.replace(
                "__MARKER_PATH__", json.dumps(str(observer.OUT / "node-markers.jsonl"))
            )
        )
        if kind == "busy35":
            body = (
                "\n__rd_event('CONTROL_BUSY_STARTED');"
                "const __control_start=process.hrtime.bigint();"
                "while(process.hrtime.bigint()-__control_start<35000000000n){};"
                "__rd_event('CONTROL_BUSY_FINISHED');\n"
            )
        else:
            holder = observer.OUT / "holder.mjs"
            retain(holder, (
                b"process.stdout.write('holder-open\\n');"
                b"setTimeout(()=>{process.stdout.write('holder-end\\n');},35000);\n"
            ))
            body = (
                "\nconst __control_holder=__control_spawn(process.execPath,["
                + json.dumps(str(holder))
                + "],{stdio:['ignore',process.stdout,'ignore']});"
                "__rd_event('CONTROL_HOLDER_SPAWNED',{holder_pid:__control_holder.pid});"
                "__control_holder.unref();__rd_event('CONTROL_PARENT_BODY_FINISHED');\n"
            )
            preamble = "import {spawn as __control_spawn} from 'node:child_process';\n" + preamble
        script = observer.OUT / "control.mjs"
        source = retain(script, (preamble + body).encode())
        outcome = {
            "kind": kind, "source": source, "control_only_stdin": "NUL_AFTER_GO",
            "expected_timeout_seconds": 30,
        }
        try:
            result = observer.observed_run(
                [node, str(script)], cwd=observer.ROOT,
                capture_output=True, text=True, timeout=30,
            )
            outcome.update(
                actual="RETURNED", returncode=result.returncode, expected_timeout_observed=False
            )
        except BaseException as exc:
            outcome.update(
                actual="RAISED", exception=issue(exc),
                expected_timeout_observed=isinstance(exc, subprocess.TimeoutExpired),
            )
        finally:
            try:
                observer.finish_control(outcome, classify=lambda state: classify(kind, state))
            except BaseException as exc:
                outcome["finalization_error"] = issue(exc)
            outcome.setdefault("observed_category", "UNKNOWN_FINALIZATION_FAILED")
            outcome["raw_observer_status"] = observer.STATE.get("status")
            outcome["raw_observer_error_count"] = observer.STATE.get("error_count")
            persistence_errors = [
                row for row in observer.STATE.get("errors", [])
                if row.get("stage") in {"prekill_checkpoint", "persist_observations"}
            ]
            if persistence_errors:
                outcome["finalization_error"] = {
                    "type": "RequiredObserverPersistenceFailed", "errors": persistence_errors
                }
            try:
                outcome["durable_pre_kill_checkpoint"] = persisted_file(
                    observer.OUT / "timeout-before-kill.json"
                )
                outcome["durable_observations"] = persisted_file(
                    observer.OUT / "observations.json"
                )
            except BaseException as exc:
                outcome["finalization_error"] = issue(exc)
        expected = (
            "RUNNING_WITH_CPU_DELTA" if kind == "busy35"
            else "EXITED_NODE_STDOUT_READER_ALIVE_STABLE_BIRTH"
        )
        markers = observer.STATE.get("node_markers", [])
        if kind == "busy35":
            truth = {"busy_entry_marker": any(
                row.get("stage") == "CONTROL_BUSY_STARTED" for row in markers
            )}
        else:
            exits = [row.get("code") for row in markers if row.get("stage") == "EXIT"]
            holders = [
                row.get("holder_pid") for row in markers
                if row.get("stage") == "CONTROL_HOLDER_SPAWNED"
            ]
            truth = {
                "parent_exit_marker_code_zero": exits == [0],
                "parent_pre_kill_poll_zero": (
                    observer.STATE.get("timeout_before_kill") or {}
                ).get("poll_before_returncode") == 0,
                "one_positive_holder_pid": len(holders) == 1
                and isinstance(holders[0], int) and holders[0] > 0,
                "no_uncaught_exception_marker": not any(
                    row.get("stage") == "UNCAUGHT_EXCEPTION_MONITOR" for row in markers
                ),
            }
        outcome["control_fixture_truth_checks"] = truth
        outcome["control_validation_errors"] = [
            name for name, valid in truth.items() if not valid
        ]
        matched = (
            outcome.get("expected_timeout_observed") and outcome["observed_category"] == expected
            and outcome.get("durable_pre_kill_checkpoint")
            and not outcome.get("finalization_error")
            and not outcome["control_validation_errors"]
        )
        outcome["category_pattern_observed"] = bool(matched)
        outcome["pattern_evaluation"] = (
            "CATEGORY_PATTERN_OBSERVED_WITH_RAW_OBSERVER_STATUS_RETAINED"
            if matched else "CATEGORY_PATTERN_NOT_OBSERVED_OR_UNKNOWN"
        )
        document(observer.OUT / "worker-result.json", outcome)
        return 0 if matched else 1


def control(kind, output):
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "kind": kind, "scope": "ARTIFICIAL_OBSERVER_CONTROL_NOT_QUALIFICATION",
        "errors": [], "job_census": [], "work_seconds": WORK_SECONDS,
        "cleanup_seconds": CLEANUP_SECONDS, "go_attempted": False, "go_sent": False,
        "cleanup_census": [], "retained_process_final_times": [],
    }
    job = process = None
    started = time.perf_counter_ns()
    record["started_perf_counter_ns"] = started
    out_path, err_path = output / "worker.stdout", output / "worker.stderr"
    with out_path.open("xb") as stdout, err_path.open("xb") as stderr:
        try:
            job = Job()
            record["job_readback"] = job.readback
            argv = [
                sys.executable, "-B", str(Path(__file__).resolve()),
                "--worker", kind, "--output", str(output),
            ]
            record["argv"] = argv
            spawn_started = time.perf_counter_ns()
            record["worker_popen_before_perf_counter_ns"] = spawn_started
            deadline = spawn_started + WORK_SECONDS * 1_000_000_000
            record["worker_work_deadline_perf_counter_ns"] = deadline
            process = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                close_fds=True, cwd=ROOT,
            )
            record["worker_popen_after_perf_counter_ns"] = time.perf_counter_ns()
            record["worker_pid"] = process.pid
            record["membership"] = job.assign(process)
            record["job_census"].append(job.census())
            record["go_admission_perf_counter_ns"] = time.perf_counter_ns()
            if record["go_admission_perf_counter_ns"] >= deadline:
                record["outer_work_timeout"] = True
                record["status"] = "NOT_ADMITTED_BEFORE_NODE_WORKLOAD"
                raise TimeoutError("90-second control work budget exhausted before GO")
            record["go_attempted"] = True
            process.stdin.write(b"GO\n")
            process.stdin.flush()
            record["go_sent"] = True
            process.stdin.close()
            while process.poll() is None and time.perf_counter_ns() < deadline:
                if len(record["job_census"]) < 512:
                    record["job_census"].append(job.census())
                else:
                    raise RuntimeError("512 bounded Job census records exhausted")
                time.sleep(min(0.25, max(0, (deadline - time.perf_counter_ns()) / 1e9)))
            record["worker_returncode_before_cleanup"] = process.poll()
            if process.poll() is None:
                record["outer_work_timeout"] = True
                raise TimeoutError("Control outer 90-second deadline expired")
        except BaseException as exc:
            record["errors"].append({"stage": "work", **issue(exc)})
            if not record["go_attempted"]:
                record.setdefault("status", "UNSUPPORTED_BEFORE_NODE_WORKLOAD")
            elif not record["go_sent"]:
                record["admission"] = "UNKNOWN_GO_WRITE_OR_FLUSH_DID_NOT_COMPLETE"
        finally:
            # Independent operations: an API/clock/close failure cannot skip the rest.
            cleanup_started = None
            try:
                cleanup_started = time.perf_counter_ns()
            except BaseException as exc:
                record["errors"].append({"stage": "cleanup_start_clock", **issue(exc)})
            cleanup_deadline = (
                cleanup_started + CLEANUP_SECONDS * 1_000_000_000
                if cleanup_started is not None else None
            )

            def remaining():
                if cleanup_deadline is None:
                    return 0
                try:
                    return max(0, (cleanup_deadline - time.perf_counter_ns()) / 1e9)
                except BaseException as exc:
                    record["errors"].append({"stage": "cleanup_admission_clock", **issue(exc)})
                    return 0
            if process is not None and process.stdin is not None and not process.stdin.closed:
                try:
                    process.stdin.close()
                except BaseException as exc:
                    record["errors"].append({"stage": "stdin_close", **issue(exc)})
            if job is not None:
                try:
                    record["before_cleanup_census"] = job.census()
                except BaseException as exc:
                    record["errors"].append({"stage": "before_cleanup_census", **issue(exc)})
                try:
                    job.terminate()
                    record["owned_job_termination_requested"] = True
                except BaseException as exc:
                    record["errors"].append({"stage": "terminate_owned_job", **issue(exc)})
            if process is not None and not record["go_attempted"]:
                try:
                    if process.poll() is None:
                        process.terminate()  # Still GO-blocked; no Node workload was admitted.
                except BaseException as exc:
                    record["errors"].append({"stage": "terminate_blocked_worker", **issue(exc)})
            if process is not None:
                try:
                    record["worker_returncode"] = process.wait(
                        timeout=remaining()
                    )
                except BaseException as exc:
                    record["errors"].append({"stage": "wait_worker", **issue(exc)})
            if job is not None:
                try:
                    while True:
                        census = job.census()
                        if len(record["cleanup_census"]) >= 512:
                            raise RuntimeError("512 bounded cleanup census records exhausted")
                        record["cleanup_census"].append(census)
                        record["after_cleanup_census"] = census
                        if (
                            census["listed_processes"] == 0
                            and census["assigned_processes"] == 0
                        ):
                            record["job_quiescent"] = True
                            break
                        if remaining() <= 0:
                            raise TimeoutError("Job quiescence unproven within cleanup budget")
                        time.sleep(0.05)
                except BaseException as exc:
                    record["errors"].append({"stage": "verify_job_quiescence", **issue(exc)})
                for pid, handle in job.process_handles.items():
                    row = {"pid": pid, "identity_scope": "RETAINED_FIRST_SEEN_HANDLE"}
                    try:
                        row.update(job.times(handle))
                    except BaseException as exc:
                        row["identity_error"] = issue(exc)
                        record["errors"].append({"stage": "final_handle_times", **row})
                    record["retained_process_final_times"].append(row)
                try:
                    record["errors"].extend(
                        {"stage": "close_job_handles", **entry} for entry in job.close()
                    )
                except BaseException as exc:
                    record["errors"].append({"stage": "close_job_handles", **issue(exc)})
            record["cleanup_started_perf_counter_ns"] = cleanup_started
            try:
                record["cleanup_completed_perf_counter_ns"] = time.perf_counter_ns()
            except BaseException as exc:
                record["cleanup_completed_perf_counter_ns"] = None
                record["errors"].append({"stage": "cleanup_end_clock", **issue(exc)})
    record["streams"] = []
    for path in (out_path, err_path):
        try:
            data = path.read_bytes()
            record["streams"].append({
                "path": str(path), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "representation": "EXACT_WORKER_OUTPUT_FILE_BYTES",
            })
        except BaseException as exc:
            record["errors"].append({"stage": "stream_hash", "path": str(path), **issue(exc)})
    try:
        record["completed_perf_counter_ns"] = time.perf_counter_ns()
    except BaseException as exc:
        record["completed_perf_counter_ns"] = None
        record["errors"].append({"stage": "completion_clock", **issue(exc)})
    try:
        result_path = output / "observer" / "worker-result.json"
        record["worker_result_file"] = persisted_file(result_path)
        worker_result = json.loads(result_path.read_text(encoding="utf-8"))
        record["raw_observer_status"] = worker_result["raw_observer_status"]
        record["raw_observer_error_count"] = worker_result["raw_observer_error_count"]
        record["category_pattern_observed"] = worker_result["category_pattern_observed"]
        record["pattern_evaluation"] = worker_result["pattern_evaluation"]
        if worker_result.get("finalization_error"):
            record["errors"].append({
                "stage": "worker_finalization", **worker_result["finalization_error"]
            })
    except BaseException as exc:
        record["errors"].append({"stage": "worker_outcome_read", **issue(exc)})
    record["controller_completion"] = (
        "COMPLETE" if not record["errors"] and record.get("job_quiescent")
        and record.get("worker_returncode") is not None else "INCOMPLETE"
    )
    complete = (
        not record["errors"] and record.get("worker_returncode") == 0
        and record.get("job_quiescent") and record.get("category_pattern_observed")
    )
    record["status_scope"] = "CONTROLLER_AND_CATEGORY_NOT_RAW_OBSERVER_COMPLETENESS"
    record.setdefault("status", "COMPLETE" if complete else "INCOMPLETE_OR_UNEXPECTED")
    try:
        document(output / "control-record.json", record)
    except BaseException as exc:
        record["errors"].append({"stage": "persist_control_record", **issue(exc)})
        record["controller_completion"] = "INCOMPLETE"
        record["status"] = "INCOMPLETE_OR_UNEXPECTED"
        try:
            print("CONTROL_RECORD_PERSISTENCE_FALLBACK=" + json.dumps(record), file=sys.stderr)
        except BaseException as fallback:
            record["fallback_stderr_error"] = issue(fallback)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", choices=KINDS)
    arguments = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("These artificial controls require Windows")
    if arguments.worker:
        return worker(arguments.worker, arguments.output.resolve())
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "schema": "reader415-node-boundary-controls/v2",
        "scope": "ARTIFICIAL_OBSERVER_CONTROLS_ONLY_NOT_QUALIFICATION",
        "controls": [], "errors": [], "ordinary_verdict_modified": False,
    }
    for kind in KINDS:
        try:
            result["controls"].append(control(kind, output / ("control-" + kind)))
        except BaseException as exc:
            result["errors"].append({"kind": kind, **issue(exc)})
    complete = (
        not result["errors"] and len(result["controls"]) == 2
        and all(row["status"] == "COMPLETE" for row in result["controls"])
    )
    result["controller_completion"] = (
        "COMPLETE" if not result["errors"] and len(result["controls"]) == 2
        and all(row["controller_completion"] == "COMPLETE" for row in result["controls"])
        else "INCOMPLETE"
    )
    result["raw_observer_status_by_control"] = {
        row["kind"]: row.get("raw_observer_status", "UNKNOWN") for row in result["controls"]
    }
    result["result"] = (
        "ALL_CATEGORY_PATTERNS_OBSERVED_RAW_STATUS_RETAINED"
        if complete else "INCOMPLETE_OR_UNEXPECTED"
    )
    try:
        document(output / "controls-summary.json", result)
    except BaseException as exc:
        result["errors"].append({"stage": "persist_controls_summary", **issue(exc)})
        result["controller_completion"] = "INCOMPLETE"
        result["result"] = "INCOMPLETE_OR_UNEXPECTED"
        complete = False
        try:
            print("CONTROLS_SUMMARY_PERSISTENCE_FALLBACK=" + json.dumps(result), file=sys.stderr)
        except BaseException as fallback:
            result["fallback_stderr_error"] = issue(fallback)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
