from __future__ import annotations

import io
import queue
import subprocess
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from provelume import startup_process as module
from provelume.desktop import STRINGS, DesktopShell
from provelume.shell_settings import ShellSettingsStale
from provelume.startup_readiness import StartupReadinessError, read_bootstrap


class Clock:
    value = 0.0

    def advance(self, amount):
        self.value += amount


class Cancel:
    def __init__(self, clock):
        self.clock = clock
        self.flag = False

    def set(self):
        self.flag = True

    def is_set(self):
        return self.flag

    def wait(self, timeout):
        if not self.flag:
            self.clock.advance(timeout)
        return self.flag


class Pipe(io.BytesIO):
    captured = b""

    def close(self):
        if not self.closed:
            self.captured = self.getvalue()
        super().close()


class Process:
    def __init__(self, harness):
        self.h = harness
        self.stdin = Pipe()
        self.code = None
        self.terminated = 0
        self.killed = 0
        self.waits = []

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated += 1
        if not self.h.hold_cleanup:
            self.code = 0

    def kill(self):
        self.killed += 1
        if not self.h.hold_cleanup:
            self.code = -9

    def wait(self, timeout):
        self.waits.append(timeout)
        if self.code is not None:
            return self.code
        if self.h.hold_cleanup:
            if len(self.waits) > 2 and self.h.release.wait(0.01):
                self.code = -9
                return self.code
        elif self.h.startup.phase == "RUNNING":
            self.h.startup.request_stop()
        raise subprocess.TimeoutExpired("synthetic-owned-child", timeout)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    h = SimpleNamespace(
        clock=Clock(),
        prepare_delay=0,
        spawn_delay=0,
        probe_delay=0,
        mode="ready",
        popen_calls=[],
        probe_calls=0,
        guards=0,
        hold_cleanup=False,
        release=threading.Event(),
        unconfirmed=threading.Event(),
        on_spawn=None,
        on_prepare=None,
    )
    monkeypatch.setattr(module.time, "monotonic", lambda: h.clock.value)

    @contextmanager
    def directory(path):
        h.guards += 1
        try:
            yield path, "posix.file-id.v1:" + "12" * 16
        finally:
            h.guards -= 1

    def instance(_path):
        if h.on_prepare:
            h.on_prepare()
        h.clock.advance(h.prepare_delay)
        return SimpleNamespace(
            store=SimpleNamespace(
                validate=lambda: None, read_config=lambda: {"instance": {"id": "inst_synthetic"}}
            )
        )

    settings = SimpleNamespace(endpoint_port=44851, restart_required=False, revision=0)
    manager = SimpleNamespace(load=lambda: SimpleNamespace(settings=settings))
    monkeypatch.setattr(module, "ProvelumeInstance", instance)
    monkeypatch.setattr(module, "open_local_directory", directory)
    monkeypatch.setattr(module, "probe_port", lambda _port: {"available": True})
    # These are deterministic lifecycle tests. Real Windows Job/event behavior
    # has separate native tests and the installed transport smoke.
    monkeypatch.setattr(module, "_new_windows_control", lambda: None)
    h.startup = module.ManagedStartup(tmp_path, manager, lambda *_: ["synthetic-child"])
    h.startup.cancelled = Cancel(h.clock)
    h.process = Process(h)

    def spawn(command, **options):
        h.popen_calls.append((command, options))
        if h.on_spawn:
            h.on_spawn()
        h.clock.advance(h.spawn_delay)
        return h.process

    def probe(**values):
        h.probe_calls += 1
        h.clock.advance(h.probe_delay)
        assert read_bootstrap(io.BytesIO(h.process.stdin.captured)) == values["secrets"]
        if h.mode == "unavailable":
            raise OSError("synthetic unavailable transport")
        if h.mode == "binding_failed":
            raise StartupReadinessError("readiness_binding_failed")
        return {"backend_state": "ready" if h.mode == "ready" else "starting"}

    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    monkeypatch.setattr(module, "probe", probe)
    original_event = h.startup._event

    def event(kind, **details):
        original_event(kind, **details)
        if kind == "unconfirmed":
            h.unconfirmed.set()

    h.startup._event = event
    return h


def events(startup):
    result = []
    while True:
        try:
            result.append(startup.events.get_nowait())
        except queue.Empty:
            return result


