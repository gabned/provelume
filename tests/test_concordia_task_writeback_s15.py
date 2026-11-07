"""Exact diff/authority/dispatch and read-only uncertainty recovery over native Core state."""

import re
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from provelume.knowledge_object_contract import record_digest
from provelume.productivity_contract import ProductivityError
from provelume.service import ProvelumeInstance
from provelume.task_writeback import TaskWriteBack
from provelume.task_writeback_qualification import (
    SyntheticWriteBackFixture,
    qualify_task_writeback,
)
from provelume.web import create_app


@pytest.fixture
def fixture(tmp_path):
    value = SyntheticWriteBackFixture(ProvelumeInstance.initialise(tmp_path / "Instance"))
    value.consent()
    return value


def confirm(fixture, plan):
    return fixture.engine.confirm(
        fixture.object_id, plan["id"], expected_plan_sha256=plan["sha256"], confirmed=True
    )


@pytest.mark.parametrize(
    "requested",
    [
        {"completed": True},
        {"due": None},
        {"due": {"kind": "date", "value": "2026-11-08", "time_zone": None}},
        {
            "completed": True,
            "due": {"kind": "instant", "value": "2026-11-08T12:00:00+00:00", "time_zone": "UTC"},
        },
    ],
)
def test_closed_fields_diff_confirm_replay_and_separate_source_read(fixture, requested):
    plan = fixture.prepare(requested)
    assert plan["changes"] == requested and set(plan["before"]) == set(requested)
    original = deepcopy(fixture.store.read_canonical("objects", fixture.object_id))
    receipt = confirm(fixture, plan)
    assert receipt["status"] == "APPLIED" and not receipt["canonical_updated"]
    assert confirm(fixture, plan) == receipt and fixture.remote.cas_calls == 1
    assert fixture.store.read_canonical("objects", fixture.object_id) == original
    fixture.acquire()
    obj = fixture.store.read_canonical("objects", fixture.object_id)
    assert obj["state"] == ("completed" if fixture.remote.value["completed"] else "open")
    assert obj["body"]["due_date"] == (
        fixture.remote.value["due"]["value"]
        if fixture.remote.value["due"] and fixture.remote.value["due"]["kind"] == "date"
        else None
    )
    assert not any(key in receipt for key in ("before", "changes", "remote_id", "token", "due"))


@pytest.mark.parametrize(
    "requested",
    [
        {"title": "disallowed"},
        {"description": "disallowed"},
        {"assignee": "disallowed"},
        {"delete": True},
        {"create": True},
        {"completed": 1},
        {},
    ],
)
def test_no_unapproved_field_or_implicit_operation_can_reach_provider(fixture, requested):
    before = fixture.remote.cas_calls
    with pytest.raises(ProductivityError):
        fixture.prepare(requested)
    assert fixture.remote.cas_calls == before


def test_no_change_and_missing_confirmation_never_dispatch(fixture):
    with pytest.raises(ProductivityError, match="no_change"):
        fixture.prepare({"completed": False})
    plan = fixture.prepare({"completed": True})
    with pytest.raises(ProductivityError, match="consent_required"):
        fixture.engine.confirm(
            fixture.object_id, plan["id"], expected_plan_sha256=plan["sha256"], confirmed=False
        )
    assert fixture.remote.cas_calls == 0


def test_newer_remote_state_is_preserved_by_actual_atomic_condition(fixture):
    plan = fixture.prepare({"due": {"kind": "date", "value": "2026-11-08", "time_zone": None}})
    newer = {"kind": "date", "value": "2026-11-09", "time_zone": None}
    fixture.remote.actor_update(due=newer)
    receipt = confirm(fixture, plan)
    assert receipt["status"] == "CONFLICT" and fixture.remote.value["due"] == newer
    assert confirm(fixture, plan) == receipt and fixture.remote.cas_calls == 1


