"""Bounded model-free admission of a kernel event observer; never qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
PROGRAM = SCRIPT.with_name("concordia_kernel_events.bt")
PRIOR_HEAD = "e2342c05463bd71ac7ec3cd96421b7f359330830"
ORDER = ("network-only", "kernel-events", "kernel-events", "network-only")
KINDS = {"F": (1, 4), "S": (2, 5), "W": (3, 3), "M": (4, 4),
         "U": (5, 4), "D": (6, 4), "X": (7, 3), "T": (8, 4)}
MAX_BYTES = 2 * 1024 * 1024
ALLOWED_PATHS = {"scripts/concordia_kernel_observer.py", "scripts/concordia_kernel_events.bt",
                 "tests/test_concordia_kernel_observer.py",
                 "docs/qualification/concordia-kernel-observer.md",
                 ".github/workflows/ai-runtime-candidate.yml"}


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def kernel_capability():
    events = Path("/sys/kernel/tracing/events")
    needed = ("sched/sched_process_fork", "sched/sched_switch", "sched/sched_wakeup",
              "sched/sched_process_exit", "syscalls/sys_enter_write",
              "syscalls/sys_enter_futex", "syscalls/sys_exit_futex",
              "syscalls/sys_enter_fsync", "syscalls/sys_exit_fsync", "raw_syscalls/sys_enter")
    return {"bpftrace": shutil.which("bpftrace"), "strace": shutil.which("strace"),
            "tracepoint_formats": {name: (events / name / "format").is_file() for name in needed},
            "kernel": platform.release(), "machine": platform.machine(),
            "python": platform.python_version()}


def source_proof():
    def git(*args):
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), *args]).decode().strip()
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("clean committed owner source required")
    subprocess.run(["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
                    "merge-base", "--is-ancestor", PRIOR_HEAD, "HEAD"],
                   check=True, capture_output=True)
    if git("rev-parse", "HEAD:core") != git("rev-parse", PRIOR_HEAD + ":core"):
        raise ValueError("model-free observer preparation changed PRODUCT bytes")
    paths = set(git("diff", "--name-only", PRIOR_HEAD, "HEAD").splitlines())
    if not paths <= ALLOWED_PATHS:
        raise ValueError("observer preparation changed another surface")
    return {"head": git("rev-parse", "HEAD"), "prior_head": PRIOR_HEAD,
            "core_tree": git("rev-parse", "HEAD:core"), "changed_paths": sorted(paths)}


def parse_events(text, stderr=""):
    """Asynchronous output is sorted by kernel time; missing output refuses."""
    if len(text.encode()) > MAX_BYTES or stderr.strip():
        raise ValueError("oversized stream or observer diagnostics; no admission")
    records, totals, observed = [], {}, Counter()
    for line in text.splitlines():
        if not line.strip():
            continue
        count = re.fullmatch(r"@emitted\[(\d+)\]: (\d+)", line)
        if count:
            key, value = map(int, count.groups())
            if key not in {v[0] for v in KINDS.values()} or key in totals:
                raise ValueError("unknown or duplicate kernel counter")
            totals[key] = value
            continue
        parts = line.split()
        if not parts or parts[0] not in KINDS or len(parts) != KINDS[parts[0]][1]:
            raise ValueError("unrecognized event output")
        if any(not re.fullmatch(r"\d+", x) for x in parts[1:]):
            raise ValueError("invalid numeric event")
        row = [parts[0], *map(int, parts[1:])]
        records.append(row)
        observed[KINDS[row[0]][0]] += 1
    if not records or dict(observed) != totals:
        raise ValueError("kernel/user event counts differ or empty stream")
    return sorted(records, key=lambda row: row[1])


def off_cpu_intervals(records):
    """Disjoint blocked/ready intervals, never sum inclusive syscall durations."""
    pending, result = {}, []
    for row in records:
        kind, stamp = row[:2]
        if kind == "S":
            previous, following, state = row[2:]
            if following in pending:
                start, raw_state, wake = pending.pop(following)
                if raw_state in {0, 256}:
                    wake = start
                result.append({"tid": following, "start": start, "end": stamp,
                               "raw_state": raw_state, "wake": wake,
                               "blocked_ns": None if wake is None else wake - start,
                               "ready_ns": None if wake is None else stamp - wake})
            if previous:
                if previous in pending:
                    raise ValueError("unmatched switch-out")
                pending[previous] = (stamp, state, None)
        elif kind == "W" and row[2] in pending:
            start, state, wake = pending[row[2]]
            pending[row[2]] = (start, state, stamp if wake is None else wake)
        elif kind == "X":
            # Exit closes a task lifetime, not a fabricated switch-in.
            pending.pop(row[2], None)
    return result


def evaluate_prediction(intervals, *, tid, start, end, capture_seconds, own_limit, complete=False):
    """Test the declared event shape, not historical or PRODUCT causality."""
    if (type(tid) is not int or tid <= 0 or type(start) is not int or type(end) is not int
            or start >= end or not math.isfinite(capture_seconds) or not math.isfinite(own_limit)
            or capture_seconds < 0 or own_limit < 0):
        raise ValueError("invalid scored window")
    excess = capture_seconds - own_limit
    result = {"qualification_eligible": False, "historical_causality": "NOT_ESTABLISHED",
              "excess_ns": round(excess * 1e9)}
    if excess <= 0:
        return {**result, "prediction": "NON_REPRODUCTION"}
    selected = [r for r in intervals if r["tid"] == tid and r["start"] < end and r["end"] > start]
    if not complete or any(r["wake"] is None for r in selected):
        return {**result, "prediction": "UNKNOWN"}
    # A preemption without sleeping is a competing outcome, not a fabricated wakeup.
    ready = [max(0, min(end, r["end"]) - max(start, r["wake"])) for r in selected
             if r["raw_state"] not in {0, 256}]
    largest = max(ready, default=0)
    return {**result, "largest_woken_ready_ns": largest,
            "prediction": "SUPPORTED_EVENT_SHAPE" if largest >= excess * 1e9 / 2
            else "REFUTED_EVENT_SHAPE"}


def verify_control(records, fixture):
    # bpftrace0.20.2 uses BOOTTIME on supported kernels, not CLOCK_MONOTONIC.
    # Prove a stable conversion interval; a suspend/clock discontinuity refuses.
    offsets = [(c["boot"] - c["mono_after"], c["boot"] - c["mono_before"])
               for c in (fixture["clock_before"], fixture["clock_after"])]
    if max(low for low, _ in offsets) > min(high for _, high in offsets):
        raise ValueError("BOOT/MONOTONIC clock offset changed")
    expected = {(r["tid"], r["code"]): r for r in fixture["markers"]}
    markers = [r for r in records if r[0] == "M"]
    if len(markers) != len(expected):
        raise ValueError("missing or extra marker")
    for _, stamp, tid, code in markers:
        item = expected.pop((tid, code), None)
        if item is None or not item["before"] <= stamp <= item["after"]:
            raise ValueError("marker identity or BOOTTIME clock mismatch")
    if expected:
        raise ValueError("missing marker identity")
    exited = {r[2] for r in records if r[0] == "X"}
    required = {fixture["pid"], *fixture["cpu_children"], fixture["waker_pid"],
                fixture["helper_tid"]}
    if not required <= exited:
        raise ValueError("missing descendant exit")
    intervals = off_cpu_intervals(records)
    for child in fixture["cpu_children"]:
        if not any(r["tid"] == child and (r["ready_ns"] or 0) > 0
                   and r["raw_state"] in {0, 256} for r in intervals):
            raise ValueError("positive runnable contention control missing")
    if not any(r["tid"] == fixture["pid"] and r["raw_state"] == 8 for r in intervals):
        raise ValueError("positive ptrace-stop control missing")
    for kind in ("U", "D"):
        pending, pairs = False, 0
        for row in records:
            if row[0] != kind or row[2] != fixture["pid"]:
                continue
            if row[3] not in {0, 1} or bool(row[3]) == pending:
                raise ValueError("unpaired fixture syscall")
            pending = bool(row[3])
            pairs += not pending
        if pending or not pairs:
            raise ValueError("positive syscall control missing")
    if not any(r["tid"] == fixture["pid"] and r["raw_state"] == 1
               and (r["blocked_ns"] or 0) > 0 and r["wake"] is not None for r in intervals):
        raise ValueError("positive blocked/wakeup control missing")
    return {"status": "CONTROL_OBSERVED", "kernel_clock_matches_markers": True,
            "kernel_clock": "bpftrace0.20.2:nsecs:CLOCK_BOOTTIME",
            "primary_marker": "raw_syscalls:sys_enter:x86_64-write-fd198",
            "typed_markers_observed": sum(r[0] == "T" for r in records),
            "typed_marker_admission": "NOT_RELIED_ON; prior incompleteness retained",
            "monotonic_offset_envelopes": offsets,
            "events": len(records), "descendant_exits": len(required),
            "off_cpu_intervals": intervals, "physical_io_causality": "NOT_ESTABLISHED"}


def cpu_work(seconds=0.15):
    """Do arithmetic between CPU-clock reads; do not benchmark clock syscalls."""
    start, reads, value = time.process_time(), 1, 1
    while True:
        for _ in range(4096):
            value = (value * 1664525 + 1013904223) & 0xFFFFFFFF
        elapsed = time.process_time() - start
        reads += 1
        if elapsed >= seconds:
            return {"cpu_seconds": elapsed, "clock_reads": reads, "checksum": value}


def fixture(output):
    """Public synthetic CPU contention, cross-process wake, futex and real fsync."""
    markers = []
    fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(fd, 198)
    os.close(fd)

    def clocks():
        before = time.monotonic_ns()
        boot = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        return {"mono_before": before, "boot": boot, "mono_after": time.monotonic_ns()}

    clock_before = clocks()

    def mark(code):
        before = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        os.write(198, b"x" * code)
        markers.append({"tid": threading.get_native_id(), "code": code,
                        "before": before, "after": time.clock_gettime_ns(time.CLOCK_BOOTTIME)})

    import socket

    # Positive check for the original network-only strace, never native no-egress evidence.
    sock = socket.socket(socket.AF_UNIX)
    sock.close()
    mark(1)
    (output.parent / "negative-go").touch(exist_ok=False)
    gate_read, gate_write = os.pipe()
    children = []
    for _ in range(2):
        child = os.fork()
        if child == 0:
            os.close(gate_write)
            os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
            os.read(gate_read, 1)
            work = cpu_work()
            write(output.parent / f"cpu-{os.getpid()}.json", work)
            os._exit(0)
        children.append(child)
    os.close(gate_read)
    os.write(gate_write, b"xx")
    os.close(gate_write)
    for child in children:
        _, status = os.waitpid(child, 0)
        if status:
            raise ValueError("CPU child failed")
    work = [json.loads((output.parent / f"cpu-{child}.json").read_text()) for child in children]
    if any(row["clock_reads"] > 2048 for row in work):
        raise ValueError("CPU fixture polled its clock excessively")
    mark(2)
    read_fd, write_fd = os.pipe()
    waker = os.fork()
    if waker == 0:
        os.close(read_fd)
        time.sleep(0.12)
        os.write(write_fd, b"x")
        os._exit(0)
    os.close(write_fd)
    mark(3)
    os.read(read_fd, 1)
    os.close(read_fd)
    os.waitpid(waker, 0)
    mark(4)
    event = threading.Event()

    def wake():
        time.sleep(0.12)
        event.set()

    helper = threading.Thread(target=wake)
    helper.start()
    mark(5)
    if not event.wait(1):
        raise ValueError("futex control timed out")
    helper.join()
    mark(6)
    with (output.parent / "synthetic-data").open("xb") as stream:
        stream.write(b"synthetic" * 1024)
        stream.flush()
        mark(7)
        os.fsync(stream.fileno())
        mark(8)
    write(output, {"pid": os.getpid(), "cpu_children": children, "waker_pid": waker,
                   "helper_tid": helper.native_id, "markers": markers,
                   "clock_before": clock_before, "clock_after": clocks(), "cpu_work": work})


def outsider(output):
    """Unowned negative control; never joined to the traced process tree."""
    deadline = time.monotonic() + 30
    while not (output.parent / "negative-go").exists():
        if time.monotonic() > deadline:
            raise ValueError("negative control did not receive trigger")
        time.sleep(0.002)
    fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(fd, 198)
    os.close(fd)
    start = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    for code in range(1, 9):
        os.write(198, b"x" * code)
    write(output, {"pid": os.getpid(), "before": start,
                   "after": time.clock_gettime_ns(time.CLOCK_BOOTTIME)})


def execute(command, output, *, environment, timeout=45):
    with output.with_suffix(".stdout").open("xb") as stdout, output.with_suffix(
            ".stderr").open("xb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                   env=environment, start_new_session=True)
        try:
            return process.wait(timeout=timeout)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


def control(output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"schema": "concordia-kernel-observer-control/v1", "status": "NOT_ADMITTED",
                "qualification_eligible": False, "native_inference": "NOT_RUN",
                "capability": kernel_capability(), "order": ORDER, "arms": [],
                "source_head": subprocess.check_output(
                    ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
                     "rev-parse", "HEAD"]).decode().strip(),
                "program_sha256": hashlib.sha256(PROGRAM.read_bytes()).hexdigest()}
    manifest["driver_sha256"] = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    try:
        cap = manifest["capability"]
        if not cap["bpftrace"] or not cap["strace"] or not all(cap["tracepoint_formats"].values()):
            raise ValueError("kernel observer capability unavailable; stop before fixtures")
        if cap["machine"] != "x86_64":
            raise ValueError("raw syscall marker ABI is qualified only for x86_64")
        manifest["source_proof"] = source_proof()
        version = subprocess.check_output([cap["bpftrace"], "--version"]).decode().strip()
        manifest["bpftrace_version"] = version
        if version != "bpftrace v0.20.2":
            raise ValueError("unreviewed bpftrace version")
        environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}
        for index, mode in enumerate(ORDER):
            arm = output / str(index)
            arm.mkdir()
            report = arm / "fixture.json"
            command = [cap["strace"], "-ff", "-tt", "-e", "trace=network", "-o",
                       str(arm / "network"), sys.executable, str(SCRIPT), "fixture",
                       "--output", str(report)]
            if mode == "kernel-events":
                command = [cap["bpftrace"], "-q", "-B", "line", "-k", "-c",
                           shlex.join(command), str(PROGRAM)]
            start = time.monotonic_ns()
            negative = subprocess.Popen([sys.executable, str(SCRIPT), "outsider",
                                         "--output", str(arm / "negative.json")],
                                        env=environment, start_new_session=True,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                code = execute(command, arm / "observer", environment=environment)
                _, negative_stderr = negative.communicate(timeout=5)
                (arm / "negative.stderr").write_bytes(negative_stderr)
                if negative.returncode:
                    raise ValueError("negative fixture failed")
            finally:
                if negative.poll() is None:
                    os.killpg(negative.pid, signal.SIGKILL)
                    negative.wait(timeout=5)
            row = {"index": index, "mode": mode, "exit": code,
                   "wall_ns": time.monotonic_ns() - start}
            manifest["arms"].append(row)
            if code or not report.is_file():
                raise ValueError("observer or fixture failed; no next arm")
            data = json.loads(report.read_text())
            traces = list(arm.glob("network.*"))
            if not traces or not any("socket(AF_UNIX" in p.read_text() for p in traces):
                raise ValueError("original strace positive control missing")
            if any(not re.search(r"\+\+\+ (exited with|killed by)", p.read_text()) for p in traces):
                raise ValueError("original trace exit missing")
            if mode == "kernel-events":
                records = parse_events((arm / "observer.stdout").read_text(),
                                       (arm / "observer.stderr").read_text())
                row["observation"] = verify_control(records, data)
                unowned = json.loads((arm / "negative.json").read_text())
                low = min(r["before"] for r in data["markers"])
                high = max(r["after"] for r in data["markers"])
                if not low <= unowned["before"] <= unowned["after"] <= high:
                    raise ValueError("negative control did not overlap the observed fixture")
                if any(unowned["pid"] in r[2:] for r in records):
                    raise ValueError("unowned negative control leaked into kernel records")
                row["observation"]["unowned_negative_control"] = "EXCLUDED"
                write(arm / "analysis.json", row["observation"])
            row["marker_envelopes_ns"] = [r["after"] - r["before"] for r in data["markers"]]
        # Costs are retained, not subtracted from a later scored Capture sample.
        envelopes = [v for arm in manifest["arms"] for v in arm["marker_envelopes_ns"]]
        if max(envelopes) > 5_000_000:
            raise ValueError("marker cost above the predeclared 5ms per-marker control bound")
        manifest["status"] = "MODEL_FREE_CONTROL_COMPLETE"
        manifest["native_admission"] = "NOT_GRANTED; event-to-Capture binding still required"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        manifest["error"] = {"type": type(exc).__name__, "detail": str(exc)}
    finally:
        write(output / "manifest.json", manifest)
    keys = ("status", "native_inference", "qualification_eligible")
    print(json.dumps({k: manifest[k] for k in keys}))
    return 0 if manifest["status"] == "MODEL_FREE_CONTROL_COMPLETE" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["control", "fixture", "outsider"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fixture":
        fixture(args.output.resolve())
        return 0
    if args.command == "outsider":
        outsider(args.output.resolve())
        return 0
    return control(args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
