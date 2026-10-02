from types import SimpleNamespace

import pytest

from provelume.catalog_registry import SUPPORTED_LANGUAGES
from provelume.desktop import DesktopShell
from provelume.shell_appearance import native_palette
from provelume.tray_queue import normalize_queue, queue_snapshot, queue_state
from provelume.windows_tray import TRAY_STATUS_LABELS, TrayState, WindowsTray, queue_text


@pytest.mark.parametrize(
    "field,state",
    [
        ("queued", "queued"),
        ("running", "running"),
        ("paused", "paused"),
        ("attention", "attention"),
    ],
)
def test_queue_state_uses_authoritative_counts_and_keeps_incomplete_visible(field, state):
    value = {"queued": 0, "running": 0, "paused": 0, "attention": 0, "complete": True}
    assert queue_state(value) == "idle"
    value[field] = 1
    assert queue_state(value) == state
    value["complete"] = False
    value["attention"] = None
    assert queue_state(value) == "degraded"


@pytest.mark.parametrize("language", sorted(SUPPORTED_LANGUAGES))
def test_queue_projection_is_textual_complete_and_localized(language):
    state = TrayState(
        language,
        "running",
        "http://127.0.0.1:44851",
        queue={
            "queued": 2,
            "running": 1,
            "paused": 3,
            "attention": 4,
            "complete": True,
        },
    ).normalized()
    assert all(str(n) in queue_text(state) for n in (1, 2, 3, 4))
    assert TRAY_STATUS_LABELS[language]["running"]
    state.queue["complete"] = False
    assert "4" not in queue_text(state)


@pytest.mark.parametrize(
    "queue",
    [
        {"queued": True},
        {"queued": -1},
        {"queued": 2**54},
        {"title": "synthetic private title"},
    ],
)
def test_invalid_or_content_bearing_projection_refused(queue):
    value = {"queued": 0, "running": 0, "paused": 0, "attention": 0, "complete": True, **queue}
    with pytest.raises(ValueError):
        normalize_queue(value)


def test_projection_preserves_incomplete_attention_and_scheduler_state(monkeypatch):
    from provelume import tray_queue

    model = SimpleNamespace(snapshot=lambda **kw: {"total": None, "complete": False})
    monkeypatch.setattr(tray_queue, "ActionCenter", lambda store: model)
    instance = SimpleNamespace(
        store=object(),
        scheduler_status=lambda: {
            "job_states": {
                "queued": 2,
                "retry_wait": 1,
                "running": 1,
                "pausing": 1,
                "paused": 3,
                "private_title": "synthetic excluded",
            }
        },
    )
    assert queue_snapshot(instance) == {
        "queued": 3,
        "running": 2,
        "paused": 3,
        "attention": None,
        "complete": False,
    }


def test_tray_refuses_arbitrary_status_or_nonlocal_tooltip():
    selected = TrayState(
        "ro", "synthetic private title", "https://user:secret@example.invalid"
    ).normalized()
    assert selected.service_status == "stopped"
    assert selected.endpoint == "http://127.0.0.1:44851"


def test_tray_actions_dispatch_existing_host_callbacks():
    calls = []
    root = SimpleNamespace(after=lambda delay, callback: callback())
    tray = WindowsTray(
        root,
        state=TrayState("de", "running", "http://127.0.0.1:44851"),
        open_interface=lambda: calls.append("open"),
        open_settings=lambda: calls.append("settings"),
        restart_service=lambda: calls.append("restart"),
        quit_application=lambda: calls.append("exit"),
        open_queue=lambda: calls.append("status"),
        pause_resume=lambda: calls.append("authoritative-controls"),
    )
    for action in (1, 5, 6, 2, 4):
        tray.exercise_action(action)
    assert calls == ["open", "status", "authoritative-controls", "settings", "exit"]
    with pytest.raises(ValueError):
        tray.exercise_action(9)


def test_close_to_tray_explains_once_and_cancel_keeps_window_visible():
    shell = DesktopShell.__new__(DesktopShell)
    shell.settings = SimpleNamespace(tray_enabled=True, language="en")
    shell.tray = object()
    shell.text = {"title": "Provelume"}
    shell.server_ready = True
    observed = []
    shell.root = SimpleNamespace(withdraw=lambda: observed.append("hidden"))
    shell._update_tray = lambda status: observed.append(status)
    shell._show_local_modal = lambda **kw: False
    shell.window_close()
    assert observed == []
    shell._show_local_modal = lambda **kw: True
    shell.window_close()
    assert observed == ["hidden", "running"]
    shell._show_local_modal = lambda **kw: pytest.fail("explained twice in this process")
    shell.window_close()
    assert observed == ["hidden", "running", "hidden", "running"]


def test_exit_stops_service_and_tray_and_is_idempotent():
    shell = DesktopShell.__new__(DesktopShell)
    observed = []
    shell.closed = False
    shell.stop_server = lambda: observed.append("service stopped")
    shell.tray = SimpleNamespace(stop=lambda: observed.append("tray stopped"))
    shell.root = SimpleNamespace(destroy=lambda: observed.append("application stopped"))
    shell.close()
    shell.close()
    assert observed == ["service stopped", "tray stopped", "application stopped"]


@pytest.mark.parametrize("choice", ["system", "light", "dark"])
def test_appearance_keeps_os_high_contrast(choice):
    assert native_palette(choice, system_dark=True, high_contrast=True) is None
    assert native_palette("system", system_dark=True) == native_palette("dark")
    assert native_palette("light", system_dark=True) != native_palette("dark")
