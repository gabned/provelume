"""Observe destination path validation in the acquisition's publication call."""

import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import get_ident
from unittest.mock import patch

PURPOSES = ("capture-instance-target",)


@dataclass
class Publication:
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None
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
    commit = transaction_type.commit
    publish = transaction_type._publish_entries
    instance_target = atomic._instance_target
    acquire_code = adapter.CaptureAdapter._acquire_locked.__code__
    commit_code = transaction_type._commit_with_pool.__code__
    publish_code = publish.__code__
    row = Publication()
    active = None
    in_publication = False
    rows = []

    def observed_commit(transaction):
        nonlocal active
        if get_ident() != caller or sys._getframe(1).f_code is not acquire_code:
            return commit(transaction)
        if rows or active is not None:
            raise ValueError("multiple acquisition commits in one selected Capture")
        active = transaction
        try:
            result = commit(transaction)
        finally:
            active = None
        rows.append(row)
        return result

    def observed_publish(transaction, stage, manifest, pool):
        nonlocal in_publication
        if (
            get_ident() != caller or active is None or active is not transaction
            or sys._getframe(1).f_code is not commit_code
        ):
            return publish(transaction, stage, manifest, pool)
        if row.start is not None or pool is not transaction._transaction_pool:
            raise ValueError("expected one publication through the acquisition pool")
        begin_entry()
        row.start = clock()
        in_publication = True
        try:
            result = publish(transaction, stage, manifest, pool)
        finally:
            in_publication = False
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

    directories = set()

    def observed_target(store, relative, *, error_type):
        if (
            get_ident() != caller or not in_publication
            or sys._getframe(1).f_code is not publish_code
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
        row.start and row.end and row.worker_tids and row.calls
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
    previous = left
    for call_start, call_end, depth in row.calls:
        if not (
            previous[0] <= call_start[0] < call_end[0] <= right[0]
            and previous[1] <= call_start[1] <= call_end[1] <= right[1]
            and depth > 0
        ):
            raise ValueError("destination validations are not ordered within publication")
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
