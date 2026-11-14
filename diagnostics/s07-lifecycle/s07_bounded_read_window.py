"""Measure only _prepare's synchronous reads of Capture destinations."""

import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-submit", "capture-process")


@dataclass
class Reads:
    expected: int
    calls: list = field(default_factory=list)


@contextmanager
def observe(atomic, adapter, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    transaction_type = atomic.AtomicInstanceCommit
    commit = transaction_type.commit
    prepare_code = transaction_type._prepare.__code__
    read = atomic._bounded_file_bytes
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

    def observed_read(path, **kwargs):
        if (get_ident() != caller or active is None
                or sys._getframe(1).f_code is not prepare_code):
            return read(path, **kwargs)
        first = purpose not in windows
        if first:
            row = windows[purpose] = Reads(len(active._writes))
            begin_entry()
            if control is not None:
                control(purpose, "before")
        else:
            row = windows[purpose]
        if len(row.calls) >= row.expected or not kwargs["missing_ok"]:
            raise ValueError("unexpected Capture destination read")
        left = clock()
        if first and control is not None:
            control(purpose, "inside")
        result = read(path, **kwargs)
        right = clock()
        if len(row.calls) + 1 == row.expected:
            end_entry()
        if first and control is not None:
            control(purpose, "after")
        root = active.store.paths.root
        row.calls.append((left, right, (
            len(root.parts), len(path.relative_to(root).parts),
            result is not None, len(result) if result is not None else 0,
        )))
        return result

    with (
        patch.object(transaction_type, "commit", observed_commit),
        patch.object(atomic, "_bounded_file_bytes", observed_read),
    ):
        yield windows


def summarize(windows, start, end, index_span):
    if tuple(windows) != PURPOSES:
        raise ValueError("expected destination reads in both Capture commits")
    index_start, index_end = index_span
    spans, calls, by_purpose = {}, {}, {}
    previous = start
    for purpose, row in windows.items():
        if not row.expected or len(row.calls) != row.expected:
            raise ValueError("missing _prepare destination reads")
        for left, right, _ in row.calls:
            if not (
                previous <= left[0] <= right[0] <= index_start[0] and left[1] <= right[1]
            ):
                raise ValueError("Capture destination reads are out of order")
            previous = right[0]
        spans[purpose] = row.calls[0][0][0], row.calls[-1][1][0]
        calls[purpose] = row.calls
        shapes = [shape for _, _, shape in row.calls]
        by_purpose[purpose] = {
            "wall_ns": sum(right[0] - left[0] for left, right, _ in row.calls),
            "thread_cpu_ns": sum(right[1] - left[1] for left, right, _ in row.calls),
            "calls": len(shapes),
            "present": sum(present for _, _, present, _ in shapes),
            "bytes_read": sum(size for _, _, _, size in shapes),
            "read_shape": shapes,
        }
    if not previous <= index_start[0] <= index_end[0] <= end:
        raise ValueError("index refresh is outside the selected probe")
    return spans, calls, {
        "by_purpose": by_purpose,
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }
