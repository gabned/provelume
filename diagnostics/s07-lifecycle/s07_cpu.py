"""Single S07 lifecycle-entry experiment on the original PRODUCT source."""

import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial, partialmethod
from pathlib import Path
from unittest.mock import patch

from s07_lifecycle_window import entry_purpose, observe, summarize

BASE = "19249382a1bb9bfbe5ce7d15d00e2ac70a21c3f2"
TREE = "e5c104cf0b753d4da5326eda691703506f37d83b"
MAIN = "2918c3968168e426986bd8fcd7d485f102c11f7b"
OWNER = "efc915815bd5a1dcad3246c135043b6111394f47"
BIND = "d046b9c9d4e77529dc17830df3a2eb23dcedc6e2"
BRANCH = "codex/s07-cpu-lifecycle-diagnostic-20261111"
PREPARATION = "619ffae7571b9bdaee21b7b80a6262c779bdbbe7"
LINT_CORRECTION = "5dc26bbdaa32d52c3730846ac5a98ee95639e2fb"
NETWORK_DIAGNOSTIC = "6e18c37d15bb1170f3dbe6a3176318d85cc92158"
TRACE_PREFIX_CORRECTION = "5202c4085ed8f6ae58be28996eecdc4c90810821"
WORKFLOW = ".github/workflows/s07-lifecycle-diagnostic.yml"
DIRECTORY = "diagnostics/s07-lifecycle"
CHANGED = {WORKFLOW, *(f"{DIRECTORY}/{name}" for name in (
    "README.md", "s07_cpu.py", "s07_lifecycle_window.py",
))}
TARGETS = [("deterministic", 1), ("s06", 1), ("s06", 2), ("s06", 5)]
CONTROL = [("control", n) for n in range(4)]
MARKERS = [9, 1, 2, 10]
KNOWN_STATES = {0, 1, 2, 4, 8, 16, 32, 64, 128, 256}
FIXED = (
    ".github/agent-protocol/pin.json", "core/provelume/instance_lifecycle.py",
    "core/provelume/capture_adapter.py", "core/provelume/ai_runtime_contract.py",
    "core/provelume/ai_runtime_limits.py", "core/provelume/ai_runtime_resources.py",
    "scripts/qualify_ai_runtime.py", "scripts/qualify_ai_jobs.py", "scripts/qualify_ai_setup.py",
    "scripts/qualify_ai_synthesis.py", "scripts/qualify_ai_classification.py",
    "scripts/ai_runtime_report.py", "scripts/ai_runtime_network.py",
    "scripts/ai_runtime_acquire.py",
    "pyproject.toml", "requirements-build.txt", "tests/fixtures/ai_runtime_quality.json",
    "tests/fixtures/ai_synthesis_quality.json",
)
WORKER_MODES = {"startup", "control", "native"}
TEMP = Path.cwd().parent if len(sys.argv) > 1 and sys.argv[1] in WORKER_MODES else Path(
    os.environ["RUNNER_TEMP"]
)
SOURCE = TEMP / "s07-original"
HELPERS = TEMP / "s07-reviewed-observer"
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve()


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, timeout=30,
    ).strip()


