from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from provelume import desktop
from provelume.about import current_about
from provelume.desktop import (
    STRINGS,
    DesktopShell,
    LauncherSettings,
    _acquire_windows_mutex,
    _window_dimensions,
    declare_startup_update_policy,
    diagnostics_payload,
    format_update_failure,
    load_settings,
    main,
    public_about_links,
    save_settings,
    startup_update_policy_enabled,
    write_native_tray_smoke,
)
from provelume.instance_lifecycle import InstanceLifecycleBusy
from provelume.service import ProvelumeInstance
from provelume.updates import UpdateCandidate, UpdateError


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


def test_initial_archive_preparation_is_owned_off_the_ui_thread(tmp_path, monkeypatch):
    """A blocked initial archive open must leave the Panel and cancellation available."""
    calling_thread = threading.get_ident()
    entered, release = threading.Event(), threading.Event()
    callbacks = []
    root = SimpleNamespace(
        protocol=lambda *_: None, after=lambda delay, action: callbacks.append((delay, action)),
    )
    tkinter = SimpleNamespace(
        ttk=SimpleNamespace(), StringVar=lambda value: _Value(value),
        BooleanVar=lambda value: _Value(value),
    )
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setattr("provelume.shell_appearance.apply_native_appearance", lambda *_: None)
    path = tmp_path / "launcher.json"
    settings = LauncherSettings(instance_path=str(tmp_path / "synthetic"), language="en",
                                schema_version=3)
    save_settings(settings, path)
    monkeypatch.setattr(desktop, "settings_path", lambda: path)
    monkeypatch.setattr(desktop, "declare_startup_update_policy", lambda *_args, **_kw: None)

    def build(shell):
        for name in ("open_button", "stop_button", "choose_button", "create_button",
                     "check_button"):
            setattr(shell, name, _Button())

    creation_grants = []

    def prepare(_shell, _path, *, create_if_missing, language=None):
        assert threading.get_ident() != calling_thread, "archive preparation ran on the UI thread"
        creation_grants.append(create_if_missing)
        entered.set()
        assert release.wait(2), "test preparation was not released"

    monkeypatch.setattr(DesktopShell, "_build", build)
    monkeypatch.setattr(DesktopShell, "_ensure_instance", prepare)
    shell = None
    try:
        shell = DesktopShell(root, initial_settings=settings, enable_native_tray=False,
                             enable_first_run_dialog=False)
        assert not entered.is_set()
        next(action for delay, action in callbacks if delay == 250)()
        assert entered.wait(1)
        owner = shell._startup
        assert owner is not None and owner.thread.is_alive() and not owner.done.is_set()
        assert shell.open_button.state == "disabled"
        shell.stop_server()
        assert owner.cancelled.is_set() and not owner.done.is_set()
        assert any(delay == 25 for delay, _ in callbacks)
    finally:
        release.set()
        if shell is not None and shell._startup is not None:
            assert shell._startup.done.wait(2)
            assert shell._startup.process is None
    shell._poll_startup()
    assert shell.open_button.state == "normal"
    shell.start_server()
    assert shell._startup.done.wait(2)
    assert creation_grants == [True, False]
    assert shell._startup.process is None


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
    assert value["version"] == "0.14.0"
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


def test_about_links_are_canonical_and_reject_untrusted_build_tags() -> None:
    value = current_about()
    value.update({"tag": "v0.11.0"})
    assert public_about_links(value) == {
        "repository": "https://github.com/gabned/provelume",
        "releases": "https://github.com/gabned/provelume/releases",
        "installed_release": "https://github.com/gabned/provelume/releases/tag/v0.11.0",
    }

    value["tag"] = "../../private"
    assert "installed_release" not in public_about_links(value)


def test_update_failures_are_actionable_localized_and_privacy_safe() -> None:
    error = UpdateError(
        "secret raw transport detail",
        code="tls_error",
        endpoint_origin="https://api.github.com",
        stage="release_manifest",
    )
    rendered = format_update_failure(error, STRINGS["it"])

    assert "connessione sicura" in rendered
    assert "manifest della release" in rendered
    assert "https://api.github.com" in rendered
    assert "tls_error" in rendered
    assert "secret raw transport detail" not in rendered


