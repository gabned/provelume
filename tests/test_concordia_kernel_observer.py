from __future__ import annotations

import json

import pytest
import yaml

from scripts import concordia_kernel_observer as observer


def events(rows):
    counts = {}
    for row in rows:
        key = observer.KINDS[row.split()[0]][0]
        counts[key] = counts.get(key, 0) + 1
    return "\n".join([*rows, *[f"@emitted[{k}]: {v}" for k, v in counts.items()]]) + "\n"


def test_async_stream_is_sorted_but_dropped_event_cannot_pass():
    text = events(["W 30 11", "S 10 11 0 1", "S 50 0 11 0"])
    assert [r[1] for r in observer.parse_events(text)] == [10, 30, 50]
    with pytest.raises(ValueError, match="counts differ"):
        observer.parse_events(text.replace("W 30 11\n", ""))


@pytest.mark.parametrize("corruption", [
    "unexpected content", "@emitted[2]: 1\n@emitted[2]: 1", "S 10 bad 0 0",
    "S -10 11 0 0", "S 10 11 0", "", "Lost 18335 events",
])
def test_unknown_partial_or_malformed_stream_refuses(corruption):
    with pytest.raises(ValueError):
        observer.parse_events(corruption)


def test_stderr_event_loss_or_helper_warning_refuses_even_matching_counts():
    text = events(["X 30 11"])
    for diagnostic in ["Lost 1 events", "WARNING: helper failed", "ERROR: BPF unavailable"]:
        with pytest.raises(ValueError, match="diagnostics"):
            observer.parse_events(text, diagnostic)


def test_blocked_and_ready_time_are_disjoint_and_wakeup_is_not_running():
    rows = observer.parse_events(events(["S 10 11 0 1", "W 30 11", "S 50 0 11 0"]))
    interval, = observer.off_cpu_intervals(rows)
    assert (interval["blocked_ns"], interval["ready_ns"]) == (20, 20)
    assert interval["blocked_ns"] + interval["ready_ns"] == interval["end"] - interval["start"]


@pytest.mark.parametrize("state", [0, 256])
def test_preempted_or_runnable_task_is_all_ready_wait(state):
    rows = observer.parse_events(events([f"S 10 11 0 {state}", "S 50 0 11 0"]))
    interval, = observer.off_cpu_intervals(rows)
    assert (interval["blocked_ns"], interval["ready_ns"]) == (0, 40)


def test_absent_wakeup_stays_unknown_and_exit_is_not_a_switch_in():
    rows = observer.parse_events(events(["S 10 11 0 2", "S 50 0 11 0",
                                         "S 60 11 0 1", "X 70 11"]))
    interval, = observer.off_cpu_intervals(rows)
    assert interval["blocked_ns"] is None and interval["ready_ns"] is None
    assert interval["raw_state"] == 2


def test_matching_clock_and_complete_descendants_are_required():
    fixture = {"pid": 10, "cpu_children": [11, 12], "waker_pid": 13, "helper_tid": 14,
               "markers": [{"tid": 10, "code": 1, "before": 1, "after": 9}],
               "clock_before": {"mono_before": 0, "mono_after": 10, "boot": 10},
               "clock_after": {"mono_before": 90, "mono_after": 110, "boot": 100}}
    rows = observer.parse_events(events([
        "M 5 10 1", "S 10 11 0 0", "S 20 0 11 0", "X 21 11",
        "S 30 12 0 256", "S 40 0 12 0", "X 41 12",
        "U 42 10 1", "S 43 10 0 1", "W 44 10", "S 45 0 10 0", "U 46 10 0",
        "S 50 10 0 8", "W 60 10", "S 70 0 10 0",
        "D 71 10 1", "D 72 10 0", "X 80 13", "X 81 14", "X 82 10",
    ]))
    assert observer.verify_control(rows, fixture)["status"] == "CONTROL_OBSERVED"
    assert observer.verify_control(
        [*rows, ["T", 6, 10, 1]], fixture)["typed_markers_observed"] == 1
    with pytest.raises(ValueError, match="missing or extra marker"):
        observer.verify_control([["T", *r[1:]] if r[0] == "M" else r for r in rows], fixture)
    fixture["markers"][0]["before"] = 6
    with pytest.raises(ValueError, match="clock mismatch"):
        observer.verify_control(rows, fixture)
    fixture["markers"][0]["before"] = 1
    with pytest.raises(ValueError, match="descendant exit"):
        observer.verify_control([r for r in rows if r != ["X", 81, 14]], fixture)
    with pytest.raises(ValueError, match="syscall control missing"):
        observer.verify_control([r for r in rows if r != ["D", 72, 10, 0]], fixture)
    fixture["clock_after"]["boot"] = 1000
    with pytest.raises(ValueError, match="clock offset changed"):
        observer.verify_control(rows, fixture)