def test_local_or_consent_revision_change_invalidates_the_displayed_diff(fixture):
    plan = fixture.prepare({"completed": True})
    fixture.title = "Changed local observation"
    fixture.acquire()
    with pytest.raises(ProductivityError, match="stale"):
        confirm(fixture, plan)
    assert fixture.remote.cas_calls == 0
    plan = fixture.prepare({"completed": True})
    fixture.engine.consent(
        fixture.source, enabled=False, fields=[], expected_revision=1, confirmed=True
    )
    with pytest.raises(ProductivityError, match="stale"):
        confirm(fixture, plan)
    assert fixture.remote.cas_calls == 0


def test_revoked_source_before_dispatch_prevents_every_write(fixture):
    plan = fixture.prepare({"completed": True})
    fixture.instance.connectors.disable_source(fixture.identity, fixture.source)
    with pytest.raises(ProductivityError):
        confirm(fixture, plan)
    assert fixture.remote.cas_calls == 0


@pytest.mark.parametrize(
    "mode,outcome", [("after_send_timeout", "APPLIED"), ("not_applied", "NOT_APPLIED")]
)
def test_timeout_recovery_uses_operation_receipt_without_resubmission(fixture, mode, outcome):
    plan = fixture.prepare({"completed": True})
    fixture.remote.mode = mode
    assert confirm(fixture, plan)["status"] == "UNKNOWN"
    assert confirm(fixture, plan)["status"] == "UNKNOWN" and fixture.remote.cas_calls == 1
    receipt = fixture.engine.reconcile(fixture.object_id)
    assert receipt["status"] == outcome and fixture.remote.cas_calls == 1
    assert fixture.remote.operation_calls == 1


def test_matching_current_fields_without_operation_proof_stays_unknown(fixture):
    plan = fixture.prepare({"completed": True})
    fixture.remote.mode = "unknown"
    assert confirm(fixture, plan)["status"] == "UNKNOWN"
    fixture.remote.actor_update(completed=True)  # An unrelated actor coincidentally matches.
    assert fixture.engine.reconcile(fixture.object_id)["status"] == "UNKNOWN"
    with pytest.raises(ProductivityError, match="unknown_outcome"):
        fixture.prepare({"due": None})
    assert fixture.remote.cas_calls == 1


def test_process_interruption_after_durable_dispatch_never_replays(fixture):
    plan = fixture.prepare({"completed": True})
    fixture.remote.mode = "crash"
    with pytest.raises(KeyboardInterrupt):
        confirm(fixture, plan)
    fixture.engine = TaskWriteBack(fixture.store, _qualification_adapter=fixture.remote)
    assert confirm(fixture, plan)["status"] == "UNKNOWN"
    assert fixture.engine.reconcile(fixture.object_id)["status"] == "UNKNOWN"
    assert fixture.remote.cas_calls == 1


def test_revoke_after_dispatch_cannot_undo_inflight_but_prevents_future_writes(fixture):
    plan = fixture.prepare({"completed": True})
    fixture.remote.on_dispatch = lambda: fixture.engine.consent(
        fixture.source, enabled=False, fields=[], expected_revision=1, confirmed=True
    )
    receipt = confirm(fixture, plan)
    assert receipt["status"] == "APPLIED"  # Dispatch was already durably authorized.
    assert fixture.engine.ledger(fixture.source)["consent"]["enabled"] is False
    with pytest.raises(ProductivityError, match="consent_required"):
        fixture.prepare({"due": None})
    assert fixture.remote.cas_calls == 1


def test_wrong_source_or_plan_hash_cannot_borrow_confirmation(fixture):
    plan = fixture.prepare({"completed": True})
    other = SyntheticWriteBackFixture(fixture.instance)
    other.consent()
    with pytest.raises(ProductivityError):
        fixture.engine.confirm(
            other.object_id, plan["id"], expected_plan_sha256=plan["sha256"], confirmed=True
        )
    with pytest.raises(ProductivityError, match="stale"):
        fixture.engine.confirm(
            fixture.object_id, plan["id"], expected_plan_sha256="0" * 64, confirmed=True
        )
    assert fixture.remote.cas_calls == 0