def test_launcher_settings_round_trip_and_malformed_fallback(tmp_path: Path) -> None:
    from provelume.shell_settings import default_settings

    path = tmp_path / "launcher.json"
    expected = replace(
        default_settings(),
        instance_path=str(tmp_path / "Mia's knowledge"),
        update_channel="stable",
        check_on_start=True,
        language="it",
    )
    save_settings(expected, path)
    assert load_settings(path) == expected

    path.write_text('{"schema_version": true}', encoding="utf-8")
    fallback = load_settings(path)
    assert fallback.schema_version == 3
    assert fallback.interface_mode == "preview" and fallback.interface_mode_change is None
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


def test_desktop_diagnostics_and_headless_instance_bootstrap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("provelume.desktop.settings_path", lambda: tmp_path / "launcher.json")
    diagnostics = diagnostics_payload()
    assert diagnostics["desktop_shell"] is True
    assert diagnostics["network_used"] is False
    assert diagnostics["about"]["version"] == "0.14.0"
    assert diagnostics["windows_identity"]["process_app_user_model_id"] in {
        "not_applicable",
        "configured",
    }

    root = tmp_path / "Instance with spaces"
    assert main(["--bootstrap-instance", str(root), "--instance-name", "Desktop Demo"]) == 0
    instance = ProvelumeInstance(root)
    assert instance.instance_summary()["name"] == "Desktop Demo"

    output = tmp_path / "diagnostics.json"
    assert main(["--diagnostics-file", str(output)]) == 0
    assert json.loads(output.read_text())["settings_schema_version"] == 3


def test_installer_validate_port_mode_rejects_reserved_and_occupied_ports() -> None:
    assert main(["--validate-port", "80"]) == 2

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        occupied_port = listener.getsockname()[1]
        assert main(["--validate-port", str(occupied_port)]) == 2


def test_login_startup_tray_mode_is_forwarded_to_the_native_shell(monkeypatch) -> None:
    observed: list[bool] = []

    def fake_run_ui(*, start_hidden: bool = False) -> int:
        observed.append(start_hidden)
        return 0

    monkeypatch.setattr("provelume.desktop.run_ui", fake_run_ui)

    assert main([]) == 0
    assert main(["--tray"]) == 0
    assert observed == [False, True]


def test_native_tray_smoke_mode_is_exclusive_and_returns_fail_closed_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observed: list[Path] = []

    def fake_native_smoke(path: Path) -> bool:
        observed.append(path)
        return len(observed) == 1

    monkeypatch.setattr("provelume.desktop.write_native_tray_smoke", fake_native_smoke)
    evidence = tmp_path / "native-tray.json"

    assert main(["--native-tray-smoke-file", str(evidence)]) == 0
    assert main(["--native-tray-smoke-file", str(evidence)]) == 2
    with pytest.raises(SystemExit, match="select only one"):
        main(
            [
                "--native-tray-smoke-file",
                str(evidence),
                "--diagnostics-file",
                str(tmp_path / "diagnostics.json"),
            ]
        )
    assert observed == [evidence, evidence]


@pytest.mark.skipif(os.name == "nt", reason="non-Windows fail-closed boundary")
def test_native_tray_smoke_evidence_fails_closed_without_leaking_paths(tmp_path: Path) -> None:
    evidence = tmp_path / "native-tray.json"

    assert write_native_tray_smoke(evidence) is False
    payload = json.loads(evidence.read_text(encoding="utf-8"))

    assert payload["status"] == "FAIL"
    assert payload["failure_code"] == "native_tray_requires_windows"
    assert payload["network_used"] is False
    assert payload["private_content_logged"] is False
    assert str(tmp_path) not in evidence.read_text(encoding="utf-8")


