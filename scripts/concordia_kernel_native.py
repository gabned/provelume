"""One original d5 sequence, kernel chronology only at S08 cold sample810."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
sys.path[:0] = [str(ROOT), str(ROOT / "core")]
from scripts import compare_concordia_journal as common  # noqa: E402
from scripts import concordia_kernel_observer as kernel  # noqa: E402
from scripts.compare_capture_path_guard import MAIN, environment  # noqa: E402
from scripts.concordia_capture_marker_fixture import (  # noqa: E402
    BASE,
    clock_pair,
    marked,
    validate_binding,
)

FORMATS = ("sched/sched_process_fork", "sched/sched_switch", "sched/sched_wakeup",
           "sched/sched_process_exit", "syscalls/sys_enter_write", "raw_syscalls/sys_enter",
           "syscalls/sys_enter_futex", "syscalls/sys_exit_futex",
           "syscalls/sys_enter_fsync", "syscalls/sys_exit_fsync")
FIXED = ("scripts/qualify_ai_runtime.py", "scripts/qualify_ai_jobs.py",
         "scripts/qualify_ai_setup.py", "scripts/qualify_ai_synthesis.py",
         "scripts/qualify_ai_classification.py", "scripts/ai_runtime_report.py",
         "scripts/ai_runtime_network.py", "scripts/ai_runtime_acquire.py",
         "pyproject.toml", "requirements-build.txt", "tests/fixtures/ai_runtime_quality.json",
         "tests/fixtures/ai_synthesis_quality.json")
STATE_PRINT_SHA256 = "571bb297a3c1a15b3be57a44f7353794af7d05f18a53d6ba6567ce1f410f1c9e"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sources():
    proof = kernel.source_proof()
    def git(*args):
        return common.git(ROOT, *args).decode().strip()
    if git("rev-parse", "refs/remotes/origin/main") != MAIN:
        raise ValueError("accepted main drift")
    if git("rev-parse", BASE + ":core") != git("rev-parse", MAIN + ":core"):
        raise ValueError("retained baseline PRODUCT drift")
    fixed = {}
    for path in FIXED:
        if git("rev-parse", "HEAD:" + path) != git("rev-parse", BASE + ":" + path):
            raise ValueError("original qualification input changed: " + path)
        fixed[path] = digest(ROOT / path)
    return {"owner": proof, "baseline": BASE, "tree": git("rev-parse", BASE + "^{tree}"),
            "fixed": fixed, "driver_sha256": digest(SCRIPT),
            "program_sha256": digest(kernel.PROGRAM)}


def process_limits():
    import resource

    limits = {name: list(resource.getrlimit(getattr(resource, "RLIMIT_" + name.upper())))
              for name in ("as", "core", "cpu", "data", "fsize", "memlock", "msgqueue",
                           "nice", "nofile", "nproc", "rss", "rtprio", "rttime",
                           "sigpending", "stack")}
    # Linux exposes RLIMIT_LOCKS in procfs but CPython does not export its constant.
    locks = re.search(r"^Max file locks\s+(\S+)\s+(\S+)",
                      Path("/proc/self/limits").read_text(), re.MULTILINE)
    if locks is None:
        raise ValueError("complete original process limits unavailable")
    limits["locks"] = [-1 if v == "unlimited" else int(v) for v in locks.groups()]
    return limits


def limit_command(limits):
    return ["prlimit", *["--" + name + "=" + ":".join(
        "unlimited" if value == -1 else str(value) for value in pair)
        for name, pair in limits.items()], "--"]


def host():
    if sys.platform != "linux":
        raise ValueError("kernel native admission requires Linux")
    if os.geteuid() == 0 or any(shutil.which(name) is None for name in
                               ("bpftrace", "strace", "setpriv", "prlimit")):
        raise ValueError("native controller must retain ordinary runner identity")
    result = environment()
    result.update(uid=os.getuid(), gid=os.getgid(), home=os.environ["HOME"],
                  nice=os.getpriority(os.PRIO_PROCESS, 0),
                  groups=sorted(os.getgroups()),
                  limits=process_limits(),
                  boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                  tools={name: digest(Path(shutil.which(name)))
                         for name in ("bpftrace", "strace", "setpriv", "prlimit")})
    return result


def child_environment():
    # HOME is a benign original runner coordinate. Removing it makes Python's
    # home lookup issue NSS sockets before the original qualifier even starts.
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1",
            "HOME": os.environ["HOME"]}


def locked_inputs(inputs):
    from provelume.ai_runtime_contract import MODEL_SHA256, MODEL_SIZE, runtime_lock
    expected = {"model.gguf": {"size": MODEL_SIZE, "sha256": MODEL_SHA256},
                **{"linux/" + name: pin
                   for name, pin in runtime_lock()["platforms"]["linux"].items()}}
    for name, pin in expected.items():
        path = inputs / name
        if (any(p.is_symlink() for p in (path, *path.parents))
                or path.stat().st_size != pin["size"] or digest(path) != pin["sha256"]):
            raise ValueError("locked native input differs: " + name)
    return expected


@contextmanager
def baseline():
    with tempfile.TemporaryDirectory(prefix="kernel-native-source-") as scratch:
        source = Path(scratch) / "source"
        common.git(ROOT, "worktree", "add", "--detach", str(source), BASE)
        try:
            yield source
        finally:
            common.git(ROOT, "worktree", "remove", str(source))


def collect(source, output, arguments, timeout):
    """Only BPF is privileged; the unchanged strace/application run as the runner."""
    output.mkdir(parents=True, exist_ok=False)
    header = output / "capture-window.h"
    header.write_text("#define CAPTURE_BINDING 1\n")
    trace = output / "network"
    command = ["env", "-i", *[name + "=" + value for name, value in child_environment().items()],
               "strace", "-ff", "-tt", "-e", "trace=network", "-o", str(trace),
               sys.executable, *arguments]
    launch = output / "launch.sh"
    launch.write_text("#!/bin/sh\n" + shlex.join(command) + " > "
                      + shlex.quote(str(output / "execution.log")) + " 2>&1\n"
                      + "concordia_exit=$?\nprintf '%s\\n' \"$concordia_exit\" > "
                      + shlex.quote(str(output / "exit-code")) + "\nexit \"$concordia_exit\"\n")
    # bpftrace may raise its own memlock limit. Restore the original complete
    # envelope before dropping privilege; setpriv itself does not reset rlimits.
    limits = host()["limits"]
    child = [*limit_command(limits), "setpriv", "--reuid", str(os.getuid()),
        "--regid", str(os.getgid()), "--groups", ",".join(map(str, os.getgroups())),
        "--", "/bin/sh", str(launch)]
    command = ["sudo", "-n", "env", "-i", "PATH=/usr/bin:/bin", "LANG=C.UTF-8",
               "bpftrace", "--include", str(header), "-q", "-B", "line", "-k",
               "-c", shlex.join(child), str(kernel.PROGRAM)]
    started = time.monotonic_ns()
    with (output / "kernel.stdout").open("x") as out, (output / "kernel.stderr").open("x") as err:
        process = subprocess.Popen(command, cwd=source, stdout=out, stderr=err,
                                   start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except BaseException:
            # The process group includes the privileged observer and its tracees.
            subprocess.run(["sudo", "-n", "kill", "-KILL", "--", "-" + str(process.pid)],
                           check=True, timeout=10, capture_output=True)
            process.wait(timeout=10)
            raise
    kernel.write(output / "observer-execution.json", {
        "observer_exit": code, "whole_execution_wall_ns": time.monotonic_ns() - started,
        "application_uid": os.getuid(), "original_strace": command,
        "cost_deduction": "NONE"})
    if code or not (output / "exit-code").is_file():
        raise ValueError("kernel observer exit or missing child exit")
    return int((output / "exit-code").read_text())


def inventory(records, traces):
    children = [r[3] for r in records if r[0] == "F"]
    parents = {r[2] for r in records if r[0] == "F"}
    roots = parents - set(children)
    exits = [r[2] for r in records if r[0] == "X"]
    if (len(roots) != 1 or len(children) != len(set(children))
            or len(exits) != len(set(exits)) or set(exits) != set(children) | roots):
        raise ValueError("incomplete owned task fork/exit inventory")
    tids = {int(p.suffix[1:]) for p in traces}
    if not tids or not tids <= set(exits):
        raise ValueError("traced task missing kernel exit")
    if any(not re.search(r"\+\+\+ (exited with|killed by)", p.read_text()) for p in traces):
        raise ValueError("original strace exit incomplete")
    return {"owned_tasks": len(exits), "traced_tasks": len(tids), "root": roots.pop()}


def syscall_pairs(records, start, end):
    pending, pairs = set(), {"U": 0, "D": 0}
    for row in records:
        if row[0] not in pairs:
            continue
        key = (row[0], row[2])
        if row[3] == 1 and key not in pending:
            pending.add(key)
        elif row[3] == 0 and key in pending:
            pending.remove(key)
            pairs[row[0]] += 1
        else:
            raise ValueError("incomplete window syscall pairing")
    if pending or not all(pairs.values()):
        raise ValueError("incomplete window syscall pairing")
    return pairs


def read_records(output):
    return kernel.parse_events((output / "kernel.stdout").read_text(),
                               (output / "kernel.stderr").read_text())


def containment_control(source, output):
    """Exercise the baseline's actual pre-import containment without a model."""
    program = (
        "import sys,json,os,socket;sys.path.insert(0," + repr(str(source / "core")) + ");"
        "from provelume.ai_runtime_limits import contain;_,limits=contain();"
        "denied=[]\n"
        "for operation in (socket.socket,os.fork):\n"
        " try: operation()\n"
        " except PermissionError: denied.append(True)\n"
        "print(json.dumps({'limits':limits,'denied':denied,'uid':os.getuid(),"
        "'affinity':sorted(os.sched_getaffinity(0))}))\n"
    )
    trace = output / "containment-network"
    result = subprocess.run(["strace", "-ff", "-tt", "-e", "trace=network",
        "-o", str(trace), sys.executable, "-c", program], cwd=source,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"},
        capture_output=True, text=True, timeout=20)
    (output / "containment.stdout").write_text(result.stdout)
    (output / "containment.stderr").write_text(result.stderr)
    if result.returncode or result.stderr.strip():
        raise ValueError("baseline containment control failed")
    observed = json.loads(result.stdout)
    traces = list(output.glob("containment-network.*"))
    if (observed["denied"] != [True, True] or observed["uid"] != os.getuid()
            or len(observed["affinity"]) != 2
            or observed["limits"]["network_control"] != "seccomp:socket-syscalls-EPERM"
            or not traces or not any("= -1 EPERM" in p.read_text() for p in traces)):
        raise ValueError("baseline containment/observer semantics missing")
    return observed


