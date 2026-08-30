from __future__ import annotations

import json
import os
import re
import zipfile
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from provelume import resource_statistics as statistics_module
from provelume.cli import main
from provelume.resource_statistics import ResourceStatisticsManager
from provelume.resource_statistics_model import (
    RESOURCE_CATEGORIES,
    ResourceStatisticsChangedError,
    ResourceStatisticsLimitError,
    ResourceStatisticsStateError,
)
from provelume.scheduler import retry_payload, schedule_payload
from provelume.service import ProvelumeInstance
from provelume.storage import CANONICAL_KINDS
from provelume.web import create_app


def _instance(tmp_path: Path) -> ProvelumeInstance:
    return ProvelumeInstance.initialise(
        tmp_path / "instance",
        name="Resource statistics fixture",
    )


def _scope(instance: ProvelumeInstance) -> dict[str, str]:
    return {"kind": "instance", "id": instance.instance_summary()["id"]}


def _policy(
    instance: ProvelumeInstance,
    *,
    now: datetime,
    attempts: int = 3,
) -> dict[str, object]:
    return instance.scheduler.journal.create_policy(
        job_kind="maintenance.resource_snapshot",
        scope=_scope(instance),
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(
            max_attempts=attempts,
            base_seconds=1,
            max_seconds=2,
        ),
        now=now,
    )


def _run(
    instance: ProvelumeInstance,
    policy: dict[str, object],
    *,
    key: str,
    now: datetime,
) -> tuple[dict[str, object], dict[str, object]]:
    queued = instance.scheduler.journal.run_now(
        str(policy["id"]),
        request_key=key,
        now=now,
    )["job"]
    result = instance.scheduler.run_one(job_id=str(queued["id"]), now=now)
    assert result is not None
    return queued, result


def _canonical_snapshot(
    instance: ProvelumeInstance,
) -> dict[str, list[dict[str, object]]]:
    return {
        kind: instance.store.list_canonical(kind)
        for kind in CANONICAL_KINDS
    }


def _fixed_capacity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    total: int = 1_000_000,
    used: int = 400_000,
    free: int = 600_000,
) -> None:
    assert total == used + free
    monkeypatch.setattr(
        statistics_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=total, used=used, free=free),
    )


