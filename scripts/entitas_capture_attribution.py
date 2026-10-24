"""One frozen diagnostic cohort; no application gate or limit is changed."""
from __future__ import annotations

import argparse
import functools
import json
import resource
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

import ai_runtime_report  # noqa: E402

from provelume import atomic_commit, capture_adapter, capture_journal  # noqa: E402

MAX_EVENTS = 4096
MAX_BYTES = 16 * 1024 * 1024
active = None
observations = []


def instrument(owner, name, label):
    original = getattr(owner, name)

    @functools.wraps(original)
    def measured(*args, **kwargs):
        row = active
        if row is None:
            return original(*args, **kwargs)
        started, cpu = time.monotonic(), time.thread_time()
        error = None
        try:
            return original(*args, **kwargs)
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            event = {"operation": label, "thread": threading.get_ident(),
                     "offset_seconds": started - row["started"],
                     "seconds": time.monotonic() - started,
                     "thread_cpu_seconds": time.thread_time() - cpu,
                     "error": error}
            # append is protected by the interpreter GIL; no new worker or lock.
            if len(row["events"]) < MAX_EVENTS:
                row["events"].append(event)
            else:
                row["truncated"] = True

    setattr(owner, name, measured)


def usage():
    row = resource.getrusage(resource.RUSAGE_SELF)
    return {name: getattr(row, name) for name in
            ("ru_utime", "ru_stime", "ru_nvcsw", "ru_nivcsw", "ru_inblock", "ru_oublock")}


def main():
    global active
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attribution", type=Path, required=True)
    args = parser.parse_args()
    original_probe = ai_runtime_report.deterministic_probe
    plan_path = ROOT / "scripts/entitas_capture_attribution_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for name in ("_prepare", "_publish_entries", "_shutdown_transaction_pool", "_shutdown_pool"):
        instrument(atomic_commit.AtomicInstanceCommit, name, "transaction." + name)
    for name in ("_instance_target", "_write_journal_payload", "_fsync_directory"):
        instrument(atomic_commit, name, "atomic." + name)
    instrument(capture_journal.CaptureJournal, "_inventory", "capture.inventory")
    instrument(capture_adapter, "refresh_search_index", "capture.search_refresh")

    def probe(instance, number):
        global active
        if active is not None:
            raise RuntimeError("overlapping diagnostic probes")
        row = {"number": number, "started": time.monotonic(), "events": [],
               "truncated": False, "before": usage(), "outcome": None, "error": None}
        active = row
        try:
            row["outcome"] = original_probe(instance, number)
            return row["outcome"]
        except BaseException as exc:
            row["error"] = type(exc).__name__
            raise
        finally:
            row["elapsed_seconds"] = time.monotonic() - row["started"]
            row["after"] = usage()
            active = None
            observations.append(row)

    ai_runtime_report.deterministic_probe = probe
    # Imports occur after instrumenting the one shared probe, including dynamic
    # S06/S07 imports. Production source, assertions and limits stay byte-identical.
    import qualify_ai_runtime

    started, before = time.monotonic(), usage()
    try:
        report = qualify_ai_runtime.measure(args.artifacts.absolute(), args.output)
    finally:
        result = {"classification": plan["classification"], "plan": plan,
                  "elapsed_seconds": time.monotonic() - started,
                  "before": before, "after": usage(), "observations": observations,
                  "overhead": "UNKNOWN_NOT_SUBTRACTED", "historical_cause": "UNKNOWN"}
        encoded = (json.dumps(result, indent=2) + "\n").encode("utf-8")
        if len(encoded) > MAX_BYTES:
            raise ValueError("attribution artifact exceeds frozen bound")
        args.attribution.write_bytes(encoded)
    # This is collection completeness, never product qualification. All original
    # gate statuses are retained in the report and external network evaluation.
    return 0 if len(report.get("samples", [])) == 60 and report.get("s06", {}).get(
        "status") == "MEASURED" and observations else 1


if __name__ == "__main__":
    raise SystemExit(main())
