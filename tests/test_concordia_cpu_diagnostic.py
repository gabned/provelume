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


def test_direct_span_preserves_exception_and_binds_the_actual_caller():
    context = {"spans": [], "active_operation": "process"}
    token = diagnostic.CURRENT.set(context)
    marker = ValueError("original")
    try:
        with pytest.raises(ValueError) as observed:
            diagnostic.observe_span(lambda: (_ for _ in ()).throw(marker), "_shutdown_pool")()
    finally:
        diagnostic.CURRENT.reset(token)
    assert observed.value is marker
    row, = context["spans"]
    assert row["operation"] == "process" and row["error"] == "ValueError"
    assert row["before"]["tid"] == row["after"]["tid"]
    assert row["before"]["monotonic_ns"] <= row["after"]["monotonic_ns"]
    assert row["before"]["thread_cpu_ns"] <= row["after"]["thread_cpu_ns"]


def test_prefix_stops_before_any_run1_warm_case_and_preserves_earlier_failures():
    calls = []

    def warm(*args):
        calls.append(args[-1])
        return "forwarded"

    wrapped = diagnostic.prefix_warm_case(warm)
    report = {"samples": [{"pass": True}] * 20,
              "deterministic_busy": [{"worker_observed": True}], "failures": []}
    assert wrapped(report, None, None, None, None, None, 0) == "forwarded"
    report["deterministic_busy"].append({"worker_observed": True})
    with pytest.raises(diagnostic.PrefixStop) as stopped:
        wrapped(report, None, None, None, None, None, 1)
    assert stopped.value.reason == "TARGET_PREFIX_COMPLETE" and calls == [0]
    report["failures"].append("original_failure")
    with pytest.raises(diagnostic.PrefixStop) as stopped:
        wrapped(report, None, None, None, None, None, 1)
    assert stopped.value.reason == "APPLICATION_FAILURE"
    assert report["failures"] == ["original_failure"] and calls == [0]


@pytest.mark.parametrize("busy", [[], [{"worker_observed": False}]])
def test_prefix_stops_before_run0_warm_work_if_first_concurrency_is_missing(busy):
    report = {"samples": [], "deterministic_busy": busy, "failures": []}
    with pytest.raises(diagnostic.PrefixStop) as stopped:
        diagnostic.prefix_warm_case(lambda *a: pytest.fail("must not start warm work"))(
            report, None, None, None, None, None, 0)
    assert stopped.value.reason == "MISSING_CONCURRENCY" and not report["samples"]


@pytest.mark.parametrize("change,reason", [
    ("missing_case", "INCOMPLETE_PREFIX"), ("missing_concurrency", "MISSING_CONCURRENCY"),
])
def test_prefix_refuses_incomplete_boundary(change, reason):
    report = {"samples": [{}] * 20, "deterministic_busy": [{"worker_observed": True}] * 2}
    if change == "missing_case":
        report["samples"].pop()
    else:
        report["deterministic_busy"] = [{"worker_observed": True}, {"worker_observed": False}]
    with pytest.raises(diagnostic.PrefixStop) as stopped:
        diagnostic.prefix_warm_case(lambda *a: pytest.fail("must stop"))(
            report, None, None, None, None, None, 1)
    assert stopped.value.reason == reason


def test_prefix_self_test_retains_failed_evidence():
    class Evidence:
        result = "FAILED"

        def public_record(self):
            return {"result": self.result, "original": "preserved"}

    with pytest.raises(diagnostic.PrefixStop) as stopped:
        diagnostic.prefix_self_test(lambda: Evidence())()
    assert stopped.value.reason == "SELF_TEST_FAILED"
    assert stopped.value.evidence == {"result": "FAILED", "original": "preserved"}


def test_prefix_environment_omits_operator_credentials_without_changing_host_home(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "synthetic-private")
    monkeypatch.setenv("HTTPS_PROXY", "synthetic-private-proxy")
    original_home = os.environ.get("HOME")
    environment = diagnostic.prefix_environment()
    assert "GH_TOKEN" not in environment and "HTTPS_PROXY" not in environment
    assert environment.get("HOME") == original_home == os.environ.get("HOME")
    assert environment["PYTHONNOUSERSITE"] == "1"