def test_scan_aggregates_closed_authority_categories_without_following_symlinks(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    manager = instance.resource_statistics
    before, before_files, before_bytes = manager._scan()
    payloads = {
        instance.root / "originals" / "synthetic.bin": b"original-bytes",
        instance.root / "knowledge" / "synthetic.json": b"{}",
        instance.root / "indexes" / "synthetic.idx": b"index",
        instance.root / "library" / "synthetic.md": b"projection",
        instance.root / "state" / "derived" / "synthetic.txt": b"derived",
        instance.root / "state" / "synthetic.json": b"state",
        instance.root / "inbox" / "synthetic.bin": b"inbox",
        instance.root / "operator-note.bin": b"other",
    }
    for path, content in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    outside = tmp_path / "outside-private-marker.txt"
    outside.write_bytes(b"must-not-be-counted")
    link = instance.root / "outside-link"
    with suppress(OSError):
        os.symlink(outside, link)

    categories, file_count, byte_count = manager._scan()
    assert tuple(categories) == RESOURCE_CATEGORIES
    assert file_count - before_files == len(payloads)
    assert byte_count - before_bytes == sum(len(value) for value in payloads.values())
    expected_categories = {
        "canonical_originals": 1,
        "canonical_records": 1,
        "derived_assets": 3,
        "operational_state": 1,
        "managed_inbox": 1,
        "other": 1,
    }
    for category, added in expected_categories.items():
        assert (
            categories[category]["file_count"]
            - before[category]["file_count"]
            == added
        )
    assert sum(item["file_count"] for item in categories.values()) == file_count
    assert sum(item["byte_count"] for item in categories.values()) == byte_count
    assert "outside-private-marker" not in json.dumps(categories)


def test_statistics_state_parent_symlink_fails_closed_without_reading_target(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    outside = tmp_path / "outside-statistics-state"
    outside.mkdir()
    (outside / "private-marker.txt").write_text("private target", encoding="utf-8")
    try:
        instance.resource_statistics.root.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable on this platform")
    with pytest.raises(ResourceStatisticsStateError, match="directory is unsafe"):
        instance.resource_statistics.status()
    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(
        finding["code"] == "resource_statistics_directory_invalid"
        for finding in report["errors"]
    )


def test_scan_rejects_directory_addition_at_the_stability_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    observed = instance.root / "observed"
    observed.mkdir()
    (observed / "stable.bin").write_bytes(b"stable")

    def add_late_file() -> None:
        (observed / "late.bin").write_bytes(b"late")

    monkeypatch.setattr(
        instance.resource_statistics,
        "_after_scan_walk",
        add_late_file,
    )
    with pytest.raises(ResourceStatisticsChangedError, match="membership changed"):
        instance.resource_statistics._scan()


def test_threshold_boundaries_and_trends_are_durable_and_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    _fixed_capacity(monkeypatch)
    canonical_before = _canonical_snapshot(instance)
    warning = instance.configure_resource_thresholds(
        minimum_free_bytes_warning=700_000,
        minimum_free_bytes_critical=500_000,
    )
    assert warning["revision"] == 1
    base = datetime(2026, 8, 30, 11, 0, tzinfo=UTC)
    policy = _policy(instance, now=base)
    _queued, first_job = _run(
        instance,
        policy,
        key="resource-warning",
        now=base,
    )
    assert first_job["status"] == "succeeded"
    first = instance.list_resource_snapshots()[0]
    assert first["sequence"] == 1
    assert first["thresholds"]["state"] == "warning"
    assert first["thresholds"]["codes"] == ["minimum_free_bytes_warning"]
    assert first["capacity"] == {
        "total_bytes": 1_000_000,
        "used_bytes": 400_000,
        "free_bytes": 600_000,
        "reserved_bytes": 0,
    }
    assert first["delta"] is None

    critical = instance.configure_resource_thresholds(
        minimum_free_bytes_warning=700_000,
        minimum_free_bytes_critical=650_000,
    )
    assert critical["revision"] == 2
    added = instance.root / "operator-growth.bin"
    added.write_bytes(b"bounded-growth")
    later = base + timedelta(minutes=5)
    _queued, second_job = _run(
        instance,
        policy,
        key="resource-critical",
        now=later,
    )
    assert second_job["status"] == "succeeded"
    second, retained_first = instance.list_resource_snapshots()
    assert retained_first == first
    assert second["sequence"] == 2
    assert second["previous_snapshot_id"] == first["id"]
    assert second["thresholds"]["state"] == "critical"
    assert second["thresholds"]["codes"] == ["minimum_free_bytes_critical"]
    assert second["delta"]["elapsed_seconds"] == 300
    assert second["delta"]["clock_reversed"] is False
    assert second["delta"]["categories"]["other"]["file_count"] == 1
    assert second["delta"]["categories"]["other"]["byte_count"] == len(
        b"bounded-growth"
    )
    assert second["delta"]["file_count"] == (
        second["file_count"] - first["file_count"]
    )
    assert second["delta"]["byte_count"] == second["byte_count"] - first["byte_count"]
    assert _canonical_snapshot(instance) == canonical_before
    serialized = json.dumps(instance.resource_statistics_status())
    assert str(instance.root) not in serialized
    assert "operator-growth.bin" not in serialized
    assert "bounded-growth" not in serialized


def test_clock_reversal_is_explicit_without_breaking_monotonic_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    _fixed_capacity(monkeypatch)
    base = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    policy = _policy(instance, now=base)
    _run(instance, policy, key="clock-normal", now=base)
    reversed_time = base - timedelta(hours=1)
    _run(
        instance,
        policy,
        key="clock-reversed-observation",
        now=reversed_time,
    )
    latest = instance.list_resource_snapshots()[0]
    assert latest["sequence"] == 2
    assert latest["delta"]["clock_reversed"] is True
    assert latest["delta"]["elapsed_seconds"] == 0
    assert instance.validate_instance(deep=True)["status"] == "valid"


def test_snapshot_commit_before_receipt_replays_without_duplicate_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    _fixed_capacity(monkeypatch)
    base = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
    policy = _policy(instance, now=base)
    job = instance.scheduler.journal.run_now(
        str(policy["id"]),
        request_key="crash-after-snapshot",
        now=base,
    )["job"]
    calls = 0

    def interrupt_once(
        _self: ResourceStatisticsManager,
        _snapshot: dict[str, object],
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic interruption after resource snapshot")

    monkeypatch.setattr(
        ResourceStatisticsManager,
        "_after_snapshot_write",
        interrupt_once,
    )
    waiting = instance.scheduler.run_one(job_id=str(job["id"]), now=base)
    assert waiting is not None
    assert waiting["status"] == "retry_wait"
    assert waiting["attempts"][-1]["error_code"] == "local_io"
    committed = instance.list_resource_snapshots()
    assert len(committed) == 1
    assert committed[0]["job_id"] == job["id"]

    retry_at = base + timedelta(seconds=1)
    instance.scheduler.recover(now=retry_at)
    finished = instance.scheduler.run_one(job_id=str(job["id"]), now=retry_at)
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["attempt"] == 2
    assert calls == 1
    assert instance.list_resource_snapshots() == committed
    receipt = instance.scheduler.journal.get_receipt(
        f"receipt_{str(job['id']).removeprefix('job_')}"
    )
    assert receipt is not None
    assert receipt["network_used"] is False
    assert receipt["canonical_mutation"] is False
    assert receipt["automatic_deletion"] is False
    assert instance.validate_instance(deep=True)["status"] == "valid"


def test_filesystem_churn_retries_boundedly_and_limit_failure_is_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    _fixed_capacity(monkeypatch)
    base = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
    policy = _policy(instance, now=base)
    original_scan = ResourceStatisticsManager._scan
    calls = 0

    def changed_once(
        manager: ResourceStatisticsManager,
        *,
        job_id: str | None = None,
    ) -> tuple[dict[str, dict[str, int]], int, int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ResourceStatisticsChangedError("synthetic filesystem churn")
        return original_scan(manager, job_id=job_id)

    monkeypatch.setattr(ResourceStatisticsManager, "_scan", changed_once)
    job = instance.scheduler.journal.run_now(
        str(policy["id"]),
        request_key="resource-churn",
        now=base,
    )["job"]
    waiting = instance.scheduler.run_one(job_id=str(job["id"]), now=base)
    assert waiting is not None
    assert waiting["status"] == "retry_wait"
    assert waiting["attempts"][-1]["error_code"] == "resource_statistics_changed"
    assert instance.list_resource_snapshots() == []
    retry_at = base + timedelta(seconds=1)
    instance.scheduler.recover(now=retry_at)
    finished = instance.scheduler.run_one(job_id=str(job["id"]), now=retry_at)
    assert finished is not None and finished["status"] == "succeeded"
    assert len(instance.list_resource_snapshots()) == 1

    monkeypatch.setattr(
        ResourceStatisticsManager,
        "_scan",
        lambda _manager, **_kwargs: (_ for _ in ()).throw(
            ResourceStatisticsLimitError("synthetic resource bound")
        ),
    )
    limit_time = base + timedelta(minutes=1)
    limit_job = instance.scheduler.journal.run_now(
        str(policy["id"]),
        request_key="resource-limit",
        now=limit_time,
    )["job"]
    failed = instance.scheduler.run_one(job_id=str(limit_job["id"]), now=limit_time)
    assert failed is not None and failed["status"] == "failed"
    assert failed["attempts"][-1]["error_code"] == "resource_statistics_limit"
    assert len(instance.list_resource_snapshots()) == 1


def test_threshold_validation_fails_closed_without_overwriting_settings(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    original = instance.configure_resource_thresholds(
        minimum_free_bytes_warning=100,
        minimum_free_bytes_critical=50,
        maximum_instance_bytes_warning=1_000,
        maximum_instance_bytes_critical=2_000,
    )
    with pytest.raises(ResourceStatisticsStateError, match="cannot exceed warning"):
        instance.configure_resource_thresholds(
            minimum_free_bytes_warning=50,
            minimum_free_bytes_critical=100,
        )
    with pytest.raises(ResourceStatisticsStateError, match="cannot precede warning"):
        instance.configure_resource_thresholds(
            maximum_instance_bytes_warning=2_000,
            maximum_instance_bytes_critical=1_000,
        )
    assert instance.resource_statistics.threshold_settings() == original
    warning = instance.resource_statistics._evaluate(
        byte_count=1_000,
        free_bytes=10_000,
        settings=original,
    )
    critical = instance.resource_statistics._evaluate(
        byte_count=2_000,
        free_bytes=10_000,
        settings=original,
    )
    assert warning["state"] == "warning"
    assert warning["codes"] == ["maximum_instance_bytes_warning"]
    assert critical["state"] == "critical"
    assert critical["codes"] == ["maximum_instance_bytes_critical"]


def test_resource_state_is_backed_up_exported_restored_and_imported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    _fixed_capacity(monkeypatch)
    instance.configure_resource_thresholds(
        minimum_free_bytes_warning=700_000,
        minimum_free_bytes_critical=500_000,
    )
    result = instance.run_maintenance_action(
        "maintenance.resource_snapshot",
        request_key="portable-resource-snapshot",
    )
    assert result["job"]["status"] == "succeeded"
    snapshot = instance.list_resource_snapshots()[0]
    settings_relative = "state/resource-statistics/thresholds.json"
    snapshot_relative = (
        "state/resource-statistics/snapshots/" f"{snapshot['id']}.json"
    )
    backup = instance.backup(
        destination=tmp_path / "backups",
        reason="resource-statistics-test",
    )
    with zipfile.ZipFile(backup["archive"]) as archive:
        assert f"payload/{settings_relative}" in archive.namelist()
        assert f"payload/{snapshot_relative}" in archive.namelist()
    portable = instance.export_portable(
        tmp_path / "exports",
        derived_state="rebuild",
    )
    with zipfile.ZipFile(portable["archive"]) as archive:
        assert f"instance/{settings_relative}" in archive.namelist()
        assert f"instance/{snapshot_relative}" in archive.namelist()

    (instance.root / settings_relative).unlink()
    (instance.root / snapshot_relative).unlink()
    instance.restore(backup["archive"])
    restored = ProvelumeInstance(instance.root)
    assert restored.get_resource_snapshot(str(snapshot["id"])) == snapshot
    assert restored.validate_instance(deep=True)["status"] == "valid"

    target = ProvelumeInstance.initialise(tmp_path / "portable-target")
    target.import_portable(portable["archive"])
    imported = ProvelumeInstance(target.root)
    assert imported.get_resource_snapshot(str(snapshot["id"])) == snapshot
    assert imported.validate_instance(deep=True)["status"] == "valid"


def test_corrupt_snapshot_is_visible_to_validation_and_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    _fixed_capacity(monkeypatch)
    result = instance.run_maintenance_action(
        "maintenance.resource_snapshot",
        request_key="corrupt-resource-state",
    )
    assert result["job"]["status"] == "succeeded"
    snapshot = instance.list_resource_snapshots()[0]
    path = (
        instance.root
        / "state"
        / "resource-statistics"
        / "snapshots"
        / f"{snapshot['id']}.json"
    )
    corrupted = json.loads(path.read_text(encoding="utf-8"))
    corrupted["absolute_path"] = str(instance.root)
    path.write_text(json.dumps(corrupted), encoding="utf-8")
    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(
        finding["code"] == "resource_statistics_record_invalid"
        for finding in report["errors"]
    )
    with TestClient(create_app(instance.root), raise_server_exceptions=False) as client:
        response = client.get("/api/v1/maintenance/resource-statistics")
        assert response.status_code == 500

    rebound = {**snapshot, "observed_at": "2026-08-31T00:00:00+00:00"}
    path.write_text(json.dumps(rebound), encoding="utf-8")
    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(
        finding["code"] == "resource_statistics_binding_invalid"
        for finding in report["errors"]
    )


def test_service_cli_api_and_browser_expose_semantically_aligned_statistics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance = _instance(tmp_path)
    _fixed_capacity(monkeypatch)
    private_name = "private-resource-name.txt"
    private_content = "private-resource-content-marker"
    (instance.root / private_name).write_text(private_content, encoding="utf-8")
    result = instance.run_maintenance_action(
        "maintenance.resource_snapshot",
        request_key="resource-surfaces",
    )
    assert result["job"]["status"] == "succeeded"
    snapshot = instance.list_resource_snapshots()[0]
    serialized = json.dumps(snapshot)
    assert str(instance.root) not in serialized
    assert private_name not in serialized
    assert private_content not in serialized

    app = create_app(instance.root)
    with TestClient(app) as client:
        status = client.get("/api/v1/maintenance/resource-statistics")
        history = client.get(
            "/api/v1/maintenance/resource-statistics/snapshots"
        )
        detail = client.get(
            f"/api/v1/maintenance/resource-statistics/snapshots/{snapshot['id']}"
        )
        missing = client.get(
            "/api/v1/maintenance/resource-statistics/snapshots/resource_"
            + "0" * 32
        )
        assert status.status_code == history.status_code == detail.status_code == 200
        assert missing.status_code == 404
        assert status.json()["latest"]["id"] == snapshot["id"]
        assert history.json()[0]["id"] == snapshot["id"]
        assert detail.json() == snapshot
        api_text = json.dumps(status.json())
        assert str(instance.root) not in api_text
        assert private_name not in api_text
        assert private_content not in api_text

        english = client.get("/maintenance?lang=en")
        italian = client.get("/maintenance?lang=it")
        assert english.status_code == italian.status_code == 200
        assert "Instance resource statistics" in english.text
        assert "Statistiche risorse dell&#39;Instance" in italian.text
        assert "Instance resource snapshot" in english.text
        assert "Snapshot delle risorse dell&#39;Instance" in italian.text
        assert str(snapshot["file_count"]) in english.text
        for page in (english.text, italian.text):
            assert str(instance.root) not in page
            assert private_name not in page
            assert private_content not in page

    assert main(["maintenance-resource-status", str(instance.root)]) == 0
    cli_status = json.loads(capsys.readouterr().out)
    assert cli_status["latest"]["id"] == snapshot["id"]
    assert main(["maintenance-resource-snapshots", str(instance.root)]) == 0
    cli_history = json.loads(capsys.readouterr().out)
    assert cli_history[0]["id"] == snapshot["id"]
    assert main(
        [
            "maintenance-resource-snapshot",
            str(instance.root),
            str(snapshot["id"]),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out) == snapshot
    assert main(
        [
            "maintenance-resource-thresholds-set",
            str(instance.root),
            "--minimum-free-bytes-warning",
            "700000",
            "--minimum-free-bytes-critical",
            "500000",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == 1


def test_public_resource_statistics_contract_is_explicit() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = (
        root
        / "docs"
        / "architecture"
        / "resource-statistics-capacity-and-thresholds.md"
    ).read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    api = (root / "docs" / "api.md").read_text(encoding="utf-8")

    for required in (
        "logical bytes",
        "regular files",
        "minimum_free_bytes_warning",
        "maximum_instance_bytes_critical",
        "clock_reversed",
        "network_used: false",
        "canonical_mutation: false",
        "automatic_deletion: false",
        "never reads file content",
        "no automatic retention",
    ):
        assert required in contract
    assert "issue [#130]" in readme
    assert "maintenance/resource-statistics" in api
    assert re.search(
        r"Package, embedded build identity, tag and latest public release remain `0\.7\.0`",
        readme,
    )
