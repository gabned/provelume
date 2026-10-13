from __future__ import annotations

import json
from dataclasses import replace

import pytest

from provelume.shell_settings import (
    ShellSettingsManager,
    default_settings,
)


@pytest.mark.parametrize("schema", [1, 2, 3, 4])
def test_inherited_previous_interface_uses_cura_without_inventing_user_choice(tmp_path, schema):
    defaults = replace(default_settings(), instance_path=str(tmp_path / "instance"))
    manager = ShellSettingsManager(tmp_path / "launcher.json", defaults)
    if schema == 4:
        manager.configure_notifications(
            defaults.notifications, expected_revision=0,
        )
        defaults = manager.load().settings
    settings = replace(defaults, interface_mode="current", schema_version=max(2, schema))
    payload = settings.as_payload()
    if schema == 1:
        payload = {"schema_version": 1, **{k: payload[k] for k in (
            "instance_path", "update_channel", "check_on_start", "language",
        )}}
    raw = json.dumps(payload).encode()
    manager.path.write_bytes(raw)
    loaded = manager.load()
    assert loaded.settings.interface_mode == "preview"
    assert loaded.settings.interface_mode_change is None
    assert loaded.settings.instance_path == settings.instance_path
    assert loaded.settings.revision == settings.revision
    assert manager.path.read_bytes() == raw  # GET/load never migrates on disk.
    assert loaded.warning == "legacy_settings_loaded_pending_migration"


def test_explicit_backup_and_return_survive_restart_and_unrelated_preferences(tmp_path):
    defaults = replace(default_settings(), instance_path=str(tmp_path / "instance"))
    manager = ShellSettingsManager(tmp_path / "launcher.json", defaults)
    assert manager.load().settings.interface_mode == "preview"
    manager.set_interface_mode("current", expected_revision=0)
    backup = manager.load().settings
    assert backup.interface_mode == "current"
    assert backup.interface_mode_change is not None
    restarted = ShellSettingsManager(manager.path, defaults)
    assert restarted.load().settings == backup
    restarted.mutate(lambda current: replace(current, theme="dark"),
                     expected_revision=backup.revision)
    changed = restarted.load().settings
    assert changed.interface_mode == "current"
    assert changed.interface_mode_change == backup.interface_mode_change
    restarted.set_interface_mode("preview", expected_revision=changed.revision)
    cura = restarted.load().settings
    assert cura.interface_mode == "preview"
    assert cura.interface_mode_change.from_mode == "current"
    assert cura.interface_mode_change.to_mode == "preview"
    assert cura.instance_path == backup.instance_path
    assert cura.theme == "dark"


def test_invalid_selection_receipt_remains_invalid_instead_of_becoming_inherited(tmp_path):
    defaults = replace(default_settings(), instance_path=str(tmp_path / "instance"))
    manager = ShellSettingsManager(tmp_path / "launcher.json", defaults)
    payload = replace(defaults, interface_mode="current").as_payload()
    payload["shell"]["interface_mode_change"] = {"to_mode": "current"}
    raw = json.dumps(payload).encode()
    manager.path.write_bytes(raw)
    assert manager.load().warning == "settings_invalid_using_safe_defaults"
    assert manager.path.read_bytes() == raw


def test_fresh_creation_uses_product_default_without_a_backup_receipt(tmp_path):
    manager = ShellSettingsManager(tmp_path / "launcher.json", default_settings())
    assert manager.load().settings.interface_mode == "preview"
    assert manager.load().settings.interface_mode_change is None
    assert not manager.path.exists()


def test_failed_side_effect_restores_legacy_bytes_and_does_not_commit_inheritance(tmp_path):
    defaults = replace(default_settings(), instance_path=str(tmp_path / "instance"))
    manager = ShellSettingsManager(tmp_path / "launcher.json", defaults)
    payload = replace(defaults, interface_mode="current", schema_version=2).as_payload()
    raw = json.dumps(payload, separators=(",", ":")).encode()
    manager.path.write_bytes(raw)

    def fail(_):
        raise RuntimeError("synthetic rejected preference side effect")

    with pytest.raises(RuntimeError):
        manager.mutate(lambda current: replace(current, theme="dark"),
                       expected_revision=0, post_commit=fail)
    assert manager.path.read_bytes() == raw
    assert manager.load().settings.interface_mode_change is None
    assert manager.load().settings.revision == 0


def test_failed_first_preferences_transaction_restores_absence(tmp_path):
    defaults = replace(default_settings(), instance_path=str(tmp_path / "instance"))
    manager = ShellSettingsManager(tmp_path / "launcher.json", defaults)

    def fail(_):
        raise RuntimeError("synthetic rejected preference side effect")

    with pytest.raises(RuntimeError):
        manager.mutate(lambda current: replace(current, theme="dark"),
                       expected_revision=0, post_commit=fail)
    assert not manager.path.exists()
