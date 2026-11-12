"""Measure the Capture acquisition's committed-manifest write and directory sync."""

import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-commit-marker",)


@dataclass
class Window:
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None
    stage: Path | None = None
    manifest: bytes | None = None


@contextmanager
def observe(atomic, adapter, store, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    transaction_type = atomic.AtomicInstanceCommit
    commit = transaction_type.commit
    shutdown = transaction_type._shutdown_transaction_pool
    write = store.InstanceStore._atomic_bytes
    sync = atomic._fsync_directory
    acquire_code = adapter.CaptureAdapter._acquire_locked.__code__
    commit_code = transaction_type._commit_with_pool.__code__
    row = Window()
    active = None
    rows = []

    def observed_commit(transaction):
        nonlocal active
        if get_ident() != caller or sys._getframe(1).f_code is not acquire_code:
            return commit(transaction)
        if rows or active is not None:
            raise ValueError("multiple Capture acquisition commits in one selected probe")
        active = transaction
        try:
            result = commit(transaction)
        finally:
            active = None
        rows.append(row)
        return result

    def observed_shutdown(transaction, primary=None):
        result = shutdown(transaction, primary)
        if (
            get_ident() == caller and transaction is active and primary is None
            and sys._getframe(1).f_code is commit_code and row.start is None
            and transaction._transaction_pool_state == "drained"
        ):
            row.start = clock()
            begin_entry()
        return result

    def observed_write(path, content):
        if (
            get_ident() != caller or active is None or row.start is None or row.end is not None
            or sys._getframe(1).f_code is not commit_code or path.name != "manifest.json"
        ):
            return write(path, content)
        if row.stage is not None:
            raise ValueError("multiple final manifests in one Capture commit")
        if control is not None:
            control("before-manifest-write")
        result = write(path, content)
        row.stage, row.manifest = path.parent, content
        return result

    def observed_sync(path):
        result = sync(path)
        if (
            get_ident() == caller and active is not None and row.stage == path
            and row.end is None and sys._getframe(1).f_code is commit_code
        ):
            end_entry()
            row.end = clock()
            if control is not None:
                control("after-stage-sync")
        return result

    with (
        patch.object(transaction_type, "commit", observed_commit),
        patch.object(transaction_type, "_shutdown_transaction_pool", observed_shutdown),
        patch.object(store.InstanceStore, "_atomic_bytes", staticmethod(observed_write)),
        patch.object(atomic, "_fsync_directory", observed_sync),
    ):
        yield rows


def summarize(rows, start, end, index_span):
    if len(rows) != 1:
        raise ValueError("expected one Capture acquisition commit")
    row = rows[0]
    if row.start is None or row.end is None or row.manifest is None:
        raise ValueError("incomplete committed-manifest window")
    left, right = row.start, row.end
    index_start, index_end = index_span
    if not (
        start <= left[0] < right[0] <= index_start[0] <= index_end[0] <= end
        and left[1] <= right[1] <= index_start[1] <= index_end[1]
    ):
        raise ValueError("committed-manifest window does not precede the separate index refresh")
    manifest = json.loads(row.manifest)
    if manifest.get("status") != "committed" or not manifest.get("entries"):
        raise ValueError("the observed manifest is not the final committed marker")
    entries = manifest["entries"]
    return {PURPOSES[0]: (left[0], right[0])}, {
        "by_purpose": {PURPOSES[0]: {
            "wall_ns": right[0] - left[0],
            "thread_cpu_ns": right[1] - left[1],
            "manifest_bytes": len(row.manifest),
            "entries": len(entries),
            "preimages": sum(entry["had_preimage"] for entry in entries),
        }},
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }
