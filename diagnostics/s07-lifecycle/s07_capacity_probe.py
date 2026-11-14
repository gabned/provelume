"""Same-runner diagnostic for the passive capacity reads in S06 sample 4."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

BASE = "03aa36dd6cd1668174e860225a7a8a35cb40cb1e"
CPU = "AMD EPYC 9V74 80-Core Processor"
FACTOR_DELAY = 0.114


def known_delay():
    deadline = time.perf_counter() + FACTOR_DELAY
    while (remaining := deadline - time.perf_counter()) > 0:
        time.sleep(remaining)


def host():
    return {
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "affinity": sorted(os.sched_getaffinity(0)),
    }


def write_once(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def exact_source(source):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()

    if git("rev-parse", "HEAD") != BASE or git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("expected immutable #460 source")
    sys.path[:0] = [str(source / "core"), str(source / "scripts")]


@contextmanager
def scoped_admission(inject=None):
    from provelume import capacity_admission as capacity
    from provelume.capture_adapter import CaptureAdapter

    selected = []
    read_policy = capacity._read_file
    read_identity = capacity.CapacityAdmission._instance_id
    admit = CaptureAdapter._admit

    def observe(function):
        cpu = time.thread_time_ns()
        start = time.monotonic_ns()
        result = function()
        return result, {"wall_ns": time.monotonic_ns() - start,
                        "thread_cpu_ns": time.thread_time_ns() - cpu}

    def measured_policy(path):
        row = selected[-1]

        def invoke():
            if inject == "inside" and len(selected) == 1 and not row["policy"]:
                known_delay()
            return read_policy(path)

        result, record = observe(invoke)
        record["missing"] = result is capacity._MISSING
        row["policy"].append(record)
        return result

    def measured_identity(self):
        result, record = observe(lambda: read_identity(self))
        selected[-1]["identity"].append(record)
        return result

    def measured_admit(self, size):
        row = {"policy": [], "identity": []}
        selected.append(row)
        if inject == "outside" and len(selected) == 1:
            known_delay()
        result, record = observe(lambda: admit(self, size))
        row.update(record)
        return result

    with (patch.object(capacity, "_read_file", measured_policy),
          patch.object(capacity.CapacityAdmission, "_instance_id", measured_identity),
          patch.object(CaptureAdapter, "_admit", measured_admit)):
        yield selected
    if len(selected) != 2 or any(
        len(row["policy"]) != 2 or len(row["identity"]) != 2
        or not all(read["missing"] for read in row["policy"])
        for row in selected
    ):
        raise ValueError("expected two observe_only policy and identity reads per phase")


def controls(args):
    from ai_runtime_report import deterministic_probe

    from provelume.service import ProvelumeInstance

    admission = json.loads((args.admission / "admission.json").read_text())
    current_host = host()
    if (admission["status"] != "ADMITTED"
            or admission["host"]["cpu_model"] != CPU
            or len(current_host["affinity"]) != 4):
        raise ValueError("S06 sample 4 requires admitted 4-vCPU EPYC 9V74")
    output = args.output
    output.mkdir()
    records = {}
    for index, arm in enumerate(("control", "inside", "outside")):
        root = output.parent / f"s06-sample4-{index}"
        root.mkdir()
        instance = ProvelumeInstance.initialise(root / "synthetic-instance")
        # Three idle, three nongoverned busy and four earlier governed captures
        # precede the targeted sample. Match the retained Capture depth.
        for prior in range(10):
            prior_probe = deterministic_probe(instance, prior)
            if not all(prior_probe[key] for key in (
                "preserved", "search_found", "product_dispatch_blocked",
            )):
                raise ValueError("model-free prefill failed")
        with scoped_admission(arm) as spans:
            probe = deterministic_probe(instance, 4)
        if not all(probe[key] for key in ("preserved", "search_found", "product_dispatch_blocked")):
            raise ValueError("model-free capture failed")
        records[arm] = {"probe": probe, "submit": spans[0], "process": spans[1]}

    for arm in records:
        span = records[arm]["submit"]["policy"][0]
        slow_read = span["wall_ns"] >= FACTOR_DELAY * 1e9 and span["thread_cpu_ns"] < 10_000_000
        if slow_read != (arm == "inside"):
            raise ValueError("known delay was not localized to the policy read")
    write_once(output / "controls.json", {"host": current_host, "arms": records})


def controls_network(args):
    files = sorted(args.output.parent.glob("s06-capacity-controls-net.*"))
    if not files:
        raise ValueError("control network observer produced no traces")
    for file in files:
        text = file.read_text(encoding="utf-8")
        if (re.search(r"\b(socket|connect|sendto|sendmsg|sendmmsg)\(", text)
                or not text.rstrip().endswith("+++ exited with 0 +++")):
            raise ValueError("model-free control network/exit check failed")
    write_once(args.output / "controls-network.json", {"verified_traces": len(files)})


def native(args):
    import qualify_ai_jobs as jobs
    from qualify_ai_runtime import measure

    control = json.loads((args.output / "controls.json").read_text())
    if not json.loads((args.output / "controls-network.json").read_text())["verified_traces"]:
        raise ValueError("model-free control network/exit check missing")
    admission = json.loads((args.admission / "admission.json").read_text())
    age = time.clock_gettime_ns(time.CLOCK_BOOTTIME) - admission["started_boot_ns"]
    if (control["host"] != host() or not 0 <= age <= 900 * 1_000_000_000
            or admission["status"] != "ADMITTED"):
        raise ValueError("fresh admission and controls on this runner are required")
    write_once(args.output / "native-started.json", {"source": BASE, "host": control["host"]})
    original = jobs.deterministic_probe
    trace = {}

    def selected(instance, number):
        if number != 4:
            return original(instance, number)
        if trace:
            raise ValueError("S06 sample 4 repeated")
        with scoped_admission() as spans:
            result = original(instance, number)
        trace.update({"probe": dict(result), "submit": spans[0], "process": spans[1]})
        return result

    with patch.object(jobs, "deterministic_probe", selected):
        report = measure(args.inputs, args.output / "exact-report.json")
    if report["source_commit"] != BASE or not trace:
        raise ValueError("exact evaluator did not reach S06 sample 4")
    write_once(args.output / "sample4-trace.json", trace)


def summarize(args):
    from ai_runtime_report import evaluate

    output = args.output
    controls = json.loads((output / "controls.json").read_text())
    controls_network = json.loads((output / "controls-network.json").read_text())
    report = json.loads((output / "exact-report.json").read_text())
    trace = json.loads((output / "sample4-trace.json").read_text())
    print("S07_EXACT_EVALUATOR=" + json.dumps({
        "status": report["status"], "gates": report["gates"],
        "failures": report["failures"], "observer_exit": args.observer_exit,
    }))
    if (report["source_commit"] != BASE or report["network"] != "PASS"
            or args.observer_exit != (0 if report["status"] == "PASS" else 1)):
        raise ValueError("missing exact-source or independent network observation")
    rows = report["s06"]["deterministic_busy"]
    baseline = report["deterministic_idle"]
    if len(rows) != 6 or len(baseline) != 3 or rows[4]["sample"] != 4:
        raise ValueError("incomplete exact evaluation")
    row = rows[4]
    if (not all(row[key] for key in ("preserved", "search_found", "worker_observed",
                                    "product_dispatch_blocked"))
            or any(row[key] != trace["probe"][key] for key in trace["probe"])):
        raise ValueError("sample 4 is not a valid controlled observation")
    limit = min(1, 2 * statistics.median(row["capture_seconds"] for row in baseline) + 0.1)
    exceeds = row["capture_seconds"] > limit
    if exceeds:
        # Re-evaluate only a copy with the target metric at the unchanged bound.
        # A pass pins the original failure solely to the observed Capture duration.
        counterfactual = deepcopy(report)
        counterfactual["s06"]["deterministic_busy"][4]["capture_seconds"] = limit
        if report["status"] != "FAIL" or evaluate(counterfactual)["status"] != "PASS":
            raise ValueError("original run has failures beyond the target Capture duration")
    elif report["status"] != "PASS":
        raise ValueError("original run did not pass its unchanged controls")
    data = {
        "status": "OBSERVED_EXCEEDANCE" if exceeds else "NON_REPRODUCTION",
        "qualification_eligible": False,
        "limit_seconds": limit,
        "original_status": report["status"],
        "candidate_evaluator": report["gates"]["s06_governed"],
        "control_arms": controls["arms"],
        "control_network": controls_network,
        "sample": trace,
    }
    write_once(output / "summary.json", data)
    print("S07_SAMPLE4=" + json.dumps(data))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = {"controls": controls, "controls-network": controls_network,
                "native": native, "summarize": summarize}
    parser.add_argument("mode", choices=commands)
    parser.add_argument("source", type=Path)
    parser.add_argument("admission", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--observer-exit", type=int)
    args = parser.parse_args()
    exact_source(args.source)
    if args.mode == "native" and args.inputs is None:
        parser.error("native requires --inputs")
    if args.mode == "summarize" and args.observer_exit is None:
        parser.error("summarize requires --observer-exit")
    commands[args.mode](args)


if __name__ == "__main__":
    main()
