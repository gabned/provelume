"""Measure the staging writer waits of both Capture commits on the original source."""

import sys
import time
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import get_ident, get_native_id
from unittest.mock import patch

PURPOSES = ("capture-submit", "capture-process")


@dataclass
class Write:
    kind: str
    size: int
    worker: tuple[int, int, int] | None = None
    wait: tuple[tuple[int, int], tuple[int, int]] | None = None


@dataclass
class Window:
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None
    writes: dict[Future, Write] = field(default_factory=dict)


@contextmanager
def observe(atomic, adapter, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    transaction_type = atomic.AtomicInstanceCommit
    commit = transaction_type.commit
    pool_scope = transaction_type._prepare_pool_scope
    prepare_code = transaction_type._prepare.__code__
    write_payload = atomic._write_journal_payload
    get_result = Future.result
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
        if selected in windows or active is not None:
            raise ValueError("repeated Capture commit in the selected probe")
        active, purpose = transaction, selected
        try:
            return commit(transaction)
        finally:
            active, purpose = None, None

    def observed_pool_scope(transaction):
        original_scope = pool_scope(transaction)
        if (get_ident() != caller or transaction is not active
                or sys._getframe(1).f_code is not prepare_code):
            return original_scope
        if purpose in windows:
            raise ValueError("repeated writer scope in the selected Capture commit")
        row = windows[purpose] = Window()
        return wrap_pool(original_scope, row)

    @contextmanager
    def wrap_pool(original_scope, row):
        with original_scope as pool:
            submit = pool.submit

            def observed_submit(fn, path, data):
                if fn is not write_payload or row.end is not None:
                    raise ValueError("unexpected task in the selected staging writer scope")
                if row.start is None:
                    begin_entry()
                    row.start = clock()
                task = Write(path.parent.name, len(data))

                def write():
                    tid = get_native_id()
                    start = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
                    result = fn(path, data)
                    task.worker = (tid, start, time.clock_gettime_ns(time.CLOCK_BOOTTIME))
                    return result

                future = submit(write)
                row.writes[future] = task
                return future

            with patch.object(pool, "submit", observed_submit):
                yield pool

    def observed_result(future, *args, **kwargs):
        if (get_ident() != caller or active is None
                or sys._getframe(1).f_code is not prepare_code):
            return get_result(future, *args, **kwargs)
        row = windows[purpose]
        task = row.writes[future]
        if task.wait is not None or row.end is not None:
            raise ValueError("staging write future awaited more than once")
        first = future is next(iter(row.writes))
        last = future is next(reversed(row.writes))
        start = clock()
        if first and control is not None:
            control(purpose, "inside")
        result = get_result(future, *args, **kwargs)
        end = clock()
        task.wait = (start, end)
        if last:
            row.end = end
            end_entry()
            if control is not None:
                control(purpose, "after")
        return result

    with (
        patch.object(transaction_type, "commit", observed_commit),
        patch.object(transaction_type, "_prepare_pool_scope", observed_pool_scope),
        patch.object(Future, "result", observed_result),
    ):
        yield windows


def summarize(windows, start, end, index_span):
    if tuple(windows) != PURPOSES:
        raise ValueError("expected one staging writer window per Capture commit")
    index_start, index_end = index_span
    spans, by_purpose, writes = {}, {}, {}
    previous = start
    for purpose, window in windows.items():
        if not (window.start and window.end and window.writes):
            raise ValueError("missing successful staging writer window")
        left, right = window.start, window.end
        if not previous <= left[0] < right[0] <= index_start[0]:
            raise ValueError("staging writer windows are out of order")
        previous = right[0]
        tasks = list(window.writes.values())
        last_return = left
        for task in tasks:
            if (task.worker is None or task.wait is None
                    or task.kind not in ("candidates", "preimages")):
                raise ValueError("missing successful staging task or future result")
            wait_start, wait_end = task.wait
            if not (
                last_return[0] <= wait_start[0] <= wait_end[0] <= right[0]
                and last_return[1] <= wait_start[1] <= wait_end[1] <= right[1]
            ):
                raise ValueError("staging writer waits are out of order")
            last_return = wait_end
        if last_return != right:
            raise ValueError("staging writer window ends after the last future")
        spans[purpose] = (left[0], right[0])
        by_purpose[purpose] = {
            "wall_ns": right[0] - left[0],
            "thread_cpu_ns": right[1] - left[1],
            "wait_wall_ns": sum(w.wait[1][0] - w.wait[0][0] for w in tasks),
            "wait_cpu_ns": sum(w.wait[1][1] - w.wait[0][1] for w in tasks),
            "staged_sizes": sorted((w.kind, w.size) for w in tasks),
        }
        writes[purpose] = [{"wait": w.wait, "worker": w.worker} for w in tasks]
    if not previous <= index_start[0] <= index_end[0] <= end:
        raise ValueError("index refresh is outside the selected probe")
    return spans, writes, {
        "by_purpose": by_purpose,
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }
