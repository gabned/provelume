import json
from types import SimpleNamespace

import pytest

from provelume import mirror_ssh_agent_worker as worker
from provelume.mirror_contract import MirrorError


@pytest.mark.parametrize("winerror", [32, 33])
def test_completed_agent_report_survives_transient_windows_read_sharing(
    tmp_path, monkeypatch, winerror,
):
    output = tmp_path / "ready.json.done"
    report = {
        "schema": "provelume-ssh-agent-result/v1", "signatures": 1,
        "host_bound": True, "private_key_logged": False,
    }
    replace = worker.os.replace
    attempts = []

    def temporarily_busy(source, target):
        if target != output:
            return replace(source, target)
        attempts.append(True)
        if len(attempts) == 1:
            error = PermissionError("SYNTHETIC concurrent Windows reader")
            error.winerror = winerror
            raise error
        replace(source, target)

    monkeypatch.setattr(worker.os, "replace", temporarily_busy)
    worker.publish(output, report)
    assert json.loads(output.read_bytes()) == report
    assert len(attempts) == 2
    assert not output.with_name(output.name + ".tmp").exists()


def test_report_sharing_failure_cannot_extend_the_existing_deadline(tmp_path, monkeypatch):
    output = tmp_path / "ready.json.done"
    clock = [0.0]
    attempts = []
    replace = worker.os.replace

    def still_busy(source, target):
        if target != output:
            return replace(source, target)
        attempts.append(True)
        clock[0] = 2.0
        error = PermissionError("SYNTHETIC sharing violation past the existing budget")
        error.winerror = 32
        raise error

    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(worker.os, "replace", still_busy)
    with pytest.raises((PermissionError, MirrorError)):
        worker.publish(output, {"schema": "synthetic-metadata"}, deadline=1.0)
    assert len(attempts) == 1
    assert not output.exists()


def test_other_permission_failures_remain_closed_without_retry(tmp_path, monkeypatch):
    output = tmp_path / "ready.json.done"
    attempts = []
    replace = worker.os.replace

    def denied(source, target):
        if target != output:
            return replace(source, target)
        attempts.append(True)
        error = PermissionError("SYNTHETIC access denied")
        error.winerror = 5
        raise error

    monkeypatch.setattr(worker.os, "replace", denied)
    with pytest.raises(PermissionError):
        worker.publish(output, {"schema": "synthetic-metadata"})
    assert attempts == [True]
    assert not output.exists()


def test_recovered_sharing_cannot_publish_after_deadline(tmp_path, monkeypatch):
    output = tmp_path / "ready.json.done"
    clock = [0.0]
    attempts = []
    replace = worker.os.replace

    def sharing(source, target):
        if target != output:
            return replace(source, target)
        attempts.append(True)
        error = PermissionError("SYNTHETIC sharing violation")
        error.winerror = 32
        raise error

    monkeypatch.setattr(worker, "time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda _seconds: clock.__setitem__(0, 2.0),
    ))
    monkeypatch.setattr(worker.os, "replace", sharing)
    with pytest.raises(MirrorError, match="ssh_agent_deadline"):
        worker.publish(output, {"schema": "synthetic-metadata"}, deadline=1.0)
    assert attempts == [True]
    assert not output.exists()
