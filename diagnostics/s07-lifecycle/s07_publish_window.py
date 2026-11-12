"""Measure publication of live entries in the Capture acquisition transaction."""

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-publish-entries",)


@dataclass
class Window:
    entries: list | None = None
    worker_tids: tuple[int, ...] = ()
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None


@contextmanager
def observe(atomic, adapter, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    transaction_type = atomic.AtomicInstanceCommit
    commit = transaction_type.commit
    publish = transaction_type._publish_entries
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

    def observed_publish(transaction, stage, manifest, pool):
        if (
            get_ident() != caller or transaction is not active
            or sys._getframe(1).f_code is not commit_code
        ):
            return publish(transaction, stage, manifest, pool)
        if row.start is not None or pool is not transaction._transaction_pool:
            raise ValueError("expected one publication through the Capture transaction pool")
        begin_entry()
        row.start = clock()
        try:
            if control is not None:
                control("before-publish")
            result = publish(transaction, stage, manifest, pool)
        finally:
            row.end = clock()
            end_entry()
        if control is not None:
            control("after-publish")
        row.entries = manifest["entries"]
        tids = [worker.native_id for worker in pool._threads]
        if not tids or None in tids or len(set(tids)) != len(tids):
            raise ValueError("missing or repeated Capture pool worker identity")
        row.worker_tids = tuple(sorted(tids))
        return result

    with (
        patch.object(transaction_type, "commit", observed_commit),
        patch.object(transaction_type, "_publish_entries", observed_publish),
    ):
        yield rows


def summarize(rows, start, end, index_span):
    if len(rows) != 1:
        raise ValueError("expected one Capture acquisition commit")
    row = rows[0]
    if not (row.start and row.end and row.entries and row.worker_tids):
        raise ValueError("missing successful publication of Capture entries")
    left, right = row.start, row.end
    index_start, index_end = index_span
    if not (
        start <= left[0] < right[0] <= index_start[0] <= index_end[0] <= end
        and left[1] <= right[1] <= index_start[1] <= index_end[1]
    ):
        raise ValueError("publication does not precede the separate index refresh")
    if any(entry.get("operation", "write") != "write" for entry in row.entries):
        raise ValueError("expected a write-only Capture publication")
    directories = {PurePosixPath(entry["relative"]).parent for entry in row.entries}
    return {PURPOSES[0]: (left[0], right[0])}, {
        "by_purpose": {PURPOSES[0]: {
            "wall_ns": right[0] - left[0],
            "thread_cpu_ns": right[1] - left[1],
            "entries": len(row.entries),
            "preimages": sum(entry["had_preimage"] for entry in row.entries),
            "destination_directories": len(directories),
        }},
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }


def publication_fsyncs(events, worker_tids, expected):
    workers = set(worker_tids)
    pending = {}
    intervals = []
    for event in events:
        if event[0] != "D" or event[2] not in workers:
            continue
        _, stamp, tid, phase = event
        if phase == 1 and tid not in pending:
            pending[tid] = stamp
        elif phase == 0 and tid in pending and pending[tid] <= stamp:
            intervals.append((pending.pop(tid), stamp))
        else:
            raise ValueError("publication worker fsync entry and exit do not pair")
    if pending or len(intervals) != expected or not intervals:
        raise ValueError(f"expected {expected} publication worker fsyncs, traced {len(intervals)}")
    return {
        "worker_fsync_pairs": len(intervals),
        "slowest_worker_fsync_ns": max(right - left for left, right in intervals),
        "first_to_last_worker_fsync_ns": (
            max(right for _, right in intervals) - min(left for left, _ in intervals)
        ),
    }
