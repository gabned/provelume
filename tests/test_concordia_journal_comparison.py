"""Evidence isolation and stop controls for the one journal application block."""
from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import compare_concordia_journal as comparison
from scripts.ai_runtime_report import evaluate


def test_comparison_refuses_a_second_product_factor():
    after = (Path(__file__).resolve().parents[1] / comparison.ATOMIC).read_bytes()
    before = after.replace(comparison.AFTER, comparison.BEFORE, 1)
    paths = [comparison.ATOMIC, "docs/qualification/concordia-cpu-diagnosis.md",
             "tests/test_atomic_journal_paths.py"]
    comparison.verify_factor(before, after, paths)
    with pytest.raises(ValueError, match="declared factor"):
        comparison.verify_factor(before, after + b"\n# another product change\n", paths)
    with pytest.raises(ValueError, match="uncontrolled"):
        comparison.verify_factor(before, after, [*paths, "core/provelume/ai_runtime.py"])


def report():
    probe = {"capture_seconds": 0.01, "search_seconds": 0.01, "preserved": True,
             "search_found": True, "product_dispatch_blocked": True}
    busy = []
    for index in range(3):
        phase = {"phase": "native_prefill", "request": str(index), "pid": 10,
                 "received": 2}
        busy.append({**probe, "capture_seconds": 2, "worker_observed": True,
                     "concurrency": phase, "inference": phase, "inference_started_at": 1,
                     "probe_started_at": 3, "probe_completed_at": 4})
    return {"failures": [], "deterministic_idle": [dict(probe) for _ in range(3)],
            "deterministic_busy": busy, "status": "FAIL", "network": "PASS"}


@pytest.mark.parametrize("broken", ["preserved", "search_found", "worker_observed",
                                    "product_dispatch_blocked"])
def test_timing_projection_never_masks_correctness_or_worker_failure(broken):
    original = report()
    original["deterministic_busy"][0][broken] = False
    snapshot = copy.deepcopy(original)
    projected = comparison.timing_projection(original)
    assert evaluate(projected)["gates"]["deterministic"] == "FAIL"
    assert original == snapshot


def test_timing_projection_preserves_original_failure_and_idle_denominator():
    original = report()
    evaluate(original)
    snapshot = copy.deepcopy(original)
    projected = comparison.timing_projection(original)
    assert evaluate(projected)["gates"]["deterministic"] == "PASS"
    assert projected["deterministic_idle"] == original["deterministic_idle"]
    assert original == snapshot and original["gates"]["deterministic"] == "FAIL"


def test_missing_probe_does_not_become_complete():
    original = report()
    original["deterministic_busy"].pop()
    assert evaluate(comparison.timing_projection(original))["gates"]["deterministic"] == "NOT_RUN"


@pytest.mark.skipif(os.name != "posix", reason="POSIX owned-process-group timeout")
def test_timeout_reaps_the_owned_child(tmp_path, monkeypatch):
    real_popen = subprocess.Popen
    children = []

    def observe_child(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", observe_child)
    with pytest.raises(subprocess.TimeoutExpired):
        comparison.execute([sys.executable, "-c", "import time; time.sleep(30)"],
                           tmp_path, tmp_path / "execution.log", 0.1)
    assert len(children) == 1 and children[0].poll() is not None
