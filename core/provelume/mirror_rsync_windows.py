"""Closed external MSYS2 rsync input; no runtime download or ambient DLL fallback."""

import hashlib
import json
from pathlib import Path

from .maintenance_local_files import open_local_file, pinned_parent
from .mirror_contract import require


def inputs():
    return json.loads(
        Path(__file__).with_name("mirror_rsync_windows_inputs.json").read_text(encoding="utf-8")
    )


def admit(binary):
    records = inputs()
    require(Path(binary).name.lower() == "rsync.exe", "rsync_profile_not_qualified")
    with pinned_parent(Path(binary)) as (selected, _parent):
        for row in records["entries"]:
            path = selected.parent / row["name"]
            require(
                path.is_file() and not path.is_symlink() and not path.is_junction(),
                "rsync_component_unavailable",
            )
            with open_local_file(path) as stream:
                data = stream.read(row["bytes"] + 1)
            require(
                len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"],
                "rsync_profile_not_qualified",
            )
    return {
        "runtime": "msys2-sdk-a741e84/v1",
        "input_set_sha256": hashlib.sha256(
            json.dumps(records, sort_keys=True).encode()
        ).hexdigest(),
    }
