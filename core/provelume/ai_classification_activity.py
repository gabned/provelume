"""Private recorded assessments and explicit removal; no inference/apply route."""

from contextlib import suppress

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from .ai_activity import reason_key
from .ai_job_contract import check
from .scheduler_model import SchedulerBusyError


def attach_classification_routes(app, setup, *, page, fields, redirect, local, mutation):
    producer = setup.classification

    def error(request, exc):
        key = reason_key(getattr(exc, "code", exc.args[0] if exc.args else None))
        return page(request, error=True, status_code=409, error_key=key)

    @app.get("/operations/ai/{job_id}/classification")
    def result(request: Request, job_id: str):
        local(request)
        try:
            job, reference, selections = producer.reference(job_id)
            body, document, targets = None, None, None
            with suppress(ValueError, OSError, SchedulerBusyError):
                body, reference, document, job, targets = producer.read(job_id)
            return page(request, "ai_classification.html", job=job, reference=reference,
                        body=body, document=document, targets=targets,
                        document_id=selections[0].version.document_id)
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)

    @app.post("/operations/ai/{job_id}/classification/discard")
    async def discard(request: Request, job_id: str):
        await fields(request, set())
        try:
            await mutation(producer.discard, job_id)
            return redirect(request, f"/operations/ai/{job_id}/classification")
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await run_in_threadpool(error, request, exc)

    @app.post("/operations/ai/{job_id}/classification/cleanup")
    async def cleanup(request: Request, job_id: str):
        from .ai_synthesis_recovery import discard as discard_orphan

        values = await fields(request, {"revision", "acknowledge"})
        try:
            check(values["acknowledge"] == "discard-orphan", "ai_consent_missing")
            job = setup.jobs.journal.get_job(job_id)
            check(job is not None and job["job_kind"] == "ai.execute"
                  and job["ai"]["request"]["template"]["id"]
                  in {"classification-en-v1", "classification-it-v1"}, "ai_job_invalid")
            await mutation(discard_orphan, producer, job_id, values["revision"])
            return redirect(request, "/operations/ai")
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await run_in_threadpool(error, request, exc)
