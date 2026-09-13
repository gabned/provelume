from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from provelume import capacity_admission as module
from provelume.capacity_admission import CapacityAdmission, CapacityAdmissionError
from provelume.storage import InstanceStore


def files(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def manager(tmp_path):
    return CapacityAdmission(InstanceStore.initialise(tmp_path / "i", name="Synthetic admission"))


def configure(manager, mode, revision=0, key="policy-request-0001"):
    return manager.configure(mode, expected_revision=revision, request_id=key)


def limits(manager, **values):
    settings = {
        key: None
        for key in (
            "minimum_free_bytes_warning",
            "minimum_free_bytes_critical",
            "maximum_instance_bytes_warning",
            "maximum_instance_bytes_critical",
        )
    }
    settings.update(values)
    manager.resources.configure_thresholds(settings)


def capacity(manager, monkeypatch, *, free=100):
    monkeypatch.setattr(
        manager.resources,
        "_capacity",
        lambda: {
            "total_bytes": 1000,
            "used_bytes": 1000 - free,
            "free_bytes": free,
            "reserved_bytes": 0,
        },
    )


def read(manager):
    return json.loads(manager.path.read_text())


def write(manager, value):
    manager.path.parent.mkdir(parents=True, exist_ok=True)
    manager.path.write_text(json.dumps(value))


def test_default_get_is_pure_and_not_an_admission_permit(manager, tmp_path, monkeypatch):
    before = files(tmp_path)
    monkeypatch.setattr(manager.resources, "_scan", lambda: pytest.fail("observe-only scans"))
    monkeypatch.setattr(manager.resources, "_capacity", lambda: pytest.fail("observe-only probes"))
    assert manager.status()["revision"] == 0
    result = manager.check_admission()
    assert result["allowed"] is True and result["reason"] == "observation_only"
    assert result["observation"] is None and result["reusable_permit"] is False
    assert result["running_jobs_stopped"] is False and result["automatic_deletion"] is False
    assert files(tmp_path) == before


def test_configure_cas_replay_private_instance_binding(manager):
    before = files(manager.store.paths.root)
    original = configure(manager, "paused")
    payload = manager.path.read_bytes()
    assert original["replayed"] is False
    assert manager.status()["revision"] == 1
    assert configure(manager, "paused")["replayed"] is True
    assert manager.path.read_bytes() == payload
    with pytest.raises(CapacityAdmissionError, match="request_conflict"):
        configure(manager, "observe_only")
    with pytest.raises(CapacityAdmissionError, match="capacity_policy_stale"):
        configure(manager, "paused", key="policy-request-0002")
    assert manager.path.parent == manager.lifecycle.control_root
    assert files(manager.store.paths.root) == before


@pytest.mark.parametrize(
    "damage",
    [
        "revision",
        "mode",
        "digest",
        "receipt_revision",
        "naive_time",
        "wait_naive",
        "future_schema",
        "boolean_schema",
        "foreign_instance",
        "null",
    ],
)
def test_invalid_policy_records_fail_closed(manager, damage):
    configure(manager, "paused")
    value = read(manager)
    if damage == "revision":
        value["revision"] = 2
    elif damage == "mode":
        value["mode"] = "observe_only"
    elif damage == "digest":
        value["receipts"][0]["request_digest"] = "0" * 64
    elif damage == "receipt_revision":
        value["receipts"][0]["revision"] = 0
    elif damage == "naive_time":
        value["receipts"][0]["at"] = "2026-09-13T10:00:00"
    elif damage == "wait_naive":
        value["last_wait"] = {
            "reason": "manual_pause",
            "observed_at": "2026-09-13T10:00:00",
            "required_bytes": 1,
            "policy_revision": 1,
        }
    elif damage == "future_schema":
        value["schema_version"] = 2
    elif damage == "boolean_schema":
        value["schema_version"] = True
    elif damage == "foreign_instance":
        value["instance_id"] = "inst_" + "a" * 32
    else:
        value = None
    write(manager, value)
    before = manager.path.read_bytes()
    with pytest.raises(CapacityAdmissionError):
        manager.check_admission(record_wait=True)
    assert manager.path.read_bytes() == before


def test_manual_wait_is_persisted_only_on_explicit_check_and_cleared_by_new_policy(manager):
    configure(manager, "paused")
    assert manager.check_admission(required_bytes=100)["reason"] == "manual_pause"
    assert manager.status()["last_wait"] is None
    decision = manager.check_admission(required_bytes=100, record_wait=True)
    waiting = manager.status()["last_wait"]
    assert waiting == {
        key: decision[key] for key in ("reason", "observed_at", "required_bytes", "policy_revision")
    }
    assert manager.status()["last_wait_is_live_capacity"] is False
    configure(manager, "observe_only", 1, "policy-request-0002")
    assert manager.status()["last_wait"] is None


def test_critical_capacity_uses_live_free_bytes_and_projected_requirement(manager, monkeypatch):
    limits(manager, minimum_free_bytes_critical=50)
    configure(manager, "pause_on_critical")
    capacity(manager, monkeypatch, free=100)
    monkeypatch.setattr(
        manager.resources, "_scan", lambda: pytest.fail("no size threshold needs a scan")
    )
    decision = manager.check_admission(required_bytes=60, record_wait=True)
    assert decision["allowed"] is False and decision["reason"] == "critical_capacity"
    observation = decision["observation"]
    assert observation["free_bytes"] == 100
    assert observation["projected_free_bytes"] == 40
    assert observation["instance_bytes"] is None
    assert observation["state"] == "critical"
    assert manager.status()["last_wait"]["required_bytes"] == 60
    capacity(manager, monkeypatch, free=500)
    assert manager.check_admission(required_bytes=60, record_wait=True)["allowed"] is True
    assert manager.status()["last_wait"] is None


def test_size_threshold_observes_actual_instance_not_stored_snapshot(manager, monkeypatch):
    configure(manager, "pause_on_critical")
    measured = manager.resources._scan()[2]
    limits(manager, maximum_instance_bytes_critical=measured + 50_000)
    capacity(manager, monkeypatch, free=1000)
    first = manager.check_admission()
    assert first["allowed"] is True
    assert first["observation"]["instance_bytes"] == manager.resources._scan()[2]
    (manager.store.paths.root / "synthetic-large.bin").write_bytes(b"x" * 60_000)
    second = manager.check_admission()
    assert second["allowed"] is False
    assert second["observation"]["instance_bytes"] > first["observation"]["instance_bytes"]
    assert (
        second["observation"]["projected_instance_bytes"] == second["observation"]["instance_bytes"]
    )


@pytest.mark.parametrize(
    "problem", ["unconfigured", "corrupt", "oversized", "unreadable", "overflow"]
)
def test_unknown_or_unreadable_capacity_never_authorizes(manager, monkeypatch, problem):
    configure(manager, "pause_on_critical")
    if problem != "unconfigured":
        limits(manager, maximum_instance_bytes_critical=2**63 - 1)
    path = manager.resources.settings_path
    if problem == "corrupt":
        path.write_bytes(b"null")
    elif problem == "oversized":
        with path.open("wb") as stream:
            stream.truncate(module.MAX_POLICY_BYTES + 1)
    elif problem == "unreadable":

        def fail():
            raise PermissionError("synthetic capacity denial")

        monkeypatch.setattr(manager.resources, "_capacity", fail)
    elif problem == "overflow":
        monkeypatch.setattr(manager.resources, "_scan", lambda: ({}, 1, 2**63 - 1))
    decision = manager.check_admission(required_bytes=1, record_wait=True)
    assert decision["allowed"] is False and decision["reason"] == "capacity_unavailable"
    assert manager.status()["last_wait"]["reason"] == "capacity_unavailable"


def test_threshold_drift_and_policy_drift_fail_closed(manager, monkeypatch):
    limits(manager, minimum_free_bytes_critical=1)
    configure(manager, "pause_on_critical")
    capacity(manager, monkeypatch, free=100)
    original = manager._thresholds
    calls = 0

    def drift():
        nonlocal calls
        calls += 1
        if calls == 2:
            limits(manager, minimum_free_bytes_critical=2)
        return original()

    monkeypatch.setattr(manager, "_thresholds", drift)
    assert manager.check_admission()["allowed"] is False
    monkeypatch.setattr(manager, "_thresholds", original)
    original_decision = manager._decision

    def policy_drift(policy, required_bytes):
        result = original_decision(policy, required_bytes)
        configure(manager, "paused", 1, "policy-request-0002")
        return result

    monkeypatch.setattr(manager, "_decision", policy_drift)
    with pytest.raises(CapacityAdmissionError, match="capacity_policy_changed"):
        manager.check_admission()


def test_receipt_bound_and_monotonic_timestamp_are_enforced(manager, monkeypatch):
    monkeypatch.setattr(module, "MAX_POLICY_RECEIPTS", 2)
    configure(manager, "paused")
    configure(manager, "observe_only", 1, "policy-request-0002")
    with pytest.raises(CapacityAdmissionError, match="capacity_policy_full"):
        configure(manager, "paused", 2, "policy-request-0003")
    value = read(manager)
    value["receipts"][1]["at"] = (
        datetime.fromisoformat(value["receipts"][0]["at"]) - timedelta(seconds=1)
    ).isoformat()
    write(manager, value)
    with pytest.raises(CapacityAdmissionError):
        manager.status()


@pytest.mark.parametrize("value", [True, -1, 2**63, "1"])
def test_required_bytes_strict_bounds(manager, value):
    with pytest.raises(CapacityAdmissionError, match="invalid_required_bytes"):
        manager.check_admission(required_bytes=value)
    assert not manager.path.exists()


def test_policy_size_and_duplicate_json_fields_are_rejected(manager):
    configure(manager, "paused")
    raw = manager.path.read_text()
    manager.path.write_text(
        raw.replace('"mode": "paused"', '"mode": "paused", "mode": "observe_only"', 1)
    )
    with pytest.raises(CapacityAdmissionError):
        manager.status()
    with manager.path.open("wb") as stream:
        stream.truncate(module.MAX_POLICY_BYTES + 1)
    with pytest.raises(CapacityAdmissionError):
        manager.status()


def test_record_wait_never_deletes_or_changes_instance_data(manager):
    configure(manager, "paused")
    marker = manager.store.paths.root / "originals" / "synthetic-marker"
    marker.parent.mkdir(exist_ok=True)
    marker.write_bytes(b"retained synthetic Original marker")
    before = files(manager.store.paths.root)
    decision = manager.check_admission(required_bytes=1, record_wait=True)
    assert decision["allowed"] is False
    assert decision["automatic_deletion"] is False and decision["running_jobs_stopped"] is False
    assert files(manager.store.paths.root) == before


def test_unsafe_host_control_is_rejected_before_lock_metadata(manager, monkeypatch):
    from types import SimpleNamespace

    original = Path.lstat
    control = manager.lifecycle.control_root

    def unsafe(path, *args, **kwargs):
        if path == control:
            return SimpleNamespace(st_mode=0o40700, st_file_attributes=1024)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", unsafe)
    monkeypatch.setattr(
        manager.lifecycle, "_hold", lambda **_: pytest.fail("unsafe lock path reached")
    )
    with pytest.raises(CapacityAdmissionError):
        configure(manager, "paused")
    with pytest.raises(CapacityAdmissionError):
        manager.check_admission(record_wait=True)
    assert not manager.path.exists()


def test_clock_reversal_cannot_replace_a_later_wait(manager):
    configure(manager, "paused")
    manager.check_admission(record_wait=True)
    value = read(manager)
    value["last_wait"]["observed_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    write(manager, value)
    before = manager.path.read_bytes()
    with pytest.raises(CapacityAdmissionError, match="capacity_clock_reversed"):
        manager.check_admission(record_wait=True)
    with pytest.raises(CapacityAdmissionError, match="capacity_clock_reversed"):
        configure(manager, "observe_only", 1, "policy-request-0002")
    assert manager.path.read_bytes() == before
