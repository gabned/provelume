"""Controlled activation fault for the disposable SSH qualification image only."""

import errno
import json
import os
from pathlib import Path

from provelume.mirror_folder_files import FolderTree

original = FolderTree.rename


def controlled(tree, source, destination, **options):
    if destination != "active.json":
        return original(tree, source, destination, **options)
    path = Path("/fixture/activation-fault.json")
    if not path.exists():
        return original(tree, source, destination, **options)
    value = json.loads(path.read_bytes())
    if value.get("consumed") or source != "staging/activate-" + value["operation_id"] + ".json":
        return original(tree, source, destination, **options)
    if value["phase"] == "after":
        original(tree, source, destination, **options)
    value["consumed"] = True
    value["native_rename_performed"] = value["phase"] == "after"
    temporary = path.with_suffix(".tmp")
    with temporary.open("x") as stream:
        stream.write(json.dumps(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    raise OSError(errno.ENOSPC, "Synthetic declared activation boundary fault")


FolderTree.rename = controlled
