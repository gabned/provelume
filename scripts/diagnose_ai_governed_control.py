"""Predetermined ABBA governed Windows experiment; never a qualification gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "tests"))

from diagnose_ai_governed import require, save  # noqa: E402
from qualify_ai_jobs import measure_jobs, native_inputs  # noqa: E402
from qualify_ai_runtime import measure  # noqa: E402

from provelume.ai_context import native_task_payload  # noqa: E402

SCHEMA = "provelume-s06-governed-abba-diagnostic/v1"
BLOCKS = (("A1", "default"), ("B1", "blocktime0"),
          ("B2", "blocktime0"), ("A2", "default"))


def projection(samples):
    """Keep all cells and compare only the predeclared complete cohort."""
    groups = {mode: [r for r in samples if r["mode"] == mode]
              for mode in ("default", "blocktime0")}
    result = {"status": "INCOMPLETE", "qualification": "NOT_QUALIFIED"}
    if any(len(rows) != 12 for rows in groups.values()):
        return result
    summaries = {}
    for mode, rows in groups.items():
        native = [r["worker"].get("diagnostic_native", {}) for r in rows]
        idle = [r.get("idle_process_counters", {}).get("groups", {}).get("process_times", {})
                for r in native]
        if any(r.get("status") != "OBSERVED" for r in idle):
            return {**result, "reason": "complete idle process counters unavailable"}
        cpu = [(r["kernel_100ns_delta"] + r["user_100ns_delta"]) / 10**7 for r in idle]
        summaries[mode] = {
            "idle_cpu_seconds": cpu,
            "idle_cpu_sum_seconds": sum(cpu),
            "warm_first_seconds": [r["first_seconds"] for r in rows if r["phase"] == "warm"],
            "prefill_seconds": [r["worker"]["phases"]["prefill_seconds"] for r in rows],
            "idle_window_seconds": [r["idle_wall_seconds"] for r in native],
        }
    pairs = {}
    for row in samples:
        pairs.setdefault((row["pair"], row["phase"]), []).append(row)
    equal = all(len(rows) == 4
                and all(r["status"] == "succeeded" and r["attempts"] == 1 for r in rows)
                and len({r["synthetic_diagnostic_input"]["sha256"] for r in rows}) == 1
                and len({r["result_fingerprint"] for r in rows}) == 1
                and len({(r["worker"]["input_tokens"],
                          r["worker"]["reused_input_tokens"],
                          r["worker"]["output_tokens"]) for r in rows}) == 1
                for rows in pairs.values())
    baseline, treatment = summaries["default"], summaries["blocktime0"]
    # These are diagnostic decision criteria, not replacements for product gates.
    cost = (baseline["idle_cpu_sum_seconds"] >= 0.6
            and treatment["idle_cpu_sum_seconds"] <= baseline["idle_cpu_sum_seconds"] * 0.25)
    baseline_warm, treatment_warm = (statistics.median(r["warm_first_seconds"])
                                   for r in (baseline, treatment))
    latency = treatment_warm <= baseline_warm * 1.10
    settings = all(r["worker"]["diagnostic_native"]["blocktime"]["original_ms"] > 0
                   and r["worker"]["diagnostic_native"]["blocktime"]["restored"]
                   and r["worker"]["diagnostic_native"]["blocktime"]["observed_ms"]
                   == (0 if r["mode"] == "blocktime0" else
                       r["worker"]["diagnostic_native"]["blocktime"]["original_ms"])
                   for r in samples)
    prefill_tail = max(treatment["prefill_seconds"]) <= max(baseline["prefill_seconds"]) * 1.10
    resource_bounds = all(r["worker"]["memory"]["private_bytes"] <= 3 * 1024**3
                          and r["worker"]["load"]["limits"]["cpu_topology"]
                          ["selected_physical_cores"] == 2
                          and r["worker"]["load"]["limits"]["priority"]
                          == "JobObject:below-normal" for r in samples)
    per_block = {}
    for block, _mode in BLOCKS:
        rows = [r for r in samples if r["block"] == block]
        per_block[block] = sum(
            (r["worker"]["diagnostic_native"]["idle_process_counters"]["groups"]
             ["process_times"]["kernel_100ns_delta"]
             + r["worker"]["diagnostic_native"]["idle_process_counters"]["groups"]
             ["process_times"]["user_100ns_delta"]) / 10**7 for r in rows)
    replicated = max(per_block["B1"], per_block["B2"]) <= min(
        per_block["A1"], per_block["A2"]) * 0.25
    return {"status": "EVALUATED", "qualification": "NOT_QUALIFIED",
            "summaries": summaries, "block_idle_cpu_seconds": per_block,
            "exact_input_output_and_token_parity": equal,
            "verified_nonzero_baseline_intervention_and_restoration": settings,
            "predeclared_idle_cost_reduction": cost,
            "reduction_replicated_in_both_blocks": replicated,
            "predeclared_warm_latency_nonregression": latency,
            "predeclared_prefill_tail_nonregression": prefill_tail,
            "unchanged_resource_bounds": resource_bounds,
            "prospective_cost_correction_supported": (equal and cost and replicated and latency
                                                       and settings and prefill_tail
                                                       and resource_bounds)}


def run(artifacts, output):
    require(os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("S06_WFP_VERIFIED") == "1",
            "verified disposable Windows WFP required")

    def cohort(instance, store, runtime, report):
        experiment = {
            "schema": SCHEMA, "qualification": "NOT_QUALIFIED",
            "started_at": datetime.now(UTC).isoformat(),
            "blocks": list(BLOCKS), "samples_planned": 24,
            "idle_window_seconds": 0.3,
            "decision_criteria": {
                "baseline_idle_cpu_sum_at_least_seconds": 0.6,
                "intervention_idle_cpu_fraction_at_most": 0.25,
                "both_intervention_blocks_below_both_baseline_blocks_fraction": 0.25,
                "warm_first_median_ratio_at_most": 1.10,
                "prefill_maximum_ratio_at_most": 1.10,
                "nonzero_baseline_and_verified_intervention_restoration": True,
                "resource_bounds": "same two selected cores/below-normal/3GiB",
                "exact_payload_result_and_token_parity_single_successful_attempt": True,
                "all_product_qualification_gates": "separate unchanged-source candidate required",
            },
            "preceding_load": "complete unchanged S05 corpus, cold/busy/cancel/unload/error path",
            "planned_cells": [{"block": block, "mode": mode, "pair": pair, "phase": phase,
                               "outcome": "NOT_RUN"}
                              for block, mode in BLOCKS for pair in range(3)
                              for phase in ("cold", "warm")],
            "fixed_payloads": [],
        }
        proof = runtime.last_observation["load"]["limits"]
        for pair in range(3):
            for phase in ("cold", "warm"):
                inputs = native_inputs(instance, proof, text=(None if phase == "cold" else
                    "Contact ada@example.test, code PRIVATE.\fSecond page. "
                    f"Public variant {pair}."))
                raw = native_task_payload(inputs.preview, inputs.current["template"])
                experiment["fixed_payloads"].append({
                    "pair": pair, "phase": phase, "sha256": hashlib.sha256(raw).hexdigest(),
                    "utf8": raw.decode()})
        report["governed_experiment"] = experiment
        save(output, report)

        def checkpoint(result):
            report["s06"] = result
            for index, row in enumerate(result["samples"]):
                cell = experiment["planned_cells"][index]
                require((cell["block"], cell["pair"], cell["phase"])
                        == (row["block"], row["pair"], row["phase"]), "cohort order changed")
                require(row["synthetic_diagnostic_input"]["sha256"]
                        == experiment["fixed_payloads"][row["pair"] * 2
                           + (row["phase"] == "warm")]["sha256"], "fixed governed input changed")
                cell["outcome"] = "MEASURED"
            save(output, report)

        result = measure_jobs(instance, store, runtime,
                              diagnostic={"blocks": BLOCKS, "checkpoint": checkpoint})
        experiment["comparison"] = projection(result["samples"])
        experiment["finished_at"] = datetime.now(UTC).isoformat()
        return result

    report = measure(artifacts, output, governed_diagnostic=cohort)
    report["schema"] = SCHEMA
    report["qualification"] = "NOT_QUALIFIED"
    save(output, report)
    return report


def audit(report, data):
    require(report.get("schema") == SCHEMA and report.get("qualification") == "NOT_QUALIFIED",
            "governed diagnostic report required")
    pids = report.get("worker_pids", [])
    rows = data.get("events", [])
    require(isinstance(pids, list) and pids
            and all(type(pid) is int and pid > 0 for pid in pids), "complete worker inventory")
    require(isinstance(rows, list) and len(rows) <= 65536
            and all(isinstance(row, dict) and type(row.get("pid")) is int
                    and row["pid"] > 0 and row.get("id") in (5156, 5157) for row in rows),
            "bounded original WFP event inventory")
    experiment = report.get("governed_experiment", {})
    complete = (len(report.get("samples", [])) == 60
                and len(report.get("cold", [])) == 3
                and len(experiment.get("planned_cells", [])) == 24
                and all(c["outcome"] == "MEASURED" for c in experiment["planned_cells"])
                and len(report.get("s06", {}).get("diagnostic_self_tests", [])) == 15
                and report.get("s06", {}).get("worker_absent") is True
                and not report.get("failures"))
    events = [row for row in rows if row["pid"] in pids]
    calibrated = data.get("audit_enabled") is True and data.get("probe_denied") is True
    report["network_audit"] = {
        "method": "Windows WFP calibration and every recorded worker PID",
        "worker_pids": pids, "worker_events": events, "complete_cohort_and_cleanup": complete,
        "status": "FAIL" if events else "PASS" if calibrated and complete else "NOT_RUN"}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    if args.audit:
        require(args.artifacts is None, "audit performs no inference")
        report = audit(json.loads(args.output.read_text(encoding="utf-8")),
                       json.loads(args.audit.read_text(encoding="utf-8-sig")))
        save(args.output, report)
        return 0 if report["network_audit"]["status"] == "PASS" else 2
    require(args.artifacts is not None and args.artifacts.is_absolute(), "absolute artifact path")
    report = run(args.artifacts, args.output)
    return 0 if report.get("governed_experiment", {}).get("comparison", {}).get(
        "status") == "EVALUATED" and not report.get("failures") else 2


if __name__ == "__main__":
    raise SystemExit(main())
