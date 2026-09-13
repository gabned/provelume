from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from html.parser import HTMLParser
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from provelume import desktop, shell_activity, shell_settings
from provelume.service import ProvelumeInstance
from provelume.shell_settings import (
    MAX_SETTINGS_REVISION,
    LauncherSettings,
    LoadedSettings,
    ShellPreferencesError,
    ShellSettingsBusy,
    ShellSettingsError,
    ShellSettingsManager,
    ShellSettingsStale,
)
from provelume.web import create_app


def _manager(tmp_path: Path, name: str = "launcher.json") -> ShellSettingsManager:
    return ShellSettingsManager(
        tmp_path / name,
        LauncherSettings(instance_path=str(tmp_path / "synthetic-private-instance"), language="it"),
    )


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class _Forms(HTMLParser):
    def __init__(self, page: str):
        super().__init__()
        self.forms: list[tuple[str | None, dict[str, str]]] = []
        self.active: dict[str, str] | None = None
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form":
            self.active = {}
            self.forms.append((attributes.get("id"), self.active))
        elif tag == "input" and self.active is not None and attributes.get("name"):
            if "disabled" in attributes:
                return
            is_check = attributes.get("type") in {"checkbox", "radio"}
            if is_check and "checked" not in attributes:
                return
            self.active[attributes["name"]] = attributes.get("value", "on" if is_check else "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.active = None


def _mode_fields(client: TestClient) -> dict[str, str]:
    page = client.get("/settings/shell?lang=en")
    assert page.status_code == 200
    forms = _Forms(page.text).forms
    fields = next(values for name, values in forms if name == "interface-mode-form")
    assert fields["action"] == "set-interface-mode"
    return {**fields, "interface_mode": "preview"}


def _browser(tmp_path: Path):
    instance = tmp_path / "instance"
    ProvelumeInstance.initialise(instance, name="Synthetic Cura preference check")
    manager = _manager(tmp_path)
    manager.save(manager.defaults)
    app = create_app(instance, shell_settings_file=manager.path)
    return TestClient(app), manager, instance


@pytest.mark.parametrize("schema", [1, 2])
def test_compatible_current_preferences_keep_schema_two_until_interface_selection(tmp_path, schema):
    manager = _manager(tmp_path)
    payload = {
        "schema_version": schema,
        "instance_path": str(tmp_path / "legacy-synthetic-instance"),
        "update_channel": "stable",
        "check_on_start": True,
        "language": "it",
    }
    if schema == 2:
        payload.update(
            {
                "revision": 7,
                "endpoint": {
                    "host": "127.0.0.1",
                    "port": 44880,
                    "last_good_port": 44879,
                    "restart_required": True,
                },
                "shell": {"tray_enabled": False, "login_startup": True, "theme": "dark"},
            }
        )
    manager.path.write_text(json.dumps(payload), encoding="utf-8")
    before, modified = manager.path.read_bytes(), manager.path.stat().st_mtime_ns
    loaded = manager.load()
    assert loaded.warning == ("legacy_settings_loaded_pending_migration" if schema == 1 else None)
    assert loaded.settings.schema_version == 2
    assert loaded.settings.interface_mode == "current"
    assert loaded.settings.interface_mode_change is None
    assert manager.path.read_bytes() == before and manager.path.stat().st_mtime_ns == modified
    assert not manager.lock_path.exists()
    saved = manager.set_preferences(theme="light", expected_revision=loaded.settings.revision)
    assert saved == replace(loaded.settings, theme="light", revision=loaded.settings.revision + 1)
    serialized = json.loads(manager.path.read_bytes())
    assert serialized["schema_version"] == 2
    assert serialized["shell"] == {
        "tray_enabled": saved.tray_enabled,
        "login_startup": saved.login_startup,
        "theme": "light",
    }
    assert manager.load().warning is None
    transferred = tmp_path / "ordinary-preferences.json"
    manager.export_preferences(transferred)
    imported = manager.import_preferences(transferred, expected_revision=saved.revision)
    started = manager.mark_endpoint_started(
        imported.endpoint_port, expected_revision=imported.revision
    )
    changed = manager.set_preferences(language="en", expected_revision=started.revision)
    assert changed.schema_version == json.loads(manager.path.read_bytes())["schema_version"] == 2
    assert changed.interface_mode == "current" and changed.interface_mode_change is None


@pytest.mark.parametrize("mode", ["current", "preview"])
def test_first_interface_choice_promotes_schema_and_receipt_in_one_write(
    tmp_path, monkeypatch, mode
):
    manager = _manager(tmp_path)
    manager.save(manager.defaults)
    original_write = shell_settings._atomic_json
    writes = []

    def observe_write(path, payload, **kwargs):
        writes.append(payload)
        original_write(path, payload, **kwargs)

    monkeypatch.setattr(shell_settings, "_atomic_json", observe_write)
    saved = manager.set_interface_mode(mode, expected_revision=0)
    assert len(writes) == 1
    assert writes[0]["schema_version"] == saved.schema_version == 3
    assert writes[0]["shell"]["interface_mode"] == mode
    receipt = writes[0]["shell"]["interface_mode_change"]
    assert receipt["revision"] == writes[0]["revision"] == saved.revision == 1
    assert receipt["from"] == "current" and receipt["to"] == mode
    assert receipt["changed"] is (mode != "current")
    assert manager.load().settings == saved


@pytest.mark.parametrize("mode", ["current", "preview"])
def test_existing_schema_three_without_receipt_survives_every_ordinary_save(
    tmp_path, monkeypatch, mode
):
    manager = _manager(tmp_path)
    payload = manager.defaults.as_payload()
    payload["schema_version"] = 3
    payload["revision"] = 7
    payload["shell"].update(interface_mode=mode, interface_mode_change=None)
    manager.path.write_text(json.dumps(payload), encoding="utf-8")
    before, modified = manager.path.read_bytes(), manager.path.stat().st_mtime_ns
    loaded = manager.load()
    assert loaded.warning is None and loaded.settings.schema_version == 3
    assert manager.path.read_bytes() == before and manager.path.stat().st_mtime_ns == modified
    saved = manager.set_preferences(theme="dark", language="en", expected_revision=7)
    started = manager.mark_endpoint_started(saved.endpoint_port, expected_revision=8)
    transfer = tmp_path / "ordinary.json"
    manager.export_preferences(transfer)
    imported = manager.import_preferences(transfer, expected_revision=started.revision)
    desktop.save_settings(LauncherSettings(**asdict(imported)), manager.path)
    restarted = desktop.load_settings(manager.path)
    assert restarted.schema_version == 3 and restarted.interface_mode == mode
    assert restarted.interface_mode_change is None
    assert json.loads(manager.path.read_bytes())["schema_version"] == 3
    assert restarted.public_view()["configuration_schema_version"] == 3
    monkeypatch.setattr(desktop, "settings_path", lambda: manager.path)
    assert desktop.diagnostics_payload()["settings_schema_version"] == 3
    before = manager.path.read_bytes()
    with pytest.raises(ShellSettingsError, match="cannot be downgraded"):
        manager.save(manager.defaults)
    assert manager.path.read_bytes() == before


@pytest.mark.parametrize("schema", [None, True, 0, 1, 4, "2"])
def test_in_memory_schema_marker_is_strict_and_never_coerced(tmp_path, schema):
    manager = _manager(tmp_path)
    with pytest.raises(ShellSettingsError, match="schema is invalid"):
        manager.save(replace(manager.defaults, schema_version=schema))
    assert not manager.path.exists()


def test_schema_two_serialization_never_drops_an_interface_choice(tmp_path):
    manager = _manager(tmp_path)
    with pytest.raises(ShellSettingsError, match="requires launcher settings schema 3"):
        replace(manager.defaults, interface_mode="preview").as_payload()
    chosen = manager.set_interface_mode("current", expected_revision=0)
    with pytest.raises(ShellSettingsError, match="requires launcher settings schema 3"):
        replace(chosen, schema_version=2).as_payload()


def test_mode_and_minimized_receipt_commit_once_without_unrelated_effects(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    manager.save(replace(manager.defaults, restart_required=True, last_good_port=44880))
    initial = manager.load().settings

    def forbidden(*args, **kwargs):
        pytest.fail("Interface selection must not touch ports or startup registration")

    monkeypatch.setattr("provelume.shell_settings.probe_port", forbidden)
    monkeypatch.setattr("provelume.shell_settings.configure_login_startup", forbidden)
    for revision, mode, changed in [
        (1, "preview", True),
        (2, "preview", False),
        (3, "current", True),
    ]:
        before = manager.load().settings
        saved = manager.set_interface_mode(mode, expected_revision=revision - 1)
        assert saved.revision == revision
        assert saved.schema_version == 3
        assert saved.interface_mode == mode
        assert saved.interface_mode_change is not None
        receipt = saved.interface_mode_change.as_payload()
        assert set(receipt) == {
            "schema_version",
            "revision",
            "recorded_at_utc",
            "from",
            "to",
            "changed",
            "source",
        }
        assert receipt["revision"] == revision
        assert receipt["from"] == before.interface_mode and receipt["to"] == mode
        assert receipt["changed"] is changed
        assert receipt["source"] == "local_process"
        assert receipt["recorded_at_utc"].endswith("+00:00")
        assert str(tmp_path) not in json.dumps(receipt)
        assert (
            replace(
                saved,
                interface_mode="current",
                interface_mode_change=None,
                revision=0,
                schema_version=2,
            )
            == initial
        )
        assert _manager(tmp_path).load().settings == saved
        assert LauncherSettings(**asdict(saved)).normalized() == saved


@pytest.mark.parametrize("invalid", [None, True, 1, [], {}, "Preview", "", "../preview"])
def test_invalid_modes_never_rewrite_saved_settings(tmp_path, invalid):
    manager = _manager(tmp_path)
    manager.set_interface_mode("current", expected_revision=0)
    before = manager.path.read_bytes()
    with pytest.raises(ShellSettingsError):
        manager.set_interface_mode(invalid, expected_revision=1)
    assert manager.path.read_bytes() == before
    payload = json.loads(before)
    payload["shell"]["interface_mode"] = invalid
    manager.path.write_text(json.dumps(payload))
    corrupt = manager.path.read_bytes()
    loaded = manager.load()
    assert loaded.warning == "settings_invalid_using_safe_defaults"
    assert loaded.settings.interface_mode == "current"
    assert manager.path.read_bytes() == corrupt


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", True),
        ("revision", 0),
        ("revision", True),
        ("revision", 2),
        ("from", []),
        ("from", "unknown"),
        ("to", "current"),
        ("changed", False),
        ("changed", 1),
        ("source", "remote"),
        ("source", []),
        ("recorded_at_utc", "2026-09-12T20:00:00+02:00"),
        ("recorded_at_utc", "2026-09-12T20:00:00"),
        ("recorded_at_utc", "x" * 41),
        ("unexpected", "synthetic secret"),
    ],
)
def test_schema_three_rejects_forged_receipt_without_rewriting(tmp_path, key, value):
    manager = _manager(tmp_path)
    manager.set_interface_mode("preview", expected_revision=0)
    payload = json.loads(manager.path.read_bytes())
    payload["shell"]["interface_mode_change"][key] = value
    manager.path.write_text(json.dumps(payload))
    before = manager.path.read_bytes()
    loaded = manager.load()
    assert loaded.warning == "settings_invalid_using_safe_defaults"
    assert (
        loaded.settings.interface_mode == "current"
        and loaded.settings.interface_mode_change is None
    )
    assert manager.path.read_bytes() == before


