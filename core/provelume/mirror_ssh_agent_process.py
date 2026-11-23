"""Parent-owned agent worker; creation-time containment and one bounded secret pipe."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from .migration_permissions import make_private
from .mirror_contract import MirrorError, parse, raw, require
from .mirror_git_runtime import child_environment
from .mirror_ssh_agent_diagnostics import observe
from .ocr_process import _terminate_process_tree


class AgentWorker:
    def __init__(self, seed, *, host_public_blob, username, deadline=None):
        self.request = {
            "schema": "provelume-ssh-agent/v1",
            "seed": base64.b64encode(seed).decode("ascii"),
            "host_key": base64.b64encode(host_public_blob).decode("ascii"),
            "username": username,
            "seconds": 30,
        }
        self.deadline = min(deadline or float("inf"), time.monotonic() + 30)
        self.resources, self.process = ExitStack(), None
        self.closed, self.lock, self.stopped = False, threading.Lock(), threading.Event()
        self.endpoint, self.report = None, None
        self.output, self.writer, self.pid = None, None, None
        self.watch = None

    def __enter__(self):
        try:
            require(time.monotonic() < self.deadline, "deadline")
            root = Path(self.resources.enter_context(TemporaryDirectory(prefix="pv-agent-worker-")))
            make_private(root)
            self.output = root / "ready.json"
            diagnostics = root / "worker-output.bin"
            errors = root / "worker-errors.bin"
            stdout = self.resources.enter_context(diagnostics.open("xb"))
            stderr = self.resources.enter_context(errors.open("xb"))
            reader, self.writer = os.pipe()
            incoming = os.fdopen(reader, "rb")
            self.resources.callback(incoming.close)
            self.resources.callback(self.close_writer)
            environment = child_environment(root)
            environment["PYTHONNOUSERSITE"] = "1"
            environment["TMPDIR"] = str(root)
            if getattr(sys, "frozen", False):
                arguments = [sys.executable, "--internal-rsync-agent-worker", str(self.output)]
            else:
                arguments = [
                    sys.executable,
                    "-m",
                    "provelume.mirror_ssh_agent_worker",
                    str(self.output),
                ]
                environment["PYTHONPATH"] = str(Path(__file__).absolute().parent.parent)
            if os.name == "nt":
                from .mirror_git_windows import WindowsGitProcess

                self.process = WindowsGitProcess(
                    arguments,
                    cwd=root,
                    environment=environment,
                    incoming=incoming,
                    output=stdout,
                    errors=stderr,
                )
            else:
                self.process = subprocess.Popen(
                    arguments,
                    cwd=root,
                    env=environment,
                    stdin=incoming,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                    close_fds=True,
                )
            incoming.close()
            self.pid = self.process.pid
            self.request["seconds"] = min(30, self.deadline - time.monotonic())
            require(self.request["seconds"] > 0, "deadline")
            payload = raw(self.request, maximum=4096)
            # A complete request is <=4KiB; no producer thread or temporary
            # credential file. Child stdin is its own inherited pipe only.
            require(os.write(self.writer, payload) == len(payload), "ssh_agent_request")
            self.close_writer()
            self.request.clear()
            self.watch = threading.Thread(
                target=self._watch, args=(diagnostics, errors), daemon=True
            )
            self.watch.start()
            admission = min(self.deadline, time.monotonic() + 5)
            while not self.output.exists():
                require(
                    self.process is not None
                    and self.process.poll() is None
                    and time.monotonic() < admission,
                    "ssh_agent_unavailable",
                )
                time.sleep(0.01)
            report = parse(self.output.read_bytes())
            require(
                set(report) == {"schema", "pid", "endpoint"}
                and report["schema"] == "provelume-ssh-agent-ready/v1"
                and report["pid"] == self.pid,
                "ssh_agent_containment",
            )
            endpoint = report["endpoint"]
            require(type(endpoint) is str and len(endpoint) <= 512, "ssh_agent_containment")
            if os.name == "nt":
                require(
                    re.fullmatch(r"\\\\\.\\pipe\\Provelume-Mirror-Auth-[0-9a-f]{32}", endpoint),
                    "ssh_agent_containment",
                )
            else:
                require(
                    Path(endpoint).is_absolute() and Path(endpoint).is_relative_to(root),
                    "ssh_agent_containment",
                )
            self.endpoint = endpoint
            return self
        except BaseException:
            self.close()
            raise

    def _watch(self, output, errors):
        while not self.stopped.wait(0.05):
            try:
                exceeded = (
                    time.monotonic() >= self.deadline
                    or output.stat().st_size > 16384
                    or errors.stat().st_size > 16384
                )
            except OSError:
                exceeded = True
            if exceeded:
                self.stop_process()
                return

    def stop_process(self):
        with self.lock:
            if self.process is not None:
                if os.name == "nt":
                    self.process.close()
                else:
                    _terminate_process_tree(self.process)
                self.process = None

    def close_writer(self):
        if self.writer is not None:
            os.close(self.writer)
            self.writer = None

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stopped.set()
        try:
            if (
                self.output is not None
                and self.output.with_name(self.output.name + ".done").is_file()
            ):
                self.report = parse(self.output.with_name(self.output.name + ".done").read_bytes())
        finally:
            self.stop_process()
            if self.watch is not None and self.watch is not threading.current_thread():
                self.watch.join(timeout=1)
                require(not self.watch.is_alive(), "ssh_agent_containment")
            self.request.clear()
            self.resources.close()

    def __exit__(self, kind, *_error):
        if kind is None and self.output is not None:
            end = min(self.deadline, time.monotonic() + 1)
            while (
                not self.output.with_name(self.output.name + ".done").is_file()
                and self.process is not None
                and self.process.poll() is None
                and time.monotonic() < end
            ):
                time.sleep(0.01)
        evidence = None
        if kind is None and self.output is not None:
            code = self.process.poll() if self.process is not None else "STOPPED"
            worker_state = {
                None: "RUNNING", 0: "EXIT_0", 2: "EXIT_2", "STOPPED": "STOPPED"
            }.get(code, "OTHER_EXIT")
            completion = self.output.with_name(self.output.name + ".done")
            evidence = {
                "schema": "provelume-ssh-agent-completion-failure/v1",
                "worker_state": worker_state,
                "completion": "PRESENT" if completion.is_file() else "ABSENT",
                "prepared_completion": completion.with_name(completion.name + ".tmp").is_file(),
                "trace": observe(self.output.with_name("worker-errors.bin")),
                "raw_worker_output": "EXCLUDED",
            }
        self.close()
        if kind is None:
            try:
                require(
                    type(self.report) is dict
                    and self.report.get("schema") == "provelume-ssh-agent-result/v1"
                    and self.report.get("signatures") == 1
                    and self.report.get("host_bound") is True
                    and self.report.get("private_key_logged") is False,
                    "ssh_credentials",
                )
            except MirrorError as error:
                error.agent_evidence = evidence
                error.add_note("SSH_AGENT_COMPLETION=" + raw(evidence).decode("ascii").strip())
                raise
