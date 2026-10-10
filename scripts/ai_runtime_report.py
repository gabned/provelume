"""Fixed ADR 0031 evaluators and synthetic deterministic-flow measurement."""
from __future__ import annotations

import statistics
import time
from uuid import uuid4

from provelume.capture_adapter import CaptureAdapter
from provelume.service import ProvelumeInstance


def deterministic_probe(instance, number):
    """Exercise real capture, exact Original preservation, extraction and search."""
    device, client = "dev_" + "a" * 32, str(uuid4())
    payload = b"S05 synthetic orchid deterministic capture and search."
    adapter = CaptureAdapter(instance.store, authorize=lambda *args: None)
    start = time.monotonic()
    adapter.submit(device, payload, {
        "schema_version": 1, "client_submission_id": client,
        "captured_at": "2026-10-03T12:00:00+00:00", "mode": "text",
        "channel": "local_browser",
    }, channel="local_browser")
    submit_seconds = time.monotonic() - start
    receipt = adapter.process(device, client, channel="local_browser")["receipt"]
    capture = time.monotonic() - start
    preserved = instance.store.original_bytes(receipt["original_id"]) == payload
    start = time.monotonic()
    results = instance.search("orchid")
    search = time.monotonic() - start
    return {"sample": number, "capture_seconds": capture, "search_seconds": search,
            "capture_submit_seconds": submit_seconds,
            "capture_process_seconds": capture - submit_seconds,
            "preserved": preserved, "search_found": bool(results),
            "product_dispatch_blocked": not ProvelumeInstance.ai_execution_status()["enabled"]}


def evaluate(report):
    """No missing dimension can become PASS; thresholds match the pre-measurement ADR."""
    gates = {}

    def bounded(name, values, count, limit):
        gates[name] = ("NOT_RUN" if len(values) != count or any(v is None for v in values)
                       else "PASS" if max(values) <= limit else "FAIL")

    cold, warm = report.get("cold", []), report.get("samples", [])
    bounded("cold_load", [r["load"]["seconds"] for r in cold], 3, 15)
    bounded("cold_first", [r.get("first_wall_seconds") for r in cold], 3, 20)
    bounded("cold_total", [r["total_seconds"] for r in cold], 3, 60)
    bounded("warm_first", [r.get("first_wall_seconds") for r in warm], 60, 5)
    bounded("warm_total", [r["total_seconds"] for r in warm], 60, 30)
    bounded("worker_peak_rss", [r["memory"].get("peak_rss") for r in cold + warm],
            63, 2 * 1024**3)
    for name in ("cancel_load", "cancel_generation"):
        row = report.get(name)
        gates[name] = ("NOT_RUN" if row is None else "PASS" if row["seconds"] <= 2
                       and row["worker_absent"] and row["code"] == "cancelled" else "FAIL")
    row = report.get("idle_unload")
    gates["unload"] = ("NOT_RUN" if row is None else "PASS" if row["worker_absent"]
                       and row["seconds"] <= 7 else "FAIL")
    before, after = report.get("parent_before"), report.get("parent_after")
    gates["parent_ram_after_unload"] = ("NOT_RUN" if not before or not after else "PASS"
        if after["rss"] - before["rss"] <= 64 * 1024**2 else "FAIL")
    for language in ("en", "it"):
        gates["quality_" + language] = report.get("quality", {}).get(language, {}).get(
            "status", "NOT_RUN")
    for name in ("absent_model", "altered_model"):
        gates[name] = ("NOT_RUN" if name not in report else "PASS" if report[name] in
                       ("missing", "integrity") else "FAIL")
    baseline = report.get("deterministic_idle", [])
    concurrent = report.get("deterministic_busy", [])
    gates["deterministic"] = "NOT_RUN"
    if len(baseline) >= 3 and len(concurrent) >= 3:
        passed = all(r["preserved"] and r["search_found"] and r["product_dispatch_blocked"]
                     and r.get("worker_observed", True) for r in baseline + concurrent)
        for key in ("capture_seconds", "search_seconds"):
            limit = min(1, 2 * statistics.median(r[key] for r in baseline) + 0.1)
            passed &= all(r[key] <= limit for r in concurrent)
        gates["deterministic"] = "PASS" if passed else "FAIL"
    gates["network"] = report.get("network", "NOT_RUN")
    gates["next_caller"] = ("NOT_RUN" if "next_caller" not in report else "PASS"
                            if report["next_caller"] == "PASSED" else "FAIL")
    if report.get("s06_required"):
        governed = report.get("s06", {})
        rows = governed.get("samples", [])
        cancels = governed.get("cancellations", [])
        gates["s06_governed"] = "NOT_RUN"
        if governed.get("status") == "MEASURED" and len(rows) == 6 and len(cancels) == 2:
            passed = (governed.get("default_off") and governed.get("final_off")
                      and governed.get("worker_absent")
                      and governed.get("next_caller") == "succeeded"
                      and governed.get("receipt_count") == 9)
            for row in rows:
                worker = row["worker"]
                passed &= (row["status"] == "succeeded" and row["attempts"] == 1
                    and row["consumption"]["usage_source"] == "LOCAL"
                    and row["consumption"]["micros"] == 0 and row["consumption"]["units"] > 0
                    and row["result_fingerprint"] is not None
                    and worker["memory"]["peak_rss"] <= 2 * 1024**3
                    and row["seconds"] <= (60 if row["phase"] == "cold" else 30)
                    and row["first_seconds"] is not None
                    and row["first_seconds"] <= (20 if row["phase"] == "cold" else 5)
                    and (row["phase"] != "cold" or worker["load"]["seconds"] <= 15))
                # Warm means the model is loaded, not an identical private prompt.
                passed &= (
                    worker.get("reused_input_tokens") == 0 if row["phase"] == "cold" else
                    0 < worker.get("reused_input_tokens", 0) < worker["input_tokens"] - 1)
            passed &= len({r.get("binding") for r in rows if r["phase"] == "warm"}) == 3
            passed &= all(rows[i].get("binding") != rows[i + 1].get("binding") for i in (0, 2, 4))
            passed &= all(r["status"] == "cancelled" and r["worker_absent"] and r["active"] == 0
                          and r["seconds"] is not None and r["seconds"] <= 2 for r in cancels)
            probes = governed.get("deterministic_busy", [])
            passed &= len(probes) == 6 and len(baseline) >= 3
            passed &= all(r["preserved"] and r["search_found"] and r["worker_observed"]
                          and r["product_dispatch_blocked"] for r in probes)
            for key in ("capture_seconds", "search_seconds"):
                if baseline:
                    limit = min(1, 2 * statistics.median(r[key] for r in baseline) + 0.1)
                    passed &= all(r[key] <= limit for r in probes)
            unload = governed.get("idle_unload", {})
            passed &= unload.get("worker_absent") and unload.get("seconds", 8) <= 7
            passed &= (governed["parent_after"]["rss"] - governed["parent_before"]["rss"]
                       <= 64 * 1024**2)
            gates["s06_governed"] = "PASS" if passed else "FAIL"
    if report.get("s07_required"):
        setup = report.get("s07", {})
        rows = setup.get("samples", [])
        gates["s07_setup"] = "NOT_RUN"
        if setup.get("status") == "MEASURED" and len(rows) == 2:
            passed = (setup.get("session_off") and setup.get("final_off")
                      and setup.get("worker_absent"))
            for row in rows:
                concurrency = row.get("concurrency", {})
                prefill = row["worker"].get("prefill") or {}
                passed &= (row["status"] == "succeeded" and row["attempts"] == 1
                           and bool(row.get("inference_observed")) and row["receipt"] is not None
                           and concurrency.get("phase") == "native_prefill"
                           and type(concurrency.get("request")) is str
                           and len(concurrency["request"]) == 32
                           and all(ch in "0123456789abcdef" for ch in concurrency["request"])
                           and concurrency == prefill
                           and concurrency.get("pid") == row["worker"]["load"].get("pid")
                           and row["worker"]["memory"]["peak_rss"] <= 2 * 1024**3
                           and row["seconds"] <= (60 if row["phase"] == "cold" else 30)
                           and row["first_seconds"] <= (20 if row["phase"] == "cold" else 5)
                           and row["probe"]["preserved"] and row["probe"]["search_found"]
                           and row["probe"].get("worker_observed")
                           and row["probe"]["product_dispatch_blocked"])
                worker = row["worker"]
                passed &= (worker.get("reused_input_tokens") == 0 if row["phase"] == "cold"
                           else 0 < worker.get("reused_input_tokens", 0) < worker["input_tokens"])
                passed &= row["phase"] != "cold" or worker["load"]["seconds"] <= 15
                passed &= len(baseline) >= 3
                for key in ("capture_seconds", "search_seconds"):
                    if baseline:
                        limit = min(1, 2 * statistics.median(r[key] for r in baseline) + 0.1)
                        passed &= row["probe"][key] <= limit
            gates["s07_setup"] = "PASS" if passed else "FAIL"
    if report.get("s08_required"):
        synthesis = report.get("s08", {})
        rows = synthesis.get("samples", [])
        complete = (synthesis.get("status") == "MEASURED" and len(rows) == 32
                    and len({r["id"] for r in rows}) == 32)
        gates["s08_references"] = (
            "NOT_RUN" if not complete else "PASS"
            if all(r["valid"] and r["status"] == "succeeded" for r in rows) else "FAIL"
        )
        gates["s08_abstention"] = (
            "NOT_RUN" if not complete else "PASS"
            if sum(r["require_abstention"] for r in rows) == 8
            and all(r["abstained"] for r in rows if r["require_abstention"]) else "FAIL"
        )
        for language in ("en", "it"):
            for task in ("summary", "key-points"):
                selected = [r for r in rows if r["language"] == language and r["task"] == task]
                gates[f"s08_quality_{language}_{task}"] = (
                    "NOT_RUN" if len(selected) != 8 else "PASS"
                    if sum(r["gold"] for r in selected) / 8 >= 0.9 else "FAIL"
                )
        performance = synthesis.get("performance", [])
        idle = synthesis.get("idle", [])
        gates["s08_performance"] = "NOT_RUN"
        if len(performance) == 2 and len(idle) == 3:
            passed = bool(synthesis.get("final_off") and synthesis.get("worker_absent"))
            cancel = synthesis.get("cancellation", {})
            passed &= bool(cancel.get("generation_observed") and cancel.get("status") == "cancelled"
                       and cancel.get("seconds", 3) <= 2 and cancel.get("worker_absent")
                       and cancel.get("active") == 0)
            before, after = synthesis.get("parent_before"), synthesis.get("parent_after")
            passed &= bool(before and after and after["rss"] - before["rss"] <= 64 * 1024**2)
            for row in performance:
                cold = row["phase"] == "cold"
                worker, probe = row["worker"], row["probe"]
                passed &= (row["status"] == "succeeded" and row["generation_observed"]
                           and row["seconds"] <= (60 if cold else 30)
                           and row["first_seconds"] <= (20 if cold else 5)
                           and worker["memory"]["peak_rss"] <= 2 * 1024**3
                           and (not cold or worker["load"]["seconds"] <= 15)
                           and probe["worker_observed"] and probe["preserved"]
                           and probe["search_found"] and probe["product_dispatch_blocked"])
                for key in ("capture_seconds", "search_seconds"):
                    limit = min(1, 2 * statistics.median(r[key] for r in idle) + 0.1)
                    passed &= probe[key] <= limit
            gates["s08_performance"] = "PASS" if passed else "FAIL"
    report["gates"] = gates
    report["status"] = ("FAIL" if report.get("failures") or "FAIL" in gates.values() else
                         "BLOCKED" if any(v != "PASS" for v in gates.values()) else "PASS")
    return report
