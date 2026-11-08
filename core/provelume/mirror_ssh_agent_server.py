"""Private local IPC, used inside the product's contained deadline-bounded worker."""

from __future__ import annotations

import ctypes
import os
import socket
import struct
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .migration_permissions import make_private
from .mirror_contract import require
from .mirror_ssh_agent import MAX_FRAME


class WindowsPipe:
    def __init__(self, *, deadline, stopped):
        from ctypes import wintypes as w

        from .migration_permissions import _private_descriptor

        self.deadline, self.stopped = deadline, stopped
        self.name = r"\\.\pipe\Provelume-Mirror-Auth-" + uuid4().hex
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_void_p

        class Overlapped(ctypes.Structure):
            _fields_ = [
                ("internal", ctypes.c_size_t),
                ("internal_high", ctypes.c_size_t),
                ("offset", w.DWORD),
                ("offset_high", w.DWORD),
                ("event", w.HANDLE),
            ]

        class Security(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("descriptor", pointer), ("inherit", w.BOOL)]

        self.overlapped = Overlapped
        api = self.api
        api.CreateNamedPipeW.argtypes = [
            w.LPCWSTR,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            pointer,
        ]
        api.CreateNamedPipeW.restype = w.HANDLE
        api.CreateEventW.argtypes, api.CreateEventW.restype = (
            [pointer, w.BOOL, w.BOOL, w.LPCWSTR],
            w.HANDLE,
        )
        api.ConnectNamedPipe.argtypes = [w.HANDLE, pointer]
        api.ConnectNamedPipe.restype = w.BOOL
        for name in ("ReadFile", "WriteFile"):
            function = getattr(api, name)
            function.argtypes = [w.HANDLE, pointer, w.DWORD, ctypes.POINTER(w.DWORD), pointer]
            function.restype = w.BOOL
        api.GetOverlappedResult.argtypes = [w.HANDLE, pointer, ctypes.POINTER(w.DWORD), w.BOOL]
        api.GetOverlappedResult.restype = w.BOOL
        api.WaitForSingleObject.argtypes, api.WaitForSingleObject.restype = (
            [w.HANDLE, w.DWORD],
            w.DWORD,
        )
        api.CancelIoEx.argtypes, api.CancelIoEx.restype = [w.HANDLE, pointer], w.BOOL
        api.CloseHandle.argtypes, api.CloseHandle.restype = [w.HANDLE], w.BOOL
        descriptor = ctypes.create_string_buffer(_private_descriptor()[0])
        security = Security(ctypes.sizeof(Security), ctypes.cast(descriptor, pointer), False)
        # First instance, overlapped I/O, byte stream, one client, no remote pipe
        # clients, and the existing protected owner-rights private DACL.
        self.handle = api.CreateNamedPipeW(
            self.name,
            3 | 0x40000000 | 0x00080000,
            8,
            1,
            MAX_FRAME + 4,
            MAX_FRAME + 4,
            1000,
            ctypes.byref(security),
        )
        require(self.handle not in (None, ctypes.c_void_p(-1).value), "ssh_agent_containment")

    def check(self):
        require(
            not self.stopped.is_set() and time.monotonic() <= self.deadline, "ssh_agent_deadline"
        )

    def operation(self, function, data=None, length=0):
        from ctypes import wintypes as w

        self.check()
        event = self.api.CreateEventW(None, True, False, None)
        require(event, "ssh_agent_containment")
        operation, count = self.overlapped(event=event), w.DWORD()
        try:
            if function == "connect":
                complete = self.api.ConnectNamedPipe(self.handle, ctypes.byref(operation))
            else:
                complete = getattr(self.api, function)(
                    self.handle, data, length, ctypes.byref(count), ctypes.byref(operation)
                )
            error = ctypes.get_last_error()
            if not complete and function == "connect" and error == 535:
                return 0  # ERROR_PIPE_CONNECTED before ConnectNamedPipe.
            require(complete or error == 997, "ssh_agent_pipe")
            if not complete:
                while self.api.WaitForSingleObject(event, 50) == 258:
                    self.check()
                require(
                    self.api.GetOverlappedResult(
                        self.handle, ctypes.byref(operation), ctypes.byref(count), False
                    ),
                    "ssh_agent_pipe",
                )
            return count.value
        finally:
            # An overlapped structure/event cannot be destroyed while I/O still
            # owns it. Cancel only this operation, then await its finite completion.
            self.api.CancelIoEx(self.handle, ctypes.byref(operation))
            self.api.GetOverlappedResult(
                self.handle, ctypes.byref(operation), ctypes.byref(count), True
            )
            self.api.CloseHandle(event)

    def connect(self):
        self.operation("connect")

    def recv(self, length):
        data = ctypes.create_string_buffer(length)
        count = self.operation("ReadFile", data, length)
        return data.raw[:count]

    def sendall(self, data):
        while data:
            buffer = ctypes.create_string_buffer(data)
            count = self.operation("WriteFile", buffer, len(data))
            require(count > 0, "ssh_agent_pipe")
            data = data[count:]

    def cancel(self):
        self.api.CancelIoEx(self.handle, None)

    def close(self):
        self.api.CloseHandle(self.handle)


class OwnedAgent:
    def __init__(self, protocol):
        self.protocol = protocol
        self.stopped = threading.Event()
        self.directory, self.listener, self.channel, self.worker = None, None, None, None
        self.endpoint, self.outcome = None, "NOT_CONNECTED"

    def __enter__(self):
        try:
            if os.name == "nt":
                self.channel = WindowsPipe(deadline=self.protocol.deadline, stopped=self.stopped)
                self.endpoint = self.channel.name
            else:
                self.directory = TemporaryDirectory(prefix="pv-agent-")
                root = Path(self.directory.name)
                make_private(root)
                self.endpoint = str(root / "agent.sock")
                self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.listener.bind(self.endpoint)
                os.chmod(self.endpoint, 0o600)
                self.listener.listen(1)
                self.listener.settimeout(0.1)
            self.worker = threading.Thread(target=self._serve, daemon=True)
            self.worker.start()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def check(self):
        require(
            not self.stopped.is_set() and time.monotonic() <= self.protocol.deadline,
            "ssh_agent_deadline",
        )

    def _read(self, length):
        data = bytearray()
        while len(data) < length:
            self.check()
            try:
                chunk = self.channel.recv(length - len(data))
            except TimeoutError:
                continue
            require(chunk, "ssh_agent_pipe")
            data.extend(chunk)
        return bytes(data)

    def _serve(self):
        try:
            if os.name == "nt":
                self.channel.connect()
            else:
                while self.channel is None:
                    self.check()
                    try:
                        self.channel, _address = self.listener.accept()
                        self.channel.settimeout(0.1)
                    except TimeoutError:
                        continue
            self.outcome = "CONNECTED"
            while not self.protocol.closed:
                size = struct.unpack(">I", self._read(4))[0]
                require(0 < size <= MAX_FRAME, "ssh_agent_request")
                response = self.protocol.handle(self._read(size))
                self.channel.sendall(struct.pack(">I", len(response)) + response)
                self.outcome = (
                    "SIGNED"
                    if self.protocol.signatures
                    else "BOUND"
                    if (self.protocol.session is not None)
                    else "CONNECTED"
                )
        except (OSError, ValueError):
            if not self.stopped.is_set() and self.outcome != "SIGNED":
                self.outcome = "REFUSED"
        finally:
            if self.channel is not None and os.name != "nt":
                self.channel.close()

    def __exit__(self, *_error):
        self.stopped.set()
        if self.channel is not None:
            if os.name == "nt":
                self.channel.cancel()
            else:
                self.channel.close()
        if self.listener is not None:
            self.listener.close()
        if self.worker is not None:
            self.worker.join(timeout=2)
            require(not self.worker.is_alive(), "ssh_agent_containment")
        if self.channel is not None and os.name == "nt":
            self.channel.close()
        if self.directory is not None:
            self.directory.cleanup()
        self.protocol.seed = b""
