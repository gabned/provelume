from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.service import ProvelumeInstance
from provelume.shell_activity import MAX_ACTIVE_NONCES, MutationNonces
from provelume.shell_i18n import SHELL_TRANSLATIONS
from provelume.shell_settings import (
    APP_USER_MODEL_ID,
    DEFAULT_LOCAL_PORT,
    LOCAL_HOST,
    MAX_SETTINGS_REVISION,
    LauncherSettings,
    ShellPortUnavailable,
    ShellPreferencesError,
    ShellSettingsBusy,
    ShellSettingsError,
    ShellSettingsManager,
    ShellSettingsStale,
    probe_port,
    validate_port,
    validate_startup_executable,
)
from provelume.web import create_app
from provelume.windows_tray import TRAY_LABELS, TRAY_STATUS_LABELS, TrayLifecycleHarness


def _manager(tmp_path: Path, *, name: str = "launcher.json") -> ShellSettingsManager:
    return ShellSettingsManager(
        tmp_path / name,
        LauncherSettings(instance_path=str(tmp_path / "private Instance – 日本")),
    )


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((LOCAL_HOST, 0))
        return int(listener.getsockname()[1])


def _form_fields(page: str) -> dict[str, str]:
    fields = {}
    for name in ("csrf_token", "mutation_nonce", "revision"):
        match = re.search(rf'name="{name}" value="([^"]*)"', page)
        assert match is not None
        fields[name] = match.group(1)
    return fields


def test_default_endpoint_and_closed_versioned_schema(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    loaded = manager.load()

    assert loaded.warning == "settings_missing_using_defaults"
    assert loaded.settings.endpoint_port == DEFAULT_LOCAL_PORT == 44851
    assert loaded.settings.tray_enabled is True
    assert loaded.settings.login_startup is False
    assert loaded.settings.theme == "system"
    manager.save(loaded.settings)
    value = json.loads(manager.path.read_text(encoding="utf-8"))
    assert set(value) == {
        "schema_version",
        "revision",
        "instance_path",
        "update_channel",
        "check_on_start",
        "language",
        "endpoint",
        "shell",
    }
    assert value["schema_version"] == 2
    assert value["endpoint"] == {
        "host": LOCAL_HOST,
        "last_good_port": DEFAULT_LOCAL_PORT,
        "port": DEFAULT_LOCAL_PORT,
        "restart_required": False,
    }
    assert value["shell"] == {
        "login_startup": False,
        "theme": "system",
        "tray_enabled": True,
    }


def test_schema_one_upgrade_preserves_compatible_preferences(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "instance_path": str(tmp_path / "legacy"),
                "update_channel": "stable",
                "check_on_start": True,
                "language": "it",
            }
        ),
        encoding="utf-8",
    )

    loaded = manager.load()

    assert loaded.warning == "legacy_settings_loaded_pending_migration"
    assert loaded.settings.endpoint_port == DEFAULT_LOCAL_PORT
    assert loaded.settings.tray_enabled is True
    changed = manager.set_preferences(theme="dark", expected_revision=0)
    assert changed.language == "it"
    assert changed.update_channel == "stable"
    assert json.loads(manager.path.read_text())["schema_version"] == 2


@pytest.mark.parametrize(
    "value",
    (True, 0, 1, 1023, 65536, 100000, "x", 44851.0, " 44851", "+44851", "４４８５１"),
)
def test_endpoint_rejects_reserved_out_of_range_and_non_integer_values(value) -> None:
    with pytest.raises(ShellSettingsError):
        validate_port(value)


