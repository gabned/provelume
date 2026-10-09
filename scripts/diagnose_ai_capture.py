"""Bounded synthetic Capture phase attribution, never qualification evidence."""

from __future__ import annotations

import cProfile
import pstats
import threading
import time
from pathlib import Path

from ai_runtime_report import deterministic_probe

from provelume.ai_models import ModelError
from provelume.ai_runtime import native_selection
from provelume.ai_runtime_contract import MODEL_ID


def diagnose(instance, store, runtime):
    # Called only after every scored sample and parent-memory observation. Function
    # aggregates use module basenames, never host paths, document text or arguments.
    result = {"status": "DIAGNOSTIC_ONLY", "synthetic_content": True, "samples": []}
    try:
        selection = native_selection()
        evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
        store.activate(MODEL_ID, selection, evidence, requested=True)
        model = store.verify(MODEL_ID, selection)
        for busy in (False, True):
            for number in range(3):
                cancelled, started = threading.Event(), threading.Event()

                def generate(started=started, cancelled=cancelled):
                    start = time.monotonic()

                    def cancel():
                        if runtime._first_received is not None and runtime._first_received >= start:
                            started.set()
                        return cancelled.is_set()

                    try:
                        runtime._infer(model, selection,
                            "Text: The synthetic word is orchid. "
                            "Question: Repeat orchid 100 times.", cancel=cancel)
                    except ModelError as exc:
                        result.setdefault("worker_outcomes", []).append(exc.code)

                thread = threading.Thread(target=generate) if busy else None
                try:
                    if thread:
                        thread.start()
                        started.wait(20)
                    observed = bool(thread and thread.is_alive() and started.is_set())
                    profile = cProfile.Profile()
                    probe = profile.runcall(deterministic_probe, instance, 900 + number)
                    observed &= bool(thread and thread.is_alive())
                    functions = []
                    for (path, line, name), (primitive, calls, own, cumulative, _) in (
                            pstats.Stats(profile).stats.items()):
                        if Path(path).suffix == ".py" or path == "~":
                            functions.append({
                                "module": Path(path).name, "line": line, "function": name,
                                "calls": calls, "primitive_calls": primitive,
                                "own_seconds": own, "cumulative_seconds": cumulative,
                            })
                    functions.sort(key=lambda row: row["cumulative_seconds"], reverse=True)
                    result["samples"].append({"phase": "busy" if busy else "idle",
                        "worker_observed": observed, "probe": probe, "functions": functions[:40]})
                finally:
                    cancelled.set()
                    if thread:
                        thread.join(2)
                        if thread.is_alive():
                            runtime.close()
                            thread.join(2)
                            raise ValueError("diagnostic_worker_cleanup")
        return result
    except Exception as exc:
        result["failure"] = type(exc).__name__
        return result
    finally:
        runtime.close()
