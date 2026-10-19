"""Bounded synthetic Windows Capture profiling; never supplies a qualification PASS."""

from __future__ import annotations

import argparse
import cProfile
import json
import multiprocessing
import os
import platform
import pstats
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "core"), str(ROOT / "scripts")]

from ai_runtime_report import deterministic_probe  # noqa: E402

from provelume.atomic_commit import _fsync_directory  # noqa: E402
from provelume.service import ProvelumeInstance  # noqa: E402


def cpu_load(stop, ready):
    ready.set()
    while not stop.is_set():
        sum(n * n for n in range(10000))


def profile_probe(instance, number):
    profiler = cProfile.Profile()
    profiler.enable()
    row = deterministic_probe(instance, number)
    profiler.disable()
    stats = pstats.Stats(profiler)
    rows = []
    for (filename, line, name), (primitive, calls, own, total, _callers) in stats.stats.items():
        path = Path(filename)
        try:
            filename = path.relative_to(ROOT).as_posix()
        except ValueError:
            filename = path.name
        rows.append(dict(file=filename, line=line, function=name, calls=calls,
                         primitive_calls=primitive, own_seconds=own, total_seconds=total))
    return {"probe": row, "profile": sorted(rows, key=lambda r: -r["total_seconds"])[:50]}


def diagnose(output):
    if os.name != "nt":
        raise SystemExit("This diagnostic requires actual Windows, never a simulated platform.")
    report = {"status": "DIAGNOSTIC_ONLY", "python": platform.python_version(),
              "platform": platform.platform(), "logical_cpus": os.cpu_count(),
              "clock": vars(time.get_clock_info("monotonic")), "samples": []}
    context = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="capture-diagnostic-") as directory:
        root = Path(directory)
        instance = ProvelumeInstance.initialise(root / "instance")
        stop = context.Event()
        workers = []
        try:
            for mode in ("idle", "two_cpu_workers"):
                if mode != "idle":
                    for _ in range(2):
                        ready = context.Event()
                        worker = context.Process(target=cpu_load, args=(stop, ready))
                        worker.start()
                        workers.append(worker)
                        if not ready.wait(10):
                            raise RuntimeError("CPU diagnostic worker did not start")
                for number in range(3):
                    sample = {"mode": mode, **profile_probe(instance, number)}
                    # The actual Windows function is already a no-op. Compare only
                    # dispatch overhead, with the same twelve calls in both paths.
                    timings = {}
                    for method in ("inline", "pool"):
                        started = time.perf_counter()
                        if method == "pool":
                            with ThreadPoolExecutor(max_workers=4) as executor:
                                pending = [executor.submit(_fsync_directory, root)
                                           for _ in range(12)]
                                for future in pending:
                                    future.result()
                        else:
                            for _ in range(12):
                                _fsync_directory(root)
                        timings[method] = time.perf_counter() - started
                    sample["directory_flush_dispatch_seconds"] = timings
                    report["samples"].append(sample)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        finally:
            stop.set()
            for worker in workers:
                worker.join(10)
                if worker.is_alive():
                    worker.terminate()
                    worker.join()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(diagnose(parser.parse_args().output), indent=2))
