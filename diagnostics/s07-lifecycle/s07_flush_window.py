"""Measure each directory flush result in the Capture acquisition transaction."""

import sys
import time
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from threading import get_ident, get_native_id
from unittest.mock import patch

PURPOSES = ("capture-flush-result",)


@dataclass
class Flush:
    worker: tuple[int, int, int] | None = None
    wait: tuple[tuple[int, int], tuple[int, int]] | None = None


@dataclass
class Window:
    entries: list | None = None
    flushes: dict[Future, Flush] = field(default_factory=dict)
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None


@contextmanager
def observe(atomic, adapter, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    transaction_type = atomic.AtomicInstanceCommit
    commit = transaction_type.commit
    publish = transaction_type._publish_entries
    get_result = Future.result
    fsync_directory = atomic._fsync_directory
    acquire_code = adapter.CaptureAdapter._acquire_locked.__code__
    commit_code = transaction_type._commit_with_pool.__code__
    publish_code = publish.__code__
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
        submit = pool.submit

        def observed_submit(fn, *args, **kwargs):
            if get_ident() != caller or fn is not fsync_directory:
                return submit(fn, *args, **kwargs)
            flush = Flush()

            def sync():
                tid = get_native_id()
                start = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
                result = fn(*args, **kwargs)
                flush.worker = (tid, start, time.clock_gettime_ns(time.CLOCK_BOOTTIME))
                return result

            future = submit(sync)
            row.flushes[future] = flush
            return future

        begin_entry()
        row.start = clock()
        try:
            with patch.object(pool, "submit", observed_submit):
                result = publish(transaction, stage, manifest, pool)
        finally:
            row.end = clock()
            end_entry()
        if control is not None:
            control("after-publish")
        row.entries = manifest["entries"]
        return result

    def observed_result(future, *args, **kwargs):
        if get_ident() != caller or sys._getframe(1).f_code is not publish_code:
            return get_result(future, *args, **kwargs)
        flush = row.flushes.get(future)
        if flush is None:
            return get_result(future, *args, **kwargs)
        if flush.wait is not None:
            raise ValueError("publication future awaited more than once")
        left = clock()
        if control is not None and future is next(iter(row.flushes)):
            control("inside-first-wait")
        value = get_result(future, *args, **kwargs)
        flush.wait = (left, clock())
        return value

    with (
        patch.object(transaction_type, "commit", observed_commit),
        patch.object(transaction_type, "_publish_entries", observed_publish),
        patch.object(Future, "result", observed_result),
    ):
        yield rows


def summarize(rows, start, end, index_span):
    if len(rows) != 1:
        raise ValueError("expected one Capture acquisition commit")
    row = rows[0]
    if not (row.start and row.end and row.entries and row.flushes):
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
    flushes = list(row.flushes.values())
    if len(flushes) != len(directories) or any(
        flush.wait is None or flush.worker is None for flush in flushes
    ):
        raise ValueError("missing directory flush task or wait")
    previous = left
    for flush in flushes:
        wait_start, wait_end = flush.wait
        if not (
            previous[0] <= wait_start[0] < wait_end[0] <= right[0]
            and previous[1] <= wait_start[1] <= wait_end[1] <= right[1]
        ):
            raise ValueError("directory flush waits are not ordered within publication")
        previous = wait_end
    return {PURPOSES[0]: (left[0], right[0])}, {
        "by_purpose": {PURPOSES[0]: {
            "wall_ns": sum(f.wait[1][0] - f.wait[0][0] for f in flushes),
            "thread_cpu_ns": sum(f.wait[1][1] - f.wait[0][1] for f in flushes),
            "entries": len(row.entries),
            "preimages": sum(entry["had_preimage"] for entry in row.entries),
            "destination_directories": len(directories),
        }},
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }


def bind_waits(events, flushes, intervals, offset):
    low, high = offset
    tids = {flush["worker"][0] for flush in flushes}
    pending = {}
    pairs = []
    for kind, stamp, tid, *payload in events:
        if kind != "D" or tid not in tids:
            continue
        if payload == [1] and tid not in pending:
            pending[tid] = stamp
        elif payload == [0] and tid in pending and pending[tid] <= stamp:
            pairs.append((tid, pending.pop(tid), stamp))
        else:
            raise ValueError("directory worker fsync entry and exit do not pair")
    if pending or len(pairs) != len(flushes):
        raise ValueError(f"expected {len(flushes)} directory worker fsyncs, traced {len(pairs)}")

    rows = []
    for flush in flushes:
        tid, worker_start, worker_end = flush["worker"]
        (left, cpu_start), (right, cpu_end) = flush["wait"]
        matches = [
            pair for pair in pairs if pair[0] == tid and worker_start <= pair[1] <= pair[2]
            <= worker_end
        ]
        if len(matches) != 1 or worker_end > right + high:
            raise ValueError("could not bind a directory fsync to its future result")
        pair = matches[0]
        pairs.remove(pair)
        fsync_start, fsync_end = pair[1:]
        totals = {"blocked": 0, "ready": 0}
        certain_start, certain_end = left + high, right + low
        for item in intervals:
            wake = item["wake"]
            if wake is not None:
                totals["blocked"] += max(
                    0, min(certain_end, wake) - max(certain_start, item["start"]),
                )
                totals["ready"] += max(
                    0, min(certain_end, item["end"]) - max(certain_start, wake),
                )
        rows.append({
            "wall_ns": right - left,
            "thread_cpu_ns": cpu_end - cpu_start,
            "certain_blocked_ns": totals["blocked"],
            "certain_ready_ns": totals["ready"],
            "fsync_ns": fsync_end - fsync_start,
            "fsync_end_minus_wait_start_ns_bounds": [fsync_end - left - high,
                                                     fsync_end - left - low],
            "wait_return_minus_fsync_end_ns_bounds": [right + low - fsync_end,
                                                      right + high - fsync_end],
        })
    return {
        "waits": rows,
        "worker_fsync_pairs": len(rows),
        "certain_blocked_ns": sum(row["certain_blocked_ns"] for row in rows),
        "certain_ready_ns": sum(row["certain_ready_ns"] for row in rows),
    }
