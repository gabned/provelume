"""Private recorded assessments and explicit removal; no inference/apply route."""

from contextlib import suppress

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from .ai_activity import reason_key
from .ai_job_contract import check
from .scheduler_model import SchedulerBusyError


def attach_classification_routes(app, setup, *, page, fields, redirect, local, mutation,
                                 launch_job, tasks):
    producer = setup.classification

    def error(request, exc):
        key = reason_key(getattr(exc, "code", exc.args[0] if exc.args else None))
        return page(request, error=True, status_code=409, error_key=key)

    def selected_preview(document_id, values):
        document = setup.instance.get_document(document_id)
        check(document is not None and document["current_version"] is not None
              and document["current_version"]["id"] == values["version_id"], "ai_setup_stale")
        choice = values["selection"].split(":")
        check(len(choice) == 2, "ai_context_mismatch")
        targets = producer.group_targets(document_id, values["target_kind"])
        return producer.preview(document_id, *choice, targets.allowlist, values["language"])

    def preview_page(request, result):
        ref, prepared, document = result
        return page(request, "ai_classification_request.html", phase="preview", ref=ref,
                    prepared=prepared, document=document, payload=setup.payload(prepared))

    @app.get("/documents/{document_id}/classification")
    def selection(request: Request, document_id: str):
        local(request)
        try:
            document, choices = setup.synthesis.choices(document_id)
            return page(request, "ai_classification_request.html", phase="selection",
                        document=document, choices=choices)
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)

    @app.post("/documents/{document_id}/classification/preview")
    async def preview(request: Request, document_id: str):
        values = await fields(request, {"selection", "version_id", "target_kind", "language"})
        try:
            result = await mutation(selected_preview, document_id, values)
            return await run_in_threadpool(preview_page, request, result)
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await run_in_threadpool(error, request, exc)

    @app.post("/documents/{document_id}/classification/verify-preview")
    async def verify_preview(request: Request, document_id: str):
        values = await fields(request, {"selection", "version_id", "target_kind", "language"})
        try:
            original = await mutation(selected_preview, document_id, values)
            result = await mutation(setup.verify_preview, original[0], fresh=True)
            return await run_in_threadpool(preview_page, request, result)
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await run_in_threadpool(error, request, exc)

    @app.post("/operations/ai/classification/execute")
    async def execute(request: Request):
        values = await fields(request, {"ref", "acknowledge"})
        try:
            check(values["acknowledge"] == "selected-document", "ai_consent_missing")
            row = setup.previews.get(values["ref"])
            check(row is not None and "classification_targets" in row, "ai_consent_missing")
            check(len(tasks) < 2, "ai_limit_exceeded")
            await mutation(setup.approve_generation, values["ref"])
            job = await mutation(setup.enqueue, values["ref"])
            if job["status"] == "queued":
                await launch_job(job["id"])
            return redirect(request, "/operations/ai")
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await run_in_threadpool(error, request, exc)

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
