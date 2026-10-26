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
import resource
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

MAIN = "096782e32a3d019c3e160c2569507d55cadfd274"
S06 = "8b3f467aa9e7c059e23f22644786ef0f87582cc3"
S08 = "e2c9244df692cdd9dbd636a0109a7d920a21ac1b"
SCRIPT = Path(__file__).resolve()
CURRENT = contextvars.ContextVar("concordia_probe", default=None)


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


def worker(source, artifacts, output, mode="legacy", placement=None,
           inherited_affinity=None, tracer_cpu=None):
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

    plan = smt_plan() if placement is not None else None
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

    try:
        with ExitStack() as stack:
            if placement is not None:
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
            report = qualify_ai_runtime.measure(artifacts, output / "report-before-observer.json")
            report["diagnostic_driver_sha256"] = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
            report["diagnostic_observation_mode"] = mode
            report["diagnostic_placement"] = placement
            write_json(output / "report-before-observer.json", report)
    finally:
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


def run(repository, inputs, output, reverse=False, observer_study=False, placement_study=False,
        tracer_study=False):
    """Four fixed arms, once each, same runner/interpreter/path; no retry-to-green."""
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
    placements = {}
    tracer_cpus = {}
    if placement_study:
        arms = [("s06-same", S06, "boundary"), ("s06-sibling", S06, "boundary"),
                ("s08-sibling", S08, "boundary"), ("s08-same", S08, "boundary")]
        placements = {name: "same_logical" if name.endswith("same") else "smt_sibling"
                      for name, _, _ in arms}
    if tracer_study:
        plan = smt_plan()
        require_original_cpu()
        arms = [("s06-tracer-shared", S06, "boundary"),
                ("s06-tracer-other", S06, "boundary"),
                ("s08-tracer-other", S08, "boundary"),
                ("s08-tracer-shared", S08, "boundary")]
        placements = dict.fromkeys((name for name, _, _ in arms), "smt_sibling")
        tracer_cpus = {name: plan["smt_sibling"] if name.endswith("shared") else plan["cores"][1][1]
                       for name, _, _ in arms}
    manifest = {"status": "DIAGNOSTIC_ONLY", "qualification_eligible": False,
                "candidate": candidate,
                "driver_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                "arms": [], "python": sys.version, "clock_ticks": os.sysconf("SC_CLK_TCK"),
                "sched_schedstats": read_text(Path("/proc/sys/kernel/sched_schedstats")),
                "observer": "strace -ff -ttt -T; syscall set recorded per arm",
                "sampling_seconds": 0.01, "order": [name for name, _, _ in arms],
                "experiment": "tracer-placement" if tracer_study else
                    "SMT-placement" if placement_study else
                    "observer-study" if observer_study else "source-comparison",
                "limitations": ["instrumentation perturbs timing", "one runner is not a fleet",
                                "OS cache not flushed", "task exits can truncate task accounting",
                                "proc sampling does not prove individual syscall causality"]}
    write_json(output / "manifest.json", manifest)
    shutil.copyfile(SCRIPT, output / "driver.py")
    if placement_study or tracer_study:
        manifest["placement_plan"] = smt_plan()
        if tracer_study:
            manifest["required_cpu_models"] = require_original_cpu()
        write_json(output / "manifest.json", manifest)
    if observer_study or placement_study or tracer_study:
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
                        if placement_study or tracer_study else []
                    if tracer_study:
                        placement_args += ["--inherited-affinity",
                            ",".join(map(str, manifest["placement_plan"]["allowed"])),
                            "--tracer-cpu", str(tracer_cpus[name])]
                    command = ["strace", "-ff", "-ttt", "-T", "-e",
                        "trace=" + arm["trace"], "-o", str(arm_output / "network"),
                        sys.executable, str(SCRIPT), "worker", "--source", str(source),
                        "--artifacts", str(data), "--output", str(arm_output), "--mode", mode,
                        *placement_args]
                    if tracer_study:
                        command = ["taskset", "--cpu-list", str(tracer_cpus[name]), *command]
                    process = subprocess.Popen(command,
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
                if placement_study or tracer_study:
                    if arm["exit_code"] != 0 or arm.get("observer_exit_code") != 0:
                        raise RuntimeError("SMT_arm_or_observer_failed; no next arm")
                    report = json.loads((arm_output / "report.json").read_text())
                    if report.get("network") != "PASS" or report.get("failures"):
                        raise RuntimeError("SMT_collection_incomplete; no next arm")
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
    measurement.add_argument("--placement", choices=("same_logical", "smt_sibling"))
    measurement.add_argument("--inherited-affinity", type=lambda raw: set(map(int, raw.split(","))))
    measurement.add_argument("--tracer-cpu", type=int)
    topology = commands.add_parser("smt-topology")
    topology.add_argument("--output", type=Path, required=True)
    topology.add_argument("--require-original-cpu", action="store_true")
    observation = commands.add_parser("observe")
    observation.add_argument("--source", type=Path, required=True)
    observation.add_argument("--output", type=Path, required=True)
    controlled = commands.add_parser("run")
    controlled.add_argument("--repository", type=Path, required=True)
    controlled.add_argument("--inputs", type=Path, required=True)
    controlled.add_argument("--output", type=Path, required=True)
    controlled.add_argument("--reverse", action="store_true")
    study = controlled.add_mutually_exclusive_group()
    study.add_argument("--observer-study", action="store_true")
    study.add_argument("--placement-study", action="store_true")
    study.add_argument("--tracer-study", action="store_true")
    args = parser.parse_args()
    if args.command == "sample":
        sample(args.pipe, args.output)
    elif args.command == "worker":
        worker(args.source.resolve(), args.artifacts.resolve(), args.output.resolve(), args.mode,
               args.placement, args.inherited_affinity, args.tracer_cpu)
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
            args.observer_study, args.placement_study, args.tracer_study)


if __name__ == "__main__":
    main()
