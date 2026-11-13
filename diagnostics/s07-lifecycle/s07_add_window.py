"""Observe destination path validation while registering Capture acquisition entries."""

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-add-instance-target",)


@dataclass
class Acquisition:
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None
    commit_start: tuple[int, int] | None = None
    publish_span: tuple[int, int] | None = None
    calls: list = field(default_factory=list)
    root_depth: int | None = None
    worker_tids: tuple[int, ...] = ()
    entries: int = 0
    preimages: int = 0
    destination_directories: int = 0


@contextmanager
def observe(atomic, adapter, *, clock, begin_entry, end_entry, control):
    caller = get_ident()
    transaction_type = atomic.AtomicInstanceCommit
    add = transaction_type.add
    commit = transaction_type.commit
    publish = transaction_type._publish_entries
    instance_target = atomic._instance_target
    acquire_code = adapter.CaptureAdapter._acquire_locked.__code__
    commit_code = transaction_type._commit_with_pool.__code__
    add_code = add.__code__
    row = Acquisition()
    active = None
    in_add = False
    directories = set()
    rows = []

    def observed_add(transaction, relative, data, *, immutable):
        nonlocal active, in_add
        if get_ident() != caller or sys._getframe(1).f_code is not acquire_code:
            return add(transaction, relative, data, immutable=immutable)
        if active is None:
            active = transaction
            begin_entry()
            row.start = clock()
        if transaction is not active or row.commit_start is not None:
            raise ValueError("Capture entry registered outside the selected acquisition")
        count = len(row.calls)
        in_add = True
        try:
            result = add(transaction, relative, data, immutable=immutable)
        finally:
            in_add = False
        if len(row.calls) != count + 1:
            raise ValueError("expected one destination validation in add")
        return result

    def observed_commit(transaction):
        if get_ident() != caller or sys._getframe(1).f_code is not acquire_code:
            return commit(transaction)
        if rows or transaction is not active or row.commit_start is not None:
            raise ValueError("commit differs from the acquisition that registered the entries")
        row.commit_start = clock()
        result = commit(transaction)
        rows.append(row)
        return result

    def observed_publish(transaction, stage, manifest, pool):
        if (
            get_ident() != caller or transaction is not active
            or sys._getframe(1).f_code is not commit_code
        ):
            return publish(transaction, stage, manifest, pool)
        if row.publish_span is not None or pool is not transaction._transaction_pool:
            raise ValueError("expected one publication through the acquisition pool")
        start = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        try:
            result = publish(transaction, stage, manifest, pool)
        finally:
            row.publish_span = start, time.clock_gettime_ns(time.CLOCK_BOOTTIME)
            row.end = clock()
            end_entry()
        entries = manifest["entries"]
        if any(entry.get("operation", "write") != "write" for entry in entries):
            raise ValueError("expected write-only Capture entries")
        row.entries = len(entries)
        row.preimages = sum(entry["had_preimage"] for entry in entries)
        tids = [worker.native_id for worker in pool._threads]
        if not tids or None in tids or len(set(tids)) != len(tids):
            raise ValueError("missing or repeated acquisition pool worker identity")
        row.worker_tids = tuple(sorted(tids))
        return result

    def observed_target(store, relative, *, error_type):
        if (
            get_ident() != caller or not in_add or sys._getframe(1).f_code is not add_code
        ):
            return instance_target(store, relative, error_type=error_type)
        first = not row.calls
        start = clock()
        if first and control is not None:
            control("inside-first-target")
        result = instance_target(store, relative, error_type=error_type)
        end = clock()
        if first and control is not None:
            control("after-first-target")
        root = store.paths.root
        target = result[0].relative_to(root)
        directories.add(target.parent)
        row.destination_directories = len(directories)
        row.root_depth = len(root.parts) - 1
        row.calls.append((start, end, len(target.parts)))
        return result

    with (
        patch.object(transaction_type, "add", observed_add),
        patch.object(transaction_type, "commit", observed_commit),
        patch.object(transaction_type, "_publish_entries", observed_publish),
        patch.object(atomic, "_instance_target", observed_target),
    ):
        yield rows


def summarize(rows, start, end, index_span, expected_root_depth):
    if len(rows) != 1:
        raise ValueError("expected one acquisition commit")
    row = rows[0]
    if not (
        row.start and row.end and row.commit_start and row.publish_span and row.worker_tids
        and len(row.calls) >= 2
        and len(row.calls) == row.entries
    ):
        raise ValueError("missing destination validation for a Capture entry")
    if row.root_depth != expected_root_depth:
        raise ValueError("Capture root depth differs from the configured probe depth")
    left, right = row.start, row.end
    index_start, index_end = index_span
    if not (
        start <= left[0] < right[0] <= index_start[0] <= index_end[0] <= end
        and left[1] <= right[1] <= index_start[1] <= index_end[1]
    ):
        raise ValueError("publication does not precede the separate index refresh")
    commit_start = row.commit_start
    previous = left
    for call_start, call_end, depth in row.calls:
        if not (
            previous[0] <= call_start[0] < call_end[0] <= commit_start[0]
            and previous[1] <= call_start[1] <= call_end[1] <= commit_start[1]
            and depth > 0
        ):
            raise ValueError("destination validations are not ordered before commit")
        previous = call_end
    return {PURPOSES[0]: (left[0], right[0])}, {
        "by_purpose": {PURPOSES[0]: {
            "wall_ns": sum(right[0] - left[0] for left, right, _ in row.calls),
            "thread_cpu_ns": sum(right[1] - left[1] for left, right, _ in row.calls),
            "entries": row.entries,
            "preimages": row.preimages,
            "destination_directories": row.destination_directories,
            "root_depth": row.root_depth,
            "relative_depths": sorted(depth for _, _, depth in row.calls),
        }},
        "search_index": {"wall_ns": index_end[0] - index_start[0],
                         "thread_cpu_ns": index_end[1] - index_start[1]},
    }
