from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from provelume.cli import main
from provelume.duplicates import (
    DuplicateCaseBusyError,
    DuplicateCaseManager,
    DuplicateScanStaleError,
)
from provelume.operations import OperationLedger
from provelume.rebuild import DerivedRebuildManager
from provelume.scheduler import retry_payload, schedule_payload
from provelume.service import ProvelumeInstance


@pytest.mark.parametrize("command", ["duplicate-scan", "rebuild-derived"])
@pytest.mark.parametrize("error", [DuplicateCaseBusyError, DuplicateScanStaleError])
def test_cli_reports_scan_conflict_once_and_closes_rebuild(
    tmp_path: Path, monkeypatch, capsys, command, error
):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    before = instance.store.knowledge_fingerprint()
    calls = []

    def conflict(self):
        calls.append(self.store.paths.root)
        raise error("synthetic producer conflict")

    monkeypatch.setattr(DuplicateCaseManager, "scan", conflict)
    assert main([command, str(instance.root)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "status": "conflict",
        "error": "synthetic producer conflict",
        "error_type": error.__name__,
        "retryable": True,
        "retry_requires_new_request": True,
    }
    assert len(calls) == 1
    assert instance.store.knowledge_fingerprint() == before
    if command == "rebuild-derived":
        operations = OperationLedger(instance.store).list()
        assert len(operations) == 1
        assert operations[0]["status"] == "failed"
        assert operations[0]["error_code"] == (
            "duplicate_case_busy" if error is DuplicateCaseBusyError else "duplicate_scan_stale"
        )
        assert DerivedRebuildManager(instance.store).list_reports() == []
        assert DerivedRebuildManager(instance.store).locks.inspect("derived-rebuild") is None


@pytest.mark.parametrize("error", [DuplicateCaseBusyError, DuplicateScanStaleError])
def test_scheduler_scan_conflict_is_terminal_and_requires_new_request(
    tmp_path: Path, monkeypatch, error
):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    scheduler = instance.scheduler
    start = datetime(2026, 9, 13, 6, 0, tzinfo=UTC)
    policy = scheduler.journal.create_policy(
        job_kind="maintenance.duplicate_scan",
        scope={"kind": "instance", "id": instance.instance_summary()["id"]},
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=10),
        now=start,
    )
    queued = scheduler.journal.run_now(policy["id"], request_key="first", now=start)["job"]
    original_scan = DuplicateCaseManager.scan
    calls = []

    def conflict(self):
        calls.append(self.store.paths.root)
        raise error("synthetic producer conflict")

    monkeypatch.setattr(DuplicateCaseManager, "scan", conflict)
    terminal = scheduler.run_one(now=start)
    assert terminal["id"] == queued["id"]
    assert terminal["status"] == "manual_intervention"
    assert terminal["attempt"] == 1
    assert terminal["lease"] is None
    assert terminal["retry_not_before"] is None
    assert terminal["attempts"][0]["outcome"] == "failed"
    receipt = scheduler.journal.list_receipts()[0]
    assert receipt["job_id"] == queued["id"]
    assert receipt["error_class"] == "manual_intervention"
    assert receipt["error_code"] == "maintenance_action_failed"
    assert receipt["canonical_mutation"] is False
    assert receipt["network_used"] is False
    later = start + timedelta(days=1)
    assert scheduler.run_one(now=later) is None
    assert len(calls) == 1
    reopened = ProvelumeInstance(instance.root).scheduler
    assert reopened.journal.get_job(queued["id"])["status"] == "manual_intervention"
    assert reopened.run_one(now=later) is None
    monkeypatch.setattr(DuplicateCaseManager, "scan", original_scan)
    explicit = reopened.journal.run_now(policy["id"], request_key="explicit-again", now=later)
    assert explicit["job"]["id"] != queued["id"]
    recovered = reopened.run_one(now=later)
    assert recovered["status"] == "succeeded"
    assert len(reopened.journal.list_receipts()) == 2
