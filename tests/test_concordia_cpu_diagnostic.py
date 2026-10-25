"""Evidence integrity checks for the optional Linux diagnostic, not timing gates."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("resource")

from scripts import diagnose_concordia_cpu as diagnostic  # noqa: E402


def test_failed_gate_survives_every_observer_evaluation():
    def evaluate(report):
        report["gates"] = {"s06_governed": "FAIL"}
        report["status"] = "FAIL"
        return report

    checked = diagnostic.nonqualifying(evaluate)
    report = {"failures": ["retained_original"]}
    for _ in range(2):
        checked(report)
        assert report == {"gates": {"s06_governed": "FAIL"}, "status": "DIAGNOSTIC_ONLY",
                          "instrumented_evaluated_status": "FAIL",
                          "qualification_eligible": False, "failures": ["retained_original"]}


def test_accounting_retains_operation_error_and_exact_thread():
    context = {"operations": []}
    token = diagnostic.CURRENT.set(context)
    marker = ValueError("retained")

    def fail():
        raise marker

    try:
        with pytest.raises(ValueError) as observed:
            diagnostic.observe_operation(fail, "process")()
    finally:
        diagnostic.CURRENT.reset(token)
    assert observed.value is marker
    row, = context["operations"]
    assert row["before"]["tid"] == row["after"]["tid"]
    assert row["after"]["thread_cpu_ns"] >= row["before"]["thread_cpu_ns"]
    assert row["after"]["monotonic_ns"] >= row["before"]["monotonic_ns"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc diagnostic")
def test_sampler_binds_actual_process_and_retains_unclosed_probe(tmp_path):
    read_pipe, write_pipe = os.pipe()
    output = tmp_path / "timeline.jsonl"
    child = subprocess.Popen([sys.executable, str(Path(diagnostic.__file__)), "sample",
                              "--pipe", str(read_pipe), "--output", str(output)],
                             pass_fds=(read_pipe,))
    os.close(read_pipe)
    try:
        os.write(write_pipe, (json.dumps({"kind": "begin", "probe_id": 7,
                                         "pids": [os.getpid()]}) + "\n").encode())
        time.sleep(0.15)
    finally:
        os.close(write_pipe)
    assert child.wait(timeout=10) == 0
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert rows[0]["event"]["probe_id"] == 7
    samples = [row for row in rows if "tasks" in row]
    assert samples
    assert all(str(os.getpid()) in row["tasks"] for row in samples)
    assert rows[-1] == {"sampler_end": True, "unclosed": [7], "partial_bytes": 0}


@pytest.mark.skipif(sys.platform != "linux", reason="Linux diagnostic worker")
@pytest.mark.parametrize("mode", ["legacy", "boundary", "extended"])
def test_final_network_observer_cannot_requalify_instrumented_capture(tmp_path, monkeypatch, mode):
    # Exercise the real worker and observer import boundaries. No native model is
    # involved; a retained synthetic failure must survive the final evaluator.
    root = Path(diagnostic.__file__).resolve().parents[1]
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.syspath_prepend(str(root / "scripts"))
    import qualify_ai_runtime

    from provelume.service import ProvelumeInstance
    from scripts import ai_runtime_network

    original_observer = ai_runtime_network.observe
    worker_finished = False
    observations = []

    def after_worker_only(*args, **kwargs):
        assert worker_finished, "network observation must follow worker/trace completion"
        observations.append(True)
        return original_observer(*args, **kwargs)

    monkeypatch.setattr(ai_runtime_network, "observe", after_worker_only)

    def synthetic_measure(artifacts, _output):
        instance = ProvelumeInstance.initialise(artifacts / "instance")
        probe = qualify_ai_runtime.deterministic_probe(instance, 0)
        return qualify_ai_runtime.evaluate({"samples": [], "deterministic_idle": [probe],
                                            "failures": ["synthetic_retained_failure"]})

    monkeypatch.setattr(qualify_ai_runtime, "measure", synthetic_measure)
    output = tmp_path / "output"
    output.mkdir()
    diagnostic.worker(root, tmp_path / "artifacts", output, mode)
    assert observations == []
    assert not (output / "report.json").exists()
    worker_finished = True
    diagnostic.observe(root, output)
    assert observations == [True]
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "DIAGNOSTIC_ONLY"
    assert report["qualification_eligible"] is False
    assert report["instrumented_evaluated_status"] == "FAIL"
    assert report["failures"] == ["synthetic_retained_failure"]
    assert report["network"] == "NOT_RUN"
    probe, = report["deterministic_idle"]
    assert probe["preserved"] and probe["search_found"]
    operations = [r["operation"] for r in probe["diagnostic_timeline"]["operations"]]
    assert operations == ["submit", "process"]
    assert (output / "timeline.jsonl").exists() is (mode != "boundary")
    if mode != "legacy":
        context = probe["diagnostic_timeline"]
        assert context["observation_mode"] == mode
        assert context["durability"]
        for row in context["operations"]:
            before, after = row["boundary_before"], row["boundary_after"]
            assert before["finished_ns"] <= row["before"]["monotonic_ns"]
            assert row["after"]["monotonic_ns"] <= after["started_ns"]
            expected = [r for r in before["tasks"] if r["tid"] == row["before"]["tid"]]
            assert len(expected) == 1
            assert isinstance(expected[0]["schedstat"], (str, dict))
        assert all(row["started_ns"] <= row["finished_ns"] for row in context["durability"])


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc counters")
def test_missing_boundary_role_stays_unknown():
    counters = diagnostic.BoundaryCounters({"exited": [999_999_999]})
    try:
        assert counters.inventory == [{"role": "exited", "pid": 999_999_999,
                                        "tasks": 0, "status": "UNKNOWN"}]
        assert counters.snapshot()["tasks"] == []
    finally:
        counters.close()


def test_durability_wrapper_retains_exception_and_commit_thread():
    from concurrent.futures import ThreadPoolExecutor

    context = {"durability": [], "active_operation": "process"}
    marker = OSError("retained fsync failure")

    def fail(_fd):
        raise marker

    wrapped = diagnostic.durability_observer(fail, "fsync", lambda: context)
    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(OSError) as observed:
        pool.submit(wrapped, 123).result()
    assert observed.value is marker
    row, = context["durability"]
    assert row["operation"] == "process" and row["call"] == "fsync"
    assert row["tid"] != diagnostic.threading.get_native_id()
    assert (row["wrapper_started_ns"] <= row["started_ns"]
            <= row["finished_ns"] <= row["wrapper_finished_ns"])