def startup_control(source, output):
    trace = output / "startup-network"
    result = subprocess.run(["strace", "-ff", "-tt", "-e", "trace=network",
        "-o", str(trace), sys.executable, str(SCRIPT), "worker", "--source", str(source),
        "--output", str(output), "--startup-only"], cwd=source, env=child_environment(),
        capture_output=True, text=True, timeout=45)
    (output / "startup.stdout").write_text(result.stdout)
    (output / "startup.stderr").write_text(result.stderr)
    traces = list(output.glob("startup-network.*"))
    if (result.returncode or result.stderr.strip() or not traces
            or any(re.search(r"\b(socket|connect|sendto|sendmsg|sendmmsg)\(", p.read_text())
                   for p in traces)
            or any("+++ exited with 0 +++" not in p.read_text() for p in traces)):
        raise ValueError("actual native-driver startup network/exit control failed")
    observed = json.loads((output / "startup.json").read_text())
    if observed["host"] != host() or observed["native_inference"] != "NOT_RUN":
        raise ValueError("startup identity/placement differs from original runner")
    return {"status": "STARTUP_OBSERVED_NO_NETWORK_CALLS", "traces": len(traces),
            "native_inference": "NOT_RUN"}


def admit(output):
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "concordia-kernel-native-admission/v1", "status": "NOT_ADMITTED",
               "native_inference": "NOT_RUN", "qualification_eligible": False}
    try:
        receipt.update(source=sources(), host=host())
        receipt["admitted_boot_ns"] = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        version = subprocess.check_output(["bpftrace", "--version"]).decode().strip()
        if version != "bpftrace v0.20.2":
            raise ValueError("unreviewed observer version")
        receipt["bpftrace"] = version
        receipt["strace"] = subprocess.check_output(["strace", "--version"]).decode()
        receipt["formats"] = {}
        for name in FORMATS:
            data = subprocess.check_output(["sudo", "-n", "cat",
                "/sys/kernel/tracing/events/" + name + "/format"], timeout=5)
            (output / (name.replace("/", "-") + ".txt")).write_bytes(data)
            receipt["formats"][name] = hashlib.sha256(data).hexdigest()
        switch = (output / "sched-sched_switch.txt").read_text()
        state_print = switch.split("print fmt: ", 1)[-1].strip().encode()
        if hashlib.sha256(state_print).hexdigest() != STATE_PRINT_SHA256:
            raise ValueError("unknown actual kernel scheduler state encoding")
        # A fresh-host prerequisite, not another fixed four-arm or CPU experiment.
        with baseline() as source:
            receipt["startup"] = startup_control(source, output)
            receipt["containment"] = containment_control(source, output)
            control = output / "capture-binding"
            fixture_path = control / "fixture.json"
            args = [str(SCRIPT.with_name("concordia_capture_marker_fixture.py")),
                    "--source", str(source), "--output", str(fixture_path)]
            if collect(source, control, args, 45):
                raise ValueError("fresh-host Capture binding failed")
            records = read_records(control)
            fixture = json.loads(fixture_path.read_text())
            binding = validate_binding(records, fixture)
            binding["inventory"] = inventory(records, list(control.glob("network.*")))
            binding["syscall_pairs"] = syscall_pairs(
                records, binding["frame"][0][1], binding["frame"][1][1])
            kernel.off_cpu_intervals(records)
            kernel.write(control / "binding.json", binding)
            receipt["binding"] = binding
        if host() != receipt["host"] or sources() != receipt["source"]:
            raise ValueError("source/host drift during fresh admission")
        receipt["status"] = "ADMITTED"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        receipt["error"] = {"type": type(exc).__name__, "detail": str(exc)}
    finally:
        kernel.write(output / "admission.json", receipt)
    print(json.dumps({k: receipt[k] for k in ("status", "native_inference")}))
    return 0 if receipt["status"] == "ADMITTED" else 1


