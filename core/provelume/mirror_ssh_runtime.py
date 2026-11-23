"""Closed native SSH execution, pinned host keys and creation-time child ownership."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import time
from contextlib import ExitStack, contextmanager, nullcontext, suppress
from pathlib import Path
from uuid import uuid4

from .maintenance_local_files import (
    MaintenanceTargetError,
    open_local_file,
    pinned_parent,
    stream_digest,
)
from .migration_permissions import make_private
from .mirror_contract import MAX_MANIFEST_BYTES, MirrorError, require
from .mirror_ssh_agent import decode_public, public_blob
from .mirror_ssh_agent_process import AgentWorker
from .mirror_ssh_crypto import public_key
from .ocr_process import _terminate_process_tree

SSH_VERSION = b"OpenSSH_10.0p2 Debian-7+deb13u4"
WINDOWS_SSH_VERSION = b"OpenSSH_for_Windows_10.4p1 Win32-OpenSSH-GitHub, LibreSSL 4.3.3"
WINDOWS_SSH_FILES = {
    "ssh.exe": (1500960, "ee115a1b833261034dcb2e5b862e6571f6dcedc084c555ea0df45ae7fd42c5e0"),
    "libcrypto.dll": (
        1801032, "b4cbfd202d52ec0f094bfa328414c74b05b51234df95d2eb42e5fdb47160c9b5"
    ),
}
MAX_COMPONENT_BYTES = 16 * 1024 * 1024
RSYNC_VERSION = "3.5.2"
MAX_COMMAND_SECONDS = 30
MAX_OPERATION_SECONDS = 120
MAX_DIAGNOSTIC_BYTES = 64 * 1024
SUBSYSTEM = "provelume-mirror-v1"


def _unlink_temporary(path, *, deadline, windows):
    while True:
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError as error:
            # Windows may still report a sharing violation while terminated
            # native descendants release inherited file objects. Confirm actual
            # removal within the same total cleanup budget; never hide a residue.
            if not windows or getattr(error, "winerror", None) != 32:
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.01, remaining))


def configuration(value):
    require(
        type(value) is dict
        and set(value)
        == {
            "transport",
            "host",
            "port",
            "username",
            "host_key",
            "configuration_sha256",
            "namespace",
            "bandwidth_kib",
            "window_start_minute_utc",
            "window_end_minute_utc",
        }
        and value["transport"] == "rsync-ssh",
        "rsync_target",
    )
    require(
        type(value["host"]) is str
        and len(value["host"]) <= 253
        and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value["host"])
        and all(
            0 < len(part) <= 63 and not part.startswith("-") and not part.endswith("-")
            for part in value["host"].split(".")
        )
        and type(value["port"]) is int
        and 1 <= value["port"] <= 65535
        and type(value["username"]) is str
        and re.fullmatch(r"[a-z_][a-z0-9_.-]{0,63}", value["username"])
        and type(value["namespace"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", value["namespace"]),
        "rsync_target",
    )
    require(
        type(value["configuration_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", value["configuration_sha256"]),
        "rsync_target",
    )
    require(type(value["host_key"]) is str and len(value["host_key"]) <= 128, "ssh_host_key")
    try:
        blob = base64.b64decode(value["host_key"], validate=True)
    except ValueError:
        raise MirrorError("ssh_host_key") from None
    decode_public(blob)
    require(base64.b64encode(blob).decode("ascii") == value["host_key"], "ssh_host_key")
    require(
        type(value["bandwidth_kib"]) is int and 1 <= value["bandwidth_kib"] <= 102400,
        "rsync_bandwidth",
    )
    window = [value["window_start_minute_utc"], value["window_end_minute_utc"]]
    require(
        type(window) is list
        and len(window) == 2
        and all(type(item) is int for item in window)
        and 0 <= window[0] < window[1] <= 1440,
        "rsync_window",
    )
    return value


def window_open(target, instant):
    configuration(target)
    require(
        instant.utcoffset() is not None and instant.utcoffset().total_seconds() == 0, "rsync_window"
    )
    return (
        target["window_start_minute_utc"]
        <= instant.hour * 60 + instant.minute
        < target["window_end_minute_utc"]
    )


def environment(work):
    names = {"PATH", "SYSTEMROOT", "WINDIR"}
    value = {key: item for key, item in os.environ.items() if key.upper() in names}
    value.update(
        {
            "HOME": str(work),
            "USERPROFILE": str(work),
            "LANG": "C",
            "LC_ALL": "C",
            "TMPDIR": str(work),
            "TMP": str(work),
            "TEMP": str(work),
        }
    )
    if os.name == "nt":
        # Win32-OpenSSH initializes ProgramData before its stdio wrappers.
        # A missing value can exit255 without diagnostics, even for -V. Its
        # private replacement grants no access to the host's global SSH config.
        value["PROGRAMDATA"] = str(work)
    return value


class NativeSession:
    def __init__(self, work, *, deadline=None):
        self.work = Path(work)
        make_private(self.work)
        self.deadline = min(deadline or float("inf"), time.monotonic() + MAX_OPERATION_SECONDS)
        self.environment = environment(self.work)
        self.commands = 0

    def run(self, arguments, *, incoming=None, maximum=MAX_DIAGNOSTIC_BYTES, check=True,
            agent=None):
        require(
            type(arguments) is list
            and arguments
            and arguments[0]
            and all(type(item) is str and "\0" not in item for item in arguments),
            "rsync_command",
        )
        require(
            incoming is None
            or type(incoming) is bytes
            and len(incoming) <= MAX_MANIFEST_BYTES + 4096,
            "limit",
        )
        require(type(maximum) is int and 0 < maximum <= MAX_MANIFEST_BYTES + 4096, "limit")
        stop = min(self.deadline, time.monotonic() + MAX_COMMAND_SECONDS)
        require(time.monotonic() < stop and self.commands < 32, "deadline")
        self.commands += 1
        child_environment = ssh_environment(self.environment, agent)
        stamp = uuid4().hex
        source, stdout, stderr = [
            self.work / (stamp + suffix) for suffix in (".in", ".out", ".err")
        ]
        process = None
        try:
            if incoming is not None:
                source.write_bytes(incoming)
            with (
                (source if incoming is not None else Path(os.devnull)).open("rb") as reader,
                stdout.open("xb") as out,
                stderr.open("xb") as err,
            ):
                if os.name == "nt":
                    from .mirror_git_windows import WindowsGitProcess

                    process = WindowsGitProcess(
                        arguments,
                        cwd=self.work,
                        environment=child_environment,
                        incoming=reader,
                        output=out,
                        errors=err,
                    )
                else:
                    process = subprocess.Popen(
                        arguments,
                        cwd=self.work,
                        env=child_environment,
                        stdin=reader,
                        stdout=out,
                        stderr=err,
                        start_new_session=True,
                        close_fds=True,
                    )
                while process.poll() is None:
                    require(time.monotonic() < stop, "deadline")
                    require(
                        stdout.stat().st_size <= maximum
                        and stderr.stat().st_size <= MAX_DIAGNOSTIC_BYTES,
                        "rsync_output_limit",
                    )
                    time.sleep(0.01)
                require(
                    stdout.stat().st_size <= maximum
                    and stderr.stat().st_size <= MAX_DIAGNOSTIC_BYTES,
                    "rsync_output_limit",
                )
                require(not check or process.returncode == 0, "ssh_command_failed")
                return process.returncode, stdout.read_bytes(), stderr.read_bytes()
        except OSError:
            raise MirrorError("rsync_component_unavailable") from None
        finally:
            cleanup_stop = time.monotonic() + 2
            if process is not None:
                if os.name == "nt":
                    process.close(deadline=cleanup_stop)
                else:
                    if process.poll() is None:
                        _terminate_process_tree(process)
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
            for item in (source, stdout, stderr):
                _unlink_temporary(item, deadline=cleanup_stop, windows=os.name == "nt")

    def component(self, name, *, binary=None):
        if os.name == "nt" and name == "ssh":
            with windows_ssh_component(binary) as component:
                code, output, errors = self.run(
                    [component["path"], "-V"], maximum=4096, check=False
                )
                require(
                    code == 0 and not output
                    and errors in {WINDOWS_SSH_VERSION + b"\n", WINDOWS_SSH_VERSION + b"\r\n"},
                    "ssh_profile_not_qualified",
                )
            return component
        binary = str(binary) if binary is not None else shutil.which(name)
        require(binary is not None, "rsync_component_unavailable")
        info = Path(binary).stat()
        require(
            stat.S_ISREG(info.st_mode) and info.st_size <= MAX_COMPONENT_BYTES,
            "rsync_component_unavailable",
        )
        pin = nullcontext()
        if os.name == "nt" and name == "rsync":
            from .mirror_rsync_windows import pinned_components

            pin = pinned_components(binary)
        with pin:
            code, output, errors = self.run(
                [binary, "-V" if name == "ssh" else "--version"], check=False
            )
            digest = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
        require(code == 0, "rsync_profile_not_qualified")
        if name == "ssh":
            require(
                errors.startswith(SSH_VERSION + b", OpenSSL ") and not output,
                "ssh_profile_not_qualified",
            )
            version = SSH_VERSION.decode("ascii")
        else:
            require(
                output.splitlines()[0] == b"rsync  version 3.5.2  protocol version 33",
                "rsync_profile_not_qualified",
            )
            version = RSYNC_VERSION
        return {
            "path": binary,
            "version": version,
            "sha256": digest,
        }


@contextmanager
def windows_ssh_component(binary=None):
    binary = binary if binary is not None else shutil.which("ssh.exe")
    require(binary is not None, "rsync_component_unavailable")
    binary = Path(binary)
    require(binary.name.lower() == "ssh.exe" and binary.is_absolute(),
            "ssh_profile_not_qualified")
    try:
        with pinned_parent(binary) as (selected, _parent), ExitStack() as files:
            require(
                sorted(p.name.lower() for p in selected.parent.iterdir())
                == sorted(WINDOWS_SSH_FILES),
                "ssh_profile_not_qualified",
            )
            # Hold both files through the native launch. The Windows read
            # handles deny writes and replacement of these selected components.
            for name, (expected_size, expected_sha) in WINDOWS_SSH_FILES.items():
                stream = files.enter_context(open_local_file(selected.parent / name))
                digest, size = stream_digest(stream, expected_size)
                require(size == expected_size and digest == expected_sha,
                        "ssh_profile_not_qualified")
            yield {
                "path": str(selected),
                "version": WINDOWS_SSH_VERSION.decode("ascii"),
                "sha256": WINDOWS_SSH_FILES["ssh.exe"][1],
            }
    except MaintenanceTargetError as error:
        raise MirrorError(
            "rsync_component_unavailable" if error.code == "target_missing"
            else "ssh_profile_not_qualified"
        ) from None


def ssh_environment(base, agent):
    if os.name != "nt" or agent is None:
        return base
    # Win32 OpenSSH opens this device name verbatim via CreateFileW. The
    # filesystem path normalization used for IdentityFile would break it.
    require(
        type(agent) is str
        and re.fullmatch(r"\\\\\.\\pipe\\Provelume-Mirror-Auth-[0-9a-f]{32}", agent),
        "ssh_agent_containment",
    )
    return {**base, "SSH_AUTH_SOCK": agent}


def config_path(value):
    # OpenSSH parses the value as a configuration token even though no shell is used.
    require('"' not in value and "\n" not in value and "\r" not in value, "ssh_component_path")
    return '"' + value.replace("\\", "/") + '"'


def ssh_arguments(binary, target, work, agent):
    configuration(target)
    public = work / "identity.pub"
    known = work / "known_hosts"
    require(public.is_file() and known.is_file(), "ssh_credentials")
    options = {
        "BatchMode": "yes",
        "IdentitiesOnly": "yes",
        "IdentityAgent": "SSH_AUTH_SOCK" if os.name == "nt" else config_path(agent),
        "IdentityFile": config_path(str(public)),
        "UserKnownHostsFile": config_path(str(known)),
        "GlobalKnownHostsFile": "none",
        "StrictHostKeyChecking": "yes",
        "UpdateHostKeys": "no",
        "VerifyHostKeyDNS": "no",
        "HostKeyAlgorithms": "ssh-ed25519",
        "PubkeyAcceptedAlgorithms": "ssh-ed25519",
        "PreferredAuthentications": "publickey",
        "PasswordAuthentication": "no",
        "KbdInteractiveAuthentication": "no",
        "GSSAPIAuthentication": "no",
        "HostbasedAuthentication": "no",
        "NumberOfPasswordPrompts": "0",
        "ForwardAgent": "no",
        "ForwardX11": "no",
        "ClearAllForwardings": "yes",
        "ExitOnForwardFailure": "yes",
        "ProxyCommand": "none",
        "ProxyJump": "none",
        "ControlMaster": "no",
        "ControlPath": "none",
        "PermitLocalCommand": "no",
        "CanonicalizeHostname": "no",
        "ConnectionAttempts": "1",
        "ConnectTimeout": "10",
        "ServerAliveInterval": "5",
        "ServerAliveCountMax": "1",
        "RequestTTY": "no",
        "EscapeChar": "none",
        "LogLevel": "ERROR",
    }
    arguments = [binary, "-F", "none", "-T"]
    for key, value in options.items():
        arguments += ["-o", key + "=" + value]
    return arguments + [
        "-p",
        str(target["port"]),
        "-l",
        target["username"],
        "-s",
        target["host"],
        SUBSYSTEM,
    ]


def ssh_error(errors):
    if (
        b"Host key verification failed" in errors
        or b"REMOTE HOST IDENTIFICATION HAS CHANGED" in errors
    ):
        return "ssh_host_key"
    if b"Permission denied" in errors or b"Too many authentication failures" in errors:
        return "ssh_credentials"
    return "ssh_command_failed"


def ssh_call(session, target, seed, request):
    configuration(target)
    binary = session.component("ssh")
    work = session.work / ("ssh-" + uuid4().hex)
    work.mkdir(mode=0o700)
    make_private(work)
    identity = public_blob(public_key(seed))
    (work / "identity.pub").write_bytes(b"ssh-ed25519 " + base64.b64encode(identity) + b"\n")
    known_host = "[" + target["host"] + "]:" + str(target["port"])
    if target["port"] == 22:
        known_host = target["host"]
    (work / "known_hosts").write_text(
        known_host + " ssh-ed25519 " + target["host_key"] + "\n", encoding="ascii"
    )
    host = base64.b64decode(target["host_key"], validate=True)
    pinned = windows_ssh_component(binary["path"]) if os.name == "nt" else nullcontext(binary)
    with pinned as component, AgentWorker(
        seed, host_public_blob=host, username=target["username"], deadline=session.deadline
    ) as owned:
        require(binary == component, "ssh_profile_not_qualified")
        result = session.run(
            ssh_arguments(binary["path"], target, work, owned.endpoint),
            incoming=request,
            maximum=MAX_MANIFEST_BYTES + 4096,
            check=False,
            agent=owned.endpoint,
        )
        if result[0] != 0:
            raise MirrorError(ssh_error(result[2]))
    return result[1], {"component": binary, "agent": owned.report}
