"""S08 real governed synthesis of public fixtures, under the existing OS observer."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path

from ai_runtime_report import deterministic_probe

from provelume.ai_contract import digest
from provelume.ai_runtime_limits import memory_observation
from provelume.ai_setup import AiSetup
from provelume.service import ProvelumeInstance


def measure_synthesis(root, store, runtime):
    corpus_path = Path(__file__).resolve().parents[1] / "tests/fixtures/ai_synthesis_quality.json"
    cases = json.loads(corpus_path.read_bytes())
    # Group task/language pairs for honest same-task cold/warm observations.
    cases.sort(key=lambda c: (c["language"], c["task"] != "summary"))
    instance = ProvelumeInstance.initialise(root / "s08-instance")
    setup = AiSetup(instance, runtime_directory=runtime.directory)
    setup.models, setup.runtime = store, runtime
    setup.save({"mode": "local"}, setup.configuration()["revision"])
    result = {"status": "NOT_RUN", "samples": [], "performance": [],
              "parent_before": memory_observation(),
              "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
              "synthetic_content": True, "live_external": "NOT_RUN",
              "idle": [deterministic_probe(instance, 800+i) for i in range(3)]}

    def activate():
        identity = setup.begin_operation("self_test")
        setup.run_operation(identity)
        if setup.operation["state"] != "completed":
            raise ValueError("s08_self_test_failed")
        if os.name == "nt":
            if (os.environ.get("GITHUB_ACTIONS") != "true"
                    or os.environ.get("S06_WFP_VERIFIED") != "1"):
                raise ValueError("independent_wfp_control_missing")
            setup.local_evidence = digest({
                "control": "verified-ci-exact-interpreter-wfp",
                "self_test": setup.self_test_evidence.public_record(),
            })
        identity = setup.begin_operation("activate")
        setup.run_operation(identity)
        if setup.operation["state"] != "completed":
            raise ValueError("s08_activation_failed")
        setup.enable()

    def preview_case(case):
        source = root / "s08-source"
        source.mkdir(exist_ok=True)
        (source / "note.txt").write_text(case["text"], encoding="utf-8")
        instance.ingest(source)
        document = next(d for d in instance.store.list_canonical("documents")
                        if d.get("title") == "note.txt")
        document = instance.get_document(document["id"])
        version = document["current_version"]["id"]
        bundle = instance.representations.bundles.materialize(
            version, recipe_id="s08-public-text", recipe_version="1",
            recipe_settings={"case": case["id"]},
            output_payloads={"text.txt": ("text/plain", case["text"].encode())},
            implementation={"component": "provelume.core", "component_version": "0.11.0",
                            "adapter": "s08-public-fixture", "adapter_version": "1",
                            "settings": {}}, anchor_targets=({"kind": "page", "page": 1},),
        )
        ref, prepared, _ = setup.synthesis.preview(
            document["id"], bundle["representation_id"],
            bundle["outputs"][0]["id"], case["task"], case["language"])
        return ref, prepared

    try:
        for index, case in enumerate(cases):
            if index % 2 == 0:
                activate()
            ref, prepared = preview_case(case)
            setup.approve(ref)
            job = setup.enqueue(ref)
            adapter = setup.jobs.adapters[prepared[3][0].fingerprint]
            original = adapter.exchange
            reached = threading.Event()
            raw = {}
            started = time.monotonic()

            def exchange(current, *, cancel, started=started, original=original,
                         reached=reached, raw=raw):
                def observe():
                    if runtime._first_received is not None and runtime._first_received >= started:
                        reached.set()
                    return cancel()
                outcome = original(current, cancel=observe)
                raw["candidate"] = getattr(outcome, "result", None)
                return outcome

            adapter.exchange = exchange
            if index == 0:
                runtime.close()
            if index < 2:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(instance.run_ai_job, job["id"])
                    observed = reached.wait(25)
                    busy = runtime.loaded and not future.done()
                    probe = deterministic_probe(instance, 810+index)
                    probe["worker_observed"] = busy and runtime.loaded and not future.done()
                    completed = future.result()
            else:
                completed = instance.run_ai_job(job["id"])
            elapsed = time.monotonic() - started
            adapter.exchange = original
            body = None
            with suppress(ValueError, OSError):
                body = setup.synthesis.read(job["id"])[0]
            valid = body is not None
            abstained = valid and body["status"] == "abstained"
            gold = valid and ((abstained and case["allow_abstention"]) or
                             (not abstained and body["references"] in case["allowed_references"]))
            result["samples"].append({
                "id": case["id"], "language": case["language"], "task": case["task"],
                "status": completed["status"], "valid": valid, "gold": gold,
                "abstained": abstained, "require_abstention": case["require_abstention"],
                "references": body["references"] if body else None,
                "candidate": raw.get("candidate"), "seconds": elapsed,
                "receipt": "receipt_" + job["id"][4:],
            })
            if index < 2:
                observation = runtime.last_observation
                result["performance"].append({
                    "phase": "cold" if index == 0 else "warm", "seconds": elapsed,
                    "first_seconds": observation["first_wall_seconds"]
                    + elapsed - observation["total_seconds"],
                    "worker": observation, "probe": probe, "generation_observed": observed,
                    "status": completed["status"],
                })
            # Continue all cases after an invalid response: this is a distinct manual
            # corpus request, never a retry or removal of the failed observation.
        # Separate explicit cancellation request through the same document path.
        activate()
        ref, prepared = preview_case({**cases[0], "id": "s08-cancel-public"})
        setup.approve(ref)
        job = setup.enqueue(ref)
        adapter = setup.jobs.adapters[prepared[3][0].fingerprint]
        original = adapter.exchange
        reached = threading.Event()
        started = time.monotonic()

        def observe_exchange(current, *, cancel):
            def observe():
                if runtime._first_received is not None and runtime._first_received >= started:
                    reached.set()
                return cancel()
            return original(current, cancel=observe)

        adapter.exchange = observe_exchange
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(instance.run_ai_job, job["id"])
            observed = reached.wait(25)
            cancel_at = time.monotonic()
            setup.jobs.control_job(job["id"], "cancel")
            completed = future.result()
        result["cancellation"] = {
            "generation_observed": observed, "status": completed["status"],
            "seconds": time.monotonic() - cancel_at, "worker_absent": not runtime.loaded,
            "active": setup.jobs.status()["accounting"]["active"],
        }
        result["status"] = "MEASURED"
    except Exception as exc:
        result["status"] = "FAIL"
        result["failure"] = type(exc).__name__
        result["last_observation"] = runtime.last_observation
    finally:
        setup.close()
        result["worker_absent"] = not runtime.loaded
        result["final_off"] = setup.jobs.status()["mode"] == "off"
        result["parent_after"] = memory_observation()
    return result
