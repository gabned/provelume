from __future__ import annotations

import json
from dataclasses import replace
from html import unescape

import pytest
from fastapi.testclient import TestClient

from provelume import __version__, desktop, perceptio, shell_settings
from provelume.build_info import current_build_info
from provelume.catalog_registry import SUPPORTED_LANGUAGES, message
from provelume.service import ProvelumeInstance
from provelume.shell_preferences import apply_preferences, preference_payload, reset_preview
from provelume.shell_settings import LauncherSettings, ShellSettingsManager, default_settings
from provelume.web import create_app


def test_fresh_browser_default_survives_restart_and_has_no_fabricated_choice(tmp_path):
    instance = tmp_path / "instance"
    ProvelumeInstance.initialise(instance)
    path = tmp_path / "launcher.json"
    first = TestClient(create_app(instance, shell_settings_file=path))
    public = first.get("/api/v1/shell").json()
    assert public["configuration_schema_version"] == 3
    assert public["shell"]["interface_mode"] == "preview"
    assert public["shell"]["interface_mode_change"] is None
    assert not path.exists()
    settings = first.app.state.shell_settings_manager
    settings.save(settings.load().settings)
    restarted = TestClient(create_app(instance, shell_settings_file=path))
    assert restarted.get("/api/v1/shell").json()["shell"] == public["shell"]
    home = restarted.get("/?lang=en")
    assert home.status_code == 200
    assert "cura-shell" in home.text


def test_fresh_installer_uses_the_same_qualified_default(tmp_path, monkeypatch):
    path = tmp_path / "launcher.json"
    monkeypatch.setattr(desktop, "settings_path", lambda: path)
    monkeypatch.setattr(
        shell_settings, "default_instance_directory", lambda: tmp_path / "synthetic-instance"
    )
    monkeypatch.setattr(desktop, "probe_port", lambda port: {"available": True})
    startup = []
    monkeypatch.setattr(
        desktop, "configure_login_startup", lambda enabled, **kw: startup.append(enabled)
    )
    assert desktop.main(["--initialize-shell-settings", "--install-language", "ro"]) == 0
    saved = desktop.load_settings(path)
    assert saved.interface_mode == "preview" and saved.schema_version == 3
    assert saved.interface_mode_change is None and saved.revision == 0
    assert saved.language == "ro" and saved.theme == "system"
    assert saved.tray_enabled and not saved.login_startup and startup == [False]
    assert saved.instance_path == str(tmp_path / "synthetic-instance")


@pytest.mark.parametrize("schema", [1, 2, 3])
def test_upgrade_keeps_existing_current_preferences_byte_for_byte(tmp_path, monkeypatch, schema):
    path = tmp_path / "launcher.json"
    legacy = LauncherSettings(instance_path=str(tmp_path / "legacy-instance"), language="it")
    payload = legacy.as_payload()
    if schema == 1:
        payload = {
            k: payload[k]
            for k in (
                "schema_version",
                "instance_path",
                "update_channel",
                "check_on_start",
                "language",
            )
        }
        payload["schema_version"] = 1
    elif schema == 3:
        payload = replace(legacy, schema_version=3).as_payload()
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    manager = ShellSettingsManager(path, default_settings())
    assert manager.load().settings.interface_mode == "current"
    monkeypatch.setattr(desktop, "settings_path", lambda: path)
    monkeypatch.setattr(desktop, "configure_login_startup", lambda *args, **kwargs: None)
    assert desktop.main(["--initialize-shell-settings"]) == 0
    assert path.read_bytes() == before
    assert desktop.load_settings(path).interface_mode == "current"


def test_explicit_reset_preview_and_undo_keep_selected_instance_and_legacy_rollback(tmp_path):
    instance = tmp_path / "retained-instance"
    instance.mkdir()
    original = instance / "synthetic-original.txt"
    original.write_bytes(b"Synthetic retained Original")
    legacy = LauncherSettings(instance_path=str(instance), language="ro", theme="dark")
    manager = ShellSettingsManager(tmp_path / "launcher.json", default_settings())
    manager.path.write_text(json.dumps(legacy.as_payload()), encoding="utf-8")
    plan = reset_preview(legacy, "appearance_language")
    assert plan["before"]["interface_mode"] == "current"
    assert plan["after"]["interface_mode"] == "preview"
    assert plan["after"]["language"] == plan["after"]["theme"] == "system"
    assert manager.load().settings == legacy
    saved = apply_preferences(manager, plan["after"], expected_revision=0)
    assert saved.interface_mode == "preview" and saved.interface_mode_change.from_mode == "current"
    undone = apply_preferences(manager, plan["before"], expected_revision=1)
    assert preference_payload(undone) == preference_payload(legacy)
    assert (
        undone.instance_path == str(instance)
        and original.read_bytes() == b"Synthetic retained Original"
    )


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("official", [False, True])
def test_live_identity_substitution_preserves_reviewed_wording(
    tmp_path, monkeypatch, language, official
):
    instance = tmp_path / "instance"
    ProvelumeInstance.initialise(instance)
    build = current_build_info()
    if official:
        build.update(
            official=True,
            identity_status="official_metadata_present",
            tag=f"v{__version__}",
            commit="a" * 40,
        )
    monkeypatch.setattr(perceptio, "current_build_info", lambda: build)
    client = TestClient(create_app(instance, shell_settings_file=tmp_path / "launcher.json"))
    response = client.get("/perceptio?lang=" + language)
    assert response.status_code == 200
    key = "perceptio.release_metadata" if official else "perceptio.unpublished"
    reviewed = message(language, key)
    assert "0.10.1" in reviewed
    rendered = reviewed.replace("0.10.1", __version__)
    assert rendered in unescape(response.text)
    model = ProvelumeInstance(instance).perceptio_read_model()
    assert model["target_version"] == "0.10.1"  # Immutable qualification baseline.
    assert model["publication"]["current_package_version"] == __version__
    assert model["publication"]["state"] == (
        "official_metadata_present" if official else "candidate"
    )
    assert model["publication"]["verification"]["status"] == "not_performed"
