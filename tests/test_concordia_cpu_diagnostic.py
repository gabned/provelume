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
@pytest.mark.parametrize("mode,placement", [("legacy", None), ("boundary", None),
                                         ("extended", None), ("boundary", "same_logical")])
def test_final_network_observer_cannot_requalify_instrumented_capture(
    tmp_path, monkeypatch, mode, placement
):
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
    if placement is not None:
        # Exercise real affinity/task wiring on this host, without claiming that
        # a synthetic plan qualifies its hardware as SMT.
        allowed = sorted(os.sched_getaffinity(0))
        monkeypatch.setattr(diagnostic, "smt_plan", lambda: {
            "allowed": allowed, "same_logical": allowed[0], "worker_cpus": [],
        })
    output = tmp_path / "output"
    output.mkdir()
    diagnostic.worker(root, tmp_path / "artifacts", output, mode, placement)
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
        if placement is not None:
            assert context["pool_tasks"]
            assert all(t["affinity"] == [allowed[0]] for t in context["pool_tasks"])
            assert context["placement"]["restored"] == allowed
            assert all(row["boundary_before"]["cgroups"] is not None
                       for row in context["operations"])


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


def test_smt_plan_requires_real_siblings_in_the_inherited_mask(tmp_path):
    for cpu, core in enumerate([0, 0, 1, 1, 2]):
        root = tmp_path / f"cpu{cpu}" / "topology"
        root.mkdir(parents=True)
        (root / "physical_package_id").write_text("0\n")
        (root / "core_id").write_text(str(core))
    assert diagnostic.smt_plan({0, 1, 2, 3}, tmp_path) == {
        "allowed": [0, 1, 2, 3], "cores": [[0, 1], [2, 3]], "worker_cpus": [0, 2],
        "same_logical": 0, "smt_sibling": 1,
    }
    with pytest.raises(ValueError, match="two physical cores"):
        diagnostic.smt_plan({0, 1, 2, 4}, tmp_path)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux affinity diagnostic")
def test_probe_placement_restores_actual_mask_and_exception():
    original = os.sched_getaffinity(0)
    cpu = min(original)
    marker = ValueError("original probe error")
    context = {}
    with pytest.raises(ValueError) as observed, diagnostic.place_probe(
        context, "same_logical", {"allowed": sorted(original), "same_logical": cpu}, []
    ):
        assert os.sched_getaffinity(0) == {cpu}
        raise marker
    assert observed.value is marker
    assert os.sched_getaffinity(0) == original
    assert context["placement"]["restored"] == sorted(original)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux affinity diagnostic")
def test_probe_placement_refuses_a_different_worker_pair():
    original = sorted(os.sched_getaffinity(0))
    with pytest.raises(RuntimeError, match="worker_affinity"), diagnostic.place_probe(
        {}, "same_logical", {"allowed": original, "worker_cpus": []}, [os.getpid()]
    ):
        pytest.fail("mismatched worker must not execute a probe")
    assert sorted(os.sched_getaffinity(0)) == original


@pytest.mark.skipif(sys.platform != "linux", reason="Linux per-task counters")
def test_pool_observer_retains_new_task_counters_result_and_error(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    context = {"pool_tasks": [], "active_operation": "process"}
    token = diagnostic.CURRENT.set(context)
    monkeypatch.setattr(ThreadPoolExecutor, "submit",
                        diagnostic.pool_observer(ThreadPoolExecutor.submit))
    marker = OSError("original task error")

    def fail():
        raise marker

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(lambda value: value + 1, 6).result() == 7
            with pytest.raises(OSError) as observed:
                pool.submit(fail).result()
            assert observed.value is marker
    finally:
        diagnostic.CURRENT.reset(token)
    assert len(context["pool_tasks"]) == 2
    for row in context["pool_tasks"]:
        assert row["operation"] == "process"
        assert row["before"]["tid"] != diagnostic.threading.get_native_id()
        assert row["before"]["tid"] == row["after"]["tid"]
        assert len(row["counters_after"]["schedstat"].split()) == 3
        assert row["queued_ns"] <= row["wrapper_started_ns"]
        assert row["before"]["monotonic_ns"] <= row["after"]["monotonic_ns"]
        assert row["after"]["monotonic_ns"] <= row["wrapper_finished_ns"]


def test_original_cpu_requirement_refuses_a_different_reported_model(tmp_path):
    path = tmp_path / "cpuinfo"
    path.write_text("model name\t: AMD EPYC 9V74 80-Core Processor\n" * 4)
    assert diagnostic.require_original_cpu(path) == ["AMD EPYC 9V74 80-Core Processor"]
    path.write_text("model name\t: AMD EPYC 9V45 96-Core Processor\n" * 4)
    with pytest.raises(ValueError, match="original EPYC"):
        diagnostic.require_original_cpu(path)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux tracer affinity diagnostic")
def test_real_tracer_stays_pinned_while_child_and_capture_get_their_own_masks(tmp_path):
    import shutil

    if shutil.which("strace") is None or shutil.which("taskset") is None:
        pytest.skip("strace/taskset is unavailable")
    allowed = sorted(os.sched_getaffinity(0))
    if len(allowed) < 2:
        pytest.skip("two allowed CPUs required for the observer control")
    tracer, foreground = allowed[:2]
    root = Path(diagnostic.__file__).resolve().parents[1]
    output = tmp_path / "output"
    output.mkdir()
    script = tmp_path / "synthetic.py"
    script.write_text(f'''
import json, os, sys
from pathlib import Path
sys.path[:0] = [{str(root)!r}, {str(root / "scripts")!r}, {str(root / "core")!r}]
from scripts import diagnose_concordia_cpu as diagnostic
import qualify_ai_runtime
from provelume.service import ProvelumeInstance
def measure(artifacts, output):
    instance = ProvelumeInstance.initialise(artifacts / "instance")
    probe = qualify_ai_runtime.deterministic_probe(instance, 0)
    return qualify_ai_runtime.evaluate({{"samples": [], "deterministic_idle": [probe],
                                        "failures": ["synthetic_retained_failure"]}})
qualify_ai_runtime.measure = measure
# Synthetic wiring control only; this does not qualify this host as SMT.
diagnostic.smt_plan = lambda: {{"allowed": {allowed!r}, "smt_sibling": {foreground},
                               "worker_cpus": []}}
diagnostic.worker(Path({str(root)!r}), Path({str(tmp_path / "artifacts")!r}),
                  Path({str(output)!r}), "boundary", "smt_sibling", {set(allowed)!r}, {tracer})
assert os.sched_getaffinity(0) == {set(allowed)!r}
''')
    observed = subprocess.run(
        ["taskset", "--cpu-list", str(tracer), "strace", "-ff", "-e", "trace=network",
         "-o", str(tmp_path / "network"),
         sys.executable, str(script)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20,
    )
    assert observed.returncode == 0, observed.stdout
    report = json.loads((output / "report-before-observer.json").read_text())
    context = report["deterministic_idle"][0]["diagnostic_timeline"]
    assert context["tracer_affinity"] == [tracer]
    assert context["placement"]["cpu"] == foreground
    assert context["placement"]["inherited"] == allowed
    assert context["placement"]["restored"] == allowed
    assert context["pool_tasks"]
    assert all(task["affinity"] == [foreground] for task in context["pool_tasks"])
    assert report["qualification_eligible"] is False
