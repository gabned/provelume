"""Measure successful Capture staging removal and the parent directory sync."""

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-stage-cleanup",)


@dataclass
class Window:
    stage: Path | None = None
    entries: list | None = None
    stage_synced: bool = False
    removal_returned: bool = False
    stage_removed: bool = False
    parent_synced: bool = False
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None


@contextmanager
def observe(atomic, adapter, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    transaction_type = atomic.AtomicInstanceCommit
    commit = transaction_type.commit
    prepare = transaction_type._prepare
    sync = atomic._fsync_directory
    rmtree = atomic.shutil.rmtree
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
        if row.stage is not None and row.removal_returned:
            try:
                os.lstat(row.stage)
            except FileNotFoundError:
                row.stage_removed = True
        rows.append(row)
        return result

    def observed_prepare(transaction):
        stage, manifest = prepare(transaction)
        if get_ident() == caller and transaction is active:
            row.stage, row.entries = stage, manifest["entries"]
        return stage, manifest

    def observed_rmtree(path, *args, **kwargs):
        if (
            get_ident() != caller or active is None or sys._getframe(1).f_code is not commit_code
            or not row.stage_synced or row.stage != path or kwargs.get("ignore_errors") is not True
        ):
            return rmtree(path, *args, **kwargs)
        if row.start is not None:
            raise ValueError("multiple cleanup calls for the committed stage")
        row.start = clock()
        begin_entry()
        if control is not None:
            control("before-stage-removal")
        result = rmtree(path, *args, **kwargs)
        row.removal_returned = True
        return result

    def observed_sync(path):
        if get_ident() != caller or active is None or sys._getframe(1).f_code is not commit_code:
            return sync(path)
        if row.removal_returned and row.end is None and path == active.stage_parent:
            try:
                result = sync(path)
                row.parent_synced = True
            finally:
                end_entry()
                row.end = clock()
            if control is not None:
                control("after-parent-sync")
            return result
        result = sync(path)
        if path == row.stage:
            row.stage_synced = True
        return result

    with (
        patch.object(transaction_type, "commit", observed_commit),
        patch.object(transaction_type, "_prepare", observed_prepare),
        patch.object(atomic.shutil, "rmtree", observed_rmtree),
        patch.object(atomic, "_fsync_directory", observed_sync),
    ):
        yield rows


def summarize(rows, start, end, index_span):
    if len(rows) != 1:
        raise ValueError("expected one Capture acquisition commit")
    row = rows[0]
    if not (row.start and row.end and row.entries and row.stage_removed and row.parent_synced):
        raise ValueError("incomplete or unsuccessful durable staging cleanup")
    left, right = row.start, row.end
    index_start, index_end = index_span
    if not (
        start <= left[0] < right[0] <= index_start[0] <= index_end[0] <= end
        and left[1] <= right[1] <= index_start[1] <= index_end[1]
    ):
        raise ValueError("staging cleanup window does not precede the separate index refresh")
    return {PURPOSES[0]: (left[0], right[0])}, {
        "by_purpose": {PURPOSES[0]: {
            "wall_ns": right[0] - left[0],
            "thread_cpu_ns": right[1] - left[1],
            "entries": len(row.entries),
            "preimages": sum(entry["had_preimage"] for entry in row.entries),
            "stage_removed": row.stage_removed,
            "parent_synced": row.parent_synced,
        }},
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }
