"""Observer prototype for the #439 lifecycle-entry hypothesis.

Apply only in a disposable diagnostic process. No evaluator, wait policy,
transaction, or underlying function is replaced by a substitute implementation.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from itertools import pairwise
from threading import get_ident
from time import monotonic_ns, thread_time_ns
from unittest.mock import patch

CAPTURE_PURPOSES = ("capture-submit", "capture-acquire")
INDEX_PURPOSE = "search-index-refresh"
PURPOSES = (*CAPTURE_PURPOSES, INDEX_PURPOSE)
_ACTIVE_ENTRY = ContextVar("s07_lifecycle_window", default=None)


def entry_purpose():
    """Identify the caller's currently observed pre-yield entry, if any."""
    row = _ACTIVE_ENTRY.get()
    return row.purpose if row is not None and row.caller == get_ident() else None


@dataclass
class Window:
    purpose: str
    caller: int
    entered: tuple[int, int]
    lock_acquired: tuple[int, int] | None = None
    ready: tuple[int, int] | None = None
    body_done: tuple[int, int] | None = None
    exited: tuple[int, int] | None = None
    lock_calls: int = 0

    def complete(self):
        marks = (self.entered, self.lock_acquired, self.ready, self.body_done, self.exited)
        return self.lock_calls == 1 and all(mark is not None for mark in marks) and all(
            first[0] <= second[0] and first[1] <= second[1]
            for first, second in pairwise(marks)
        )


@contextmanager
def observe(lifecycle, *, clock=None, begin_entry, end_entry):
    """Scope the observer to a caller running one declared original probe."""
    if clock is None:
        def clock():
            return monotonic_ns(), thread_time_ns()

    owner = get_ident()
    rows = []
    acquire = lifecycle._acquire_os_lock
    hold = lifecycle.InstanceLifecycleManager._hold

    def observed_acquire(descriptor):
        row = _ACTIVE_ENTRY.get()
        if row is None or row.caller != get_ident():
            return acquire(descriptor)
        row.lock_calls += 1
        result = acquire(descriptor)
        row.lock_acquired = clock()
        begin_entry()
        return result

    @contextmanager
    def observed_hold(manager, *, purpose, wait_seconds=0):
        if get_ident() != owner or purpose not in PURPOSES or _ACTIVE_ENTRY.get() is not None:
            token = _ACTIVE_ENTRY.set(None)
            try:
                with hold(manager, purpose=purpose, wait_seconds=wait_seconds) as value:
                    yield value
            finally:
                _ACTIVE_ENTRY.reset(token)
            return
        row = Window(purpose=purpose, caller=owner, entered=clock())
        token = _ACTIVE_ENTRY.set(row)
        rows.append(row)
        try:
            with hold(manager, purpose=purpose, wait_seconds=wait_seconds) as value:
                end_entry()
                row.ready = clock()
                # Do not count a lock acquired by the application body as entry.
                _ACTIVE_ENTRY.reset(token)
                token = None
                try:
                    yield value
                finally:
                    row.body_done = clock()
        finally:
            row.exited = clock()
            if token is not None:
                _ACTIVE_ENTRY.reset(token)

    with (
        patch.object(lifecycle, "_acquire_os_lock", observed_acquire),
        patch.object(lifecycle.InstanceLifecycleManager, "_hold", observed_hold),
    ):
        yield rows


def summarize(rows, probe_start_ns, probe_end_ns, index_span):
    """Bind the three holds to the probe and the index hold to the index call."""
    if tuple(row.purpose for row in rows) != PURPOSES:
        raise ValueError("unexpected Capture lifecycle calls")
    previous = probe_start_ns
    by_purpose = {}
    for row in rows:
        if not row.complete() or not previous <= row.entered[0] <= row.exited[0] <= probe_end_ns:
            raise ValueError("incomplete, overlapping, or unbound lifecycle window")
        by_purpose[row.purpose] = {
            "hold_wall_ns": row.exited[0] - row.entered[0],
            "pre_yield_wall_ns": row.ready[0] - row.lock_acquired[0],
            "pre_yield_thread_cpu_ns": row.ready[1] - row.lock_acquired[1],
            "body_wall_ns": row.body_done[0] - row.ready[0],
        }
        previous = row.exited[0]
    index = rows[-1]
    start, end = index_span
    if not (
        rows[1].exited[0] <= start[0] <= index.entered[0] <= index.exited[0] <= end[0]
        and end[0] <= probe_end_ns
        and start[1] <= index.entered[1] <= index.exited[1] <= end[1]
    ):
        raise ValueError("search-index hold is not bound to its refresh call")
    return {
        "by_purpose": by_purpose,
        "capture_pre_yield_wall_ns": sum(
            by_purpose[purpose]["pre_yield_wall_ns"] for purpose in CAPTURE_PURPOSES
        ),
        "search_index": {"wall_ns": end[0] - start[0], "thread_cpu_ns": end[1] - start[1]},
    }