@contextmanager
def capture_marks(adapter, synthesis, emit):
    selected = []
    active = False
    submit, process = adapter.submit, adapter.process
    probe = synthesis.deterministic_probe

    def scoped(method, begin, finish):
        wrapped = marked(method, begin, finish, emit)
        def call(*args, **kwargs):
            return wrapped(*args, **kwargs) if active else method(*args, **kwargs)
        return call

    def observed(instance, number):
        nonlocal active
        if number != 810:
            return probe(instance, number)
        if selected:
            raise ValueError("sample810 repeated; no second frame")
        selected.append(number)
        active = True
        emit(9)
        try:
            return probe(instance, number)
        finally:
            emit(10)
            active = False

    adapter.submit = scoped(submit, 1, 2)
    adapter.process = scoped(process, 3, 4)
    synthesis.deterministic_probe = observed
    try:
        yield selected
    finally:
        adapter.submit, adapter.process = submit, process
        synthesis.deterministic_probe = probe


def worker(source, inputs, output, *, startup_only=False):
    if (common.git(source, "rev-parse", "HEAD").decode().strip() != BASE
            or common.git(source, "status", "--porcelain").strip()):
        raise ValueError("exact clean baseline required")
    sys.path[:0] = [str(source / "scripts"), str(source / "core"), str(source)]
    import scripts
    scripts.__path__ = [str(source / "scripts")]
    import qualify_ai_runtime as original
    import qualify_ai_synthesis as synthesis

    from provelume.capture_adapter import CaptureAdapter

    for module in (original, synthesis, sys.modules[CaptureAdapter.__module__]):
        if not Path(module.__file__).resolve().is_relative_to(source):
            raise ValueError("application module did not load from immutable baseline")
    if startup_only:
        kernel.write(output / "startup.json", {"source": BASE, "host": host(),
                     "native_inference": "NOT_RUN", "pid": os.getpid()})
        return 0
    markers, selected = [], []
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 198)
    os.close(null)

    def emit(code):
        before = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        os.write(198, b"x" * code)
        markers.append({"tid": threading.get_native_id(), "code": code, "before": before,
                        "after": time.clock_gettime_ns(time.CLOCK_BOOTTIME)})

    before = clock_pair()
    coordinates = host()
    try:
        with capture_marks(CaptureAdapter, synthesis, emit) as selected:
            report = original.measure(inputs, output / "report-before-observer.json")
    finally:
        os.close(198)
        kernel.write(output / "markers.json", {"source": BASE, "pid": os.getpid(),
            "tid": threading.get_native_id(), "host": coordinates, "selected": selected,
            "clock_before": before, "clock_after": clock_pair(), "markers": markers})
    return 0 if report["status"] == "PASS" else 1


def analyze(output):
    records = read_records(output)
    report = json.loads((output / "report.json").read_text())
    fixture = json.loads((output / "markers.json").read_text())
    performance = report["s08"]["performance"]
    if (len(performance) != 2 or performance[0]["phase"] != "cold"
            or performance[0]["probe"]["sample"] != 810 or fixture["selected"] != [810]):
        raise ValueError("original cold sample810 binding missing")
    probe = performance[0]["probe"]
    fixture["probe"] = probe
    binding = validate_binding(records, fixture)
    binding["native_inference"] = "OBSERVED_IN_ORIGINAL_REPORT"
    tasks = inventory(records, list(output.glob("network.*")))
    syscall = syscall_pairs(records, binding["frame"][0][1], binding["frame"][1][1])
    intervals = kernel.off_cpu_intervals(records)
    start, end = (r[1] for r in binding["process_window"])
    selected = [r for r in intervals if r["tid"] == fixture["tid"]
                and start <= r["start"] and r["end"] <= end]
    caller_switches = [r for r in records if r[0] == "S" and start <= r[1] <= end
                       and r[2] == fixture["tid"]]
    complete = (len(selected) == len(caller_switches)
                and all(r["wake"] is not None and r["raw_state"] in
                        {0, 1, 2, 4, 8, 16, 32, 64, 128, 256} for r in selected))
    idle = report["s08"]["idle"]
    limit = min(1, 2 * statistics.median(r["capture_seconds"] for r in idle) + .1)
    prediction = kernel.evaluate_prediction(intervals, tid=fixture["tid"], start=start, end=end,
        capture_seconds=probe["capture_seconds"], own_limit=limit, complete=complete)
    if not complete:
        prediction["prediction"] = "UNKNOWN"
    return {"schema": "concordia-kernel-native-result/v1", "qualification_eligible": False,
            "original_status": report["status"], "original_gates": report["gates"],
            "probe": probe, "own_limit": limit, "binding": binding, "tasks": tasks,
            "syscall_pairs": syscall, "caller_process_intervals": selected,
            "chronology_complete": complete, "prediction": prediction,
            "physical_io_causality": "NOT_ESTABLISHED", "findings": "CURRENT / NOT_DEMONSTRATED"}