def test_windowed_backend_does_not_require_console_logging(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "Instance with Unicode – 日本"
    ProvelumeInstance.initialise(root)
    app = object()
    observed: list[tuple[object, dict[str, object]]] = []

    monkeypatch.setattr("provelume.desktop.create_app", lambda _root, **_kwargs: app)
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

    instance.google_connection.set_network(enabled=True, consent=True)
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
    assert disabled["policy"]["external_access"] is True
    assert startup_update_policy_enabled(root) is False


@pytest.mark.parametrize("failure", ["transient", "persistent", "invalid"])
def test_startup_policy_open_retries_only_bounded_lifecycle_contention(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root)
    before = instance.store.read_config()
    elapsed = 0.0
    attempts = 0
    writes = []
    write_config = instance.store.write_config
    error = (
        ValueError("invalid instance") if failure == "invalid" else InstanceLifecycleBusy("busy")
    )

    def sleep(seconds):
        nonlocal elapsed
        assert 0 < seconds <= 0.025
        elapsed += seconds

    def open_instance(path):
        nonlocal attempts
        assert path == root
        attempts += 1
        if failure == "transient" and attempts == 3:
            return instance
        raise error

    def write_once(config):
        writes.append(config)
        write_config(config)

    monkeypatch.setattr(desktop, "time", SimpleNamespace(monotonic=lambda: elapsed, sleep=sleep))
    monkeypatch.setattr(desktop, "ProvelumeInstance", open_instance)
    monkeypatch.setattr(instance.store, "write_config", write_once)
    if failure == "transient":
        declare_startup_update_policy(root, enabled=True)
        assert attempts == 3
        assert elapsed == 0.05
        assert len(writes) == 1
        assert instance.store.read_config()["network"]["update_checks"] is True
    else:
        with pytest.raises(type(error)) as raised:
            declare_startup_update_policy(root, enabled=True)
        assert raised.value is error
        assert writes == []
        assert instance.store.read_config() == before
        if failure == "persistent":
            assert elapsed == 2.0
            assert 80 <= attempts <= 82
        else:
            assert attempts == 1
            assert elapsed == 0


@pytest.mark.parametrize("external,component", [(False, True), (True, False), (False, False)])
def test_background_update_check_fails_closed_without_both_policy_flags(
    tmp_path: Path,
    monkeypatch,
    external,
    component,
) -> None:
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root)
    config = instance.store.read_config()
    config["network"].update(
        {
            "external_access": external,
            "update_checks": component,
            "update_endpoint": "https://api.github.com",
            "update_data_categories": [],
        }
    )
    instance.store.write_config(config)

    shell = DesktopShell.__new__(DesktopShell)
    shell.closed = False
    shell.instance = root
    shell.update_generation = 0
    shell.candidate = None
    shell.update_status = _Value("current")
    shell.download_button = _Button()
    shell.check_button = _Button()
    shell.channel = _Value("preview")
    shell.text = {"network_notice": "network", "checking": "checking"}

    network_calls, workers = [], []
    thread_type = threading.Thread
    policy_reader = desktop.startup_update_policy_enabled
    ui_thread = threading.get_ident()

    def policy(path):
        assert threading.get_ident() != ui_thread
        return policy_reader(path)

    def worker(*args, **kwargs):
        result = thread_type(*args, **kwargs)
        workers.append(result)
        return result

    monkeypatch.setattr(desktop, "startup_update_policy_enabled", policy)
    monkeypatch.setattr(desktop.threading, "Thread", worker)
    monkeypatch.setattr(shell, "_check_updates_worker", lambda *_: network_calls.append(True))

    shell.check_updates(interactive=False)
    for thread in workers:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert network_calls == []
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


