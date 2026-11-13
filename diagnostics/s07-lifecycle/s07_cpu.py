"""One S07 comparison of staging writer waits on the original failure source."""

import ctypes
import errno
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
from functools import partial
from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

from s07_flush_window import bind_waits
from s07_prepare_window import PURPOSES, observe, summarize

BASE = "a713f0141799fea60b7caa1a0e62826f3b373bf9"
TREE = "8ae742fd7499f63cf7f70722166ef344c0cabda9"
MAIN = "2918c3968168e426986bd8fcd7d485f102c11f7b"
OWNER = "efc915815bd5a1dcad3246c135043b6111394f47"
BIND = "d046b9c9d4e77529dc17830df3a2eb23dcedc6e2"
BRANCH = "codex/s07-cpu-lifecycle-diagnostic-20261111"
PREVIOUS = "b06a16b2cf2925b43f8add6a1d3d315fe82f0827"
HISTORICAL_S06_CPU = "AMD EPYC 9V45 96-Core Processor"
COMPARISON_CPUS = {
    HISTORICAL_S06_CPU,
    "AMD EPYC 9V74 80-Core Processor",
    "AMD EPYC 7763 64-Core Processor",
}
WORKFLOW = ".github/workflows/s07-lifecycle-diagnostic.yml"
DIRECTORY = "diagnostics/s07-lifecycle"
CHANGED = {WORKFLOW, *(f"{DIRECTORY}/{name}" for name in (
    "README.md", "s07_cpu.py", "s07_lifecycle_window.py", "s07_lifecycle_events.bt",
    "s07_inventory_window.py", "s07_manifest_window.py", "s07_assure_window.py",
    "s07_cleanup_window.py", "s07_pool_window.py", "s07_publish_window.py",
    "s07_flush_window.py", "s07_target_window.py", "s07_add_window.py",
    "s07_prepare_window.py",
))}
# Three idle captures precede deterministic slot 1. All three deterministic
# busy captures precede the governed S06 slots.
MATCHED_SLOTS = {("deterministic", 1): 4, ("s06", 1): 7, ("s06", 2): 8, ("s06", 5): 11}
TARGETS = list(MATCHED_SLOTS)
CONTROL = [("control", n) for n in range(4)] + [
    ("matched-idle", n) for n in MATCHED_SLOTS.values()
]
WINDOW_OPEN = 3
WINDOW_CLOSE = 4
MARKERS = [9, 1, *([WINDOW_OPEN, WINDOW_CLOSE] * len(PURPOSES)), 2, 10]
KNOWN_STATES = {0, 1, 2, 4, 8, 16, 32, 64, 128, 256}
FIXED = (
    ".github/agent-protocol/pin.json", "core/provelume/instance_lifecycle.py",
    "core/provelume/capture_adapter.py", "core/provelume/atomic_commit.py",
    "core/provelume/ai_runtime_contract.py",
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
PROGRAM = SCRIPT.with_name("s07_lifecycle_events.bt")


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, timeout=30,
    ).strip()


