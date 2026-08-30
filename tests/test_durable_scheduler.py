from __future__ import annotations

import json
import time
import tomllib
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from provelume import scheduler as scheduler_module
from provelume.cli import main
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.scheduler import SchedulerStore, retry_payload, schedule_payload
from provelume.scheduler_model import (
    SchedulerBusyError,
    SchedulerError,
    eligible_instant,
    resolve_local_time,
)
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _instance(tmp_path: Path) -> ProvelumeInstance:
    return ProvelumeInstance.initialise(tmp_path / "instance", name="Scheduler fixture")


def _scope(instance: ProvelumeInstance) -> dict[str, str]:
    return {"kind": "instance", "id": instance.instance_summary()["id"]}


def _manual_policy(
    instance: ProvelumeInstance,
    *,
    job_kind: str = "maintenance.validate",
    retry: dict[str, int] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    return instance.scheduler.journal.create_policy(
        job_kind=job_kind,
        scope=_scope(instance),
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry,
        now=now,
    )


def test_cross_platform_iana_timezone_data_is_a_runtime_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as handle:
        dependencies = tomllib.load(handle)["project"]["dependencies"]
    assert any(dependency.startswith("tzdata>=") for dependency in dependencies)


def test_dst_gap_fold_quiet_window_and_jitter_are_deterministic() -> None:
    spring = date(2026, 3, 29)
    assert (
        resolve_local_time(
            spring,
            "02:30",
            timezone="Europe/Rome",
            dst_policy="skip",
        )
        is None
    )
    shifted = resolve_local_time(
        spring,
        "02:30",
        timezone="Europe/Rome",
        dst_policy="shift_forward",
    )
    assert shifted is not None
    assert shifted.astimezone(ZoneInfo("Europe/Rome")).strftime("%H:%M") == "03:00"

    autumn = date(2026, 10, 25)
    earliest = resolve_local_time(
        autumn,
        "02:30",
        timezone="Europe/Rome",
        dst_policy="earliest",
    )
    latest = resolve_local_time(
        autumn,
        "02:30",
        timezone="Europe/Rome",
        dst_policy="latest",
    )
    assert earliest is not None and latest is not None
    assert latest - earliest == timedelta(hours=1)

    quiet_schedule = schedule_payload(
        mode="interval",
        timezone="UTC",
        interval_seconds=60,
        quiet_start="22:00",
        quiet_end="06:00",
    )
    nominal = datetime(2026, 1, 4, 22, 30, tzinfo=UTC)
    assert eligible_instant(
        nominal,
        policy_id="policy_" + "1" * 32,
        revision=1,
        schedule=quiet_schedule,
    ) == datetime(2026, 1, 5, 6, 0, tzinfo=UTC)

    jittered = schedule_payload(
        mode="interval",
        timezone="UTC",
        interval_seconds=60,
        jitter_seconds=30,
    )
    first = eligible_instant(
        nominal,
        policy_id="policy_" + "2" * 32,
        revision=7,
        schedule=jittered,
    )
    second = eligible_instant(
        nominal,
        policy_id="policy_" + "2" * 32,
        revision=7,
        schedule=jittered,
    )
    assert first == second
    assert timedelta(0) <= first - nominal <= timedelta(seconds=30)

    wide_jitter = schedule_payload(
        mode="interval",
        timezone="UTC",
        interval_seconds=60,
        jitter_seconds=24 * 60 * 60,
    )
    wide_first = eligible_instant(
        nominal,
        policy_id="policy_" + "3" * 32,
        revision=7,
        schedule=wide_jitter,
    )
    wide_second = eligible_instant(
        nominal + timedelta(seconds=60),
        policy_id="policy_" + "3" * 32,
        revision=7,
        schedule=wide_jitter,
    )
    assert wide_second - wide_first == timedelta(seconds=60)


def test_wide_jitter_preserves_interval_evaluation_order(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    journal = instance.scheduler.journal
    start = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    policy = journal.create_policy(
        job_kind="maintenance.validate",
        scope=_scope(instance),
        state="enabled",
        schedule=schedule_payload(
            mode="interval",
            timezone="UTC",
            interval_seconds=60,
            jitter_seconds=24 * 60 * 60,
            missed_run_policy="catch_up_one",
        ),
        now=start,
    )
    first_due = datetime.fromisoformat(str(policy["next_due_at"]))

    result = journal.evaluate(now=first_due + timedelta(seconds=61))

    assert len(result["created_jobs"]) == 1
    job = journal.get_job(result["created_jobs"][0])
    assert job is not None
    assert job["reason"] == "catch_up"
    assert datetime.fromisoformat(job["eligible_at"]) == first_due + timedelta(seconds=60)
    current = journal.get_policy(str(policy["id"]))
    assert current is not None
    assert datetime.fromisoformat(current["next_due_at"]) == first_due + timedelta(seconds=120)


def test_policy_modes_scope_and_unmanaged_source_refresh_fail_closed(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    journal = instance.scheduler.journal
    now = datetime(2026, 8, 30, 7, 0, tzinfo=UTC)
    manual = journal.create_policy(
        job_kind="maintenance.validate",
        scope=_scope(instance),
        state="enabled",
        schedule=schedule_payload(mode="manual", timezone="Europe/Rome"),
        now=now,
    )
    assert manual["next_due_at"] is None
    interval = journal.create_policy(
        job_kind="search.reindex",
        scope=_scope(instance),
        state="enabled",
        schedule=schedule_payload(
            mode="interval",
            timezone="UTC",
            interval_seconds=3600,
        ),
        now=now,
    )
    assert interval["next_due_at"] == "2026-08-30T08:00:00+00:00"
    calendar = journal.create_policy(
        job_kind="maintenance.validate",
        scope=_scope(instance),
        state="paused",
        schedule=schedule_payload(
            mode="calendar",
            timezone="Europe/Rome",
            calendar_time="02:30",
            weekdays=list(range(7)),
            dst_policy="latest",
        ),
        now=now,
    )
    assert calendar["state"] == "paused"
    assert calendar["schedule"]["weekdays"] == list(range(7))

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.txt").write_text("synthetic", encoding="utf-8")
    instance.ingest(source_dir)
    source_id = instance.list_sources()[0]["id"]
    refresh = journal.create_policy(
        job_kind="source.refresh",
        scope={"kind": "source", "id": source_id},
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        now=now,
    )
    enabled = journal.update_policy(refresh["id"], state="enabled", now=now)
    assert enabled["state"] == "enabled"
    queued = journal.run_now(refresh["id"], request_key="explicit", now=now)
    assert queued["created"] is True
    finished = instance.scheduler.run_one(now=now)
    assert finished is not None
    assert finished["status"] == "failed"
    assert finished["attempts"][-1]["error_code"] == "invalid_state"


def test_missed_runs_are_bounded_and_clock_reversal_recomputes(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    journal = instance.scheduler.journal
    start = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    policies = {}
    for missed in ("skip", "coalesce", "catch_up_one"):
        policies[missed] = journal.create_policy(
            job_kind="maintenance.validate",
            scope=_scope(instance),
            state="enabled",
            schedule=schedule_payload(
                mode="interval",
                timezone="UTC",
                interval_seconds=60,
                missed_run_policy=missed,
            ),
            now=start,
        )

    result = journal.evaluate(now=start + timedelta(seconds=181))
    assert len(result["created_jobs"]) == 2
    assert result["skipped_policies"] == [policies["skip"]["id"]]
    jobs = journal.list_jobs(limit=10)
    assert {job["reason"] for job in jobs} == {"coalesced", "catch_up"}
    assert all(job["attempt"] == 0 for job in jobs)

    repeated = journal.evaluate(now=start + timedelta(seconds=181))
    assert repeated["created_jobs"] == []
    assert len(journal.list_jobs(limit=10)) == 2

    reversed_clock = journal.evaluate(now=start - timedelta(minutes=10))
    assert set(reversed_clock["clock_changes"]) == {
        policy["id"] for policy in policies.values()
    }
    assert all(
        datetime.fromisoformat(policy["next_due_at"]) > start - timedelta(minutes=10)
        for policy in journal.list_policies()
    )


def test_scheduled_creation_is_idempotent_across_policy_commit_crash(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    journal = instance.scheduler.journal
    start = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    policy = journal.create_policy(
        job_kind="maintenance.validate",
        scope=_scope(instance),
        state="enabled",
        schedule=schedule_payload(
            mode="interval",
            timezone="UTC",
            interval_seconds=60,
            missed_run_policy="coalesce",
        ),
        now=start,
    )
    first = journal.evaluate(now=start + timedelta(seconds=181))
    assert len(first["created_jobs"]) == 1

    # Model a crash after the durable job write but before the policy cursor commit.
    journal._write_policy(policy)
    replay = journal.evaluate(now=start + timedelta(seconds=242))
    assert replay["created_jobs"] == []
    assert replay["duplicate_jobs"] == first["created_jobs"]
    assert len(journal.list_jobs()) == 1


def test_lease_heartbeat_checkpoint_retry_replay_and_receipt_are_durable(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    journal = instance.scheduler.journal
    start = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    policy = _manual_policy(
        instance,
        retry=retry_payload(max_attempts=3, base_seconds=10, max_seconds=40),
        now=start,
    )
    queued = journal.run_now(
        policy["id"],
        request_key="private/path/that-must-not-be-retained",
        now=start,
    )
    assert queued["created"] is True
    job_id = queued["job"]["id"]

    claimed = journal.claim_next(worker_id="test-worker", lease_seconds=10, now=start)
    assert claimed is not None and claimed["id"] == job_id
    public_running = instance.get_scheduler_job(job_id)
    assert public_running is not None
    assert "token" not in public_running["lease"]
    assert public_running["lease"]["token_present"] is True
    assert (
        journal.claim_next(worker_id="competing-worker", lease_seconds=10, now=start)
        is None
    )
    lease_token = claimed["lease"]["token"]
    heartbeat = journal.heartbeat(
        job_id,
        lease_token,
        lease_seconds=10,
        now=start + timedelta(seconds=5),
    )
    assert heartbeat["lease"]["expires_at"] == "2026-08-30T10:00:15+00:00"
    checkpoint = journal.checkpoint(
        job_id,
        lease_token,
        sequence=1,
        phase="executing",
        progress={"processed": 2, "skipped": 1, "errors": 0},
        now=start + timedelta(seconds=6),
    )
    assert checkpoint["checkpoint"]["sequence"] == 1

    recovery = journal.recover(now=start + timedelta(seconds=16))
    assert recovery["expired_leases"] == 1
    recovered = journal.get_job(job_id)
    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["recovery_state"] == "restart_only"
    assert recovered["recovery_count"] == 1

    second = journal.claim_next(
        worker_id="test-worker",
        lease_seconds=10,
        now=start + timedelta(seconds=16),
    )
    assert second is not None
    retrying = journal.fail(
        job_id,
        second["lease"]["token"],
        error_class="transient",
        error_code="local_io",
        progress=second["progress"],
        now=start + timedelta(seconds=17),
    )
    assert retrying["status"] == "retry_wait"
    assert retrying["retry_not_before"] == "2026-08-30T10:00:37+00:00"
    assert journal.recover(now=start + timedelta(seconds=36))["retries_ready"] == 0
    assert journal.recover(now=start + timedelta(seconds=37))["retries_ready"] == 1

    third = journal.claim_next(
        worker_id="test-worker",
        lease_seconds=10,
        now=start + timedelta(seconds=37),
    )
    assert third is not None and third["attempt"] == 3
    terminal = journal.succeed(
        job_id,
        third["lease"]["token"],
        progress={"processed": 4, "skipped": 1, "errors": 0},
        now=start + timedelta(seconds=38),
    )
    assert terminal["status"] == "succeeded"
    receipt = journal.list_receipts()[0]
    assert receipt["job_id"] == job_id
    assert receipt["attempts"] == 3
    assert receipt["network_used"] is False
    assert receipt["canonical_mutation"] is False
    assert receipt["automatic_deletion"] is False

    replay = journal.run_now(
        policy["id"],
        request_key="private/path/that-must-not-be-retained",
        now=start + timedelta(hours=1),
    )
    assert replay["created"] is False
    assert replay["job"]["id"] == job_id
    persisted = json.dumps({"job": terminal, "receipt": receipt}, sort_keys=True)
    assert "private/path" not in persisted
    assert "title" not in persisted
    assert "secret" not in persisted


def test_committed_checkpoint_never_becomes_falsely_successful(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    journal = instance.scheduler.journal
    start = datetime(2026, 8, 30, 11, 0, tzinfo=UTC)
    policy = _manual_policy(instance, now=start)
    job = journal.run_now(policy["id"], request_key="committed-crash", now=start)["job"]
    claimed = journal.claim_next(worker_id="crash-worker", lease_seconds=5, now=start)
    assert claimed is not None
    journal.checkpoint(
        job["id"],
        claimed["lease"]["token"],
        sequence=1,
        phase="committed",
        progress={"processed": 1, "skipped": 0, "errors": 0},
        now=start + timedelta(seconds=1),
    )
    journal.recover(now=start + timedelta(seconds=6))
    recovered = journal.get_job(job["id"])
    assert recovered is not None
    assert recovered["status"] == "manual_intervention"
    receipt = journal.list_receipts()[0]
    assert receipt["error_code"] == "committed_checkpoint_needs_review"


def test_backward_clock_change_expires_a_stale_lease_safely(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    journal = instance.scheduler.journal
    start = datetime(2026, 8, 30, 11, 15, tzinfo=UTC)
    policy = _manual_policy(instance, now=start)
    job = journal.run_now(policy["id"], request_key="clock-back", now=start)["job"]
    claimed = journal.claim_next(worker_id="clock-worker", lease_seconds=30, now=start)
    assert claimed is not None

    recovery = journal.recover(now=start - timedelta(hours=1))
    assert recovery["expired_leases"] == 1
    assert recovery["clock_changes"] == 1
    recovered = journal.get_job(job["id"])
    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["recovery_state"] == "restart_only"
    assert recovered["attempts"][-1]["error_code"] == "lease_clock_reversed"


def test_receipt_first_crash_is_reconciled_without_reexecuting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    journal = instance.scheduler.journal
    start = datetime(2026, 8, 30, 11, 30, tzinfo=UTC)
    policy = _manual_policy(instance, now=start)
    job = journal.run_now(policy["id"], request_key="receipt-first", now=start)["job"]
    claimed = journal.claim_next(worker_id="crash-worker", lease_seconds=30, now=start)
    assert claimed is not None
    original_write_job = journal._write_job

    def fail_terminal_job_write(value):
        if value.get("status") == "succeeded":
            raise OSError("synthetic crash after immutable receipt")
        return original_write_job(value)

    monkeypatch.setattr(journal, "_write_job", fail_terminal_job_write)
    with pytest.raises(OSError, match="synthetic crash"):
        journal.succeed(
            job["id"],
            claimed["lease"]["token"],
            progress={"processed": 1, "skipped": 0, "errors": 0},
            now=start + timedelta(seconds=1),
        )

    reopened = SchedulerStore(instance.store)
    assert reopened.get_job(job["id"])["status"] == "running"
    recovery = reopened.recover(now=start + timedelta(seconds=2))
    assert recovery["receipts_reconciled"] == 1
    reconciled = reopened.get_job(job["id"])
    assert reconciled is not None
    assert reconciled["status"] == "succeeded"
    assert reconciled["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    assert reconciled["attempts"][-1]["outcome"] == "succeeded"


def test_safe_local_executors_create_terminal_receipts(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("scheduler reindex fixture", encoding="utf-8")
    instance.ingest(source)
    (instance.root / "indexes" / "search.sqlite3").unlink()

    validation = _manual_policy(instance, job_kind="maintenance.validate")
    instance.schedule_run_now(validation["id"], request_key="validate-once")
    validation_result = instance.run_scheduler_cycle(max_jobs=1)
    assert validation_result["jobs"][0]["status"] == "succeeded"
    validation_job = validation_result["jobs"][0]
    assert validation_job["checkpoint"]["sequence"] == 3
    assert validation_job["checkpoint"]["phase"] == "committed"
    assert datetime.fromisoformat(
        validation_job["checkpoint"]["committed_at"]
    ) <= datetime.fromisoformat(validation_job["updated_at"])

    reindex = _manual_policy(instance, job_kind="search.reindex")
    instance.schedule_run_now(reindex["id"], request_key="reindex-once")
    reindex_result = instance.run_scheduler_cycle(max_jobs=1)
    assert reindex_result["jobs"][0]["status"] == "succeeded"
    assert reindex_result["jobs"][0]["progress"]["processed"] == 1
    assert instance.search("scheduler")[0]["title"] == "note.txt"
    assert instance.scheduler_status()["receipts"] == 2


def test_execution_serializes_with_instance_lifecycle_and_heartbeats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    policy = _manual_policy(
        instance,
        retry=retry_payload(max_attempts=2, base_seconds=1, max_seconds=2),
    )
    instance.schedule_run_now(policy["id"], request_key="busy")
    with InstanceLifecycleManager(instance.store)._hold(purpose="synthetic-writer"):
        observer = ProvelumeInstance(instance.root)
        assert observer.scheduler_status()["startup_recovery"]["deferred"] is True
        with pytest.raises(SchedulerBusyError, match="another Instance operation"):
            instance.run_scheduler_cycle(max_jobs=1)
    queued = instance.list_scheduler_jobs()[0]
    assert queued["status"] == "queued"
    assert queued["attempt"] == 0

    journal = instance.scheduler.journal
    heartbeat_calls = []
    original_heartbeat = journal.heartbeat

    def observed_heartbeat(*args, **kwargs):
        heartbeat_calls.append(str(args[0]))
        return original_heartbeat(*args, **kwargs)

    def slow_success(_job):
        time.sleep(1.1)
        return (
            True,
            {"processed": 1, "skipped": 0, "errors": 0},
            "",
            "",
            False,
            False,
        )

    monkeypatch.setattr(journal, "heartbeat", observed_heartbeat)
    monkeypatch.setattr(instance.scheduler, "_execute", slow_success)
    finished = instance.scheduler.run_one(lease_seconds=3)
    assert finished is not None and finished["status"] == "succeeded"
    assert heartbeat_calls == [finished["id"]]


def test_heartbeat_is_bounded_to_executor_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    policy = _manual_policy(instance)
    instance.schedule_run_now(policy["id"], request_key="heartbeat-order")
    journal = instance.scheduler.journal
    checkpoint_phases: list[str] = []
    thread_events: list[tuple[str, tuple[str, ...]]] = []
    original_checkpoint = journal.checkpoint

    def observed_checkpoint(*args, **kwargs):
        checkpoint_phases.append(str(kwargs["phase"]))
        return original_checkpoint(*args, **kwargs)

    class ObservedThread:
        def __init__(self, *, target, name, daemon):
            del target, name, daemon

        def start(self) -> None:
            thread_events.append(("start", tuple(checkpoint_phases)))

        def join(self) -> None:
            thread_events.append(("join", tuple(checkpoint_phases)))

    monkeypatch.setattr(journal, "checkpoint", observed_checkpoint)
    monkeypatch.setattr(scheduler_module, "Thread", ObservedThread)
    monkeypatch.setattr(
        instance.scheduler,
        "_execute",
        lambda _job: (
            True,
            {"processed": 1, "skipped": 0, "errors": 0},
            "",
            "",
            False,
            False,
        ),
    )

    finished = instance.scheduler.run_one(lease_seconds=3)

    assert finished is not None and finished["status"] == "succeeded"
    assert checkpoint_phases == ["prepared", "executing", "committed"]
    assert thread_events == [
        ("start", ("prepared", "executing")),
        ("join", ("prepared", "executing")),
    ]


def test_scheduler_state_survives_restart_backup_restore_and_portable_import(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    policy = _manual_policy(instance)
    policy_relative = f"state/scheduler/policies/{policy['id']}.json"

    backup = instance.backup(destination=tmp_path / "backups", reason="scheduler-test")
    with zipfile.ZipFile(backup["archive"]) as bundle:
        assert f"payload/{policy_relative}" in bundle.namelist()

    portable = instance.export_portable(tmp_path / "exports", derived_state="rebuild")
    with zipfile.ZipFile(portable["archive"]) as bundle:
        assert f"instance/{policy_relative}" in bundle.namelist()

    policy_path = instance.root / policy_relative
    policy_path.unlink()
    restarted = ProvelumeInstance(instance.root)
    assert restarted.list_schedule_policies() == []
    restarted.restore(backup["archive"])
    restored = ProvelumeInstance(instance.root)
    assert restored.get_schedule_policy(policy["id"]) is not None

    (restored.root / policy_relative).unlink()
    restored.import_portable(portable["archive"])
    imported = ProvelumeInstance(instance.root)
    assert imported.get_schedule_policy(policy["id"]) is not None
    assert imported.store.read_config()["schema_version"] == 2


def test_scheduler_cli_api_browser_and_state_validation(tmp_path: Path, capsys) -> None:
    root = tmp_path / "instance"
    ProvelumeInstance.initialise(root)
    assert (
        main(
            [
                "scheduler-policy-create",
                str(root),
                "--kind",
                "maintenance.validate",
                "--mode",
                "manual",
                "--state",
                "disabled",
            ]
        )
        == 0
    )
    policy = json.loads(capsys.readouterr().out)
    assert policy["schedule"]["timezone"] == "UTC"
    assert (
        main(
            [
                "scheduler-run-now",
                str(root),
                policy["id"],
                "--idempotency-key",
                "cli-once",
            ]
        )
        == 0
    )
    queued = json.loads(capsys.readouterr().out)
    assert queued["created"] is True
    assert main(["scheduler-run", str(root), "--max-jobs", "1"]) == 0
    cycle = json.loads(capsys.readouterr().out)
    assert cycle["jobs"][0]["status"] == "succeeded"
    assert main(["scheduler-receipts", str(root), "--limit", "10"]) == 0
    receipts = json.loads(capsys.readouterr().out)
    assert len(receipts) == 1
    assert receipts[0]["job_id"] == queued["job"]["id"]

    app = create_app(root)
    with TestClient(app) as client:
        status = client.get("/api/v1/scheduler")
        assert status.status_code == 200
        assert status.json()["receipts"] == 1
        policies = client.get("/api/v1/scheduler/policies")
        assert policies.status_code == 200
        assert policies.json()[0]["id"] == policy["id"]
        job = client.get(f"/api/v1/scheduler/jobs/{queued['job']['id']}")
        assert job.status_code == 200
        assert job.json()["status"] == "succeeded"
        assert client.get("/scheduler?lang=en").status_code == 200
        assert "Scheduler &amp; job journal" in client.get("/scheduler?lang=en").text
        assert "Scheduler e registro job" in client.get("/scheduler?lang=it").text

    instance = ProvelumeInstance(root)
    policy_path = (
        root / "state" / "scheduler" / "policies" / f"{policy['id']}.json"
    )
    corrupted = json.loads(policy_path.read_text(encoding="utf-8"))
    corrupted["job_kind"] = "hidden.network"
    policy_path.write_text(json.dumps(corrupted), encoding="utf-8")
    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(error["code"] == "scheduler_record_invalid" for error in report["errors"])


def test_deep_validation_binds_terminal_job_to_exact_receipt(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    policy = _manual_policy(instance)
    job = instance.schedule_run_now(policy["id"], request_key="receipt-binding")["job"]
    finished = instance.run_scheduler_cycle(max_jobs=1)["jobs"][0]
    receipt_path = instance.root / finished["receipt_ref"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["scope"] = {"kind": "instance", "id": "inst_" + "f" * 32}
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(
        error["code"] in {"scheduler_receipt_missing", "scheduler_job_receipt_mismatch"}
        for error in report["errors"]
    )
    assert instance.get_scheduler_job(job["id"])["status"] == "succeeded"


def test_scheduler_state_root_fails_closed_when_not_a_directory(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    scheduler_root = instance.root / "state" / "scheduler"
    scheduler_root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(SchedulerError, match="directory is invalid"):
        instance.scheduler_status()
    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(
        error["code"] == "scheduler_directory_invalid"
        and error["path"] == "state/scheduler"
        for error in report["errors"]
    )


def test_scheduler_store_rejects_duplicate_and_invalid_record_fields(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    journal = SchedulerStore(instance.store)
    policy = _manual_policy(instance)
    first = journal.run_now(policy["id"], request_key="same")
    second = journal.run_now(policy["id"], request_key="same")
    assert first["created"] is True
    assert second["created"] is False
    assert len(journal.list_jobs()) == 1

    # Claiming uses the complete durable journal, not the API/UI presentation limit.
    journal.list_jobs = lambda **_kwargs: []  # type: ignore[method-assign]
    claimed = journal.claim_next(worker_id="complete-journal-worker")
    assert claimed is not None and claimed["id"] == first["job"]["id"]
    with pytest.raises(SchedulerError, match="invalid error code"):
        journal.fail(
            claimed["id"],
            claimed["lease"]["token"],
            error_class="permanent",
            error_code="document_content_as_error",
            progress=claimed["progress"],
        )


def test_retry_wait_job_can_be_cancelled_without_erasing_attempt_evidence(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    journal = instance.scheduler.journal
    start = datetime(2026, 8, 30, 15, 0, tzinfo=UTC)
    policy = _manual_policy(
        instance,
        retry=retry_payload(max_attempts=2, base_seconds=10, max_seconds=10),
        now=start,
    )
    job = journal.run_now(policy["id"], request_key="cancel-retry", now=start)["job"]
    claimed = journal.claim_next(worker_id="cancel-worker", now=start)
    assert claimed is not None
    retrying = journal.fail(
        job["id"],
        claimed["lease"]["token"],
        error_class="transient",
        error_code="local_io",
        progress={"processed": 0, "skipped": 0, "errors": 1},
        now=start + timedelta(seconds=1),
    )
    assert retrying["status"] == "retry_wait"

    cancelled = journal.cancel(job["id"], now=start + timedelta(seconds=2))
    assert cancelled["status"] == "cancelled"
    assert cancelled["attempts"][-1]["outcome"] == "retry"
    assert journal.list_receipts()[0]["error_code"] == "cancelled_by_user"
    assert instance.validate_instance(deep=True)["status"] == "valid"
