"""Explicit Linux helper enrollment and fixed forced-command SSH subsystem entry."""

from __future__ import annotations

import hashlib
import os
import re
import select
import shlex
import signal
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .maintenance_local_files import MaintenanceTargetError, pinned_parent
from .migration_permissions import make_private
from .mirror_contract import MirrorError, fingerprint, parse, raw, require
from .mirror_rsync_protocol import read_frame, request
from .mirror_rsync_remote import RemoteNamespace, config_value, exclude
from .mirror_ssh_runtime import SUBSYSTEM, NativeSession


def enroll_helper(
    config_directory, *, root, source, namespace, client_public_sha256, rsync_binary, excluded_roots
):
    """Operator-selected remote preparation; never invoked by client publication.

    All paths remain in a private local namespace file. The returned public
    receipt carries hashes and a dedicated public-key constraint, never a secret.
    The operator separately installs the exact forced-command authorization.
    """
    require(
        os.name == "posix" and os.uname().sysname == "Linux", "rsync_server_profile_not_qualified"
    )
    selected, control = Path(root), Path(config_directory)
    for path in (selected, control):
        with pinned_parent(path) as (checked, _parent):
            exclude(
                checked.parent.resolve() / checked.name, [Path(item) for item in excluded_roots]
            )
            require(not checked.exists() and not checked.is_symlink(), "rsync_namespace_exists")
    require(
        not selected.is_relative_to(control) and not control.is_relative_to(selected),
        "rsync_namespace_boundary",
    )
    with TemporaryDirectory(prefix="pv-rsync-enrollment-") as work:
        component = NativeSession(Path(work)).component("rsync", binary=rsync_binary)
    value = config_value(
        {
            "schema": "provelume-rsync-namespace/v1",
            "namespace": namespace,
            "root": str(selected),
            "source": source,
            "client_public_sha256": client_public_sha256,
            "excluded_roots": list(excluded_roots),
            "rsync_binary": component["path"],
            "rsync_sha256": component["sha256"],
        }
    )
    # Re-admit the physical parent before the first enrollment effect.
    with pinned_parent(control) as (checked, parent):
        exclude(checked.parent.resolve() / checked.name, [selected, *map(Path, excluded_roots)])
        os.mkdir(checked.name, 0o700, dir_fd=parent)
        make_private(checked)
        (checked / "operations").mkdir(mode=0o700)
        path = checked / "namespace.json"
        with path.open("xb") as stream:
            stream.write(raw(value))
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o600)
    return {
        "schema": "provelume-rsync-helper-enrollment/v1",
        "configuration_sha256": fingerprint(value),
        "namespace": namespace,
        "client_public_sha256": client_public_sha256,
        "rsync": {key: component[key] for key in ("version", "sha256")},
        "root_created": False,
        "forced_command_installation": "NOT_RUN",
        "remote_account_authorization": "REQUIRED_FOR_THIS_SPECIFIC_ACCOUNT_AND_DESTINATION",
    }


def main():
    value = None
    try:
        if sys.argv[1:2] == ["enroll"]:
            import argparse
            import base64

            from .mirror_ssh_agent import decode_public

            parser = argparse.ArgumentParser(
                description="Prepare a fresh dedicated SSH mirror namespace on this Linux account"
            )
            parser.add_argument("enroll")
            parser.add_argument("configuration_file", type=Path)
            parser.add_argument("--confirm", action="store_true")
            options = parser.parse_args()
            require(options.confirm is True, "consent_required")
            with open(options.configuration_file, "rb") as stream:
                payload = parse(stream.read(16385))
            require(
                set(payload)
                == {
                    "config_directory",
                    "root",
                    "source",
                    "namespace",
                    "client_public_key",
                    "rsync_binary",
                    "excluded_roots",
                },
                "rsync_namespace_configuration",
            )
            public = payload.pop("client_public_key")
            require(
                type(public) is str
                and public.startswith("ssh-ed25519 ")
                and len(public.split()) == 2,
                "ssh_key",
            )
            key = base64.b64decode(public.split()[1], validate=True)
            decode_public(key)
            result = enroll_helper(**payload, client_public_sha256=hashlib.sha256(key).hexdigest())
            command = shlex.join(
                [
                    sys.executable,
                    "-m",
                    "provelume.mirror_rsync_remote_main",
                    str(Path(payload["config_directory"]) / "namespace.json"),
                ]
            )
            result["authorized_key_line"] = (
                'restrict,command="'
                + command.replace("\\", "\\\\").replace('"', '\\"')
                + '" '
                + public
            )
            result["subsystem_configuration"] = "Subsystem " + SUBSYSTEM + " " + SUBSYSTEM
            sys.stdout.buffer.write(raw(result))
            return 0
        require(
            os.name == "posix" and os.uname().sysname == "Linux",
            "rsync_server_profile_not_qualified",
        )

        def interrupted(_number, _frame):
            # Unwind through receive()'s owned-child cleanup, then persist only
            # a positively confirmed stop. SIGKILL/power loss leaves UNKNOWN.
            raise MirrorError("rsync_transfer_interrupted")

        signal.signal(signal.SIGHUP, interrupted)
        signal.signal(signal.SIGTERM, interrupted)
        require(
            os.environ.get("SSH_ORIGINAL_COMMAND") == SUBSYSTEM, "rsync_forced_command_required"
        )
        require(
            len(sys.argv) == 2 and Path(sys.argv[1]).is_absolute(), "rsync_namespace_configuration"
        )
        os.umask(0o077)
        selected = RemoteNamespace(sys.argv[1])
        value = request(read_frame(0))
        selected.admit_request(value)
        if value["action"] in {"receive", "resume"}:
            return selected.transfer(value, incoming=0, outgoing=1)
        # A control operation has no opaque stdin suffix. Bound EOF admission
        # precedes enrollment/activation and never consumes rsync stream bytes.
        require(select.select([0], [], [], 5)[0] and os.read(0, 1) == b"", "rsync_protocol")
        result = (
            selected.activate(value) if value["action"] == "activate" else selected.inspect(value)
        )
        sys.stdout.buffer.write(raw(result))
        sys.stdout.buffer.flush()
        return 0
    except Exception as error:
        if value is None or value.get("action") not in {"receive", "resume"}:
            code = (
                error.code
                if isinstance(error, (MirrorError, MaintenanceTargetError))
                else "rsync_helper_unavailable"
            )
            require(
                type(code) is str and re.fullmatch(r"[a-z_]{1,80}", code),
                "rsync_helper_unavailable",
            )
            sys.stdout.buffer.write(
                raw({"schema": "provelume-rsync-error/v1", "result": "UNAVAILABLE", "code": code})
            )
            sys.stdout.buffer.flush()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
