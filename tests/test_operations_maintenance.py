from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from provelume import operations_maintenance as module
from provelume.domain import Source
from provelume.instance_backup import create_backup
from provelume.maintenance_backups import BackupVerificationService
from provelume.maintenance_targets import LocalTargetRegistry
from provelume.operations_maintenance import OperationsMaintenance
from provelume.scheduler import SchedulerCoordinator, SchedulerStore, schedule_payload
from provelume.scheduler_model import SCHEDULER_JOB_KINDS, SOURCE_SCOPED_JOB_KINDS, SchedulerError
from provelume.storage import InstanceStore

NOW = datetime(2026, 9, 13, 10, tzinfo=UTC)
SOURCE_ID = "src_" + "1" * 32


def files(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def store(tmp_path):
    return InstanceStore.initialise(tmp_path / "i", name="Synthetic operations")


def queued(store, kind="maintenance.validate", *, key="one"):
    journal = SchedulerStore(store)
    scope = {"kind": "instance", "id": journal.instance_id}
    if kind in SOURCE_SCOPED_JOB_KINDS:
        store.write_source(Source(SOURCE_ID, "filesystem", "Synthetic", NOW.isoformat()))
        scope = {"kind": "source", "id": SOURCE_ID}
    policy = journal.create_policy(
        job_kind=kind,
        scope=scope,
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        now=NOW,
    )
    plan = None
    if kind == "maintenance.backup_verify":
        archive = store.paths.root.parent / "synthetic.zip"
        create_backup(store, destination=archive)
        target = LocalTargetRegistry(store).register_archive(archive)
        plan = BackupVerificationService(store).plan(
            {name: target[name] for name in ("target_ref", "target_revision")}
        )
    job = journal.run_now(policy["id"], request_key=key, now=NOW, execution_plan=plan)["job"]
    return journal, policy, job


def succeeded(store):
    journal, policy, job = queued(store)
    claimed = journal.claim_next(
        worker_id="synthetic-worker", job_id=job["id"], now=NOW + timedelta(seconds=1)
    )
    job = journal.succeed(
        job["id"],
        claimed["lease"]["token"],
        progress={"processed": 1, "skipped": 0, "errors": 0},
        now=NOW + timedelta(seconds=2),
    )
    return journal, policy, job


def test_empty_and_populated_snapshots_are_pure(store, tmp_path, monkeypatch):
    model = OperationsMaintenance(store)
    before = files(tmp_path)
    empty = model.snapshot()
    assert empty["complete"] is True and empty["total_jobs"] == 0
    assert files(tmp_path) == before
    _, _, job = succeeded(store)
    before = files(tmp_path)
    monkeypatch.setattr(SchedulerStore, "hold", lambda *_: pytest.fail("GET acquired writer lock"))
    monkeypatch.setattr(store, "list_canonical", lambda *_: pytest.fail("unbounded source scan"))
    monkeypatch.setattr(module, "public_control_progress", lambda _job: {"cheap": True})
    snapshot = model.snapshot()
    assert snapshot["complete"] is True and snapshot["total_jobs"] == 1
    view = snapshot["jobs"][0]
    assert view["id"] == job["id"] and view["terminal_receipt_status"] == "verified"
    assert view["progress_view"]["cheap"] is True
    assert files(tmp_path) == before


@pytest.mark.parametrize("kind", SCHEDULER_JOB_KINDS)
def test_every_actual_job_kind_including_backup_is_projected(store, kind):
    _, _, job = queued(store, kind)
    view = OperationsMaintenance(store).snapshot()
    assert view["complete"] is True
    assert view["jobs"][0]["id"] == job["id"]
    assert view["jobs"][0]["job_kind"] == kind
    assert view["jobs"][0]["last_attempt_at"] is None
    assert set(item["kind"] for item in view["job_kinds"]) == set(SCHEDULER_JOB_KINDS)


def test_policy_evaluation_is_not_execution_and_recovery_state_is_preserved(store):
    journal, policy, job = queued(store)
    journal.update_policy(
        policy["id"],
        state="enabled",
        schedule=schedule_payload(mode="interval", timezone="UTC", interval_seconds=3600),
        now=NOW,
    )
    journal.evaluate(now=NOW + timedelta(seconds=1))
    view = OperationsMaintenance(store).snapshot()
    assert view["policies"][0]["last_evaluated_at"] == (NOW + timedelta(seconds=1)).isoformat()
    assert view["policies"][0]["last_attempt_at"] is None
    assert view["policies"][0]["last_success_at"] is None
    job = {**job, "recovery_state": "restart_only", "recovery_count": 1}
    journal._write_job(job)
    assert OperationsMaintenance(store).job(job["id"])["recovery_state"] == "restart_only"


@pytest.mark.parametrize("damage", ["missing", "mismatch", "corrupt", "oversized"])
def test_terminal_success_requires_current_exact_receipt(store, damage):
    journal, _, job = succeeded(store)
    receipt = journal.receipts / ("receipt_" + job["id"].removeprefix("job_") + ".json")
    if damage == "missing":
        receipt.unlink()
    elif damage == "mismatch":
        value = json.loads(receipt.read_text())
        value["progress"]["processed"] = 2
        receipt.write_text(json.dumps(value))
    elif damage == "corrupt":
        receipt.write_bytes(b"{")
    else:
        with receipt.open("wb") as stream:
            stream.truncate(module.MAX_VIEW_RECORD_BYTES + 1)
    view = OperationsMaintenance(store).snapshot()
    assert view["complete"] is False
    assert view["jobs"][0]["display_state"] == "completed"  # actual producer status
    assert view["jobs"][0]["terminal_receipt"] is None
    assert view["jobs"][0]["last_success_at"] is None
    assert view["coverage"]["receipts"]["total"] is None
    assert view["policies"][0]["history_complete"] is False


@pytest.mark.parametrize("damage", ["corrupt", "oversized", "nonregular", "wrong_filename"])
def test_invalid_jobs_are_not_zero_or_complete(store, damage):
    journal, _, job = queued(store)
    path = journal.jobs / (job["id"] + ".json")
    if damage == "corrupt":
        path.write_bytes(b"{")
    elif damage == "oversized":
        with path.open("wb") as stream:
            stream.truncate(module.MAX_VIEW_RECORD_BYTES + 1)
    elif damage == "nonregular":
        path.unlink()
        path.mkdir()
    else:
        path.rename(path.with_name("job_" + "f" * 32 + ".json"))
    view = OperationsMaintenance(store).snapshot()
    assert view["total_jobs"] is None
    assert view["coverage"]["jobs"]["complete"] is False
    with pytest.raises(SchedulerError):
        OperationsMaintenance(store).job(job["id"])


def test_limits_and_pagination_preserve_unknown_totals(store, monkeypatch):
    _, _, first = queued(store)
    _, _, second = queued(store, key="two")
    model = OperationsMaintenance(store)
    assert model.snapshot(limit=1, offset=1)["total_jobs"] == 2
    assert model.job(first["id"])["id"] == first["id"]
    assert model.job(second["id"])["id"] == second["id"]
    monkeypatch.setattr(module, "MAX_VIEW_RECORDS", 1)
    partial = model.snapshot()
    assert partial["complete"] is False and partial["total_jobs"] is None
    assert "record_limit" in partial["coverage"]["jobs"]["reasons"]


def test_global_bracket_detects_job_change_during_receipt_collection(store, monkeypatch):
    journal, _, job = succeeded(store)
    model = OperationsMaintenance(store)
    original = model._records
    path = journal.jobs / (job["id"] + ".json")

    def drift(directory, validator, **kwargs):
        result = original(directory, validator, **kwargs)
        if directory == journal.receipts:
            path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(model, "_records", drift)
    view = model.snapshot()
    assert not view["complete"]
    assert "changed_during_observation" in view["coverage"]["jobs"]["reasons"]
    assert view["jobs"][0]["terminal_receipt"] is None


def test_foreign_instance_and_unknown_source_are_excluded(store, tmp_path):
    foreign = InstanceStore.initialise(tmp_path / "foreign", name="Foreign synthetic")
    fj, _, fjob = succeeded(foreign)
    journal, _, _ = queued(store)
    for path in fj.jobs.glob("*.json"):
        (journal.jobs / path.name).write_bytes(path.read_bytes())
    for path in fj.receipts.glob("*.json"):
        (journal.receipts / path.name).write_bytes(path.read_bytes())
    view = OperationsMaintenance(store).snapshot()
    assert not view["complete"] and view["total_jobs"] is None
    assert fjob["id"] not in {job["id"] for job in view["jobs"]}
    with pytest.raises(SchedulerError):
        OperationsMaintenance(store).job(fjob["id"])
    _, _, source_job = queued(store, "source.refresh")
    (store.paths.canonical_dir("sources") / (SOURCE_ID + ".json")).unlink()
    view = OperationsMaintenance(store).snapshot()
    assert source_job["id"] not in {job["id"] for job in view["jobs"]}


def test_total_byte_bound_is_honest(store, monkeypatch):
    queued(store)
    monkeypatch.setattr(module, "MAX_VIEW_TOTAL_BYTES", 1)
    view = OperationsMaintenance(store).snapshot()
    assert view["complete"] is False and view["total_jobs"] is None
    assert "total_byte_limit" in view["coverage"]["jobs"]["reasons"]


def test_real_backup_verification_job_has_exact_terminal_proof(store):
    _, _, job = queued(store, "maintenance.backup_verify")
    completed = SchedulerCoordinator(store).run_one(
        job_id=job["id"], now=NOW + timedelta(seconds=1)
    )
    assert completed["status"] == "succeeded"
    view = OperationsMaintenance(store).job(job["id"])
    assert view["terminal_receipt_status"] == "verified"
    assert view["job_kind"] == "maintenance.backup_verify"
    assert view["execution_plan"]["archive_sha256"] == completed["execution_plan"]["archive_sha256"]
    assert view["terminal_receipt"]["network_used"] is False
