"""Synthetic failed qualification calls: attribution, privacy and mandatory cleanup."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from provelume.ai_runtime_diagnostics import native_failure
from provelume.scheduler_model import SchedulerError


@pytest.fixture
def classification_host(tmp_path, monkeypatch):
    from scripts import qualify_ai_classification as qualifier

    state = SimpleNamespace(reads=[], closed=False, sequence=[], terminals=[], checkpoints=[])
    runtime = SimpleNamespace(directory=tmp_path / "unused-native", loaded=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("S06_WFP_VERIFIED", "1")

    def factory(instance, **_kwargs):
        setup = SimpleNamespace(operation=None)
        setup.save = lambda *_args: None
        setup.configuration = lambda: {"revision": 0}
        setup.begin_operation = lambda action: action
        setup.run_operation = lambda action: setattr(setup, "operation", {"state": "completed"})
        setup.self_test_evidence = SimpleNamespace(public_record=lambda: {"synthetic": True})
        setup.enable = lambda: None
        setup.jobs = SimpleNamespace(status=lambda: {"mode": "off", "accounting": {}})
        setup.approve_generation = lambda _ref: None
        setup.enqueue = lambda _ref: {"id": "job_" + str(len(state.terminals))}

        def execute(job_id):
            terminal = copy.deepcopy(state.sequence.pop(0))
            terminal.setdefault("id", job_id)
            state.terminals.append(terminal)
            return terminal

        def read(job_id):
            state.reads.append(job_id)
            if state.terminals[-1]["status"] != "succeeded":
                raise SchedulerError("DoNotPublishSecondaryReaderError")
            return ({"assessment": {"status": "abstained", "target": None},
                     "classification_quality": "NOT_EVALUATED", "confidence": None,
                     "automation_authorized": False}, None, None, None, None)

        def close():
            state.closed = True
            runtime.loaded = False

        instance.run_ai_job = execute
        setup.close = close
        setup.classification = SimpleNamespace(
            preview=lambda *_args: ("public-ref", None, None), read=read,
            discard=lambda _job: None, reference=lambda _job: ({"status": "succeeded"}, None, None),
            path=lambda _job: tmp_path / "absent-public-result",
        )
        return setup

    monkeypatch.setattr(qualifier, "AiSetup", factory)
    state.run = lambda **kwargs: qualifier.measure_classification(
        tmp_path, object(), runtime, **kwargs)
    return state


@pytest.mark.parametrize("prior_success", [False, True])
def test_failed_terminal_keeps_its_diagnostic_without_reading_a_missing_result(
    classification_host, prior_success,
):
    host = classification_host
    owned = native_failure({"phase": "generation", "parent_termination": True}, code="timeout")
    success = {"status": "succeeded", "ai": {"blocked": None}}
    failure = {"status": "failed", "ai": {"blocked": "ai_local_stopped",
                "attempts": [{"native_failure": owned}]}}
    host.sequence = ([success] if prior_success else []) + [failure]
    result = host.run()
    assert result["status"] == "FAIL" and result["failure"] == "classification_job_failed"
    assert result["failed_stage"] == "execution_failed" and result["stage"] == "cleanup"
    assert len(host.reads) == int(prior_success)
    assert host.closed and result["worker_absent"] and result["final_off"]
    assert result["quality"] == "NOT_EVALUATED" and result["gold_labels"] == "NOT_REVIEWED"
    sample = result["samples"][-1]
    assert sample["status"] == "failed" and sample["native_failure"] == owned
    sample["native_failure"]["phase"] = "request_send"
    assert host.terminals[-1]["ai"]["attempts"][-1]["native_failure"]["phase"] == "generation"
    assert "DoNotPublish" not in json.dumps(result)


def test_failed_terminal_rejects_private_or_foreign_diagnostic(classification_host):
    host = classification_host
    invalid = {**native_failure({}, code="timeout"), "stderr": "DoNotPublishPrivateText"}
    host.sequence = [{"status": "failed", "ai": {"blocked": "ai_local_stopped",
                      "attempts": [{"native_failure": invalid}]}}]
    result = host.run()
    assert result["failure"] == "classification_job_failed" and not host.reads
    assert "native_failure" not in result["samples"][-1]
    assert "DoNotPublish" not in json.dumps(result)
    assert host.closed


def test_checkpoints_keep_both_successes_and_cleanup_without_claiming_accuracy(classification_host):
    host = classification_host
    host.sequence = [{"status": "succeeded", "ai": {"blocked": None}} for _ in range(2)]
    result = host.run(checkpoint=lambda row: host.checkpoints.append(copy.deepcopy(row)))
    assert result["status"] == "MEASURED" and len(host.reads) == 2 and host.closed
    assert host.checkpoints[-1] == result
    assert any(row.get("stage") == "result_read" and row["samples"] for row in host.checkpoints)
    assert all(row["quality"] == "NOT_EVALUATED" for row in host.checkpoints)
    assert all(sample["confidence"] is None and not sample["application_authorized"]
               for sample in result["samples"])
    assert all(sample["assessment"] == "abstained"
               and sample["journey"]["destination_review"] == "NOT_APPLICABLE_ABSTENTION"
               for sample in result["samples"])


def test_other_job_cannot_supply_failure_attribution(classification_host):
    host = classification_host
    host.sequence = [{"id": "job_other_owner", "status": "failed", "ai": {
        "blocked": "ai_local_stopped", "attempts": [
            {"native_failure": native_failure({}, code="timeout")}]}}]
    result = host.run()
    assert result["failure"] == "classification_job_identity"
    assert not result["samples"] and not host.reads and host.closed


def test_checkpoint_write_error_still_closes_setup(classification_host):
    host = classification_host

    def unavailable(_result):
        raise OSError("DoNotPublishPrivateOutputPath")

    with pytest.raises(OSError):
        host.run(checkpoint=unavailable)
    assert host.closed and not host.reads and not host.terminals


def test_installed_acquisition_summary_reports_bounded_failed_transfer_only(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from scripts.qualify_custodia_installed import summary

    row = {"state": "failed", "action": "install", "bytes": "822882922",
           "error": "timeout", "elapsed_seconds": 350.812,
           "private": "DoNotPublishPrivatePath"}
    report = {"status": "FAIL", "phase": "ordinary_network_acquisition", "checks": {},
              "failure_type": "ValueError", "failure_code": "model_operation",
              "operation_history": [row]}
    expected = {"state": "failed", "action": "install", "bytes": 822882922,
                "error": "timeout", "elapsed_ms": 350812}
    assert summary(report)["failed_model_operation"] == expected
    assert "DoNotPublish" not in json.dumps(summary(report))
    for bad in (True, -1, "DoNotPublishPrivatePath", "1435238657", "1e8"):
        row["bytes"] = bad
        assert "bytes" not in summary(report)["failed_model_operation"]
    row.update(state="completed", bytes="1435238656")
    assert "failed_model_operation" not in summary(report)
    for action in ("DoNotPublishPrivateAction", ["install"], {"install": True}):
        row.update(state="failed", action=action)
        assert "failed_model_operation" not in summary(report)
