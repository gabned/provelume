"""Local authenticated Browser controls for the existing AI services."""

from __future__ import annotations

import asyncio
import hmac
import secrets
from contextlib import suppress
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from .ai_jobs import ai_capabilities
from .ai_setup import AiSetup
from .shell_activity import MutationNonces, _loopback_request


def attach_ai_routes(app, instance, templates, context_factory):
    setup = AiSetup(instance)
    app.state.ai_setup = setup
    csrf = secrets.token_urlsafe(32)
    nonces = MutationNonces()
    tasks = set()
    app.state.ai_tasks = tasks

    def local(request):
        if not _loopback_request(request):
            raise HTTPException(403, "AI controls require the local browser")

    def page(request, name="ai_settings.html", *, status_code=200, **values):
        local(request)
        context = context_factory(request, instance, **values)
        context.update(
            ai=setup.read(),
            csrf_token=csrf,
            mutation_nonce=nonces.issue(),
            selected_instance_id=setup.instance_id,
        )
        response = templates.TemplateResponse(
            request=request, name=name, context=context, status_code=status_code
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    async def fields(request, required):
        local(request)
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != (
            "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "unsupported AI form")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise HTTPException(413, "AI form exceeds bound")
        try:
            raw = parse_qs(
                body.decode(), keep_blank_values=True, strict_parsing=True, max_num_fields=20
            )
        except (ValueError, UnicodeError):
            raise HTTPException(400, "invalid AI form") from None
        if set(raw) != required | {"csrf_token", "mutation_nonce", "instance_id"} or any(
            len(v) != 1 for v in raw.values()
        ):
            raise HTTPException(400, "invalid AI fields")
        result = {k: v[0] for k, v in raw.items()}
        if not hmac.compare_digest(result["csrf_token"], csrf):
            raise HTTPException(403, "invalid AI token")
        if result["instance_id"] != setup.instance_id:
            raise HTTPException(409, "AI Instance changed")
        if not nonces.consume(result["mutation_nonce"]):
            raise HTTPException(409, "AI form expired or already submitted")
        return result

    def redirect(request, path):
        language = context_factory(request, instance)["lang"]
        return RedirectResponse(
            f"{path}?lang={language}", status_code=303, headers={"Cache-Control": "no-store"}
        )

    def launch(function, *args, **kwargs):
        # One explicit operation, no periodic loop or second durable queue. AI jobs
        # are claimed/fenced/executed solely by the existing SchedulerCoordinator.
        async def run():
            with suppress(ValueError, OSError):
                await asyncio.to_thread(function, *args, **kwargs)

        task = asyncio.create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @app.get("/settings/ai")
    def settings(request: Request):
        return page(request)

    @app.post("/settings/ai")
    async def save(request: Request):
        values = await fields(
            request,
            {
                "revision",
                "mode",
                "endpoint",
                "model",
                "credential",
                "order",
                "job_units",
                "period_units",
            },
        )
        try:
            setup.save(
                {
                    k: (int(values[k]) if k.endswith("units") else values[k])
                    for k in (
                        "mode",
                        "endpoint",
                        "model",
                        "credential",
                        "order",
                        "job_units",
                        "period_units",
                    )
                },
                int(values["revision"]),
            )
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)
        return redirect(request, "/settings/ai")

    @app.post("/settings/ai/control")
    async def control(request: Request):
        values = await fields(request, {"action", "revision"})
        try:
            setup.control(values["action"], int(values["revision"]))
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)
        return redirect(request, "/settings/ai")

    @app.post("/settings/ai/model")
    async def model(request: Request):
        values = await fields(request, {"action", "path", "acknowledge"})
        try:
            if values["acknowledge"] != "explicit":
                raise ValueError("consent")
            identity = setup.begin_operation(values["action"])
            launch(setup.run_operation, identity, path=values["path"] or None)
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)
        return redirect(request, "/settings/ai")

    @app.post("/settings/ai/model/cancel")
    async def cancel_model(request: Request):
        values = await fields(request, {"operation_id"})
        try:
            setup.cancel_operation(values["operation_id"])
        except ValueError:
            return page(request, error=True, status_code=409)
        return redirect(request, "/settings/ai")

    @app.post("/settings/ai/test/preview")
    async def preview(request: Request):
        await fields(request, set())
        try:
            ref, prepared = setup.preview_test()
            return page(
                request,
                "ai_preview.html",
                ref=ref,
                prepared=prepared,
                payload=setup.payload(prepared),
                phase="preview",
            )
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)

    @app.post("/settings/ai/test/consent")
    async def consent(request: Request):
        values = await fields(request, {"ref", "acknowledge"})
        try:
            if values["acknowledge"] != "synthetic-test":
                raise ValueError("consent")
            setup.approve(values["ref"])
            prepared = setup.previews[values["ref"]]["prepared"]
            return page(
                request,
                "ai_preview.html",
                ref=values["ref"],
                prepared=prepared,
                payload=setup.payload(prepared),
                phase="consented",
            )
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)

    @app.post("/settings/ai/test/enqueue")
    async def enqueue(request: Request):
        values = await fields(request, {"ref"})
        try:
            setup.enqueue(values["ref"])
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)
        return redirect(request, "/operations/ai")

    @app.get("/operations/ai")
    def operations(request: Request):
        local(request)
        records = setup.jobs.journal.list_jobs(limit=100)
        jobs = [setup.jobs.public(j["id"]) for j in records if j["job_kind"] == "ai.execute"]
        revisions = {
            j["id"]: ai_capabilities(j)["revision"]
            for j in records
            if j["job_kind"] == "ai.execute"
        }
        receipts = [
            r for r in setup.jobs.journal.list_receipts(limit=100) if r["job_kind"] == "ai.execute"
        ]
        return page(
            request, "ai_operations.html", jobs=jobs, receipts=receipts, revisions=revisions
        )

    @app.post("/operations/ai/control")
    async def job_control(request: Request):
        values = await fields(request, {"job_id", "action", "revision"})
        try:
            job = setup.jobs.public(values["job_id"])
            if values["action"] == "dispatch":
                if job["status"] != "queued" or len(tasks) >= 2:
                    raise ValueError("unavailable")
                actual = setup.jobs.journal.get_job(job["id"])
                if ai_capabilities(actual)["revision"] != values["revision"]:
                    raise ValueError("stale")
                # Validate before scheduling and again under the durable claim.
                setup.current(job["ai"]["request_ref"], job["ai"]["route"]).prepare()
                launch(instance.run_ai_job, job["id"])
            elif values["action"] in {"cancel", "pause", "resume", "retry"}:
                setup.jobs.request_control(
                    job["id"],
                    values["action"],
                    request_id=values["mutation_nonce"],
                    expected_revision=values["revision"],
                )
            else:
                raise ValueError("unavailable")
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)
        return redirect(request, "/operations/ai")

    @app.get("/documents/{document_id}/ai")
    def document_selection(request: Request, document_id: str):
        local(request)
        try:
            document, choices = setup.document_choices(document_id)
            return page(request, "ai_document.html", document=document, choices=choices)
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)

    @app.post("/operations/ai/reconcile")
    async def reconcile(request: Request):
        values = await fields(request, {"job_id", "attempt", "evidence", "acknowledge"})
        try:
            if values["acknowledge"] != "quiescent-and-duplicate-risk":
                raise ValueError("consent")
            setup.jobs.reconcile(
                values["job_id"],
                attempt=int(values["attempt"]),
                evidence=values["evidence"],
                quiescent=True,
                acknowledge_duplicate_risk=True,
            )
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)
        return redirect(request, "/operations/ai")

    @app.post("/documents/{document_id}/ai")
    async def document_preview(request: Request, document_id: str):
        values = await fields(request, {"selection", "start", "end", "version_id"})
        try:
            document, choices = setup.document_choices(document_id)
            if document["current_version"]["id"] != values["version_id"]:
                raise ValueError("stale")
            choice = tuple(values["selection"].split(":"))
            if choice not in choices:
                raise ValueError("selection")
            prepared, document = setup.document_preview(
                document_id,
                representation_id=choice[0],
                output_id=choice[1],
                anchor_id=choice[2],
                start=int(values["start"]),
                end=int(values["end"]),
            )
            return page(
                request,
                "ai_preview.html",
                document=document,
                prepared=prepared,
                payload=setup.payload(prepared),
                phase="document",
            )
        except (ValueError, OSError):
            return page(request, error=True, status_code=409)
