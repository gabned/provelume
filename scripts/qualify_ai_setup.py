"""S07 host composition, measured only under the existing native CI observer."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ai_runtime_report import deterministic_probe

from provelume.ai_contract import digest
from provelume.ai_runtime_contract import MODEL_ID
from provelume.ai_setup import AiSetup


def measure_setup(instance, store, runtime):
    setup = AiSetup(instance, runtime_directory=runtime.directory)
    setup.models, setup.runtime = store, runtime
    result = {"samples": [], "synthetic_content": True, "live_external": "NOT_RUN"}
    result["session_off"] = not setup.read()["control"]["session_authorized"]
    setup.save({"mode": "local"}, setup.configuration()["revision"])
    try:
        identity = setup.begin_operation("self_test")
        setup.run_operation(identity)
        if setup.operation["state"] != "completed":
            raise ValueError("self_test_failed")
        if os.name == "nt":
            if (
                os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("S06_WFP_VERIFIED") != "1"
            ):
                raise ValueError("independent_wfp_control_missing")
            # This is the disposable CI observer's authority, never a product
            # boolean, UI input, successful process launch or localhost claim.
            setup.local_evidence = digest(
                {
                    "control": "verified-ci-exact-interpreter-wfp",
                    "self_test": setup.self_test_evidence.public_record(),
                }
            )
        identity = setup.begin_operation("activate")
        setup.run_operation(identity)
        if setup.operation["state"] != "completed":
            raise ValueError("activation_failed")
        setup.enable()
        # A warm user test follows the cold test in the same enabled session.
        # Running another self-test here replaces the native prefix and measures
        # an unrelated prompt transition instead of the intended warm path.
        for phase in ("cold", "warm"):
            ref, prepared = setup.preview_test()
            setup.approve(ref)
            job = setup.enqueue(ref)
            adapter = setup.jobs.adapters[prepared[3][0].fingerprint]
            original = adapter.exchange
            observed = threading.Event()
            started = time.monotonic()

            def exchange(current, *, cancel, started=started, observed=observed, original=original):
                def observe():
                    if runtime._first_received is not None and runtime._first_received >= started:
                        observed.set()
                    return cancel()

                return original(current, cancel=observe)

            adapter.exchange = exchange
            if phase == "cold":
                runtime.close()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(instance.run_ai_job, job["id"])
                reached = observed.wait(25)
                busy_before = runtime.loaded and not future.done()
                probe = deterministic_probe(instance, 700 if phase == "cold" else 701)
                probe["worker_observed"] = busy_before and runtime.loaded and not future.done()
                completed = future.result()
            elapsed = time.monotonic() - started
            adapter.exchange = original
            observation = runtime.last_observation
            result["samples"].append(
                {
                    "phase": phase,
                    "status": completed["status"],
                    "attempts": completed["attempt"],
                    "seconds": elapsed,
                    "binding": completed["ai"]["binding"],
                    "first_seconds": (
                        observation["first_wall_seconds"] + elapsed - observation["total_seconds"]
                    ),
                    "worker": observation,
                    "probe": probe,
                    "generation_observed": reached,
                    "receipt": setup.jobs.journal.list_receipts(limit=100)[0]["id"],
                    "model": MODEL_ID,
                }
            )
        result["status"] = "MEASURED"
    finally:
        setup.close()
        result["worker_absent"] = not runtime.loaded
        result["final_off"] = setup.jobs.status()["mode"] == "off"
    return result
