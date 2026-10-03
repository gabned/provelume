"""Real S05 candidate measurements; synthetic corpus, explicit acquisition first."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from provelume.ai_model_store import ModelStore  # noqa: E402
from provelume.ai_models import ModelError  # noqa: E402
from provelume.ai_runtime import LocalRuntime, native_selection  # noqa: E402
from provelume.ai_runtime_contract import (  # noqa: E402
    CONFIGURATION,
    LOCK_SHA256,
    MODEL_ID,
    MODEL_SHA256,
    hardware,
)
from provelume.ai_runtime_limits import memory_observation  # noqa: E402


def measure(root, output):
    report = {
        "schema_version": 1,
        "status": "NOT_RUN",
        "samples": [],
        "failures": [],
        "configuration": CONFIGURATION,
        "runtime_lock_sha256": LOCK_SHA256,
        "model_sha256": MODEL_SHA256,
        "network": "NOT_RUN",
        "profile_scope": "observed host only; minimum laptop NOT_RUN",
        "cold_condition": "fresh process; OS file cache not flushed",
        "product_dispatch": "REQUIRES_S06",
        "recommended": False,
    }

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    runtime = None
    try:
        report["environment"] = hardware()
        system = report["environment"]["platform"]
        store = ModelStore(root / "store")
        selection = native_selection()
        runtime = LocalRuntime(root / system)
        before = memory_observation()
        report["parent_before"] = before
        try:
            store.verify(MODEL_ID, selection)
        except ModelError as exc:
            report["absent_model"] = exc.code
        report["installation"] = store.import_offline(
            MODEL_ID, root / "qwen.gguf", selection, requested=True, license_accepted="Apache-2.0"
        )
        corpus_path = ROOT / "tests/fixtures/ai_runtime_quality.json"
        report["corpus_sha256"] = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        for cold_run in range(3):
            runtime.close()
            evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
            report.setdefault("self_tests", []).append(evidence.public_record())
            report.setdefault("cold", []).append(runtime.last_observation)
            if evidence.result != "PASSED":
                report["failures"].append("self_test:" + evidence.result)
                break
            store.activate(MODEL_ID, selection, evidence, requested=True)
            for case in corpus:
                # Fresh evidence has a 60-second TTL. Refresh explicitly; no inferred
                # authority, persisted qualification or implicit inference retry.
                if time.monotonic() + 20 >= evidence.expires:
                    evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
                    store.activate(MODEL_ID, selection, evidence, requested=True)
                result = runtime.qualify(
                    store,
                    "Text: " + case["text"] + "\nQuestion: " + case["question"],
                    requested=True,
                )
                normalized = result["text"].strip().strip(".\"' ").casefold()
                row = {
                    "id": case["id"],
                    "language": case["language"],
                    "run": cold_run,
                    "expected": case["expected"],
                    "pass": normalized == case["expected"].casefold(),
                    **result,
                }
                report["samples"].append(row)
                save()
        # Explicit cancellation at the first wait during fresh-worker load.
        runtime.close()
        model = store.verify(MODEL_ID, selection)
        start = time.monotonic()
        try:
            runtime._infer(
                model,
                selection,
                "Text: A. Question: Repeat A.",
                cancel=lambda: time.monotonic() - start >= 0.1,
            )
        except ModelError as exc:
            report["cancel_load"] = {
                "code": exc.code,
                "seconds": time.monotonic() - start,
                "worker_absent": not runtime.loaded,
            }
        evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
        store.activate(MODEL_ID, selection, evidence, requested=True)
        start = time.monotonic()
        try:
            runtime.qualify(
                store,
                "Text: A synthetic test. Question: Repeat the word test 100 times.",
                requested=True,
                cancel=lambda: time.monotonic() - start >= 0.1,
            )
        except ModelError as exc:
            report["cancel_generation"] = {
                "code": exc.code,
                "seconds": time.monotonic() - start,
                "worker_absent": not runtime.loaded,
            }
        evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
        report["next_caller"] = evidence.result
        start = time.monotonic()
        while runtime.loaded and time.monotonic() - start < 7:
            time.sleep(0.05)
        report["idle_unload"] = {
            "seconds": time.monotonic() - start,
            "worker_absent": not runtime.loaded,
        }
        report["parent_after"] = memory_observation()
        for language in ("en", "it"):
            rows = [r for r in report["samples"] if r["language"] == language]
            score = sum(r["pass"] for r in rows) / len(rows) if rows else 0
            report.setdefault("quality", {})[language] = {
                "score": score,
                "n": len(rows),
                "abstention": all(r["pass"] for r in rows if r["expected"] == "UNKNOWN"),
                "status": "PASS"
                if len(rows) == 30
                and score >= 0.9
                and all(r["pass"] for r in rows if r["expected"] == "UNKNOWN")
                else "FAIL",
            }
        if report["samples"]:
            report["warm_total_median"] = statistics.median(
                r["total_seconds"] for r in report["samples"]
            )
            report["warm_total_max"] = max(r["total_seconds"] for r in report["samples"])
        # No successful offline run substitutes for an OS observation of all phases.
        report["status"] = "BLOCKED_NO_EGRESS_OBSERVATION"
    except Exception as exc:
        report["status"] = "FAIL"
        report["failures"].append(exc.code if isinstance(exc, ModelError) else type(exc).__name__)
    finally:
        if runtime:
            runtime.close()
        save()
    # The corpus and every output are synthetic and public. Preserve raw samples
    # in both the artifact and native job log for an independently readable ledger.
    print("S05_REAL_REPORT=" + json.dumps(report, ensure_ascii=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = measure(args.artifacts.absolute(), args.output)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
