"""Controlled activation fault for the disposable SSH qualification image only."""

import errno
import json
import os
import signal
import threading
import time
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

# This hook exists only in the disposable image. The product receiver still
# starts, transfers through actual SSH and unwinds through its own signal and
# process-group containment before persisting any safe-resume evidence.
from provelume import mirror_rsync_remote as remote  # noqa: E402

original_receive = remote.receive


def interrupted_receive(arguments, **options):
    path = Path("/fixture/transfer-fault.json")
    if not path.exists():
        return original_receive(arguments, **options)
    value = json.loads(path.read_bytes())
    if value.get("consumed") or options["stage"] != "staging/" + value["operation_id"]:
        return original_receive(arguments, **options)
    stopped = threading.Event()

    def interrupt():
        deadline = time.monotonic() + 10
        stage = options["tree"].root / options["stage"]
        while not stopped.wait(0.02) and time.monotonic() < deadline:
            count = sum(item.stat().st_size for item in stage.rglob("*") if item.is_file())
            if count < 65536:
                continue
            value.update(consumed=True, observed_partial_bytes=count, signal="SIGTERM")
            path.write_text(json.dumps(value))
            os.kill(os.getpid(), signal.SIGTERM)
            return

    thread = threading.Thread(target=interrupt, daemon=True)
    thread.start()
    try:
        return original_receive(arguments, **options)
    finally:
        stopped.set()
        thread.join(timeout=0.5)


remote.receive = interrupted_receive