def test_prefix_worker_preserves_original_finalization_and_partial_network_gate(
    tmp_path, monkeypatch
):
    root = Path(diagnostic.__file__).resolve().parents[1]
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.syspath_prepend(str(root / "scripts"))
    import qualify_ai_runtime

    finalized = []

    def evaluate(report):
        report.update(status="FAIL", gates={"retained": "FAIL"})
        return report

    def measure(artifacts, output):
        report = {"samples": [{"pass": True, "total_seconds": 1, "memory": {"peak_rss": 1}}] * 20,
                  "deterministic_busy": [{"worker_observed": True}] * 2, "failures": []}
        try:
            qualify_ai_runtime.measure_warm_case(report, None, None, None, None, None, 1)
            pytest.fail("prefix must not execute run1 warm case")
        finally:
            finalized.append(True)
            qualify_ai_runtime.evaluate(report)
            output.write_text(json.dumps(report))

    monkeypatch.setattr(qualify_ai_runtime, "measure", measure)
    monkeypatch.setattr(qualify_ai_runtime, "evaluate", evaluate)
    diagnostic.worker(root, tmp_path, tmp_path, mode="boundary", pool_accounting=True,
                      pool_prefix=True)
    assert finalized == [True]
    report = json.loads((tmp_path / "report-before-observer.json").read_text())
    assert report["instrumented_evaluated_status"] == "FAIL"
    assert report["gates"] == {"retained": "FAIL"}
    state = json.loads((tmp_path / "prefix-state.json").read_text())
    assert state["stop"] == "TARGET_PREFIX_COMPLETE"
    diagnostic.observe(root, tmp_path)
    observed = json.loads((tmp_path / "report.json").read_text())
    assert observed["network"] == "NOT_RUN"
    assert observed["network_observation"]["complete_phases"] is False
    assert observed["qualification_eligible"] is False


@pytest.mark.parametrize("mode,pool", [("legacy", True), ("extended", True), ("boundary", False)])
def test_prefix_requires_its_observation_contract_before_source_import(tmp_path, mode, pool):
    with pytest.raises(ValueError, match="boundary accounting"):
        diagnostic.worker(tmp_path, tmp_path, tmp_path, mode=mode,
                          pool_accounting=pool, pool_prefix=True)


@pytest.mark.parametrize("explode", [False, True])
def test_full_span_worker_forwards_later_cases_and_restores_methods_on_failure(
    tmp_path, monkeypatch, explode
):
    root = Path(diagnostic.__file__).resolve().parents[1]
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.syspath_prepend(str(root / "scripts"))
    import qualify_ai_runtime

    from provelume.atomic_commit import AtomicInstanceCommit

    original_prepare = AtomicInstanceCommit._prepare
    forwarded, finalized = [], []

    def warm(*args):
        forwarded.append(True)
        if explode:
            raise ValueError("application failure retained")
        return "later phase reached"

    def evaluate(report):
        report.update(status="FAIL", gates={"s06_governed": "FAIL"})
        return report

    def measure(artifacts, output):
        report = {"failures": []}
        try:
            assert AtomicInstanceCommit._prepare is not original_prepare
            assert qualify_ai_runtime.measure_warm_case(1) == "later phase reached"
        finally:
            finalized.append(True)
            qualify_ai_runtime.evaluate(report)
            output.write_text(json.dumps(report))
        return report

    monkeypatch.setattr(qualify_ai_runtime, "measure_warm_case", warm)
    monkeypatch.setattr(qualify_ai_runtime, "measure", measure)
    monkeypatch.setattr(qualify_ai_runtime, "evaluate", evaluate)
    if explode:
        with pytest.raises(ValueError, match="application failure retained"):
            diagnostic.worker(root, tmp_path, tmp_path, mode="boundary",
                              pool_accounting=True, caller_spans=True)
    else:
        diagnostic.worker(root, tmp_path, tmp_path, mode="boundary",
                          pool_accounting=True, caller_spans=True)
    assert forwarded == finalized == [True]
    assert AtomicInstanceCommit._prepare is original_prepare
    assert not (tmp_path / "prefix-state.json").exists()
    report = json.loads((tmp_path / "report-before-observer.json").read_text())
    assert report["gates"] == {"s06_governed": "FAIL"}
    assert report["status"] == "DIAGNOSTIC_ONLY"
    assert report["qualification_eligible"] is False


