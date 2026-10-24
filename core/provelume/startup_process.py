"""One owned startup worker; UI code consumes events, never blocks on its I/O."""

from __future__ import annotations

import os
import queue
import secrets
import subprocess
import threading
import time
from collections import deque
from contextlib import ExitStack, suppress
from pathlib import Path

from .maintenance_local_files import DirectoryCloseUnconfirmed, open_local_directory
from .service import ProvelumeInstance
from .shell_settings import ShellSettingsError, ShellSettingsManager, probe_port
from .startup_readiness import ERROR_CODES, StartupReadinessError, StartupSecrets, probe

PREPARATION_SECONDS = 10.0
SPAWN_SECONDS = 5.0
READINESS_SECONDS = 60.0
TOTAL_SECONDS = 75.0
PROBE_GAP_SECONDS = 0.25
MAX_PROBES = 240
CLEANUP_SECONDS = (4.0, 2.0)
_EXIT_ERRORS = {3: "startup_initialization_failed", 73: "bootstrap_failed",
                74: "startup_configuration_invalid",
                75: "startup_integrity_failed", 76: "startup_initialization_failed"}
_PHASES = {"PREPARING", "SPAWNING", "WAITING_READY", "RUNNING", "STOPPING",
           "STOP_UNCONFIRMED", "STOPPED", "FAILED"}
_DIAGNOSTIC_CODES = ERROR_CODES | {
    "spawn", "waiting", "operational", "endpoint_started", "endpoint_revision_changed",
    "cleanup_confirmed", "guard_close_failed", "endpoint_rolled_back",
    "endpoint_rollback_unconfirmed",
}


def _new_windows_control():
    if os.name == "nt":
        from .startup_windows import OwnedWindowsControl

        return OwnedWindowsControl()
    return None


class ManagedStartup:
    def __init__(self, instance: Path, manager: ShellSettingsManager, command_factory):
        self.instance = instance
        self.manager = manager
        self.command_factory = command_factory
        self.started_at = time.monotonic()
        self.total_deadline = self.started_at + TOTAL_SECONDS
        self.phase_deadline = min(self.total_deadline, self.started_at + PREPARATION_SECONDS)
        self.phase = "PREPARING"
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.events = queue.SimpleQueue()
        self.diagnostics = deque(maxlen=32)
        self._diagnostic_lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        self.port: int | None = None
        self.settings = None
        self.probes = 0
        self.accepted_at: float | None = None
        self.failure: str | None = None
        self.cancel_code = "cancelled"
        self.stop_requested_at: float | None = None
        self.cleanup_started_at: float | None = None
        self.rolled_back = False
        self._windows_control = None
        self._guard_close_unknown = False
        self.thread = threading.Thread(target=self._run, name="ProvelumeStartup", daemon=True)

    def start(self):
        self.thread.start()

    @property
    def cleanup_unconfirmed(self):
        since = self.stop_requested_at
        if self.cleanup_started_at is not None:
            since = (self.cleanup_started_at if since is None
                     else min(since, self.cleanup_started_at))
        return not self.done.is_set() and (
            self.phase == "STOP_UNCONFIRMED"
            or (since is not None and time.monotonic() - since >= sum(CLEANUP_SECONDS))
        )

    def request_stop(self, code="cancelled"):
        if not self.cancelled.is_set():
            self.cancel_code = code if code in ERROR_CODES else "cancelled"
            self.stop_requested_at = time.monotonic()
            self.cancelled.set()

    def _event(self, kind, **details):
        # Private event payloads can contain owned process/settings objects. The
        # shareable diagnostic ring below has an independent closed allow-list.
        self.events.put((kind, details))

    def _record(self, phase, code, *, exit_code=None):
        phase = phase if phase in _PHASES else "FAILED"
        code = code if code in _DIAGNOSTIC_CODES else "startup_initialization_failed"
        event = {"phase": phase, "code": code,
                 "elapsed_ms": max(0, int((time.monotonic() - self.started_at) * 1000))}
        if type(exit_code) is int:
            event["exit_code"] = exit_code
        with self._diagnostic_lock:
            self.diagnostics.append(event)

    def diagnostic_snapshot(self):
        with self._diagnostic_lock:
            return [dict(event) for event in self.diagnostics]

    def _checkpoint(self):
        if self.cancelled.is_set():
            raise StartupReadinessError(self.cancel_code)
        if time.monotonic() >= min(self.total_deadline, self.phase_deadline):
            code = {"PREPARING": "preparation_timeout", "SPAWNING": "bootstrap_failed"}.get(
                self.phase, "readiness_timeout"
            )
            raise StartupReadinessError(code)

    def _child_status(self):
        try:
            return self.process.poll()
        except OSError as exc:
            raise StartupReadinessError("startup_initialization_failed") from exc

    def _run(self):
        material = None
        root_guard = ExitStack()
        try:
            self._checkpoint()
            self.settings = self.manager.load().settings
            self.port = self.settings.endpoint_port
            # Refuse unsupported aliases before opening anything through them.
            with open_local_directory(self.instance):
                pass
            self._checkpoint()
            # Preserve the existing mandatory preparation/recovery, moved off Tk.
            instance = ProvelumeInstance(self.instance)
            self._checkpoint()
            _, identity = root_guard.enter_context(open_local_directory(self.instance))
            instance.store.validate()
            instance_id = instance.store.read_config()["instance"]["id"]
            self._checkpoint()
            if not probe_port(self.port)["available"]:
                raise StartupReadinessError("endpoint_occupied")
            self._checkpoint()
            material = StartupSecrets(secrets.token_hex(16), secrets.token_bytes(32))
            binding = material.instance_binding(instance_id, identity, self.port)
            self._event("prepared", settings=self.settings, port=self.port)
            self.phase = "SPAWNING"
            self.phase_deadline = min(self.total_deadline, time.monotonic() + SPAWN_SECONDS)
            self._record(self.phase, "spawn")
            self._windows_control = _new_windows_control()
            if self._windows_control is not None:
                try:
                    self._windows_control.prepare(material.stop_event_name())
                except OSError as exc:
                    raise StartupReadinessError("spawn_failed") from exc
            self._checkpoint()
            command = [*self.command_factory(self.instance, self.port), "--startup-bootstrap-stdin"]
            try:
                self.process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt"
                    else 0,
                )
            except OSError as exc:
                raise StartupReadinessError("spawn_failed") from exc
            self._event("spawned", process=self.process, port=self.port)
            if self._windows_control is not None:
                self._windows_control.assign(self.process)
            self._checkpoint()
            try:
                with self.process.stdin as stream:
                    stream.write(material.bootstrap_frame())
                    stream.flush()
            except (OSError, ValueError) as exc:
                raise StartupReadinessError("bootstrap_failed") from exc
            self._checkpoint()
            self.phase = "WAITING_READY"
            self.phase_deadline = min(self.total_deadline, time.monotonic() + READINESS_SECONDS)
            self._record(self.phase, "waiting")
            used_challenges = set()
            while self.probes < MAX_PROBES:
                self._checkpoint()
                exit_code = self._child_status()
                if exit_code is not None:
                    self._record(self.phase, "process_exited", exit_code=exit_code)
                    raise StartupReadinessError(_EXIT_ERRORS.get(exit_code, "process_exited"))
                challenge = secrets.token_hex(32)
                if challenge in used_challenges:
                    raise StartupReadinessError("readiness_binding_failed")
                used_challenges.add(challenge)
                self.probes += 1
                try:
                    value = probe(secrets=material, binding=binding, port=self.port,
                                  challenge=challenge, deadline=self.phase_deadline,
                                  cancelled=self.cancelled)
                except OSError:
                    value = None
                self._checkpoint()
                if self._child_status() is not None:
                    raise StartupReadinessError("process_exited")
                if value and value["backend_state"] == "failed":
                    raise StartupReadinessError("startup_" + value["reason"])
                if value and value["backend_state"] == "ready":
                    # Both the response and opened-root guard were valid at this
                    # observation. Release startup guards before normal operation;
                    # existing maintenance/lifecycle authorities remain unchanged.
                    root_guard.close()
                    self._checkpoint()
                    if self._child_status() is not None:
                        raise StartupReadinessError("process_exited")
                    if self.settings.restart_required:
                        try:
                            self.settings = self.manager.mark_endpoint_started(
                                self.port, expected_revision=self.settings.revision
                            )
                            self._record(self.phase, "endpoint_started")
                        except ShellSettingsError:
                            self._record(self.phase, "endpoint_revision_changed")
                    self._checkpoint()
                    self.accepted_at = time.monotonic()
                    self.phase = "RUNNING"
                    self._record(self.phase, "operational")
                    material = None
                    value = None
                    used_challenges.clear()
                    self._event("ready", process=self.process, port=self.port,
                                settings=self.settings)
                    while not self.cancelled.is_set():
                        try:
                            code = self.process.wait(timeout=0.1)
                        except subprocess.TimeoutExpired:
                            continue
                        self._record(self.phase, "process_exited", exit_code=code)
                        self.failure = "process_exited"
                        return
                    return
                remaining = min(self.total_deadline, self.phase_deadline) - time.monotonic()
                self.cancelled.wait(min(PROBE_GAP_SECONDS, max(0, remaining)))
            raise StartupReadinessError("readiness_timeout")
        except DirectoryCloseUnconfirmed:
            self._guard_close_unknown = True
            self.failure = "startup_initialization_failed"
            self._record(self.phase, "guard_close_failed")
        except StartupReadinessError as exc:
            self.failure = exc.code
            self._record(self.phase, exc.code)
        except (OSError, ValueError, KeyError, ShellSettingsError):
            self.failure = "startup_configuration_invalid"
            self._record(self.phase, self.failure)
        except Exception:
            # Neither exceptions, bootstrap frames, raw stderr nor locals are
            # diagnostic payloads. The owned worker still performs its cleanup.
            self.failure = "startup_initialization_failed"
            self._record(self.phase, self.failure)
        finally:
            material = None
            self.cleanup_started_at = time.monotonic()
            self.phase = "STOPPING"
            self._cleanup()
            if self.process is not None and self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except (OSError, ValueError):
                    self._record("STOPPING", "bootstrap_failed")
            try:
                root_guard.close()
            except DirectoryCloseUnconfirmed:
                self._guard_close_unknown = True
                self.failure = "startup_initialization_failed"
                self._record("STOPPING", "guard_close_failed")
            except (OSError, ValueError):
                self.failure = self.failure or "startup_initialization_failed"
                self._record("STOPPING", "guard_close_failed")
            self._close_windows_control()
            if self._guard_close_unknown:
                self.phase = "STOP_UNCONFIRMED"
                self._record(self.phase, "stop_unconfirmed")
                self._event("unconfirmed")
                # Descriptor identity after an ambiguous OS close is unsafe to
                # retry. Keep the owner and block replacement until the operator
                # resolves this unsupported OS condition; never close a reused fd.
                while self._guard_close_unknown:
                    time.sleep(0.25)
            if (self.failure not in {None, "cancelled"} and self.settings is not None
                    and self.settings.restart_required
                    and self.settings.last_good_port != self.settings.endpoint_port):
                try:
                    self.settings = self.manager.rollback_endpoint(
                        expected_revision=self.settings.revision
                    )
                    self.rolled_back = True
                    self._record("STOPPING", "endpoint_rolled_back")
                except (OSError, ValueError, ShellSettingsError):
                    self._record("STOPPING", "endpoint_rollback_unconfirmed")
            self.phase = "FAILED" if self.failure not in {None, "cancelled"} else "STOPPED"
            self._event("finished", code=self.failure, process=self.process, port=self.port,
                        settings=self.settings, rolled_back=self.rolled_back)
            self.done.set()

    def _close_windows_control(self):
        if self._windows_control is None:
            return
        while True:
            try:
                self._windows_control.close()
                return
            except OSError:
                self.phase = "STOP_UNCONFIRMED"
                if self.failure in {None, "cancelled"}:
                    self.failure = "startup_initialization_failed"
                self._record(self.phase, "guard_close_failed")
                self._event("unconfirmed")
                time.sleep(0.25)

    def _cleanup(self):
        process = self.process
        if process is None:
            return
        if self._windows_control is not None:
            self._cleanup_windows(process)
            return

        def exited():
            try:
                return type(process.poll()) is int
            except OSError:
                return False

        if exited():
            return
        self.phase = "STOPPING"
        self._event("stopping")
        with suppress(OSError):
            process.terminate()
        for index, timeout in enumerate(CLEANUP_SECONDS):
            if index:
                with suppress(OSError):
                    process.kill()
            try:
                process.wait(timeout=timeout)
                self._record("STOPPING", "cleanup_confirmed")
                return
            except subprocess.TimeoutExpired:
                continue
            except OSError:
                if exited():
                    return
        self.phase = "STOP_UNCONFIRMED"
        self._record(self.phase, "stop_unconfirmed")
        self._event("unconfirmed")
        # Keep ownership, the worker and its resources. Never turn a still-live
        # child into STOPPED or permit a concurrent retry after the 4+2s budget.
        while not exited():
            try:
                process.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                continue
            except OSError:
                time.sleep(0.25)
        self._record("STOPPING", "cleanup_confirmed")

    def _cleanup_windows(self, process):
        control = self._windows_control
        self.phase = "STOPPING"
        self._event("stopping")
        with suppress(OSError):
            control.request_stop()
        reaped = False

        def complete(timeout):
            nonlocal reaped
            if not reaped:
                try:
                    process.wait(timeout=timeout)
                    reaped = True
                except (subprocess.TimeoutExpired, OSError):
                    pass
            try:
                return reaped and control.empty()
            except OSError:
                return False

        for index, seconds in enumerate(CLEANUP_SECONDS):
            if index:
                with suppress(OSError):
                    control.terminate()
                # This is the retained owned process handle, not a PID/name lookup.
                with suppress(OSError):
                    process.kill()
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if complete(min(0.1, max(0, deadline - time.monotonic()))):
                    self._record("STOPPING", "cleanup_confirmed")
                    return
                if reaped and index == 0:
                    break  # Remaining descendants require the scoped Job escalation.
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        self.phase = "STOP_UNCONFIRMED"
        self._record(self.phase, "stop_unconfirmed")
        self._event("unconfirmed")
        while not complete(0.25):
            time.sleep(0.1)
        self._record("STOPPING", "cleanup_confirmed")
