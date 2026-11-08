"""Native pinned MSYS2 local-copy proof and Windows SSH version observation only."""

import hashlib
import os
import re
import traceback
from contextlib import contextmanager
from pathlib import Path

from .build_info import current_build_info
from .maintenance_local_files import open_local_file
from .migration_permissions import make_private
from .mirror_contract import MirrorError, require
from .mirror_rsync_windows import admit, inputs, native_path
from .mirror_ssh_runtime import NativeSession


class WindowsComponentsFailure(MirrorError):
    """Closed diagnostics for synthetic native qualification, without path/secret text."""


@contextmanager
def qualification_phase(phase):
    try:
        yield
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failure = WindowsComponentsFailure(getattr(exc, "code", "rsync_windows_qualification"))
        failure.evidence = {
            "schema": "concordia-rsync-windows-components-failure/v1",
            "phase": phase,
            "exception": type(exc).__name__,
            "frames": [
                {"module": Path(frame.f_code.co_filename).name,
                 "function": frame.f_code.co_name, "line": line}
                for frame, line in list(traceback.walk_tb(exc.__traceback__))[-6:]
            ],
        }
        filename = getattr(exc, "filename", None)
        suffix = Path(filename).suffix if isinstance(filename, str) else ""
        failure.evidence["temporary_role"] = {
            ".in": "stdin", ".out": "stdout", ".err": "stderr"
        }.get(suffix, "not_transport_temporary")
        if type(getattr(exc, "winerror", None)) is int:
            failure.evidence["native_error"] = exc.winerror
        if hasattr(exc, "containment_evidence"):
            failure.evidence["containment"] = exc.containment_evidence
        raise failure from None


def qualify_components(root, *, fixture_directory):
    require(os.name == "nt", "rsync_windows_qualification_platform")
    root = Path(root).absolute()
    directory = Path(fixture_directory).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    with qualification_phase("private_root"):
        root.mkdir(parents=True)
        make_private(root)
    binary = directory / "rsync.exe"
    with qualification_phase("pinned_inputs"):
        admitted = admit(binary)
    with qualification_phase("native_version"):
        session = NativeSession(root)
        component = session.component("rsync", binary=str(binary))
    source, destination = root / "Input with space", root / "Output with space"
    source.mkdir()
    destination.mkdir()
    (source / "nested").mkdir()
    expected = {
        "one.txt": b"Synthetic native Windows rsync input\n",
        "nested/two.txt": b"Dato sintetico, nessuna credenziale.\n",
    }
    for name, data in expected.items():
        (source / name).write_bytes(data)
    with qualification_phase("native_local_copy"):
        session.run(
            [
                str(binary),
                "--recursive",
                "--checksum",
                "--no-links",
                "--no-devices",
                "--no-specials",
                "--no-owner",
                "--no-group",
                "--no-perms",
                "--timeout=15",
                native_path(source) + "/",
                native_path(destination) + "/",
            ]
        )
    require(
        {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        == set(expected),
        "rsync_windows_qualification",
    )
    with qualification_phase("copied_bytes"):
        for name, data in expected.items():
            with open_local_file(destination / name) as stream:
                require(stream.read(len(data) + 1) == data, "rsync_windows_qualification")
    ssh = Path(os.environ["SYSTEMROOT"]) / "System32/OpenSSH/ssh.exe"
    observed = {"result": "UNAVAILABLE", "profile": "NOT_ADMITTED"}
    if ssh.is_file():
        with open_local_file(ssh) as stream:
            content = stream.read(16 * 1024 * 1024 + 1)
        require(len(content) <= 16 * 1024 * 1024, "ssh_component_unavailable")
        code, stdout, stderr = session.run([str(ssh), "-V"], maximum=4096, check=False)
        require(
            code == 0
            and not stdout
            and re.fullmatch(rb"OpenSSH_for_Windows_[0-9.]+p[0-9]+, LibreSSL [0-9.]+\r?\n", stderr),
            "rsync_windows_qualification",
        )
        observed = {
            "result": "OBSERVED_ONLY",
            "profile": "NOT_ADMITTED",
            "version": stderr.decode().strip(),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    manifest = inputs()
    return {
        "schema": "concordia-rsync-windows-components/v1",
        "result": "PASS",
        "commit": current_build_info().get("commit"),
        "mode": "NATIVE_PINNED_LOCAL_RSYNC_AND_SSH_VERSION_ONLY",
        "rsync": {key: component[key] for key in ("version", "sha256")},
        "input_set": admitted,
        "source": {
            key: manifest[key]
            for key in (
                "repository",
                "commit",
                "source_verification",
                "package_validation_metadata",
            )
        },
        "native_local_copy": "PASS",
        "ssh": observed,
        "external_network_used": False,
        "native_ssh_authentication": "NOT_RUN",
        "native_rsync_over_ssh": "NOT_RUN",
        "s22_acceptance": "NOT_ACCEPTED",
        "application_component_distribution": False,
        "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