def test_prefix_requires_explicit_current_source_before_acquisition(tmp_path):
    with pytest.raises(ValueError, match="explicit observer source"):
        diagnostic.run(tmp_path, tmp_path / "missing", tmp_path / "output",
                       observer_study=True, pool_prefix=True)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("prefix,source", [(False, None), (True, "f" * 40)])
def test_full_caller_spans_require_their_own_explicit_admission(tmp_path, prefix, source):
    with pytest.raises(ValueError, match="one explicit full observer source"):
        diagnostic.run(tmp_path, tmp_path / "missing", tmp_path / "output",
                       observer_study=True, observer_revision=source,
                       pool_prefix=prefix, caller_spans=True)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("options", [
    {"mode": "extended", "pool_accounting": True},
    {"mode": "boundary", "pool_accounting": False},
    {"mode": "boundary", "pool_accounting": True, "pool_prefix": True},
])
def test_full_caller_spans_refuse_incompatible_observation_before_import(tmp_path, options):
    with pytest.raises(ValueError, match="caller spans require"):
        diagnostic.worker(tmp_path, tmp_path, tmp_path, caller_spans=True, **options)


@pytest.mark.parametrize("defect", [None, "network_claim", "network_call", "span", "tid", "exit"])
def test_prefix_collection_never_promotes_partial_or_missing_observations(tmp_path, defect):
    counter = {"schedstat": "1 0 1", "io": "rchar: 0"}
    rows = []
    for index in range(5):
        operations, spans = [], []
        for name in ["submit", "process"]:
            boundary = {"tasks": [{"role": "parent", "tid": 42, **counter}]}
            operations.append({"operation": name,
                "before": {"tid": 42, "monotonic_ns": 100},
                "after": {"tid": 42, "monotonic_ns": 900},
                "boundary_before": boundary, "boundary_after": boundary})
            for method in ["_prepare", "_publish_entries", "_shutdown_pool"]:
                spans.append({"span": method, "operation": name,
                              "before": {"tid": 42, "monotonic_ns": 200},
                              "after": {"tid": 42, "monotonic_ns": 300}})
        rows.append({"probe_id": index + 1, "operations": operations, "spans": spans,
                     "pool_tasks": [{"counters_before": counter, "counters_after": counter}]})
    report = {"status": "DIAGNOSTIC_ONLY", "qualification_eligible": False,
              "instrumented_evaluated_status": "FAIL", "failures": [],
              "network": "NOT_RUN", "network_observation": {"complete_phases": False},
              "deterministic_idle": [{"preserved": True, "search_found": True}] * 3,
              "deterministic_busy": [{"preserved": True, "search_found": True,
                                      "worker_observed": True}] * 2,
              "samples": [{"pass": True}] * 20, "worker_pids": [42]}
    trace = "1.000000 +++ exited with 0 +++\n"
    if defect == "network_claim":
        report["network"] = "PASS"
    elif defect == "network_call":
        trace = "1.000000 socket(AF_INET, SOCK_STREAM, 0) = 3\n" + trace
    elif defect == "span":
        rows[0]["spans"].pop()
    elif defect == "tid":
        rows[0]["spans"][0]["after"]["tid"] = 99
    elif defect == "exit":
        trace = ""
    (tmp_path / "report.json").write_text(json.dumps(report))
    (tmp_path / "prefix-state.json").write_text(json.dumps({"stop": "TARGET_PREFIX_COMPLETE"}))
    (tmp_path / "probe-accounting.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n")
    (tmp_path / "network.42").write_text(trace)
    result = diagnostic.inspect_prefix(tmp_path)
    assert result["status"] == ("INCOMPLETE" if defect else "PREFIX_COLLECTION_COMPLETE")
    assert result["qualification_eligible"] is False
    assert result["full_phase_network_gate"] == "NOT_RUN"
    assert result["original_partial_evaluated_status"] == "FAIL"


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
@pytest.mark.parametrize("mode,placement,pool_accounting", [
    ("legacy", None, False), ("boundary", None, False), ("extended", None, False),
    ("boundary", "same_logical", False), ("boundary", "portable_foreground", False),
    ("boundary", None, True), ("extended", None, True),
])
def test_final_network_observer_cannot_requalify_instrumented_capture(
    tmp_path, monkeypatch, mode, placement, pool_accounting
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
        function = "portable_tracer_plan" if placement == "portable_foreground" else "smt_plan"
        monkeypatch.setattr(diagnostic, function, lambda: {
            "allowed": allowed, "same_logical": allowed[0],
            "portable_foreground": allowed[0], "worker_cpus": [],
        })
    output = tmp_path / "output"
    output.mkdir()
    inherited = sorted(os.sched_getaffinity(0))
    diagnostic.worker(root, tmp_path / "artifacts", output, mode, placement,
                      pool_accounting=pool_accounting)
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
        if pool_accounting:
            assert sorted(os.sched_getaffinity(0)) == inherited
            assert context["pool_tasks"]
            assert all(task["affinity"] == inherited for task in context["pool_tasks"])
            assert all(diagnostic._observed_task_counters(task[label])
                       for task in context["pool_tasks"]
                       for label in ("counters_before", "counters_after"))


@pytest.mark.parametrize("revision", ["main", "A" * 40, "a" * 39, "--help", "$(false)"])
def test_observer_source_rejects_unbounded_refs_before_git(tmp_path, monkeypatch, revision):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid source must stop before Git or acquisition")

    monkeypatch.setattr(subprocess, "check_output", forbidden)
    with pytest.raises(ValueError, match="full commit SHA"):
        diagnostic.observer_source(tmp_path, revision)


def test_observer_source_binds_fetched_main_not_driver_head(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "main")
    main = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", main)
    git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "driver")
    driver = git("rev-parse", "HEAD")
    selected = diagnostic.observer_source(tmp_path, main)
    assert selected["source"] == main and selected["tree"] == git("rev-parse", main + "^{tree}")
    with pytest.raises(ValueError, match="differs from fetched main"):
        diagnostic.observer_source(tmp_path, driver)
    (tmp_path / "dirty").write_text("synthetic")
    with pytest.raises(ValueError, match="not clean"):
        diagnostic.observer_source(tmp_path, main)


