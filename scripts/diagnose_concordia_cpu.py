"""Controlled Linux replay of S01 CPU findings. Never candidate qualification.

The original payload, evaluator, job sequence and network observer are imported
from each immutable source. Only this external driver supplies instrumentation.
"""

from __future__ import annotations

import argparse
import contextvars
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

try:
    import resource
except ImportError:
    resource = None

MAIN = "096782e32a3d019c3e160c2569507d55cadfd274"
S06 = "8b3f467aa9e7c059e23f22644786ef0f87582cc3"
S08 = "e2c9244df692cdd9dbd636a0109a7d920a21ac1b"
SCRIPT = Path(__file__).resolve()
CURRENT = contextvars.ContextVar("concordia_probe", default=None)


def observer_source(repository, revision):
    """Bind an optional observer experiment to the freshly fetched default ref."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("observer source requires a full commit SHA")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repository):
        raise ValueError("observer driver source is not clean")
    actual = subprocess.check_output(
        ["git", "rev-parse", "refs/remotes/origin/main"], cwd=repository, text=True).strip()
    if revision != actual:
        raise ValueError("observer source differs from fetched main")
    if subprocess.check_output(
            ["git", "cat-file", "-t", revision], cwd=repository, text=True).strip() != "commit":
        raise ValueError("observer source is not a commit")
    tree = subprocess.check_output(
        ["git", "rev-parse", revision + "^{tree}"], cwd=repository, text=True).strip()
    return {"source": revision, "tree": tree, "reference": "refs/remotes/origin/main"}


def admit_observer(repository, revision, output):
    """Require source, counters and real tracing before acquiring any model."""
    if output.exists() or output.is_symlink():
        raise ValueError("preserve existing observer admission")
    selected = observer_source(repository, revision)
    portable = admit_portable(output.with_suffix(".portable.json"))
    result = {**portable, "selected_source": selected, "status": "CAPABILITY_MISSING"}
    try:
        sys.path.insert(0, str(repository / "core"))
        from provelume.ai_runtime_contract import hardware

        result["native_hardware"] = hardware()
        with tempfile.TemporaryDirectory(prefix="observer-trace-") as scratch:
            trace = Path(scratch) / "network"
            smoke = subprocess.run([
                "strace", "-ff", "-tt", "-e", "trace=network", "-o", str(trace),
                sys.executable, "-c", "import socket; s=socket.socket(); s.close()",
            ], capture_output=True, text=True, timeout=20)
            traces = [path.read_text() for path in trace.parent.glob("network.*")]
            result["strace_control"] = {"exit_code": smoke.returncode,
                                       "stderr": smoke.stderr, "traces": traces}
            if smoke.returncode or not any("socket(AF_INET" in row for row in traces):
                raise ValueError("actual observer strace control failed")
        result["status"] = "OBSERVER_SOURCE_ADMITTED"
    finally:
        write_json(output, result)
    return result


def portable_tracer_plan(allowed=None, topology=Path("/sys/devices/system/cpu")):
    """Observe a usable layout without requiring or emulating the original CPU.

    Native selection still uses the first logical CPU of the first two physical
    cores. Prefer their two siblings; otherwise use two additional physical cores.
    No affinity, native configuration or hardware identity is changed here.
    """
    allowed = set(os.sched_getaffinity(0) if allowed is None else allowed)
    if len(allowed) < 4 or any(type(cpu) is not int or cpu < 0 for cpu in allowed):
        raise ValueError("portable tracer control requires four allowed logical CPUs")
    groups = {}
    for cpu in sorted(allowed):
        root = topology / f"cpu{cpu}" / "topology"
        identity = []
        for key in ("physical_package_id", "core_id"):
            raw = (root / key).read_text().strip()
            if not raw.isascii() or not raw.isdecimal() or len(raw) > 10:
                raise ValueError("portable CPU topology unavailable")
            identity.append(int(raw))
        groups.setdefault(tuple(identity), []).append(cpu)
    cores = sorted(groups.values())
    if len(cores) >= 2 and all(len(core) >= 2 for core in cores[:2]):
        foreground, other = cores[0][1], cores[1][1]
        layout = "worker-smt-siblings"
    elif len(cores) >= 4:
        foreground, other = cores[2][0], cores[3][0]
        layout = "separate-physical-cores"
    else:
        raise ValueError("portable control requires two worker siblings or four physical cores")
    return {"allowed": sorted(allowed), "cores": cores,
            "worker_cpus": [core[0] for core in cores[:2]],
            "portable_foreground": foreground, "tracer_other": other, "layout": layout}


def portable_environment(cpuinfo=Path("/proc/cpuinfo")):
    """Record actual public hardware metadata, not a substituted reference profile."""
    import platform

    raw = cpuinfo.read_text()
    models = sorted({line.split(":", 1)[1].strip() for line in raw.splitlines()
                     if line.startswith("model name")})
    flags = [set(line.split(":", 1)[1].split()) for line in raw.splitlines()
             if line.startswith("flags")]
    return {"cpu_models": models, "avx2": bool(flags) and all("avx2" in row for row in flags),
            "kernel": platform.release(), "machine": platform.machine(),
            "python": platform.python_version(), "original_profile_required": False}


def admit_portable(output):
    """Stop before acquisition unless topology, tracing and scheduler controls work."""
    if output.exists():
        raise ValueError("preserve existing portable admission evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {"status": "CAPABILITY_MISSING", "qualification_eligible": False,
              "experiment": "portable-tracer-placement", "model_acquisition": "NOT_RUN"}
    try:
        if sys.platform != "linux" or resource is None:
            raise ValueError("portable tracer control requires Linux resource/scheduler support")
        result["environment"] = portable_environment()
        if (not result["environment"]["cpu_models"] or not result["environment"]["avx2"]
                or result["environment"]["machine"] != "x86_64"
                or sys.version_info[:2] != (3, 12)):
            raise ValueError("observed host does not support the existing native runtime")
        result["plan"] = portable_tracer_plan()
        if any(shutil.which(tool) is None for tool in ("strace", "taskset")):
            raise ValueError("portable tracer transport unavailable")
        result["scheduler_calibration"] = calibrate_scheduler()
        if result["scheduler_calibration"]["status"] != "POSITIVE_RUNQUEUE_CONTROL":
            raise ValueError("positive scheduler counters unavailable; no acquisition")
        result["status"] = "PORTABLE_PROFILE_ADMITTED"
    except (OSError, ValueError, RuntimeError) as exc:
        result["reason"] = str(exc)
        write_json(output, result)
        raise
    write_json(output, result)
    return result


DIGEST_BASE = "967222f71d43de7e518d9c55c80167bf1d886c83"
DIGEST_OLD = (
    b"            while block := handle.read(1024 * 1024):\n"
    b"                size += len(block)\n"
    b"                if size > limit:\n"
    b"                    raise error_type()\n"
    b"                digest.update(block)"
)
DIGEST_NEW = (
    b"            # The fresh size also bounds the read buffer. Requesting a full\n"
    b"            # MiB for a tiny journal allocates that buffer on every digest.\n"
    b"            # One extra byte detects growth; the identity checks still follow.\n"
    b"            while block := handle.read(min(1024 * 1024, before.st_size - size + 1)):\n"
    b"                size += len(block)\n"
    b"                if size > before.st_size:\n"
    b"                    raise error_type()\n"
    b"                digest.update(block)"
)
DIGEST_PATH = "core/provelume/atomic_commit.py"
DIGEST_CONTROL_PATHS = {
    DIGEST_PATH, "tests/test_atomic_digest_bounds.py",
    "tests/test_concordia_cpu_diagnostic.py", "scripts/diagnose_concordia_cpu.py",
    ".github/workflows/ai-runtime-candidate.yml",
    "docs/qualification/concordia-cpu-diagnosis.md",
}


def digest_factor(before, after, paths):
    """Admit only the declared read-size change, with no other PRODUCT delta."""
    if (set(paths) - DIGEST_CONTROL_PATHS or DIGEST_PATH not in paths
            or before.count(DIGEST_OLD) != 1
            or after != before.replace(DIGEST_OLD, DIGEST_NEW)):
        raise ValueError("bounded_digest_factor_not_isolated")


def digest_comparison(repository, candidate):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repository)
    parents = git("rev-list", "--parents", "-n", "1", candidate).decode().split()
    if parents != [candidate, DIGEST_BASE]:
        raise ValueError("bounded_digest_source_is_not_the_predeclared_child")
    original_blob = git("rev-parse", DIGEST_BASE + ":" + DIGEST_PATH).decode().strip()
    if original_blob != "1f019e176780c3ae85743b6222ca3941d3fa05d0":
        raise ValueError("bounded_digest_baseline_blob_changed")
    before = git("show", DIGEST_BASE + ":" + DIGEST_PATH)
    after = git("show", candidate + ":" + DIGEST_PATH)
    paths = git("diff", "--name-only", DIGEST_BASE, candidate).decode().splitlines()
    digest_factor(before, after, paths)
    return {"baseline": DIGEST_BASE, "candidate": candidate, "changed_paths": paths,
            "product_path": DIGEST_PATH, "baseline_blob": original_blob,
            "candidate_blob": git("rev-parse", candidate + ":" + DIGEST_PATH).decode().strip(),
            "factor": "digest read bound by the freshly observed file size",
            "qualification_eligible": False}


def admit_digest_comparison(repository, output):
    if output.exists():
        raise ValueError("preserve existing digest factor admission")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {"status": "INPUT_MISMATCH", "qualification_eligible": False}
    try:
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=repository):
            raise ValueError("controlled source is not clean")
        candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository,
                                            text=True).strip()
        result["comparison"] = digest_comparison(repository, candidate)
        result["status"] = "ISOLATED_DIGEST_FACTOR_CONFIRMED"
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        result["reason"] = str(exc)
        write_json(output, result)
        raise
    write_json(output, result)
    return result


def smt_plan(allowed=None, topology=Path("/sys/devices/system/cpu")):
    """Require the originals' two-core/four-thread topology; never emulate SMT."""
    allowed = set(os.sched_getaffinity(0) if allowed is None else allowed)
    cores = {}
    for cpu in sorted(allowed):
        root = topology / f"cpu{cpu}" / "topology"
        identity = tuple(int((root / key).read_text())
                         for key in ("physical_package_id", "core_id"))
        cores.setdefault(identity, []).append(cpu)
    pairs = sorted(cores.values())
    if len(allowed) != 4 or len(pairs) != 2 or any(len(pair) != 2 for pair in pairs):
        raise ValueError("SMT study requires four logical CPUs on two physical cores")
    return {"allowed": sorted(allowed), "cores": pairs,
            "worker_cpus": [pair[0] for pair in pairs],
            "same_logical": pairs[0][0], "smt_sibling": pairs[0][1]}


def require_original_cpu(cpuinfo=Path("/proc/cpuinfo")):
    models = {line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines()
              if line.startswith("model name")}
    if models != {"AMD EPYC 9V74 80-Core Processor"}:
        raise ValueError("original EPYC 9V74 CPU model unavailable")
    return sorted(models)


@contextmanager
def place_probe(context, placement, plan, workers):
    """Change only this probe thread; restore even when the original call fails."""
    if placement is None:
        yield
        return
    before = os.sched_getaffinity(0)
    if before != set(plan["allowed"]):
        raise RuntimeError("probe_inherited_affinity_changed")
    observed = {str(pid): sorted(os.sched_getaffinity(pid)) for pid in workers}
    if any(mask != plan["worker_cpus"] for mask in observed.values()):
        raise RuntimeError("native_worker_affinity_differs_from_predeclared_pair")
    cpu = plan[placement]
    context["placement"] = {"condition": placement, "cpu": cpu,
                            "inherited": sorted(before), "workers": observed,
                            "started_ns": time.monotonic_ns()}
    try:
        os.sched_setaffinity(0, {cpu})
        if os.sched_getaffinity(0) != {cpu}:
            raise RuntimeError("probe_affinity_not_applied")
        context["placement"]["applied_ns"] = time.monotonic_ns()
        yield
    finally:
        context["placement"]["restore_started_ns"] = time.monotonic_ns()
        os.sched_setaffinity(0, before)
        context["placement"]["restored_ns"] = time.monotonic_ns()
        context["placement"]["restored"] = sorted(os.sched_getaffinity(0))
        if os.sched_getaffinity(0) != before:
            raise RuntimeError("probe_affinity_not_restored")


def pool_observer(original):
    """Keep new commit-task counters, queue time and observer envelopes explicit."""
    def submit(executor, function, /, *args, **kwargs):
        context = CURRENT.get()
        if context is None:
            return original(executor, function, *args, **kwargs)
        operation = context.get("active_operation")
        queued = time.monotonic_ns()

        def measured():
            row = {"operation": operation, "queued_ns": queued,
                   "wrapper_started_ns": time.monotonic_ns(),
                   "affinity": sorted(os.sched_getaffinity(0))}
            try:
                with ExitStack() as stack:
                    counters = {}
                    for name in ("schedstat", "io"):
                        try:
                            fd = os.open("/proc/thread-self/" + name,
                                         os.O_RDONLY | os.O_CLOEXEC)
                            stack.callback(os.close, fd)
                            counters[name] = fd
                        except OSError as exc:
                            counters[name] = {"status": "UNKNOWN", "error": type(exc).__name__}

                    def snapshot():
                        values = {}
                        for name, fd in counters.items():
                            try:
                                values[name] = os.pread(fd, 4096, 0).decode("ascii") \
                                    if isinstance(fd, int) else fd
                            except OSError as exc:
                                values[name] = {"status": "UNKNOWN", "error": type(exc).__name__}
                        return values

                    row["counters_before"] = snapshot()
                    row["before"] = accounting()
                    try:
                        return function(*args, **kwargs)
                    finally:
                        row["after"] = accounting()
                        row["counters_after"] = snapshot()
            finally:
                row["wrapper_finished_ns"] = time.monotonic_ns()
                context["pool_tasks"].append(row)
        return original(executor, measured)
    return submit


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_text(path):
    try:
        return path.read_text(encoding="ascii")
    except OSError as exc:
        return {"status": "UNKNOWN", "error": type(exc).__name__}


def tasks(pid):
    """Numeric task accounting only; never collect argv, environment or paths."""
    result = {}
    for task in Path(f"/proc/{pid}/task").glob("[0-9]*"):
        row = {}
        try:
            # Fields following comm start with state (stat field 3).
            values = (task / "stat").read_text().rsplit(")", 1)[1].split()
            row.update(state=values[0], minor_faults=int(values[7]),
                       major_faults=int(values[9]), user_ticks=int(values[11]),
                       system_ticks=int(values[12]), start_ticks=int(values[19]))
            row["schedstat"] = read_text(task / "schedstat")
            row["io"] = read_text(task / "io")
            row["context_switches"] = {
                line.split(":")[0]: int(line.split(":")[1])
                for line in (task / "status").read_text().splitlines()
                if line.startswith(("voluntary_ctxt_switches:", "nonvoluntary_ctxt_switches:"))
            }
        except (OSError, ValueError, IndexError) as exc:
            row["error"] = type(exc).__name__
        result[task.name] = row
    return result


def cgroups(pid):
    """Retain all visible v2 ancestor counters, distinguishing missing hierarchy."""
    try:
        membership = Path(f"/proc/{pid}/cgroup").read_text()
        relative = next(line[3:] for line in membership.splitlines() if line.startswith("0::"))
        root = Path("/sys/fs/cgroup")
        current = root / relative.lstrip("/")
        if ".." in current.parts or not current.is_dir():
            return {"status": "UNKNOWN", "reason": "unmounted_cgroup"}
        rows = []
        while True:
            rows.append({name: read_text(current / name) for name in
                         ("cpu.stat", "cpu.max", "cpu.pressure", "io.stat", "io.pressure")})
            if current == root:
                return rows
            current = current.parent
    except (OSError, StopIteration):
        return {"status": "UNKNOWN", "reason": "cgroup_unavailable"}


def sample(pipe, output):
    """Separate sampler: retain every observation, including exited/missing tasks."""
    selector = selectors.DefaultSelector()
    selector.register(pipe, selectors.EVENT_READ)
    pending = b""
    active = {}
    with output.open("x", encoding="utf-8") as stream:
        while True:
            if selector.select(0.01 if active else None):
                block = os.read(pipe, 65536)
                if not block:
                    break
                pending += block
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    event = json.loads(line)
                    stream.write(json.dumps({"event": event}) + "\n")
                    if event["kind"] == "begin":
                        active[event["probe_id"]] = event
                    else:
                        active.pop(event["probe_id"], None)
            for identity, event in active.items():
                started = time.monotonic_ns()
                row = {"probe_id": identity, "monotonic_ns": started,
                       "realtime_ns": time.time_ns(),
                       "tasks": {str(pid): tasks(pid) for pid in event["pids"]},
                       "cpu_pressure": read_text(Path("/proc/pressure/cpu")),
                       "io_pressure": read_text(Path("/proc/pressure/io")),
                       "cgroups": cgroups(event["pids"][0])}
                row["collection_ns"] = time.monotonic_ns() - started
                row["sampler_cpu_ns"] = time.process_time_ns()
                stream.write(json.dumps(row) + "\n")
        stream.write(json.dumps({"sampler_end": True, "unclosed": list(active),
                                 "partial_bytes": len(pending)}) + "\n")
    selector.close()


def accounting():
    if resource is None:
        raise RuntimeError("native CPU accounting unavailable on this platform")
    result = {"monotonic_ns": time.monotonic_ns(), "realtime_ns": time.time_ns(),
              "process_cpu_ns": time.process_time_ns(), "thread_cpu_ns": time.thread_time_ns(),
              "tid": threading.get_native_id()}
    for name, who in (("thread", resource.RUSAGE_THREAD), ("process", resource.RUSAGE_SELF)):
        usage = resource.getrusage(who)
        result[name] = {key: getattr(usage, "ru_" + key) for key in
                        ("utime", "stime", "nvcsw", "nivcsw", "inblock", "oublock",
                         "minflt", "majflt")}
    return result


class BoundaryCounters:
    """Preopen numeric counters outside capture; bracket even very short calls.

    Tasks born after this inventory remain outside these per-task counters. Parent
    process CPU/rusage and the durability wrapper still include their work.
    """

    def __init__(self, roles, *, cgroup_boundaries=False):
        self.entries = []
        self.inventory = []
        self.cgroup_boundaries = cgroup_boundaries
        for role, pids in roles.items():
            for pid in pids:
                tids = list(Path(f"/proc/{pid}/task").glob("[0-9]*"))
                self.inventory.append({"role": role, "pid": pid, "tasks": len(tids),
                                       "status": "OBSERVED" if tids else "UNKNOWN"})
                for task in tids:
                    entry = {"role": role, "pid": pid, "tid": int(task.name), "fds": {}}
                    for name in ("schedstat", "io"):
                        try:
                            entry["fds"][name] = os.open(task / name, os.O_RDONLY | os.O_CLOEXEC)
                        except OSError as exc:
                            entry["fds"][name] = {"status": "UNKNOWN",
                                                  "error": type(exc).__name__}
                    self.entries.append(entry)

    def snapshot(self):
        started, cpu = time.monotonic_ns(), time.thread_time_ns()
        rows = []
        for entry in self.entries:
            row = {key: entry[key] for key in ("role", "pid", "tid")}
            for name, fd in entry["fds"].items():
                if isinstance(fd, int):
                    try:
                        raw = os.pread(fd, 4096, 0).decode("ascii")
                        row[name] = raw if raw else {"status": "UNKNOWN", "error": "empty_counter"}
                    except OSError as exc:
                        row[name] = {"status": "UNKNOWN", "error": type(exc).__name__}
                else:
                    row[name] = fd
            rows.append(row)
        cgroup = cgroups(os.getpid()) if self.cgroup_boundaries else None
        return {"started_ns": started, "finished_ns": time.monotonic_ns(),
                "cgroups": cgroup,
                "collection_thread_cpu_ns": time.thread_time_ns() - cpu, "tasks": rows}

    def close(self):
        for entry in self.entries:
            for fd in entry["fds"].values():
                if isinstance(fd, int):
                    os.close(fd)


def durability_observer(original, name, active):
    def wrapped(fd):
        context = active()
        if context is None:
            return original(fd)
        row = {"call": name, "operation": context.get("active_operation"),
               "tid": threading.get_native_id(), "wrapper_started_ns": time.monotonic_ns()}
        row["started_cpu_ns"] = time.thread_time_ns()
        row["started_ns"] = time.monotonic_ns()
        try:
            return original(fd)
        finally:
            row["finished_ns"] = time.monotonic_ns()
            row["finished_cpu_ns"] = time.thread_time_ns()
            row["wrapper_finished_ns"] = time.monotonic_ns()
            # Shared only by this serial probe, including its commit-pool threads.
            context["durability"].append(row)
    return wrapped


