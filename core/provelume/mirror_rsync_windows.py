"""Closed external MSYS2 rsync input; no runtime download or ambient DLL fallback."""

import hashlib
import json
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .maintenance_local_files import (
    MaintenanceTargetError,
    open_local_file,
    pinned_parent,
    stream_digest,
)
from .mirror_contract import MirrorError, require

OPENSSL_CONFIGURATION = b"""config_diagnostics = 1
openssl_conf = application_init

[application_init]
providers = application_providers

[application_providers]
default = application_default

[application_default]
activate = 1
"""


def inputs():
    return json.loads(
        Path(__file__).with_name("mirror_rsync_windows_inputs.json").read_text(encoding="utf-8")
    )


def admit(binary):
    with pinned_components(binary) as records:
        return records


@contextmanager
def pinned_openssl_configuration(path):
    try:
        with open_local_file(path) as stream:
            require(
                stream.read(len(OPENSSL_CONFIGURATION) + 1) == OPENSSL_CONFIGURATION,
                "rsync_profile_not_qualified",
            )
            # Only the built-in provider is configured. Any external module path
            # would have to descend through this read-pinned regular file.
            relative = "./" + path.name
            yield {"OPENSSL_CONF": relative, "OPENSSL_MODULES": relative}
    except MaintenanceTargetError:
        raise MirrorError("rsync_profile_not_qualified") from None


@contextmanager
def pinned_components(binary):
    records = inputs()
    require(Path(binary).name.lower() == "rsync.exe", "rsync_profile_not_qualified")
    with pinned_parent(Path(binary)) as (selected, _parent), ExitStack() as files:
        require(
            sorted(path.name.lower() for path in selected.parent.iterdir())
            == sorted(row["name"] for row in records["entries"]),
            "rsync_profile_not_qualified",
        )
        for row in records["entries"]:
            path = selected.parent / row["name"]
            stream = files.enter_context(open_local_file(path))
            digest, size = stream_digest(stream, row["bytes"])
            require(
                size == row["bytes"] and digest == row["sha256"],
                "rsync_profile_not_qualified",
            )
        yield {
            "runtime": f"msys2-sdk-{records['commit'][:7]}/v1",
            "input_set_sha256": hashlib.sha256(
                json.dumps(records, sort_keys=True).encode()
            ).hexdigest(),
        }