def test_missing_capability_stops_before_any_fixture_and_keeps_failure(tmp_path, monkeypatch):
    output = tmp_path / "evidence"
    monkeypatch.setattr(observer, "kernel_capability", lambda: {
        "bpftrace": None, "strace": "/usr/bin/strace", "tracepoint_formats": {},
    })
    assert observer.control(output) == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "NOT_ADMITTED" and manifest["arms"] == []
    assert manifest["native_inference"] == "NOT_RUN"
    assert manifest["qualification_eligible"] is False
    with pytest.raises(FileExistsError):
        observer.control(output)


def test_control_mode_excludes_every_old_job_and_has_no_model_acquisition():
    path = observer.ROOT / ".github/workflows/ai-runtime-candidate.yml"
    workflow = yaml.safe_load(path.read_text())
    jobs = workflow["jobs"]
    for name, job in jobs.items():
        if name not in {"concordia-kernel-control", "concordia-kernel-native"}:
            condition = job["if"]
            guarded = condition.startswith(
                chr(36) + "{{ inputs.concordia_kernel_control != true && (")
            historical_pr_only = condition.startswith(
                chr(36) + "{{ github.event_name == 'pull_request' &&")
            assert guarded or historical_pr_only
    control_job = jobs["concordia-kernel-control"]
    assert "github.run_attempt == 1" in control_job["if"]
    assert "refs/heads/product/0.15-s07-cpu-recovery" in control_job["if"]
    runs = "\n".join(step.get("run", "") for step in control_job["steps"])
    assert "ai_runtime_acquire" not in runs and "qualify_ai_runtime" not in runs
    assert "concordia_kernel_observer.py" in runs


def test_prediction_needs_actual_exceedance_and_complete_same_window_evidence():
    interval = {"tid": 11, "start": 10_000_000, "wake": 30_000_000,
                "end": 90_000_000, "raw_state": 1}
    window = {"tid": 11, "start": 0, "end": 100_000_000,
              "capture_seconds": .4, "own_limit": .3}
    assert observer.evaluate_prediction([interval], **window)["prediction"] == "UNKNOWN"
    result = observer.evaluate_prediction([interval], **window, complete=True)
    assert result["prediction"] == "SUPPORTED_EVENT_SHAPE"
    assert result["largest_woken_ready_ns"] == 60_000_000
    assert result["historical_causality"] == "NOT_ESTABLISHED"
    assert result["qualification_eligible"] is False
    interval["wake"] = 80_000_000
    assert observer.evaluate_prediction(
        [interval], **window, complete=True)["prediction"] == "REFUTED_EVENT_SHAPE"
    interval["wake"] = None
    assert observer.evaluate_prediction(
        [interval], **window, complete=True)["prediction"] == "UNKNOWN"
    window["own_limit"] = .5
    assert observer.evaluate_prediction(
        [interval], **window, complete=True)["prediction"] == "NON_REPRODUCTION"


def test_preempted_thread_or_another_task_cannot_support_wakeup_prediction():
    window = {"tid": 11, "start": 0, "end": 100_000_000,
              "capture_seconds": .4, "own_limit": .3}
    interval = {"tid": 11, "start": 0, "wake": 0, "end": 100_000_000, "raw_state": 256}
    assert observer.evaluate_prediction(
        [interval], **window, complete=True)["prediction"] == "REFUTED_EVENT_SHAPE"
    interval.update(tid=12, raw_state=1)
    assert observer.evaluate_prediction(
        [interval], **window, complete=True)["prediction"] == "REFUTED_EVENT_SHAPE"


def test_cpu_fixture_does_work_between_bounded_clock_observations():
    result = observer.cpu_work(.002)
    assert result["cpu_seconds"] >= .002
    assert 2 <= result["clock_reads"] < 2048
    assert type(result["checksum"]) is int
