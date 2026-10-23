"""DRAFT stdlib-only C3 sparse Capture and batched atomic-component analysis.

No candidate import or execution, no qualification authority, no ordinary C3
report. Preserve C1's four failures and formal refusals. Execute only after the
host selects exact source/input pins in the credential-free offline laboratory.
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


MAX_MEMBER_BYTES = 128 * 1024 * 1024


MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


MAX_MEMBERS = 4096


OPERATION_LABELS = {
    "os.fsync": "fsync", "os.replace": "replace", "os.rename": "rename",
    "atomic.payload_write_flush_fsync": "write_journal_payload",
    "store.atomic_bytes": "store_atomic_bytes",
}


CALIBRATION_PAIRS = 256
BOUNDARY_RECIPE = "wall_process_body_process_wall/v1"
MODE = "SPARSE_COMPONENT_V3"
REGIME = "SPARSE_CAPTURE_AND_ATOMIC_COMPONENT_WITH_SEPARATE_C1_CONTROL"

EMAIL_PROFILE = {
    "schema_version": 1, "key": "email-intake", "kind": "email.intake",
    "owner_id_pattern": r"job_[0-9a-f]{32}\Z",
    "limits": {"max_entries": 4096, "max_entry_bytes": 64*1024*1024,
               "max_candidate_bytes": 256*1024*1024,
               "max_preimage_bytes": 128*1024*1024,
               "max_journal_payload_bytes": 384*1024*1024},
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


def seconds_ns(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "invalid_seconds")
    return round(value * 1_000_000_000)


def boundary_measurement(boundary):
    """One identical sparse recipe, never a per-operation recorder envelope."""
    require(type(boundary) is dict and boundary.get("recipe") == BOUNDARY_RECIPE,
            "sparse_boundary_recipe")
    first, last = boundary["before"], boundary["after"]
    start = integer(first["monotonic_ns"], "sparse_wall_before")
    stop = integer(last["monotonic_ns"], "sparse_wall_after")
    cpu0 = integer(first["process_cpu_ns"], "sparse_cpu_before")
    cpu1 = integer(last["process_cpu_ns"], "sparse_cpu_after")
    require(start <= stop and cpu0 <= cpu1, "sparse_boundary_order")
    for name, raw_name in (("before", "raw_wall_before_seconds"),
                           ("after", "raw_wall_after_seconds")):
        value = boundary[raw_name]
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                "sparse_raw_float_wall")
        require(round(value * 1_000_000_000) == boundary[name]["monotonic_ns"],
                "sparse_raw_float_ns_binding")
    require(boundary["raw_wall_after_seconds"] >= boundary["raw_wall_before_seconds"],
            "sparse_raw_wall_decreased")
    return {"process_cpu_ns": cpu1-cpu0,
            "wall_ns": seconds_ns(boundary["raw_wall_after_seconds"]
                                  - boundary["raw_wall_before_seconds"]),
            "recorded_span_count": 1,
            "boundary_start_ns": start, "boundary_end_ns": stop,
            "scope": "net parent-process CPU; includes transient pool and concurrent parent threads",
            "recipe": BOUNDARY_RECIPE}


def capture_process_cpu(callback):
    return boundary_measurement(callback["capture_boundary"])


def validate_callback(callback):
    require(callback.get("arm") in ("A", "B"), "callback_arm")
    require("exception_type" not in callback, "callback_original_exception")
    probe = callback.get("probe")
    require(type(probe) is dict, "callback_probe_missing")
    for name in ("preserved", "search_found", "product_dispatch_blocked"):
        require(probe.get(name) is True, "callback_semantic_outcome")
    require(callback.get("spans", []) == []
            and callback.get("inner_operation_wrappers_installed") is False,
            "primary_inner_instrumentation_forbidden")
    boundary = capture_process_cpu(callback)
    require(boundary["wall_ns"] == seconds_ns(probe["capture_seconds"]),
            "sparse_original_capture_wall_binding")
    return probe


def calibration_envelope(telemetry):
    """All 512 equal-boundary no-ops, no span-count extrapolation or subtraction."""
    cal = telemetry.get("calibration")
    require(type(cal) is dict
            and cal.get("schema") == "capture-cost-sparse-boundary-calibration/v1"
            and cal.get("complete") is True
            and cal.get("kind") == "SPARSE_BOUNDARY_NOOP_NOT_PRODUCT_WORK"
            and cal.get("recipe") == BOUNDARY_RECIPE
            and cal.get("pairs") == CALIBRATION_PAIRS, "sparse_calibration_contract")
    samples = cal.get("samples")
    require(type(samples) is list and len(samples) == CALIBRATION_PAIRS,
            "sparse_calibration_count")
    values = {"wall_ns": [], "process_cpu_ns": []}
    previous_stop = None
    for index, sample in enumerate(samples):
        require(sample.get("pair") == index and sample.get("order") ==
                (["A", "B"] if index % 2 == 0 else ["B", "A"]),
                "sparse_calibration_fixed_pair_order")
        for arm in sample["order"]:
            row = sample["patterns"][arm]
            require(row.get("outcome") == "NOOP_COMPLETE"
                    and "exception_type" not in row
                    and row.get("observation_recipes") == 1,
                    "sparse_calibration_complete_recipe")
            measured = boundary_measurement(row["boundary"])
            require(previous_stop is None or previous_stop <= measured["boundary_start_ns"],
                    "sparse_calibration_actual_order")
            previous_stop = measured["boundary_end_ns"]
            for field in values:
                values[field].append(measured[field])
    result = {}
    for field, clock in (("wall_ns", "monotonic"), ("process_cpu_ns", "process_time")):
        resolution = cal["clock_resolution_ns"][clock]
        require(type(resolution) in (int, float) and math.isfinite(resolution)
                and resolution >= 0, "sparse_calibration_resolution")
        result[field] = {"low_ns_per_event": max(0, min(values[field])-resolution),
                         "high_ns_per_event": max(values[field])+resolution,
                         "all_512_raw_unit_costs": values[field], "resolution_ns": resolution}
    result["scope"] = ("empirical identical one-boundary recipe reference; never a statistical "
                       "confidence interval or universal tracer/scheduler bound")
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


def component_batch_evidence(batch, fixture, *, measured=True):
    require(type(batch) is dict and batch.get("status") == "COMPLETE"
            and batch.get("expected_transactions") == 32
            and batch.get("completed_transactions") == 32
            and batch.get("started_transaction_ordinals") == list(range(32))
            and batch.get("completed_transaction_ordinals") == list(range(32)),
            "component_complete_fixed_batch32")
    require(batch.get("profile") == fixture["profile"]
            and batch.get("payload_sha256") == fixture["payload_sha256"],
            "component_profile_payload_identity")
    require(type(batch.get("fixture_id")) is str and batch["fixture_id"],
            "component_fixture_identity")
    targets = batch.get("targets")
    require(type(targets) is list and len(targets) == 32
            and [t.get("ordinal") for t in targets] == list(range(32)),
            "component_target_ordinal_coverage")
    for target in targets:
        relative = target.get("relative")
        require(type(relative) is str and relative and "\\" not in relative
                and not PurePosixPath(relative).is_absolute()
                and str(PurePosixPath(relative)) == relative
                and all(part not in (".", "..") for part in PurePosixPath(relative).parts),
                "component_target_relative_path")
        require(re.fullmatch(r"job_[0-9a-f]{32}", target.get("owner_id", "")) is not None
                and target.get("bytes") == fixture["payload_bytes"] == 4096
                and target.get("sha256") == fixture["payload_sha256"],
                "component_target_public_bytes_owner")
    require(len({t["relative"] for t in targets}) == len({t["owner_id"] for t in targets}) == 32,
            "component_distinct_batch_targets_owners")
    checks = batch.get("postchecks", {})
    observed = checks.get("observed_targets")
    require(checks.get("expected_target_count") in range(32, 385, 32)
            and type(observed) is list and len(observed) == checks["expected_target_count"]
            and checks.get("prior_targets_unchanged") is True
            and checks.get("journal_entries") == [] and checks.get("unexpected_paths") == [],
            "component_postcheck_inventory_complete")
    require(all(t.get("bytes") == 4096 and t.get("sha256") == fixture["payload_sha256"]
                and type(t.get("relative")) is str for t in observed)
            and len({t["relative"] for t in observed}) == len(observed),
            "component_postcheck_all_hashes")
    actual = {t["relative"]: (t["bytes"], t["sha256"]) for t in observed}
    require(all(actual.get(t["relative"]) == (t["bytes"], t["sha256"]) for t in targets),
            "component_new_targets_hashes_bound")
    require(batch.get("cleanup", {}).get("status") == "COMPLETE"
            and batch["cleanup"].get("journal_empty") is True,
            "component_journal_cleanup")
    if measured:
        timing = boundary_measurement(batch["boundary"])
    else:
        require(batch.get("boundary") is None, "unscored_control_must_not_invent_timing")
        timing = None
    return {"fixture_id": batch["fixture_id"], "targets": targets,
            "observed_targets": observed, "expected_target_count": checks["expected_target_count"],
            "boundary": timing, "transactions": 32,
            "scope": "32 complete generic production Atomic commits; no Capture domain record claim"}


def group_metrics(telemetry, group, order, fixture, *, component=False):
    callbacks = [c for c in telemetry["callbacks"] if c["group"] == group]
    require(len(callbacks) == 12, "micro_callback_count")
    callbacks.sort(key=lambda c: c["treatment_ordinal"])
    require([c["treatment_ordinal"] for c in callbacks] == list(range(12)), "micro_ordinal_coverage")
    require("".join(c["arm"] for c in callbacks) == order * 3, "micro_treatment_order")
    values = []
    for index, callback in enumerate(callbacks):
        probe = validate_callback(callback)
        require(callback["section_context"].get("micro_pass") == index // 6,
                "micro_instance_assignment")
        require(callback["component_batch"].get("arm") == callback["arm"]
                and callback["component_batch"].get("method_identity") == callback["method_identity"],
                "component_selected_arm_and_methods_match_callback")
        batch = component_batch_evidence(callback["component_batch"], fixture)
        require(capture_process_cpu(callback)["boundary_end_ns"] <= batch["boundary"]["boundary_start_ns"],
                "capture_must_precede_component_batch")
        cpu = batch["boundary"] if component else capture_process_cpu(callback)
        wall = cpu["wall_ns"] if component else seconds_ns(probe["capture_seconds"])
        values.append({"id": callback["id"], "ordinal": index, "arm": callback["arm"],
                       "capture_wall_ns": wall,
                       "raw_capture_seconds": (None if component else probe["capture_seconds"]),
                       "submit_through_process_cpu_ns": cpu["process_cpu_ns"],
                       "capture_cpu_boundary": cpu, "capture_event_count": 1,
                       "transactions": 32 if component else None,
                       "component_evidence": batch if component else None})
    envelope = calibration_envelope(telemetry)
    contrasts = {field: cycle_contrasts(values, field, envelope[
                     "wall_ns" if field == "capture_wall_ns" else "process_cpu_ns"])
                 for field in ("capture_wall_ns", "submit_through_process_cpu_ns")}
    summaries = {field: {
        "raw_median_A_minus_B_ns": statistics.median(v["raw_A_minus_B_ns"] for v in cycles),
        "empirical_median_effect_interval_ns": [statistics.median(v["empirical_effect_interval_ns"][i]
                                                                  for v in cycles) for i in (0, 1)]}
                for field, cycles in contrasts.items()}
    if component:
        for summary in summaries.values():
            summary["raw_median_A_minus_B_ns_per_transaction"] = summary["raw_median_A_minus_B_ns"] / 32
            summary["empirical_median_effect_interval_ns_per_transaction"] = [
                v/32 for v in summary["empirical_median_effect_interval_ns"]]
    return {"group": group, "measurement": "ATOMIC_BATCH32" if component else "FULL_CAPTURE",
            "rows": values, "recorder_empirical_envelope": envelope,
            "cycle_contrasts_A_minus_B": contrasts, "contrast_summaries": summaries,
            "scope": ("net parent CPU/wall across complete32; concurrent parent threads included"
                      if component else "Capture-only CPU and original Capture wall; A/B descriptive")}


def component_inventory(telemetry, fixture):
    """Independently compare every cumulative target inventory and final cleanup."""
    fixtures, all_owner_ids, fixture_ids = [], set(), set()
    for pass_index in range(2):
        callbacks = [c for c in telemetry["callbacks"]
                     if c["group"] in ("appended_idle", "appended_governed_busy")
                     and c["section_context"].get("micro_pass") == pass_index]
        callbacks.sort(key=lambda c: (c["group"] == "appended_governed_busy", c["treatment_ordinal"]))
        require(len(callbacks) == 12, "component_pass_twelve_batches")
        accumulated, selected_id = {}, None
        for index, callback in enumerate(callbacks):
            evidence = component_batch_evidence(callback["component_batch"], fixture)
            if selected_id is None:
                selected_id = evidence["fixture_id"]
            require(evidence["fixture_id"] == selected_id, "component_one_store_per_pass")
            for target in evidence["targets"]:
                require(target["relative"] not in accumulated and target["owner_id"] not in all_owner_ids,
                        "component_target_or_owner_reused")
                accumulated[target["relative"]] = (target["bytes"], target["sha256"])
                all_owner_ids.add(target["owner_id"])
            actual = {t["relative"]: (t["bytes"], t["sha256"]) for t in evidence["observed_targets"]}
            require(actual == accumulated and evidence["expected_target_count"] == 32*(index+1),
                    "component_exact_cumulative_inventory")
        require(selected_id not in fixture_ids, "component_store_reused_between_passes")
        fixture_ids.add(selected_id)
        cleanups = [r for r in telemetry.get("component_fixture_cleanup", [])
                    if r.get("micro_pass") == pass_index and r.get("fixture_id") == selected_id]
        require(len(cleanups) == 1, "component_final_fixture_cleanup_identity")
        cleanup = cleanups[0]
        final = cleanup.get("final_observed_targets", [])
        require(cleanup.get("status") == "COMPLETE" and cleanup.get("removed") is True
                and cleanup.get("final_expected_target_count") == len(final) == 384
                and len({t.get("relative") for t in final}) == 384
                and {t["relative"]: (t["bytes"], t["sha256"]) for t in final} == accumulated,
                "component_final_all_targets_and_disposal")
        fixtures.append({"micro_pass": pass_index, "fixture_id": selected_id,
                         "targets": 384, "postchecks": "EXACT_ALL_TARGET_HASHES",
                         "cleanup": "COMPLETE_REMOVED"})
    require(len(telemetry.get("component_fixture_cleanup", [])) == 2
            and len(all_owner_ids) == 768, "component_exact_768_transactions_two_fixtures")
    return {"complete": True, "measured_transactions": 768, "fixtures": fixtures}


def control_metrics(telemetry, fixture, plan):
    controls = telemetry.get("component_controls", {})
    require(controls.get("status") == "COMPLETE"
            and controls.get("scope") == "UNSCORED_SELECTED_PYTHON_DURABLE_OPERATIONS",
            "unscored_control_scope")
    batches = controls.get("batches")
    require(type(batches) is list and len(batches) == 2
            and [b.get("arm") for b in batches] == ["A", "B"], "unscored_control_fixed_arm_inventory")
    result, arm_counts, arm_bytes = [], {}, {}
    for batch in batches:
        method = batch.get("method_identity", {})
        require(method.get("source_sha256") == plan["atomic_source_sha256"][batch["arm"]]
                and method.get("method_ast_sha256") == plan["method_ast_sha256"][batch["arm"]],
                "control_actual_three_method_identity")
        evidence = component_batch_evidence(batch, fixture, measured=False)
        require(evidence["expected_target_count"] == 32, "control_fresh_fixture")
        require(batch.get("cleanup", {}).get("removed") is True, "control_fixture_disposal")
        counts, byte_counts = Counter(), Counter()
        operations = batch.get("operations")
        require(type(operations) is list and operations, "unscored_selected_operation_inventory")
        marker_states = Counter()
        for row in operations:
            label = row.get("label")
            require(label in OPERATION_LABELS and row.get("kind") == OPERATION_LABELS[label]
                    and type(row.get("role")) is str and row["role"]
                    and row.get("outcome") == "OK", "unscored_operation_schema_outcome")
            key = label+":"+row["role"]
            counts[key] += 1
            if label in ("atomic.payload_write_flush_fsync", "store.atomic_bytes"):
                byte_counts[key] += integer(row.get("bytes"), "unscored_operation_bytes")
            if label == "store.atomic_bytes" and row["role"] == "manifest_marker":
                require(row.get("marker_status") in ("prepared", "committed"), "control_marker_state")
                marker_states[row["marker_status"]] += 1
        require(sum(v for k,v in counts.items() if k.startswith("os.fsync:")) == 9*32
                and sum(v for k,v in counts.items() if k.startswith("os.replace:")) == 3*32
                and not any(k.startswith("os.rename:") for k in counts)
                and marker_states == Counter({"prepared": 32, "committed": 32}),
                "control_complete_fsync_replace_marker_recipe")
        pools = batch.get("pools")
        require(type(pools) is list and len(pools) == (64 if batch["arm"] == "A" else 0),
                "control_removed_single_task_pool_lifecycles")
        require(all(p.get("tasks_submitted") == p.get("tasks_completed") == 1
                    and p.get("shutdown_wait") is True and p.get("threads_alive_after") == 0
                    and p.get("function") in ("_write_journal_payload", "_fsync_directory")
                    for p in pools), "control_one_task_pools_all_joined")
        if batch["arm"] == "A":
            require(Counter(p["function"] for p in pools) ==
                    Counter({"_write_journal_payload": 32, "_fsync_directory": 32}),
                    "control_one_prepare_one_publish_task_per_transaction")
        arm_counts[batch["arm"]], arm_bytes[batch["arm"]] = counts, byte_counts
        result.append({"arm": batch["arm"], "transactions": 32, "pools": pools,
                       "selected_counts": dict(counts), "selected_bytes": dict(byte_counts),
                       "marker_states": dict(marker_states), "fixture_id": evidence["fixture_id"]})
    require(batches[0]["fixture_id"] != batches[1]["fixture_id"], "control_fixtures_not_fresh")
    require(arm_counts["A"] == arm_counts["B"] and arm_bytes["A"] == arm_bytes["B"],
            "unscored_selected_durable_work_mismatch")
    return {"complete": True, "selected_durable_counts_equal": True,
            "selected_durable_bytes_equal": True, "batches": result,
            "scope": "unscored selected Python operations only; no timing or complete kernel I/O claim"}


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


def literal_fresh_margins(idle, busy):
    """Preserve the original float comparison; no ns-rounding slack at zero."""
    result = {}
    for arm in ("A", "B"):
        baseline = [r["raw_capture_seconds"] for r in idle["rows"] if r["arm"] == arm]
        loaded = [r["raw_capture_seconds"] for r in busy["rows"] if r["arm"] == arm]
        require(len(baseline) == len(loaded) == 6, "literal_margin_exact_six_rows")
        require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0
                    for v in baseline+loaded), "literal_margin_original_raw_seconds")
        limit = min(1, 2*statistics.median(baseline)+0.1)
        result[arm] = {"raw_margin_seconds": max(loaded)-limit,
                       "limit_seconds": limit, "maximum_busy_seconds": max(loaded),
                       "at_most_zero": max(loaded)-limit <= 0}
    return result


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
        require(type(call.get("started_ns")) is int and type(call.get("completed_ns")) is int
                and call["started_ns"] <= boundary["boundary_start_ns"]
                <= boundary["boundary_end_ns"] <= call["completed_ns"],
                "governed_callback_inside_actual_native_call")
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


def original_execution_identity(manifest, workflow_head, run_id):
    """Original run/attempt metadata is authority; no conclusion from steps/jobs."""
    for name in ("run_original", "attempt_original"):
        row = manifest[name]
        require(row.get("id") == run_id and row.get("head_sha") == workflow_head
                and row.get("run_attempt") == 1 and row.get("workflow_id") == 374188063
                and row.get("event") == "workflow_dispatch"
                and row.get("path") == ".github/workflows/ai-runtime-candidate.yml"
                and row.get("status") == "completed" and row.get("conclusion") == "success",
                "original_run_attempt_actual_success_identity")
        require(row.get("actor", {}).get("id") == 25499689
                and row.get("triggering_actor", {}).get("id") == 25499689
                and row.get("repository", {}).get("id") == 1343746770,
                "original_run_attempt_actor_repository_identity")
    return {"run_id": run_id, "run_attempt": 1, "workflow_head": workflow_head,
            "workflow_id": 374188063, "repository_id": 1343746770,
            "actor_id": 25499689, "triggering_actor_id": 25499689,
            "event": "workflow_dispatch", "status": "completed", "conclusion": "success",
            "scope": "both original raw run and attempt agree; never derived from job steps"}


def manifest_slots(manifest, plan, plan_sha256, workflow_head, run_id):
    original_execution_identity(manifest, workflow_head, run_id)
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


TELEMETRY_SCHEMA = "capture-cost-temporary-component-telemetry/v1"
PLAN_SCHEMA = "capture-single-task-experiment/v3"
CONTROL_SCHEMA = "capture-cost-C1-ordinary-control/v1"


def c1_controls(plan, raw, execution_raw, host_launch_raw):
    """Host-pinned external CONTROL_ONLY dataset, never candidate authority."""
    expected = plan['c1_control_dataset']
    require(digest(raw) == expected['bundle_sha256'], 'C1_control_bundle_pin')
    require(digest(host_launch_raw) == expected['host_launch_sha256'], 'C1_actual_host_launch_pin')
    bundle = load_json(raw)
    require(digest(execution_raw) == expected['execution_receipt_sha256'], 'C1_control_execution_pin')
    execution = load_json(execution_raw)
    require(execution.get('schema') == 'capture-cost-C1-ordinary-control-execution/v1'
            and execution.get('scope') == 'CONTROL_ONLY_NO_CORRECTION_SUPPORT'
            and execution.get('result') == 'FULL_ORDINARY_LOAD_REPLAYED_CONTROL_ONLY'
            and execution.get('helper_sha256') == expected['operator_helper_sha256']
            and execution.get('errors') == []
            and execution['control_bundle']['sha256'] == expected['bundle_sha256'],
            'C1_actual_control_execution_identity')
    environment = execution['environment']
    require(environment.get('network') == 'REFUSED'
            and environment.get('no_operator_home_credentials_or_socket') is True
            and environment.get('readonly_cpu_and_inputs') is True,
            'C1_actual_control_execution_environment')
    require(bundle.get('schema') == CONTROL_SCHEMA
            and bundle.get('result') == 'FULL_ORDINARY_LOAD_REPLAYED_CONTROL_ONLY'
            and bundle.get('scope') == 'CONTROL_ONLY_NO_CORRECTION_SUPPORT'
            and bundle.get('qualification') == 'NOT_GRANTED'
            and bundle.get('correction_support') == 'NOT_GRANTED', 'C1_control_scope')
    require(bundle.get('workflow_head') == 'b00525333940baae5bb1698d77f5d865e46c01b0'
            and bundle.get('run_id') == 39884284376 and bundle.get('run_attempt') == 1,
            'C1_original_workflow_identity')
    require(bundle['original_manifest']['sha256'] ==
            '6955c9e87ac05a281584a387314597f809c92063f4298a6c1236d4fad5a37419'
            and bundle['plan']['sha256'] ==
            '17c27d65416645d1c8210fa0a1a13db47a3b4ea1ca1694a4387bbd6fdde98be6',
            'C1_original_manifest_and_plan')
    accepted = bundle['accepted']
    require(accepted.get('source') == '210512725f1826861585278214d21fd31093e123'
            and accepted.get('evaluator_sha256') == plan['analysis']['accepted_evaluator_sha256']
            and accepted.get('observer_sha256') == plan['analysis']['accepted_observer_sha256']
            and bundle.get('operator_helper_sha256') == expected['operator_helper_sha256'],
            'C1_accepted_replay_source')
    require(bundle['formal_replay'].get('result') == 'REFUSED'
            and bundle['formal_analysis'].get('state') == 'NOT_DEMONSTRATED'
            and bundle['formal_replay']['reference']['sha256'] == expected['formal_replay_sha256']
            and bundle['formal_analysis']['reference']['sha256'] == expected['formal_analysis_sha256'],
            'C1_formal_failures_not_preserved')
    require(bundle.get('all_four_full_ordinary_controls_verified') is True,
            'C1_full_control_dataset_incomplete')
    require(bundle.get('errors') == [] and bundle.get('all_four_actual_jobs_failed') is True
            and bundle.get('actual_workflow_conclusion') == 'failure', 'C1_original_failures_or_errors')
    slots = bundle.get('slots')
    require(type(slots) is list and len(slots) == 4, 'C1_control_four_slots')
    source_a = '4b1046428c31b1470fbb8a67a2673cb650d05679'
    source_b = '162c225b96fd88237c58c93327a231db26b14766'
    summary = []
    coverage = {'three_cold': 3, 'samples': 60, 'idle': 3, 's05_busy': 3,
                's06_samples': 6, 's06_cancellations': 2, 's07_samples': 2,
                's08_samples': 32, 'iudicium_samples': 2, 'network_complete': True}
    for ordinal, name in enumerate(('A1', 'B1', 'B2', 'A2')):
        found = [s for s in slots if s.get('ordinal') == ordinal and s.get('slot') == name]
        require(len(found) == 1, 'C1_control_slot_identity')
        row = found[0]
        require(row.get('source_head') == (source_a if ordinal in (0, 3) else source_b)
                and row.get('actual_job_conclusion') == 'failure'
                and row.get('entry_exit') == 42 and row.get('append_trace_exit') == 1
                and row.get('observer_exit') == 0, 'C1_actual_failure_or_exit_identity')
        original, recomputed = row['original_gate_map'], row['recomputed_gate_map']
        require(set(original) == GATES and recomputed == original
                and all(value == 'PASS' for value in original.values()), 'C1_original_control_gates')
        require(row.get('full_gate_and_status_replay_equal') is True
                and row.get('network_replay_equal') is True
                and row.get('all_nonperformance_controls_pass') is True,
                'C1_control_network_or_semantics')
        require(all(row['full_previous_load_coverage'].get(key) == value
                    for key, value in coverage.items()), 'C1_full_previous_load_coverage')
        guard = row['insufficient_guard']
        require(guard.get('status') == 'NOT_RUN_INSUFFICIENT_REMAINING_BUDGET'
                and guard.get('required_seconds') == 330
                and type(guard.get('actual_remaining_seconds')) in (float, int)
                and 0 <= guard['actual_remaining_seconds'] < 330, 'C1_original_guard_reason')
        summary.append({'slot': name, 'actual_job_conclusion': 'failure',
                        'ordinary_raw_and_replayed_28_pass': True,
                        'scope': 'CONTROL_ONLY_NO_CORRECTION_SUPPORT'})
    return {'schema': CONTROL_SCHEMA, 'bundle_sha256': digest(raw),
            'execution_receipt_sha256': digest(execution_raw),
            'actual_host_launch_sha256': digest(host_launch_raw),
            'original_four_actual_jobs': 'FAILURE_PRESERVED', 'slots': summary,
            'qualification': 'NOT_GRANTED', 'correction_support': 'NOT_GRANTED'}


def original_audit(plan, plan_sha256, raw, expected_sha256, manifest_raw, workflow_head, run_id):
    require(digest(raw) == expected_sha256, 'C3_host_selected_original_audit_hash')
    audit = load_json(raw)
    require(audit.get('schema') == 'capture-cost-C3-original-audit/v1'
            and audit.get('result') == 'ORIGINAL_METADATA_AND_BYTES_VERIFIED_NOT_QUALIFIED'
            and audit.get('scope') == 'METADATA_AND_BYTES_ONLY'
            and audit.get('qualification') == audit.get('correction_support') == 'NOT_GRANTED'
            and audit.get('helper_sha256') == plan['analysis']['original_auditor_sha256']
            and audit.get('dependency_replayer_sha256') ==
            '915e77e6f228c7d1a4b794688115328e316945c4f2c0db027059f02ea8609952',
            'C3_original_audit_scope_source')
    require(audit.get('workflow_head') == workflow_head and audit.get('run_id') == run_id
            and audit.get('run_attempt') == 1 and audit.get('errors') == []
            and audit.get('source_identities_verified') is True
            and audit.get('all_four_original_slots_verified') is True
            and audit['plan']['sha256'] == plan_sha256
            and audit['original_manifest']['sha256'] == digest(manifest_raw),
            'C3_original_audit_input_identity')
    environment = audit['environment']
    require(environment.get('network') == 'REFUSED'
            and environment.get('readonly_cpu_and_inputs') is True
            and environment.get('no_operator_home_credentials_or_socket') is True,
            'C3_original_audit_environment')
    require(type(audit.get('slots')) is list and len(audit['slots']) == 4,
            'C3_original_audit_four_slots')
    return audit


def entry_cleanup_evidence(receipt, telemetry_sha256):
    """Actual pinned entry sidecar has no invented schema or identity fields."""
    require(receipt.get("authority") == "NONE_DIAGNOSTIC_NOT_QUALIFICATION"
            and receipt.get("mode") == MODE and "ordinary_report" in receipt and receipt["ordinary_report"] is None
            and type(receipt.get("diagnostic_returncode")) is int
            and receipt["diagnostic_returncode"] == 0
            and "primary_exception_type" in receipt and receipt["primary_exception_type"] is None
            and receipt.get("cleanup_errors") == []
            and receipt.get("cohort_cleanup_completed") is True
            and receipt.get("cleanup_scope") == "VERIFIED_ALREADY_COMPLETED_WITHIN_COHORT"
            and receipt.get("appended_status") == "COMPLETE",
            "actual_entry_cleanup_incomplete_or_emergency")
    original = receipt.get("telemetry", {})
    require(original.get("sha256") == telemetry_sha256 and original.get("status") == "COMPLETE",
            "entry_cleanup_original_telemetry_binding")
    return {"complete": True, "cleanup_scope": receipt["cleanup_scope"],
            "telemetry_sha256": telemetry_sha256,
            "scope": "actual entry sidecar plus independent original entry exit and source/run binding"}


def micro_network(plan, telemetry, telemetry_sha256, receipt, audit):
    require(receipt.get('schema') == 'capture-cost-component-network-observation/v1'
            and receipt.get('regime') == 'SPARSE_CAPTURE_AND_ATOMIC_COMPONENT_WITH_SEPARATE_C1_CONTROL'
            and receipt.get('telemetry_sha256') == telemetry_sha256,
            'micro_network_receipt_identity')
    counts = {'unscored_seed': 2, 'appended_idle': 12, 'appended_governed_busy': 12}
    require(receipt.get('status') == 'PASS' and receipt.get('errors') == []
            and receipt.get('complete_passes') == 2 and receipt.get('callback_counts') == counts
            and receipt.get('ordinary_report_created') is False, 'micro_network_producer_incomplete')
    histories = telemetry.get('registered_runtime_histories')
    require(type(histories) is list and histories, 'registered_runtime_histories_missing')
    history = [pid for item in histories for pid in item['worker_history']]
    require(all(type(pid) is int and pid > 0 for pid in history)
            and len(set(history)) == len(history), 'worker_pid_reuse_trace_ambiguity')
    appended = telemetry['appended_report']['worker_pids']
    expected = set(history) | set(appended)
    actual = {row['pid']: row for row in audit['traces']}
    require(expected and expected <= set(actual), 'all_registered_and_appended_pid_trace_coverage')
    require(receipt.get('worker_pids') == sorted(expected)
            and receipt.get('appended_worker_pids') == appended,
            'micro_network_pid_binding')
    traces = receipt.get('traces')
    require(type(traces) is list and len(traces) == len(actual)
            and {r['pid'] for r in traces} == set(actual)
            and receipt.get('trace_files') == len(actual), 'micro_network_all_trace_inventory')
    for row in traces:
        observed = actual[row['pid']]
        require(row.get('path') == '.agent/'+plan['analysis']['trace_prefix']+'.'+str(row['pid'])
                and row.get('bytes') == observed['bytes'] and row.get('sha256') == observed['sha256'],
                'micro_network_trace_raw_bytes')
    require(audit['unexpected_network_call_count'] == 0
            and receipt.get('unexpected_network_call_count') == 0
            and receipt.get('network_calls_count') == audit['network_call_count']
            and len(receipt.get('network_calls', [])) == audit['network_call_count'],
            'micro_network_unchanged_all_trace_EPERM_predicate')
    return {'status': 'PASS', 'all_registered_worker_pids': sorted(expected),
            'trace_files': len(actual), 'network_call_count': audit['network_call_count'],
            'unexpected_network_call_count': 0,
            'scope': 'independent all-original-trace predicate and PID coverage, not producer verdict alone'}


def capture_governed_activity(telemetry, configuration_sha256):
    """Capture ends before the separately timed batch; preserve its tight raw bracket."""
    shadow = dict(telemetry)
    rows = []
    for callback in telemetry["callbacks"]:
        row = dict(callback)
        if callback["group"] == "appended_governed_busy":
            row["runtime_after"] = callback["component_runtime_before"]
            row["proc_after"] = callback["component_proc_before"]
        rows.append(row)
    shadow["callbacks"] = rows
    result = actual_governed_activity(shadow, configuration_sha256)
    result["scope"] = "original pre-Capture snapshot to pre-component snapshot; final callback snapshot retained separately"
    return result


def component_governed_activity(telemetry, configuration_sha256):
    """Same worker-accounting predicate, independently bracket the component batch."""
    shadow = dict(telemetry)
    rows = []
    for callback in telemetry["callbacks"]:
        if callback["group"] != "appended_governed_busy":
            rows.append(callback)
            continue
        row = dict(callback)
        row["capture_boundary"] = callback["component_batch"]["boundary"]
        for side in ("before", "after"):
            row["runtime_"+side] = callback["component_runtime_"+side]
            row["proc_"+side] = callback["component_proc_"+side]
        rows.append(row)
    shadow["callbacks"] = rows
    observed = actual_governed_activity(shadow, configuration_sha256)
    return {"coverage": observed["coverage"],
            "rows": [{k.replace("capture", "component_batch"): v for k,v in row.items()}
                     for row in observed["rows"]],
            "all_positive_inside_component_batch": observed["all_positive_inside_capture"],
            "limits": observed["limits"] + [
                "Component follows Capture in the same real S06 callback; zero is valid.",
                "No continuous CPU or active-CPU claim follows configured callback context."]}


def micro_budget(telemetry):
    budget = telemetry.get("micro_budget", {})
    require(budget.get("total_seconds") == 600 and budget.get("work_seconds") == 540
            and budget.get("cleanup_seconds") == 60 and budget.get("upload_reserve_seconds") == 90,
            "actual_fixed_micro_work_cleanup_budget")
    start = integer(budget.get("started_monotonic_ns"), "micro_start")
    work_end = integer(budget.get("work_completed_monotonic_ns"), "micro_work_end")
    end = integer(budget.get("cleanup_completed_monotonic_ns"), "micro_cleanup_end")
    require(start <= work_end <= start+540_000_000_000 and work_end <= end <= start+600_000_000_000,
            "micro_work_or_cleanup_outside_fixed_deadline")
    calibration_windows = []
    for sample in telemetry["calibration"]["samples"]:
        for arm in sample["order"]:
            calibration_windows.append(boundary_measurement(sample["patterns"][arm]["boundary"]))
    primary_windows = []
    for row in telemetry["callbacks"]:
        if row["group"] == "unscored_seed":
            continue
        primary_windows.extend((capture_process_cpu(row),
                                boundary_measurement(row["component_batch"]["boundary"])))
    require(len(calibration_windows) == 512 and len(primary_windows) == 48,
            "micro_complete_raw_boundary_budget_coverage")
    for window in calibration_windows+primary_windows:
        require(start <= window["boundary_start_ns"] <= window["boundary_end_ns"] <= work_end,
                "actual_calibration_or_primary_outside_budget")
    require(max(w["boundary_end_ns"] for w in calibration_windows) <=
            min(w["boundary_start_ns"] for w in primary_windows), "calibration_must_precede_all_primaries")
    ordered = sorted(primary_windows, key=lambda w: w["boundary_start_ns"])
    require(all(a["boundary_end_ns"] <= b["boundary_start_ns"] for a,b in zip(ordered, ordered[1:])),
            "primary_timing_windows_overlap")
    def phase(row, code, *, cleanup=False):
        a = integer(row.get("started_monotonic_ns"), code+"_start")
        b = integer(row.get("completed_monotonic_ns"), code+"_end")
        require(start <= a <= b <= (end if cleanup else work_end), code+"_outside_budget")
        require(all(b <= w["boundary_start_ns"] or a >= w["boundary_end_ns"]
                    for w in primary_windows), code+"_overlaps_primary_timing")
        return a,b
    controls_start, _ = phase(telemetry["component_controls"], "control_phase")
    require(max(w["boundary_end_ns"] for w in primary_windows) <= controls_start,
            "unscored_controls_must_follow_all_primaries")
    setups = telemetry.get("component_fixture_setup")
    require(type(setups) is list and len(setups) == 2
            and {r.get("micro_pass") for r in setups} == {0,1}, "component_two_setup_phase_records")
    for setup in setups:
        _, setup_end = phase(setup, "component_fixture_setup")
        rows = [r for r in telemetry["callbacks"] if r["group"] == "appended_idle"
                and r["section_context"].get("micro_pass") == setup["micro_pass"]]
        require(rows and all(r["component_batch"]["fixture_id"] == setup.get("fixture_id") for r in rows)
                and setup_end <= min(capture_process_cpu(r)["boundary_start_ns"] for r in rows),
                "component_setup_precedes_pass_and_identity")
    for cleanup in telemetry.get("component_fixture_cleanup", []):
        cleanup_start, _ = phase(cleanup, "component_fixture_cleanup", cleanup=True)
        rows = [r for r in telemetry["callbacks"] if r["group"] in ("appended_idle", "appended_governed_busy")
                and r["section_context"].get("micro_pass") == cleanup.get("micro_pass")]
        require(rows and max(boundary_measurement(r["component_batch"]["boundary"])["boundary_end_ns"]
                             for r in rows) <= cleanup_start, "component_cleanup_after_last_batch")
    return {"total_seconds": 600, "work_seconds": 540, "cleanup_seconds": 60,
            "observed_work_seconds": (work_end-start)/1e9,
            "observed_total_seconds": (end-start)/1e9,
            "linked_calibration_windows": 512, "linked_primary_windows": 48,
            "scope": "raw calibration/primary/fixture/control/cleanup phases bound; no upload reserve borrowed"}


def component_cost_effect(groups):
    require(len(groups) == 2, "component_idle_and_busy_required")
    return all(g["contrast_summaries"]["submit_through_process_cpu_ns"]["raw_median_A_minus_B_ns"] > 0
               and g["contrast_summaries"]["submit_through_process_cpu_ns"]["empirical_median_effect_interval_ns"][0] > 0
               for g in groups)


def mechanism_cell(plan, plan_sha256, telemetry, telemetry_sha256, network, audit, ordinal):
    cell = plan['cells'][ordinal]
    head = plan['original_commit'] if cell['ordinary_arm'] == 'A' else plan['fast_commit']
    require(telemetry.get('schema') == TELEMETRY_SCHEMA
            and telemetry.get('mode') == MODE, 'component_telemetry_schema_mode')
    identity = telemetry['identity']
    require(identity.get('regime') == REGIME
            and identity.get('head') == head and identity.get('cell') == cell
            and identity.get('frozen_plan_sha256') == plan_sha256, 'component_source_cell_identity')
    require(telemetry.get('status') == 'COMPLETE' and telemetry.get('errors') == [],
            'component_recorder_errors_or_incomplete')
    counts = {'unscored_seed': 2, 'appended_idle': 12, 'appended_governed_busy': 12}
    require(Counter(c.get('group') for c in telemetry['callbacks']) == Counter(counts)
            and len({c['id'] for c in telemetry['callbacks']}) == 26,
            'component_exact_twenty_six_callback_inventory')
    require(telemetry.get('ordinary_callback_counts') ==
            {'ordinary_idle': 0, 'ordinary_s05_busy': 0, 'ordinary_s06_busy': 0}
            and telemetry.get('ordinary_actual_row_binding') == []
            and 'ordinary_report' in telemetry and telemetry['ordinary_report'] is None
            and telemetry.get('ordinary_control_scope') == 'SEPARATE_C1_CONTROL_ONLY_NOT_THIS_RESULT',
            'component_forbidden_ordinary_rows')
    require(identity.get('runtime_coordinates') == plan['runtime_coordinates']
            and set(plan['runtime_coordinates']) ==
            {'configuration_sha256', 'model_sha256', 'runtime_lock_sha256'},
            'actual_component_runtime_coordinates')
    fixture = plan.get('component_fixture', {})
    require(fixture.get('profile') == EMAIL_PROFILE and fixture.get('payload_bytes') == 4096
            and fixture.get('transactions_per_batch') == 32
            and re.fullmatch('[0-9a-f]{64}', fixture.get('payload_sha256', '')) is not None,
            'fixed_existing_profile_and_public_component_fixture')
    budget = micro_budget(telemetry)
    model_setup = identity.get('micro_model_setup', {})
    require(model_setup.get('installation', {}).get('id') == 'qwen3.5-2b-q5-k-m'
            and model_setup['installation'].get('state') == 'verified'
            and model_setup['installation'].get('activated') is False
            and type(model_setup.get('started_ns')) is int
            and type(model_setup.get('completed_ns')) is int
            and 0 <= model_setup['started_ns'] <= model_setup['completed_ns'],
            'actual_accepted_model_setup')
    appended = telemetry['appended_report']
    passes = appended.get('passes', [])
    require(appended.get('status') == 'COMPLETE' and len(passes) == 2
            and all(p.get('status') == 'COMPLETE' for p in passes)
            and len({p.get('instance_id') for p in passes}) == 2,
            'two_fresh_complete_full_governed_passes')
    for p in passes:
        require(len(p.get('idle', [])) == 6 and len(p['governed'].get('samples', [])) == 6,
                'component_full_measure_jobs_shape')
        require(all(p.get('unscored_seed', {}).get(key) is True for key in
                    ('preserved', 'search_found', 'product_dispatch_blocked')), 'component_seed_semantics')
    seeds = [c for c in telemetry['callbacks'] if c['group'] == 'unscored_seed']
    for index, p in enumerate(passes):
        matching = [c for c in seeds if c['section_context'].get('micro_pass') == index]
        require(len(matching) == 1 and matching[0]['arm'] == cell['ordinary_arm']
                and matching[0]['probe'] == p['unscored_seed'], 'component_seed_original_row_identity')
    idle_callbacks = sorted([c for c in telemetry['callbacks'] if c['group'] == 'appended_idle'],
                            key=lambda c: c['treatment_ordinal'])
    require([c['probe'] for c in idle_callbacks] == [row for p in passes for row in p['idle']],
            'component_idle_original_rows_recomputed')
    for callback in telemetry['callbacks']:
        if callback['group'] != 'unscored_seed':
            validate_callback(callback)
        else:
            require(callback.get('component_batch') is None, 'unscored_seed_has_measured_batch')
        method = callback['method_identity']
        require(method.get('source_sha256') == plan['atomic_source_sha256'][callback['arm']]
                and method.get('method_ast_sha256') == plan['method_ast_sha256'][callback['arm']],
                'selected_source_and_three_method_identity')
    idle = group_metrics(telemetry, 'appended_idle', cell['micro_order'], fixture)
    busy = group_metrics(telemetry, 'appended_governed_busy', cell['micro_order'], fixture)
    component_idle = group_metrics(telemetry, 'appended_idle', cell['micro_order'], fixture, component=True)
    component_busy = group_metrics(telemetry, 'appended_governed_busy', cell['micro_order'], fixture, component=True)
    inventory = component_inventory(telemetry, fixture)
    require(not {r['fixture_id'] for r in inventory['fixtures']} & {p['instance_id'] for p in passes},
            'component_store_overlaps_capture_instance')
    controls = control_metrics(telemetry, fixture, plan)
    require(not {b['fixture_id'] for b in controls['batches']} &
            ({r['fixture_id'] for r in inventory['fixtures']} | {p['instance_id'] for p in passes}),
            'unscored_control_fixture_reused')
    activity = capture_governed_activity(telemetry, plan['runtime_coordinates']['configuration_sha256'])
    component_activity = component_governed_activity(telemetry, plan['runtime_coordinates']['configuration_sha256'])
    network_coverage = micro_network(plan, telemetry, telemetry_sha256, network, audit)
    margins = margin_intervals(idle, busy)
    groups = (component_idle, component_busy)
    cpu_effect = component_cost_effect(groups)
    fullflow_cpu = all(g['contrast_summaries']['submit_through_process_cpu_ns']['raw_median_A_minus_B_ns'] > 0
                      and g['contrast_summaries']['submit_through_process_cpu_ns']['empirical_median_effect_interval_ns'][0] > 0
                      for g in (idle, busy))
    wall_compatibility = all(g['contrast_summaries']['capture_wall_ns']['empirical_median_effect_interval_ns'][1] >= 0
                             for g in (idle, busy))
    literal_margins = literal_fresh_margins(idle, busy)
    absolute_b = literal_margins['B']['at_most_zero']
    return {'ordinal': ordinal, 'slot': cell['slot'], 'checkout_base_arm': cell['ordinary_arm'],
            'micro_order': cell['micro_order'], 'regime': REGIME,
            'idle': idle, 'busy': busy, 'component_idle': component_idle, 'component_busy': component_busy,
            'actual_governed_activity': activity, 'component_governed_activity': component_activity,
            'component_inventory': inventory, 'unscored_component_controls': controls,
            'micro_budget': budget, 'network': network_coverage, 'fresh_diagnostic_margin': margins,
            'B_fresh_absolute_M6_at_most_zero': absolute_b,
            'literal_raw_fresh_M6': literal_margins,
            'margin_compatible_with_no_material_regression': margins['observed_compatibility_with_no_material_regression'],
            'observed_fresh_headroom_improvement': margins['observed_headroom_benefit'],
            'observed_fresh_spread_improvement': margins['observed_spread_benefit'],
            'descriptive_fullflow': {'net_parent_cpu': fullflow_cpu,
                                     'wall_observed_compatibility': wall_compatibility,
                                     'authority': 'DESCRIPTIVE_NOT_ADVANCEMENT_NOT_NONREGRESSION_PROOF'},
            'cost_components': {'batch32_net_parent_cpu': cpu_effect,
                                'selected_durable_work_equal': True},
            'avoidable_component_cost_demonstrated': cpu_effect,
            'avoidable_cost_demonstrated': cpu_effect,
            'limits': ['Only generic Atomic component CPU is the prespecified causal target.',
                       'All full Capture A/B contrasts and booleans remain descriptive, including false.',
                       'Strict absolute B fresh latency guard has no calibration slack and is not qualification.',
                       'Empirical recorder envelope is not a statistical CI or universal scheduling bound.']}


def source_integrity(plan, plan_sha256, selected, workflow_head, job, ordinal):
    names = plan['source_proof_members']
    def raw(key):
        return selected[names[key]]['raw']
    arm = plan['cells'][ordinal]['ordinary_arm']
    head = plan['original_commit'] if arm == 'A' else plan['fast_commit']
    require(raw('checkout_git').decode('ascii').splitlines() ==
            [head, plan['source_parents'][arm], plan['source_trees'][arm]], 'C3_checkout_git_proof')
    workflow = raw('workflow_git').decode('ascii').splitlines()
    require(len(workflow) == 3 and workflow[:2] == [workflow_head, plan['fast_commit']]
            and re.fullmatch('[0-9a-f]{40}', workflow[2]) is not None, 'C3_workflow_git_proof')
    require(digest(raw('frozen_plan')) == plan_sha256 and raw('source_status_after') == b'',
            'C3_plan_or_after_source_status')
    for key in ('entry_exit', 'network_exit', 'source_status_exit', 'source_head_exit', 'source_tree_exit'):
        require(raw(key) == b'0\n', 'C3_original_exit_not_zero')
    require(job['listed_original'].get('conclusion') == job['direct_original'].get('conclusion') == 'success',
            'C3_actual_original_job_not_success')
    steps = job['direct_original'].get('steps', [])
    expected_step = 'Complete fixed sparse Capture and Atomic component diagnostic cohort'
    setup_post = 'Post Run actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405'
    require(len([s for s in steps if s.get('name') == expected_step]) == 1
            and len([s for s in steps if s.get('name') == setup_post]) == 1,
            'C3_measurement_or_pinned_post_identity')
    require(all(s.get('status') == 'completed' and s.get('conclusion') == 'success' for s in steps),
            'C3_original_job_step_not_success')
    return {'actual_job_conclusion': 'success', 'source_head': head,
            'source_parent': plan['source_parents'][arm], 'source_tree': plan['source_trees'][arm],
            'all_original_source_exit_codes_zero': True,
            'fixed_member_sha256': {key: selected[name]['sha256'] for key, name in names.items()}}


def decision_summary(cells):
    require(type(cells) is list and len(cells) == 4, "decision_exact_four_complete_cells")
    require([c["ordinal"] for c in cells] == list(range(4))
            and [c["slot"] for c in cells] == ["A1", "B1", "B2", "A2"],
            "decision_exact_original_slot_order")
    result = {
        "all_four_cost_proofs": all(c["avoidable_cost_demonstrated"] for c in cells),
        "all_four_B_fresh_absolute_M6_at_most_zero": all(c["B_fresh_absolute_M6_at_most_zero"] for c in cells),
        "all_four_actual_jobs_success": all(c["independent_source_integrity"]["actual_job_conclusion"] == "success"
                                           for c in cells),
        "all_four_fresh_margin_observed_compatibility": all(c["margin_compatible_with_no_material_regression"]
                                                          for c in cells),
        "all_four_fresh_headroom_benefit": all(c["observed_fresh_headroom_improvement"] for c in cells),
        "all_four_fresh_spread_benefit": all(c["observed_fresh_spread_improvement"] for c in cells),
        "all_four_descriptive_fullflow_cpu_positive": all(c["descriptive_fullflow"]["net_parent_cpu"]
                                                        for c in cells),
        "all_four_descriptive_fullflow_wall_compatibility": all(c["descriptive_fullflow"]["wall_observed_compatibility"]
                                                              for c in cells),
    }
    result["clean_candidate_preparation_supported"] = (
        result["all_four_cost_proofs"] and result["all_four_B_fresh_absolute_M6_at_most_zero"]
        and result["all_four_actual_jobs_success"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--originals-manifest', type=Path, required=True)
    parser.add_argument('--workflow-head', required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--c1-controls', type=Path, required=True)
    parser.add_argument('--c1-control-execution-receipt', type=Path, required=True)
    parser.add_argument('--c1-control-host-launch', type=Path, required=True)
    parser.add_argument('--original-audit', type=Path, required=True)
    parser.add_argument('--original-audit-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'schema': 'independent-capture-atomic-component-analysis/v3',
              'authority': 'NONE_DIAGNOSTIC_NOT_QUALIFICATION', 'state': 'NOT_DEMONSTRATED',
              'regime': REGIME,
              'cells': [], 'errors': [], 'original_artifacts': []}
    try:
        raw = args.plan.read_bytes()
        require(digest(raw) == args.plan_sha256, 'C3_frozen_plan_sha256')
        plan = load_json(raw)
        require(plan.get('schema') == PLAN_SCHEMA and plan.get('status') == 'FROZEN'
                and plan.get('mode') == 'SPARSE_COMPONENT_V3'
                and plan.get('regime') == 'SPARSE_CAPTURE_AND_ATOMIC_COMPONENT_WITH_SEPARATE_C1_CONTROL', 'C3_frozen_plan_mode')
        require(plan['job_seconds'] == 1200 and plan['micro_budget_seconds'] == 600
                and plan['upload_reserve_seconds'] == 90 and plan['work_budget_seconds'] == 540
                and plan['cleanup_budget_seconds'] == 60, 'C3_fixed_time_boundaries')
        require(plan['analysis']['analyzer_sha256'] == digest(Path(__file__).read_bytes()), 'C3_analyzer_pin')
        require(len(plan['cells']) == 4, 'C3_four_slots_required')
        result['C1_control_only'] = c1_controls(plan, args.c1_controls.read_bytes(),
                                              args.c1_control_execution_receipt.read_bytes(),
                                              args.c1_control_host_launch.read_bytes())
        manifest_raw = args.originals_manifest.read_bytes()
        manifest = load_json(manifest_raw)
        audit = original_audit(plan, args.plan_sha256, args.original_audit.read_bytes(),
                               args.original_audit_sha256, manifest_raw, args.workflow_head, args.run_id)
        slots = manifest_slots(manifest, plan, args.plan_sha256, args.workflow_head, args.run_id)
        result['original_execution_identity'] = original_execution_identity(manifest, args.workflow_head, args.run_id)
        result['selection_manifest'] = {'sha256': digest(manifest_raw), 'bytes': len(manifest_raw),
                                        'workflow_head': args.workflow_head, 'run_id': args.run_id, 'run_attempt': 1}
        result['independent_original_audit'] = {'sha256': args.original_audit_sha256,
                                               'helper_sha256': audit['helper_sha256'],
                                               'scope': 'METADATA_AND_BYTES_ONLY'}
        for ordinal, job, artifact in slots:
            try:
                members = dict(plan['artifact_members'])
                members.update(plan['source_proof_members'])
                selected, inventory = read_artifact(Path(artifact['zip_path']), members, plan['analysis']['trace_prefix'])
                require(inventory['bytes'] == artifact['expected_bytes']
                        and inventory['sha256'] == artifact['expected_zip_sha256'], 'C3_original_ZIP_API_binding')
                audited = [r for r in audit['slots'] if r.get('ordinal') == ordinal
                           and r.get('slot') == plan['cells'][ordinal]['slot']]
                require(len(audited) == 1, 'C3_original_audit_slot_identity')
                observed = audited[0]
                source_head = plan['original_commit'] if plan['cells'][ordinal]['ordinary_arm'] == 'A' else plan['fast_commit']
                require(observed.get('job_id') == job['job_id']
                        and observed.get('source_head') == source_head
                        and observed.get('artifact_id') == artifact['artifact_id']
                        and observed.get('zip_bytes') == inventory['bytes']
                        and observed.get('zip_sha256') == inventory['sha256']
                        and observed.get('listed_direct_equal') is True
                        and observed.get('metadata_and_bytes_verified') is True
                        and observed.get('original_checkout_proof_verified') is True
                        and observed.get('actual_job_status') == job['direct_original']['status']
                        and observed.get('actual_job_conclusion') == job['direct_original']['conclusion'],
                        'C3_original_audit_original_bytes_and_actual_job_binding')
                require('s05-real.json' not in {m['name'] for m in inventory['members']}, 'C3_forbidden_ordinary_report')
                inventory.update(slot=ordinal, artifact_id=artifact['artifact_id'], original_job_id=job['job_id'],
                                 original_job_conclusion=job['direct_original']['conclusion'])
                result['original_artifacts'].append(inventory)
                source = source_integrity(plan, args.plan_sha256, selected, args.workflow_head, job, ordinal)
                t = selected[plan['artifact_members']['telemetry']]
                n = selected[plan['artifact_members']['network_observation']]
                e = selected[plan['artifact_members']['entry_execution']]
                entry_evidence = entry_cleanup_evidence(load_json(e['raw']), t['sha256'])
                telemetry = load_json(t['raw'])
                require(telemetry['identity'].get('workflow_head') == args.workflow_head
                        and telemetry['identity'].get('workflow_run_id') == str(args.run_id)
                        and telemetry['identity'].get('workflow_run_attempt') == '1', 'C3_telemetry_run_identity')
                cell = mechanism_cell(plan, args.plan_sha256, telemetry, t['sha256'], load_json(n['raw']),
                                      inventory['raw_network_trace_audit'], ordinal)
                cell['independent_source_integrity'] = source
                cell['entry_cleanup_evidence'] = entry_evidence
                result['cells'].append(cell)
            except Exception as exc:
                result['errors'].append({'slot': ordinal,
                                         'code': str(exc) if isinstance(exc, Unsupported) else type(exc).__name__})
        if len(result['cells']) == 4 and not result['errors']:
            cells = result['cells']
            result['state'] = 'COMPLETE_COMPONENT_COMPARISON'
            result.update(decision_summary(cells))
    except Exception as exc:
        result['errors'].append({'code': str(exc) if isinstance(exc, Unsupported) else type(exc).__name__})
    result['qualification'] = 'NOT_QUALIFIED_REQUIRES_CLEAN_EXACT_HEAD_FULL_ORDINARY_ALL_GATES_AND_POSTMERGE'
    result['limits'] = ['C1 original four failures and formal refusals remain unchanged.',
                        'Only Atomic batch32 net CPU is primary; fullflow A/B metrics cannot prove nonregression/headroom.',
                        'No historical-cause, universal recorder-bound or release authority follows.']
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+'\n')
    return 0 if result['state'] == 'COMPLETE_COMPONENT_COMPARISON' else 2


if __name__ == '__main__':
    raise SystemExit(main())