def test_automatic_update_preserves_request_identity_and_rejects_a_late_grant(
    tmp_path, monkeypatch,
):
    shell = DesktopShell.__new__(DesktopShell)
    shell.instance = tmp_path / "synthetic"
    shell.closed = False
    shell.update_generation = 7
    calls = []
    monkeypatch.setattr(desktop, "startup_update_policy_enabled", lambda _: True)
    monkeypatch.setattr(shell, "_check_updates_worker", lambda *args: calls.append(args))
    shell._startup_update_check_worker(shell.instance, 7, "preview")
    assert calls == [("preview", 7)]
    calls.clear()

    entered, release = threading.Event(), threading.Event()

    def policy(_instance):
        entered.set()
        assert release.wait(2)
        return True

    monkeypatch.setattr(desktop, "startup_update_policy_enabled", policy)
    worker = threading.Thread(target=shell._startup_update_check_worker,
                              args=(shell.instance, 7, "preview"))
    try:
        worker.start()
        assert entered.wait(1)
        shell.update_generation = 8
    finally:
        release.set()
        worker.join(timeout=2)
    assert not worker.is_alive() and calls == []


def test_first_run_directory_creation_refuses_an_alias_before_descending(tmp_path):
    from provelume.maintenance_local_files import MaintenanceTargetError, prepare_local_directory

    target = tmp_path / "synthetic target"
    target.mkdir()
    alias = tmp_path / "alias"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(alias))
    else:
        alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(MaintenanceTargetError), prepare_local_directory(
        alias / "must not appear", create=True,
    ):
        pytest.fail("unsafe alias was accepted")
    assert not (target / "must not appear").exists()


def test_first_run_directory_creation_and_existing_only_recovery(tmp_path):
    from provelume.maintenance_local_files import MaintenanceTargetError, prepare_local_directory

    root = tmp_path / "new parent" / "new synthetic instance"
    with pytest.raises(MaintenanceTargetError), prepare_local_directory(root):
        pytest.fail("missing directory was silently created")
    assert not root.parent.exists()
    with prepare_local_directory(root, create=True) as (path, binding):
        assert path == root and root.is_dir() and binding
    marker = root / "synthetic preserved.txt"
    marker.write_text("synthetic original")
    with prepare_local_directory(root) as (_, binding):
        assert binding and marker.read_text() == "synthetic original"


@pytest.mark.parametrize("after_stop", ["install", "unconfirmed", "stale", "quit"])
def test_installer_waits_for_confirmed_cleanup_and_current_intent(
    tmp_path, monkeypatch, after_stop,
):
    shell = DesktopShell.__new__(DesktopShell)
    done, cancelled = threading.Event(), threading.Event()
    owner = SimpleNamespace(
        done=done, cancelled=cancelled, phase="PREPARING", events=queue.SimpleQueue(),
        cleanup_unconfirmed=False, request_stop=lambda: cancelled.set(),
    )
    shell._startup = owner
    shell._startup_poll_scheduled = False
    shell._startup_status_on_finish = "stopped"
    shell._restart_after_stop = False
    shell._pending_instance = None
    shell._close_requested = False
    shell.closed = False
    shell.root = SimpleNamespace(after=lambda *_: None, destroy=lambda: None)
    shell.tray = None
    shell.server = None
    shell.server_port = None
    shell.server_ready = False
    shell.open_target = None
    shell.instance_available = True
    shell.status = _Value("starting")
    shell.text = STRINGS["en"]
    shell.open_button, shell.stop_button = _Button(), _Button()
    shell.channel = _Value("preview")
    shell.update_generation = 2
    shell.candidate = _candidate(channel="preview")
    shell.update_status = _Value("downloaded")
    calls = []
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(
        messagebox=SimpleNamespace(askyesno=lambda *_: True),
    ))
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *args, **kw: calls.append((args, kw)))
    path = tmp_path / "synthetic-installer.exe"
    shell._installer_ready(path, shell.candidate, 2, "preview")
    assert cancelled.is_set() and not done.is_set()
    assert calls == [], "installer ran before owned cleanup completed"
    if after_stop == "unconfirmed":
        shell._show_startup_unconfirmed()
    elif after_stop == "stale":
        shell.update_generation += 1
    elif after_stop == "quit":
        shell.close()
    owner.events.put(("finished", {
        "code": "cancelled", "settings": None, "rolled_back": False,
    }))
    done.set()
    shell._poll_startup()
    if after_stop == "install":
        assert len(calls) == 1 and calls[0][0][0][0] == str(path)
        assert shell.closed
    else:
        assert calls == []


