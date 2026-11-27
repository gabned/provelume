import json
from types import SimpleNamespace

import pytest

from provelume import mirror_ssh_agent_diagnostics as diagnostics
from provelume import mirror_ssh_agent_process as process
from provelume.mirror_contract import MirrorError


def test_missing_completion_retains_closed_worker_phase_without_weakening_refusal(
    tmp_path, monkeypatch
):
    worker = process.AgentWorker(b"s" * 32, host_public_blob=b"synthetic", username="synthetic")
    worker.output = tmp_path / "ready.json"
    worker.output.write_text("{}")
    worker.process = SimpleNamespace(poll=lambda: None)
    (tmp_path / "worker-errors.bin").write_text(
        json.dumps(
            {
                "schema": diagnostics.SCHEMA,
                "phase": "SESSION",
                "untrusted": "SYNTHETIC_SECRET/private/path",
            }
        )
        + "\n"
    )
    clock = [0.0]
    monkeypatch.setattr(
        process,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            sleep=lambda _: clock.__setitem__(0, 2.0),
        ),
    )
    closed = []
    monkeypatch.setattr(worker, "close", lambda: closed.append(True))
    with pytest.raises(MirrorError) as failure:
        worker.__exit__(None)
    assert failure.value.code == "ssh_credentials" and closed == [True]
    evidence = failure.value.agent_evidence
    assert evidence["worker_state"] == "RUNNING"
    assert evidence["completion"] == "ABSENT"
    assert evidence["trace"]["phase"] == "SESSION"
    rendered = json.dumps(evidence) + "".join(failure.value.__notes__)
    assert "SYNTHETIC_SECRET" not in rendered and str(tmp_path) not in rendered


def test_worker_error_diagnostics_exclude_unknown_codes_messages_and_native_values(capsys):
    error = MirrorError("SYNTHETIC_SECRET/private/path")
    error.winerror = 1234567
    diagnostics.emit("SESSION", error)
    rendered = capsys.readouterr().err
    value = json.loads(rendered)
    assert value["error_code"] == value["native_error"] == "OTHER"
    assert "SYNTHETIC_SECRET" not in rendered and "1234567" not in rendered


def test_transport_failure_retains_the_workers_signature_observation(tmp_path, monkeypatch):
    worker = process.AgentWorker(b"s" * 32, host_public_blob=b"synthetic", username="synthetic")
    worker.output = tmp_path / "ready.json"
    worker.process = SimpleNamespace(poll=lambda: 2)

    def close():
        worker.report = {"signatures": 0}

    monkeypatch.setattr(worker, "close", close)
    failure = MirrorError("ssh_command_failed")
    worker.__exit__(MirrorError, failure)
    assert failure.code == "ssh_command_failed"
    assert failure.agent_evidence["worker_state"] == "EXIT_2"
    assert failure.agent_evidence["signature_observation"] == "NO_SIGNATURE"


def test_phase_logging_is_optional_in_a_frozen_windowless_worker(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(diagnostics.sys, "stderr", None)
        assert diagnostics.emit("SESSION") is None


@pytest.mark.parametrize(
    "value",
    [
        {"phase": ["SYNTHETIC_SECRET"]},
        {"phase": "SYNTHETIC_SECRET", "error_code": [], "native_error": {}},
    ],
)
def test_foreign_trace_fields_are_never_rendered(tmp_path, value):
    path = tmp_path / "trace"
    path.write_text(json.dumps({"schema": diagnostics.SCHEMA, **value}) + "\n")
    result = diagnostics.observe(path)
    assert result["phase"] == "OTHER" and "SYNTHETIC_SECRET" not in json.dumps(result)