def source_proof():
    if (
        os.environ["GITHUB_REF"] != f"refs/heads/{BRANCH}"
        or os.environ["GITHUB_RUN_ATTEMPT"] != "1"
        or git(ROOT, "rev-parse", "HEAD") != os.environ["GITHUB_SHA"]
        or git(ROOT, "show", "-s", "--format=%P", "HEAD") != PREVIOUS
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
    journal = "core/provelume/capture_journal.py"
    if git(ROOT, "rev-parse", f"{BASE}:{journal}") != git(ROOT, "rev-parse", f"{MAIN}:{journal}"):
        raise ValueError("historical Capture journal differs from main")
    return {"diagnostic": os.environ["GITHUB_SHA"], "baseline": BASE, "tree": TREE,
            "main": MAIN, "owner": OWNER, "bind": BIND,
            "kernel_program_sha256": hashlib.sha256(PROGRAM.read_bytes()).hexdigest()}


def load_sources():
    sys.path[:0] = [str(SOURCE / "core"), str(HELPERS)]
    from scripts import concordia_kernel_native as native
    # The reused helper puts its own Core on sys.path. Retain only original PRODUCT.
    sys.path[:] = [str(SOURCE / "core"), str(SOURCE / "scripts"), *(
        p for p in sys.path if p not in (str(SOURCE / "core"), str(HELPERS / "core"))
    )]
    import scripts
    scripts.__path__ = [str(SOURCE / "scripts")]
    native.kernel.PROGRAM = PROGRAM
    return native


def original_modules():
    import qualify_ai_jobs as jobs
    import qualify_ai_runtime as qualifier

    from provelume import atomic_commit, capture_adapter

    for module in (jobs, qualifier, atomic_commit, capture_adapter):
        if not Path(module.__file__).resolve().is_relative_to(SOURCE):
            raise ValueError("module loaded outside the original PRODUCT source")
    return jobs, qualifier, atomic_commit, capture_adapter


def clock():
    return time.monotonic_ns(), time.thread_time_ns()


def exercise_syscalls(fixture):
    """Prove futex and fsync capture inside a synthetic post-lock window."""
    # The pinned observer is Linux x86-64. FUTEX_WAIT_PRIVATE on a mismatched
    # word returns EAGAIN without sleeping or involving another thread.
    syscall = ctypes.CDLL(None, use_errno=True).syscall
    syscall.restype = ctypes.c_long
    word = ctypes.c_int(0)
    if syscall(202, ctypes.byref(word), 128, 1, None, None, 0) != -1 or (
        ctypes.get_errno() != errno.EAGAIN
    ):
        raise ValueError("synthetic futex did not return EAGAIN")
    fixture.write(b"s07 fsync control\n")
    fixture.flush()
    os.fsync(fixture.fileno())


def worker(native, mode, output, inputs=None):
    if (git(SOURCE, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() != [BASE, TREE]
            or git(SOURCE, "status", "--porcelain", "--untracked-files=all")):
        raise ValueError("worker source mismatch")
    jobs, qualifier, atomic, adapter = original_modules()
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

    def wrap(original, group, selected, *, writer_control=None):
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
                atomic, adapter, clock=clock, control=writer_control,
                begin_entry=partial(emit, WINDOW_OPEN), end_entry=partial(emit, WINDOW_CLOSE),
            ) as rows:
                emit(1)
                start = time.monotonic_ns()
                result = original(instance, number)
                end = time.monotonic_ns()
                emit(2)
            emit(10)
            if len(spans) != 1:
                raise ValueError("exactly one index refresh required")
            if len(instance.store.paths.root.parts) != len(TEMP.parts) + 2:
                raise ValueError("Capture root differs from the matched probe depth")
            windows, writes, summary = summarize(rows, start, end, spans[0])
            frames.append({"key": key, "summary": summary, "probe": result.copy(),
                           "windows": windows, "writes": writes,
                           "probe_interval": (start, end)})
            return result

        return probe

    before = native.clock_pair()
    try:
        if mode == "control":
            from provelume.service import ProvelumeInstance

            injections = {}

            def writer_hook(number, fixture, purpose, phase):
                if (number, phase) in ((1, "inside"), (2, "after")):
                    start = time.monotonic_ns()
                    time.sleep(0.12)
                    injections.setdefault(number, {})[purpose] = (start, time.monotonic_ns())
                elif number == 3 and purpose == PURPOSES[0] and phase == "inside":
                    exercise_syscalls(fixture)

            for number in range(4):
                with (
                    tempfile.TemporaryDirectory(prefix="s07-control-", dir=TEMP) as temp,
                    tempfile.TemporaryFile(dir=output) as syscall_fixture,
                ):
                    probe = wrap(
                        qualifier.deterministic_probe, "control", {number},
                        writer_control=partial(writer_hook, number, syscall_fixture),
                    )
                    probe(ProvelumeInstance.initialise(Path(temp) / "synthetic-instance"), number)
                if number in injections:
                    frames[-1]["injection"] = injections[number]
            # The full qualifier grows the journal with three idle and three
            # deterministic-busy captures before S06. On this same runner,
            # build an independent model-free instance with that many receipts.
            with tempfile.TemporaryDirectory(prefix="s07-replay-", dir=TEMP) as temp:
                instance = ProvelumeInstance.initialise(Path(temp) / "synthetic-instance")
                selected = set(MATCHED_SLOTS.values())
                probe = wrap(qualifier.deterministic_probe, "matched-idle", selected)
                for number in range(max(selected) + 1):
                    result = probe(instance, number)
                    if not all(result[key] for key in (
                        "preserved", "search_found", "product_dispatch_blocked"
                    )):
                        raise ValueError("model-free journal priming changed Capture semantics")
        else:
            # Wrap the deterministic busy entry point so all original idle
            # measurements and every nonselected probe stay uninstrumented.
            measure_busy = qualifier.measure_busy_probe
            base_probe = qualifier.deterministic_probe

            def observed_busy(instance, runtime, thread, number, **kwargs):
                if number != 1:
                    return measure_busy(instance, runtime, thread, number, **kwargs)
                with patch.object(
                    qualifier, "deterministic_probe", wrap(base_probe, "deterministic", {1}),
                ):
                    return measure_busy(instance, runtime, thread, number, **kwargs)

            with (
                patch.object(qualifier, "measure_busy_probe", observed_busy),
                patch.object(
                    jobs, "deterministic_probe", wrap(
                        jobs.deterministic_probe, "s06",
                        {number for group, number in TARGETS if group == "s06"},
                    ),
                ),
            ):
                qualifier.measure(inputs, output / "report-before-network.json")
    finally:
        os.close(198)
        native.kernel.write(output / "frames.json", {
            "host": host, "tid": threading.get_native_id(), "pid": os.getpid(),
            "clock_before": before, "clock_after": native.clock_pair(),
            "frames": frames, "markers": markers,
        })


def bound_markers(events, data, targets):
    raw = [event for event in events if event[0] == "M"]
    completed = [event for event in events if event[0] == "T"]
    expected = MARKERS * len(targets)
    entries, exits = [row[3] for row in raw], [row[3] for row in completed]
    worker_exited = any(row[0] == "X" and row[2] == data["pid"] for row in events)
    print("S07_MARKER_CONTROL=" + json.dumps({
        "expected": len(expected), "entries": len(entries), "exits": len(exits),
        "entry_order": entries == expected, "exit_order": exits == expected,
        "worker_exited": worker_exited,
    }), flush=True)
    if entries != expected or exits != expected or not worker_exited:
        raise ValueError("incomplete marker entry/completion sequence or missing worker exit")
    for raw_row, exit_row, user in zip(raw, completed, data["markers"], strict=True):
        if raw_row[1] > exit_row[1]:
            raise ValueError("write completion precedes marker entry")
        if any(
            row[2] != data["tid"] or row[2] != user["tid"] or row[3] != user["code"]
            or not user["before"] <= row[1] <= user["after"]
            or user["after"] - user["before"] > 5_000_000
            for row in (raw_row, exit_row)
        ):
            raise ValueError("marker exceeds original clock/TID/cost bounds")
    return raw


def account_window(native, events, tid, row, left, right, calls, offset):
    intervals = [
        item for item in native.kernel.off_cpu_intervals(events) if item["tid"] == tid
    ]
    switch_outs = sum(event[0] == "S" and event[2] == tid for event in events)
    if len(intervals) != switch_outs:
        raise ValueError("incomplete caller switch pairs")
    if row["thread_cpu_ns"] > row["wall_ns"]:
        raise ValueError("thread CPU exceeds the wall-clock interval")
    for item in intervals:
        if item["end"] <= left or item["start"] >= right:
            continue
        if item["wake"] is None or item["raw_state"] not in KNOWN_STATES:
            raise ValueError("unattributed overlapping caller interval")

    low, high = offset
    totals = {"blocked": 0, "ready": 0}
    for call_start, call_end, _ in calls:
        certain_start, certain_end = call_start[0] + high, call_end[0] + low
        for item in intervals:
            wake = item["wake"]
            if wake is None:
                continue
            totals["blocked"] += max(
                0, min(certain_end, wake) - max(certain_start, item["start"]),
            )
            totals["ready"] += max(
                0, min(certain_end, item["end"]) - max(certain_start, wake),
            )
    for kind, total in totals.items():
        row[f"certain_{kind}_ns"] = total
    return intervals


def validate_syscall_pairs(events):
    pending = set()
    for kind, _, tid, *payload in events:
        if kind not in {"U", "D"}:
            continue
        key = (kind, tid)
        if payload == [1] and key not in pending:
            pending.add(key)
        elif payload == [0] and key in pending:
            pending.remove(key)
        else:
            raise ValueError("incomplete syscall pairing")
    if pending:
        raise ValueError("incomplete syscall pairing")


def kernel_binding(native, output, targets, host):
    data = json.loads((output / "frames.json").read_text())
    if (data["host"] != host or [tuple(row["key"]) for row in data["frames"]] != targets):
        raise ValueError("missing frame or worker placement drift")
    stdout, stderr = output / "kernel.stdout", output / "kernel.stderr"
    print("S07_KERNEL_STREAM=" + json.dumps({
        "stage": output.name, "stdout_bytes": stdout.stat().st_size,
        "stderr_bytes": stderr.stat().st_size, "limit_bytes": native.kernel.MAX_BYTES,
    }), flush=True)
    if stderr.stat().st_size:
        with stderr.open("rb") as stream:
            print("S07_KERNEL_STDERR=" + stream.read(4096).decode(errors="replace"), flush=True)
    events = native.read_records(output)
    raw = bound_markers(events, data, targets)
    tid = data["tid"]
    pairs = [data["clock_before"], data["clock_after"]]
    low = max(pair["boot"] - pair["mono_after"] for pair in pairs)
    high = min(pair["boot"] - pair["mono_before"] for pair in pairs)
    if low > high:
        raise ValueError("monotonic/boot clocks do not reconcile")
    native.inventory(events, list(output.glob("network.*")))
    if targets == CONTROL:
        native.syscall_pairs(events, raw[0][1], raw[-1][1])
    else:
        # A native caller may make no futex calls. Validate every observed pair.
        validate_syscall_pairs(events)

    windows = []
    for index, frame in enumerate(data["frames"]):
        first = index * len(MARKERS)
        stamps = [event[1] for event in raw[first:first + len(MARKERS)]]
        if any(before >= after for before, after in pairwise(stamps)):
            raise ValueError("kernel windows are not strictly ordered within the probe")
        start, end = stamps[1], stamps[-2]
        for slot, purpose in enumerate(PURPOSES):
            opened, closed = stamps[2 + slot * 2:4 + slot * 2]
            left, right = frame["windows"][purpose]
            if not (
                start <= opened <= left + low <= left + high <= right + low
                <= right + high <= closed <= end
            ):
                raise ValueError("kernel markers do not bind the staging writer window")
            windows.append((opened, closed))
            scoped = [event for event in events if opened <= event[1] <= closed]
            row = frame["summary"]["by_purpose"][purpose]
            intervals = account_window(
                native, scoped, tid, row, left + high, right + low,
                [((left, 0), (right, 0), None)], (low, high),
            )
            writes = frame["writes"][purpose]
            row["future_results"] = bind_waits(scoped, writes, intervals, (low, high))
            if targets == CONTROL and index == 3 and purpose == PURPOSES[0]:
                pairs = native.syscall_pairs(
                    [event for event in scoped if event[0] in ("U", "D") and event[2] == tid],
                    opened, closed,
                )
                print("S07_SYSCALL_CONTROL=" + json.dumps(pairs, sort_keys=True), flush=True)
        if not all(frame["probe"][key] for key in (
            "preserved", "search_found", "product_dispatch_blocked"
        )):
            raise ValueError("original Capture semantics failed")
    for kind, stamp, *_ in events:
        if kind in ("S", "W") and not any(left <= stamp <= right for left, right in windows):
            raise ValueError("scheduler event outside the staging writer windows")
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
    observed = {"cpu": host["cpu_model"], "logical_cpus": host["logical_cpus"]}
    print("S07_PREPARE_HOST=" + json.dumps(observed), flush=True)
    if host["cpu_model"] not in COMPARISON_CPUS or host["logical_cpus"] != 4:
        raise ValueError("runner is not an admitted EPYC 7763, 9V74 or 9V45 with four logical CPUs")
    started = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    if subprocess.check_output(["bpftrace", "--version"], text=True).strip() != "bpftrace v0.20.2":
        raise ValueError("unreviewed bpftrace version")
    formats = {}
    for name in (*native.FORMATS, "raw_syscalls/sys_exit"):
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
            raise ValueError("Capture staging writer kernel controls failed")
    except (OSError, ValueError, subprocess.SubprocessError):
        for path in (control / "kernel.stderr", control / "execution.log"):
            if path.is_file():
                print(f"S07_CONTROL_{path.name}=" + path.read_text()[-4096:], flush=True)
        raise
    clean_network(control, "network", "four-frame-capture-control")
    frames = kernel_binding(native, control, CONTROL, host)
    for purpose in PURPOSES:
        positive = frames[1]["summary"]["by_purpose"][purpose]
        negative = frames[2]["summary"]["by_purpose"][purpose]
        pos_start, pos_end = frames[1]["injection"][purpose]
        neg_start, neg_end = frames[2]["injection"][purpose]
        (wait_left, _), (wait_right, _) = frames[1]["writes"][purpose][0]["wait"]
        _, neg_right = frames[2]["windows"][purpose]
        if not (
            wait_left <= pos_start <= pos_end <= wait_right
            and pos_end - pos_start >= 120_000_000
            and neg_right <= neg_start <= neg_end <= frames[2]["probe_interval"][1]
            and neg_end - neg_start >= 120_000_000
            and positive["wait_wall_ns"] >= 120_000_000
            and positive["future_results"]["certain_blocked_ns"] > 0
            and negative["wall_ns"] < 120_000_000
        ):
            raise ValueError(f"known delay was not localized at the {purpose} writer wait")
    if source != source_proof() or host != native.host():
        raise ValueError("source or host changed during admission")
    matched_idle = {str(frame["key"][1]): frame for frame in frames if (
        frame["key"][0] == "matched-idle"
    )}
    receipt = {"status": "ADMITTED", "source": source, "host": host, "formats": formats,
               "containment": containment, "started_boot_ns": started,
               "matched_idle": matched_idle}
    native.kernel.write(output / "admission.json", receipt)
    print("S07_ADMISSION=" + json.dumps({
        "status": "ADMITTED", "source": source, "qualification_eligible": False,
        "native_inference": "NOT_RUN", "controls": [frame["summary"] for frame in frames],
    }), flush=True)


def compare_writers(frame, control, slot):
    comparison = {}
    for purpose in PURPOSES:
        busy = frame["summary"]["by_purpose"][purpose]
        idle = control["summary"]["by_purpose"][purpose]
        if [kind for kind, _ in busy["staged_sizes"]] != [
            kind for kind, _ in idle["staged_sizes"]
        ]:
            raise ValueError(f"{purpose} staging write counts differ from the matched control")
        metrics = (
            "wall_ns", "thread_cpu_ns", "wait_wall_ns", "wait_cpu_ns",
            "certain_blocked_ns", "certain_ready_ns",
        )
        comparison[purpose] = {metric: busy[metric] - idle[metric] for metric in metrics}
    return {
        "control_slot": slot,
        "control_capture_seconds": control["probe"]["capture_seconds"],
        "control_summary": control["summary"],
        "busy_minus_control_ns": comparison,
    }


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
    busy = {"deterministic": report["deterministic_busy"],
            "s06": report["s06"]["deterministic_busy"]}
    for frame in frames:
        group, index = frame["key"]
        row = busy[group][index]
        matches_probe = all(row[key] == value for key, value in frame["probe"].items())
        if row["sample"] != index or not matches_probe:
            raise ValueError("selected probe differs from the original report")
        excess = (row["capture_seconds"] - limit) * 1e9
        durations = {purpose: frame["summary"]["by_purpose"][purpose]["wall_ns"]
                     for purpose in PURPOSES}
        slot = MATCHED_SLOTS[(group, index)]
        control = receipt["matched_idle"][str(slot)]
        frame["matched_idle"] = compare_writers(frame, control, slot)
        frame.update(limit_seconds=limit, excess_ns=excess, observation=(
            "NON_REPRODUCTION" if excess <= 0 else
            "PREPARE_WRITERS_INSUFFICIENT_IN_THIS_SAMPLE" if sum(durations.values()) < excess else
            "PREPARE_WRITERS_COMPATIBLE_IN_THIS_SAMPLE"
        ))
    result = {"status": "COMPLETE_DIAGNOSTIC_ONLY", "historical_cause": "NOT_ESTABLISHED",
              "factor": "Capture staging writers in _prepare, submit and process",
              "comparison": "SAME_RUNNER_MODEL_FREE_MATCHED_STAGING_WRITE_COUNTS",
              "cpu_model": receipt["host"]["cpu_model"],
              "historical_cpu_model_matched": receipt["host"]["cpu_model"] == HISTORICAL_S06_CPU,
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
