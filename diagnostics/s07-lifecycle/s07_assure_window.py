"""Measure the Capture acquisition's post-commit integrity readback."""

import sys
from contextlib import contextmanager
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-assure",)


@contextmanager
def observe(adapter, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    acquire_code = adapter.CaptureAdapter._acquire_locked.__code__
    assure = adapter.CaptureAdapter._assure
    read = adapter._read
    active = False
    read_calls = 0
    read_bytes = 0
    rows = []

    def observed_read(*args, **kwargs):
        nonlocal read_calls, read_bytes
        result = read(*args, **kwargs)
        if active and get_ident() == caller:
            read_calls += 1
            read_bytes += len(result)
        return result

    def observed_assure(instance, receipt, submission, payload, *, candidates=None):
        nonlocal active
        if (
            get_ident() != caller or sys._getframe(1).f_code is not acquire_code
            or candidates is not None
        ):
            return assure(instance, receipt, submission, payload, candidates=candidates)
        if active or rows:
            raise ValueError("multiple post-commit Capture readbacks in one selected probe")
        start = clock()
        begin_entry()
        active = True
        try:
            if control is not None:
                control("before-readback")
            result = assure(instance, receipt, submission, payload)
        finally:
            active = False
            end_entry()
        finish = clock()
        rows.append((start, finish, {
            "read_calls": read_calls,
            "read_bytes": read_bytes,
            "payload_bytes": len(payload),
            "derived_checked": receipt["processing"]["artifact_id"] is not None,
        }))
        if control is not None:
            control("after-readback")
        return result

    with (
        patch.object(adapter.CaptureAdapter, "_assure", observed_assure),
        patch.object(adapter, "_read", observed_read),
    ):
        yield rows


def summarize(rows, start, end, index_span):
    if len(rows) != 1:
        raise ValueError("expected one post-commit Capture readback")
    left, right, shape = rows[0]
    index_start, index_end = index_span
    if not (
        start <= left[0] < right[0] <= index_start[0] <= index_end[0] <= end
        and left[1] <= right[1] <= index_start[1] <= index_end[1]
        and shape["read_calls"] > 0
    ):
        raise ValueError("incomplete readback or overlapping index refresh")
    return {PURPOSES[0]: (left[0], right[0])}, {
        "by_purpose": {PURPOSES[0]: {
            "wall_ns": right[0] - left[0],
            "thread_cpu_ns": right[1] - left[1],
            **shape,
        }},
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }
