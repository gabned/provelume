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
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

MAIN = "096782e32a3d019c3e160c2569507d55cadfd274"
S06 = "8b3f467aa9e7c059e23f22644786ef0f87582cc3"
S08 = "e2c9244df692cdd9dbd636a0109a7d920a21ac1b"
SCRIPT = Path(__file__).resolve()
CURRENT = contextvars.ContextVar("concordia_probe", default=None)


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

    def __init__(self, roles):
        self.entries = []
        self.inventory = []
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
        return {"started_ns": started, "finished_ns": time.monotonic_ns(),
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


def worker(source, artifacts, output, mode="legacy"):
    sys.path[:0] = [str(source / "scripts"), str(source / "core"), str(source)]
    import ai_runtime_report
    import qualify_ai_runtime

    from provelume.ai_runtime import LocalRuntime
    from provelume.capture_adapter import CaptureAdapter

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
        pids = [pid for values in roles.values() for pid in values]
        event = {"kind": "begin", "probe_id": sequence, "sample": number,
                 "caller": context["caller"], "pids": list(dict.fromkeys(pids)),
                 "roles": {"parent": os.getpid(), "tracer": os.getppid(),
                           "sampler": sampler.pid if sampler else None,
                           "workers": roles["workers"]},
                 "monotonic_ns": time.monotonic_ns(), "realtime_ns": time.time_ns()}
        if write_pipe is not None:
            os.write(write_pipe, (json.dumps(event) + "\n").encode())
        boundary = BoundaryCounters(roles) if mode != "legacy" else None
        if boundary is not None:
            context.update(_boundary=boundary, boundary_inventory=boundary.inventory,
                           roles=roles, durability=[], observation_mode=mode)
        active = context
        token = CURRENT.set(context)
        try:
            row = raw_probe(instance, number)
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


def run(repository, inputs, output, reverse=False, observer_study=False):
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
    manifest = {"status": "DIAGNOSTIC_ONLY", "qualification_eligible": False,
                "candidate": candidate,
                "driver_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                "arms": [], "python": sys.version, "clock_ticks": os.sysconf("SC_CLK_TCK"),
                "sched_schedstats": read_text(Path("/proc/sys/kernel/sched_schedstats")),
                "observer": "strace -ff -ttt -T; syscall set recorded per arm",
                "sampling_seconds": 0.01, "order": [name for name, _, _ in arms],
                "experiment": "observer-study" if observer_study else "source-comparison",
                "limitations": ["instrumentation perturbs timing", "one runner is not a fleet",
                                "OS cache not flushed", "task exits can truncate task accounting",
                                "proc sampling does not prove individual syscall causality"]}
    write_json(output / "manifest.json", manifest)
    shutil.copyfile(SCRIPT, output / "driver.py")
    if observer_study:
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
                    process = subprocess.Popen(["strace", "-ff", "-ttt", "-T", "-e",
                        "trace=" + arm["trace"], "-o", str(arm_output / "network"),
                        sys.executable, str(SCRIPT), "worker", "--source", str(source),
                        "--artifacts", str(data), "--output", str(arm_output), "--mode", mode],
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
    observation = commands.add_parser("observe")
    observation.add_argument("--source", type=Path, required=True)
    observation.add_argument("--output", type=Path, required=True)
    controlled = commands.add_parser("run")
    controlled.add_argument("--repository", type=Path, required=True)
    controlled.add_argument("--inputs", type=Path, required=True)
    controlled.add_argument("--output", type=Path, required=True)
    controlled.add_argument("--reverse", action="store_true")
    controlled.add_argument("--observer-study", action="store_true")
    args = parser.parse_args()
    if args.command == "sample":
        sample(args.pipe, args.output)
    elif args.command == "worker":
        worker(args.source.resolve(), args.artifacts.resolve(), args.output.resolve(), args.mode)
    elif args.command == "observe":
        observe(args.source.resolve(), args.output.resolve())
    else:
        run(args.repository.resolve(), args.inputs.resolve(), args.output.resolve(), args.reverse,
            args.observer_study)


if __name__ == "__main__":
    main()