def test_portable_restore_does_not_reuse_write_consent_on_another_device_root(fixture, tmp_path):
    archive = tmp_path / "Portable.zip"
    fixture.instance.export_portable(archive, derived_state="rebuild")
    restored = ProvelumeInstance.initialise(tmp_path / "Restored")
    restored.import_portable(archive)
    engine = TaskWriteBack(restored.store, _qualification_adapter=fixture.remote)
    assert engine.view(fixture.object_id)["consent_effective"] is False
    with pytest.raises(ProductivityError, match="consent_required"):
        engine.prepare(
            fixture.object_id,
            {"completed": True},
            expected_consent_revision=1,
            expected_local_sha256=record_digest(
                restored.store.read_canonical("objects", fixture.object_id)
            ),
        )
    assert fixture.remote.cas_calls == 0


def test_default_runtime_cannot_enable_qualification_adapter_or_public_writes(fixture):
    engine = TaskWriteBack(fixture.store)
    assert engine.view(fixture.object_id)["capability"]["available"] is False
    with pytest.raises(ProductivityError, match="conditional_write_unavailable"):
        engine.consent(
            fixture.source, enabled=True, fields=["completed"], expected_revision=1, confirmed=True
        )
    assert fixture.remote.cas_calls == 0


def test_complete_synthetic_package_qualification_never_qualifies_a_live_provider(tmp_path):
    report = qualify_task_writeback(tmp_path / "Qualification")
    assert report["result"] == "PASS" and not report["network_used"]
    assert (
        report["public_provider_writeback"] == "NOT_QUALIFIED"
        and report["release_gate"] == "BLOCKED"
    )


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
def test_real_http_diff_confirmation_and_replay_are_explicit(fixture, tmp_path, language):
    app = create_app(fixture.instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._task_writeback_manager = fixture.engine
    client = TestClient(app)
    target = "/task-writeback/" + fixture.object_id + "?lang=" + language
    before = (fixture.remote.read_calls, fixture.remote.cas_calls, fixture.remote.operation_calls)
    response = client.get(target)
    assert response.status_code == 200 and "task_write.title" not in response.text
    assert before == (
        fixture.remote.read_calls,
        fixture.remote.cas_calls,
        fixture.remote.operation_calls,
    )
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def control(action, **fields):
        return client.post(
            target, data={"csrf_token": csrf, "confirm": "yes", "action": action, **fields}
        )

    assert client.post(target, data={"csrf_token": "wrong"}).status_code == 403
    response = control(
        "prepare",
        local_sha256=fixture.engine.view(fixture.object_id)["local_sha256"],
        revision="1",
        completed="yes",
        due_kind="date",
        day="2026-11-08",
        clock="",
        zone="UTC",
    )
    assert response.status_code == 200 and 'id="task-write-diff"' in response.text
    assert "2026-11-07" in response.text and "2026-11-08" in response.text
    assert fixture.remote.cas_calls == 0 and fixture.remote.read_calls == 1
    assert "task_write.before" not in response.text
    plan = re.search(r'name="plan_id" value="([^"]+)"', response.text).group(1)
    digest = re.search(r'name="plan_sha256" value="([^"]+)"', response.text).group(1)
    before = fixture.remote.read_calls
    assert client.get(str(response.url)).status_code == 200 and fixture.remote.read_calls == before
    response = control("confirm", plan_id=plan, plan_sha256=digest)
    assert 'id="task-write-receipt"' in response.text and fixture.remote.cas_calls == 1
    response = control("confirm", plan_id=plan, plan_sha256=digest)
    assert 'id="task-write-receipt"' in response.text and fixture.remote.cas_calls == 1
    response = control(
        "prepare",
        local_sha256="0" * 64,
        revision="1",
        completed="yes",
        due_kind="unchanged",
        title="unapproved",
    )
    assert "notice=error" in str(response.url) and fixture.remote.cas_calls == 1


def test_unknown_view_is_passive_and_reconciliation_only_reads(fixture, tmp_path):
    app = create_app(fixture.instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._task_writeback_manager = fixture.engine
    client = TestClient(app)
    target = "/task-writeback/" + fixture.object_id
    response = client.get(target)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    plan = fixture.prepare({"completed": True})
    fixture.remote.mode = "after_send_timeout"
    response = client.post(
        target,
        data={
            "csrf_token": csrf,
            "confirm": "yes",
            "action": "confirm",
            "plan_id": plan["id"],
            "plan_sha256": plan["sha256"],
        },
    )
    assert "notice=UNKNOWN" in str(response.url)
    assert fixture.remote.operation_calls == 0 and fixture.remote.cas_calls == 1
    assert client.get(target).status_code == 200 and fixture.remote.operation_calls == 0
    response = client.post(
        target, data={"csrf_token": csrf, "confirm": "yes", "action": "reconcile"}
    )
    assert "notice=APPLIED" in str(response.url)
    assert fixture.remote.operation_calls == 1 and fixture.remote.cas_calls == 1


@pytest.mark.parametrize("provider", ["asana", "tududi"])
def test_public_provider_cannot_obtain_write_authority_from_synthetic_success(tmp_path, provider):
    instance = ProvelumeInstance.initialise(tmp_path / "Instance")
    if provider == "asana":
        from provelume.asana_qualification import seed_asana

        manager, remote, source = seed_asana(instance)
        calls = remote.calls
    else:
        from provelume.tududi_qualification import seed_tududi

        manager, remote, source = seed_tududi(instance)
        calls = len(remote.calls)
    engine = TaskWriteBack(instance.store)
    assert not engine.capability(source)["available"]
    with pytest.raises(ProductivityError, match="conditional_write_unavailable"):
        engine.consent(
            source, enabled=True, fields=["completed", "due"], expected_revision=0, confirmed=True
        )
    assert (remote.calls if provider == "asana" else len(remote.calls)) == calls
    assert manager.view()["sources"]


def test_receipt_persisted_before_interrupted_local_finalization_prevents_resend(
    fixture, monkeypatch
):
    plan = fixture.prepare({"completed": True})
    save = fixture.engine.save_ledger

    def fail_finalization(value):
        if value["inflight"] is None:
            raise OSError("synthetic interruption after durable remote receipt")
        save(value)

    monkeypatch.setattr(fixture.engine, "save_ledger", fail_finalization)
    with pytest.raises(OSError):
        confirm(fixture, plan)
    fixture.engine = TaskWriteBack(fixture.store, _qualification_adapter=fixture.remote)
    assert confirm(fixture, plan)["status"] == "APPLIED"
    assert fixture.engine.ledger(fixture.source)["inflight"] is None
    assert fixture.remote.cas_calls == 1


def test_late_old_recovery_cannot_clear_a_newer_unknown_operation(fixture):
    old = fixture.prepare({"completed": True})
    receipt = confirm(fixture, old)
    fixture.acquire()
    newer = fixture.prepare({"due": None})
    fixture.remote.mode = "unknown"
    assert confirm(fixture, newer)["status"] == "UNKNOWN"
    assert fixture.engine.finish(old, {"outcome": "UNKNOWN"}) == receipt
    assert fixture.engine.ledger(fixture.source)["inflight"]["plan"]["id"] == newer["id"]
    assert fixture.remote.cas_calls == 2


@pytest.mark.parametrize("day", ["2026-03-29", "2026-10-25"])
def test_explicit_ambiguous_or_missing_dst_clock_is_refused_before_remote_preview(day):
    from provelume.productivity_contract import local_instant

    with pytest.raises(ProductivityError, match="time_zone"):
        local_instant(day, "02:30", "Europe/Rome")
    assert local_instant("2026-11-08", "12:30", "Europe/Rome")["value"].endswith("+01:00")
