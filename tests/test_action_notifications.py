from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from provelume import shell_settings
from provelume.notification_preferences import NotificationPreferences, NotificationPreferencesError
from provelume.notifications import (
    NotificationError,
    NotificationJournalError,
    NotificationService,
    NotificationStale,
)
from provelume.shell_settings import (
    LauncherSettings,
    ShellPreferencesError,
    ShellSettingsError,
    ShellSettingsManager,
    ShellSettingsStale,
)

INSTANCE_ID = "inst_" + "a" * 32
NOW = "2026-09-13T12:00:00+00:00"


@pytest.fixture
def context(tmp_path: Path):
    root = tmp_path / "synthetic-instance"
    root.mkdir()
    (root / "instance-manifest.json").write_text(json.dumps({"instance": {"id": INSTANCE_ID}}))
    (root / "original.bin").write_bytes(b"original evidence\x00")
    manager = ShellSettingsManager(tmp_path / "local/launcher.json", LauncherSettings(str(root)))
    return root, manager, NotificationService(root, INSTANCE_ID)


def snapshot(*, revision="1" * 64, second=False, complete=True):
    items = [
        {
            "id": "aci_11111111111111111111111111111111",
            "instance_id": INSTANCE_ID,
            "queue": "intake",
            "revision": revision,
            "review_state": "awaiting_review",
            "title": "Sensitive title",
            "content": "Private content",
            "href": "https://untrusted.example/private",
        }
    ]
    if second:
        items.append(
            {**items[0], "id": "aci_22222222222222222222222222222222", "queue": "retention"}
        )
    return {
        "instance_id": INSTANCE_ID,
        "items": items,
        "revision": "e" * 64,
        "total": 300 if complete else None,
        "observed_count": 300,
        "complete": complete,
        "count_relation": "exact" if complete else "at_least",
        "limit": 100,
        "offset": 0,
    }


def ack(service, manager, value, *, now=NOW):
    view = service.preview(value, manager.load(), now=now)
    return service.acknowledge(
        value,
        manager.load(),
        batch_id=view["batch_id"],
        expected_revision=view["journal_revision"],
        expected_settings_revision=view["settings_revision"],
        now=now,
    )


def test_default_preferences_are_independent_minimized_and_closed():
    preferences = NotificationPreferences()
    payload = preferences.as_payload()
    assert payload["channels"] == {
        "in_app": True,
        "host_desktop": False,
        "browser": False,
        "pwa": False,
    }
    assert payload["preview"] == "counts_only"
    assert NotificationPreferences.from_payload(payload) == preferences
    outward = replace(preferences, host_desktop=True, browser=True, pwa=True)
    states = outward.channel_states()
    assert states["in_app"]["enabled"] is True
    for channel in ("host_desktop", "browser", "pwa"):
        assert states[channel]["requested"] is True
        assert states[channel]["enabled"] is False
        assert states[channel]["supported"] is False
        assert states[channel]["state"] == "integration_pending"
        assert states[channel]["permission"] == "unknown"


@pytest.mark.parametrize(
    "change",
    [
        {"in_app": "true"},
        {"browser": 1},
        {"quiet_enabled": "false"},
        {"aggregation_seconds": True},
        {"aggregation_seconds": 0},
        {"aggregation_seconds": 3601},
        {"quiet_start": "25:00"},
        {"quiet_end": "8:00"},
        {"quiet_start": "08:00"},
        {"timezone": "invalid/timezone"},
        {"timezone": "../UTC"},
    ],
)
def test_invalid_preferences_rejected(change):
    with pytest.raises(NotificationPreferencesError):
        replace(NotificationPreferences(), **change).normalized()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("preview", "titles"),
        ("provider", "telegram"),
        ("channels", {"in_app": True}),
    ],
)
def test_unknown_or_incomplete_wire_contract_rejected(field, value):
    payload = NotificationPreferences().as_payload()
    payload[field] = value
    with pytest.raises(NotificationPreferencesError):
        NotificationPreferences.from_payload(payload)


