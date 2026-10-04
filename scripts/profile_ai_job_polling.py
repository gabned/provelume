"""Paired synthetic S06 polling profile; no worker, credential or network.

The baseline disables only reuse of the pure calculation, preserving all current
reads, locks and checks. This is a development measurement, not native qualification.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from ai_jobs_fakes import BUDGET, REF, manager  # noqa: E402

from provelume.ai_job_runtime import JobOutcome  # noqa: E402
from provelume.service import ProvelumeInstance  # noqa: E402


def measure(root, *, reuse, polls):
    instance = ProvelumeInstance.initialise(root)
    jobs, _ = manager(instance.root)
    assert jobs.status()["mode"] == "off"
    jobs.configure(mode="enabled", budget=BUDGET)
    sample = {}
    authoritative = jobs.current
    reads = 0

    def current(*args):
        nonlocal reads
        reads += 1
        return authoritative(*args)

    class Probe:
        network_used = False

        def exchange(self, current, *, cancel):
            current().prepare()
            before = reads
            wall, cpu = time.perf_counter(), time.thread_time()
            for _ in range(polls):
                assert not cancel()
            sample.update(seconds=time.perf_counter() - wall, cpu_seconds=time.thread_time() - cpu)
            assert reads - before == polls
            return JobOutcome({"kind": "untrusted_text", "value": "public fixture"}, 9, 0, "LOCAL")

    jobs.current = current
    jobs.adapters = {key: Probe() for key in jobs.adapters}
    job = jobs.enqueue(REF, request_key="profile", budget=BUDGET)
    baseline = patch(
        "provelume.ai_jobs._PollPreparation.__call__", lambda self, inputs: inputs.prepare())
    with nullcontext() if reuse else baseline:
        result = jobs.coordinator.run_one(job_id=job["id"])
    assert result["status"] == "succeeded" and len(jobs.journal.list_receipts()) == 1
    return sample


def main():
    (ROOT / ".agent").mkdir(exist_ok=True)
    report = {"scope": "synthetic current-authority polling only", "polls_per_sample": 200,
              "baseline": [], "reuse": []}
    with tempfile.TemporaryDirectory(prefix="s06-poll-", dir=ROOT / ".agent") as directory:
        for pair in range(5):
            # Alternate order, retain every sample; no outlier filtering.
            for reuse in ((False, True) if pair % 2 == 0 else (True, False)):
                name = "reuse" if reuse else "baseline"
                report[name].append(
                    measure(Path(directory) / f"{pair}-{name}", reuse=reuse, polls=200))
    report["median"] = {
        name: {key: statistics.median(r[key] for r in report[name])
               for key in ("seconds", "cpu_seconds")}
        for name in ("baseline", "reuse")
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
