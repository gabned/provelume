from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from provelume.about import current_about
from provelume.desktop import (
    STRINGS,
    DesktopShell,
    LauncherSettings,
    _acquire_windows_mutex,
    _window_dimensions,
    declare_startup_update_policy,
    diagnostics_payload,
    load_settings,
    main,
    save_settings,
    startup_update_policy_enabled,
    write_ui_diagnostics,
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
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.exit_code or 0

    def kill(self) -> None:
        self.killed = True
        self.exit_code = -9


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
    assert value["version"] == "0.5.0"
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


def test_missing_persisted_instance_is_not_silently_recreated(tmp_path: Path) -> None:
    missing = tmp_path / "Moved Instance"
    shell = DesktopShell.__new__(DesktopShell)
    shell.settings = LauncherSettings(instance_path=str(missing), language="en")
    shell.text = STRINGS["en"]

    with pytest.raises(RuntimeError, match="could not be found"):
        shell._ensure_instance(missing, create_if_missing=False)
    assert not missing.exists()

    shell._ensure_instance(missing, create_if_missing=True)
    assert ProvelumeInstance(missing).instance_summary()["name"] == "My Provelume"


def test_unwritable_default_instance_fails_visibly(tmp_path: Path, monkeypatch) -> None:
    shell = DesktopShell.__new__(DesktopShell)
    shell.settings = LauncherSettings(instance_path=str(tmp_path), language="it")
    shell.text = STRINGS["it"]

    def reject_initialise(*_args, **_kwargs):
        raise PermissionError("synthetic access denied")

    monkeypatch.setattr(ProvelumeInstance, "initialise", reject_initialise)
    with pytest.raises(RuntimeError, match="Impossibile aprire"):
        shell._ensure_instance(tmp_path / "non scrivibile", create_if_missing=True)


def test_missing_instance_keeps_recovery_controls_available() -> None:
    shell = DesktopShell.__new__(DesktopShell)
    shell.instance_available = True
    shell.status = _Value("ready")
    shell.open_button = _Button()
    shell.stop_button = _Button()
    shell.choose_button = _Button()
    shell.create_button = _Button()

    shell._show_instance_error("synthetic missing Instance")

    assert shell.instance_available is False
    assert shell.status.get() == "synthetic missing Instance"
    assert shell.open_button.state == "disabled"
    assert shell.stop_button.state == "disabled"
    assert shell.choose_button.state == "normal"
    assert shell.create_button.state == "normal"


def test_desktop_diagnostics_and_headless_instance_bootstrap(tmp_path: Path) -> None:
    diagnostics = diagnostics_payload()
    assert diagnostics["desktop_shell"] is True
    assert diagnostics["network_used"] is False
    assert diagnostics["about"]["version"] == "0.5.0"

    root = tmp_path / "Instance with spaces"
    assert main(["--bootstrap-instance", str(root), "--instance-name", "Desktop Demo"]) == 0
    instance = ProvelumeInstance(root)
    assert instance.instance_summary()["name"] == "Desktop Demo"

    output = tmp_path / "diagnostics.json"
    assert main(["--diagnostics-file", str(output)]) == 0
    assert json.loads(output.read_text())["settings_schema_version"] == 1


def test_windowed_backend_does_not_require_console_logging(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "Instance with Unicode – 日本"
    ProvelumeInstance.initialise(root)
    app = object()
    observed: list[tuple[object, dict[str, object]]] = []

    monkeypatch.setattr("provelume.desktop.create_app", lambda _root: app)
    monkeypatch.setattr(
        "provelume.desktop.uvicorn.run",
        lambda selected, **kwargs: observed.append((selected, kwargs)),
    )

    assert main(["--serve", str(root), "--port", "8123"]) == 0
    assert observed == [
        (
            app,
            {
                "host": "127.0.0.1",
                "port": 8123,
                "log_level": "warning",
                "log_config": None,
                "access_log": False,
            },
        )
    ]


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
    shell.check_button = _Button()
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
    shell.check_button = _Button()
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
    shell.server_ready = False
    shell.status = _Value("starting")
    shell.text = {"running": "running", "server_failed": "failed"}
    shell.open_button = _Button()
    shell.stop_button = _Button()
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
    assert shell.server_ready is True
    assert shell.open_button.state == "normal"


def test_repeated_open_during_startup_never_opens_browser(monkeypatch) -> None:
    shell = DesktopShell.__new__(DesktopShell)
    shell.server = _Process()
    shell.server_port = 8040
    shell.server_ready = False
    opened: list[str] = []
    monkeypatch.setattr("provelume.desktop.webbrowser.open", opened.append)

    shell.open_product()

    assert opened == []


def test_failed_or_terminated_backend_keeps_an_actionable_state(monkeypatch) -> None:
    shell = DesktopShell.__new__(DesktopShell)
    process = _Process(exit_code=1)
    shell.closed = False
    shell.server = process
    shell.server_port = 8040
    shell.server_ready = False
    shell.instance_available = True
    shell.status = _Value("starting")
    shell.text = {
        "server_failed": "failed visibly",
        "server_exited": "exited visibly",
        "stopped": "stopped",
        "stopping": "stopping",
    }
    shell.open_button = _Button()
    shell.stop_button = _Button()
    monkeypatch.setattr("provelume.desktop.webbrowser.open", pytest.fail)

    shell._server_ready(process, 8040, False)
    assert shell.status.get() == "failed visibly"
    assert shell.server is None
    assert shell.open_button.state == "normal"
    assert shell.stop_button.state == "disabled"

    replacement = _Process()
    shell.server = replacement
    shell.server_port = 8041
    shell.server_ready = True
    shell._server_exited(replacement, 8041, 7)
    assert shell.status.get() == "exited visibly"
    assert shell.server is None
    assert shell.server_port is None
    assert shell.server_ready is False


@pytest.mark.parametrize(
    ("screen", "expected"),
    (
        ((1920, 1080), (680, 520)),
        ((800, 600), (680, 504)),
        ((640, 480), (592, 384)),
    ),
)
def test_window_dimensions_fit_reduced_work_areas(screen, expected) -> None:
    assert _window_dimensions(*screen) == expected


def test_en_it_launcher_copy_covers_every_transient_state() -> None:
    required = {
        "starting",
        "running",
        "stopping",
        "stopped",
        "server_failed",
        "server_exited",
        "checking",
        "current",
        "available",
        "downloading",
        "download_ready",
        "network_notice",
        "unsigned_notice",
        "install_notice",
        "missing_instance",
    }
    for language in ("en", "it"):
        assert required <= STRINGS[language].keys()
        assert all(STRINGS[language][key].strip() for key in required)
        assert STRINGS[language]["network_notice"] != STRINGS[language]["install_notice"]


@pytest.mark.skipif(os.name != "nt", reason="named Windows mutex")
def test_windows_mutex_rejects_a_second_launcher() -> None:
    import ctypes

    first = _acquire_windows_mutex()
    try:
        assert first is not None
        assert _acquire_windows_mutex() is None
    finally:
        ctypes.windll.kernel32.CloseHandle(first)


@pytest.mark.skipif(os.name != "nt", reason="real Tk layout probe")
def test_windows_tk_layout_probe_is_offline_and_scrollable(tmp_path: Path) -> None:
    output = tmp_path / "layout.json"
    write_ui_diagnostics(
        output,
        language="it",
        dpi_percent=200,
        viewport_width=640,
        viewport_height=480,
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["language"] == "it"
    assert value["dpi_percent"] == 200
    assert value["network_used"] is False
    assert value["instance_content_sent"] is False
    assert value["all_action_labels_present"] is True
    assert value["window"]["width"] <= 640
    assert value["window"]["height"] <= 480
    assert value["scroll_surface"]["viewport_width"] > 1
    assert value["scroll_surface"]["viewport_height"] > 1
    assert value["scroll_surface"]["content_height"] > 0
    assert value["controls"] == {
        "check": "normal",
        "choose": "normal",
        "create": "normal",
        "download": "disabled",
        "open": "normal",
        "stop": "disabled",
    }


@pytest.mark.skipif(os.name != "nt", reason="real Tk recovery probe")
def test_windows_missing_persisted_instance_renders_recovery_shell(
    tmp_path: Path,
) -> None:
    import tkinter as tk

    root = tk.Tk()
    shell = None
    try:
        shell = DesktopShell(
            root,
            initial_settings=LauncherSettings(
                instance_path=str(tmp_path / "Moved Instance – 日本"),
                language="en",
            ),
            create_instance_if_missing=False,
        )
        root.update()
        assert shell.instance_available is False
        assert str(shell.open_button.cget("state")) == "disabled"
        assert str(shell.stop_button.cget("state")) == "disabled"
        assert str(shell.choose_button.cget("state")) == "normal"
        assert str(shell.create_button.cget("state")) == "normal"
        assert "could not be found" in shell.status.get()
    finally:
        if shell is not None:
            shell.close()
        else:
            root.destroy()
