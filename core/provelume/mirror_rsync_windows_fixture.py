"""Loopback bridge to an owned Linux SSH fixture on a disposable Windows runner."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import threading
from contextlib import contextmanager, suppress
from pathlib import Path

from .mirror_contract import require

DOCKER_SOCKET = "unix:///run/provelume-concordia/docker.sock"
_CHUNK = 65536
_BRIDGE = """\
import os, socket, sys, threading

connection = socket.create_connection(('127.0.0.1', 2222), timeout=5)
connection.settimeout(None)

def send():
    try:
        while data := os.read(0, 65536):
            connection.sendall(data)
    except OSError:
        pass
    finally:
        try:
            connection.shutdown(socket.SHUT_WR)
        except OSError:
            pass

threading.Thread(target=send, daemon=True).start()
with connection:
    while data := connection.recv(65536):
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
"""


class WindowsFixture:
    def __init__(self, distribution, expected_head):
        require(os.name == "nt", "rsync_fixture_platform")
        require(
            re.fullmatch(r"Provelume-Concordia-[0-9a-f]{12}", distribution)
            and re.fullmatch(r"[0-9a-f]{40}", expected_head),
            "rsync_fixture_identity",
        )
        windows = Path(os.environ.get("SYSTEMROOT", ""))
        wsl = windows / "System32/wsl.exe"
        require(windows.is_absolute() and wsl.is_file(), "rsync_fixture_wsl")
        self._command = [str(wsl), "--distribution", distribution, "--user", "root", "--exec"]
        self._environment = {
            name: os.environ[name]
            for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE")
            if name in os.environ
        }
        admitted = subprocess.run(
            [*self._command, "/bin/cat", "/etc/provelume-concordia-fixture"],
            env=self._environment,
            capture_output=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        require(
            admitted.returncode == 0 and admitted.stdout == expected_head.encode() + b"\n",
            "rsync_fixture_identity",
        )

    def _docker_command(self, *arguments):
        return [*self._command, "/usr/bin/docker", "--host=" + DOCKER_SOCKET, *arguments]

    def docker(self, *arguments, incoming=None, check=True):
        result = subprocess.run(
            self._docker_command(*arguments),
            env=self._environment,
            input=incoming,
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        require(
            len(result.stdout) <= 2 * 1024 * 1024 and len(result.stderr) <= 65536,
            "rsync_fixture_limit",
        )
        require(not check or result.returncode == 0, "rsync_fixture_command")
        return result

    @contextmanager
    def endpoint(self, container, address, port):
        require(
            re.fullmatch(r"concordia-rsync-[0-9a-f]{12}", container)
            and re.fullmatch(r"172\.(?:[0-9]{1,3}\.){2}[0-9]{1,3}", address)
            and port == 2222,
            "rsync_fixture_network",
        )
        command = self._docker_command(
            "exec", "-i", container, "/opt/python/bin/python3.12", "-c", _BRIDGE
        )

        def start():
            return subprocess.Popen(
                command,
                env=self._environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

        with _endpoint(start) as selected:
            yield selected


def _close_socket(connection):
    with suppress(OSError):
        connection.shutdown(socket.SHUT_RDWR)
    connection.close()


def _connection(connection, start, stop, errors):
    process = None
    upstream = None
    try:
        process = start()

        def send():
            try:
                while not stop.is_set() and (chunk := connection.recv(_CHUNK)):
                    process.stdin.write(chunk)
                    process.stdin.flush()
            except OSError:
                pass
            finally:
                with suppress(OSError):
                    process.stdin.close()

        upstream = threading.Thread(target=send, daemon=True)
        upstream.start()
        while not stop.is_set() and (chunk := process.stdout.read1(_CHUNK)):
            connection.sendall(chunk)
    except OSError:
        if process is None and not stop.is_set():
            errors.append("START_FAILED")
    finally:
        _close_socket(connection)
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    errors.append("PROCESS_NOT_REAPED")
            process.stdout.close()
        if upstream is not None:
            upstream.join(5)
            if upstream.is_alive():
                errors.append("PIPE_WORKER_NOT_REAPED")


@contextmanager
def _endpoint(start):
    stop = threading.Event()
    active = []
    errors = []
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        server.settimeout(0.1)

        def accept():
            while not stop.is_set():
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    if not stop.is_set():
                        errors.append("LISTENER_FAILED")
                    break
                active[:] = [item for item in active if item[1].is_alive()]
                if len(active) >= 4:
                    _close_socket(connection)
                    errors.append("CONNECTION_LIMIT")
                    continue
                worker = threading.Thread(
                    target=_connection, args=(connection, start, stop, errors), daemon=True
                )
                active.append((connection, worker))
                worker.start()

        listener = threading.Thread(target=accept, daemon=True)
        listener.start()
        try:
            yield server.getsockname()
        finally:
            stop.set()
            listener.join(5)
            for connection, _ in active:
                _close_socket(connection)
            for _, worker in active:
                worker.join(15)
            require(
                not listener.is_alive()
                and not any(worker.is_alive() for _, worker in active)
                and not errors,
                "rsync_fixture_wsl_cleanup",
            )
