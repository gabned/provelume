"""Trusted stdlib-only prospective diagnostic analysis, review candidate v1.

The eventual accepted operator must pin this file, plan and original ZIPs and run
it in the credential-free offline context. It never imports candidate code or
executes an archive member. No candidate-provided DEMONSTRATED verdict is read.

Missing/unsupported fields produce NOT_DEMONSTRATED, never an inferred value.
No candidate code is imported and no archive member is executed or extracted.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import statistics
import zipfile


TELEMETRY_SCHEMA = "capture-cost-temporary-telemetry/v1"
PLAN_SCHEMA = "capture-single-task-experiment/v1"
REPLAY_SCHEMA = "capture-cost-independent-ordinary-replay/v1"
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 4096
POOL_API = {"pool.create", "pool.submit", "pool.future_result_wait", "pool.shutdown_join"}
OPERATION_LABELS = {
    "os.fsync": "fsync", "os.replace": "replace", "os.rename": "rename",
    "atomic.payload_write_flush_fsync": "write_journal_payload",
    "store.atomic_bytes": "store_atomic_bytes",
}
CALIBRATION_PATTERNS = {
    "A": ["pool.create", "pool.submit", "pool.task", "atomic.payload_write_flush_fsync",
          "os.fsync", "pool.future_result_wait", "pool.shutdown_join", "pool.create",
          "atomic._publish_entries", "os.replace", "pool.submit", "pool.task",
          "atomic.directory_fsync", "os.fsync", "pool.future_result_wait", "pool.shutdown_join"],
    "B": ["atomic.payload_write_flush_fsync", "os.fsync", "atomic._publish_entries",
          "os.replace", "atomic.directory_fsync", "os.fsync"],
}
GATES = {
    "cold_load", "cold_first", "cold_total", "warm_first", "warm_total",
    "warm_preparation", "worker_peak_rss", "cancel_load", "cancel_generation",
    "unload", "parent_ram_after_unload", "quality_en", "quality_it",
    "absent_model", "altered_model", "deterministic", "network", "next_caller",
    "s06_governed", "s07_setup", "s08_references", "s08_abstention",
    "s08_quality_en_summary", "s08_quality_en_key-points",
    "s08_quality_it_summary", "s08_quality_it_key-points", "s08_performance",
    "iudicium_execution_conformance",
}


class Unsupported(ValueError):
    """Closed analysis failure; messages contain fixed codes, never input text."""


def require(condition, code):
    if not condition:
        raise Unsupported(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def nonfinite(_value):
        raise Unsupported("nonfinite_json_number")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def integer(value, code):
    require(type(value) is int and value >= 0, code)
    return value


def merge(intervals):
    """Disjoint closed-open wall intervals; nesting/concurrency is not summed."""
    result = []
    for start, end in sorted(intervals):
        integer(start, "interval_start")
        integer(end, "interval_end")
        require(start <= end, "interval_order")
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def measure(intervals):
    return sum(end - start for start, end in merge(intervals))


def intersect(left, right):
    left, right = merge(left), merge(right)
    i = j = 0
    result = []
    while i < len(left) and j < len(right):
        start, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if start < end:
            result.append((start, end))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return result


def span_interval(span):
    return (integer(span["before"]["monotonic_ns"], "span_before"),
            integer(span["after"]["monotonic_ns"], "span_after"))


def seconds_ns(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "invalid_seconds")
    return round(value * 1_000_000_000)


def subtract(left, right):
    result = []
    right = merge(right)
    for begin, end in merge(left):
        cursor = begin
        for low, high in right:
            if high <= cursor:
                continue
            if low >= end:
                break
            if cursor < low:
                result.append((cursor, min(low, end)))
            cursor = max(cursor, high)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def pool_administration(callback):
    """Only eligible API spans, minus any actual task overlap, in wall ns.

    An entire executor lifetime is deliberately NOT used: mandatory parent
    marker/fsync work can occur inside that lifetime. The API whitelist above
    must remain pinned to the reviewed recorder implementation.
    """
    spans = callback["spans"]
    tasks = [s for s in spans if s["label"] == "pool.task"]
    counts = Counter(s["extra"]["pool"] for s in tasks)
    eligible = {pool for pool, count in counts.items() if count == 1}
    residual, raw_api, own_overlap, cross_overlap = [], [], [], []
    admin_event_count = 0
    for pool in eligible:
        api = [span_interval(s) for s in spans
               if s["label"] in POOL_API and s["extra"].get("pool") == pool]
        own_task = [span_interval(s) for s in tasks if s["extra"].get("pool") == pool]
        other_tasks = [span_interval(s) for s in tasks if s["extra"].get("pool") != pool]
        require(bool(api) and len(own_task) == 1, "pool_api_task_coverage")
        raw_api.extend(api)
        own_overlap.extend(intersect(api, own_task))
        cross_overlap.extend(intersect(api, other_tasks))
        residual.extend(subtract(api, own_task))
        admin_event_count += len(api) + len(own_task)
    return {
        "eligible_pool_count": len(eligible),
        "eligible_administration_event_count": admin_event_count,
        "api_union_ns": measure(raw_api),
        "same_pool_task_overlap_union_ns": measure(own_overlap),
        "cross_pool_task_overlap_union_ns": measure(cross_overlap),
        "critical_api_administration_ns": measure(residual),
        "scope": "eligible executor APIs, not a complete operation/CPU attribution",
    }


def capture_process_cpu(callback):
    """Parent process CPU includes A pool threads; native child is another PID.

    The boundary is the actual submit API entry through process API return.
    It excludes following search and caller timer bookkeeping. It is not the
    calling thread's CPU and not the sum of inclusive nested span CPU values.
    """
    starts = [s for s in callback["spans"] if s["label"] == "capture.submit"]
    stops = [s for s in callback["spans"] if s["label"] == "capture.process"]
    require(len(starts) == len(stops) == 1, "capture_api_boundary_coverage")
    first, last = starts[0], stops[0]
    require(first["tid"] == last["tid"], "capture_caller_tid_changed")
    require(first["after"]["monotonic_ns"] <= last["before"]["monotonic_ns"],
            "capture_api_boundary_order")
    before = integer(first["before"]["process_cpu_ns"], "process_cpu_before")
    after = integer(last["after"]["process_cpu_ns"], "process_cpu_after")
    require(after >= before, "process_cpu_decreased")
    inside = [s for s in callback["spans"]
              if first["before"]["monotonic_ns"] <= s["before"]["monotonic_ns"]
              and s["after"]["monotonic_ns"] <= last["after"]["monotonic_ns"]]
    return {"process_cpu_ns": after - before,
            "recorded_span_count": len(inside),
            "boundary_start_ns": first["before"]["monotonic_ns"],
            "boundary_end_ns": last["after"]["monotonic_ns"],
            "scope": "submit API entry through process API return, not subsequent search"}


def required_operations(callback):
    """Recompute selected wrapped-operation counts from raw spans.

    These are different abstraction levels, never a total kernel-I/O count.
    Actual identity/timestamp hashes are not required to be falsely equal.
    """
    require(callback.get("operation_coverage") == "COMPLETE_SELECTED_WRAPPED_OPERATIONS",
            "selected_operation_coverage")
    counts, byte_counts = Counter(), Counter()
    raw_operations = []
    for span in callback["spans"]:
        label = span["label"]
        if label not in OPERATION_LABELS:
            continue
        require("exception_type" not in span, "operation_outcome")
        details = span.get("extra", {})
        require(type(details.get("role")) is str and details["role"], "operation_role")
        key = label + ":" + details["role"]
        counts[key] += 1
        if label in ("atomic.payload_write_flush_fsync", "store.atomic_bytes"):
            byte_counts[key] += integer(details.get("bytes"), "operation_bytes")
        raw_operations.append({"span_id": span["id"], "label": label,
                               "kind": OPERATION_LABELS[label], "role": details["role"],
                               "bytes": details.get("bytes"), "outcome": "OK"})
    require(bool(counts), "durable_operations_missing")
    if "operations" in callback:
        projected = [{k: event.get(k) for k in
                      ("span_id", "label", "kind", "role", "bytes", "outcome")}
                     for event in callback["operations"]]
        require(projected == raw_operations, "operation_projection_mismatch")
    return counts, byte_counts, raw_operations


def validate_callback(callback):
    require(callback.get("arm") in ("A", "B"), "callback_arm")
    require("exception_type" not in callback, "callback_original_exception")
    probe = callback.get("probe")
    require(type(probe) is dict, "callback_probe_missing")
    for name in ("preserved", "search_found", "product_dispatch_blocked"):
        require(probe.get(name) is True, "callback_semantic_outcome")
    begin = integer(callback["before"]["monotonic_ns"], "callback_before")
    end = integer(callback["after"]["monotonic_ns"], "callback_after")
    require(begin <= end, "callback_clock_order")
    spans = callback.get("spans")
    require(type(spans) is list and spans, "callback_spans_missing")
    require(callback.get("span_event_attempts") == len(spans)
            and callback.get("observer_outer_events") == 1, "callback_event_attempt_coverage")
    ids = {s["id"] for s in spans}
    require(len(ids) == len(spans), "duplicate_span_id")
    for span in spans:
        start, stop = span_interval(span)
        require(begin <= start <= stop <= end, "span_outside_callback")
        require(span.get("parent") is None or span["parent"] in ids, "span_parent_missing")
        require("exception_type" not in span, "span_original_exception")
        for name in ("thread_cpu_ns", "process_cpu_ns"):
            require(span["after"][name] >= span["before"][name], "span_cpu_decreased")
    return probe


def calibration_envelope(telemetry):
    """All 512 raw patterns define a prospective empirical range per event.

    This is not a universal scheduling/recorder bound. It never changes a raw
    time or an official threshold. Its differential use is frozen in the plan.
    """
    cal = telemetry.get("calibration")
    require(type(cal) is dict and cal.get("schema") == "capture-cost-recorder-calibration/v1"
            and cal.get("complete") is True
            and cal.get("kind") == "RECORDER_NOOP_OVERHEAD_NOT_PRODUCT_WORK",
            "calibration_missing_or_unsupported")
    require(cal.get("pairs") == 256 and cal.get("patterns") == CALIBRATION_PATTERNS,
            "calibration_fixed_pattern_contract")
    samples = cal.get("samples")
    require(type(samples) is list and len(samples) == 256, "calibration_count")
    values = {"wall_ns": [], "process_cpu_ns": []}
    for index, sample in enumerate(samples):
        require(sample.get("pair") == index and sample.get("order") ==
                (["A", "B"] if index % 2 == 0 else ["B", "A"]), "calibration_pair_order")
        for arm in ("A", "B"):
            row = sample["patterns"][arm]
            events = len(CALIBRATION_PATTERNS[arm])
            require(row.get("event_count") == len(row["spans"]) == events
                    and row.get("span_event_attempts") == events
                    and row.get("observer_outer_events") == 1
                    and [s["label"] for s in row["spans"]] == CALIBRATION_PATTERNS[arm],
                    "calibration_event_coverage")
            require(all("exception_type" not in s and s.get("after") is not None
                        for s in row["spans"]), "calibration_span_outcome")
            for field, key in (("wall_ns", "monotonic_ns"), ("process_cpu_ns", "process_cpu_ns")):
                elapsed = row["after"][key] - row["before"][key]
                require(elapsed >= 0 and math.isfinite(elapsed), "calibration_negative_or_nonfinite")
                values[field].append(elapsed / events)
    result = {}
    for field, clock in (("wall_ns", "monotonic"), ("process_cpu_ns", "process_time")):
        resolution = cal["clock_resolution_ns"][clock]
        require(type(resolution) in (int, float) and math.isfinite(resolution)
                and resolution >= 0, "calibration_resolution")
        result[field] = {"low_ns_per_event": max(0, min(values[field]) - resolution),
                         "high_ns_per_event": max(values[field]) + resolution,
                         "all_512_raw_unit_costs": values[field], "resolution_ns": resolution}
    result["scope"] = "empirical no-op recorder envelope; other bookkeeping/scheduling is not universally bounded"
    return result


def cycle_contrasts(rows, field, envelope):
    result = []
    for start in (0, 4, 8):
        cycle = rows[start:start + 4]
        a = [row for row in cycle if row["arm"] == "A"]
        b = [row for row in cycle if row["arm"] == "B"]
        require(len(a) == len(b) == 2, "cycle_balance")
        n_a = statistics.mean(r["capture_event_count"] for r in a)
        n_b = statistics.mean(r["capture_event_count"] for r in b)
        low, high = envelope["low_ns_per_event"], envelope["high_ns_per_event"]
        bias_low, bias_high = low*n_a - high*n_b, high*n_a - low*n_b
        raw = statistics.mean(r[field] for r in a) - statistics.mean(r[field] for r in b)
        result.append({"cycle": start // 4, "raw_A_minus_B_ns": raw,
                       "mean_event_counts": {"A": n_a, "B": n_b},
                       "observer_bias_interval_ns": [bias_low, bias_high],
                       "empirical_effect_interval_ns": [raw-bias_high, raw-bias_low]})
    return result


def group_metrics(telemetry, group, order):
    callbacks = [c for c in telemetry["callbacks"] if c["group"] == group]
    require(len(callbacks) == 12, "micro_callback_count")
    callbacks.sort(key=lambda c: c["treatment_ordinal"])
    require([c["treatment_ordinal"] for c in callbacks] == list(range(12)), "micro_ordinal_coverage")
    require("".join(c["arm"] for c in callbacks) == order * 3, "micro_treatment_order")
    values = []
    ops = {arm: Counter() for arm in ("A", "B")}
    byte_ops = {arm: Counter() for arm in ("A", "B")}
    for index, callback in enumerate(callbacks):
        probe = validate_callback(callback)
        require(callback["section_context"].get("micro_pass") == index // 6,
                "micro_instance_assignment")
        operation_counts, operation_bytes, operations = required_operations(callback)
        ops[callback["arm"]].update(operation_counts)
        byte_ops[callback["arm"]].update(operation_bytes)
        cpu = capture_process_cpu(callback)
        values.append({"id": callback["id"], "ordinal": index, "arm": callback["arm"],
                       "capture_wall_ns": seconds_ns(probe["capture_seconds"]),
                       "submit_through_process_cpu_ns": cpu["process_cpu_ns"],
                       "capture_cpu_boundary": cpu,
                       "capture_event_count": cpu["recorded_span_count"],
                       "pool_api_administration": pool_administration(callback),
                       "selected_operations": operations, "span_count": len(callback["spans"])})
    envelope = calibration_envelope(telemetry)
    contrasts = {field: cycle_contrasts(values, field, envelope[
                     "wall_ns" if field == "capture_wall_ns" else "process_cpu_ns"])
                 for field in ("capture_wall_ns", "submit_through_process_cpu_ns")}
    summaries = {field: {
        "raw_median_A_minus_B_ns": statistics.median(v["raw_A_minus_B_ns"] for v in cycles),
        "empirical_median_effect_interval_ns": [statistics.median(v["empirical_effect_interval_ns"][i]
                                                                  for v in cycles) for i in (0, 1)]}
                for field, cycles in contrasts.items()}
    return {"group": group, "rows": values, "recorder_empirical_envelope": envelope,
            "cycle_contrasts_A_minus_B": contrasts,
            "contrast_summaries": summaries,
            "required_durable_counts": {k: dict(v) for k, v in ops.items()},
            "required_durable_bytes": {k: dict(v) for k, v in byte_ops.items()},
            "durable_counts_equal": ops["A"] == ops["B"],
            "durable_bytes_equal": byte_ops["A"] == byte_ops["B"]}


def full_ordinary_coverage(report):
    """An early aborted FAIL is not a full previous-load control observation."""
    require(report.get("status") in ("PASS", "FAIL") and report.get("failures") == [],
            "ordinary_original_exception_or_partial_status")
    require(report.get("phase") == "final_integrity_and_cleanup"
            and report.get("final_integrity_stage") == "capture_diagnostic", "ordinary_final_phase")
    require(len(report.get("cold", [])) == 3 and len(report.get("samples", [])) == 60,
            "ordinary_3_cold_60_samples")
    require(3 <= len(report.get("warm_preparations", [])) <= 60, "ordinary_warm_preparation_coverage")
    require(len(report.get("deterministic_idle", [])) == 3
            and len(report.get("deterministic_busy", [])) == 3, "ordinary_s05_probe_coverage")
    require(all(report.get(key) for key in ("cancel_load", "cancel_generation", "idle_unload",
                                           "worker_error", "altered_model", "absent_model")),
            "ordinary_lifecycle_coverage")
    s06, s07, s08 = report.get("s06", {}), report.get("s07", {}), report.get("s08", {})
    require(s06.get("status") == "MEASURED" and len(s06.get("samples", [])) == 6
            and len(s06.get("cancellations", [])) == 2
            and len(s06.get("deterministic_busy", [])) == 6, "ordinary_full_s06_coverage")
    require(s07.get("status") == "MEASURED" and len(s07.get("samples", [])) == 2,
            "ordinary_full_s07_coverage")
    require(s08.get("status") == "MEASURED" and len(s08.get("samples", [])) == 32
            and len(s08.get("performance", [])) == 2 and len(s08.get("idle", [])) == 3
            and bool(s08.get("cancellation")), "ordinary_full_s08_coverage")
    iudicium = report.get("iudicium_execution", {})
    require(iudicium.get("status") == "MEASURED" and len(iudicium.get("samples", [])) == 2
            and {r.get("language") for r in iudicium["samples"]} == {"en", "it"}
            and iudicium.get("journey", {}).get("status") == "MEASURED",
            "ordinary_full_iudicium_coverage")
    network = report.get("network_observation", {})
    require(report.get("network") == "PASS" and network.get("status") == "PASS"
            and network.get("complete_phases") is True and bool(report.get("worker_pids")),
            "ordinary_complete_network_observation")
    require(all(v in ("PASS", "FAIL") for v in report["gates"].values()),
            "ordinary_not_run_or_blocked_gate")
    return {"source": "raw final original report", "complete_previous_load": True,
            "three_cold": 3, "samples": 60, "idle": 3, "s05_busy": 3,
            "s06_samples": 6, "s06_cancellations": 2, "s07_samples": 2,
            "s08_samples": 32, "iudicium_samples": 2, "network_complete": True}


def ordinary_evidence(report, replay, source_head, report_sha256, evaluator_sha256):
    require(report.get("source_commit") == source_head, "ordinary_source_head")
    raw = report.get("gates")
    require(type(raw) is dict and set(raw) == GATES, "ordinary_gate_shape")
    require(type(replay) is dict and replay.get("schema") == REPLAY_SCHEMA,
            "accepted_independent_ordinary_replay_required")
    require(replay.get("ordinary_report_sha256") == report_sha256
            and replay.get("evaluator_sha256") == evaluator_sha256,
            "ordinary_replay_input_or_evaluator_identity")
    require(replay.get("gates") == raw, "ordinary_recomputed_gate_map_mismatch")
    coverage = full_ordinary_coverage(report)
    # Supplied by the separately pinned trusted operator, not the candidate:
    # aggregated deterministic/S06/S07/S08 gates must be factored so a genuine
    # timing failure cannot conceal a semantic/security/lifecycle failure.
    require(replay.get("all_nonperformance_controls_pass") is True,
            "accepted_nonperformance_control_factorization_required")
    return {"original_gate_map": raw, "accepted_recomputed_gate_map": replay["gates"],
            "full_previous_load": coverage,
            "all_28_pass": all(v == "PASS" for v in replay["gates"].values())}


def empirical_duration(row, field, envelope):
    value, events = row[field], row["capture_event_count"]
    low = max(0, value - envelope["high_ns_per_event"] * events)
    high = value - envelope["low_ns_per_event"] * events
    require(high >= low, "duration_outside_empirical_recorder_envelope")
    return [low, high]


def margin_intervals(idle, busy):
    result = {}
    for arm in ("A", "B"):
        baselines = [r for r in idle["rows"] if r["arm"] == arm]
        loads = [r for r in busy["rows"] if r["arm"] == arm]
        require(len(baselines) == len(loads) == 6, "arm_count")
        idle_bounds = [empirical_duration(r, "capture_wall_ns", idle["recorder_empirical_envelope"]["wall_ns"])
                       for r in baselines]
        busy_bounds = [empirical_duration(r, "capture_wall_ns", busy["recorder_empirical_envelope"]["wall_ns"])
                       for r in loads]
        raw_idle = [r["capture_wall_ns"] for r in baselines]
        raw_busy = [r["capture_wall_ns"] for r in loads]
        low = max(v[0] for v in busy_bounds) - min(
            1_000_000_000, 2*statistics.median(v[1] for v in idle_bounds)+100_000_000)
        high = max(v[1] for v in busy_bounds) - min(
            1_000_000_000, 2*statistics.median(v[0] for v in idle_bounds)+100_000_000)
        result[arm] = {
            "raw_margin_ns": max(raw_busy) - min(1_000_000_000, 2*statistics.median(raw_idle)+100_000_000),
            "empirical_margin_interval_ns": [low, high],
            "raw_spread_ns": max(raw_busy)-statistics.median(raw_busy),
            "empirical_spread_interval_ns": [
                max(v[0] for v in busy_bounds)-statistics.median(v[1] for v in busy_bounds),
                max(v[1] for v in busy_bounds)-statistics.median(v[0] for v in busy_bounds)],
            "idle_empirical_intervals_ns": idle_bounds, "busy_empirical_intervals_ns": busy_bounds,
        }
    improvement = [result["A"]["empirical_margin_interval_ns"][0] - result["B"]["empirical_margin_interval_ns"][1],
                   result["A"]["empirical_margin_interval_ns"][1] - result["B"]["empirical_margin_interval_ns"][0]]
    spread_improvement = [result["A"]["empirical_spread_interval_ns"][0] - result["B"]["empirical_spread_interval_ns"][1],
                          result["A"]["empirical_spread_interval_ns"][1] - result["B"]["empirical_spread_interval_ns"][0]]
    return {"arms": result,
            "raw_improvement_A_minus_B_ns": result["A"]["raw_margin_ns"] - result["B"]["raw_margin_ns"],
            "empirical_improvement_interval_ns": improvement,
            "observed_compatibility_with_no_material_regression": improvement[1] >= 0,
            "observed_headroom_benefit": improvement[0] > 0,
            "empirical_spread_improvement_interval_ns": spread_improvement,
            "observed_spread_benefit": spread_improvement[0] > 0,
            "scope": "six-idle/six-busy diagnostic metric, never a replacement ordinary gate"}


def governed_semantics(governed):
    """Mandatory non-Capture-wall S06 predicates, using accepted limits.

    The relative Capture metric is evaluated separately. Nothing here authorizes
    a change to the ordinary evaluator or fabricates a governed PASS gate.
    """
    require(governed.get("status") == "MEASURED", "governed_not_measured")
    rows, cancels, probes = (governed.get("samples", []), governed.get("cancellations", []),
                             governed.get("deterministic_busy", []))
    require(len(rows) == 6 and len(cancels) == 2 and len(probes) == 6, "governed_full_shape")
    require(all(governed.get(k) is True for k in ("default_off", "final_off", "worker_absent"))
            and governed.get("next_caller") == "succeeded" and governed.get("receipt_count") == 9,
            "governed_lifecycle_or_receipts")
    for index, row in enumerate(rows):
        worker, usage = row["worker"], row["consumption"]
        cold = index % 2 == 0
        require(row.get("phase") == ("cold" if cold else "warm")
                and row.get("status") == "succeeded" and row.get("attempts") == 1,
                "governed_real_first_attempt_outcome")
        require(usage.get("usage_source") == "LOCAL" and usage.get("micros") == 0
                and usage.get("units", 0) > 0 and row.get("result_fingerprint") is not None,
                "governed_accounting_or_output")
        require(worker["memory"]["peak_rss"] <= 2 * 1024**3
                and row["seconds"] <= (60 if cold else 30)
                and row.get("first_seconds") is not None
                and row["first_seconds"] <= (20 if cold else 5)
                and (not cold or worker["load"]["seconds"] <= 15), "governed_existing_native_bounds")
        reused, tokens = worker.get("reused_input_tokens"), worker["input_tokens"]
        require(reused == 0 if cold else type(reused) is int and 0 < reused < tokens - 1,
                "governed_reuse_semantics")
        limits = worker["load"]["limits"]
        require(limits.get("memory_bytes") == 3 * 1024**3
                and limits.get("cpu") == "sched_setaffinity:2"
                and limits.get("cpu_topology", {}).get("selected_physical_cores") == 2
                and len(limits.get("cpu_topology", {}).get("selected_logical_cpus", [])) == 2
                and limits.get("nice", -1) >= 10
                and limits.get("network_control") == "seccomp:socket-syscalls-EPERM",
                "governed_resource_or_network_controls")
    require(len({r.get("binding") for r in rows if r["phase"] == "warm"}) == 3
            and all(rows[i].get("binding") != rows[i+1].get("binding") for i in (0, 2, 4)),
            "governed_binding_semantics")
    require(all(c.get("status") == "cancelled" and c.get("worker_absent") is True
                and c.get("active") == 0 and c.get("seconds") is not None and c["seconds"] <= 2
                for c in cancels), "governed_cancellation_semantics")
    require(all(all(p.get(k) is True for k in
                    ("preserved", "search_found", "worker_observed", "product_dispatch_blocked"))
                for p in probes), "governed_probe_semantics")
    require(governed.get("idle_unload", {}).get("worker_absent") is True
            and governed["idle_unload"]["seconds"] <= 7
            and governed["parent_after"]["rss"] - governed["parent_before"]["rss"] <= 64 * 1024**2,
            "governed_cleanup_semantics")
    return {"complete": True, "six_first_attempt_native_jobs": True,
            "cancellations": 2, "receipts": 9,
            "scope": "non-Capture-wall S06 semantics; relative Capture limits remain separate"}


def proc_process(snapshot, pid):
    rows = [p for p in snapshot["processes"] if p["pid"] == pid]
    require(len(rows) == 1, "process_snapshot_pid_coverage")
    process = rows[0]["process"]
    require(all(type(process.get(k)) in (dict, list) and "unavailable_errno" not in process[k]
                for k in ("stat", "schedstat", "status", "io")), "process_counter_coverage")
    require(type(process["stat"].get("start_ticks")) is int, "process_start_identity")
    required = {"stat": {"minor_faults", "major_faults", "user_ticks", "system_ticks", "start_ticks"},
                "status": {"voluntary_ctxt_switches", "nonvoluntary_ctxt_switches"},
                "io": {"rchar", "wchar", "syscr", "syscw", "read_bytes", "write_bytes", "cancelled_write_bytes"}}
    for key, fields in required.items():
        require(fields <= set(process[key])
                and all(type(process[key][field]) is int for field in fields),
                "process_exact_counter_coverage")
    require(type(process["stat"].get("state")) is str
            and type(process["schedstat"]) is list and len(process["schedstat"]) == 3
            and all(type(v) is int and v >= 0 for v in process["schedstat"]),
            "process_schedstat_state_coverage")
    return process


def actual_governed_activity(telemetry, configuration_sha256):
    """Zero is a valid observation, never a reason to exclude/retime a probe."""
    appended = telemetry["appended_report"]
    callbacks = sorted([c for c in telemetry["callbacks"] if c["group"] == "appended_governed_busy"],
                       key=lambda c: c["treatment_ordinal"])
    require(len(callbacks) == 12, "activity_all_twelve_callbacks")
    result, matched_call_ids, topologies = [], set(), []
    for ordinal, callback in enumerate(callbacks):
        pass_index, local_index = divmod(ordinal, 6)
        governed = appended["passes"][pass_index]["governed"]
        governed_semantics(governed)
        idle = appended["passes"][pass_index]["idle"]
        require(len(idle) == 6, "governed_search_baseline_coverage")
        search_limit = min(1, 2*statistics.median(p["search_seconds"] for p in idle)+0.1)
        require(all(p["search_seconds"] <= search_limit for p in governed["deterministic_busy"]),
                "governed_existing_search_formula_with_full_pass_baseline")
        official_probe = governed["deterministic_busy"][local_index]
        require(all(official_probe.get(k) == v for k, v in callback["probe"].items()),
                "appended_probe_original_row_binding")
        worker = governed["samples"][local_index]["worker"]
        topologies.append(worker["load"]["limits"]["cpu_topology"])
        prefill, pid = worker["prefill"], worker["load"]["pid"]
        require(prefill["pid"] == pid, "governed_prefill_pid_identity")
        request = prefill["request"]
        matches = [n for n in telemetry["native_calls"]
                   if n.get("section") == "appended_governed_busy"
                   and n.get("section_context", {}).get("micro_pass") == pass_index
                   and n.get("request") == request and n.get("worker_pid") == pid]
        require(len(matches) == 1 and matches[0]["id"] not in matched_call_ids,
                "governed_call_identity_or_duplicate")
        call = matches[0]
        matched_call_ids.add(call["id"])
        require("exception_type" not in call and call.get("input_tokens") == worker["input_tokens"]
                and call.get("configuration_sha256") == configuration_sha256
                and call.get("output_tokens") == worker["output_tokens"]
                and type(call.get("prompt_sha256")) is str and len(call["prompt_sha256"]) == 64
                and type(call.get("output_sha256")) is str and len(call["output_sha256"]) == 64,
                "governed_native_hash_or_token_coverage")
        for side in ("before", "after"):
            observed = [r for r in callback["runtime_"+side] if r.get("pid") == pid and r.get("request") == request]
            require(len(observed) == 1, "runtime_pid_request_coverage")
        before, after = callback["proc_before"], callback["proc_after"]
        p0, p1 = proc_process(before, pid), proc_process(after, pid)
        require(p0["stat"]["start_ticks"] == p1["stat"]["start_ticks"], "worker_pid_start_changed")
        ticks = ((p1["stat"]["user_ticks"] + p1["stat"]["system_ticks"])
                 - (p0["stat"]["user_ticks"] + p0["stat"]["system_ticks"]))
        require(ticks >= 0 and before["clock_ticks_per_second"] == after["clock_ticks_per_second"],
                "worker_tick_counter_consistency")
        tick_ns = 1_000_000_000 / before["clock_ticks_per_second"]
        boundary = capture_process_cpu(callback)
        bracket_start = before["monotonic_ns"]
        bracket_end = after["monotonic_ns"] + after["observation_wall_ns"]
        require(bracket_start <= boundary["boundary_start_ns"] <= boundary["boundary_end_ns"] <= bracket_end,
                "activity_snapshot_bracket")
        outside = ((boundary["boundary_start_ns"] - bracket_start)
                   + (bracket_end - boundary["boundary_end_ns"]))
        # Two separate accounting tick quantizations and two permitted CPUs.
        # This conservative lower bound can be <=0 and remains valid data.
        activity_lower = max(0, (ticks-2)*tick_ns - 2*outside)
        result.append({"ordinal": ordinal, "callback_id": callback["id"], "arm": callback["arm"],
                       "micro_pass": pass_index, "phase": "cold" if local_index % 2 == 0 else "warm",
                       "native_call_id": call["id"], "pid": pid, "request": request,
                       "prompt_sha256": call["prompt_sha256"], "prompt_bytes": call["prompt_bytes"],
                       "output_sha256": call["output_sha256"], "input_tokens": call["input_tokens"],
                       "output_tokens": call["output_tokens"], "observed_worker_cpu_ticks": ticks,
                       "tick_ns": tick_ns, "snapshot_outside_capture_wall_ns": outside,
                       "worker_cpu_inside_capture_lower_bound_ns": activity_lower,
                       "positive_cpu_inside_capture_proven_by_empirical_counters": activity_lower > 0})
    require(len(matched_call_ids) == 12, "twelve_actual_governed_calls_required")
    require(all(t == topologies[0] for t in topologies), "within_host_exact_cpu_topology_changed")
    return {"coverage": "COMPLETE_TWELVE_REAL_GOVERNED_CALLS",
            "rows": result, "all_positive_inside_capture": all(r["worker_cpu_inside_capture_lower_bound_ns"] > 0 for r in result),
            "limits": ["Zero/nonpositive lower bounds remain valid observations and are not excluded.",
                       "Positive CPU is not a native-prefill claim or proof of continuous activity.",
                       "Source trigger remains the original after-first callback."]}


def network_and_original_boundaries(plan, telemetry, telemetry_sha256, report,
                                    before, before_sha256, trace_receipt, trace_audit):
    mutable = {"status", "network", "network_observation", "gates"}
    require({k: v for k, v in before.items() if k not in mutable}
            == {k: v for k, v in report.items() if k not in mutable},
            "ordinary_changed_beyond_network_observer_fields")
    binding = telemetry["identity"].get("ordinary_raw_before_network_observer", {})
    require(binding.get("sha256") == before_sha256, "original_before_network_hash_binding")
    require(trace_receipt.get("schema") == "diagnostic-appended-worker-trace-presence/v1"
            and trace_receipt.get("telemetry_sha256") == telemetry_sha256,
            "appended_trace_receipt_identity")
    require(trace_receipt.get("ordinary_report_modified") is False,
            "trace_receipt_ordinary_modified")
    histories = telemetry.get("registered_runtime_histories")
    require(type(histories) is list and histories, "registered_runtime_histories_missing")
    all_history = [pid for item in histories for pid in item["worker_history"]]
    require(all(type(pid) is int and pid > 0 for pid in all_history), "worker_history_pid")
    require(len(set(all_history)) == len(all_history), "worker_pid_reuse_trace_ambiguity")
    expected = set(all_history) | set(report["worker_pids"]) | set(telemetry["appended_report"]["worker_pids"])
    actual = {row["pid"]: row for row in trace_audit["traces"]}
    require(expected <= set(actual), "all_ordinary_and_appended_pid_trace_coverage")
    require(trace_audit["unexpected_network_call_count"] == 0, "unexpected_network_call_in_original_traces")
    prefix = plan["analysis"]["trace_prefix"]
    for row in trace_receipt.get("traces", []):
        pid = row["pid"]
        require(pid in actual and row.get("path") == ".agent/"+prefix+"."+str(pid)
                and row.get("bytes") == actual[pid]["bytes"]
                and row.get("sha256") == actual[pid]["sha256"], "trace_receipt_raw_member_binding")
    require(set(trace_receipt.get("worker_pids", [])) ==
            set(telemetry["appended_report"]["worker_pids"]), "appended_trace_pid_receipt_binding")
    require({r["pid"] for r in trace_receipt.get("traces", [])} ==
            set(telemetry["appended_report"]["worker_pids"]), "appended_trace_rows_complete")
    return {"ordinary_original_nonobserver_fields_equal": True,
            "all_registered_worker_pids": sorted(expected),
            "trace_file_count": len(trace_audit["traces"]),
            "network_call_count": trace_audit["network_call_count"],
            "unexpected_network_call_count": trace_audit["unexpected_network_call_count"],
            "scope": "raw all-thread trace-byte audit, not a synthesized job conclusion"}


def analyze_cell(plan, plan_sha256, telemetry, telemetry_sha256, report, report_sha256,
                 before, before_sha256, trace_receipt, trace_audit, replay, slot):
    cell = plan["cells"][slot]
    expected_head = plan["original_commit"] if cell["ordinary_arm"] == "A" else plan["fast_commit"]
    require(cell["ordinal"] == slot, "plan_cell_ordinal")
    require(telemetry.get("schema") == TELEMETRY_SCHEMA, "telemetry_schema")
    identity = telemetry.get("identity", {})
    require(identity.get("head") == expected_head and identity.get("cell") == cell
            and identity.get("frozen_plan_sha256") == plan_sha256, "telemetry_identity")
    require(telemetry.get("errors") == [], "recorder_errors")
    require(telemetry.get("status") == "COMPLETE", "recorder_incomplete")
    expected_groups = {"ordinary_idle": 3, "ordinary_s05_busy": 3, "ordinary_s06_busy": 6,
                       "unscored_seed": 2, "appended_idle": 12, "appended_governed_busy": 12}
    require(Counter(c.get("group") for c in telemetry["callbacks"]) == Counter(expected_groups),
            "complete_callback_inventory")
    require(len({c["id"] for c in telemetry["callbacks"]}) == 38, "callback_id_inventory")
    require(telemetry.get("ordinary_callback_counts") ==
            {"ordinary_idle": 3, "ordinary_s05_busy": 3, "ordinary_s06_busy": 6},
            "ordinary_callback_counts")
    bindings = telemetry.get("ordinary_actual_row_binding")
    require(type(bindings) is list and len(bindings) == 12
            and all(b.get("actual_row_matches") is True for b in bindings),
            "ordinary_actual_row_binding")
    for group, official in (("ordinary_idle", report["deterministic_idle"]),
                            ("ordinary_s05_busy", report["deterministic_busy"]),
                            ("ordinary_s06_busy", report["s06"]["deterministic_busy"])):
        callbacks = [c for c in telemetry["callbacks"] if c["group"] == group]
        require(len(callbacks) == len(official), "ordinary_raw_row_count")
        for cb, original_row in zip(callbacks, official):
            validate_callback(cb)
            require(all(original_row.get(k) == v for k, v in cb["probe"].items()),
                    "ordinary_raw_row_binding_recomputed")
    for key, expected in plan["runtime_coordinates"].items():
        require(report.get(key) == expected, "ordinary_runtime_coordinate")
    appended = telemetry.get("appended_report", {})
    require(appended.get("status") == "COMPLETE", "appended_incomplete")
    passes = appended.get("passes", [])
    require(len(passes) == 2 and all(p.get("status") == "COMPLETE" for p in passes),
            "appended_passes")
    require(len({p.get("instance_id") for p in passes}) == 2, "fresh_instance_identities")
    for p in passes:
        require(p.get("unscored_seed", {}).get("preserved") is True
                and p["unscored_seed"].get("search_found") is True
                and p["unscored_seed"].get("product_dispatch_blocked") is True,
                "unscored_fixture_seed")
    idle = group_metrics(telemetry, "appended_idle", cell["micro_order"])
    busy = group_metrics(telemetry, "appended_governed_busy", cell["micro_order"])
    require(all(len(p["idle"]) == 6 and len(p["governed"]["samples"]) == 6
                and len(p["governed"]["deterministic_busy"]) == 6 for p in passes),
            "accepted_governed_shape")
    for ordinal, row in enumerate([r for p in passes for r in p["governed"]["samples"]]):
        require(row.get("phase") == ("cold" if ordinal % 2 == 0 else "warm"),
                "governed_cold_warm_order")
    for callback in telemetry["callbacks"]:
        if callback["group"] not in ("appended_idle", "appended_governed_busy"):
            continue
        method_identity = callback.get("method_identity", {})
        require(method_identity.get("source_sha256") == plan["atomic_source_sha256"][callback["arm"]],
                "actual_selected_method_source_identity")
        require(method_identity.get("method_ast_sha256") == plan["method_ast_sha256"][callback["arm"]],
                "actual_selected_method_ast_identity")
    activity = actual_governed_activity(telemetry, plan["runtime_coordinates"]["configuration_sha256"])
    network_coverage = network_and_original_boundaries(
        plan, telemetry, telemetry_sha256, report, before, before_sha256, trace_receipt, trace_audit)
    margins = margin_intervals(idle, busy)
    groups = (idle, busy)
    # An eliminated API is not sufficient proof; independent CPU/wall effects
    # and durable-work equivalence are required on every host and condition.
    cpu_effect = all(g["contrast_summaries"]["submit_through_process_cpu_ns"]["raw_median_A_minus_B_ns"] > 0
                     and g["contrast_summaries"]["submit_through_process_cpu_ns"]["empirical_median_effect_interval_ns"][0] > 0
                     for g in groups)
    wall_compatibility = all(g["contrast_summaries"]["capture_wall_ns"]["empirical_median_effect_interval_ns"][1] >= 0
                             for g in groups)
    api_effect = all(
        all(r["pool_api_administration"]["eligible_pool_count"] > 0
            and r["pool_api_administration"]["cross_pool_task_overlap_union_ns"] == 0
            for r in g["rows"] if r["arm"] == "A")
        and statistics.median([
            r["pool_api_administration"]["critical_api_administration_ns"]
            - g["recorder_empirical_envelope"]["wall_ns"]["high_ns_per_event"]
            * r["pool_api_administration"]["eligible_administration_event_count"]
            for r in g["rows"] if r["arm"] == "A"]) > 0
        and all(r["pool_api_administration"]["eligible_pool_count"] == 0
                for r in g["rows"] if r["arm"] == "B") for g in groups)
    io_equal = all(g["durable_counts_equal"] and g["durable_bytes_equal"] for g in groups)
    return {"slot": slot, "ordinary_arm": cell["ordinary_arm"], "micro_order": cell["micro_order"],
            "ordinary": ordinary_evidence(report, replay, expected_head, report_sha256,
                                           plan["analysis"]["accepted_evaluator_sha256"]),
            "idle": idle, "busy": busy, "actual_governed_activity": activity,
            "independent_all_phase_trace_coverage": network_coverage,
            "diagnostic_margin": margins,
            "margin_compatible_with_no_material_regression": margins["observed_compatibility_with_no_material_regression"],
            "observed_headroom_improvement": margins["observed_headroom_benefit"],
            "observed_spread_improvement": margins["observed_spread_benefit"],
            "cost_components": {"net_parent_cpu": cpu_effect, "wall_observed_compatibility": wall_compatibility,
                                "single_task_api_cost": api_effect, "durable_work_equal": io_equal},
            "avoidable_cost_demonstrated": cpu_effect and wall_compatibility and api_effect and io_equal}


def read_artifact(path, member_names, trace_prefix):
    raw_hash = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            raw_hash.update(chunk)
    selected = {}
    members = []
    trace_rows = []
    network_calls = unexpected_calls = 0
    total = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        require(len(infos) <= MAX_MEMBERS, "archive_member_limit")
        names = set()
        for info in infos:
            name = info.filename
            parts = PurePosixPath(name).parts
            require(name not in names and "\\" not in name and "\0" not in name
                    and not PurePosixPath(name).is_absolute() and ".." not in parts
                    and all(":" not in part for part in parts), "archive_path")
            names.add(name)
            require(not stat.S_ISLNK(info.external_attr >> 16), "archive_symlink")
            require(info.file_size <= MAX_MEMBER_BYTES, "archive_member_size")
            total += info.file_size
            require(total <= MAX_ARCHIVE_BYTES, "archive_total_size")
            h = hashlib.sha256()
            is_trace = name.startswith(trace_prefix+".") and name[len(trace_prefix)+1:].isdecimal()
            value = bytearray() if name in member_names.values() or is_trace else None
            with archive.open(info) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
                    if value is not None:
                        value.extend(chunk)
            members.append({"name": name, "bytes": info.file_size, "sha256": h.hexdigest(), "crc_read": True})
            if is_trace:
                text = bytes(value).decode("utf-8", errors="strict")
                calls = [line for line in text.splitlines()
                         if re.search(r"\b(socket|connect|sendto|sendmsg|sendmmsg)\(", line)]
                network_calls += len(calls)
                unexpected_calls += sum("= -1 EPERM" not in line for line in calls)
                trace_rows.append({"pid": int(name[len(trace_prefix)+1:]), "name": name,
                                   "bytes": info.file_size, "sha256": h.hexdigest()})
            if name in member_names.values():
                selected[name] = {"raw": bytes(value), "sha256": h.hexdigest()}
    require(set(selected) == set(member_names.values()), "artifact_required_members")
    return selected, {"path": str(path), "bytes": path.stat().st_size,
                      "sha256": raw_hash.hexdigest(), "members": members,
                      "raw_network_trace_audit": {"traces": trace_rows,
                          "network_call_count": network_calls,
                          "unexpected_network_call_count": unexpected_calls}}


def manifest_slots(manifest, plan, plan_sha256, workflow_head, run_id):
    require(manifest.get("schema") == "capture-cost-diagnostic-originals/v1",
            "originals_manifest_schema")
    require(manifest.get("workflow_head") == workflow_head and manifest.get("run_id") == run_id
            and manifest.get("run_attempt") == 1 and manifest.get("plan_sha256") == plan_sha256,
            "one_run_C_attempt1_frozen_plan_identity")
    require(manifest.get("source_a") == plan["original_commit"]
            and manifest.get("source_b") == plan["fast_commit"], "originals_source_A_B")
    require(manifest.get("slot_order") == ["A1", "B1", "B2", "A2"]
            and manifest.get("contract_errors") == []
            and manifest.get("missing_artifact_slots") == []
            and manifest.get("unexpected_attempt_originals") == [], "originals_contract_incomplete")
    run, attempt = manifest["run_original"], manifest["attempt_original"]
    require(run.get("id") == attempt.get("id") == run_id
            and run.get("head_sha") == attempt.get("head_sha") == workflow_head
            and run.get("event") == "workflow_dispatch"
            and run.get("run_attempt") == attempt.get("run_attempt") == 1
            and run.get("status") == attempt.get("status") == "completed",
            "original_run_attempt_identity_and_terminal_state")
    jobs, artifacts = manifest.get("jobs"), manifest.get("artifacts")
    require(type(jobs) is list and type(artifacts) is list and len(jobs) == len(artifacts) == 4,
            "exact_four_original_jobs_and_zips")
    result = []
    for ordinal, slot in enumerate(manifest["slot_order"]):
        selected_jobs = [j for j in jobs if j.get("ordinal") == ordinal and j.get("slot") == slot]
        selected_artifacts = [a for a in artifacts if a.get("ordinal") == ordinal and a.get("slot") == slot]
        require(len(selected_jobs) == len(selected_artifacts) == 1, "original_slot_duplicate_or_missing")
        job, artifact = selected_jobs[0], selected_artifacts[0]
        source = plan["original_commit"] if plan["cells"][ordinal]["ordinary_arm"] == "A" else plan["fast_commit"]
        require(job.get("head_sha") == workflow_head and job.get("expected_checkout_source") == source
                and artifact.get("workflow_head") == workflow_head
                and artifact.get("expected_checkout_source") == source
                and artifact.get("name") == plan["cells"][ordinal]["artifact_name"], "slot_source_or_artifact_identity")
        for key in ("listed_original", "direct_original"):
            original = job[key]
            require(original.get("id") == job["job_id"] and original.get("run_id") == run_id
                    and original.get("run_attempt") == 1 and original.get("head_sha") == workflow_head
                    and original.get("status") == "completed"
                    and type(original.get("conclusion")) is str, "original_job_identity_or_terminal_state")
        require(all(job["listed_original"].get(k) == job["direct_original"].get(k)
                    for k in ("status", "conclusion", "started_at", "completed_at")),
                "original_job_list_direct_incoherence")
        result.append((ordinal, job, artifact))
    return result


def source_integrity(plan, plan_sha256, selected, workflow_head, job, report, ordinal):
    """Original fixed-member bytes; API conclusions are checked independently."""
    names = plan["source_proof_members"]
    def raw(key):
        return selected[names[key]]["raw"]
    arm = plan["cells"][ordinal]["ordinary_arm"]
    head = plan["original_commit"] if arm == "A" else plan["fast_commit"]
    parent = plan["base_commit"] if arm == "A" else plan["original_commit"]
    require(raw("checkout_git").decode("ascii").splitlines() ==
            [head, parent, plan["source_trees"][arm]], "original_checkout_git_proof")
    workflow = raw("workflow_git").decode("ascii").splitlines()
    require(len(workflow) == 3 and workflow[:2] == [workflow_head, plan["fast_commit"]]
            and re.fullmatch("[0-9a-f]{40}", workflow[2]) is not None,
            "original_workflow_git_proof")
    require(digest(raw("frozen_plan")) == plan_sha256, "original_zip_frozen_plan")
    require(raw("source_status_after") == b"", "original_after_source_not_clean")
    require(raw("entry_exit") == raw("append_trace_exit") == b"0\n",
            "original_entry_or_append_trace_exit")
    observer = raw("observer_exit")
    require(observer in (b"0\n", b"1\n") and report.get("network") == "PASS",
            "original_observer_exit_or_network")
    require((observer == b"0\n") == (report.get("status") == "PASS"),
            "original_observer_exit_gate_status_disagreement")
    require(arm == "A" or observer == b"0\n", "B_original_observer_not_success")
    conclusion = job["direct_original"]["conclusion"]
    require(conclusion == ("success" if observer == b"0\n" else "failure"),
            "original_job_conclusion_not_expected_observer_outcome")
    step_name = "Complete ordinary real Linux path and declared appended diagnostic cohort"
    steps = job["direct_original"].get("steps", [])
    require(len([s for s in steps if s.get("name") == step_name]) == 1,
            "original_measurement_step_identity")
    setup_post_name = "Post Run actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405"
    require(len([s for s in steps if s.get("name") == setup_post_name]) == 1,
            "original_pinned_setup_python_post_identity")
    allowed_setup_post_skip = (arm == "A" and observer == b"1\n"
                               and report.get("status") == "FAIL" and conclusion == "failure")
    skipped_setup_post = []
    for step in steps:
        require(step.get("status") == "completed", "original_job_step_not_completed")
        if (step.get("name") == setup_post_name and step.get("conclusion") == "skipped"
                and allowed_setup_post_skip):
            # This pinned action's conditional post-hook may skip after failure.
            # Its executable setup and every other nonmeasurement step must succeed.
            skipped_setup_post.append(setup_post_name)
            continue
        require(step.get("conclusion") ==
                (conclusion if step.get("name") == step_name else "success"),
                "other_original_job_step_not_success")
    return {"source_head": head, "source_parent": parent, "source_tree": plan["source_trees"][arm],
            "after_source_status_bytes": 0, "entry_exit": 0, "append_trace_exit": 0,
            "observer_exit": int(observer), "actual_job_conclusion": conclusion,
            "exact_conditional_setup_python_post_skips": skipped_setup_post,
            "fixed_member_sha256": {key: selected[name]["sha256"] for key, name in names.items()},
            "scope": "original pinned workflow Git/status/exit evidence plus actual direct-job conclusion"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--originals-manifest", type=Path, required=True,
                        help="Accepted operator's raw one-run-C/attempt1/four-slot original metadata manifest.")
    parser.add_argument("--workflow-head", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--ordinary-replays", type=Path, required=True,
                        help="Accepted operator's independent raw-report replay results, keyed by slot.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"schema": "independent-capture-single-task-analysis/v1",
              "authority": "NONE_DIAGNOSTIC_NOT_QUALIFICATION", "state": "NOT_DEMONSTRATED",
              "cells": [], "errors": [], "original_artifacts": []}
    try:
        raw = args.plan.read_bytes()
        require(digest(raw) == args.plan_sha256, "frozen_plan_sha256")
        plan = load_json(raw)
        require(plan.get("schema") == PLAN_SCHEMA and plan.get("status") == "FROZEN", "plan_not_frozen")
        require(plan["analysis"]["analyzer_sha256"] == digest(Path(__file__).read_bytes()), "analyzer_pin")
        require(len(plan["cells"]) == 4, "four_original_slots_required")
        manifest_raw = args.originals_manifest.read_bytes()
        manifest = load_json(manifest_raw)
        slots = manifest_slots(manifest, plan, args.plan_sha256, args.workflow_head, args.run_id)
        result["selection_manifest"] = {"path": str(args.originals_manifest), "bytes": len(manifest_raw),
                                         "sha256": digest(manifest_raw), "workflow_head": args.workflow_head,
                                         "run_id": args.run_id, "run_attempt": 1}
        replays = load_json(args.ordinary_replays.read_bytes())
        for slot, job, artifact in slots:
            try:
                path = Path(artifact["zip_path"])
                members = dict(plan["artifact_members"])
                members.update(plan["source_proof_members"])
                selected, inventory = read_artifact(path, members, plan["analysis"]["trace_prefix"])
                require(inventory["bytes"] == artifact.get("expected_bytes")
                        and inventory["sha256"] == artifact.get("expected_zip_sha256"),
                        "original_zip_api_size_or_digest_binding")
                inventory["slot"] = slot
                inventory["artifact_id"] = artifact["artifact_id"]
                inventory["original_job_id"] = job["job_id"]
                inventory["original_job_conclusion"] = job["direct_original"]["conclusion"]
                result["original_artifacts"].append(inventory)
                t = selected[plan["artifact_members"]["telemetry"]]
                r = selected[plan["artifact_members"]["ordinary"]]
                before = selected[plan["artifact_members"]["ordinary_before_network"]]
                trace_receipt = selected[plan["artifact_members"]["append_worker_trace_integrity"]]
                telemetry = load_json(t["raw"])
                report = load_json(r["raw"])
                source = source_integrity(plan, args.plan_sha256, selected,
                                          args.workflow_head, job, report, slot)
                require(telemetry["identity"].get("workflow_head") == args.workflow_head
                        and telemetry["identity"].get("workflow_run_id") == str(args.run_id)
                        and telemetry["identity"].get("workflow_run_attempt") == "1",
                        "telemetry_workflow_run_attempt_binding")
                result["cells"].append(analyze_cell(plan, args.plan_sha256, telemetry, t["sha256"],
                                                  report, r["sha256"],
                                                  load_json(before["raw"]), before["sha256"],
                                                  load_json(trace_receipt["raw"]), inventory["raw_network_trace_audit"],
                                                  replays.get(str(slot)), slot))
                result["cells"][-1]["independent_source_integrity"] = source
            except Exception as exc:
                result["errors"].append({"slot": slot, "code": str(exc) if isinstance(exc, Unsupported)
                                          else type(exc).__name__})
        if len(result["cells"]) == 4 and not result["errors"]:
            cells = result["cells"]
            result["all_four_cost_proofs"] = all(c["avoidable_cost_demonstrated"] for c in cells)
            result["all_four_margin_observed_compatibility"] = all(c["margin_compatible_with_no_material_regression"] for c in cells)
            result["all_four_observed_headroom_improvement"] = all(c["observed_headroom_improvement"] for c in cells)
            result["all_four_observed_spread_improvement"] = all(c["observed_spread_improvement"] for c in cells)
            result["both_B_ordinary_independent_28_pass"] = all(c["ordinary"]["all_28_pass"] for c in cells
                                                              if c["ordinary_arm"] == "B")
            result["both_B_actual_jobs_success"] = all(
                c["independent_source_integrity"]["actual_job_conclusion"] == "success"
                for c in cells if c["ordinary_arm"] == "B")
            result["state"] = "COMPLETE_DIAGNOSTIC_COMPARISON"
            result["clean_candidate_preparation_supported"] = (
                result["all_four_cost_proofs"] and result["all_four_margin_observed_compatibility"]
                and result["both_B_ordinary_independent_28_pass"] and result["both_B_actual_jobs_success"])
    except Exception as exc:
        result["errors"].append({"code": str(exc) if isinstance(exc, Unsupported) else type(exc).__name__})
    result["qualification"] = "NOT_QUALIFIED_REQUIRES_CLEAN_EXACT_HEAD_ALL_GATES"
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return 0 if result["state"] == "COMPLETE_DIAGNOSTIC_COMPARISON" else 2


if __name__ == "__main__":
    raise SystemExit(main())
