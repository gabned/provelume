"""Real S05 candidate measurements; synthetic corpus, explicit acquisition first."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from ai_runtime_report import deterministic_probe, evaluate  # noqa: E402

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
from provelume.service import ProvelumeInstance  # noqa: E402


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
        "product_dispatch": "governed_job_required",
        "recommended": False,
        "s06_required": True,
        "s07_required": True,
        "s08_required": True,
    }

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    runtime = None
    try:
        report["source_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
        report["configuration_sha256"] = hashlib.sha256(
            native_selection().configuration).hexdigest()
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
            MODEL_ID, root / "model.gguf", selection, requested=True, license_accepted="Apache-2.0"
        )
        corpus_path = ROOT / "tests/fixtures/ai_runtime_quality.json"
        report["corpus_sha256"] = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        instance = ProvelumeInstance.initialise(root / "synthetic-instance")
        report["deterministic_idle"] = [deterministic_probe(instance, n) for n in range(3)]
        for cold_run in range(3):
            runtime.close()
            evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
            report.setdefault("self_tests", []).append(evidence.public_record())
            report.setdefault("cold", []).append(runtime.last_observation)
            if evidence.result != "PASSED":
                report["failures"].append("self_test:" + evidence.result)
                break
            store.activate(MODEL_ID, selection, evidence, requested=True)
            model = store.verify(MODEL_ID, selection)
            outcome = []

            def generate(model=model, outcome=outcome):
                try:
                    outcome.append(runtime._infer(model, selection,
                        "Text: The synthetic word is orchid. Question: Repeat orchid 100 times."))
                except ModelError as exc:
                    report["failures"].append(exc.code)

            thread = threading.Thread(target=generate)
            thread.start()
            time.sleep(0.02)
            row = deterministic_probe(instance, cold_run)
            row["worker_observed"] = runtime.loaded and thread.is_alive()
            report.setdefault("deterministic_busy", []).append(row)
            thread.join()  # Runtime's single canonical operation deadline owns termination.
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
        model = store.verify(MODEL_ID, selection)
        start = time.monotonic()
        try:
            runtime._infer(
                model,
                selection,
                "Text: A synthetic test. Question: Repeat the word test 100 times.",
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
        # A real worker error, followed by termination, is part of the network
        # observation and cleanup protocol (the prompt exceeds the token ceiling).
        model = store.verify(MODEL_ID, selection)
        try:
            runtime._infer(model, selection, " a" * 2048)
        except ModelError as exc:
            report["worker_error"] = {"code": exc.code, "worker_absent": not runtime.loaded}
        from qualify_ai_jobs import measure_jobs

        evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
        store.activate(MODEL_ID, selection, evidence, requested=True)
        report["s06"] = measure_jobs(instance, store, runtime)
        from qualify_ai_setup import measure_setup

        report["s07"] = measure_setup(instance, store, runtime)
        from qualify_ai_synthesis import measure_synthesis

        report["s08"] = measure_synthesis(root, store, runtime)
        # Change one byte only in this disposable installed test model, then restore
        # in finally; no acquisition, fallback or fabricated evidence on corruption.
        model = store.verify(MODEL_ID, selection)
        with model.model.path.open("rb") as stream:
            stream.seek(128)
            original = stream.read(1)
        try:
            with model.model.path.open("r+b") as stream:
                stream.seek(128)
                stream.write(bytes([original[0] ^ 1]))
                stream.flush()
            try:
                store.verify(MODEL_ID, selection)
            except ModelError as exc:
                report["altered_model"] = exc.code
        finally:
            with model.model.path.open("r+b") as stream:
                stream.seek(128)
                stream.write(original)
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
        from diagnose_ai_capture import diagnose

        report["capture_diagnostic"] = diagnose(instance, store, runtime)
    except Exception as exc:
        report["status"] = "FAIL"
        report["failures"].append(exc.code if isinstance(exc, ModelError) else type(exc).__name__)
        report["last_observation"] = runtime.last_observation if runtime else None
    finally:
        if runtime:
            runtime.close()
            report["worker_pids"] = runtime.worker_history
        evaluate(report)
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
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