def test_single_source_control_refuses_reverse_before_output_or_acquisition(tmp_path):
    with pytest.raises(ValueError, match="fixed ABBA order"):
        diagnostic.run(tmp_path, tmp_path / "missing", tmp_path / "output",
                       reverse=True, observer_study=True, observer_revision="a" * 40)
    assert not (tmp_path / "output").exists()


def test_pool_accounting_refuses_legacy_before_source_import(tmp_path):
    with pytest.raises(ValueError, match="operation-boundary"):
        diagnostic.worker(tmp_path, tmp_path, tmp_path, pool_accounting=True)


def test_observer_admission_preserves_existing_evidence_before_git(tmp_path, monkeypatch):
    output = tmp_path / "admission.json"
    output.write_text("retained original observation")

    def forbidden(*args, **kwargs):
        pytest.fail("existing evidence must stop before collection or acquisition")

    monkeypatch.setattr(subprocess, "check_output", forbidden)
    with pytest.raises(ValueError, match="preserve existing"):
        diagnostic.admit_observer(tmp_path, "a" * 40, output)
    assert output.read_text() == "retained original observation"


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
@pytest.mark.parametrize("placement", ["smt_sibling", "portable_foreground"])
def test_real_tracer_stays_pinned_while_child_and_capture_get_their_own_masks(tmp_path, placement):
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
    plan_function = "portable_tracer_plan" if placement == "portable_foreground" else "smt_plan"
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
diagnostic.{plan_function} = lambda: {{"allowed": {allowed!r}, {placement!r}: {foreground},
                               "worker_cpus": []}}