@pytest.mark.parametrize("language", sorted(STRINGS))
def test_update_channel_hint_is_not_a_download_and_invalidation_is_not_success(language) -> None:
    shell = DesktopShell.__new__(DesktopShell)
    shell.closed = False
    shell.update_generation = 2
    shell.channel = _Value("stable")
    shell.candidate = None
    shell.update_status = _Value("checking")
    shell.download_button = _Button()
    shell.check_button = _Button()
    shell.text = STRINGS[language]

    shell._update_checked(None, 2, "stable", "0.11.0")
    assert "stable" in shell.update_status.get()
    assert "0.11.0" in shell.update_status.get()
    assert "preview" in shell.update_status.get()
    assert shell.candidate is None
    assert shell.download_button.state == "disabled"

    shell.channel.set("preview")
    shell._invalidate_update_result()
    assert shell.update_status.get() == shell.text["not_checked"]
    shell._update_checked(None, 2, "stable", "0.12.0")
    assert shell.update_status.get() == shell.text["not_checked"]
    shell._update_checked(_candidate(channel="preview"), 3, "preview")
    assert shell.download_button.state == "normal"


@pytest.mark.parametrize("language", sorted(STRINGS))
def test_future_update_format_has_localized_manual_recovery(language) -> None:
    error = UpdateError("untrusted remote detail", code="unsupported_manifest",
                        stage="release_manifest")
    message = format_update_failure(error, STRINGS[language])
    assert "untrusted remote detail" not in message
    assert STRINGS[language]["update_error_unsupported_manifest"] in message


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


