from __future__ import annotations

import json
from pathlib import Path

from provelume.about import current_about
from provelume.desktop import (
    DesktopShell,
    LauncherSettings,
    declare_startup_update_policy,
    diagnostics_payload,
    load_settings,
    main,
    save_settings,
    startup_update_policy_enabled,
)
from provelume.service import ProvelumeInstance
from provelume.updates import UpdateCandidate


class _Value:
    def __init__(self, value: object):
        self.value = value

    def get(self):
        return self.value

    def set(self, value: object) -> None:
        self.value = value


class _Button:
    def __init__(self):
        self.state: str | None = None

    def configure(self, *, state: str) -> None:
        self.state = state


class _Process:
    def __init__(self, exit_code: int | None = None):
        self.exit_code = exit_code

    def poll(self) -> int | None:
        return self.exit_code


def _candidate(*, channel: str) -> UpdateCandidate:
    return UpdateCandidate(
        version="0.4.0",
        tag="v0.4.0",
        channel=channel,
        commit="a" * 40,
        release_url="https://github.com/gabned/provelume/releases/tag/v0.4.0",
        manifest_url="https://github.com/gabned/provelume/releases/download/v0.4.0/manifest.json",
        installer_name="Provelume-Setup-0.4.0-x64.exe",
        installer_url=(
            "https://github.com/gabned/provelume/releases/download/v0.4.0/"
            "Provelume-Setup-0.4.0-x64.exe"
        ),
        installer_sha256="b" * 64,
        installer_size_bytes=123,
        architecture="x86_64",
        installer_type="inno_setup",
        minimum_windows_build=19045,
        signature_status="not_verified",
        automatic_apply=False,
    )


def test_about_is_local_and_describes_preview_update_boundary() -> None:
    value = current_about()

    assert value["product"] == "Provelume"
    assert value["version"] == "0.3.0"
    assert value["runtime"]["packaging"] == "python_package"
    assert value["updates"] == {
        "manual_check_available": True,
        "check_on_start_default": False,
        "automatic_apply": False,
        "initial_transport": "github_releases",
        "network_required_for_check": True,
        "instance_content_sent": False,
        "publisher_authentication": "not_established",
        "platform_signature": "not_verified",
    }


def test_launcher_settings_round_trip_and_malformed_fallback(tmp_path: Path) -> None:
    path = tmp_path / "launcher.json"
    expected = LauncherSettings(
        instance_path=str(tmp_path / "Mia's knowledge"),
        update_channel="stable",
        check_on_start=True,
        language="it",
    )
    save_settings(expected, path)
    assert load_settings(path) == expected

    path.write_text('{"schema_version": true}', encoding="utf-8")
    fallback = load_settings(path)
    assert fallback.schema_version == 1
    assert fallback.update_channel == "preview"
    assert fallback.check_on_start is False


def test_desktop_diagnostics_and_headless_instance_bootstrap(tmp_path: Path) -> None:
    diagnostics = diagnostics_payload()
    assert diagnostics["desktop_shell"] is True
    assert diagnostics["network_used"] is False
    assert diagnostics["about"]["version"] == "0.3.0"

    root = tmp_path / "Instance with spaces"
    assert main(["--bootstrap-instance", str(root), "--instance-name", "Desktop Demo"]) == 0
    instance = ProvelumeInstance(root)
    assert instance.instance_summary()["name"] == "Desktop Demo"

    output = tmp_path / "diagnostics.json"
    assert main(["--diagnostics-file", str(output)]) == 0
    assert json.loads(output.read_text())["settings_schema_version"] == 1


def test_startup_update_opt_in_is_visible_in_instance_network_status(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root)

    declare_startup_update_policy(root, enabled=True)
    enabled = instance.network_status()
    update = next(
        component
        for component in enabled["components"]
        if component["id"] == "builtin.update_checks"
    )
    assert update["enabled"] is True
    assert update["endpoint"] == "https://api.github.com"
    assert update["data_categories"] == []
    assert enabled["policy"]["external_access"] is True
    assert enabled["conflicts"] == []
    assert startup_update_policy_enabled(root) is True

    declare_startup_update_policy(root, enabled=False)
    disabled = instance.network_status()
    update = next(
        component
        for component in disabled["components"]
        if component["id"] == "builtin.update_checks"
    )
    assert update["enabled"] is False
    assert disabled["policy"]["external_access"] is False
    assert startup_update_policy_enabled(root) is False


def test_background_update_check_fails_closed_without_both_policy_flags(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root)
    config = instance.store.read_config()
    config["network"].update(
        {
            "external_access": False,
            "update_checks": True,
            "update_endpoint": "https://api.github.com",
            "update_data_categories": [],
        }
    )
    instance.store.write_config(config)

    shell = DesktopShell.__new__(DesktopShell)
    shell.instance = root
    shell.update_generation = 0
    shell.candidate = None
    shell.update_status = _Value("current")
    shell.download_button = _Button()
    shell.channel = _Value("preview")
    shell.text = {"network_notice": "network", "checking": "checking"}

    def reject_thread(*_args, **_kwargs):
        raise AssertionError("background network worker must not start")

    monkeypatch.setattr(
        "provelume.desktop.threading.Thread",
        reject_thread,
    )

    shell.check_updates(interactive=False)
    assert shell.update_generation == 0
    assert shell.update_status.get() == "current"


def test_stale_update_results_cannot_replace_the_current_channel() -> None:
    shell = DesktopShell.__new__(DesktopShell)
    shell.closed = False
    shell.update_generation = 2
    shell.channel = _Value("stable")
    shell.candidate = None
    shell.update_status = _Value("checking stable")
    shell.download_button = _Button()
    shell.text = {
        "current": "current",
        "failed": "failed: {error}",
        "available": "available: {version}",
    }

    shell._update_checked(_candidate(channel="preview"), 1, "preview")
    shell._update_failed("old failure", 1, "preview")
    assert shell.candidate is None
    assert shell.update_status.get() == "checking stable"
    assert shell.download_button.state is None

    stable = _candidate(channel="stable")
    shell._update_checked(stable, 2, "stable")
    assert shell.candidate == stable
    assert shell.update_status.get() == "available: 0.4.0"
    assert shell.download_button.state == "normal"


def test_stale_server_readiness_cannot_stop_a_replacement(monkeypatch) -> None:
    shell = DesktopShell.__new__(DesktopShell)
    old_process = _Process()
    current_process = _Process()
    shell.closed = False
    shell.server = current_process
    shell.server_port = 8041
    shell.status = _Value("starting")
    shell.text = {"running": "running", "server_failed": "failed"}
    stopped: list[bool] = []
    shell.stop_server = lambda: stopped.append(True)
    opened: list[str] = []
    monkeypatch.setattr("provelume.desktop.webbrowser.open", opened.append)

    shell._server_ready(old_process, 8040, False)
    assert shell.status.get() == "starting"
    assert stopped == []

    shell._server_ready(current_process, 8041, True)
    assert shell.status.get() == "running"
    assert opened == ["http://127.0.0.1:8041/"]
