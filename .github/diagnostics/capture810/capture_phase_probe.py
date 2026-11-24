"""Label application phases of one real AI-Off synthetic Capture per control.

The original probe measures Capture unchanged. The independent phase stamps
remain separate. This driver never acquires an AI input or scores a release gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from functools import wraps
from pathlib import Path
from unittest.mock import patch


HEAD = "5f177ac68c1777843f5a97f1292b0848728ef974"
TREE = "258ef309a75b0ec18c071d2d69d68cc37b890c88"
MARKER_FD = 198
MINIMUM_HISTORIC_EXCESS_NS = 612_790
WAIT_NS = 12_000_000
CONTROLS = (
    ("unperturbed", None),
    ("canonical_pipe_wait", "canonical_commit"),
    ("projection_pipe_wait", "search_projection"),
)
PHASES = (
    ("submit", 11, 12),
    ("process", 21, 22),
    ("journal_read", 31, 32),
    ("canonical_commit", 41, 42),
    ("review_routing", 51, 52),
    ("search_projection", 61, 62),
)
EXPECTED_SEQUENCE = (11, 12, 21, 31, 32, 41, 42, 51, 52, 61, 62, 22)
SOURCE_FILES = (
    "scripts/ai_runtime_report.py",
    "core/provelume/capture_adapter.py",
    "core/provelume/capture_journal.py",
    "core/provelume/atomic_commit.py",
    "core/provelume/index.py",
)


def git(source, *args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(source), *args], text=True
    ).rstrip("\n")


def source_identity(source):
    if git(source, "rev-parse", "HEAD") != HEAD or git(source, "rev-parse", "HEAD^{tree}") != TREE:
        raise ValueError("Incorrect source head or tree")
    if git(source, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Source checkout is dirty")
    checked = {}
    for relative in SOURCE_FILES:
        payload = (source / relative).read_bytes()
        if payload != subprocess.check_output(
            ["git", "--no-replace-objects", "-C", str(source), "show", f"HEAD:{relative}"]
        ):
            raise ValueError("Source bytes differ from exact Git object")
        checked[relative] = {
            "git_blob": git(source, "rev-parse", f"HEAD:{relative}"),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    return checked


def wait_on_owned_pipe():
    """Independently record a deliberate blocking interval in a known hook."""
    reader, writer = os.pipe()
    started = threading.Event()

    def signal():
        if started.wait(0.2):
            time.sleep(WAIT_NS / 1e9)
            os.write(writer, b"x")

    worker = threading.Thread(target=signal, daemon=True)
    begin = time.monotonic_ns()
    cpu_before = time.thread_time_ns()
    try:
        worker.start()
        started.set()
        # select bounds the synthetic pipe independently of the external watchdog.
        from select import select

        if not select([reader], [], [], 0.4)[0] or os.read(reader, 1) != b"x":
            raise RuntimeError("Synthetic release did not arrive")
    finally:
        worker.join(0.5)
        os.close(reader)
        os.close(writer)
        if worker.is_alive():
            raise RuntimeError("Synthetic release thread survived")
    return {
        "before_ns": begin,
        "after_ns": time.monotonic_ns(),
        "thread_cpu_ns": time.thread_time_ns() - cpu_before,
    }


def run_control(instance, sample, selected, emit, probe, capture, atomic):
    marker_rows = []
    injection = None
    tid = threading.get_native_id()

    def mark(label, code):
        if threading.get_native_id() != tid:
            raise RuntimeError("Capture markers crossed threads")
        before = time.monotonic_ns()
        cpu = time.thread_time_ns()
        if emit:
            os.write(MARKER_FD, b"." * code)
        after = time.monotonic_ns()
        marker_rows.append({
            "phase": label, "code": code, "tid": tid,
            "before_ns": before, "after_ns": after, "thread_cpu_ns": cpu,
        })

    def scoped(original, label, start, end):
        @wraps(original)
        def call(*args, **kwargs):
            nonlocal injection
            if label == "canonical_commit" and args[0].profile != capture.PROFILE:
                return original(*args, **kwargs)
            mark(label, start)
            try:
                if label == selected:
                    if injection is not None:
                        raise RuntimeError("Unexpected duplicate synthetic delay")
                    injection = {**wait_on_owned_pipe(), "phase": label}
                return original(*args, **kwargs)
            finally:
                mark(label, end)
        return call

    adapter = capture.CaptureAdapter
    wraps_to = (
        (adapter, "submit"),
        (adapter, "process"),
        (adapter, "_submission_locked"),
        (atomic.AtomicInstanceCommit, "commit"),
        (capture, "route_committed_acquisitions_locked"),
        (capture, "refresh_search_index"),
    )
    with ExitStack() as stack:
        for (owner, name), (label, start, end) in zip(wraps_to, PHASES, strict=True):
            stack.enter_context(patch.object(owner, name, scoped(getattr(owner, name), label, start, end)))
        measured = probe(instance, sample)
    observed = tuple(row["code"] for row in marker_rows)
    if observed != EXPECTED_SEQUENCE:
        raise RuntimeError(f"Capture phase model mismatch in sample {sample}: {observed}")
    if not all(measured[key] is True for key in ("preserved", "search_found", "product_dispatch_blocked")):
        raise RuntimeError("Original Capture result rejected")
    by_code = {row["code"]: row for row in marker_rows}
    windows = {}
    for label, start, end in PHASES:
        first, last = by_code[start], by_code[end]
        wall = last["before_ns"] - first["after_ns"]
        cpu = last["thread_cpu_ns"] - first["thread_cpu_ns"]
        if min(wall, cpu) < 0:
            raise RuntimeError("Inverted clocks")
        windows[label] = {
            "first_code": start, "last_code": end,
            "wall_ns": wall, "calling_thread_cpu_ns": cpu,
            "before_ns": first["after_ns"], "after_ns": last["before_ns"],
        }
    process = windows["process"]
    inside = [windows[label] for label, *_ in PHASES[2:]]
    if not all(process["before_ns"] <= row["before_ns"] <= row["after_ns"] <= process["after_ns"] for row in inside):
        raise RuntimeError("Marker windows escape ordinary process call")
    if not all(left["after_ns"] <= right["before_ns"] for left, right in zip(inside, inside[1:])):
        raise RuntimeError("Nested application labels overlapped")
    matches = []
    if injection is not None:
        matches = [
            label for label, *_ in PHASES[2:]
            if windows[label]["before_ns"] <= injection["before_ns"] <= injection["after_ns"] <= windows[label]["after_ns"]
        ]
        if matches != [selected] or injection["after_ns"] - injection["before_ns"] < WAIT_NS:
            raise RuntimeError("Synthetic interval was not labeled correctly")
    elif selected is not None:
        raise RuntimeError("Synthetic delay did not run")
    return {
        "probe": measured, "windows": windows, "markers": marker_rows,
        "independent_pipe_interval": injection, "specific_owner": matches,
        "process_wall_remainder_ns": process["wall_ns"] - sum(row["wall_ns"] for row in inside),
        "marker_bracket_total_ns": sum(r["after_ns"] - r["before_ns"] for r in marker_rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--emit-fd-markers", action="store_true")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    identity = source_identity(source)
    if output.exists() or output.is_relative_to(source):
        raise ValueError("Use a fresh private destination outside the source checkout")
    sys.path[:0] = [str(source / "core"), str(source)]
    from provelume import atomic_commit, capture_adapter
    from provelume.service import ProvelumeInstance
    from scripts import ai_runtime_report

    for module in (atomic_commit, capture_adapter, ai_runtime_report):
        if not Path(module.__file__).resolve().is_relative_to(source):
            raise ValueError("Wrong imported source root")

    socket_audits = []

    def audit(event, _args):
        if event.startswith("socket.") and event != "socket.gethostname":
            socket_audits.append(event)
            raise RuntimeError("Socket operation refused in model-free Capture fixture")

    sys.addaudithook(audit)
    fd = None
    if args.emit_fd_markers:
        fd = os.open(os.devnull, os.O_WRONLY | os.O_CLOEXEC)
        if fd != MARKER_FD:
            os.dup2(fd, MARKER_FD, inheritable=False)
            os.close(fd)
    rows = {}
    try:
        with tempfile.TemporaryDirectory(prefix="synthetic-capture-", dir=output.parent) as scratch:
            for name, label in CONTROLS:
                instance = ProvelumeInstance.initialise(Path(scratch) / name / "instance")
                probes = [
                    run_control(
                        instance, sample, label if sample == 810 else None, args.emit_fd_markers,
                        ai_runtime_report.deterministic_probe, capture_adapter, atomic_commit,
                    )
                    for sample in (800, 801, 802, 810)
                ]
                baseline = statistics.median(r["probe"]["capture_seconds"] for r in probes[:3])
                current = probes[-1]["probe"]["capture_seconds"]
                rows[name] = {
                    "samples": probes, "idle_median_seconds": baseline,
                    "formula_control_limit_seconds": min(1, 2 * baseline + 0.1),
                    "test_sample_wall_seconds": current,
                    "marker_bracket_total_ns": sum(item["marker_bracket_total_ns"] for item in probes),
                }
    finally:
        if fd is not None:
            os.close(MARKER_FD)
    if socket_audits:
        raise RuntimeError("Unexpected socket audit events")
    report = {
        "source": HEAD, "tree": TREE, "checked_files": identity,
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixture_type": "AI_OFF_MODEL_FREE_REAL_CAPTURE",
        "native_inference": "NOT_RUN", "qualification_eligible": False,
        "socket_audit_attempts": len(socket_audits), "pid": os.getpid(),
        "tid": threading.get_native_id(), "fd_markers": args.emit_fd_markers,
        "minimum_historic_excess_ns": MINIMUM_HISTORIC_EXCESS_NS,
        "marker_clock_less_than_minimum_excess": all(
            row["marker_bracket_total_ns"] < MINIMUM_HISTORIC_EXCESS_NS for row in rows.values()
        ),
        "controls": rows,
    }
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