def test_notification_save_alone_promotes_and_preserves_renderer_and_receipts(context):
    root, manager, _service = context
    manager.save(manager.load().settings)
    legacy_bytes = manager.path.read_bytes()
    assert manager.load().settings.schema_version == 2
    assert manager.path.read_bytes() == legacy_bytes
    ordinary = manager.set_preferences(theme="dark", language="it", expected_revision=0)
    assert ordinary.schema_version == 2
    selected = manager.set_interface_mode("preview", expected_revision=1)
    assert selected.schema_version == 3
    interface_receipt = selected.interface_mode_change
    selected = manager.configure_notifications(
        NotificationPreferences(quiet_enabled=True), expected_revision=2
    )
    assert selected.schema_version == 4 and selected.revision == 3
    assert (
        selected.instance_path == str(root)
        and selected.theme == "dark"
        and selected.language == "it"
    )
    assert (
        selected.interface_mode == "preview" and selected.interface_mode_change == interface_receipt
    )
    assert selected.notifications_change["changed"] is True
    assert selected.notifications_change["revision"] == 3
    assert selected.notifications_change["sha256"] == selected.notifications.digest()
    restored = ShellSettingsManager(manager.path, manager.defaults).load()
    assert restored.warning is None and restored.settings == selected
    # Desktop's asdict/constructor path and presentation rollback retain all new fields.
    assert LauncherSettings(**asdict(selected)).normalized() == selected
    rolled_back = manager.set_interface_mode("current", expected_revision=3)
    assert rolled_back.schema_version == 4
    assert rolled_back.notifications == selected.notifications
    assert rolled_back.notifications_change == selected.notifications_change
    ordinary = manager.set_preferences(theme="light", expected_revision=4)
    assert ordinary.schema_version == 4 and ordinary.notifications == selected.notifications
    with pytest.raises(ShellSettingsError, match="downgraded"):
        manager.save(LauncherSettings(str(root), schema_version=3))


def test_explicit_default_notification_save_promotes_with_non_content_receipt(context):
    _root, manager, _service = context
    selected = manager.configure_notifications(
        NotificationPreferences().as_payload(), expected_revision=0
    )
    assert selected.schema_version == 4
    assert selected.notifications_change["changed"] is False
    assert set(selected.notifications_change) == {
        "schema_version",
        "revision",
        "recorded_at_utc",
        "source",
        "previous_sha256",
        "sha256",
        "changed",
    }
    assert "notifications" in json.loads(manager.path.read_bytes())["shell"]


def test_stale_notification_preferences_do_not_mutate(context):
    _root, manager, _service = context
    manager.configure_notifications(NotificationPreferences(in_app=False), expected_revision=0)
    before = manager.path.read_bytes()
    with pytest.raises(ShellSettingsStale):
        manager.configure_notifications(NotificationPreferences(), expected_revision=0)
    assert manager.path.read_bytes() == before


def test_legacy_preference_import_preserves_schema_four_fields(context, monkeypatch, tmp_path):
    _root, manager, _service = context
    monkeypatch.setattr(shell_settings, "probe_port", lambda port: {"available": True})
    manager.set_interface_mode("preview", expected_revision=0)
    selected = manager.configure_notifications(
        NotificationPreferences(in_app=False), expected_revision=1
    )
    exported = tmp_path / "preferences.json"
    manager.export_preferences(exported)
    transfer = json.loads(exported.read_bytes())
    assert transfer["schema_version"] == 1 and "notifications" not in transfer
    transfer["theme"] = "dark"
    exported.write_text(json.dumps(transfer))
    loaded = manager.import_preferences(exported, expected_revision=2)
    assert loaded.schema_version == 4 and loaded.interface_mode == "preview"
    assert loaded.notifications == selected.notifications
    assert loaded.notifications_change == selected.notifications_change
    assert loaded.interface_mode_change == selected.interface_mode_change


def test_failed_atomic_notification_save_restores_exact_prior_bytes(context, monkeypatch):
    _root, manager, _service = context
    manager.set_interface_mode("preview", expected_revision=0)
    before = manager.path.read_bytes()

    def fail_replace(*args):
        raise PermissionError("synthetic replace failure")

    monkeypatch.setattr(shell_settings.os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        manager.configure_notifications(NotificationPreferences(), expected_revision=1)
    assert manager.path.read_bytes() == before
    assert list(manager.path.parent.glob(".launcher.json.*.tmp")) == []


def test_invalid_persisted_notification_settings_fail_closed_without_repair(context):
    _root, manager, service = context
    manager.configure_notifications(NotificationPreferences(), expected_revision=0)
    value = json.loads(manager.path.read_bytes())
    value["shell"]["notifications"]["preview"] = "all_content"
    manager.path.write_text(json.dumps(value))
    before = manager.path.read_bytes()
    loaded = manager.load()
    assert loaded.warning == "settings_invalid_using_safe_defaults"
    view = service.preview(snapshot(), loaded, now=NOW)
    assert view["state"] == "unavailable"
    assert not any(channel["enabled"] for channel in view["channels"].values())
    with pytest.raises(ShellPreferencesError):
        manager.configure_notifications(NotificationPreferences(), expected_revision=0)
    assert manager.path.read_bytes() == before and not service.path.exists()


def test_preview_is_pure_minimized_and_uses_exact_authoritative_item_urls(context):
    root, manager, service = context
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    value = snapshot(second=True)
    original = copy.deepcopy(value)
    first = service.preview(value, manager.load(), now=NOW)
    second = service.preview(value, manager.load(), now=NOW)
    assert first == second and value == original
    assert first["state"] == "ready" and first["count"] == 2 and first["queue_count"] == 300
    assert first["message_args"] == {"count": 2}
    assert first["journal_revision"] == 0
    assert not service.path.parent.exists() and not manager.path.exists()
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    encoded = json.dumps(first)
    assert "Sensitive title" not in encoded and "Private content" not in encoded
    assert "untrusted.example" not in encoded
    assert first["items"][0]["href"] == (
        "/attention/items/aci_11111111111111111111111111111111?"
        f"instance_id={INSTANCE_ID}&revision={'1' * 64}"
    )


def test_ack_is_durable_idempotent_and_never_a_review_decision(context):
    root, manager, service = context
    value = snapshot(second=True)
    original = copy.deepcopy(value)
    first = service.preview(value, manager.load(), now=NOW)
    result = ack(service, manager, value)
    before = service.path.read_bytes()
    duplicate = service.acknowledge(
        value,
        manager.load(),
        batch_id=first["batch_id"],
        expected_revision=0,
        expected_settings_revision=0,
        now=NOW,
    )
    assert result["receipt"] == duplicate["receipt"] and duplicate["replayed"] is True
    assert service.path.read_bytes() == before
    restarted = NotificationService(root, INSTANCE_ID)
    assert restarted.preview(value, manager.load(), now=NOW)["state"] == "empty"
    assert value == original and (root / "original.bin").read_bytes() == b"original evidence\x00"
    assert b"Sensitive title" not in before and b"Private content" not in before
    assert b"aci_11111111111111111111111111111111" not in before and b"review_state" not in before


def test_new_item_revision_is_not_hidden_by_old_acknowledgement(context):
    _root, manager, service = context
    ack(service, manager, snapshot())
    value = snapshot(revision="2" * 64)
    early = service.preview(value, manager.load(), now="2026-09-13T12:00:10+00:00")
    assert early["state"] == "aggregating"
    assert early["next_eligible_at"] == "2026-09-13T12:01:00+00:00"
    later = service.preview(value, manager.load(), now="2026-09-13T12:01:00+00:00")
    assert later["state"] == "ready" and later["count"] == 1


def test_stale_input_and_preference_revisions_do_not_acknowledge_new_items(context):
    _root, manager, service = context
    first = service.preview(snapshot(), manager.load(), now=NOW)
    with pytest.raises(NotificationStale):
        service.acknowledge(
            snapshot(revision="2" * 64),
            manager.load(),
            batch_id=first["batch_id"],
            expected_revision=0,
            expected_settings_revision=0,
            now=NOW,
        )
    assert not service.path.exists()
    manager.configure_notifications(NotificationPreferences(in_app=False), expected_revision=0)
    with pytest.raises(NotificationStale):
        service.acknowledge(
            snapshot(),
            manager.load(),
            batch_id=first["batch_id"],
            expected_revision=0,
            expected_settings_revision=0,
            now=NOW,
        )
    assert not service.path.exists()


@pytest.mark.parametrize("wrong", ["snapshot_instance", "item_instance", "bad_id", "bad_revision"])
def test_cross_instance_and_malformed_item_references_fail_before_journal_write(context, wrong):
    _root, manager, service = context
    value = snapshot()
    if wrong == "snapshot_instance":
        value["instance_id"] = "inst_" + "b" * 32
    elif wrong == "item_instance":
        value["items"][0]["instance_id"] = "inst_" + "b" * 32
    elif wrong == "bad_id":
        value["items"][0]["id"] = "../../other"
    else:
        value["items"][0]["revision"] = "newest"
    with pytest.raises(NotificationError):
        service.preview(value, manager.load(), now=NOW)
    assert not service.path.parent.exists()


def test_other_instance_journal_is_never_reused(context):
    root, manager, service = context
    ack(service, manager, snapshot())
    before = service.path.read_bytes()
    other = NotificationService(root, "inst_" + "b" * 32)
    with pytest.raises(NotificationError):
        other.preview(snapshot(), manager.load(), now=NOW)
    assert service.path.read_bytes() == before


def test_incomplete_snapshot_count_is_not_presented_as_total(context):
    _root, manager, service = context
    view = service.preview(snapshot(complete=False), manager.load(), now=NOW)
    assert view["count"] == 1 and view["queue_count"] is None
    assert view["count_relation"] == "at_least" and view["snapshot_complete"] is False


@pytest.mark.parametrize("status", ["unavailable", "partial"])
def test_unobserved_incomplete_snapshot_is_unavailable_not_empty(context, status):
    _root, manager, service = context
    value = snapshot(complete=False)
    value.update(items=[], status=status, observed_count=0, count_relation="unknown")
    view = service.preview(value, manager.load(), now=NOW)
    assert view["state"] == "unavailable" and view["error_code"] == "snapshot_unavailable"
    assert view["queue_count"] is None and view["count_relation"] == "unknown"
    assert not service.path.parent.exists()


def test_later_page_remains_notifiable_after_first_page_acknowledgement(context):
    _root, manager, service = context
    first = snapshot()
    first_view = service.preview(first, manager.load(), now=NOW)
    ack(service, manager, first)
    assert service.preview(first, manager.load(), now=NOW)["state"] == "empty"
    later = snapshot(second=True)
    later.update(items=later["items"][1:], offset=100)
    later_view = service.preview(later, manager.load(), now="2026-09-13T12:01:00Z")
    assert later_view["state"] == "ready" and later_view["count"] == 1
    assert later_view["queue_count"] == 300 and later_view["count_relation"] == "exact"
    assert later_view["batch_id"] != first_view["batch_id"]
    assert later_view["items"][0]["item_id"] == "aci_" + "2" * 32
    ack(service, manager, later, now="2026-09-13T12:01:00Z")
    assert service.preview(later, manager.load(), now=NOW)["state"] == "empty"


def test_resolved_items_and_disabled_channel_do_not_generate_notifications(context):
    _root, manager, service = context
    value = snapshot()
    value["items"][0]["review_state"] = "superseded"
    assert service.preview(value, manager.load(), now=NOW)["state"] == "empty"
    manager.configure_notifications(NotificationPreferences(in_app=False), expected_revision=0)
    assert service.preview(snapshot(), manager.load(), now=NOW)["state"] == "disabled"
    assert not service.path.exists()


@pytest.mark.parametrize(
    "now,expected",
    [
        ("2026-09-13T21:00:00+00:00", "2026-09-14T06:00:00+00:00"),
        ("2026-09-14T05:59:00+00:00", "2026-09-14T06:00:00+00:00"),
        ("2026-09-14T06:00:00+00:00", "2026-09-14T06:00:00+00:00"),
    ],
)
def test_quiet_hours_cross_midnight_with_explicit_zone(now, expected):
    preferences = NotificationPreferences(quiet_enabled=True, timezone="Europe/Rome")
    assert preferences.next_eligible_at(now).isoformat() == expected


def test_quiet_hours_cover_dst_fold_and_shift_gap_to_first_valid_instant():
    preferences = NotificationPreferences(
        quiet_enabled=True, quiet_end="02:30", timezone="Europe/Rome"
    )
    assert (
        preferences.next_eligible_at("2026-10-25T00:45:00Z").isoformat()
        == "2026-10-25T01:30:00+00:00"
    )
    assert (
        preferences.next_eligible_at("2026-03-29T00:50:00Z").isoformat()
        == "2026-03-29T01:00:00+00:00"
    )


def test_quiet_hours_defer_ack_without_hiding_or_mutating_queue(context):
    _root, manager, service = context
    manager.configure_notifications(
        NotificationPreferences(quiet_enabled=True), expected_revision=0
    )
    value = snapshot(second=True)
    view = service.preview(value, manager.load(), now="2026-09-13T23:00:00Z")
    assert view["state"] == "deferred_quiet" and view["count"] == 2
    with pytest.raises(NotificationStale):
        service.acknowledge(
            value,
            manager.load(),
            batch_id=view["batch_id"],
            expected_revision=0,
            expected_settings_revision=1,
            now="2026-09-13T23:00:00Z",
        )
    assert not service.path.exists() and value["items"][0]["review_state"] == "awaiting_review"


def test_clock_reversal_is_explicit_and_does_not_resend(context):
    _root, manager, service = context
    ack(service, manager, snapshot())
    view = service.preview(snapshot(revision="2" * 64), manager.load(), now="2026-09-13T11:00:00Z")
    assert view["state"] == "clock_reversed"
    assert view["next_eligible_at"] == "2026-09-13T12:01:00+00:00"


def test_corrupt_journal_is_not_silently_reset(context):
    _root, manager, service = context
    first = service.preview(snapshot(), manager.load(), now=NOW)
    service.path.parent.mkdir(parents=True)
    service.path.write_text('{"broken":true}')
    before = service.path.read_bytes()
    assert service.preview(snapshot(), manager.load(), now=NOW)["state"] == "unavailable"
    with pytest.raises(NotificationJournalError):
        service.acknowledge(
            snapshot(),
            manager.load(),
            batch_id=first["batch_id"],
            expected_revision=0,
            expected_settings_revision=0,
            now=NOW,
        )
    assert service.path.read_bytes() == before


@pytest.mark.parametrize("confirmation", [False, 1, "true", None])
def test_notification_reset_requires_explicit_redelivery_confirmation(context, confirmation):
    _root, manager, service = context
    ack(service, manager, snapshot())
    before = service.path.read_bytes()
    with pytest.raises(NotificationError):
        service.reset_acknowledgements(
            manager.load(),
            expected_revision=1,
            expected_settings_revision=0,
            confirm_redelivery=confirmation,
            now=NOW,
        )
    assert service.path.read_bytes() == before


def test_notification_reset_is_metadata_only_durable_and_replay_safe(context):
    root, manager, service = context
    value = snapshot()
    ack(service, manager, value)
    before = json.loads(service.path.read_bytes())
    reset = service.reset_acknowledgements(
        manager.load(),
        expected_revision=1,
        expected_settings_revision=0,
        confirm_redelivery=True,
        now=NOW,
    )
    assert reset["receipt"]["previous_acknowledged_count"] == 1
    assert reset["receipt"]["previous_receipt_count"] == 1
    assert reset["receipt"]["redelivery_confirmed"] is True
    assert reset["receipt"]["previous_revision"] == before["revision"]
    assert len(reset["receipt"]["previous_sha256"]) == 64
    encoded = service.path.read_bytes()
    repeated = service.reset_acknowledgements(
        manager.load(),
        expected_revision=1,
        expected_settings_revision=0,
        confirm_redelivery=True,
        now=NOW,
    )
    assert repeated["replayed"] is True and repeated["receipt"] == reset["receipt"]
    assert service.path.read_bytes() == encoded
    restored = NotificationService(root, INSTANCE_ID)
    view = restored.preview(value, manager.load(), now=NOW)
    assert view["state"] == "ready" and view["last_reset"] == reset["receipt"]
    ack(restored, manager, value)
    assert restored.preview(value, manager.load(), now=NOW)["state"] == "empty"
    assert restored.preview(value, manager.load(), now=NOW)["last_reset"] == reset["receipt"]
    assert (root / "original.bin").read_bytes() == b"original evidence\x00"
    assert value["items"][0]["review_state"] == "awaiting_review"
    assert b"Sensitive title" not in encoded
    assert b"aci_11111111111111111111111111111111" not in encoded


@pytest.mark.parametrize("target_kind", ["journal", "lock", "parent"])
def test_dangling_notification_links_cannot_create_external_metadata(context, target_kind):
    root, manager, service = context
    first = service.preview(snapshot(), manager.load(), now=NOW)
    outside = root.parent / "uncreated-external-metadata"
    if target_kind == "parent":
        (root / "state").mkdir()
        link = service.path.parent
    else:
        service.path.parent.mkdir(parents=True)
        link = service.path if target_kind == "journal" else service.path.with_suffix(".json.lock")
    try:
        link.symlink_to(outside, target_is_directory=target_kind == "parent")
    except OSError as exc:
        pytest.skip(f"platform does not permit creating test symlinks: {exc}")
    with pytest.raises(ShellPreferencesError):
        service.acknowledge(
            snapshot(),
            manager.load(),
            batch_id=first["batch_id"],
            expected_revision=0,
            expected_settings_revision=0,
            now=NOW,
        )
    assert not outside.exists() and link.is_symlink()
    if target_kind != "lock":
        assert service.preview(snapshot(), manager.load(), now=NOW)["state"] == "unavailable"


def test_reset_is_available_at_history_capacity_without_silent_pruning(context):
    root, manager, service = context
    ack(service, manager, snapshot())
    journal = json.loads(service.path.read_bytes())
    # Fill the real on-disk bounded metadata with distinct synthetic digests.
    journal["acknowledged"] = [f"{number:064x}" for number in range(512)]
    service.path.write_text(json.dumps(journal))
    before = service.path.read_bytes()
    view = service.preview(snapshot(revision="3" * 64), manager.load(), now=NOW)
    assert view["state"] == "unavailable" and view["error_code"] == "notification_journal_full"
    assert service.path.read_bytes() == before
    reset = service.reset_acknowledgements(
        manager.load(),
        expected_revision=1,
        expected_settings_revision=0,
        confirm_redelivery=True,
        now=NOW,
    )
    assert reset["receipt"]["previous_acknowledged_count"] == 512
    restored = NotificationService(root, INSTANCE_ID)
    assert (
        restored.preview(snapshot(revision="3" * 64), manager.load(), now=NOW)["state"] == "ready"
    )
    assert len(service.path.read_bytes()) < 64 * 1024
    assert json.loads(service.path.read_bytes())["last_reset"] == reset["receipt"]


def test_reset_checks_both_revisions_before_any_change(context):
    _root, manager, service = context
    ack(service, manager, snapshot())
    before = service.path.read_bytes()
    with pytest.raises(NotificationStale):
        service.reset_acknowledgements(
            manager.load(),
            expected_revision=0,
            expected_settings_revision=0,
            confirm_redelivery=True,
            now=NOW,
        )
    with pytest.raises(NotificationStale):
        service.reset_acknowledgements(
            manager.load(),
            expected_revision=1,
            expected_settings_revision=1,
            confirm_redelivery=True,
            now=NOW,
        )
    assert service.path.read_bytes() == before