def test_healthy_worker_owns_pipe_child_and_only_one_serial_probe(harness):
    h = harness
    h.startup._run()
    assert h.startup.done.is_set() and h.startup.phase == "STOPPED"
    assert h.startup.failure is None and h.probe_calls == 1
    assert h.process.terminated == 1 and h.process.stdin.closed and h.guards == 0
    assert len(h.popen_calls) == 1
    command, options = h.popen_calls[0]
    assert command == ["synthetic-child", "--startup-bootstrap-stdin"]
    assert options["close_fds"] is True and "env" not in options
    assert options["stdin"] == subprocess.PIPE and options["stderr"] == subprocess.DEVNULL
    assert [e[0] for e in events(h.startup)] == [
        "prepared",
        "spawned",
        "ready",
        "stopping",
        "finished",
    ]


@pytest.mark.parametrize(
    ("phase", "code"),
    [
        ("prepare", "preparation_timeout"),
        ("spawn", "bootstrap_failed"),
        ("probe", "readiness_timeout"),
    ],
)
def test_late_phase_result_cannot_publish_ready_and_child_is_reconciled(harness, phase, code):
    h = harness
    if phase == "prepare":
        h.prepare_delay = 10.01
    elif phase == "spawn":
        h.spawn_delay = 5.01
    else:
        h.probe_delay = 60.01
    h.startup._run()
    assert h.startup.failure == code and h.startup.phase == "FAILED"
    assert h.startup.done.is_set() and h.guards == 0
    assert "ready" not in [e[0] for e in events(h.startup)]
    if phase == "prepare":
        assert not h.popen_calls
    else:
        assert h.process.poll() is not None and h.process.stdin.closed


@pytest.mark.parametrize("mode", ["starting", "unavailable"])
def test_unused_phase_time_does_not_extend_readiness_or_allow_more_than_240_probes(harness, mode):
    h = harness
    h.mode = mode
    h.startup._run()
    assert h.startup.failure == "readiness_timeout"
    assert h.probe_calls == 240 and h.clock.value == 60
    assert h.process.terminated == 1 and h.startup.total_deadline == 75


def test_cancel_during_spawn_reaps_late_child_closes_pipe_and_never_accepts_ready(harness):
    h = harness
    h.on_spawn = h.startup.request_stop
    h.startup._run()
    assert h.startup.failure == "cancelled" and h.startup.done.is_set()
    assert h.process.terminated == 1 and h.process.stdin.closed and h.probe_calls == 0
    assert "ready" not in [e[0] for e in events(h.startup)]


def test_bad_binding_has_no_health_fallback_and_diagnostics_have_a_closed_allowlist(harness):
    h = harness
    h.mode = "binding_failed"
    h.startup._run()
    assert h.probe_calls == 1 and h.startup.failure == "readiness_binding_failed"
    h.startup._record("arbitrary phase", "secret /synthetic/private/path")
    diagnostic = str(h.startup.diagnostic_snapshot())
    assert "secret" not in diagnostic and str(h.startup.instance) not in diagnostic
    assert "startup_initialization_failed" in diagnostic
    assert str(StartupReadinessError("private raw error")) == "startup_initialization_failed"


def test_newer_endpoint_revision_is_neither_marked_good_nor_rolled_back(harness):
    h = harness
    settings = h.startup.manager.load().settings
    settings.restart_required = True
    settings.last_good_port = 44852
    calls = []

    def stale_mark(port, *, expected_revision):
        calls.append((port, expected_revision))
        raise ShellSettingsStale("synthetic concurrent preference edit")

    h.startup.manager.mark_endpoint_started = stale_mark
    h.startup.manager.rollback_endpoint = lambda **_: pytest.fail(
        "rollback after successful readiness"
    )
    h.startup._run()
    assert calls == [(44851, 0)]
    assert h.startup.failure is None and h.startup.done.is_set()
    assert "endpoint_revision_changed" in {e["code"] for e in h.startup.diagnostic_snapshot()}


def test_failure_preserves_stale_rollback_instead_of_overwriting_new_preferences(harness):
    h = harness
    settings = h.startup.manager.load().settings
    settings.restart_required = True
    settings.last_good_port = 44852
    h.mode = "binding_failed"

    def stale_rollback(*, expected_revision):
        assert expected_revision == 0
        raise ShellSettingsStale("synthetic newer preference revision")

    h.startup.manager.rollback_endpoint = stale_rollback
    h.startup._run()
    assert h.startup.failure == "readiness_binding_failed"
    assert not h.startup.rolled_back and h.startup.done.is_set()
    assert "endpoint_rollback_unconfirmed" in {e["code"] for e in h.startup.diagnostic_snapshot()}


class Value:
    def set(self, value):
        self.value = value


class Button:
    def configure(self, **values):
        self.state = values["state"]


class Root:
    destroyed = False

    def after(self, _delay, _callback):
        pass

    def destroy(self):
        self.destroyed = True


