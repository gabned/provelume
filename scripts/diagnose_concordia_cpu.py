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
        row = {"operation": name, "before": accounting()}
        try:
            return original(*args, **kwargs)
        finally:
            row["after"] = accounting()
            context["operations"].append(row)
    return wrapped


def worker(source, artifacts, output):
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

    read_pipe, write_pipe = os.pipe()
    sampler = subprocess.Popen([sys.executable, str(SCRIPT), "sample", "--pipe", str(read_pipe),
                                "--output", str(output / "timeline.jsonl")],
                               pass_fds=(read_pipe,))
    os.close(read_pipe)
    raw_probe = ai_runtime_report.deterministic_probe
    sequence = 0

    def probe(instance, number):
        nonlocal sequence
        sequence += 1
        context = {"probe_id": sequence, "sample": number, "operations": [],
                   "caller": Path(sys._getframe(1).f_code.co_filename).name,
                   "before": accounting()}
        pids = [os.getpid(), os.getppid(), sampler.pid]
        pids += [r._process.pid for r in instances if r._process is not None]
        event = {"kind": "begin", "probe_id": sequence, "sample": number,
                 "caller": context["caller"], "pids": list(dict.fromkeys(pids)),
                 "roles": {"parent": os.getpid(), "tracer": os.getppid(),
                           "sampler": sampler.pid, "workers": pids[3:]},
                 "monotonic_ns": time.monotonic_ns(), "realtime_ns": time.time_ns()}
        os.write(write_pipe, (json.dumps(event) + "\n").encode())
        token = CURRENT.set(context)
        try:
            row = raw_probe(instance, number)
            row["diagnostic_timeline"] = context
            return row
        finally:
            context["after"] = accounting()
            CURRENT.reset(token)
            # Save even an exceptional probe, outside its original measured interval.
            with (output / "probe-accounting.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(context) + "\n")
            os.write(write_pipe, (json.dumps({"kind": "end", "probe_id": sequence,
                     "monotonic_ns": time.monotonic_ns()}) + "\n").encode())

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(LocalRuntime, "__init__", runtime_init))
            stack.enter_context(patch.object(ai_runtime_report, "deterministic_probe", probe))
            stack.enter_context(patch.object(qualify_ai_runtime, "deterministic_probe", probe))
            for target in (ai_runtime_report, qualify_ai_runtime):
                stack.enter_context(patch.object(target, "evaluate",
                                                  nonqualifying(target.evaluate)))
            for name in ("submit", "process"):
                stack.enter_context(patch.object(CaptureAdapter, name,
                    observe_operation(getattr(CaptureAdapter, name), name)))
            report = qualify_ai_runtime.measure(artifacts, output / "report-before-observer.json")
            report["diagnostic_driver_sha256"] = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
            write_json(output / "report-before-observer.json", report)
    finally:
        os.close(write_pipe)
        if sampler.wait(timeout=30) != 0:
            raise RuntimeError("sampler_failed")


def observe(source, output):
    """Original observer, in a fresh process AFTER strace and all tracees exit."""
    sys.path[:0] = [str(source / "scripts"), str(source / "core"), str(source)]
    from scripts import ai_runtime_network

    report = json.loads((output / "report-before-observer.json").read_text())
    with patch.object(ai_runtime_network, "evaluate", nonqualifying(ai_runtime_network.evaluate)):
        ai_runtime_network.observe(report, trace=output / "network")
    write_json(output / "report.json", report)


def run(repository, inputs, output, reverse=False):
    """Four fixed arms, once each, same runner/interpreter/path; no retry-to-green."""
    output.mkdir(parents=True, exist_ok=False)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository,
                                        text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repository):
        raise ValueError("controlled replay requires unchanged committed source")
    arms = [("main", MAIN), ("s06-original", S06), ("s08-original", S08),
            ("candidate", candidate)]
    if reverse:
        arms.reverse()
    manifest = {"status": "DIAGNOSTIC_ONLY", "qualification_eligible": False,
                "candidate": candidate,
                "driver_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                "arms": [], "python": sys.version, "clock_ticks": os.sysconf("SC_CLK_TCK"),
                "sched_schedstats": read_text(Path("/proc/sys/kernel/sched_schedstats")),
                "observer": "strace -ff -ttt -T -e trace=network,fsync,fdatasync",
                "sampling_seconds": 0.01, "order": [name for name, _ in arms],
                "limitations": ["instrumentation perturbs timing", "one runner is not a fleet",
                                "OS cache not flushed", "task exits can truncate task accounting",
                                "proc sampling does not prove individual syscall causality"]}
    write_json(output / "manifest.json", manifest)
    shutil.copyfile(SCRIPT, output / "driver.py")
    with (output / "dependencies.txt").open("w") as stream:
        subprocess.run([sys.executable, "-m", "pip", "freeze"], stdout=stream, check=True)
    with tempfile.TemporaryDirectory(prefix="concordia-cpu-") as scratch:
        source = Path(scratch) / "source"
        data = Path(scratch) / "data"
        for name, revision in arms:
            arm_output = output / name
            arm_output.mkdir()
            arm = {"name": name, "source": revision, "started_ns": time.time_ns()}
            manifest["arms"].append(arm)
            write_json(output / "manifest.json", manifest)
            subprocess.run(["git", "worktree", "add", "--detach", str(source), revision],
                           cwd=repository, check=True)
            try:
                # Identical locked acquisition, separate installed store and synthetic Instance.
                data.mkdir()
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
                        "trace=network,fsync,fdatasync", "-o", str(arm_output / "network"),
                        sys.executable, str(SCRIPT), "worker", "--source", str(source),
                        "--artifacts", str(data), "--output", str(arm_output)],
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
    observation = commands.add_parser("observe")
    observation.add_argument("--source", type=Path, required=True)
    observation.add_argument("--output", type=Path, required=True)
    controlled = commands.add_parser("run")
    controlled.add_argument("--repository", type=Path, required=True)
    controlled.add_argument("--inputs", type=Path, required=True)
    controlled.add_argument("--output", type=Path, required=True)
    controlled.add_argument("--reverse", action="store_true")
    args = parser.parse_args()
    if args.command == "sample":
        sample(args.pipe, args.output)
    elif args.command == "worker":
        worker(args.source.resolve(), args.artifacts.resolve(), args.output.resolve())
    elif args.command == "observe":
        observe(args.source.resolve(), args.output.resolve())
    else:
        run(args.repository.resolve(), args.inputs.resolve(), args.output.resolve(), args.reverse)


if __name__ == "__main__":
    main()
