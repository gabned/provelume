"""Measure only direct Capture journal inventories on the calling thread."""

import sys
from contextlib import contextmanager
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-submit", "capture-acquire")


@contextmanager
def observe(journal, adapter, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    original = journal.CaptureJournal._inventory
    call_sites = {
        journal.CaptureJournal.submit.__code__: PURPOSES[0],
        adapter.CaptureAdapter._submission_locked.__code__: PURPOSES[1],
    }
    rows = []

    def measure(instance):
        purpose = call_sites.get(sys._getframe(1).f_code)
        if get_ident() != caller or purpose is None:
            return original(instance)
        start = clock()
        begin_entry()
        try:
            if control is not None:
                control(purpose)
            records = original(instance)
        finally:
            end_entry()
        rows.append((purpose, start, clock(), len(records)))
        return records

    with patch.object(journal.CaptureJournal, "_inventory", measure):
        yield rows


def summarize(rows, start, end, index_span):
    if tuple(row[0] for row in rows) != PURPOSES:
        raise ValueError("unexpected direct Capture inventory calls")
    previous = start
    spans = {}
    by_purpose = {}
    for purpose, left, right, entries in rows:
        if not previous <= left[0] < right[0] <= end or not left[1] <= right[1]:
            raise ValueError("incomplete or overlapping Capture inventory")
        spans[purpose] = (left[0], right[0])
        by_purpose[purpose] = {
            "inventory_wall_ns": right[0] - left[0],
            "inventory_thread_cpu_ns": right[1] - left[1],
            "records": entries,
        }
        previous = right[0]
    index_start, index_end = index_span
    if not previous <= index_start[0] <= index_end[0] <= end or index_start[1] > index_end[1]:
        raise ValueError("index refresh overlaps a direct inventory")
    return spans, {
        "by_purpose": by_purpose,
        "capture_inventory_wall_ns": sum(row["inventory_wall_ns"] for row in by_purpose.values()),
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }
