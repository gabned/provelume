"""Observe the durable prepared marker of both Capture commits."""

import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-submit", "capture-process")
OPERATIONS = ("manifest_write", "stage_sync", "parent_sync")


@dataclass
class Window:
    start: tuple[int, int]
    stage: Path
    manifest: bytes
    end: tuple[int, int] | None = None
    operations: dict = field(default_factory=dict)


@contextmanager
def observe(atomic, adapter, store, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    transaction_type = atomic.AtomicInstanceCommit
    commit = transaction_type.commit
    prepare_code = transaction_type._prepare.__code__
    write = store.InstanceStore._atomic_bytes
    sync = atomic._fsync_directory
    entrypoints = {
        adapter.CaptureJournal.submit.__code__: PURPOSES[0],
        adapter.CaptureAdapter._acquire_locked.__code__: PURPOSES[1],
    }
    active, purpose = None, None
    windows = {}

    def observed_commit(transaction):
        nonlocal active, purpose
        selected = entrypoints.get(sys._getframe(1).f_code)
        if get_ident() != caller or selected is None:
            return commit(transaction)
        if active is not None or selected in windows:
            raise ValueError("repeated Capture commit in the selected probe")
        active, purpose = transaction, selected
        try:
            return commit(transaction)
        finally:
            active, purpose = None, None

    def observed_write(path, content):
        if (get_ident() != caller or active is None
                or sys._getframe(1).f_code is not prepare_code):
            return write(path, content)
        if purpose in windows or path.name != "manifest.json":
            raise ValueError("expected one prepared manifest per Capture commit")
        if path.parent.parent != active.stage_parent:
            raise ValueError("prepared manifest path differs from the Capture staging tree")
        begin_entry()
        row = windows[purpose] = Window(clock(), path.parent, content)
        if control is not None:
            control(purpose, "inside")
        left = clock()
        result = write(path, content)
        row.operations["manifest_write"] = left, clock()
        return result

    def observed_sync(path):
        if (get_ident() != caller or active is None or purpose not in windows
                or sys._getframe(1).f_code is not prepare_code):
            return sync(path)
        row = windows[purpose]
        if path == row.stage and tuple(row.operations) == OPERATIONS[:1]:
            operation = "stage_sync"
        elif path == row.stage.parent and tuple(row.operations) == OPERATIONS[:2]:
            operation = "parent_sync"
        else:
            raise ValueError("prepared marker directory syncs are missing or out of order")
        left = clock()
        result = sync(path)
        right = clock()
        row.operations[operation] = left, right
        if operation == "parent_sync":
            row.end = right
            end_entry()
            if control is not None:
                control(purpose, "after")
        return result

    with (
        patch.object(transaction_type, "commit", observed_commit),
        patch.object(store.InstanceStore, "_atomic_bytes", staticmethod(observed_write)),
        patch.object(atomic, "_fsync_directory", observed_sync),
    ):
        yield windows


def summarize(windows, start, end, index_span):
    if tuple(windows) != PURPOSES:
        raise ValueError("expected one prepared marker per Capture commit")
    index_start, index_end = index_span
    spans, operations, by_purpose = {}, {}, {}
    previous = start
    for purpose, row in windows.items():
        if row.end is None or tuple(row.operations) != OPERATIONS:
            raise ValueError("incomplete prepared marker window")
        left, right = row.start, row.end
        if not (previous <= left[0] < right[0] <= index_start[0] and left[1] <= right[1]):
            raise ValueError("prepared marker windows are out of order")
        last = left
        for begin, finish in row.operations.values():
            if not (
                last[0] <= begin[0] <= finish[0] <= right[0]
                and last[1] <= begin[1] <= finish[1] <= right[1]
            ):
                raise ValueError("prepared marker operations are out of order")
            last = finish
        manifest = json.loads(row.manifest)
        entries = manifest["entries"]
        if (
            manifest.get("status") != "prepared" or manifest["committed_at"] is not None
            or not entries
        ):
            raise ValueError("the observed manifest is not the prepared marker")
        spans[purpose] = left[0], right[0]
        operations[purpose] = {
            name: (begin[0], finish[0]) for name, (begin, finish) in row.operations.items()
        }
        by_purpose[purpose] = {
            "wall_ns": right[0] - left[0],
            "thread_cpu_ns": right[1] - left[1],
            "manifest_bytes": len(row.manifest),
            "entries": len(entries),
            "preimages": sum(entry["had_preimage"] for entry in entries),
        }
        previous = right[0]
    if not previous <= index_start[0] <= index_end[0] <= end:
        raise ValueError("index refresh is outside the selected probe")
    return spans, operations, {
        "by_purpose": by_purpose,
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }


def bind_fsyncs(events, tid, operations, offset, *, synthetic):
    low, high = offset
    stamps = [(event[1], event[3]) for event in events
              if event[0] == "D" and event[2] == tid]
    names = ("synthetic", *OPERATIONS) if synthetic else OPERATIONS
    if [phase for _, phase in stamps] != [1, 0] * len(names):
        raise ValueError("incomplete caller fsyncs for the prepared marker")
    receipts = {}
    for name, (entry, exit_) in zip(names, zip(stamps[::2], stamps[1::2], strict=True),
                                    strict=True):
        begin, finish = entry[0], exit_[0]
        if begin > finish:
            raise ValueError("prepared marker fsync exit precedes entry")
        if name == "synthetic":
            if finish > operations["manifest_write"][0] + low:
                raise ValueError("synthetic fsync overlapped the real manifest write")
            continue
        left, right = operations[name]
        if not left + high <= begin <= finish <= right + low:
            raise ValueError(f"caller fsync falls outside {name}")
        receipts[name] = {"operation_ns": right - left, "fsync_ns": finish - begin}
    return receipts