def run(inputs, admission_path, output):
    admission = json.loads(admission_path.read_text())
    if (admission.get("status") != "ADMITTED" or admission["source"] != sources()
            or admission["host"] != host()
            or not 0 <= time.clock_gettime_ns(time.CLOCK_BOOTTIME)
            - admission["admitted_boot_ns"] <= 900 * 1_000_000_000):
        raise ValueError("missing fresh source/host admission")
    pins = locked_inputs(inputs)
    kernel.write(admission_path.with_suffix(".started.json"),
                 {"output": str(output), "source": sources(), "inputs": pins})
    manifest = {"schema": "concordia-kernel-native-sequence/v1", "status": "RUNNING",
                "qualification_eligible": False, "admission": admission, "inputs": pins,
                "native_inference": "STARTED", "sequence_count": 1}
    try:
        with baseline() as source, tempfile.TemporaryDirectory(
                prefix="replay-", dir=inputs.parent) as temporary:
            data = Path(temporary)
            if len(data.parts) != len(inputs.parts):
                raise ValueError("unequal acquired/replay input-store path depth")
            shutil.copytree(inputs / "linux", data / "linux")
            shutil.copyfile(inputs / "model.gguf", data / "model.gguf")
            locked_inputs(data)
            code = collect(source, output, [str(SCRIPT), "worker", "--source", str(source),
                "--inputs", str(data), "--output", str(output)], 1200)
            manifest["execution_exit"] = code
            if code not in {0, 1} or not (output / "report-before-observer.json").is_file():
                raise ValueError("abnormal application exit or incomplete report")
            shutil.copyfile(output / "report-before-observer.json", output / "report.json")
            manifest["network_exit"] = common.execute([sys.executable,
                str(source / "scripts/ai_runtime_network.py"), "--report",
                str(output / "report.json"), "--trace", str(output / "network")], source,
                output / "network-observer.log", 60)
            report = json.loads((output / "report.json").read_text())
            manifest.update(original_status=report["status"], original_gates=report["gates"])
            common.inspect_report(source, output / "report.json", output / "stop-control.json")
            stop = json.loads((output / "stop-control.json").read_text())
            if (report.get("network") != "PASS" or report.get("failures")
                    or not stop["non_capture_conjuncts_checked"]):
                raise ValueError("original non-timing/application/network failure")
            result = analyze(output)
            if json.loads((output / "markers.json").read_text())["host"] != admission["host"]:
                raise ValueError("native child identity/placement differs from admitted host")
            kernel.write(output / "analysis.json", result)
            manifest.update(status="COMPLETE_DIAGNOSTIC_ONLY", native_inference="COMPLETE",
                            prediction=result["prediction"])
    except Exception as exc:
        manifest.update(status="STOPPED", prediction={"prediction": "UNKNOWN"},
                        error={"type": type(exc).__name__, "detail": str(exc)})
    finally:
        output.mkdir(parents=True, exist_ok=True)
        kernel.write(output / "manifest.json", manifest)
    print(json.dumps({k: manifest[k] for k in ("status", "prediction")}))
    return 0 if manifest["status"] == "COMPLETE_DIAGNOSTIC_ONLY" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("admit", "run", "worker", "analyze"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--startup-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.command == "admit":
        return admit(output)
    if args.command == "analyze":
        print(json.dumps(analyze(output)))
        return 0
    if args.command == "worker":
        return worker(args.source.resolve(), args.inputs.resolve() if args.inputs else None,
                      output, startup_only=args.startup_only)
    return run(args.inputs.resolve(), args.admission.resolve(), output)


if __name__ == "__main__":
    raise SystemExit(main())