def calibrate_scheduler():
    """Require a positive runqueue counter under known synthetic contention.

    A readable zero, missing sysctl or virtual /proc is not evidence of no wait.
    This does not qualify the host or reproduce an application failure.
    """
    code = """
import json, os, sys, time
os.sched_setaffinity(0, {int(sys.argv[1])})
print('READY', flush=True)
sys.stdin.buffer.read(1)
def counters():
    with open('/proc/thread-self/schedstat') as stream:
        return list(map(int, stream.read().split()))
before = counters()
start = time.monotonic_ns()
cpu = time.thread_time_ns()
while time.monotonic_ns() - start < 300_000_000:
    pass
after = counters()
print(json.dumps({'before': before, 'after': after,
                  'wall_ns': time.monotonic_ns()-start,
                  'thread_cpu_ns': time.thread_time_ns()-cpu}), flush=True)
"""
    children = []
    result = {"status": "UNKNOWN", "sched_schedstats":
              read_text(Path("/proc/sys/kernel/sched_schedstats")), "children": []}
    try:
        cpu = min(os.sched_getaffinity(0))
        for _ in range(2):
            child = subprocess.Popen([sys.executable, "-c", code, str(cpu)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            children.append(child)
            with selectors.DefaultSelector() as ready:
                ready.register(child.stdout, selectors.EVENT_READ)
                if not ready.select(10) or child.stdout.readline().strip() != "READY":
                    raise RuntimeError("scheduler_calibration_child_not_ready")
        for child in children:
            child.stdin.write("x")
            child.stdin.flush()
        for child in children:
            stdout, stderr = child.communicate(timeout=10)
            result["children"].append({"exit_code": child.returncode,
                                       "counters": json.loads(stdout), "stderr": stderr})
        if all(row["exit_code"] == 0 and row["counters"]["thread_cpu_ns"] > 0
               and row["counters"]["after"][0] > row["counters"]["before"][0]
               and row["counters"]["after"][1] > row["counters"]["before"][1]
               for row in result["children"]):
            result["status"] = "POSITIVE_RUNQUEUE_CONTROL"
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result["error"] = type(exc).__name__
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
    return result


def nonqualifying(evaluate):
    def wrapped(report):
        evaluate(report)
        report["instrumented_evaluated_status"] = report["status"]
        report["status"] = "DIAGNOSTIC_ONLY"
        report["qualification_eligible"] = False
        return report
    return wrapped


def observe_operation(original, name):
    def wrapped(*args, **kwargs):
        context = CURRENT.get()
        if context is None:
            return original(*args, **kwargs)
        row = {"operation": name}
        boundary = context.get("_boundary")
        if boundary is not None:
            row["boundary_before"] = boundary.snapshot()
            context["active_operation"] = name
        row["before"] = accounting()
        try:
            return original(*args, **kwargs)
        finally:
            row["after"] = accounting()
            if boundary is not None:
                row["boundary_after"] = boundary.snapshot()
                context.pop("active_operation", None)
            context["operations"].append(row)
    return wrapped


def observe_span(original, name):
    """Time a caller-bound method directly; never use a cross-thread profile stack."""
    def wrapped(*args, **kwargs):
        context = CURRENT.get()
        if context is None:
            return original(*args, **kwargs)
        row = {"span": name, "operation": context.get("active_operation"),
               "before": accounting()}
        try:
            return original(*args, **kwargs)
        except BaseException as error:
            row["error"] = type(error).__name__
            raise
        finally:
            row["after"] = accounting()
            context["spans"].append(row)
    return wrapped


class PrefixStop(BaseException):
    """Let the unchanged qualifier finalize its partial report and native cleanup."""
    def __init__(self, reason, evidence=None):
        self.reason = reason
        self.evidence = evidence


def prefix_warm_case(original):
    def wrapped(report, store, runtime, selection, evidence, case, run):
        if report.get("failures"):
            raise PrefixStop("APPLICATION_FAILURE")
        busy = report.get("deterministic_busy", [])
        if not busy or not all(row.get("worker_observed") for row in busy):
            raise PrefixStop("MISSING_CONCURRENCY")
        if run == 1:
            if len(report.get("samples", [])) != 20 or len(busy) != 2:
                raise PrefixStop("INCOMPLETE_PREFIX")
            raise PrefixStop("TARGET_PREFIX_COMPLETE")
        result = original(report, store, runtime, selection, evidence, case, run)
        if report.get("failures") or not report["samples"][-1]["pass"]:
            raise PrefixStop("APPLICATION_FAILURE")
        return result
    return wrapped


def prefix_self_test(original):
    def wrapped(*args, **kwargs):
        evidence = original(*args, **kwargs)
        if evidence.result != "PASSED":
            raise PrefixStop("SELF_TEST_FAILED", evidence.public_record())
        return evidence
    return wrapped


def prefix_environment():
    """Retain host path/locale selectors without credentials or proxy headers."""
    result = {name: os.environ[name] for name in
              ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP")
              if name in os.environ}
    result["PYTHONNOUSERSITE"] = "1"
    return result


def worker(source, artifacts, output, mode="legacy", placement=None,
           inherited_affinity=None, tracer_cpu=None, pool_accounting=False, pool_prefix=False):
    if pool_prefix and (mode != "boundary" or not pool_accounting or placement is not None
                        or inherited_affinity is not None or tracer_cpu is not None):
        raise ValueError("pool prefix requires boundary accounting without placement changes")
    if pool_prefix and any((output / name).exists() or (output / name).is_symlink()
                           for name in ("report-before-observer.json", "probe-accounting.jsonl",
                                        "prefix-state.json")):
        raise ValueError("preserve existing prefix evidence")
    if pool_accounting and mode == "legacy":
        raise ValueError("pool accounting requires operation-boundary counters")
    # The tracer alone receives its one-CPU condition. Restore the child before
    # application imports, hardware checks or any native worker can be created.
    if inherited_affinity is not None:
        os.sched_setaffinity(0, inherited_affinity)
        if os.sched_getaffinity(0) != set(inherited_affinity):
            raise RuntimeError("tracee_inherited_affinity_not_restored")
    sys.path[:0] = [str(source / "scripts"), str(source / "core"), str(source)]
    import ai_runtime_report
    import qualify_ai_runtime

    from provelume.ai_runtime import LocalRuntime
    from provelume.capture_adapter import CaptureAdapter

    plan = (portable_tracer_plan() if placement == "portable_foreground" else smt_plan()) \
        if placement is not None else None
    instances = []
    original_init = LocalRuntime.__init__

    def runtime_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        instances.append(self)

    sampler, write_pipe = None, None
    if mode != "boundary":
        read_pipe, write_pipe = os.pipe()
        sampler = subprocess.Popen([sys.executable, str(SCRIPT), "sample", "--pipe", str(read_pipe),
                                    "--output", str(output / "timeline.jsonl")],
                                   pass_fds=(read_pipe,))
        os.close(read_pipe)
    raw_probe = ai_runtime_report.deterministic_probe
    sequence = 0
    active = None

    def probe(instance, number):
        nonlocal sequence, active
        sequence += 1
        context = {"probe_id": sequence, "sample": number, "operations": [],
                   "caller": Path(sys._getframe(1).f_code.co_filename).name,
                   "before": accounting()}
        if pool_prefix:
            context["spans"] = []
        roles = {"parent": [os.getpid()], "tracer": [os.getppid()],
                 "sampler": [sampler.pid] if sampler else [],
                 "workers": [r._process.pid for r in instances if r._process is not None]}
        if tracer_cpu is not None:
            observed = sorted(os.sched_getaffinity(os.getppid()))
            context["tracer_affinity"] = observed
            if observed != [tracer_cpu]:
                raise RuntimeError("tracer_affinity_differs_from_declared_condition")
        pids = [pid for values in roles.values() for pid in values]
        event = {"kind": "begin", "probe_id": sequence, "sample": number,
                 "caller": context["caller"], "pids": list(dict.fromkeys(pids)),
                 "roles": {"parent": os.getpid(), "tracer": os.getppid(),
                           "sampler": sampler.pid if sampler else None,
                           "workers": roles["workers"]},
                 "monotonic_ns": time.monotonic_ns(), "realtime_ns": time.time_ns()}
        if write_pipe is not None:
            os.write(write_pipe, (json.dumps(event) + "\n").encode())
        boundary = BoundaryCounters(roles, cgroup_boundaries=placement is not None) \
            if mode != "legacy" else None
        if boundary is not None:
            context.update(_boundary=boundary, boundary_inventory=boundary.inventory,
                           roles=roles, durability=[], observation_mode=mode, pool_tasks=[])
        active = context
        token = CURRENT.set(context)
        try:
            with place_probe(context, placement, plan, roles["workers"]):
                row = raw_probe(instance, number)
                if placement is not None and any(
                    task["affinity"] != [plan[placement]] for task in context["pool_tasks"]
                ):
                    raise RuntimeError("capture_pool_task_affinity_differs_from_condition")
            row["diagnostic_timeline"] = context
            return row
        finally:
            context["after"] = accounting()
            CURRENT.reset(token)
            active = None
            if boundary is not None:
                boundary.close()
                context.pop("_boundary")
            # Save even an exceptional probe, outside its original measured interval.
            with (output / "probe-accounting.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(context) + "\n")
            if write_pipe is not None:
                os.write(write_pipe, (json.dumps({"kind": "end", "probe_id": sequence,
                         "monotonic_ns": time.monotonic_ns()}) + "\n").encode())

    prefix_state = {"status": "DIAGNOSTIC_ONLY", "qualification_eligible": False,
                    "stop": "APPLICATION_ERROR"}
    try:
        with ExitStack() as stack:
            if placement is not None or pool_accounting:
                stack.enter_context(patch.object(ThreadPoolExecutor, "submit",
                    pool_observer(ThreadPoolExecutor.submit)))
            stack.enter_context(patch.object(LocalRuntime, "__init__", runtime_init))
            stack.enter_context(patch.object(ai_runtime_report, "deterministic_probe", probe))
            stack.enter_context(patch.object(qualify_ai_runtime, "deterministic_probe", probe))
            if mode != "legacy":
                for name in ("fsync", "fdatasync"):
                    stack.enter_context(patch.object(os, name, durability_observer(
                        getattr(os, name), name, lambda: active)))
            for target in (ai_runtime_report, qualify_ai_runtime):
                stack.enter_context(patch.object(target, "evaluate",
                                                  nonqualifying(target.evaluate)))
            for name in ("submit", "process"):
                stack.enter_context(patch.object(CaptureAdapter, name,
                    observe_operation(getattr(CaptureAdapter, name), name)))
            if pool_prefix:
                from provelume.ai_model_store import ModelStore
                from provelume.atomic_commit import AtomicInstanceCommit

                for name in ("_prepare", "_publish_entries", "_shutdown_pool"):
                    stack.enter_context(patch.object(AtomicInstanceCommit, name,
                        observe_span(getattr(AtomicInstanceCommit, name), name)))
                stack.enter_context(patch.object(qualify_ai_runtime, "measure_warm_case",
                    prefix_warm_case(qualify_ai_runtime.measure_warm_case)))
                stack.enter_context(patch.object(ModelStore, "self_test",
                    prefix_self_test(ModelStore.self_test)))
            try:
                report = qualify_ai_runtime.measure(
                    artifacts, output / "report-before-observer.json")
            except PrefixStop as stopped:
                if not pool_prefix:
                    raise
                prefix_state.update(stop=stopped.reason, evidence=stopped.evidence)
                report = json.loads((output / "report-before-observer.json").read_text())
            report["diagnostic_driver_sha256"] = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
            report["diagnostic_observation_mode"] = mode
            report["diagnostic_placement"] = placement
            write_json(output / "report-before-observer.json", report)
    finally:
        if pool_prefix:
            write_json(output / "prefix-state.json", prefix_state)
        if write_pipe is not None:
            os.close(write_pipe)
        if sampler is not None and sampler.wait(timeout=30) != 0:
            raise RuntimeError("sampler_failed")


def observe(source, output):
    """Original observer, in a fresh process AFTER strace and all tracees exit."""
    sys.path[:0] = [str(source / "scripts"), str(source / "core"), str(source)]
    from scripts import ai_runtime_network

    report = json.loads((output / "report-before-observer.json").read_text())
    with patch.object(ai_runtime_network, "evaluate", nonqualifying(ai_runtime_network.evaluate)):
        ai_runtime_network.observe(report, trace=output / "network")
    write_json(output / "report.json", report)



def _observed_task_counters(value):
    raw = value.get("schedstat")
    if not isinstance(raw, str) or not isinstance(value.get("io"), str):
        return False
    try:
        numbers = [int(item) for item in raw.split()]
    except ValueError:
        return False
    return len(numbers) == 3 and min(numbers) >= 0 and bool(value["io"])


def verify_digest_accounting(output, expected_probes=25):
    """Refuse another arm when the required contemporaneous counters are absent."""
    rows = [json.loads(line) for line in
            (output / "probe-accounting.jsonl").read_text().splitlines()]
    if [row["probe_id"] for row in rows] != list(range(1, expected_probes + 1)):
        raise ValueError("digest_probe_collection_incomplete")
    pool_count = 0
    for row in rows:
        if sorted(op["operation"] for op in row["operations"]) != ["process", "submit"]:
            raise ValueError("digest_operation_collection_incomplete")
        for op in row["operations"]:
            for label in ("boundary_before", "boundary_after"):
                callers = [task for task in op[label]["tasks"]
                           if task["role"] == "parent" and task["tid"] == op["before"]["tid"]]
                if len(callers) != 1 or not _observed_task_counters(callers[0]):
                    raise ValueError("digest_caller_counter_gap")
        for task in row["pool_tasks"]:
            pool_count += 1
            if any(not _observed_task_counters(task[label])
                   for label in ("counters_before", "counters_after")):
                raise ValueError("digest_pool_counter_gap")
    if not pool_count:
        raise ValueError("digest_pool_collection_incomplete")
    return {"status": "REQUIRED_COUNTERS_COMPLETE", "probes": expected_probes,
            "operations": 2 * expected_probes, "snapshots": 4 * expected_probes,
            "pool_tasks": pool_count}


def inspect_prefix(output):
    """Check collection of the partial prefix without qualifying a full network gate."""
    report = json.loads((output / "report.json").read_text())
    state = json.loads((output / "prefix-state.json").read_text())
    rows = [json.loads(line) for line in
            (output / "probe-accounting.jsonl").read_text().splitlines()]
    errors = []
    if state.get("stop") != "TARGET_PREFIX_COMPLETE" or report.get("failures"):
        errors.append("prefix application or boundary failure")
    if (report.get("status") != "DIAGNOSTIC_ONLY"
            or report.get("qualification_eligible") is not False
            or "instrumented_evaluated_status" not in report):
        errors.append("original partial verdict not preserved")
    if (report.get("network") != "NOT_RUN"
            or report.get("network_observation", {}).get("complete_phases") is not False):
        errors.append("partial prefix cannot qualify the original full-phase network gate")
    idle, busy = report.get("deterministic_idle", []), report.get("deterministic_busy", [])
    if (len(idle) != 3 or len(busy) != 2 or len(report.get("samples", [])) != 20
            or not all(p.get("preserved") and p.get("search_found") for p in idle + busy)
            or not all(p.get("worker_observed") for p in busy)
            or not all(p.get("pass") for p in report.get("samples", []))):
        errors.append("prefix cases or concurrency incomplete")
    try:
        counters = verify_digest_accounting(output, expected_probes=5)
    except ValueError as error:
        counters = None
        errors.append(str(error))
    for row in rows:
        spans = row.get("spans", [])
        if sorted(s["span"] for s in spans) != sorted(
                ["_prepare", "_publish_entries", "_shutdown_pool"] * 2):
            errors.append("direct method spans incomplete")
            break
        operations = {op["operation"]: op for op in row["operations"]}
        if any(sorted(s["span"] for s in spans if s["operation"] == name)
               != ["_prepare", "_publish_entries", "_shutdown_pool"] for name in operations):
            errors.append("transaction span sequence incomplete")
        for span in spans:
            operation = operations.get(span["operation"])
            before, after = span["before"], span["after"]
            if (operation is None or before["tid"] != after["tid"]
                    or before["tid"] != operation["before"]["tid"]
                    or not operation["before"]["monotonic_ns"] <= before["monotonic_ns"]
                    <= after["monotonic_ns"] <= operation["after"]["monotonic_ns"]):
                errors.append("direct span caller or interval mismatch")
    traces = list(output.glob("network.*"))
    calls = [line for path in traces for line in path.read_text().splitlines()
             if re.search(r"\b(socket|connect|sendto|sendmsg|sendmmsg)\(", line)]
    unexpected = [line for line in calls if "= -1 EPERM" not in line]
    if unexpected:
        errors.append("unexpected prefix network call")
    exits = {}
    for pid in report.get("worker_pids", []):
        path = output / ("network." + str(pid))
        exits[str(pid)] = path.is_file() and bool(re.search(
            r"\+\+\+ (?:exited with \d+|killed by SIG[^\n]+) \+\+\+", path.read_text()))
    if not exits or not all(exits.values()):
        errors.append("native exits not observed")
    result = {"status": "PREFIX_COLLECTION_COMPLETE" if not errors else "INCOMPLETE",
              "qualification_eligible": False, "errors": errors, "counters": counters,
              "prefix_network_calls": calls, "native_trace_exits": exits,
              "full_phase_network_gate": "NOT_RUN",
              "original_partial_evaluated_status": report.get("instrumented_evaluated_status")}
    write_json(output / "prefix-inspection.json", result)
    return result


def run(repository, inputs, output, reverse=False, observer_study=False, placement_study=False,
        tracer_study=False, portable_tracer_study=False, digest_study=False,
        observer_revision=None, pool_prefix=False):
    """Four fixed arms, once each, same runner/interpreter/path; no retry-to-green."""
    if digest_study and reverse:
        raise ValueError("bounded digest comparison has one fixed AB/BA order")
    if pool_prefix and (not observer_study or observer_revision is None):
        raise ValueError("pool prefix requires an explicit observer source")
    selected = None
    if observer_revision is not None:
        if not observer_study or reverse or any((placement_study, tracer_study,
                                                portable_tracer_study, digest_study)):
            raise ValueError("single-source observer control requires its fixed ABBA order")
        selected = observer_source(repository, observer_revision)
    output.mkdir(parents=True, exist_ok=False)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository,
                                        text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repository):
        raise ValueError("controlled replay requires unchanged committed source")
    arms = ([("s06-boundary", S06, "boundary"), ("s06-extended", S06, "extended"),
             ("s08-extended", S08, "extended"), ("s08-boundary", S08, "boundary")]
            if observer_study else
            [("main", MAIN, "legacy"), ("s06-original", S06, "legacy"),
             ("s08-original", S08, "legacy"), ("candidate", candidate, "legacy")])
    if reverse:
        arms.reverse()
    if selected is not None:
        arms = [("main-boundary-a", observer_revision, "boundary"),
                ("main-extended-b1", observer_revision, "extended"),
                ("main-extended-b2", observer_revision, "extended"),
                ("main-boundary-a2", observer_revision, "boundary")]
    if pool_prefix:
        arms = [("main-pool-prefix", observer_revision, "boundary")]
    placements = {}
    tracer_cpus = {}
    if placement_study:
        arms = [("s06-same", S06, "boundary"), ("s06-sibling", S06, "boundary"),
                ("s08-sibling", S08, "boundary"), ("s08-same", S08, "boundary")]
        placements = {name: "same_logical" if name.endswith("same") else "smt_sibling"
                      for name, _, _ in arms}
    if tracer_study or portable_tracer_study or digest_study:
        plan = portable_tracer_plan() if portable_tracer_study or digest_study else smt_plan()
        if tracer_study:
            require_original_cpu()
        arms = [("s06-tracer-shared", S06, "boundary"),
                ("s06-tracer-other", S06, "boundary"),
                ("s08-tracer-other", S08, "boundary"),
                ("s08-tracer-shared", S08, "boundary")]
        if digest_study:
            digest_comparison(repository, candidate)
            arms = [("s06-baseline", DIGEST_BASE, "boundary"),
                    ("s06-candidate", candidate, "boundary"),
                    ("s08-candidate", candidate, "boundary"),
                    ("s08-baseline", DIGEST_BASE, "boundary")]
        placement = ("portable_foreground"
                     if portable_tracer_study or digest_study else "smt_sibling")
        placements = dict.fromkeys((name for name, _, _ in arms), placement)
        other = (plan["tracer_other"]
                 if portable_tracer_study or digest_study else plan["cores"][1][1])
        tracer_cpus = {name: plan[placement] if digest_study or name.endswith("shared") else other
                       for name, _, _ in arms}
    manifest = {"status": "DIAGNOSTIC_ONLY", "qualification_eligible": False,
                "candidate": candidate,
                "driver_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                "arms": [], "python": sys.version, "clock_ticks": os.sysconf("SC_CLK_TCK"),
                "sched_schedstats": read_text(Path("/proc/sys/kernel/sched_schedstats")),
                "observer": "strace -ff -ttt -T; syscall set recorded per arm",
                "sampling_seconds": 0.01, "order": [name for name, _, _ in arms],
                "experiment": "caller-bound-pool-prefix" if pool_prefix else
                    "bounded-digest-product-comparison" if digest_study else
                    "portable-tracer-placement" if portable_tracer_study else
                    "tracer-placement" if tracer_study else
                    "SMT-placement" if placement_study else
                    "observer-study" if observer_study else "source-comparison",
                "limitations": ["instrumentation perturbs timing", "one runner is not a fleet",
                                "OS cache not flushed", "task exits can truncate task accounting",
                                "proc sampling does not prove individual syscall causality"]}
    write_json(output / "manifest.json", manifest)
    if selected is not None:
        manifest["experiment"] = ("caller-bound-pool-prefix" if pool_prefix
                                  else "current-main-observer-bundle")
        manifest["selected_source"] = selected
        manifest["common_pool_accounting"] = True
        manifest["limitations"].append("new-task observer cost is retained, never subtracted")
        if pool_prefix:
            manifest["prefix"] = "3 idle; run0 busy and 20 warm cases; run1 busy; stop before warm"
            manifest["limitations"].append("partial prefix cannot qualify full-phase network")
        write_json(output / "manifest.json", manifest)
    shutil.copyfile(SCRIPT, output / "driver.py")
    if digest_study:
        manifest["product_comparison"] = digest_comparison(repository, candidate)
    if portable_tracer_study or digest_study:
        manifest["observed_environment"] = portable_environment()
        manifest["limitations"].append("not a reproduction of the original EPYC9V74 host")
    if placement_study or tracer_study or portable_tracer_study or digest_study:
        manifest["placement_plan"] = (portable_tracer_plan()
                                      if portable_tracer_study or digest_study else smt_plan())
        if tracer_study:
            manifest["required_cpu_models"] = require_original_cpu()
        write_json(output / "manifest.json", manifest)
    if (observer_study or placement_study or tracer_study
            or portable_tracer_study or digest_study):
        manifest["scheduler_calibration"] = calibrate_scheduler()
        write_json(output / "manifest.json", manifest)
        if manifest["scheduler_calibration"]["status"] != "POSITIVE_RUNQUEUE_CONTROL":
            raise RuntimeError("scheduler_counter_not_demonstrated; no replay started")
    with (output / "dependencies.txt").open("w") as stream:
        subprocess.run([sys.executable, "-m", "pip", "freeze"], stdout=stream, check=True)
    with (
        tempfile.TemporaryDirectory(prefix="concordia-cpu-") as scratch,
        tempfile.TemporaryDirectory(prefix="s05-replay-", dir=inputs.parent) as replay,
    ):
        source = Path(scratch) / "source"
        data = Path(replay)
        # The original workflow measures RUNNER_TEMP/s05-inputs. Preserve its
        # component count: physical path guards are part of the capture cost.
        if len(data.parts) != len(inputs.parts):
            raise ValueError("measurement path depth differs from acquired input root")
        manifest["measurement_path_depth"] = len(data.parts)
        manifest["acquired_input_path_depth"] = len(inputs.parts)
        for name, revision, mode in arms:
            arm_output = output / name
            arm_output.mkdir()
            arm = {"name": name, "source": revision, "observation_mode": mode,
                   "placement": placements.get(name),
                   "tracer_cpu": tracer_cpus.get(name),
                   "started_ns": time.time_ns(),
                   "trace": "network" if mode == "boundary" else "network,fsync,fdatasync"}
            manifest["arms"].append(arm)
            write_json(output / "manifest.json", manifest)
            subprocess.run(["git", "worktree", "add", "--detach", str(source), revision],
                           cwd=repository, check=True)
            try:
                # Identical locked acquisition, separate installed store and synthetic Instance.
                data.mkdir(exist_ok=True)
                shutil.copytree(inputs / "linux", data / "linux")
                shutil.copyfile(inputs / "model.gguf", data / "model.gguf")
                arm["tree"] = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"],
                                                       cwd=source, text=True).strip()
                arm["input_blobs"] = {path: subprocess.check_output(
                    ["git", "rev-parse", revision + ":" + path], cwd=repository, text=True).strip()
                    for path in ("scripts/ai_runtime_report.py", "scripts/qualify_ai_runtime.py",
                                 "scripts/qualify_ai_jobs.py", "scripts/qualify_ai_synthesis.py",
                                 "scripts/ai_runtime_network.py",
                                 "core/provelume/ai_runtime_contract.py",
                                 "core/provelume/atomic_commit.py",
                                 "core/provelume/capture_adapter.py")}
                with (arm_output / "execution.log").open("w") as stream:
                    placement_args = ["--placement", placements[name]] \
                        if (placement_study or tracer_study or portable_tracer_study
                            or digest_study) else []
                    if selected is not None:
                        placement_args += ["--pool-accounting"]
                    if pool_prefix:
                        placement_args += ["--pool-prefix"]
                    if tracer_study or portable_tracer_study or digest_study:
                        placement_args += ["--inherited-affinity",
                            ",".join(map(str, manifest["placement_plan"]["allowed"])),
                            "--tracer-cpu", str(tracer_cpus[name])]
                    command = ["strace", "-ff", "-ttt", "-T", "-e",
                        "trace=" + arm["trace"], "-o", str(arm_output / "network"),
                        sys.executable, str(SCRIPT), "worker", "--source", str(source),
                        "--artifacts", str(data), "--output", str(arm_output), "--mode", mode,
                        *placement_args]
                    if tracer_study or portable_tracer_study or digest_study:
                        command = ["taskset", "--cpu-list", str(tracer_cpus[name]), *command]
                    child_environment = None
                    if pool_prefix:
                        # Preserve harmless selectors, excluding credentials and proxy headers.
                        child_environment = prefix_environment()
                    process = subprocess.Popen(command, env=child_environment,
                        cwd=source, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True)
                    try:
                        arm["exit_code"] = process.wait(timeout=1200)
                    except subprocess.TimeoutExpired:
                        arm["timeout"] = True
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
                        write_json(output / "manifest.json", manifest)
                        # Never start another arm after a timeout; retain partial evidence.
                        raise
                if arm["exit_code"] == 0:
                    with (arm_output / "observer.log").open("w") as stream:
                        observed = subprocess.run([sys.executable, str(SCRIPT), "observe",
                            "--source", str(source), "--output", str(arm_output)],
                            cwd=source, stdout=stream, stderr=subprocess.STDOUT, timeout=60)
                    arm["observer_exit_code"] = observed.returncode
                arm["finished_ns"] = time.time_ns()
                write_json(output / "manifest.json", manifest)
                if pool_prefix:
                    if arm["exit_code"] != 0 or arm.get("observer_exit_code") != 0:
                        raise RuntimeError("prefix execution or observation failed; no retry")
                    arm["prefix_inspection"] = inspect_prefix(arm_output)
                    write_json(output / "manifest.json", manifest)
                    if arm["prefix_inspection"]["status"] != "PREFIX_COLLECTION_COMPLETE":
                        raise RuntimeError("prefix collection incomplete; no retry")
                    continue
                if selected is not None:
                    if arm["exit_code"] != 0 or arm.get("observer_exit_code") != 0:
                        raise RuntimeError("observer_arm_or_collection_failed; no next arm")
                    report = json.loads((arm_output / "report.json").read_text())
                    if report.get("network") != "PASS" or report.get("failures"):
                        raise RuntimeError("observer_network_or_application_failed; no next arm")
                    arm["accounting_integrity"] = verify_digest_accounting(arm_output)
                    stop_path = arm_output / "non-timing-stop-control.json"
                    subprocess.run([sys.executable, str(repository / "scripts" /
                        "compare_concordia_journal.py"), "inspect", "--source", str(source),
                        "--report", str(arm_output / "report.json"), "--output", str(stop_path)],
                        cwd=source, check=True, timeout=60)
                    stop = json.loads(stop_path.read_text())
                    arm["non_timing_conjuncts_pass"] = stop["non_capture_conjuncts_checked"]
                    write_json(output / "manifest.json", manifest)
                    if not arm["non_timing_conjuncts_pass"]:
                        raise RuntimeError("observer_non_timing_failure; no next arm")
                if placement_study or tracer_study or portable_tracer_study or digest_study:
                    if arm["exit_code"] != 0 or arm.get("observer_exit_code") != 0:
                        raise RuntimeError("SMT_arm_or_observer_failed; no next arm")
                    report = json.loads((arm_output / "report.json").read_text())
                    if report.get("network") != "PASS" or report.get("failures"):
                        raise RuntimeError("SMT_collection_incomplete; no next arm")
                    if digest_study:
                        arm["accounting_integrity"] = verify_digest_accounting(arm_output)
                        write_json(output / "manifest.json", manifest)
                    capture_gates = {"deterministic", "s06_governed", "s07_setup",
                                     "s08_performance"}
                    if any(value != "PASS" for key, value in report["gates"].items()
                           if key not in capture_gates):
                        raise RuntimeError("SMT_non_capture_gate_failed; no next arm")
            finally:
                subprocess.run(["git", "worktree", "remove", str(source)], cwd=repository,
                               check=True)
                shutil.rmtree(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sampling = commands.add_parser("sample")
    sampling.add_argument("--pipe", type=int, required=True)
    sampling.add_argument("--output", type=Path, required=True)
    measurement = commands.add_parser("worker")
    measurement.add_argument("--source", type=Path, required=True)
    measurement.add_argument("--artifacts", type=Path, required=True)
    measurement.add_argument("--output", type=Path, required=True)
    measurement.add_argument("--mode", choices=("legacy", "boundary", "extended"), default="legacy")
    measurement.add_argument("--pool-accounting", action="store_true")
    measurement.add_argument("--pool-prefix", action="store_true")
    measurement.add_argument("--placement",
                             choices=("same_logical", "smt_sibling", "portable_foreground"))
    measurement.add_argument("--inherited-affinity", type=lambda raw: set(map(int, raw.split(","))))
    measurement.add_argument("--tracer-cpu", type=int)
    topology = commands.add_parser("smt-topology")
    topology.add_argument("--output", type=Path, required=True)
    topology.add_argument("--require-original-cpu", action="store_true")
    portable = commands.add_parser("portable-topology")
    portable.add_argument("--output", type=Path, required=True)
    digest = commands.add_parser("digest-admission")
    digest.add_argument("--repository", type=Path, required=True)
    digest.add_argument("--output", type=Path, required=True)
    observer_admission = commands.add_parser("observer-admission")
    observer_admission.add_argument("--repository", type=Path, required=True)
    observer_admission.add_argument("--source", required=True)
    observer_admission.add_argument("--output", type=Path, required=True)
    observation = commands.add_parser("observe")
    observation.add_argument("--source", type=Path, required=True)
    observation.add_argument("--output", type=Path, required=True)
    controlled = commands.add_parser("run")
    controlled.add_argument("--repository", type=Path, required=True)
    controlled.add_argument("--inputs", type=Path, required=True)
    controlled.add_argument("--output", type=Path, required=True)
    controlled.add_argument("--reverse", action="store_true")
    controlled.add_argument("--observer-source")
    controlled.add_argument("--pool-prefix", action="store_true")
    study = controlled.add_mutually_exclusive_group()
    study.add_argument("--observer-study", action="store_true")
    study.add_argument("--placement-study", action="store_true")
    study.add_argument("--tracer-study", action="store_true")
    study.add_argument("--portable-tracer-study", action="store_true")
    study.add_argument("--bounded-digest-study", action="store_true")
    args = parser.parse_args()
    if args.command == "sample":
        sample(args.pipe, args.output)
    elif args.command == "worker":
        worker(args.source.resolve(), args.artifacts.resolve(), args.output.resolve(), args.mode,
               args.placement, args.inherited_affinity, args.tracer_cpu, args.pool_accounting,
               args.pool_prefix)
    elif args.command == "observer-admission":
        admit_observer(args.repository.resolve(), args.source, args.output)
    elif args.command == "portable-topology":
        admit_portable(args.output)
    elif args.command == "digest-admission":
        admit_digest_comparison(args.repository.resolve(), args.output)
    elif args.command == "smt-topology":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = {"status": "SMT_TOPOLOGY_CONFIRMED", "plan": smt_plan()}
            if args.require_original_cpu:
                result["cpu_models"] = require_original_cpu()
                if shutil.which("taskset") is None:
                    raise ValueError("tracer affinity transport unavailable")
            write_json(args.output, result)
        except (OSError, ValueError) as exc:
            write_json(args.output, {"status": "CAPABILITY_MISSING", "reason": str(exc)})
            raise
    elif args.command == "observe":
        observe(args.source.resolve(), args.output.resolve())
    else:
        run(args.repository.resolve(), args.inputs.resolve(), args.output.resolve(), args.reverse,
            args.observer_study, args.placement_study, args.tracer_study,
            args.portable_tracer_study, args.bounded_digest_study, args.observer_source,
            args.pool_prefix)


if __name__ == "__main__":
    main()
