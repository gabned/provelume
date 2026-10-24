"""Frozen prospective Capture comparison; temporary observer outside PRODUCT."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import UUID


def snapshot(root):
    rows = {}
    for folder in ("knowledge", "originals", "state/capture", "state/capture-processing",
                   "state/derived"):
        base = root / folder
        for path in sorted(base.rglob("*")):
            if path.is_file():
                rows[path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes()).hexdigest()
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--initialise", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", choices=(
        "ordinary", "owner_delay", "canonical_delay", "canonical_error"))
    parser.add_argument("--arm", choices=("A1", "B1", "B2", "A2"))
    parser.add_argument("--expected-head")
    args = parser.parse_args()
    source = args.source.absolute()
    for path in (source, source / "scripts", source / "core"):
        sys.path.insert(0, str(path))
    import ai_runtime_report

    from provelume.service import ProvelumeInstance

    if args.initialise:
        ProvelumeInstance.initialise(args.fixture)
        return 0
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if head != args.expected_head or subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=source, text=True).strip():
        raise ValueError("source identity or clean-tree mismatch")
    args.output.mkdir(parents=True, exist_ok=False)
    instance_path = args.output / "private-work/instance"
    shutil.copytree(args.fixture, instance_path)
    instance = ProvelumeInstance(instance_path)
    lock_path = instance_path.parent / ".instance.provelume/lifecycle.lock.json"
    for name, module in list(sys.modules.items()):
        if name.startswith("provelume.") and callable(getattr(module, "utc_now", None)):
            module.utc_now = lambda: "2026-10-24T00:00:00+00:00"
    ids = iter(UUID(f"00000000-0000-4000-8000-{index:012d}") for index in range(1, 4))
    ai_runtime_report.uuid4 = lambda: next(ids)
    original = os.fsync
    events, rows = [], []
    guard = threading.Lock()
    counts = {}
    current = {"index": None, "first_payload": True}

    def observed_sync(descriptor):
        observed = os.fstat(descriptor)
        path = os.readlink(f"/proc/self/fd/{descriptor}")
        category = (
            "owner" if Path(path) == lock_path else
            "directory" if stat.S_ISDIR(observed.st_mode) else
            "journal_payload" if "/transactions/" in path and (
                "/candidates/" in path or "/preimages/" in path) else
            "manifest" if path.endswith("/manifest.json") else "other_file"
        )
        with guard:
            counts[category] = counts.get(category, 0) + 1
            reject = (args.case == "canonical_error" and category == "journal_payload"
                      and current["first_payload"])
            if reject:
                current["first_payload"] = False
        delay = (.18 if args.case == "owner_delay" and category == "owner" else
                 .06 if args.case == "canonical_delay" and category == "journal_payload" else 0)
        started, cpu, error = time.monotonic(), time.thread_time(), None
        try:
            if delay:
                time.sleep(delay)
            if reject:
                raise OSError("synthetic canonical fsync failure")
            return original(descriptor)
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            event = {"capture": current["index"], "category": category,
                     "injected_delay_seconds": delay, "seconds": time.monotonic()-started,
                     "thread_cpu_seconds": time.thread_time()-cpu, "error": error}
            with guard:
                if len(events) >= 1024:
                    raise ValueError("frozen event bound")
                events.append(event)

    initial = snapshot(instance_path)
    started = time.monotonic()
    os.fsync = observed_sync
    try:
        for index in range(3):
            current.update(index=index, first_payload=True)
            at = time.monotonic()
            row = {"index":index, "outcome":None, "error":None}
            try:
                row["outcome"] = ai_runtime_report.deterministic_probe(instance, index)
                row["status"] = "SUCCEEDED"
            except Exception as exc:
                row.update(status="REFUSED", error=type(exc).__name__)
            row["elapsed_seconds"] = time.monotonic()-at
            rows.append(row)
    finally:
        os.fsync = original
    elapsed = time.monotonic()-started
    final = snapshot(instance_path)
    result = {"classification":"CONTROLLED_PROSPECTIVE_MECHANISM_NOT_QUALIFICATION",
              "head":head, "arm":args.arm, "case":args.case, "rows":rows,
              "elapsed_seconds":elapsed, "events":events, "fsync_counts":counts,
              "snapshot":final, "initial_snapshot":initial,
              "historical_cause":"UNKNOWN"}
    encoded = (json.dumps(result, indent=2)+"\n").encode()
    if len(encoded) > 2*1024*1024:
        raise ValueError("frozen result byte bound")
    (args.output / "observation.json").write_bytes(encoded)
    # Only explicit observer metadata and hashes leave the work directory.
    shutil.rmtree(args.output / "private-work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
