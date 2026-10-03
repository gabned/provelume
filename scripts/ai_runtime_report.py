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
    receipt = adapter.process(device, client, channel="local_browser")["receipt"]
    capture = time.monotonic() - start
    preserved = instance.store.original_bytes(receipt["original_id"]) == payload
    start = time.monotonic()
    results = instance.search("orchid")
    search = time.monotonic() - start
    return {"sample": number, "capture_seconds": capture, "search_seconds": search,
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
    report["gates"] = gates
    report["status"] = ("FAIL" if report.get("failures") or "FAIL" in gates.values() else
                         "BLOCKED" if any(v != "PASS" for v in gates.values()) else "PASS")
    return report
