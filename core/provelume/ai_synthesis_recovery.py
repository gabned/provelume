"""Explicit, bounded disposal after the existing job owner proves quiescence."""

from __future__ import annotations

import hashlib
import os

from .ai_contract import digest
from .ai_job_contract import check, fingerprint
from .maintenance_local_files import open_local_file, pinned_parent
from .scheduler_model import TERMINAL_JOB_STATUSES


def _candidate(synthesis, job_id):
    from .ai_synthesis import MAX_RESULT_BYTES

    setup = synthesis.setup
    check(setup.instance.store.read_config()["instance"]["id"] == setup.instance_id,
          "ai_wrong_instance")
    path = synthesis.path(job_id)
    job = setup.jobs.journal.get_job(job_id)
    check(job is not None and job["job_kind"] == "ai.execute"
          and job["status"] in TERMINAL_JOB_STATUSES and job["lease"] is None,
          "ai_reconciliation_required")
    ai = job["ai"]
    check(ai["terminal"] in {"failed", "cancelled", "uncertain"}
          and ai["result"] is None and bool(ai["attempts"]), "ai_reconciliation_required")
    check(all(row["phase"] in {"settled", "released"} and row["quiescent"] is True
              for row in ai["attempts"]), "ai_reconciliation_required")
    # Lease expiry is not evidence of process death. The original reconciliation
    # operation must first record explicit quiescence for an uncertain outcome.
    check(ai["terminal"] != "uncertain" or bool(ai["attempts"][-1]["reconciliations"]),
          "ai_reconciliation_required")
    with open_local_file(path) as stream:
        raw = stream.read(MAX_RESULT_BYTES + 1)
    check(len(raw) <= MAX_RESULT_BYTES, "ai_limit_exceeded")
    return {"bytes": len(raw), "revision": digest({
        "instance": setup.instance_id, "job": job, "control": setup.jobs._control(),
        "session": setup.jobs.session_authorized,
        "body": hashlib.sha256(raw).hexdigest(),
    })}


def candidate(synthesis, job_id):
    with synthesis.setup.jobs._transaction(wait_seconds=2):
        return _candidate(synthesis, job_id)


def discard(synthesis, job_id, revision):
    fingerprint(revision)
    with synthesis.setup.jobs._transaction(wait_seconds=2):
        observed = _candidate(synthesis, job_id)
        check(observed["revision"] == revision, "ai_setup_stale")
        with pinned_parent(synthesis.path(job_id)) as (path, parent):
            if os.name == "nt":
                path.unlink()
            else:
                os.unlink(path.name, dir_fd=parent)
        # No job, receipt, usage, reservation, consent or retry state is changed.
