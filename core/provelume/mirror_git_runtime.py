"""Bounded optional Git processes. No process is run by construction or status."""

from __future__ import annotations

import os
import re
import shutil
import signal
import stat
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from .mirror_contract import MAX_FILE_BYTES, MAX_MANIFEST_BYTES, MirrorError, require, sha
from .ocr_process import _terminate_process_tree

MAX_OPERATION_SECONDS = 120
MAX_COMMAND_SECONDS = 30
MAX_DIAGNOSTIC_BYTES = 64 * 1024
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OBJECT_BYTES = 512 * 1024 * 1024
MAX_OBJECT_FILES = 10_000
CANDIDATE_GIT_VERSIONS = frozenset({"2.52.0", "2.56.0.windows.4"})


def child_environment(work):
    # Preserve host proxy/CA trust; remove ambient Git, SSH, trace and helper settings.
    names = {
        "PATH",
        "HOME",
        "SYSTEMROOT",
        "WINDIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in names}
    env.update(
        {
            "LANG": "C",
            "LC_ALL": "C",
            "TEMP": str(work),
            "TMP": str(work),
            "TMPDIR": str(work),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "false",
            "SSH_ASKPASS": "false",
            "GIT_ALLOW_PROTOCOL": "file:https",
            "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_DEFAULT_HASH": "sha1",
        }
    )
    return env


def tree_storage_bound(root):
    count, size = 0, 0
    if not root.exists():
        return
    require(not root.is_symlink() and not root.is_junction(), "unsafe_git_storage")
    for item in root.rglob("*"):
        require(not item.is_symlink() and not item.is_junction(), "unsafe_git_storage")
        info = item.stat()
        if stat.S_ISDIR(info.st_mode):
            continue
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe_git_storage")
        count += 1
        size += info.st_size
        require(count <= MAX_OBJECT_FILES and size <= MAX_OBJECT_BYTES, "git_storage_limit")


class GitSession:
    def __init__(self, work, *, deadline=None, inherited_directories=()):
        self.work = Path(work)
        self.deadline = min(deadline or float("inf"), time.monotonic() + MAX_OPERATION_SECONDS)
        self.repository = self.work / "repository.git"
        self.empty_hooks = self.work / "empty-hooks"
        self.empty_hooks.mkdir(exist_ok=True)
        self.environment = child_environment(self.work)
        self.binary = shutil.which("git")
        require(self.binary is not None and Path(self.binary).is_file(), "git_unavailable")
        self.directories = tuple(inherited_directories)
        require(len(self.directories) <= 4 and len(set(self.directories)) == len(self.directories))
        for descriptor in self.directories:
            require(
                os.name == "posix"
                and type(descriptor) is int
                and descriptor >= 3
                and stat.S_ISDIR(os.fstat(descriptor).st_mode),
                "unsafe_git_storage",
            )
        self.commands = 0

    def run(
        self,
        arguments,
        *,
        input_bytes=None,
        payload_limit=MAX_DIAGNOSTIC_BYTES,
        check=True,
        monitor_storage=False,
        git_directory=None,
    ):
        require(
            type(arguments) in {list, tuple}
            and arguments
            and all(type(item) is str and item and "\x00" not in item for item in arguments)
        )
        require(
            input_bytes is None
            or (type(input_bytes) is bytes and len(input_bytes) <= MAX_INPUT_BYTES),
            "limit",
        )
        require(type(payload_limit) is int and 0 < payload_limit <= MAX_FILE_BYTES + 1024, "limit")
        deadline = min(self.deadline, time.monotonic() + MAX_COMMAND_SECONDS)
        require(deadline > time.monotonic(), "deadline")
        command = [
            self.binary,
            "-c",
            "core.hooksPath=" + str(self.empty_hooks),
            "-c",
            "credential.helper=",
            "-c",
            "http.followRedirects=false",
            "-c",
            "http.sslVerify=true",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "protocol.file.allow=always",
            "-c",
            "gc.auto=0",
            "-c",
            "core.longpaths=true",
            "--git-dir=" + str(git_directory or self.repository),
            *arguments,
        ]
        token = uuid4().hex
        stdout, stderr, source = [
            self.work / (token + suffix) for suffix in (".out", ".err", ".in")
        ]
        process = None
        try:
            if input_bytes is not None:
                source.write_bytes(input_bytes)
            with (
                stdout.open("xb") as output,
                stderr.open("xb") as errors,
                (source if input_bytes is not None else Path(os.devnull)).open("rb") as incoming,
            ):
                options = {
                    "cwd": self.work,
                    "env": self.environment,
                    "stdin": incoming,
                    "stdout": output,
                    "stderr": errors,
                    "shell": False,
                    "close_fds": True,
                }
                if os.name == "posix":
                    options.update(start_new_session=True, pass_fds=self.directories)
                    process = subprocess.Popen(command, **options)
                else:
                    from .mirror_git_windows import WindowsGitProcess

                    process = WindowsGitProcess(
                        command,
                        cwd=self.work,
                        environment=self.environment,
                        incoming=incoming,
                        output=output,
                        errors=errors,
                    )
                self.commands += 1
                next_storage_check = time.monotonic()
                while process.poll() is None:
                    require(time.monotonic() <= deadline, "deadline")
                    require(
                        stdout.stat().st_size <= payload_limit
                        and stderr.stat().st_size <= MAX_DIAGNOSTIC_BYTES,
                        "git_output_limit",
                    )
                    if monitor_storage and time.monotonic() >= next_storage_check:
                        tree_storage_bound(self.repository / "objects")
                        next_storage_check = time.monotonic() + 0.25
                    time.sleep(0.01)
            require(
                stdout.stat().st_size <= payload_limit
                and stderr.stat().st_size <= MAX_DIAGNOSTIC_BYTES,
                "git_output_limit",
            )
            if monitor_storage:
                tree_storage_bound(self.repository / "objects")
            data = stdout.read_bytes()
            require(not check or process.returncode == 0, "git_command_failed")
            return process.returncode, data
        except (OSError, subprocess.SubprocessError):
            raise MirrorError("git_unavailable") from None
        finally:
            if process is not None:
                if os.name == "nt":
                    process.close()
                else:
                    if process.poll() is None:
                        _terminate_process_tree(process)
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
            for item in (stdout, stderr, source):
                item.unlink(missing_ok=True)

    def probe(self):
        _code, output = self.run(["--version"])
        match = re.fullmatch(rb"git version ([0-9a-z.]+)\r?\n", output)
        require(match is not None, "git_version_unsupported")
        version = match.group(1).decode("ascii")
        require(version in CANDIDATE_GIT_VERSIONS, "git_version_unsupported")
        return version

    def initialize_work(self):
        self.run(["init", "--bare", "--object-format=sha1", str(self.repository)])
        require(
            self.run(["rev-parse", "--show-object-format"])[1].strip() == b"sha1",
            "git_object_format",
        )

    def blob(self, oid, *, maximum=MAX_FILE_BYTES):
        require(type(oid) is str and re.fullmatch(r"[0-9a-f]{40}", oid), "git_object_format")
        size = self.run(["cat-file", "-s", oid])[1].strip()
        require(size.isdigit() and int(size) <= maximum, "limit")
        return self.run(["cat-file", "blob", oid], payload_limit=max(1, maximum))[1]

    def verify_blobs(self, rows):
        """Check size before reading, then SHA-256, with bounded batch processes."""
        selected = {}
        for row in rows:
            oid = row["oid"]
            require(type(oid) is str and re.fullmatch(r"[0-9a-f]{40}", oid), "git_object_format")
            require(
                type(row["size_bytes"]) is int and 0 <= row["size_bytes"] <= MAX_FILE_BYTES, "limit"
            )
            expected = (row["size_bytes"], row["sha256"])
            require(oid not in selected or selected[oid] == expected, "git_incomplete")
            selected[oid] = expected
        if not selected:
            return
        request = "".join(oid + "\n" for oid in selected).encode("ascii")
        output = self.run(
            ["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
            input_bytes=request,
            payload_limit=MAX_MANIFEST_BYTES,
        )[1].splitlines()
        require(len(output) == len(selected), "git_incomplete")
        for header, (oid, (size, _digest)) in zip(output, selected.items(), strict=True):
            require(header == (oid + " blob " + str(size)).encode("ascii"), "git_incomplete")

        def verify_batch(batch):
            response = self.run(
                ["cat-file", "--batch"],
                input_bytes="".join(oid + "\n" for oid in batch).encode("ascii"),
                payload_limit=sum(selected[oid][0] + 128 for oid in batch),
            )[1]
            offset = 0
            for oid in batch:
                size, digest = selected[oid]
                end = response.find(b"\n", offset, offset + 129)
                require(
                    end >= offset and response[offset:end] == (oid + " blob " + str(size)).encode(),
                    "git_incomplete",
                )
                start, offset = end + 1, end + 1 + size
                require(
                    response[offset : offset + 1] == b"\n"
                    and sha(response[start:offset]) == digest,
                    "git_incomplete",
                )
                offset += 1
            require(offset == len(response), "git_incomplete")

        batch, bound = [], 0
        for oid, (size, _digest) in selected.items():
            if batch and bound + size + 128 > MAX_FILE_BYTES:
                verify_batch(batch)
                batch, bound = [], 0
            batch.append(oid)
            bound += size + 128
        verify_batch(batch)
