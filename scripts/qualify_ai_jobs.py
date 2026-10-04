"""S06 native governed execution on public fixtures; called by the S05 observer."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from ai_context_fakes import context_plan  # noqa: E402
from ai_jobs_fakes import REF, inputs_for  # noqa: E402
from ai_runtime_report import deterministic_probe  # noqa: E402

from provelume.ai_context import preview_context  # noqa: E402
from provelume.ai_contract import Limits, digest  # noqa: E402
from provelume.ai_job_contract import Budget  # noqa: E402
from provelume.ai_job_runtime import NativeConfig, NativeJobAdapter  # noqa: E402
from provelume.ai_runtime import native_selection  # noqa: E402
from provelume.ai_runtime_contract import MODEL_ID, MODEL_SHA256, RUNTIME_ID  # noqa: E402
from provelume.ai_runtime_limits import memory_observation  # noqa: E402


def native_inputs(instance, proof, *, text=None):
    base = inputs_for(instance.store.read_config()["instance"]["id"], text=text)
    config = NativeConfig()
    limits = Limits(4096, 128, 2, 60)
    profile = replace(
        base.profiles[0],
        provider=RUNTIME_ID,
        model=MODEL_ID,
        revision=MODEL_SHA256,
        route_revision=config.fingerprint,
        limits=limits,
    )
    evidence = replace(
        base.evidence[0],
        profile_fingerprint=profile.fingerprint,
        qualification_revision=digest(proof),
    )
    current = dict(base.current)
    current["request_limits"] = limits
    current["rules"] = tuple(
        replace(
            r,
            limits=limits if r.limits else None,
            allowed_profiles=(profile.id,) if r.allowed_profiles else None,
        )
        for r in current["rules"]
    )
    preview = preview_context(base.source, base.selections, **current)
    gateway = {"profiles": (profile,), "evidence": (evidence,)}
    plan = context_plan(preview, base.source, base.selections, current, gateway)
    return replace(base, current=current, preview=preview, plan=plan, config=config, **gateway)


def measure_jobs(instance, store, runtime):
    """Real bytes, worker, scheduler, gateway, reservation and durable completion.

    The locality grant comes from independently applied host controls. Linux's
    previous real self-test must report actual seccomp containment. Windows's
    disposable CI controller must have checked the exact interpreter WFP rule.
    External observation of every worker remains a separate mandatory final gate.
    """
    proof = runtime.last_observation["load"]["limits"]
    if os.name == "nt":
        if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("S06_WFP_VERIFIED") != "1":
            return {"status": "BLOCKED", "reason": "independent_wfp_control_missing"}
        proof = {**proof, "network_control": "verified-ci-exact-interpreter-wfp"}
    elif proof.get("network_control") != "seccomp:socket-syscalls-EPERM":
        return {"status": "BLOCKED", "reason": "seccomp_control_missing"}
    inputs = native_inputs(instance, proof)
    adapter = NativeJobAdapter(runtime, store)
    jobs = instance.bind_ai_execution(
        current=lambda ref, route: replace(inputs, route_index=route),
        adapters={inputs.profiles[0].fingerprint: adapter},
    )
    budget = Budget(4224 * 2, 4224 * 20, job_micros=0, period_micros=0)
    off = jobs.status()["mode"] == "off"
    jobs.configure(mode="enabled", budget=budget)
    result = {
        "default_off": off,
        "locality_control_fingerprint": digest(proof),
        "binding": inputs.plan.binding,
        "samples": [],
        "cancellations": [],
        "deterministic_busy": [],
        "parent_before": memory_observation(),
    }
    selection = native_selection()
    original_exchange = adapter.exchange
    sample_start = 0
    sample_observed = False
    polling = {}

    def observed_exchange(current, *, cancel):
        def observe():
            nonlocal sample_observed
            if (
                not sample_observed
                and runtime._first_received is not None
                and runtime._first_received >= sample_start
            ):
                sample_observed = True
                probe = deterministic_probe(instance, len(result["deterministic_busy"]))
                probe["worker_observed"] = runtime.loaded
                result["deterministic_busy"].append(probe)
            started = time.monotonic()
            cpu = time.thread_time()
            try:
                return cancel()
            finally:
                polling["calls"] += 1
                polling["seconds"] += time.monotonic() - started
                polling["cpu_seconds"] += time.thread_time() - cpu

        return original_exchange(current, cancel=observe)

    adapter.exchange = observed_exchange

    def refresh():
        evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
        store.activate(MODEL_ID, selection, evidence, requested=True)

    def execute(key):
        nonlocal sample_start, sample_observed, polling
        job = jobs.enqueue(REF, request_key=key, budget=budget)
        started = time.monotonic()
        sample_start, sample_observed = started, False
        polling = {"calls": 0, "seconds": 0, "cpu_seconds": 0}
        completed = jobs.coordinator.run_one(job_id=job["id"])
        return completed, time.monotonic() - started

    for index in range(3):
        refresh()
        runtime.close()
        for phase in ("cold", "warm"):
            inputs = native_inputs(instance, proof, text=(
                None if phase == "cold" else
                f"Contact ada@example.test, code PRIVATE.\fSecond page. Public variant {index}."))
            job, elapsed = execute(f"s06-{phase}-{index}")
            row = job["ai"]["attempts"][-1]
            result["samples"].append(
                {
                    "phase": phase,
                    "status": job["status"],
                    "job_id": job["id"],
                    "attempts": job["attempt"],
                    "seconds": elapsed,
                    # Include admission and persistence overhead conservatively.
                    "first_seconds": (
                        runtime.last_observation["first_wall_seconds"]
                        + elapsed
                        - runtime.last_observation["total_seconds"]
                    ),
                    "consumption": {k: row[k] for k in ("units", "micros", "usage_source")},
                    "result_fingerprint": job["ai"]["result_fingerprint"],
                    "binding": inputs.plan.binding,
                    "worker": runtime.last_observation,
                    "adapter_phases": adapter.last_observation,
                    "authority_polling": dict(polling),
                }
            )
    adapter.exchange = original_exchange
    for phase in ("load", "generation"):
        refresh()
        if phase == "load":
            runtime.close()
        job = jobs.enqueue(REF, request_key="s06-cancel-" + phase, budget=budget)
        interrupted = []
        attempt_start = time.monotonic()

        def exchange(
            current,
            *,
            cancel,
            job=job,
            phase=phase,
            interrupted=interrupted,
            attempt_start=attempt_start,
        ):
            def stop():
                reached = runtime._process is not None and (
                    runtime._load is None
                    if phase == "load"
                    else runtime._first_received is not None
                    and runtime._first_received >= attempt_start
                )
                if reached and not interrupted:
                    interrupted.append(time.monotonic())
                    jobs.control_job(job["id"], "cancel")
                return cancel()

            return original_exchange(current, cancel=stop)

        adapter.exchange = exchange
        completed = jobs.coordinator.run_one(job_id=job["id"])
        result["cancellations"].append(
            {
                "phase": phase,
                "status": completed["status"],
                "seconds": time.monotonic() - interrupted[0] if interrupted else None,
                "worker_absent": not runtime.loaded,
                "active": jobs.status()["accounting"]["active"],
            }
        )
    adapter.exchange = original_exchange
    refresh()
    completed, _ = execute("s06-next-caller")
    result["next_caller"] = completed["status"]
    result["receipt_count"] = len(
        [r for r in jobs.journal.list_receipts() if r["job_kind"] == "ai.execute"]
    )
    jobs.configure(mode="off")
    result["final_off"] = jobs.status()["mode"] == "off"
    idle_started = time.monotonic()
    while runtime.loaded and time.monotonic() - idle_started < 7:
        time.sleep(0.05)
    result["idle_unload"] = {
        "seconds": time.monotonic() - idle_started,
        "worker_absent": not runtime.loaded,
    }
    runtime.close()
    result["worker_absent"] = not runtime.loaded
    result["parent_after"] = memory_observation()
    result["status"] = "MEASURED"  # External native observer decides the final gate.
    return result
