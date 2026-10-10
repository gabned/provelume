"""Qualification preconditions, without model acquisition or hardware claims."""
from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ai_runtime_report import evaluate, warm_preparation_gate


def warm_report():
    samples = []
    for index in range(60):
        pid = index // 20 + 1
        samples.append({
            "id": f"case-{index}", "run": index // 20, "authority_renewed": False,
            "cold": False, "first_wall_seconds": 2, "total_seconds": 3,
            "load": {"pid": pid, "seconds": 2}, "memory": {"peak_rss": 1024**3},
            "prefill": {"pid": pid, "request": f"sample-{index}", "phase": "native_prefill"},
        })
    preparations = []
    for index in (0, 20, 40):
        row = copy.deepcopy(samples[index])
        row.update(sample_index=index, case=row["id"], reason="initial", **{
            "pass": True, "cold": True, "first_wall_seconds": 7, "total_seconds": 8,
        })
        row["prefill"]["request"] = f"preparation-{index}"
        preparations.append(row)
    return {"samples": samples, "warm_preparations": preparations, "failures": []}


def test_cold_preparation_is_retained_under_cold_bounds_and_corpus_is_genuinely_warm():
    report = warm_report()
    assert warm_preparation_gate(report) == "PASS"
    gates = evaluate(report)["gates"]
    assert gates["warm_preparation"] == gates["warm_first"] == gates["warm_total"] == "PASS"
    assert len(report["samples"]) == 60 and len(report["warm_preparations"]) == 3
    assert report["warm_preparations"][0]["first_wall_seconds"] == 7
    report["samples"][0]["first_wall_seconds"] = 5.001
    assert evaluate(report)["gates"]["warm_first"] == "FAIL"
    report["samples"][0].update(first_wall_seconds=2, cold=True)
    assert evaluate(report)["gates"]["warm_first"] == "FAIL"


@pytest.mark.parametrize("field,value", [
    ("first_wall_seconds", 20.001), ("total_seconds", 60.001),
    ("pass", False), ("reason", "unexplained"), ("case", "wrong-case"), ("run", 2),
])
def test_preparation_does_not_hide_failed_or_misbound_observations(field, value):
    report = warm_report()
    report["warm_preparations"][0][field] = value
    assert warm_preparation_gate(report) == "FAIL"


@pytest.mark.parametrize("section,field,value", [
    ("load", "seconds", 15.001), ("load", "pid", 99),
    ("memory", "peak_rss", 2 * 1024**3 + 1),
    ("prefill", "request", "sample-0"),
])
def test_preparation_keeps_load_memory_and_worker_identity_limits(section, field, value):
    report = warm_report()
    report["warm_preparations"][0][section][field] = value
    assert warm_preparation_gate(report) == "FAIL"


def test_missing_duplicate_and_unrecorded_renewal_preparations_cannot_pass():
    report = warm_report()
    report["samples"][7]["authority_renewed"] = True
    assert warm_preparation_gate(report) == "FAIL"
    report = warm_report()
    report["warm_preparations"].append(copy.deepcopy(report["warm_preparations"][0]))
    assert warm_preparation_gate(report) == "FAIL"
    report = warm_report()
    del report["warm_preparations"][0]["cold"]
    assert warm_preparation_gate(report) == "NOT_RUN"
    report = warm_report()
    report["warm_preparations"].pop()
    assert warm_preparation_gate(report) == "NOT_RUN"


def test_a_preparation_that_is_already_warm_still_has_the_five_second_limit():
    report = warm_report()
    report["warm_preparations"][0]["cold"] = False
    assert warm_preparation_gate(report) == "FAIL"


@pytest.mark.parametrize("initial,renew", [(True, False), (False, True), (False, False)])
def test_slow_authority_renewal_cannot_turn_a_measured_warm_case_into_a_cold_load(
    monkeypatch, initial, renew,
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from scripts import qualify_ai_runtime as measure

    monkeypatch.setattr(measure.time, "monotonic", lambda: 100)
    calls = []

    class Runtime:
        loaded = True

        def qualify(self, store, prompt, *, requested):
            assert requested is True
            cold = not self.loaded
            self.loaded = True
            preparation = "ORCHID" in prompt
            calls.append(("preparation" if preparation else "case", cold))
            return {"text": "ORCHID" if preparation else "Ada", "cold": cold,
                    "first_wall_seconds": 7 if cold else 2, "total_seconds": 8 if cold else 3}

    runtime = Runtime()

    class Store:
        def self_test(self, identifier, selection, runner, *, requested):
            assert requested is True and runner is runtime
            calls.append("self_test")
            return SimpleNamespace(expires=200)

        def activate(self, identifier, selection, evidence, *, requested):
            assert requested is True
            calls.append("activate")
            # Simulate real post-inference verification/activation outlasting idle.
            runtime.loaded = False

    report = {"samples": [] if initial else [{}], "warm_preparations": []}
    evidence = SimpleNamespace(expires=110 if renew else 200)
    case = {"id": "en01", "language": "en", "text": "Ada", "question": "Who?",
            "expected": "Ada"}
    result = measure.measure_warm_case(report, Store(), runtime, object(), evidence, case, 0)
    assert report["samples"][-1]["cold"] is False
    assert report["samples"][-1]["pass"] is True
    assert report["samples"][-1]["authority_renewed"] is renew
    assert len(report["warm_preparations"]) == int(initial or renew)
    assert calls[-1] == ("case", False)
    if renew:
        assert calls == ["self_test", "activate", ("preparation", True), ("case", False)]
        assert result is not evidence
        assert report["warm_preparations"][0]["first_wall_seconds"] == 7
    elif initial:
        assert calls == [("preparation", False), ("case", False)]
    else:
        assert calls == [("case", False)]