def shell_for(startup):
    shell = DesktopShell.__new__(DesktopShell)
    shell._startup = startup
    shell._startup_poll_scheduled = False
    shell._startup_status_on_finish = "stopped"
    shell._close_requested = False
    shell._restart_after_stop = False
    shell._pending_instance = None
    shell.closed = False
    shell.root = Root()
    shell.tray = None
    shell.status = Value()
    shell.text = STRINGS["en"]
    shell.settings = startup.manager.load().settings
    shell.instance = startup.instance
    shell.instance_available = True
    shell.server = startup.process
    shell.server_port = startup.port
    shell.server_ready = False
    shell.open_target = None
    shell.open_button = Button()
    shell.stop_button = Button()
    return shell


def test_unconfirmed_cleanup_keeps_owner_resources_and_blocks_restart_and_quit(harness):
    h = harness
    h.mode = "binding_failed"
    h.hold_cleanup = True
    h.startup.start()
    try:
        assert h.unconfirmed.wait(2)
        assert not h.startup.done.is_set() and h.guards == 1
        shell = shell_for(h.startup)
        shell._poll_startup()
        assert shell.status.value == STRINGS["en"]["startup_stop_unconfirmed"]
        shell.restart_server()
        shell.start_server(open_target="/")
        shell.close()
        assert not shell.closed and not shell.root.destroyed
        assert not shell._restart_after_stop and len(h.popen_calls) == 1
        assert h.process.waits[:2] == [4.0, 2.0]
    finally:
        h.release.set()
        assert h.startup.done.wait(2)
    shell._poll_startup()
    assert shell.closed and shell.root.destroyed
    assert h.guards == 0 and h.process.stdin.closed


def test_failed_native_control_preparation_retains_unconfirmed_handles_before_spawn(
    harness, monkeypatch
):
    from provelume import startup_windows as windows

    h = harness
    # Controlled API model only; native Windows behavior has separate tests.
    kernel = SimpleNamespace(
        CreateEventW=lambda *_: 11,
        CreateJobObjectW=lambda *_: 12,
        SetInformationJobObject=lambda *_: 0,
        CloseHandle=lambda *_: int(h.release.is_set()),
    )
    control = windows.OwnedWindowsControl()
    monkeypatch.setattr(windows, "_api", lambda: kernel)
    monkeypatch.setattr(windows.c, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(module, "_new_windows_control", lambda: control)
    h.startup.start()
    try:
        assert h.unconfirmed.wait(2)
        assert not h.startup.done.is_set() and not h.popen_calls
        assert h.startup._windows_control is control
        assert control._event == 11 and control._job == 12
        shell = shell_for(h.startup)
        shell._poll_startup()
        shell.restart_server()
        shell.start_server(open_target="/")
        shell.close()
        assert not shell.closed and not shell.root.destroyed and not h.popen_calls
    finally:
        h.release.set()
        assert h.startup.done.wait(2)
    assert control._event is None and control._job is None
    assert h.startup.failure == "spawn_failed"
    shell._poll_startup()
    assert shell.closed and shell.root.destroyed


def test_blocked_preparation_remains_owned_after_deadline_and_cannot_spawn_a_late_child(harness):
    h = harness
    entered = threading.Event()

    def prepare():
        entered.set()
        assert h.release.wait(2)

    h.on_prepare = prepare
    h.startup.start()
    try:
        assert entered.wait(2)
        shell = shell_for(h.startup)
        h.clock.advance(10.01)
        shell._poll_startup()
        assert h.startup.cancel_code == "preparation_timeout"
        h.clock.advance(6.01)
        shell._poll_startup()
        shell.restart_server()
        shell.close()
        assert not shell.closed and not shell._restart_after_stop and not h.popen_calls
        assert not h.startup.done.is_set()
    finally:
        h.release.set()
        assert h.startup.done.wait(2)
    shell._poll_startup()
    assert shell.closed and not h.popen_calls
    assert h.startup.failure == "preparation_timeout"


def test_unknown_process_observation_is_not_treated_as_exited_or_ready(harness):
    h = harness
    h.hold_cleanup = True

    def unknown_poll():
        raise OSError("synthetic process observation unavailable")

    h.process.poll = unknown_poll
    h.startup.start()
    try:
        assert h.unconfirmed.wait(2)
        assert not h.startup.done.is_set() and h.guards == 1
        assert h.probe_calls == 0
    finally:
        h.release.set()
        assert h.startup.done.wait(2)
    assert h.startup.failure == "startup_initialization_failed"
    assert h.process.stdin.closed and h.guards == 0
