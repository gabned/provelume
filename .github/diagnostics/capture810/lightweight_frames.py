"""Exercise four outside-the-probe markers and memory-only Capture phase stamps."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from capture_phase_probe import HEAD, MARKER_FD, TREE, run_control, source_identity
from quartet_contract import FRAME, SAMPLES, bind_quartet


def boot_ns():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def paired_clock():
    begin = time.monotonic_ns()
    boot = boot_ns()
    return boot - time.monotonic_ns(), boot - begin


@contextmanager
def capture_four_frames(synthesis, capture, atomic, emit):
    """Select exactly the official three idle probes and cold sample810."""
    base_probe = synthesis.deterministic_probe
    rows = []

    def observed(instance, sample):
        if sample not in SAMPLES:
            return base_probe(instance, sample)
        if len(rows) == len(SAMPLES) or sample != SAMPLES[len(rows)]:
            raise ValueError("Duplicate or displaced Capture sample")
        clock_before = paired_clock()
        start_bracket = emit(FRAME[0])
        try:
            result = run_control(instance, sample, None, False, base_probe, capture, atomic)
        finally:
            end_bracket = emit(FRAME[1])
        clock_after = paired_clock()
        offset = max(clock_before[0], clock_after[0]), min(clock_before[1], clock_after[1])
        if offset[0] > offset[1]:
            raise ValueError("Monotonic and boot clock conversion changed")
        phase_limit = (
            start_bracket[1],
            end_bracket[0],
        )
        if not all(
            phase_limit[0] <= mark["before_ns"] + offset[0] <= mark["after_ns"] + offset[1] <= phase_limit[1]
            for mark in result["markers"]
        ):
            raise ValueError("In-memory phase stamp not enclosed by raw frames")
        rows.append({
            "sample": sample, "outer_brackets": [start_bracket, end_bracket],
            "offset_ns": offset, "phase_stamps": result["markers"],
            "capture": result["probe"], "memory_marker_bracket_cost_ns": result["marker_bracket_total_ns"],
        })
        return result["probe"]

    synthesis.deterministic_probe = observed
    try:
        yield rows
        if tuple(row["sample"] for row in rows) != SAMPLES:
            raise ValueError("Complete idle and cold contrasts were not observed")
    finally:
        synthesis.deterministic_probe = base_probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    identity = source_identity(source)
    if output.exists() or output.is_relative_to(source):
        raise ValueError("Use a fresh path outside source")
    sys.path[:0] = [str(source / "scripts"), str(source / "core"), str(source)]
    from provelume import atomic_commit, capture_adapter
    from provelume.service import ProvelumeInstance
    from scripts import concordia_kernel_native, qualify_ai_synthesis

    for module in (atomic_commit, capture_adapter, qualify_ai_synthesis):
        if not Path(module.__file__).resolve().is_relative_to(source):
            raise ValueError("Wrong imported source worktree")
    if Path(qualify_ai_synthesis.deterministic_probe.__code__.co_filename).resolve() != (
        source / "scripts" / "ai_runtime_report.py"
    ):
        raise ValueError("Synthesis must consume the exact deterministic probe")
    denied = []

    def audit(event, _args):
        if event.startswith("socket.") and event != "socket.gethostname":
            denied.append(event)
            raise RuntimeError("Model-free control requested a socket")

    sys.addaudithook(audit)
    sentinel = os.open(os.devnull, os.O_WRONLY | os.O_CLOEXEC)
    if sentinel != MARKER_FD:
        os.dup2(sentinel, MARKER_FD, inheritable=False)
        os.close(sentinel)

    def emit(code):
        begin = boot_ns()
        if os.write(MARKER_FD, b"x" * code) != code:
            raise ValueError("Short marker write")
        return begin, boot_ns()

    base_probe = qualify_ai_synthesis.deterministic_probe
    try:
        with tempfile.TemporaryDirectory(prefix="four-frame-control-", dir=output.parent) as temporary:
            instance = ProvelumeInstance.initialise(Path(temporary) / "instance")
            with capture_four_frames(qualify_ai_synthesis, capture_adapter, atomic_commit, emit) as rows:
                observed = [qualify_ai_synthesis.deterministic_probe(instance, number) for number in SAMPLES]
    finally:
        os.close(MARKER_FD)
    if denied or qualify_ai_synthesis.deterministic_probe is not base_probe:
        raise ValueError("Audit or instrumentation cleanup failed")
    if [row["capture"] for row in rows] != observed:
        raise ValueError("Original probe response changed")
    # The actual raw tuples are collected by the independent kernel observer
    # on an eligible host. This control validates the user-space protocol.
    tid = threading.get_native_id()
    brackets = [pair for row in rows for pair in row["outer_brackets"]]
    synthetic_markers = [
        ("M", (left + right) // 2, tid, code)
        for (left, right), code in zip(brackets, FRAME * len(SAMPLES), strict=True)
    ]
    bound = bind_quartet(synthetic_markers, brackets, SAMPLES, tid)
    if tuple(bound) != SAMPLES:
        raise ValueError("Control authorization scope changed")
    with output.open("x", encoding="utf-8") as handle:
        json.dump({
            "head": HEAD, "tree": TREE, "source_check": identity,
            "status": "MODEL_FREE_USER_SPACE_FRAMES_VERIFIED",
            "raw_kernel_events": "NOT_RUN", "whole_probe_external_perturbation": "NOT_MEASURED",
            "native_inference": "NOT_RUN", "qualification_eligible": False,
            "socket_audit_attempts": 0, "outer_markers": 8, "controls": rows,
            "tid": tid, "uid": os.getuid(), "gid": os.getgid(), "groups": sorted(os.getgroups()),
            "nice": os.getpriority(os.PRIO_PROCESS, 0), "affinity": sorted(os.sched_getaffinity(0)),
            "process_limits": concordia_kernel_native.process_limits(),
        }, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