@pytest.mark.parametrize("missing", ["interface_mode", "interface_mode_change"])
def test_schema_three_requires_both_declared_selection_fields(tmp_path, missing):
    manager = _manager(tmp_path)
    manager.set_interface_mode("current", expected_revision=0)
    payload = json.loads(manager.path.read_bytes())
    del payload["shell"][missing]
    manager.path.write_text(json.dumps(payload))
    assert manager.load().warning == "settings_invalid_using_safe_defaults"


def test_failed_atomic_replace_preserves_mode_and_receipt_together(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    manager.set_interface_mode("preview", expected_revision=0)
    before = manager.path.read_bytes()

    def fail_replace(*args):
        raise OSError("synthetic atomic replace failure")

    monkeypatch.setattr("provelume.shell_settings.os.replace", fail_replace)
    with pytest.raises(OSError, match="synthetic atomic"):
        manager.set_interface_mode("current", expected_revision=1)
    assert manager.path.read_bytes() == before
    assert not list(tmp_path.glob(".launcher.json.*.tmp"))


def test_competing_selections_and_revision_limit_preserve_a_single_commit(tmp_path):
    manager = _manager(tmp_path)
    manager.save(manager.defaults)
    barrier = Barrier(2)

    def select(mode):
        barrier.wait()
        try:
            return _manager(tmp_path).set_interface_mode(mode, expected_revision=0)
        except (ShellSettingsBusy, ShellSettingsStale) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(select, ("preview", "current")))
    saved = [item for item in outcomes if isinstance(item, LauncherSettings)]
    assert len(saved) == 1 and manager.load().settings == saved[0]
    assert saved[0].revision == 1
    before = manager.path.read_bytes()
    with pytest.raises(ShellSettingsStale):
        manager.set_interface_mode("preview", expected_revision=0)
    with manager.hold(), pytest.raises(ShellSettingsBusy):
        manager.set_interface_mode("preview", expected_revision=1)
    assert manager.path.read_bytes() == before
    manager.save(replace(saved[0], revision=MAX_SETTINGS_REVISION))
    before = manager.path.read_bytes()
    with pytest.raises(ShellSettingsError, match="revision limit"):
        manager.set_interface_mode("current", expected_revision=MAX_SETTINGS_REVISION)
    assert manager.path.read_bytes() == before