def source_proof():
    if (
        os.environ["GITHUB_REF"] != f"refs/heads/{BRANCH}"
        or os.environ["GITHUB_RUN_ATTEMPT"] != "1"
        or git(ROOT, "rev-parse", "HEAD") != os.environ["GITHUB_SHA"]
        or git(ROOT, "show", "-s", "--format=%P", "HEAD") != TRACE_PREFIX_CORRECTION
        or git(ROOT, "show", "-s", "--format=%P", TRACE_PREFIX_CORRECTION) != NETWORK_DIAGNOSTIC
        or git(ROOT, "show", "-s", "--format=%P", NETWORK_DIAGNOSTIC) != LINT_CORRECTION
        or git(ROOT, "show", "-s", "--format=%P", LINT_CORRECTION) != PREPARATION
        or git(ROOT, "show", "-s", "--format=%P", PREPARATION) != MAIN
        or git(ROOT, "rev-parse", "refs/remotes/origin/main") != MAIN
        or set(git(ROOT, "diff", "--name-only", MAIN, "HEAD").splitlines()) != CHANGED
        or git(SOURCE, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() != [BASE, TREE]
        or git(HELPERS, "rev-parse", "HEAD") != OWNER
        or git(ROOT, "rev-parse", "refs/remotes/origin/product/0.15-s07-cpu-recovery") != OWNER
        or git(HELPERS, "merge-base", BIND, OWNER) != BIND
        or any(git(root, "status", "--porcelain", "--untracked-files=all")
               for root in (ROOT, SOURCE, HELPERS))
    ):
        raise ValueError("exact isolated source, main or owner/BIND proof is missing")
    for path in FIXED:
        if len({git(ROOT, "rev-parse", f"{ref}:{path}") for ref in (BASE, MAIN, OWNER)}) != 1:
            raise ValueError(f"fixed input drift: {path}")
    return {"diagnostic": os.environ["GITHUB_SHA"], "baseline": BASE, "tree": TREE,
            "main": MAIN, "owner": OWNER, "bind": BIND}


def load_sources():
    sys.path[:0] = [str(SOURCE / "core"), str(HELPERS)]
    from scripts import concordia_kernel_native as native
    # The reused helper puts its own Core on sys.path. Retain only original PRODUCT.
    sys.path[:] = [str(SOURCE / "core"), str(SOURCE / "scripts"), *(
        p for p in sys.path if p not in (str(SOURCE / "core"), str(HELPERS / "core"))
    )]
    import scripts
    scripts.__path__ = [str(SOURCE / "scripts")]
    return native


def original_modules():
    import qualify_ai_jobs as jobs
    import qualify_ai_runtime as qualifier

    from provelume import capture_adapter, instance_lifecycle

    for module in (jobs, qualifier, capture_adapter, instance_lifecycle):
        if not Path(module.__file__).resolve().is_relative_to(SOURCE):
            raise ValueError("module loaded outside the original PRODUCT source")
    return jobs, qualifier, capture_adapter, instance_lifecycle


def clock():
    return time.monotonic_ns(), time.thread_time_ns()


def worker(native, mode, output, inputs=None):
    if (git(SOURCE, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() != [BASE, TREE]
            or git(SOURCE, "status", "--porcelain", "--untracked-files=all")):
        raise ValueError("worker source mismatch")
    jobs, qualifier, adapter, lifecycle = original_modules()
    host = native.host()
    if mode == "startup":
        native.kernel.write(output / "startup.json", {"host": host, "native_inference": "NOT_RUN"})
        return

    markers, frames = [], []
    fd = os.open(os.devnull, os.O_WRONLY)
    if fd != 198:
        os.dup2(fd, 198)
        os.close(fd)

    def emit(code):
        before = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        if os.write(198, b"x" * code) != code:
            raise ValueError("short observer marker")
        markers.append({"tid": threading.get_native_id(), "code": code, "before": before,
                        "after": time.clock_gettime_ns(time.CLOCK_BOOTTIME)})

    def wrap(original, group, selected):
        def probe(instance, number):
            if number not in selected:
                return original(instance, number)
            key = (group, number)
            if key in [tuple(row["key"]) for row in frames]:
                raise ValueError(f"duplicate frame: {key}")
            index, spans = adapter.refresh_search_index, []

            def refresh(*args, **kwargs):
                start = clock()
                try:
                    return index(*args, **kwargs)
                finally:
                    spans.append((start, clock()))

            emit(9)
            with patch.object(adapter, "refresh_search_index", refresh), observe(
                lifecycle, clock=clock
            ) as rows:
                emit(1)
                start = time.monotonic_ns()
                result = original(instance, number)
                end = time.monotonic_ns()
                emit(2)
            emit(10)
            if len(spans) != 1:
                raise ValueError("exactly one index refresh required")
            summary = summarize(rows, start, end, spans[0])
            frames.append({"key": key, "summary": summary, "probe": result.copy(),
                           "pre_yield": {row.purpose: (row.lock_acquired[0], row.ready[0])
                                         for row in rows}})
            return result

        return probe

    before = native.clock_pair()
    try:
        if mode == "control":
            from provelume import capture_journal
            from provelume.service import ProvelumeInstance

            probe = wrap(qualifier.deterministic_probe, "control", set(range(4)))
            recovery = capture_journal.recover_capture_transactions_locked
            acquire = adapter.CaptureAdapter._acquire_locked
            injections = {}

            def inject(number):
                start = time.monotonic_ns()
                time.sleep(0.12)
                injections[number] = (start, time.monotonic_ns())

            def recovery_control(number, *args, **kwargs):
                if number == 1 and entry_purpose() == "capture-acquire":
                    inject(number)
                return recovery(*args, **kwargs)

            def body_control(adapter_instance, number, *args, **kwargs):
                if number == 2:
                    inject(number)
                return acquire(adapter_instance, *args, **kwargs)

            for number in range(4):
                with (
                    tempfile.TemporaryDirectory(dir=output) as temp,
                    patch.object(capture_journal, "recover_capture_transactions_locked",
                                 partial(recovery_control, number)),
                    patch.object(adapter.CaptureAdapter, "_acquire_locked",
                                 partialmethod(body_control, number)),
                ):
                    probe(ProvelumeInstance.initialise(Path(temp) / "Synthetic Space"), number)
                if number in injections:
                    frames[-1]["injection"] = injections[number]
        else:
            # Patch the two actual call sites. Idle, S07 setup and S08 remain untouched.
            original_busy = qualifier.measure_busy_probe

            def busy(*args, **kwargs):
                replacement = wrap(qualifier.deterministic_probe, "deterministic", {1})
                with patch.object(qualifier, "deterministic_probe", replacement):
                    return original_busy(*args, **kwargs)

            with patch.object(qualifier, "measure_busy_probe", busy), patch.object(
                jobs, "deterministic_probe", wrap(jobs.deterministic_probe, "s06", {1, 2, 5})
            ):
                qualifier.measure(inputs, output / "report-before-network.json")
    finally:
        os.close(198)
        native.kernel.write(output / "frames.json", {
            "host": host, "tid": threading.get_native_id(), "pid": os.getpid(),
            "clock_before": before, "clock_after": native.clock_pair(),
            "frames": frames, "markers": markers,
        })


def kernel_binding(native, output, targets, host):
    data = json.loads((output / "frames.json").read_text())
    if (data["host"] != host or [tuple(row["key"]) for row in data["frames"]] != targets):
        raise ValueError("missing frame or worker placement drift")
    events = native.read_records(output)
    markers = [event for event in events if event[0] == "M"]
    tid = data["tid"]
    if ([event[3] for event in markers] != MARKERS * len(targets)
            or not any(event[0] == "X" and event[2] == data["pid"] for event in events)):
        raise ValueError("incomplete raw marker sequence or missing worker exit")
    for event, userspace in zip(markers, data["markers"], strict=True):
        if not (event[2] == tid == userspace["tid"] and event[3] == userspace["code"]
                and userspace["before"] <= event[1] <= userspace["after"]
                and userspace["after"] - userspace["before"] <= 5_000_000):
            raise ValueError("raw marker exceeds original clock/TID/cost bounds")
    pairs = [data["clock_before"], data["clock_after"]]
    low = max(pair["boot"] - pair["mono_after"] for pair in pairs)
    high = min(pair["boot"] - pair["mono_before"] for pair in pairs)
    if low > high:
        raise ValueError("monotonic/boot clocks do not reconcile")
    traces = list(output.glob("network.*"))
    native.inventory(events, traces)
    native.syscall_pairs(events, markers[0][1], markers[-1][1])
    for index, frame in enumerate(data["frames"]):
        begin, start, end, finish = [event[1] for event in markers[index * 4:index * 4 + 4]]
        scoped = [event for event in events if begin <= event[1] <= finish]
        typed = [event[3] for event in scoped if event[0] == "T" and event[2] == tid
                 and event[3] in (1, 2)]
        if not begin < start < end < finish or typed != [1, 2]:
            raise ValueError("independent typed write trace or exact frame boundary missing")
        intervals = [row for row in native.kernel.off_cpu_intervals(scoped) if row["tid"] == tid]
        if len(intervals) != sum(event[0] == "S" and event[2] == tid for event in scoped):
            raise ValueError("incomplete caller switch pairs")
        for purpose, (left, right) in frame["pre_yield"].items():
            if not start <= left + low <= right + high <= end:
                raise ValueError("lifecycle entry outside the original probe")
            row = frame["summary"]["by_purpose"][purpose]
            if row["pre_yield_thread_cpu_ns"] > row["pre_yield_wall_ns"]:
                raise ValueError("thread CPU exceeds the wall-clock interval")
            buckets = (("blocked", "start", "wake"), ("ready", "wake", "end"))
            for kind, start_key, end_key in buckets:
                total = 0
                for item in intervals:
                    if item["end"] <= left + low or item["start"] >= right + high:
                        continue
                    if item["wake"] is None or item["raw_state"] not in KNOWN_STATES:
                        raise ValueError("unattributed overlapping caller interval")
                    # Include only time inside the window for every reconciled offset.
                    total += max(0, min(right + low, item[end_key])
                                 - max(left + high, item[start_key]))
                row[f"certain_{kind}_ns"] = total
        if not all(frame["probe"][key] for key in (
            "preserved", "search_found", "product_dispatch_blocked"
        )):
            raise ValueError("original Capture semantics failed")
    return data["frames"]


def clean_network(path, prefix, stage):
    traces = sorted(path.glob(f"{prefix}.*"))
    calls, exits = {}, {}
    for trace in traces:
        content = trace.read_text()
        for line in content.splitlines():
            call = re.search(r"\b(socket|connect|sendto|sendmsg|sendmmsg)\(", line)
            if call:
                # Keep syscall, address family and result. Drop addresses and arguments.
                family = re.search(r"\bAF_[A-Z0-9_]+\b", line)
                errno = re.search(r"= -1 ([A-Z0-9_]+)\b", line)
                key = ":".join((
                    call[1], family[0] if family else "-", errno[1] if errno else "-",
                ))
                calls[key] = calls.get(key, 0) + 1
        ending = re.search(r"\+\+\+ (exited with \d+|killed by SIG[A-Z0-9]+) \+\+\+", content)
        key = ending[1] if ending else "no exit marker"
        exits[key] = exits.get(key, 0) + 1
    clean = bool(traces) and not calls and exits == {"exited with 0": len(traces)}
    print("S07_NETWORK_CONTROL=" + json.dumps({
        "stage": stage, "traces": len(traces), "calls": calls, "exits": exits, "pass": clean,
    }), flush=True)
    if not clean:
        raise ValueError(f"{stage}: model-free network/exit check failed")


def worker_args(mode, output, *extra):
    return [str(SCRIPT), mode, str(output), *map(str, extra)]


def admit(native, output):
    output.mkdir()
    source, host = source_proof(), native.host()
    started = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    if subprocess.check_output(["bpftrace", "--version"], text=True).strip() != "bpftrace v0.20.2":
        raise ValueError("unreviewed bpftrace version")
    formats = {}
    for name in native.FORMATS:
        data = subprocess.check_output(
            ["sudo", "-n", "cat", f"/sys/kernel/tracing/events/{name}/format"], timeout=5,
        )
        formats[name] = hashlib.sha256(data).hexdigest()
        fmt = data.split(b"print fmt: ", 1)[-1].strip()
        if name == "sched/sched_switch" and (
            hashlib.sha256(fmt).hexdigest() != native.STATE_PRINT_SHA256
        ):
            raise ValueError("unreviewed kernel scheduler state encoding")
    subprocess.run(
        ["strace", "-ff", "-tt", "-e", "trace=network", "-o", str(output / "startup-network"),
         sys.executable, *worker_args("startup", output)],
        check=True, timeout=45, cwd=SOURCE, env=native.child_environment(),
    )
    clean_network(output, "startup-network", "actual-worker-startup")
    if json.loads((output / "startup.json").read_text())["host"] != host:
        raise ValueError("actual worker startup placement differs")
    containment = native.containment_control(SOURCE, output)
    control = output / "control"
    try:
        if native.collect(SOURCE, control, worker_args("control", control), 45):
            raise ValueError("four-frame kernel control failed")
    except (OSError, ValueError, subprocess.SubprocessError):
        for path in (control / "kernel.stderr", control / "execution.log"):
            if path.is_file():
                print(f"S07_CONTROL_{path.name}=" + path.read_text()[-4096:], flush=True)
        raise
    clean_network(control, "network", "four-frame-capture-control")
    frames = kernel_binding(native, control, CONTROL, host)
    positive, negative = (frames[i]["summary"]["by_purpose"]["capture-acquire"] for i in (1, 2))
    pos_start, pos_end = frames[1]["injection"]
    neg_start, neg_end = frames[2]["injection"]
    pos_lock, pos_yield = frames[1]["pre_yield"]["capture-acquire"]
    _, neg_yield = frames[2]["pre_yield"]["capture-acquire"]
    if not (
        pos_lock <= pos_start <= pos_end <= pos_yield
        and pos_end - pos_start >= 120_000_000
        and neg_yield <= neg_start <= neg_end <= neg_yield + negative["body_wall_ns"]
        and neg_end - neg_start >= 120_000_000
        and positive["pre_yield_wall_ns"] >= 120_000_000
        and positive["certain_blocked_ns"] > 0
        and negative["pre_yield_wall_ns"] < 120_000_000
        and negative["body_wall_ns"] >= 120_000_000
    ):
        raise ValueError("known delay was not localized on both sides of the first yield")
    if source != source_proof() or host != native.host():
        raise ValueError("source or host changed during admission")
    receipt = {"status": "ADMITTED", "source": source, "host": host, "formats": formats,
               "containment": containment, "started_boot_ns": started}
    native.kernel.write(output / "admission.json", receipt)
    print("S07_ADMISSION=" + json.dumps({
        "status": "ADMITTED", "source": source, "qualification_eligible": False,
        "native_inference": "NOT_RUN", "controls": [frame["summary"] for frame in frames],
    }), flush=True)


def run(native, admission, inputs, output):
    receipt = json.loads((admission / "admission.json").read_text())
    pins = native.locked_inputs(inputs)
    if (receipt["status"] != "ADMITTED" or receipt["source"] != source_proof()
            or receipt["host"] != native.host()
            or not 0 <= time.clock_gettime_ns(time.CLOCK_BOOTTIME) - receipt["started_boot_ns"]
            <= 900 * 1_000_000_000):
        raise ValueError("fresh same-host admission missing")
    with tempfile.TemporaryDirectory(prefix="s07-replay-", dir=inputs.parent) as temporary:
        replay = Path(temporary)
        if len(replay.parts) != len(inputs.parts):
            raise ValueError("input-store depth changed")
        shutil.copytree(inputs / "linux", replay / "linux")
        shutil.copyfile(inputs / "model.gguf", replay / "model.gguf")
        if native.locked_inputs(replay) != pins:
            raise ValueError("locked replay input differs")
        if not 0 <= time.clock_gettime_ns(time.CLOCK_BOOTTIME) - receipt["started_boot_ns"] <= (
            900 * 1_000_000_000
        ):
            raise ValueError("admission expired during input staging")
        started = {"source": receipt["source"], "inputs": pins}
        native.kernel.write(admission / "started.json", started)
        print("S07_NATIVE=STARTED", flush=True)
        code = native.collect(SOURCE, output, worker_args("native", output, replay), 1200)
        if code or not (output / "report-before-network.json").is_file():
            raise ValueError("original sequence failed to return a report")
    report_path = output / "report.json"
    shutil.copyfile(output / "report-before-network.json", report_path)
    native.common.execute([
        sys.executable, str(SOURCE / "scripts/ai_runtime_network.py"),
        "--report", str(report_path), "--trace", str(output / "network"),
    ], SOURCE, output / "network-observer.log", 60)
    report = json.loads(report_path.read_text())
    print("S05_REAL_REPORT=" + json.dumps(report, ensure_ascii=True), flush=True)
    native.common.inspect_report(SOURCE, report_path, output / "stop-control.json")
    stop = json.loads((output / "stop-control.json").read_text())
    if (report.get("network") != "PASS" or not stop["non_capture_conjuncts_checked"]
            or any(group["search_seconds"]["exceedances"] for group in stop["capture"].values())):
        raise ValueError("original network/application/non-timing gate failed")
    frames = kernel_binding(native, output, TARGETS, receipt["host"])
    idle = report["deterministic_idle"]
    limit = min(1, 2 * statistics.median(row["capture_seconds"] for row in idle) + 0.1)
    busy = {
        "deterministic": report["deterministic_busy"],
        "s06": report["s06"]["deterministic_busy"],
    }
    for frame in frames:
        group, index = frame["key"]
        row = busy[group][index]
        matches_probe = all(row[key] == value for key, value in frame["probe"].items())
        if row["sample"] != index or not matches_probe:
            raise ValueError("selected probe differs from the original report")
        excess = (row["capture_seconds"] - limit) * 1e9
        duration = frame["summary"]["capture_pre_yield_wall_ns"]
        frame.update(limit_seconds=limit, excess_ns=excess, observation=(
            "NON_REPRODUCTION" if excess <= 0 else
            "CAPTURE_ENTRY_INSUFFICIENT_IN_THIS_SAMPLE" if duration < excess else
            "CAPTURE_ENTRY_COMPATIBLE_IN_THIS_SAMPLE"
        ))
    result = {"status": "COMPLETE_DIAGNOSTIC_ONLY", "historical_cause": "NOT_ESTABLISHED",
              "qualification_eligible": False, "original_status": report["status"],
              "original_gates": report["gates"], "frames": frames, "cost_deduction": "NONE"}
    native.kernel.write(output / "analysis.json", result)
    print("S07_RESULT=" + json.dumps(result, ensure_ascii=True), flush=True)


def main():
    mode, destination, *args = sys.argv[1:]
    output = Path(destination).resolve()
    native = load_sources()
    if mode in WORKER_MODES:
        worker(native, mode, output, *(Path(arg) for arg in args))
        return
    try:
        if mode == "admit":
            admit(native, output)
        elif mode == "run":
            run(native, output, *(Path(arg) for arg in args))
        else:
            raise ValueError("invalid stage")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        started = (output / "started.json").exists()
        state = "STOPPED / UNKNOWN" if started else "NOT_ADMITTED / NOT_RUN"
        print(f"S07_STATUS={state}: {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