diagnostic.worker(Path({str(root)!r}), Path({str(tmp_path / "artifacts")!r}),
                  Path({str(output)!r}), "boundary", {placement!r}, {set(allowed)!r}, {tracer})
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

@pytest.mark.skipif(sys.platform != "linux", reason="Linux tracee import-affinity control")
def test_tracee_restores_full_mask_before_first_application_import(tmp_path, monkeypatch):
    import builtins

    original = os.sched_getaffinity(0)
    entered = []
    marker = RuntimeError("stop before any application import")
    real_import = builtins.__import__

    def first_application_import(name, *args, **kwargs):
        if name == "ai_runtime_report":
            entered.append(sorted(os.sched_getaffinity(0)))
            raise marker
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(builtins, "__import__", first_application_import)
    try:
        os.sched_setaffinity(0, {min(original)})
        with pytest.raises(RuntimeError) as observed:
            diagnostic.worker(tmp_path, tmp_path, tmp_path, "boundary",
                              "portable_foreground", original, min(original))
        assert observed.value is marker
        assert entered == [sorted(original)]
        assert os.sched_getaffinity(0) == original
    finally:
        os.sched_setaffinity(0, original)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux portable admission")
def test_portable_admission_keeps_actual_model_and_refuses_missing_scheduler(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostic, "portable_environment", lambda: {
        "cpu_models": ["AMD EPYC 9V45 96-Core Processor"], "avx2": True,
        "machine": "x86_64", "original_profile_required": False,
    })
    monkeypatch.setattr(diagnostic, "portable_tracer_plan", lambda: {
        "allowed": [0, 1, 2, 3], "layout": "separate-physical-cores",
    })
    monkeypatch.setattr(diagnostic.shutil, "which", lambda _tool: "/synthetic/control")
    monkeypatch.setattr(diagnostic, "calibrate_scheduler", lambda: {"status": "UNKNOWN"})
    output = tmp_path / "admission.json"
    with pytest.raises(ValueError, match="positive scheduler"):
        diagnostic.admit_portable(output)
    report = json.loads(output.read_text())
    assert report["status"] == "CAPABILITY_MISSING"
    assert report["environment"]["cpu_models"] == ["AMD EPYC 9V45 96-Core Processor"]
    assert report["model_acquisition"] == "NOT_RUN"
    assert report["qualification_eligible"] is False
    retained = output.read_bytes()
    with pytest.raises(ValueError, match="preserve existing"):
        diagnostic.admit_portable(output)
    assert output.read_bytes() == retained


def test_bounded_digest_factor_accepts_only_the_declared_allocation_change():
    before = b"synthetic prefix\n" + diagnostic.DIGEST_OLD + b"\nsynthetic suffix"
    after = before.replace(diagnostic.DIGEST_OLD, diagnostic.DIGEST_NEW)
    diagnostic.digest_factor(before, after, [diagnostic.DIGEST_PATH])


@pytest.mark.parametrize("mismatch", [
    "unchanged", "extra_product", "extra_edit", "missing", "duplicate",
])
def test_bounded_digest_factor_refuses_uncontrolled_changes(mismatch):
    before = b"synthetic prefix\n" + diagnostic.DIGEST_OLD + b"\nsynthetic suffix"
    after = before.replace(diagnostic.DIGEST_OLD, diagnostic.DIGEST_NEW)
    paths = [diagnostic.DIGEST_PATH]
    if mismatch == "unchanged":
        after = before
    elif mismatch == "extra_product":
        paths.append("core/provelume/capture_adapter.py")
    elif mismatch == "extra_edit":
        after += b"\nunrelated product change"
    elif mismatch == "missing":
        paths = []
    elif mismatch == "duplicate":
        before += diagnostic.DIGEST_OLD
        after = before.replace(diagnostic.DIGEST_OLD, diagnostic.DIGEST_NEW)
    with pytest.raises(ValueError, match="factor_not_isolated"):
        diagnostic.digest_factor(before, after, paths)