@pytest.mark.parametrize("mode", ["current", "preview"])
def test_v1_transfer_preserves_destination_selection_and_receipt(tmp_path, monkeypatch, mode):
    source = _manager(tmp_path, "exporter.json")
    source.set_interface_mode("preview", expected_revision=0)
    source.set_preferences(theme="dark", language="en", expected_revision=1)
    transfer = tmp_path / "preferences.json"
    source.export_preferences(transfer)
    value = json.loads(transfer.read_bytes())
    assert set(value) == {
        "schema_version",
        "kind",
        "endpoint_port",
        "tray_enabled",
        "login_startup",
        "theme",
        "language",
    }
    assert value["schema_version"] == 1
    destination = _manager(tmp_path, "destination.json")
    selected = destination.set_interface_mode(mode, expected_revision=0)
    imported = destination.import_preferences(transfer, expected_revision=1)
    assert (
        imported.interface_mode == mode
        and imported.interface_mode_change == selected.interface_mode_change
    )
    assert imported.theme == "dark" and imported.language == "en" and imported.revision == 2
    before = destination.path.read_bytes()
    transfer.write_text(json.dumps({**value, "interface_mode": "current"}))
    with pytest.raises(ShellPreferencesError):
        destination.import_preferences(transfer)
    assert destination.path.read_bytes() == before
    transfer.write_text(json.dumps({**value, "login_startup": True}))

    def fail_startup(*args, **kwargs):
        raise OSError("synthetic startup failure")

    monkeypatch.setattr("provelume.shell_settings.configure_login_startup", fail_startup)
    with pytest.raises(OSError, match="synthetic startup"):
        destination.import_preferences(transfer, expected_revision=2)
    assert destination.path.read_bytes() == before


def test_v1_import_without_revision_preserves_mode_changed_after_preflight(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    manager.save(manager.defaults)
    transfer = tmp_path / "preferences.json"
    manager.export_preferences(transfer)
    original_mutate = manager.mutate

    def intervening_selection(mutator, **kwargs):
        _manager(tmp_path).set_interface_mode("preview", expected_revision=0)
        return original_mutate(mutator, **kwargs)

    monkeypatch.setattr(manager, "mutate", intervening_selection)
    imported = manager.import_preferences(transfer)
    assert imported.interface_mode == "preview" and imported.revision == 2
    assert imported.schema_version == json.loads(manager.path.read_bytes())["schema_version"] == 3
    assert imported.interface_mode_change.revision == 1


def test_desktop_edits_and_existing_installation_preserve_saved_mode(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    selected = manager.set_interface_mode("preview", expected_revision=0)
    shell = desktop.DesktopShell.__new__(desktop.DesktopShell)
    shell.settings_manager = manager
    shell._replace_settings(theme="dark", check_on_start=True)
    assert shell.settings.interface_mode_change == selected.interface_mode_change
    assert shell.settings.interface_mode == "preview"
    desktop.save_settings(shell.settings, manager.path)
    assert desktop.load_settings(manager.path) == shell.settings
    before = manager.path.read_bytes()
    startup = []
    monkeypatch.setattr(desktop, "settings_path", lambda: manager.path)
    monkeypatch.setattr(
        desktop, "configure_login_startup", lambda enabled, **kw: startup.append(enabled)
    )
    assert desktop.main(["--initialize-shell-settings"]) == 0
    assert manager.path.read_bytes() == before and startup == [False]


def test_browser_selection_separate_nonces_saved_language_and_instance_preservation(tmp_path):
    client, manager, instance = _browser(tmp_path)
    source = tmp_path / "comparison.txt"
    content = b"Synthetic retained knowledge for Cura preference rollback.\n"
    source.write_bytes(content)
    acquired = ProvelumeInstance(instance).ingest(source, source_name="Synthetic comparison")
    assert len(acquired) == 1
    before_instance = _files(instance)
    assert content in before_instance.values()
    page = client.get("/settings/shell?lang=en")
    forms = _Forms(page.text).forms
    ordinary = next(
        values for name, values in forms if name != "interface-mode-form" and "revision" in values
    )
    selected = next(values for name, values in forms if name == "interface-mode-form")
    assert ordinary["mutation_nonce"] != selected["mutation_nonce"]
    response = client.post(
        "/settings/shell?lang=en",
        data={**selected, "interface_mode": "preview"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/settings/shell?lang=it&status=saved"
    saved = manager.load().settings
    assert saved.interface_mode == "preview" and saved.revision == 1 and saved.language == "it"
    assert saved.interface_mode_change.source == "local_browser"
    public = client.get("/api/v1/shell")
    assert public.json()["shell"]["interface_mode"] == "preview"
    assert (
        public.json()["shell"]["interface_mode_change"] == saved.interface_mode_change.as_payload()
    )
    for private in (str(tmp_path), selected["csrf_token"], selected["mutation_nonce"]):
        assert private not in public.text
    stale = client.post("/settings/shell", data={**ordinary, "action": "reset-port"})
    assert stale.status_code == 400 and "stale_configuration" in stale.text
    assert manager.load().settings == saved
    rollback = _mode_fields(client)
    response = client.post(
        "/settings/shell", data={**rollback, "interface_mode": "current"}, follow_redirects=False
    )
    assert response.status_code == 303 and manager.load().settings.interface_mode == "current"
    assert _files(instance) == before_instance


@pytest.mark.parametrize(
    "patch,status",
    [
        ({"interface_mode": "../preview"}, 400),
        ({"interface_mode": None}, 400),
        ({"port": "44880"}, 400),
        ({"language": "en"}, 400),
        ({"source": "local_process"}, 400),
        ({"action": "save"}, 400),
        ({"action": "reset-port"}, 400),
        ({"csrf_token": "invalid"}, 403),
        ({"csrf_token": "日本"}, 403),
        ({"revision": "-1"}, 400),
        ({"revision": "١"}, 400),
        ({"revision": str(MAX_SETTINGS_REVISION + 1)}, 400),
    ],
)
def test_invalid_mode_forms_do_not_consume_nonce_or_change_settings(tmp_path, patch, status):
    client, manager, _instance = _browser(tmp_path)
    valid = _mode_fields(client)
    invalid = {**valid, **patch}
    invalid = {key: value for key, value in invalid.items() if value is not None}
    before = manager.path.read_bytes()
    response = client.post("/settings/shell", data=invalid, follow_redirects=False)
    assert response.status_code == status
    assert manager.path.read_bytes() == before
    assert client.post("/settings/shell", data=valid, follow_redirects=False).status_code == 303


def test_duplicate_wrong_type_oversized_and_nonlocal_mode_writes_fail_closed(tmp_path):
    client, manager, _instance = _browser(tmp_path)
    valid = _mode_fields(client)
    before = manager.path.read_bytes()
    duplicate = urlencode([*valid.items(), ("interface_mode", "current")])
    assert (
        client.post(
            "/settings/shell",
            content=duplicate,
            headers={"content-type": "application/x-www-form-urlencoded"},
        ).status_code
        == 400
    )
    assert client.post("/settings/shell", json=valid).status_code == 415
    assert (
        client.post(
            "/settings/shell",
            content="x" * (8 * 1024 + 1),
            headers={"content-type": "application/x-www-form-urlencoded"},
        ).status_code
        == 413
    )
    remote = TestClient(client.app, client=("203.0.113.10", 12345))
    remote_page = remote.get("/settings/shell")
    assert remote_page.status_code == 200 and 'name="mutation_nonce"' not in remote_page.text
    assert remote.post("/settings/shell", data=valid).status_code == 403
    assert client.post("/api/v1/shell", data=valid).status_code == 405
    assert manager.path.read_bytes() == before
    assert client.post("/settings/shell", data=valid, follow_redirects=False).status_code == 303
    committed = manager.path.read_bytes()
    assert client.post("/settings/shell", data=valid).status_code == 409
    assert manager.path.read_bytes() == committed


def test_failed_browser_save_returns_fresh_form_without_a_committed_receipt(tmp_path, monkeypatch):
    client, manager, _instance = _browser(tmp_path)
    fields = _mode_fields(client)
    before = manager.path.read_bytes()
    save = shell_settings._atomic_json

    def fail_once(*args, **kwargs):
        monkeypatch.setattr(shell_settings, "_atomic_json", save)
        raise OSError("synthetic write failure containing private detail")

    monkeypatch.setattr(shell_settings, "_atomic_json", fail_once)
    failed = client.post("/settings/shell", data=fields, follow_redirects=False)
    assert failed.status_code == 400 and "shell_settings_error" in failed.text
    assert "private detail" not in failed.text
    assert manager.path.read_bytes() == before
    assert manager.load().settings.interface_mode_change is None
    assert client.post("/settings/shell", data=fields).status_code == 409
    fresh = next(
        values for name, values in _Forms(failed.text).forms if name == "interface-mode-form"
    )
    assert fresh["mutation_nonce"] != fields["mutation_nonce"]
    assert (
        client.post(
            "/settings/shell", data={**fresh, "interface_mode": "preview"}, follow_redirects=False
        ).status_code
        == 303
    )
    assert manager.load().settings.interface_mode_change.revision == 1


@pytest.mark.parametrize("age,status", [(600, 303), (600.001, 409)])
def test_synthetic_nonce_expiry_and_app_restart_preserve_mode(tmp_path, monkeypatch, age, status):
    clock = [100.0]
    monkeypatch.setattr(shell_activity, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    client, manager, instance = _browser(tmp_path)
    fields = _mode_fields(client)
    clock[0] += age
    response = client.post("/settings/shell", data=fields, follow_redirects=False)
    assert response.status_code == status
    if status == 409:
        assert manager.load().settings.revision == 0
        fields = _mode_fields(client)
        assert (
            client.post("/settings/shell", data=fields, follow_redirects=False).status_code == 303
        )
    restarted = TestClient(create_app(instance, shell_settings_file=manager.path))
    assert restarted.get("/api/v1/shell").json()["shell"]["interface_mode"] == "preview"
    before = manager.path.read_bytes()
    assert restarted.post("/settings/shell", data=fields).status_code == 403
    assert manager.path.read_bytes() == before
    fresh = _mode_fields(restarted)
    assert (
        restarted.post(
            "/settings/shell", data={**fresh, "interface_mode": "current"}, follow_redirects=False
        ).status_code
        == 303
    )


def test_shell_page_reuses_one_snapshot_for_form_and_renderer(tmp_path, monkeypatch):
    client, manager, _instance = _browser(tmp_path)
    calls = []

    def changing_load():
        calls.append(True)
        return LoadedSettings(
            replace(
                manager.defaults,
                schema_version=3,
                revision=len(calls),
                interface_mode="preview" if len(calls) == 1 else "current",
            ),
            None,
        )

    monkeypatch.setattr(client.app.state.shell_settings_manager, "load", changing_load)
    fields = _mode_fields(client)
    assert fields["revision"] == "1"
    assert len(calls) == 1