def test_occupied_port_is_rejected_without_mutating_configuration(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.save(manager.defaults)
    before = manager.path.read_bytes()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((LOCAL_HOST, 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with pytest.raises(ShellPortUnavailable):
            manager.set_port(port, expected_revision=0)
        assert probe_port(port)["status"] == "occupied"

    assert manager.path.read_bytes() == before


def test_atomic_apply_restart_success_reset_and_explicit_rollback(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = _available_port()
    second = _available_port()
    while second == first:
        second = _available_port()

    configured = manager.set_port(first, expected_revision=0)
    assert configured.revision == 1
    assert configured.restart_required is True
    assert configured.last_good_port == DEFAULT_LOCAL_PORT
    started = manager.mark_endpoint_started(first, expected_revision=1)
    assert started.restart_required is False
    assert started.last_good_port == first
    pending = manager.set_port(second, expected_revision=2)
    rolled_back = manager.rollback_endpoint(expected_revision=pending.revision)
    assert rolled_back.endpoint_port == first
    assert rolled_back.restart_required is True
    reset = manager.reset_port(expected_revision=rolled_back.revision)
    assert reset.endpoint_port == DEFAULT_LOCAL_PORT


def test_failed_post_commit_rolls_back_exact_previous_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    manager.save(manager.defaults)
    before = manager.path.read_bytes()

    def fail_startup(_enabled: bool, *, command=None) -> None:
        raise OSError("synthetic registry failure")

    monkeypatch.setattr("provelume.shell_settings.configure_login_startup", fail_startup)
    with pytest.raises(OSError, match="synthetic registry failure"):
        manager.set_preferences(login_startup=True, expected_revision=0)

    assert manager.path.read_bytes() == before
    assert manager.load().settings.login_startup is False


def test_corrupt_remote_host_and_oversized_settings_fail_to_safe_defaults(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.path.write_text('{"schema_version": 2, "endpoint": {"host": "0.0.0.0"}}')
    loaded = manager.load()
    assert loaded.warning == "settings_invalid_using_safe_defaults"
    assert loaded.settings.endpoint_port == DEFAULT_LOCAL_PORT
    assert loaded.settings.public_view()["endpoint"]["binding"] == "loopback_only"

    manager.path.write_bytes(b"{" + b"x" * (64 * 1024) + b"}")
    oversized = manager.load()
    assert oversized.warning == "settings_invalid_using_safe_defaults"


def test_empty_instance_path_in_schema_two_fails_to_safe_defaults(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    payload = manager.defaults.as_payload()
    payload["instance_path"] = ""
    manager.path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = manager.load()

    assert loaded.warning == "settings_invalid_using_safe_defaults"
    assert loaded.settings.instance_path == manager.defaults.instance_path
    assert loaded.settings.instance_path != "."


def test_crash_recovery_is_bounded_and_leaves_no_locked_temporary_writes(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.path.parent.mkdir(parents=True, exist_ok=True)
    abandoned = [manager.path.parent / f".{manager.path.name}.{index}.tmp" for index in range(35)]
    for path in abandoned:
        path.write_text("synthetic incomplete write", encoding="utf-8")

    first = manager.recover_abandoned_writes()
    second = manager.recover_abandoned_writes()

    assert first["abandoned_writes_removed"] == 32
    assert second["abandoned_writes_removed"] == 3
    assert not list(manager.path.parent.glob(f".{manager.path.name}.*.tmp"))
    manager.set_preferences(theme="light", expected_revision=0)
    assert manager.load().settings.theme == "light"


def test_lock_and_revision_guards_reject_concurrent_and_stale_updates(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.save(manager.defaults)
    with manager.hold(), pytest.raises(ShellSettingsBusy):
        manager.set_preferences(theme="dark")

    saved = manager.set_preferences(theme="dark", expected_revision=0)
    assert saved.revision == 1
    with pytest.raises(ShellSettingsStale):
        manager.set_preferences(theme="light", expected_revision=0)
    assert manager.load().settings.theme == "dark"


def test_revision_counter_is_bounded_and_does_not_rewrite_at_the_limit(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.save(LauncherSettings(instance_path=str(tmp_path), revision=MAX_SETTINGS_REVISION))
    before = manager.path.read_bytes()

    with pytest.raises(ShellSettingsError, match="revision limit"):
        manager.set_preferences(theme="dark", expected_revision=MAX_SETTINGS_REVISION)

    assert manager.path.read_bytes() == before


def test_preference_export_import_backup_restore_excludes_instance_data(tmp_path: Path) -> None:
    source = _manager(tmp_path, name="source.json")
    port = _available_port()
    configured = source.set_port(port, expected_revision=0)
    source.set_preferences(theme="dark", tray_enabled=False, expected_revision=configured.revision)
    export = tmp_path / "portable-shell.json"
    result = source.export_preferences(export)
    serialized = export.read_text(encoding="utf-8")

    assert result["contains_instance_path"] is False
    assert str(tmp_path) not in serialized
    assert "private Instance" not in serialized
    assert "instance_path" not in serialized

    destination = _manager(tmp_path, name="restored.json")
    restored = destination.import_preferences(export, expected_revision=0)
    assert restored.endpoint_port == port
    assert restored.theme == "dark"
    assert restored.tray_enabled is False
    assert restored.instance_path.endswith("private Instance – 日本")

    export.write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(ShellPreferencesError):
        destination.import_preferences(export)


@pytest.mark.skipif(os.name == "nt", reason="symlink fixture uses POSIX semantics")
def test_preference_import_rejects_symlink_and_symlink_parent(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(ShellPreferencesError, match="symlink"):
        manager.import_preferences(link)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ShellPreferencesError, match="parents"):
        manager.export_preferences(linked_parent / "export.json")
    (real_parent / "Provelume.exe").write_bytes(b"synthetic executable marker")
    with pytest.raises(ShellSettingsError, match="command is invalid"):
        validate_startup_executable(str(linked_parent / "Provelume.exe"))


def test_shell_cli_is_sanitized_and_uses_explicit_restart_plan(tmp_path: Path, capsys) -> None:
    settings_file = tmp_path / "launcher.json"
    port = _available_port()
    assert main(["set-endpoint", str(port), "--settings-file", str(settings_file)]) == 0
    changed = json.loads(capsys.readouterr().out)
    assert changed["endpoint"]["host"] == LOCAL_HOST
    assert changed["endpoint"]["port"] == port
    assert changed["restart_plan"]["automatic_restart"] is False
    assert str(tmp_path) not in json.dumps(changed)

    assert main(["shell-diagnostics", "--settings-file", str(settings_file)]) == 0
    diagnostics = json.loads(capsys.readouterr().out)
    assert diagnostics["privacy"] == {
        "contains_instance_path": False,
        "contains_secrets": False,
        "network_used": False,
    }
    assert diagnostics["signing"]["authenticode"] == "unsigned"
    assert main(["reset-endpoint", "--settings-file", str(settings_file)]) == 0
    assert json.loads(capsys.readouterr().out)["endpoint"]["port"] == DEFAULT_LOCAL_PORT


def test_browser_shell_mutation_has_csrf_nonce_revision_and_read_only_api(tmp_path: Path) -> None:
    instance_root = tmp_path / "instance"
    ProvelumeInstance.initialise(instance_root)
    settings_file = tmp_path / "launcher.json"
    port = _available_port()
    client = TestClient(
        create_app(
            instance_root,
            shell_settings_file=settings_file,
            effective_port=DEFAULT_LOCAL_PORT,
        )
    )
    page = client.get("/settings/shell?lang=en")
    assert page.status_code == 200
    fields = _form_fields(page.text)
    data = {
        **fields,
        "port": str(port),
        "tray_enabled": "on",
        "theme": "dark",
        "language": "it",
        "action": "save",
    }
    saved = client.post("/settings/shell?lang=it", data=data)
    assert saved.status_code == 200
    assert [response.status_code for response in saved.history] == [303]
    assert str(saved.url).endswith("/settings/shell?lang=it&status=saved")
    assert "salvate atomicamente" in saved.text
    assert 'data-theme="dark"' in saved.text
    assert f"http://{LOCAL_HOST}:{DEFAULT_LOCAL_PORT}" in saved.text
    assert f"http://{LOCAL_HOST}:{port}" in saved.text

    assert client.post("/settings/shell", data=data).status_code == 409
    assert client.post("/api/v1/shell", data=data).status_code == 405
    public = client.get("/api/v1/shell")
    assert public.status_code == 200
    assert public.json()["endpoint"]["port"] == port
    assert public.json()["service"]["port"] == DEFAULT_LOCAL_PORT
    assert public.json()["service"]["display"] == f"http://{LOCAL_HOST}:{DEFAULT_LOCAL_PORT}"
    assert public.json()["endpoint"]["binding"] == "loopback_only"
    assert str(tmp_path) not in public.text

    fresh = client.get("/settings/shell").text
    stale = _form_fields(fresh)
    stale["revision"] = "0"
    stale.update({"port": str(port), "theme": "light", "language": "en", "action": "save"})
    rejected = client.post("/settings/shell", data=stale)
    assert rejected.status_code == 400
    assert "stale_configuration" in rejected.text

    duplicate_page = client.get("/settings/shell?lang=en")
    duplicate_fields = _form_fields(duplicate_page.text)
    duplicate_body = urlencode(
        [
            *duplicate_fields.items(),
            ("port", str(port)),
            ("port", str(DEFAULT_LOCAL_PORT)),
            ("theme", "system"),
            ("language", "en"),
            ("action", "save"),
        ]
    )
    duplicate = client.post(
        "/settings/shell?lang=en",
        content=duplicate_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "invalid shell settings fields"


def test_ipv6_loopback_service_endpoint_uses_bracketed_url_authority(tmp_path: Path) -> None:
    instance_root = tmp_path / "instance"
    ProvelumeInstance.initialise(instance_root)
    client = TestClient(
        create_app(
            instance_root,
            shell_settings_file=tmp_path / "launcher.json",
            effective_host="::1",
            effective_port=DEFAULT_LOCAL_PORT,
        )
    )

    public = client.get("/api/v1/shell")
    page = client.get("/settings/shell?lang=en")

    assert public.status_code == page.status_code == 200
    assert public.json()["service"] == {
        "status": "running",
        "host": "::1",
        "port": DEFAULT_LOCAL_PORT,
        "display": f"http://[::1]:{DEFAULT_LOCAL_PORT}",
        "binding": "loopback_only",
    }
    assert f"http://[::1]:{DEFAULT_LOCAL_PORT}" in page.text


def test_browser_theme_navigation_and_inert_markup_are_accessible(tmp_path: Path) -> None:
    instance_root = tmp_path / "instance"
    ProvelumeInstance.initialise(instance_root, name='<script>alert("x")</script>')
    settings_file = tmp_path / "launcher.json"
    manager = ShellSettingsManager(
        settings_file,
        LauncherSettings(instance_path=str(instance_root), theme="dark"),
    )
    manager.save(manager.defaults)
    client = TestClient(create_app(instance_root, shell_settings_file=settings_file))
    page = client.get("/?lang=en")

    assert '<html lang="en" data-theme="dark">' in page.text
    assert '<a class="skip-link" href="#main-content">' in page.text
    assert '<nav aria-label="Primary navigation">' in page.text
    for label in (
        "Knowledge",
        "Operational status",
        "Configuration",
        "Maintenance",
        "Diagnostics &amp; support",
    ):
        assert label in page.text
    assert '<script>alert("x")</script>' not in page.text
    assert "&lt;script&gt;" in page.text
    css = client.get("/static/app.css").text
    assert "prefers-reduced-motion" in css
    assert "forced-colors: active" in css
    assert 'html[data-theme="light"]' in css
    assert 'html[data-theme="dark"]' in css


def test_en_it_shell_and_tray_semantics_are_complete_and_equivalent() -> None:
    assert set(SHELL_TRANSLATIONS["en"]) == set(SHELL_TRANSLATIONS["it"])
    assert set(TRAY_LABELS["en"]) == set(TRAY_LABELS["it"])
    assert set(TRAY_STATUS_LABELS["en"]) == set(TRAY_STATUS_LABELS["it"])
    assert all(
        value.strip()
        for catalog in SHELL_TRANSLATIONS.values()
        for value in catalog.values()
    )
    assert all(value.strip() for catalog in TRAY_LABELS.values() for value in catalog.values())
    assert all(
        value.strip() for catalog in TRAY_STATUS_LABELS.values() for value in catalog.values()
    )
    assert APP_USER_MODEL_ID == "Provelume.Desktop"


def test_login_startup_executable_rejects_argument_and_path_injection(tmp_path: Path) -> None:
    executable = tmp_path / "Provelume.exe"
    executable.write_bytes(b"synthetic executable marker")
    assert validate_startup_executable(str(executable)) == str(executable)
    for unsafe in (
        "Provelume.exe",
        f'{executable}" --unexpected',
        f"{executable}\n--unexpected",
        str(tmp_path / "Provelume.cmd"),
    ):
        with pytest.raises(ShellSettingsError, match="command is invalid"):
            validate_startup_executable(unsafe)


def test_nonce_registry_is_bounded_and_each_reference_is_single_use() -> None:
    nonces = MutationNonces()
    values = [nonces.issue() for _ in range(MAX_ACTIVE_NONCES + 5)]
    assert nonces.consume(values[0]) is False
    assert nonces.consume(values[-1]) is True
    assert nonces.consume(values[-1]) is False


def test_tray_lifecycle_default_opt_out_single_instance_and_controlled_quit() -> None:
    tray = TrayLifecycleHarness(enabled=True)
    tray.start_service()
    tray.close_window()
    assert tray.evidence()["service_instances"] == 1
    assert tray.evidence()["window_visible"] is False
    tray.open_interface()
    tray.open_interface()
    tray.restart_service()
    assert tray.evidence()["service_instances"] == 1
    tray.quit()
    assert tray.evidence() == {
        "schema_version": 1,
        "tray_enabled": True,
        "service_instances": 0,
        "window_visible": False,
        "shell_running": False,
        "network_used": False,
    }

    opted_out = TrayLifecycleHarness(enabled=False)
    opted_out.start_service()
    opted_out.close_window()
    assert opted_out.evidence()["service_instances"] == 0
    assert opted_out.evidence()["shell_running"] is False


def test_shell_preferences_never_modify_instance_canonical_or_provider_data(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    before = {
        str(path.relative_to(instance.root)): (
            None if path.is_dir() else path.read_bytes()
        )
        for path in instance.root.rglob("*")
    }
    manager = _manager(tmp_path)
    manager.set_preferences(theme="light", tray_enabled=False, expected_revision=0)

    after = {
        str(path.relative_to(instance.root)): (
            None if path.is_dir() else path.read_bytes()
        )
        for path in instance.root.rglob("*")
    }
    assert after == before


def test_shell_sources_contain_no_firewall_or_remote_bind_actions() -> None:
    root = Path(__file__).resolve().parents[1]
    text = "\n".join(
        (root / relative).read_text(encoding="utf-8")
        for relative in (
            "core/provelume/shell_settings.py",
            "core/provelume/desktop.py",
            "core/provelume/shell_activity.py",
        )
    ).casefold()
    assert "new-netfirewallrule" not in text
    assert "netsh advfirewall" not in text
    assert 'host="0.0.0.0"' not in text
    assert "socket.gethostbyname" not in text
