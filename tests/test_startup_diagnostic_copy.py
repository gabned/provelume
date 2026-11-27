from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from provelume import __version__, desktop
from provelume.desktop import STRINGS, DesktopShell
from provelume.startup_process import startup_diagnostic_report

BUILD = {"version": __version__, "channel": "development", "commit": None,
         "identity_status": "development_build"}
EVENT = {"phase": "FAILED", "code": "readiness_timeout", "elapsed_ms": 75000,
         "exit_code": -1}


def test_report_is_an_isolated_bounded_observation_without_new_checks():
    events, build = [dict(EVENT) for _ in range(32)], dict(BUILD)
    report = startup_diagnostic_report(events, attempted=True, build=build)
    assert report["events"] == events and report["event_limit"] == 32
    assert report["trace_coverage"] == "bounded_tail"
    assert report["scope"] == "last_attempt_in_current_launcher_session"
    assert report["collection_network_used"] is report["checks_executed"] is False
    events[0]["code"] = "PRIVATE_SENTINEL"
    build["commit"] = "PRIVATE_SENTINEL"
    assert "PRIVATE_SENTINEL" not in json.dumps(report)


@pytest.mark.parametrize("change", [
    lambda e, b: e[0].update(path="PRIVATE_SENTINEL"),
    lambda e, b: e[0].update(code="PRIVATE_SENTINEL"),
    lambda e, b: e[0].update(phase="PRIVATE_SENTINEL"),
    lambda e, b: e[0].update(elapsed_ms=True),
    lambda e, b: e[0].update(elapsed_ms=-1),
    lambda e, b: e[0].update(elapsed_ms=2**63),
    lambda e, b: e[0].update(exit_code=False),
    lambda e, b: e[0].update(exit_code=2**32),
    lambda e, b: e.extend([dict(EVENT)] * 32),
    lambda e, b: b.update(instance_path="PRIVATE_SENTINEL"),
    lambda e, b: b.update(commit="PRIVATE_SENTINEL"),
    lambda e, b: b.update(channel=[]),
    lambda e, b: b.update(identity_status={}),
])
def test_private_unknown_or_unbounded_inputs_cannot_be_copied(change):
    events, build = [dict(EVENT)], dict(BUILD)
    change(events, build)
    with pytest.raises(ValueError, match="^startup diagnostics unavailable$"):
        startup_diagnostic_report(events, attempted=True, build=build)


@pytest.mark.parametrize("attempted", [False, True])
def test_no_trace_does_not_fabricate_a_startup_success(attempted):
    report = startup_diagnostic_report([], attempted=attempted, build=BUILD)
    assert report["attempt_present"] is attempted and report["events"] == []
    assert report["trace_coverage"] == ("bounded_tail" if attempted else "not_started")


def test_startup_dialog_copies_the_reviewed_trace_without_opening_the_instance(monkeypatch):
    shell = DesktopShell.__new__(DesktopShell)
    events = [dict(EVENT)]
    shell._startup = SimpleNamespace(diagnostic_snapshot=lambda: copy.deepcopy(events))
    shell._startup_diagnostics_build = dict(BUILD)
    shell.text = STRINGS["it"]
    captured = {}
    shell._show_local_modal = lambda **kw: captured.update(kw)
    monkeypatch.setattr(desktop, "current_about", lambda: pytest.fail("no package I/O on copy"))
    shell.show_startup_diagnostics()
    events[0]["code"] = "PRIVATE_SENTINEL"
    report = json.loads(captured["copy_text"])
    assert report["events"] == [EVENT]
    assert captured["confirm"] is False and captured["links"] == []
    assert shell.text["startup_details_help"] in captured["body"]


