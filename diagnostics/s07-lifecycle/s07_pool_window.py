"""Measure the successful shutdown of the Capture acquisition transaction pool."""

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-pool-shutdown",)


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
    prepare = transaction_type._prepare
    publish = transaction_type._publish_entries
    drain = transaction_type._shutdown_transaction_pool
    acquire_code = adapter.CaptureAdapter._acquire_locked.__code__
    commit_code = transaction_type._commit_with_pool.__code__
    row = Window()
    active = None
    published = False
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

    def observed_prepare(transaction):
        stage, manifest = prepare(transaction)
        if get_ident() == caller and transaction is active:
            row.entries = manifest["entries"]
        return stage, manifest

    def observed_publish(transaction, stage, manifest, pool):
        nonlocal published
        result = publish(transaction, stage, manifest, pool)
        if get_ident() == caller and transaction is active:
            published = True
        return result

    def observed_drain(transaction, primary=None):
        if (
            get_ident() != caller or transaction is not active
            or sys._getframe(1).f_code is not commit_code or not published
            or primary is not None or transaction._transaction_pool_state != "active"
        ):
            return drain(transaction, primary)
        if row.start is not None or transaction._transaction_pool is None:
            raise ValueError("expected one live pool at the successful drain")
        workers = tuple(transaction._transaction_pool._threads)
        tids = [thread.native_id for thread in workers]
        if not workers or None in tids or len(set(tids)) != len(tids) or not all(
            thread.is_alive() for thread in workers
        ):
            raise ValueError("transaction pool workers were not all live before drain")
        row.worker_tids = tuple(sorted(tids))
        row.start = clock()
        begin_entry()
        try:
            if control is not None:
                control("before-pool-wait")
            result = drain(transaction, primary)
        finally:
            end_entry()
            row.end = clock()
        if transaction._transaction_pool_state != "drained" or any(
            thread.is_alive() for thread in workers
        ):
            raise ValueError("transaction pool did not finish joining its workers")
        if control is not None:
            control("after-pool-wait")
        return result

    with (
        patch.object(transaction_type, "commit", observed_commit),
        patch.object(transaction_type, "_prepare", observed_prepare),
        patch.object(transaction_type, "_publish_entries", observed_publish),
        patch.object(transaction_type, "_shutdown_transaction_pool", observed_drain),
    ):
        yield rows


def summarize(rows, start, end, index_span):
    if len(rows) != 1:
        raise ValueError("expected one Capture acquisition commit")
    row = rows[0]
    if not (row.start and row.end and row.entries and row.worker_tids):
        raise ValueError("missing successful Capture pool shutdown")
    left, right = row.start, row.end
    index_start, index_end = index_span
    if not (
        start <= left[0] < right[0] <= index_start[0] <= index_end[0] <= end
        and left[1] <= right[1] <= index_start[1] <= index_end[1]
    ):
        raise ValueError("pool shutdown window does not precede the separate index refresh")
    return {PURPOSES[0]: (left[0], right[0])}, {
        "by_purpose": {PURPOSES[0]: {
            "wall_ns": right[0] - left[0],
            "thread_cpu_ns": right[1] - left[1],
            "entries": len(row.entries),
            "preimages": sum(entry["had_preimage"] for entry in row.entries),
            "pool_workers": len(row.worker_tids),
        }},
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }
