"""One real AI-Off Capture probe with exact method markers; never qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from functools import wraps
from pathlib import Path

BASE = "d5b2cc9f06c14be8c51a082d309dbde0358552e8"


def clock_pair():
    before = time.monotonic_ns()
    boot = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    return {"mono_before": before, "boot": boot, "mono_after": time.monotonic_ns()}


def marked(original, begin, finish, emit):
    @wraps(original)
    def call(*args, **kwargs):
        emit(begin)
        try:
            return original(*args, **kwargs)
        finally:
            emit(finish)
    return call


def validate_binding(records, fixture):
    markers = [r for r in records if r[0] == "M"]
    if len(markers) != 6 or [r[3] for r in markers] != [9, 1, 2, 3, 4, 10]:
        raise ValueError("exact submit/process markers absent or out of order")
    for row, expected in zip(markers, fixture["markers"], strict=True):
        if (row[2] != fixture["tid"] or row[3] != expected["code"]
                or not expected["before"] <= row[1] <= expected["after"]):
            raise ValueError("Capture marker identity/clock mismatch")
    offsets = [(c["boot"] - c["mono_after"], c["boot"] - c["mono_before"])
               for c in (fixture["clock_before"], fixture["clock_after"])]
    if max(low for low, _ in offsets) > min(high for _, high in offsets):
        raise ValueError("Capture clock conversion changed")
    if not any(r[0] == "X" and r[2] == fixture["pid"] for r in records):
        raise ValueError("Capture fixture exit missing")
    if not all(fixture["probe"][k] for k in (
            "preserved", "search_found", "product_dispatch_blocked")):
        raise ValueError("original Capture semantic check failed")
    if max(r["after"] - r["before"] for r in fixture["markers"]) > 5_000_000:
        raise ValueError("Capture marker exceeds original 5ms control bound")
    return {"status": "CAPTURE_WINDOW_BINDING_OBSERVED", "qualification_eligible": False,
            "source": fixture["source"], "native_inference": "NOT_RUN",
            "frame": [markers[0], markers[-1]],
            "submit_window": markers[1:3], "process_window": markers[3:5],
            "probe": fixture["probe"], "marker_costs_ns": [
                r["after"] - r["before"] for r in fixture["markers"]]}


def run(source, output):
    def git(*args):
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={source}", "-C", str(source), *args]
        ).decode().strip()
    if git("rev-parse", "HEAD") != BASE or git("status", "--porcelain"):
        raise ValueError("exact clean retained baseline required")
    sys.path[:0] = [str(source / "scripts"), str(source / "core"), str(source)]
    from ai_runtime_report import deterministic_probe

    from provelume.capture_adapter import CaptureAdapter
    from provelume.service import ProvelumeInstance

    output = output.resolve()
    markers = []
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 198)
    os.close(null)

    def emit(code):
        before = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        os.write(198, b"x" * code)
        markers.append({"tid": threading.get_native_id(), "code": code,
                        "before": before, "after": time.clock_gettime_ns(time.CLOCK_BOOTTIME)})

    submit, process = CaptureAdapter.submit, CaptureAdapter.process
    CaptureAdapter.submit = marked(submit, 1, 2, emit)
    CaptureAdapter.process = marked(process, 3, 4, emit)
    before = clock_pair()
    try:
        with tempfile.TemporaryDirectory(prefix="capture-binding-", dir=output.parent) as path:
            instance = ProvelumeInstance.initialise(Path(path) / "instance")
            emit(9)
            probe = deterministic_probe(instance, 810)
            emit(10)
    finally:
        CaptureAdapter.submit, CaptureAdapter.process = submit, process
        os.close(198)
    result = {"source": BASE, "pid": os.getpid(), "tid": threading.get_native_id(),
              "uid": os.getuid(), "clock_before": before, "clock_after": clock_pair(),
              "markers": markers, "probe": probe, "qualification_eligible": False,
              "native_inference": "NOT_RUN", "probe_source_sha256": hashlib.sha256(
                  (source / "scripts/ai_runtime_report.py").read_bytes()).hexdigest()}
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.output)


if __name__ == "__main__":
    main()
