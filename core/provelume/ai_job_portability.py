"""Conservative AI settlement in existing staged restore/import transactions."""

from __future__ import annotations

import copy

from .ai_job_contract import AI_JOB_KIND, check
from .ai_jobs import AiJobs, finish_ai_locked
from .scheduler import SchedulerCoordinator, SchedulerStore
from .scheduler_model import TERMINAL_JOB_STATUSES, utc_instant


def prepare_restored_ai(staged_store, previous_store=None):
    """Called before atomic directory publication, under the lifecycle exclusion.

    A backup cannot erase later local liabilities. A portable Instance carrying AI
    accounting may only replace the same Instance. An empty new destination still
    requires explicit same-Instance restore, not identity rebinding.
    """
    target = SchedulerStore(staged_store)
    old = SchedulerStore(previous_store) if previous_store is not None else None
    incoming = {j["id"]: j for j in target._all_jobs() if j["job_kind"] == AI_JOB_KIND}
    retained = {j["id"]: j for j in old._all_jobs() if j["job_kind"] == AI_JOB_KIND} if old else {}
    if (
        not incoming
        and not retained
        and not (target.root / "ai-control.json").exists()
        and (old is None or not (old.root / "ai-control.json").exists())
    ):
        return
    check(old is None or target.instance_id == old.instance_id, "ai_wrong_instance")
    with target.hold():
        for job_id, job in retained.items():
            previous = incoming.get(job_id)
            if previous is not None:
                check(
                    job["ai"]["binding"] == previous["ai"]["binding"]
                    and job["attempt"] >= previous["attempt"]
                    and utc_instant(job["updated_at"]) >= utc_instant(previous["updated_at"]),
                    "ai_restore_history_conflict",
                )
            incoming[job_id] = copy.deepcopy(job)
            target._write_policy(old.get_policy(job["policy_id"]))
            receipt_id = "receipt_" + job_id.removeprefix("job_")
            receipt = old.get_receipt(receipt_id)
            if receipt is not None:
                # The staged archive is unpublished; preserve the current immutable receipt.
                staged_store._atomic_json(target.receipts / (receipt_id + ".json"), receipt)
        manager = AiJobs(SchedulerCoordinator(staged_store))
        control = manager._control()
        if old:
            current = AiJobs(SchedulerCoordinator(previous_store))._control()
            if current["budget"] is not None:
                control["budget"] = current["budget"]
            control["generation"] = max(control["generation"], current["generation"])
            control["revoked"] = sorted(set(control["revoked"]) | set(current["revoked"]))
        control.update(mode="off", generation=control["generation"] + 1)
        manager._save_control(control)
        for job in incoming.values():
            job["ai"]["restored"] = True
            if job["status"] not in TERMINAL_JOB_STATUSES and job["ai"]["terminal"] is None:
                if job["lease"]:
                    # A stale portable RESERVED snapshot cannot prove no later transmission.
                    job["ai"]["attempts"][-1].update(phase="uncertain", quiescent=False)
                    job["ai"].update(terminal="uncertain", blocked="ai_restore_uncertain")
                else:
                    job["ai"].update(
                        terminal="cancelled", blocked="ai_restored_requires_new_request"
                    )
            job = target._write_job(job)
            if job["status"] not in TERMINAL_JOB_STATUSES:
                finish_ai_locked(target, job, utc_instant())
