"""TEMP C4 parent observer; Linux x86-64, explicit credential-free invocation only.

Copied as scripts/capture_cost_v4_observer.py. No Product qualification or
correction support follows from this temporary mechanism dataset.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import mmap
import os
from pathlib import Path
import platform
import resource
import struct
import subprocess
import sys
import threading
import time


MODE = "FULL_ORDINARY_PROCESS_MECHANISM_V4"
REGIME = "FULL_ORDINARY_ALL19_PROCESS_OBSERVATION_NOT_QUALIFICATION"
PLAN_SCHEMA = "capture-process-mechanism-experiment/v4"
CONTROL_BYTES = 4096
HEADER_BYTES = 128
SLOT_BYTES = 128
SLOT_COUNT = 19
ACTIVE_OFFSET = 16
MAGIC = b"PVC4CTL1"
SLOT = struct.Struct("<16Q")
INTERVAL_NS = 50_000_000
ROUND_CAP = 128
TOTAL_ROUND_CAP = 2432
TID_CAP = 16
TARGET_CAP = 3
ENCODED_CAP = 16 * 1024**2
ENCODED_METADATA_RESERVE = 512 * 1024
RSS_CAP = 64 * 1024**2
READ_ATTEMPT_CAP = 192
READ_BYTES_CAP = 256 * 1024
POLICY = {
    "interval_ns": INTERVAL_NS, "per_callback_round_cap": ROUND_CAP,
    "total_round_cap": TOTAL_ROUND_CAP, "tid_cap": TID_CAP,
    "target_cap": TARGET_CAP, "encoded_bytes_cap": ENCODED_CAP,
    "rss_limit_bytes": RSS_CAP, "control_bytes": CONTROL_BYTES,
    "slot_bytes": SLOT_BYTES, "slots": SLOT_COUNT,
    "calibration_recipes": 512, "max_read_attempts": READ_ATTEMPT_CAP,
    "max_read_bytes": READ_BYTES_CAP,
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def runtime_support():
    return {
        "supported": (sys.platform == "linux" and platform.machine().lower() in
                      {"x86_64", "amd64"} and platform.python_implementation() == "CPython"
                      and sys.version_info[:2] == (3, 12)),
        "platform": sys.platform, "machine": platform.machine(),
        "implementation": platform.python_implementation(), "version": sys.version,
        "contract": "Verified CPython3.12/Linux-x86-64 immutable-slot publication; not portable mmap semantics",
    }


def sha_ref(path):
    digest, size = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return {"path": str(Path(path).absolute()), "bytes": size, "sha256": digest.hexdigest()}


def write_json_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def load_plan(path, expected_sha):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("frozen_plan_sha256")
    plan = json.loads(raw)
    if (plan.get("schema") != PLAN_SCHEMA or plan.get("status") != "FROZEN"
            or plan.get("mode") != MODE or plan.get("regime") != REGIME
            or plan.get("job_seconds") != 1200
            or plan.get("callbacks_per_job") != 19 or plan.get("callback_count_total") != 76
            or plan.get("observer") != POLICY):
        raise ValueError("frozen_C4_policy")
    if len(plan.get("cells", [])) != 4:
        raise ValueError("four_cells_required")
    return plan


class DisabledControl:
    """Explicit unavailable observer; Product operations must still execute."""

    def __init__(self, reason):
        self.errors = [{"reason": reason}]

    def publish(self, slot, entry_pid, caller_tid, native_pid):
        return False

    def clear(self, slot):
        return False

    def summary(self):
        return {"status": "INCOMPLETE", "published_slots": [], "errors": self.errors,
                "fd_closed_after_mapping": True, "mapping_closed": True}

    def close(self):
        return None


class ControlWriter:
    """One writer; each official descriptor is immutable and published once."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.published = bytearray(SLOT_COUNT)
        self.errors = []
        self.closed = False
        self.entry_pid = os.getpid()
        self.caller_tid = threading.get_native_id()

    @classmethod
    def attach(cls, fd):
        selected = None
        try:
            if not runtime_support()["supported"]:
                raise ValueError("unsupported_memory_ordering_runtime")
            if os.fstat(fd).st_size != CONTROL_BYTES:
                raise ValueError("control_size")
            selected = mmap.mmap(fd, CONTROL_BYTES, flags=mmap.MAP_SHARED,
                                 prot=mmap.PROT_READ | mmap.PROT_WRITE)
            if selected[:8] != MAGIC or struct.unpack_from("<II", selected, 8) != (1, SLOT_COUNT):
                raise ValueError("control_header")
            # Prefault the single fixed page, before the ordinary suite.
            selected[-1] = selected[-1]
            return cls(selected)
        except BaseException:
            if selected is not None:
                selected.close()
            raise
        finally:
            os.close(fd)

    def _error(self, reason, slot=None):
        if len(self.errors) < 64:
            self.errors.append({"reason": reason, "slot": slot})
        return False

    def publish(self, slot, entry_pid, caller_tid, native_pid):
        # No clock, proc, allocation of a descriptor buffer, FD operation or ack.
        try:
            if self.closed or type(slot) is not int or not 0 <= slot < SLOT_COUNT:
                return self._error("invalid_publish_slot", slot)
            if self.published[slot] or self.mapping[ACTIVE_OFFSET] != 0:
                return self._error("slot_reuse_or_nested_active", slot)
            if (entry_pid != self.entry_pid or caller_tid != self.caller_tid
                    or type(native_pid) is not int or native_pid < 0):
                return self._error("cached_caller_or_native_identity", slot)
            SLOT.pack_into(self.mapping, HEADER_BYTES + slot * SLOT_BYTES,
                           slot + 1, slot, entry_pid, caller_tid, native_pid,
                           0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            self.published[slot] = 1
            self.mapping[ACTIVE_OFFSET] = slot + 1
            return True
        except BaseException as exc:
            return self._error("publish_" + type(exc).__name__, slot)

    def clear(self, slot):
        try:
            if (self.closed or type(slot) is not int or not 0 <= slot < SLOT_COUNT
                    or not self.published[slot]):
                return self._error("clear_unpublished_slot", slot)
            if self.mapping[ACTIVE_OFFSET] != slot + 1:
                return self._error("clear_active_mismatch", slot)
            self.mapping[ACTIVE_OFFSET] = 0
            return True
        except BaseException as exc:
            return self._error("clear_" + type(exc).__name__, slot)

    def summary(self):
        return {"status": "INCOMPLETE" if self.errors else "COMPLETE",
                "published_slots": [i for i, published in enumerate(self.published) if published],
                "errors": list(self.errors),
                "fd_closed_after_mapping": True, "mapping_closed": self.closed}

    def close(self):
        if not self.closed:
            try:
                if self.mapping[ACTIVE_OFFSET] != 0:
                    self._error("active_slot_at_entry_cleanup")
                    self.mapping[ACTIVE_OFFSET] = 0
            finally:
                self.mapping.close()
                self.closed = True


def descriptor_snapshot(mapping):
    first = mapping[ACTIVE_OFFSET]
    if first == 0:
        return {"status": "INACTIVE", "active_before": 0, "active_after": 0}
    if not 1 <= first <= SLOT_COUNT:
        return {"status": "INCOHERENT", "reason": "invalid_flag", "active_before": first}
    values = SLOT.unpack_from(mapping, HEADER_BYTES + (first - 1) * SLOT_BYTES)
    second = mapping[ACTIVE_OFFSET]
    if first != second or values[:2] != (first, first - 1) or any(values[5:]):
        return {"status": "INCOHERENT", "reason": "flag_or_immutable_payload",
                "active_before": first, "active_after": second,
                "generation": values[0], "slot": values[1]}
    return {"status": "ACTIVE", "active_before": first, "active_after": second,
            "generation": values[0], "slot": values[1], "entry_pid": values[2],
            "caller_tid": values[3], "native_pid": values[4]}


def parse_stat(raw):
    text = raw.decode("ascii", errors="strict")
    opening, closing = text.find("("), text.rfind(")")
    fields = text[closing + 2:].split()
    if opening <= 0 or closing <= opening or len(fields) < 22:
        raise ValueError("stat_shape")
    return {"id": int(text[:opening].strip()), "state": fields[0],
            "ppid": int(fields[1]), "minor_faults": int(fields[7]),
            "major_faults": int(fields[9]), "utime_ticks": int(fields[11]),
            "stime_ticks": int(fields[12]), "start_ticks": int(fields[19]),
            "rss_pages": int(fields[21])}


def parse_status(raw):
    wanted = {"PPid", "TracerPid", "Threads", "voluntary_ctxt_switches",
              "nonvoluntary_ctxt_switches"}
    result = {}
    for line in raw.decode("ascii", errors="strict").splitlines():
        key, separator, value = line.partition(":")
        if separator and key in wanted:
            result[key] = int(value.strip())
    return result


def parse_schedstat(raw):
    values = raw.decode("ascii", errors="strict").split()
    if len(values) != 3:
        raise ValueError("schedstat_shape")
    return dict(zip(("runtime_ns", "runqueue_ns", "timeslices"), map(int, values)))


def parse_io(raw):
    wanted = {"rchar", "wchar", "syscr", "syscw", "read_bytes", "write_bytes",
              "cancelled_write_bytes"}
    result = {}
    for line in raw.decode("ascii", errors="strict").splitlines():
        key, separator, value = line.partition(":")
        if separator and key in wanted:
            result[key] = int(value.strip())
    return result


def parse_syscall(raw):
    token = raw.split(maxsplit=1)[0].decode("ascii", errors="strict")
    return {"state": "RUNNING"} if token == "running" else {"number": int(token, 0)}


class ProcRound:
    """Only selected proc interfaces; bound all reads, identities and errors."""

    def __init__(self, proc_root=Path("/proc")):
        self.root = Path(proc_root)
        self.attempts = 0
        self.open_attempts = 0
        self.read_calls = 0
        self.bytes = 0
        self.errors = []

    def error(self, interface, reason, pid, tid=None, errno=None):
        row = {"interface": interface, "reason": reason, "pid": pid, "tid": tid}
        if errno is not None:
            row["errno"] = errno
        self.errors.append(row)
        return {"availability": "UNAVAILABLE", **row}

    def read(self, pid, interface, parser, tid=None, cap=8192):
        if self.attempts >= READ_ATTEMPT_CAP or self.bytes >= READ_BYTES_CAP:
            return self.error(interface, "round_read_cap", pid, tid)
        self.attempts += 1
        selected = self.root / str(pid)
        if tid is not None:
            selected = selected / "task" / str(tid)
        selected = selected / interface
        fd = None
        started = time.monotonic_ns()
        try:
            self.open_attempts += 1
            fd = os.open(selected, os.O_RDONLY | os.O_CLOEXEC)
            self.read_calls += 1
            raw = os.read(fd, min(cap, READ_BYTES_CAP - self.bytes) + 1)
            self.bytes += len(raw)
            if len(raw) > cap or self.bytes > READ_BYTES_CAP:
                return self.error(interface, "oversized_or_round_bytes_cap", pid, tid)
            result = parser(raw)
            return {"availability": "AVAILABLE", "value": result,
                    "started_ns": started, "completed_ns": time.monotonic_ns(),
                    "bytes": len(raw)}
        except OSError as exc:
            return self.error(interface, "os_error", pid, tid, exc.errno)
        except (ValueError, UnicodeError, IndexError) as exc:
            return self.error(interface, "parse_" + type(exc).__name__, pid, tid)
        finally:
            if fd is not None:
                os.close(fd)

    def tids(self, pid):
        if self.attempts >= READ_ATTEMPT_CAP:
            self.error("task", "round_read_cap", pid)
            return []
        self.attempts += 1
        result = []
        try:
            with os.scandir(self.root / str(pid) / "task") as entries:
                for row in entries:
                    if row.name.isdecimal():
                        result.append(int(row.name))
                        if len(result) > TID_CAP:
                            self.error("task", "tid_cap_truncated", pid)
                            break
        except OSError as exc:
            self.error("task", "os_error", pid, errno=exc.errno)
        return sorted(result[:TID_CAP])

    def task(self, pid, tid, caller_or_leader):
        before = self.read(pid, "stat", parse_stat, tid)
        scheduling = self.read(pid, "schedstat", parse_schedstat, tid)
        extra = {}
        if caller_or_leader:
            extra = {
                "wchan": self.read(pid, "wchan", lambda raw: raw.decode("ascii").strip(), tid, 256),
                "syscall": self.read(pid, "syscall", parse_syscall, tid, 1024),
            }
        after = self.read(pid, "stat", parse_stat, tid)
        identity = (before.get("availability") == after.get("availability") == "AVAILABLE"
                    and before["value"]["id"] == after["value"]["id"] == tid
                    and before["value"]["start_ticks"] == after["value"]["start_ticks"])
        if not identity:
            self.error("task_identity", "unverified_disappeared_or_reused", pid, tid)
        return {"tid": tid, "birth_identity_verified": identity, "stat_before": before,
                "schedstat": scheduling, "stat_after": after, **extra}

    def target(self, role, pid, caller_tid=None, expected_parent=None):
        before = self.read(pid, "stat", parse_stat)
        status = self.read(pid, "status", parse_status)
        row = {"role": role, "pid": pid, "stat_before": before, "status": status}
        if expected_parent is not None and (status.get("availability") != "AVAILABLE"
                or status["value"].get("PPid") != expected_parent):
            self.error("target_identity", "native_parent_unverified", pid)
            row["ancestry_verified"] = False
            return row
        row["ancestry_verified"] = True if expected_parent is not None else None
        row["io"] = self.read(pid, "io", parse_io)
        row["tasks"] = [self.task(pid, tid, tid in {pid, caller_tid}) for tid in self.tids(pid)]
        after = self.read(pid, "stat", parse_stat)
        row["stat_after"] = after
        row["birth_identity_verified"] = (
            before.get("availability") == after.get("availability") == "AVAILABLE"
            and before["value"]["id"] == after["value"]["id"] == pid
            and before["value"]["start_ticks"] == after["value"]["start_ticks"])
        if not row["birth_identity_verified"]:
            self.error("target_identity", "unverified_disappeared_or_reused", pid)
        return row


class ParentObserver:
    def __init__(self, mapping, entry_pid, proc_root=Path("/proc")):
        self.mapping = mapping
        self.entry_pid = entry_pid
        self.proc_root = proc_root
        self.records = []
        self.encoded_bytes = 0
        self.counts = Counter()
        self.errors = Counter()
        self.rounds = Counter()
        self.retained_rounds = Counter()
        self.seen_slots = set()
        self.first_births = {}
        self.sampling_disabled = False
        self.retention_stop = None

    def error(self, tag):
        self.errors[tag] += 1

    def append(self, row):
        raw = json.dumps(row, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if self.encoded_bytes + len(raw) + 1 > ENCODED_CAP - ENCODED_METADATA_RESERVE:
            self.error("encoded_bytes_cap")
            self.sampling_disabled = True
            self.counts["records_omitted_after_cap"] += 1
            return False
        self.records.append(raw)
        self.encoded_bytes += len(raw) + 1
        return True

    def tick(self, number, scheduled, started, missed):
        self.counts["wakeups"] += 1
        self.counts["missed_intervals"] += missed
        if self.retention_stop is not None:
            self.counts["ticks_omitted_after_rss_cap"] += 1
            return
        cpu_start = time.thread_time_ns()
        tick = {"tick": number, "scheduled_ns": scheduled, "started_ns": started,
                "lateness_ns": max(0, started - scheduled), "missed_intervals": missed}
        if self.mapping is None:
            tick["descriptor"] = {"status": "UNAVAILABLE"}
            self.counts["unavailable_ticks"] += 1
        else:
            descriptor = descriptor_snapshot(self.mapping)
            tick["descriptor"] = descriptor
            if descriptor["status"] == "INACTIVE":
                self.counts["inactive_ticks"] += 1
            elif descriptor["status"] != "ACTIVE":
                self.error("incoherent_descriptor")
            elif descriptor["entry_pid"] != self.entry_pid or descriptor["caller_tid"] <= 0:
                self.error("entry_or_caller_identity")
            else:
                slot = descriptor["slot"]
                self.seen_slots.add(slot)
                self.counts["active_ticks"] += 1
                if (self.rounds[slot] >= ROUND_CAP
                        or self.counts["active_rounds"] >= TOTAL_ROUND_CAP):
                    self.error("round_cap")
                    self.counts["active_ticks_without_sample"] += 1
                elif self.sampling_disabled:
                    self.counts["active_ticks_without_sample"] += 1
                else:
                    self.rounds[slot] += 1
                    self.counts["active_rounds"] += 1
                    sample = ProcRound(self.proc_root)
                    entry = sample.target("entry", self.entry_pid, descriptor["caller_tid"])
                    targets = [entry]
                    if descriptor["native_pid"]:
                        if descriptor["native_pid"] == self.entry_pid:
                            self.error("native_equals_entry")
                        else:
                            targets.append(sample.target("native", descriptor["native_pid"],
                                                         expected_parent=self.entry_pid))
                    tracer = entry["status"].get("value", {}).get("TracerPid")
                    if type(tracer) is int and tracer > 0 and tracer not in {
                            self.entry_pid, descriptor["native_pid"]}:
                        targets.append(sample.target("tracer", tracer))
                    else:
                        sample.error("TracerPid", "unavailable_or_not_traced", self.entry_pid)
                    if len(targets) > TARGET_CAP:
                        self.error("target_cap")
                    for target in targets:
                        if target.get("birth_identity_verified"):
                            identity = (target["role"], target["pid"])
                            birth = target["stat_before"]["value"]["start_ticks"]
                            if identity in self.first_births and self.first_births[identity] != birth:
                                sample.error("target_identity", "pid_reused_since_previous_sample",
                                             target["pid"])
                            else:
                                self.first_births[identity] = birth
                    final_flag = self.mapping[ACTIVE_OFFSET]
                    tick["sample"] = {
                        "round_in_callback": self.rounds[slot], "targets": targets,
                        "errors": sample.errors, "read_attempts": sample.attempts,
                        "open_attempts": sample.open_attempts, "read_calls": sample.read_calls,
                        "read_bytes": sample.bytes,
                        "active_flag_at_sample_end": final_flag,
                        "active_flag_stability": ("UNCHANGED" if final_flag == descriptor["active_before"]
                            else "TORN_CALLBACK_BOUNDARY"),
                        "alignment_scope": "retain read intervals; not a complete in-Capture state assertion",
                    }
                    self.counts["read_attempts"] += sample.attempts
                    self.counts["open_attempts"] += sample.open_attempts
                    self.counts["read_calls"] += sample.read_calls
                    self.counts["read_bytes"] += sample.bytes
                    for error in sample.errors:
                        self.error(error["reason"] + ":" + str(error.get("errno")))
        tick["completed_ns"] = time.monotonic_ns()
        tick["sampling_body_thread_cpu_ns"] = time.thread_time_ns() - cpu_start
        tick["cpu_scope"] = "tick body; record encoding excluded; total observer process CPU also retained"
        if self.append(tick) and "sample" in tick:
            self.retained_rounds[tick["descriptor"]["slot"]] += 1
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        if rss > RSS_CAP:
            self.error("observer_rss_cap")
            self.sampling_disabled = True
            self.retention_stop = {"reason": "observer_rss_cap", "tick": number,
                "rss_peak_bytes": rss, "retained_records": len(self.records),
                "encoded_record_bytes_with_separators": self.encoded_bytes}

    def summary(self):
        return {"status": "INCOMPLETE" if self.errors else "COMPLETE",
                "counts": dict(self.counts), "errors": dict(self.errors),
                "rounds_per_callback": {str(i): self.rounds[i] for i in range(SLOT_COUNT)},
                "retained_sample_rounds_per_callback": {str(i): self.retained_rounds[i] for i in range(SLOT_COUNT)},
                "rounds_scope": "rounds started; retained completed sample rows counted separately",
                "callbacks_with_active_descriptor": sorted(self.seen_slots),
                "callbacks_with_samples": sorted(i for i, count in self.retained_rounds.items() if count),
                "zero_sample_meaning": "NOT_OBSERVED; a callback can finish between ticks",
                "encoded_record_bytes_with_separators": self.encoded_bytes,
                "encoded_metadata_reserve_bytes": ENCODED_METADATA_RESERVE,
                "retention_stop": self.retention_stop,
                "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}

    def write(self, path, header):
        # Stream retained encoded records; never create a second joined16MiB copy.
        with Path(path).open("xb") as stream:
            prefix = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if len(prefix) + self.encoded_bytes + 32 > ENCODED_CAP:
                raise ValueError("final_encoded_output_cap")
            stream.write(prefix[:-1] + b',"records":[')
            for ordinal, raw in enumerate(self.records):
                if ordinal:
                    stream.write(b",")
                stream.write(raw)
            stream.write(b"]}\n")

    def final_descriptors(self):
        rows = []
        if self.mapping is None:
            self.error("final_control_unavailable")
            return rows
        for index in range(SLOT_COUNT):
            values = SLOT.unpack_from(self.mapping, HEADER_BYTES + index * SLOT_BYTES)
            valid = (values[:2] == (index + 1, index) and values[2] == self.entry_pid
                     and values[3] > 0 and not any(values[5:]))
            rows.append({"slot": index, "generation": values[0], "entry_pid": values[2],
                         "caller_tid": values[3], "native_pid": values[4],
                         "published_identity_verified": valid,
                         "sample_rounds": self.rounds[index],
                         "retained_sample_rounds": self.retained_rounds[index]})
            if not valid:
                self.error("missing_or_invalid_final_descriptor")
        return rows


def environment_observations():
    """One bounded bootstrap/final observation, never a per-Capture read."""
    paths = {"perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid"),
             "yama_ptrace_scope": Path("/proc/sys/kernel/yama/ptrace_scope"),
             "cpu_pressure": Path("/proc/pressure/cpu"),
             "io_pressure": Path("/proc/pressure/io"),
             "memory_pressure": Path("/proc/pressure/memory")}
    cgroup = None
    try:
        with Path("/proc/self/cgroup").open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("cgroup_file_cap")
        for row in raw.decode("ascii").splitlines():
            if row.startswith("0::"):
                selected = Path(row[3:])
                if not selected.is_absolute() or ".." in selected.parts:
                    raise ValueError("cgroup_path")
                cgroup = Path("/sys/fs/cgroup") / str(selected).lstrip("/")
        if cgroup is not None:
            for name in ("cpu.max", "cpu.stat", "cpu.pressure", "io.pressure", "memory.pressure"):
                paths["cgroup_" + name] = cgroup / name
    except (OSError, ValueError, UnicodeError) as exc:
        cgroup = {"availability": "UNAVAILABLE", "exception_type": type(exc).__name__,
                  "errno": getattr(exc, "errno", None)}
    result = {"started_ns": time.monotonic_ns(), "cgroup": str(cgroup) if isinstance(cgroup, Path) else cgroup,
              "interfaces": {}}
    for name, path in paths.items():
        try:
            with path.open("rb") as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError("environment_file_cap")
            result["interfaces"][name] = {"availability": "AVAILABLE", "text": raw.decode("ascii"),
                                          "bytes": len(raw)}
        except (OSError, ValueError, UnicodeError) as exc:
            result["interfaces"][name] = {"availability": "UNAVAILABLE", "exception_type": type(exc).__name__,
                                          "errno": getattr(exc, "errno", None)}
    result["completed_ns"] = time.monotonic_ns()
    return result


def create_control():
    if not runtime_support()["supported"]:
        raise ValueError("unsupported_memory_ordering_runtime")
    fd = os.memfd_create("provelume-c4-observation", os.MFD_CLOEXEC)
    mapping = None
    try:
        os.ftruncate(fd, CONTROL_BYTES)
        mapping = mmap.mmap(fd, CONTROL_BYTES, flags=mmap.MAP_SHARED,
                            prot=mmap.PROT_READ | mmap.PROT_WRITE)
        mapping[:] = bytes(CONTROL_BYTES)
        mapping[:8] = MAGIC
        struct.pack_into("<II", mapping, 8, 1, SLOT_COUNT)
        return fd, mapping
    except BaseException:
        if mapping is not None:
            mapping.close()
        os.close(fd)
        raise


def parser():
    selected = argparse.ArgumentParser(description=__doc__)
    for option in ("artifacts", "output", "telemetry", "sampler-output", "plan"):
        selected.add_argument("--" + option, type=Path, required=True)
    selected.add_argument("--plan-sha256", required=True)
    selected.add_argument("--cell-ordinal", type=int, choices=range(4), required=True)
    return selected


def main():
    args = parser().parse_args()
    plan = load_plan(args.plan, args.plan_sha256)
    cell = plan["cells"][args.cell_ordinal]
    if cell.get("ordinal") != args.cell_ordinal or cell.get("ordinary_arm") not in {"A", "B"}:
        raise ValueError("cell_identity")
    root = Path(__file__).resolve().parents[1]
    control_fd, mapping = None, None
    setup_errors = []
    observer = None
    child = None
    primary = None
    started_utc, started_ns, cpu_start = utc_now(), time.monotonic_ns(), time.process_time_ns()
    try:
        args.sampler_output.parent.mkdir(parents=True, exist_ok=True)
    except BaseException as exc:
        setup_errors.append({"operation": "sampler_output_directory", "exception_type": type(exc).__name__,
                             "errno": getattr(exc, "errno", None)})
    try:
        environment_before = environment_observations()
    except BaseException as exc:
        environment_before = {"availability": "UNAVAILABLE", "exception_type": type(exc).__name__}
        setup_errors.append({"operation": "environment_bootstrap", "exception_type": type(exc).__name__,
                             "errno": getattr(exc, "errno", None)})
    try:
        try:
            control_fd, mapping = create_control()
        except BaseException as exc:
            setup_errors.append({"operation": "control_setup", "exception_type": type(exc).__name__,
                                 "errno": getattr(exc, "errno", None)})
        command = [sys.executable, "-I", "-B", str(root / "scripts/diagnose_capture_cost_v4.py")]
        for name in ("artifacts", "output", "telemetry", "plan"):
            command.extend(["--" + name, str(getattr(args, name))])
        command.extend(["--plan-sha256", args.plan_sha256,
                        "--cell-ordinal", str(args.cell_ordinal)])
        if control_fd is not None:
            command.extend(["--observer-control-fd", str(control_fd)])
        child = subprocess.Popen(command, cwd=root,
                                 pass_fds=(control_fd,) if control_fd is not None else ())
        if control_fd is not None:
            os.close(control_fd)
            control_fd = None
        observer = ParentObserver(mapping, child.pid)
        for error in setup_errors:
            observer.error(error["operation"] + ":" + error["exception_type"])
        scheduled, ordinal = time.monotonic_ns(), 0
        try:
            while child.poll() is None:
                now = time.monotonic_ns()
                if now < scheduled:
                    time.sleep((scheduled - now) / 1e9)
                    continue
                missed = max(0, (now - scheduled) // INTERVAL_NS)
                observer.tick(ordinal, scheduled, now, missed)
                ordinal += 1
                scheduled += (missed + 1) * INTERVAL_NS
        except BaseException as exc:
            primary = type(exc).__name__
            observer.error("observer_loop_" + primary)
        # Observer failure never cancels or reruns ordinary Product execution.
        child_returncode = child.wait()
        if mapping is not None and mapping[ACTIVE_OFFSET] != 0:
            observer.error("entry_exit_with_active_flag")
        final_descriptors = observer.final_descriptors()
        environment_after = environment_observations()
        summary = observer.summary()
        parent_returncode = (42 if summary["status"] != "COMPLETE" else child_returncode)
        if child_returncode < 0:
            parent_returncode = 128 - child_returncode
        header = {"schema": "capture-process-proc-observation/v4", "mode": MODE, "regime": REGIME,
                  "authority": "NONE_MECHANISM_ONLY", "qualification": "NOT_GRANTED",
                  "correction_support": "NOT_GRANTED", "plan_sha256": args.plan_sha256,
                  "workflow_head": os.environ.get("GITHUB_SHA"),
                  "run_id": os.environ.get("GITHUB_RUN_ID"),
                  "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                  "cell": cell, "entry_pid": child.pid, "observer_pid": os.getpid(),
                  "observer_ppid": os.getppid(), "policy": POLICY,
                  "runtime_support": runtime_support(), "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
                  "page_bytes": os.sysconf("SC_PAGE_SIZE"), "summary": summary,
                  "final_descriptors": final_descriptors,
                  "environment_before": environment_before, "environment_after": environment_after,
                  "observation_limits": ["samples are read intervals, not atomic snapshots",
                      "syscall number may be ptrace entry/exit stop, not blocking",
                      "T/t is observed tracing stop; wchan0 is hidden/unknown",
                      "all unavailable errno and partial records retained"],
                  "started_at": started_utc, "completed_at_before_output": utc_now()}
        observer.write(args.sampler_output, header)
        execution = {"schema": "capture-process-observer-execution/v4", "authority": "NONE_MECHANISM_ONLY",
                     "qualification": "NOT_GRANTED", "correction_support": "NOT_GRANTED",
                     "started_at": started_utc, "completed_at": utc_now(),
                     "started_ns": started_ns, "completed_ns": time.monotonic_ns(),
                     "observer_process_cpu_ns": time.process_time_ns() - cpu_start,
                     "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                     "actual_entry_argv": command, "actual_entry_returncode": child_returncode,
                     "observer_returncode": parent_returncode, "primary_exception_type": primary,
                     "setup_errors": setup_errors, "sampler_status": summary["status"],
                     "sampler": sha_ref(args.sampler_output),
                     "plan_sha256": args.plan_sha256, "cell_ordinal": args.cell_ordinal,
                     "control_fd_closed_after_spawn": control_fd is None,
                     "control_mapping_close_pending_in_finally": mapping is not None,
                     "cost_scope": "parent bootstrap through sampler output; this sidecar write excluded"}
        write_json_new(args.sampler_output.with_name("observer.execution.json"), execution)
        return parent_returncode
    finally:
        # This also covers a failure between Popen and the sampler-loop try.
        # Reap the same original child; never kill, retry or abandon its workload.
        original_error = sys.exc_info()[1]
        cleanup_error = None
        for label, cleanup in (
                ("entry_wait", child.wait if child is not None and child.returncode is None else None),
                ("control_fd_close", (lambda: os.close(control_fd)) if control_fd is not None else None),
                ("control_mapping_close", mapping.close if mapping is not None else None)):
            if cleanup is None:
                continue
            try:
                cleanup()
            except BaseException as exc:
                cleanup_error = cleanup_error or exc
                print(json.dumps({"observer_cleanup_failed": label,
                                  "exception_type": type(exc).__name__,
                                  "primary_exception_type": type(original_error).__name__
                                  if original_error is not None else None}), file=sys.stderr)
        if original_error is None and cleanup_error is not None:
            raise cleanup_error


if __name__ == "__main__":
    raise SystemExit(main())
