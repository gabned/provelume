"""Run one bounded model-free four-Capture calibration on ephemeral Actions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from capture_phase_probe import HEAD, TREE, git, source_identity
from quartet_contract import HISTORICAL_EXCESS_NS, SAMPLES, bind_quartet


BASE = "3b9242fc6ce655a0f29c91d52a081d8cf6ed06b4"
ARM_LIMIT_S = 45
ARM_ORDER = ("network-only", "kernel", "kernel", "network-only")
HERE = Path(__file__).resolve().parent
NETWORK = re.compile(r"\b(?:socket|socketpair|connect|bind|listen|accept4?|sendto|sendmsg|sendmmsg)\(")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_receipt(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def run_baseline(source, directory, input_args, environment):
    directory.mkdir()
    command = ["strace", "-ff", "-tt", "-e", "trace=network", "-o",
               str(directory / "network"), sys.executable, *input_args]
    with (directory / "execution.log").open("x") as log:
        process = subprocess.Popen(command, cwd=source, env=environment, start_new_session=True,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            return process.wait(timeout=ARM_LIMIT_S)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
            raise


def capture_rows(fixture, mode, directory, observer, native):
    assert fixture["head"] == HEAD and fixture["tree"] == TREE
    assert fixture["native_inference"] == "NOT_RUN" and fixture["socket_audit_attempts"] == 0
    assert fixture["outer_markers"] == 8 and fixture["qualification_eligible"] is False
    assert tuple(item["sample"] for item in fixture["controls"]) == SAMPLES
    assert native.process_limits() == fixture["process_limits"]
    assert (fixture["uid"], fixture["gid"], fixture["groups"], fixture["nice"], fixture["affinity"]) == (
        os.getuid(), os.getgid(), sorted(os.getgroups()), os.getpriority(os.PRIO_PROCESS, 0),
        sorted(os.sched_getaffinity(0)),
    )
    traces = list(directory.glob("network.*"))
    if not traces:
        raise ValueError("Original network-only trace absent")
    for trace in traces:
        lines = trace.read_text().splitlines()
        if not lines or not lines[-1].endswith("exited with 0 +++") or any(NETWORK.search(line) for line in lines):
            raise ValueError("Network call or missing clean trace exit")
    measurement = {
        "mode": mode, "fixture": fixture,
        "network_calls": 0, "network_trace_exits": len(traces),
        "network_hashes": {path.suffix[1:]: digest(path) for path in traces},
        "capture_ns": {row["sample"]: round(row["capture"]["capture_seconds"] * 1e9) for row in fixture["controls"]},
    }
    if mode == "kernel":
        events_path = directory / "kernel.stdout"
        if events_path.stat().st_size > observer.MAX_BYTES:
            raise ValueError("Observer exceeded original stream limit")
        records = native.read_records(directory)
        markers = [row for row in records if row[0] == "M"]
        bound = bind_quartet(markers, [pair for row in fixture["controls"] for pair in row["outer_brackets"]],
                             SAMPLES, fixture["tid"])
        inventory = native.inventory(records, traces)
        pairs = native.syscall_pairs(records, bound[800][9], bound[810][10])
        caller_windows = {}
        for sample, window in bound.items():
            if window[9] >= window[10]:
                raise ValueError("Inverted Capture frame")
            inside = [row for row in records if row[0] in {"S", "W"} and window[9] <= row[1] <= window[10]]
            intervals = observer.off_cpu_intervals(inside)
            caller = [row for row in intervals if row["tid"] == fixture["tid"]]
            switchouts = [row for row in inside if row[0] == "S" and row[2] == fixture["tid"]]
            if not switchouts or len(caller) != len(switchouts) or any(row["wake"] is None for row in caller):
                raise ValueError("Incomplete caller chronology")
            caller_windows[sample] = len(caller)
        measurement["kernel"] = {
            "inventory": inventory, "matched_raw_markers": len(markers), "caller_windows": caller_windows,
            "paired_operations": pairs, "bytes": events_path.stat().st_size,
            "sha256": digest(events_path), "numeric_events": records,
        }
    return measurement


def cost_so_far(arms):
    points = {sample: [arm["capture_ns"][sample] for arm in arms] for sample in SAMPLES}
    return {sample: max(values) - min(values) for sample, values in points.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--published-evidence", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    source, evidence, scratch = [value.resolve() for value in (args.source, args.published_evidence, args.scratch)]
    if evidence.exists() or scratch.exists() or evidence.is_relative_to(source) or scratch.is_relative_to(source):
        raise ValueError("Use fresh destinations outside the source")
    evidence.mkdir()
    scratch.mkdir()
    result = {"status": "REFUSED", "head": HEAD, "base": BASE, "tree": TREE,
              "event": "MODEL_FREE_CALIBRATION", "native_inference": "NOT_RUN",
              "qualification_eligible": False, "arm_limit_s": ARM_LIMIT_S, "arms": [],
              "driver_sha256s": {p.name: digest(p) for p in HERE.glob("*.py")}}
    try:
        result["source_bytes"] = source_identity(source)
        if git(source, "ls-remote", "https://github.com/gabned/provelume.git", "refs/heads/main").split()[0] != BASE:
            raise ValueError("Actual default changed")
        sys.path[:0] = [str(source), str(source / "core")]
        from scripts import concordia_kernel_native as native
        from scripts import concordia_kernel_observer as observer

        if os.geteuid() == 0 or subprocess.check_output(["sudo", "-n", "bpftrace", "--version"], text=True).strip() != "bpftrace v0.20.2":
            raise ValueError("Unreviewed observer version or privileged application")
        formats = {}
        for name in native.FORMATS:
            raw = subprocess.check_output(["sudo", "-n", "cat", f"/sys/kernel/tracing/events/{name}/format"])
            formats[name] = hashlib.sha256(raw).hexdigest()
            if name == "sched/sched_switch":
                suffix = raw.decode().split("print fmt: ", 1)[1].strip()
                if hashlib.sha256(suffix.encode()).hexdigest() != native.STATE_PRINT_SHA256:
                    raise ValueError("Unreviewed scheduler state layout")
        host = native.host()
        result.update(observer_source_sha256=digest(observer.PROGRAM), tracepoint_formats=formats,
                      tool_sha256s=host["tools"], runner_kernel=host["kernel"])

        for index, mode in enumerate(ARM_ORDER):
            directory = scratch / f"arm-{index}"
            probe = directory / "fixture.json"
            input_args = [str(HERE / "lightweight_frames.py"), "--source", str(source), "--output", str(probe)]
            if mode == "kernel":
                exit_code = native.collect(source, directory, input_args, ARM_LIMIT_S)
            else:
                exit_code = run_baseline(source, directory, input_args, native.child_environment())
            if exit_code or not probe.is_file():
                raise ValueError("Unsuccessful model-free arm")
            result["arms"].append(capture_rows(json.loads(probe.read_bytes()), mode, directory, observer, native))
            spreads = cost_so_far(result["arms"])
            result["observed_whole_probe_spread_ns"] = spreads
            if max(spreads.values()) * 3 >= HISTORICAL_EXCESS_NS[0]:
                raise ValueError("WHOLE_PROBE_COST_EXCEEDS_HISTORY_SCALE")
        result["status"] = "OBSERVED_CALIBRATION_WITHIN_RESOLUTION"
    except (AssertionError, IndexError, KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        result["failure"] = {"type": type(error).__name__, "detail": str(error)[:400]}
    finally:
        write_receipt(evidence / "receipt.json", result)
        print(json.dumps({key: result[key] for key in ("status", "native_inference")}))
        shutil.rmtree(scratch)
    return 0 if result["status"] == "OBSERVED_CALIBRATION_WITHIN_RESOLUTION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