@pytest.mark.parametrize("clipboard_failure", [False, True])
def test_modal_requires_a_click_and_keeps_the_report_after_clipboard_failure(
    monkeypatch, clipboard_failure,
):
    widgets, values, actions = [], [], []

    class TclError(Exception):
        pass

    class Value:
        def __init__(self, *, value):
            self.value = value
            values.append(self)

        def set(self, value):
            self.value = value

    class Widget:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            self.content = ""
            widgets.append(self)

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

        def insert(self, index, text):
            self.content = text

        def configure(self, **kwargs):
            self.kwargs.update(kwargs)

    class Root:
        clipboard = "original clipboard"

        def clipboard_clear(self):
            actions.append("clear")
            if clipboard_failure:
                raise TclError("PRIVATE_SENTINEL")
            self.clipboard = ""

        def clipboard_append(self, text):
            actions.append("append")
            self.clipboard += text

        def wait_window(self, dialog):
            assert actions == [] and self.clipboard == "original clipboard"
            button = next(w for w in widgets if w.kwargs.get("text") == "Copy diagnostics")
            button.kwargs["command"]()
            assert any(w.content == "all 32 observed events" and
                       w.kwargs.get("state") == "disabled" for w in widgets)
            assert values[-1].value == STRINGS["en"][
                "startup_copy_failed" if clipboard_failure else "startup_copied"]
            assert "PRIVATE_SENTINEL" not in values[-1].value

    shell = DesktopShell.__new__(DesktopShell)
    shell.root, shell.text = Root(), STRINGS["en"]
    shell.tk = SimpleNamespace(Toplevel=Widget, Text=Widget, StringVar=Value, TclError=TclError)
    shell.ttk = SimpleNamespace(Frame=Widget, Label=Widget, Button=Widget, Scrollbar=Widget)
    monkeypatch.setattr(desktop, "_versioned_icon_path", lambda: None)
    payload = json.dumps(startup_diagnostic_report([EVENT], attempted=True, build=BUILD))
    shell._show_local_modal(title="Startup", body="all 32 observed events", links=[],
                            confirm=False, copy_text=payload)
    assert actions == (["clear"] if clipboard_failure else ["clear", "append"])
    assert shell.root.clipboard == ("original clipboard" if clipboard_failure else payload)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows Tk clipboard and modal lifecycle")
@pytest.mark.parametrize("language", ["en", "it"])
def test_windows_clipboard_survives_the_scrollable_diagnostic_dialog(language):
    probe = r'''
import json
import sys
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from provelume.desktop import DesktopShell, STRINGS

root = tk.Tk()
root.geometry("640x480")
shell = DesktopShell.__new__(DesktopShell)
shell.root, shell.tk, shell.ttk = root, tk, ttk
shell.text = STRINGS[sys.argv[1]]
events = [{"phase": "FAILED", "code": "readiness_timeout", "elapsed_ms": n}
          for n in range(32)]
shell._startup = SimpleNamespace(diagnostic_snapshot=lambda: [dict(x) for x in events])
observed, failures = [], []

def descendants(widget):
    return [child for w in widget.winfo_children() for child in [w, *descendants(w)]]

def inspect():
    dialogs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    try:
        assert len(dialogs) == 1
        widgets = descendants(dialogs[0])
        content, = [w for w in widgets if isinstance(w, tk.Text)]
        assert str(content.cget("state")) == "disabled"
        assert "31 ms" in content.get("1.0", "end")
        assert content.cget("yscrollcommand")
        next(w for w in widgets if isinstance(w, ttk.Button)
             and w.cget("text") == shell.text["startup_copy"]).invoke()
        observed.append(json.loads(root.clipboard_get()))
        next(w for w in widgets if isinstance(w, ttk.Button)
             and w.cget("text") == shell.text["close"]).invoke()
    except BaseException as error:
        failures.append(error)
        for dialog in dialogs:
            dialog.destroy()

try:
    root.after(0, inspect)
    watchdog = root.after(5000, root.destroy)
    shell.show_startup_diagnostics()
    root.after_cancel(watchdog)
    assert not failures, failures
    assert len(observed) == 1 and observed[0]["events"] == events
    assert json.loads(root.clipboard_get()) == observed[0]
finally:
    root.destroy()
'''
    result = subprocess.run(
        [sys.executable, "-c", probe, language],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