def test_backend_teardown_kills_and_reaps_a_child_that_ignores_terminate() -> None:
    from provelume.startup_process import ManagedStartup

    class HangingProcess(_Process):
        def __init__(self):
            super().__init__()
            self.waits = 0

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if not self.killed:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            self.exit_code = -9
            return -9

    process = HangingProcess()
    startup = ManagedStartup(Path("synthetic-unused"), SimpleNamespace(), lambda *_: [])
    startup.process = process
    # The same terminate/kill/reap guarantee now belongs to the owned worker,
    # rather than blocking the Tk callback for up to six seconds.
    startup._cleanup()

    assert process.terminated is True
    assert process.killed is True
    assert process.waits == 2
    assert process.poll() == -9


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
    assert set(STRINGS["en"]) == set(STRINGS["it"])
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
        "already_running",
    }
    for language in ("en", "it"):
        assert required <= STRINGS[language].keys()
        assert all(STRINGS[language][key].strip() for key in required)
        assert STRINGS[language]["network_notice"] != STRINGS[language]["install_notice"]
        for host in (
            "api.github.com",
            "github.com",
            "objects.githubusercontent.com",
            "release-assets.githubusercontent.com",
        ):
            assert host in STRINGS[language]["network_notice"]


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
@pytest.mark.parametrize("theme", ["system", "light", "dark"])
@pytest.mark.parametrize("dpi", [100, 200])
def test_windows_tk_layout_probe_is_offline_and_scrollable(
    tmp_path: Path, theme: str, dpi: int,
) -> None:
    output = tmp_path / "layout.json"
    # Each launcher owns one Tk interpreter. Probe that actual process lifetime:
    # repeated Tk()/destroy() in one Windows process can lose Tcl library state.
    probe = """
import sys
from pathlib import Path
from provelume.desktop import DesktopShell, write_ui_diagnostics

def unexpected_first_run(self):
    raise AssertionError("offline layout diagnostics must remain non-interactive")

DesktopShell.show_first_run = unexpected_first_run
write_ui_diagnostics(Path(sys.argv[1]), language="it", theme=sys.argv[2],
                     dpi_percent=int(sys.argv[3]), viewport_width=640, viewport_height=480)
"""
    subprocess.run(
        [sys.executable, "-c", probe, str(output), theme, str(dpi)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["language"] == "it"
    assert value["dpi_percent"] == dpi
    assert value["theme"] == theme
    assert value["controls_fit"] is True
    assert all(row["contrast"] >= 4.5 for row in value["appearance"].values())
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


def _windows_panel_probe(tmp_path: Path, mode: str) -> dict:
    # Match the launcher's process lifetime, as the layout probes above do.
    # Tcl initialization errors fail the probe rather than skipping its assertions.
    probe = """
import json
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from provelume import desktop
from provelume.desktop import DesktopShell, LauncherSettings, save_settings

directory, mode = Path(sys.argv[1]), sys.argv[2]
assert mode in {"missing", "blocked"}
settings = LauncherSettings(instance_path=str(directory / "Moved Instance – 日本"),
                            language="en", schema_version=3)
path = directory / "launcher.json"
save_settings(settings, path)
desktop.settings_path = lambda: path
entered, release = threading.Event(), threading.Event()
ui_thread = threading.get_ident()

def prepare(*_args, **_kwargs):
    assert threading.get_ident() != ui_thread
    entered.set()
    assert release.wait(4)
    raise RuntimeError("synthetic interrupted archive preparation")

if mode == "blocked":
    Path(settings.instance_path).mkdir()
    DesktopShell._ensure_instance = prepare
root = tk.Tk()
shell = None
try:
    shell = DesktopShell(root, initial_settings=settings, enable_native_tray=False,
                         enable_first_run_dialog=False, create_instance_if_missing=False)
    if mode == "missing":
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            root.update()
            if shell._startup is not None and shell._startup.done.is_set():
                shell._poll_startup()
                break
            time.sleep(0.01)
        assert shell._startup is not None and shell._startup.done.is_set()
        assert shell.instance_available is False
        assert str(shell.open_button.cget("state")) == "disabled"
        assert str(shell.stop_button.cget("state")) == "disabled"
        assert str(shell.choose_button.cget("state")) == "normal"
        assert str(shell.create_button.cget("state")) == "normal"
        assert "could not be found" in shell.status.get()
    else:
        deadline = time.monotonic() + 3
        while not entered.is_set() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert entered.is_set()
        ticks = []
        root.after(0, lambda: ticks.append("preparing"))
        root.update()
        assert ticks == ["preparing"] and not shell._startup.done.is_set()
        shell.close()
        assert not shell.closed and shell._startup.cancelled.is_set()
        root.after(0, lambda: ticks.append("waiting_for_cleanup"))
        root.update()
        assert ticks == ["preparing", "waiting_for_cleanup"]
finally:
    release.set()
    if shell is not None and shell._startup is not None:
        assert shell._startup.done.wait(2)
        shell._startup.thread.join(2)
        assert not shell._startup.thread.is_alive()
        assert shell._startup.process is None
    if shell is not None:
        shell.close()
        assert shell.closed
    else:
        root.destroy()
print(json.dumps({"mode": mode, "assertions": "PASS", "cleanup": "CONFIRMED"}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(tmp_path), mode],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.skipif(os.name != "nt", reason="real Tk recovery probe")
def test_windows_missing_persisted_instance_renders_recovery_shell(tmp_path: Path) -> None:
    assert _windows_panel_probe(tmp_path, "missing") == {
        "mode": "missing", "assertions": "PASS", "cleanup": "CONFIRMED",
    }


@pytest.mark.skipif(os.name != "nt", reason="real Tk initial preparation lifecycle")
def test_windows_panel_renders_and_quit_waits_for_initial_archive_io(tmp_path: Path) -> None:
    assert _windows_panel_probe(tmp_path, "blocked") == {
        "mode": "blocked", "assertions": "PASS", "cleanup": "CONFIRMED",
    }
