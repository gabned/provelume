"""Local authenticated Browser controls for the existing AI services."""

from __future__ import annotations

import asyncio
import hmac
import secrets
from contextlib import suppress
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .ai_jobs import ai_capabilities
from .ai_setup import AiSetup
from .scheduler_model import SchedulerBusyError, SchedulerError
from .shell_activity import MutationNonces, _loopback_request


def reason_key(code):
    """Translate only closed diagnostics; arbitrary exception text never reaches UI."""
    groups = {
        "reason_off": {"ai_off"},
        "reason_policy": {"ai_explicit_deny", "ai_missing_policy", "ai_conflicting_policy"},
        "reason_locality": {"ai_locality_unqualified"},
        "reason_limit": {"ai_limit_exceeded", "ai_budget_exhausted", "ai_attempts_exhausted"},
        "reason_stale": {
            "ai_context_mismatch",
            "ai_consent_missing",
            "ai_stale_plan",
            "ai_setup_stale",
            "ai_authority_changed",
        },
        "reason_route": {
            "ai_unsupported_capability",
            "ai_profile_not_allowed",
            "ai_route_not_configured",
            "ai_route_changed",
        },
        "reason_network": {"ai_local_only", "ai_network_disabled"},
        "reason_uncertain": {"ai_outcome_uncertain"},
        "price_block": {"ai_price_unknown", "ai_price_expired", "ai_price_invalid_bound"},
    }
    return next(
        ("ai." + key for key, codes in groups.items() if isinstance(code, str) and code in codes),
        "ai.error",
    )


def attach_ai_routes(app, instance, templates, context_factory):
    setup = AiSetup(instance)
    app.state.ai_setup = setup
    csrf = secrets.token_urlsafe(32)
    nonces = MutationNonces()
    tasks = set()
    app.state.ai_tasks = tasks

    def failure(request, status):
        return HTTPException(status, context_factory(request, instance)["t"]("ai.error"))

    def local(request):
        if not _loopback_request(request):
            raise failure(request, 403)

    def page(request, name="ai_settings.html", *, status_code=200, **values):
        local(request)
        context = context_factory(request, instance, **values)
        context.update(
            ai=setup.read(),
            csrf_token=csrf,
            mutation_nonce=nonces.issue(),
            selected_instance_id=setup.instance_id,
            ai_reason_key=reason_key,
        )
        response = templates.TemplateResponse(
            request=request, name=name, context=context, status_code=status_code
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    async def render(request, *args, **values):
        # Rendering reads the same protected AI state as synchronous GET pages.
        # An early error must not block the event loop behind another operation.
        return await run_in_threadpool(page, request, *args, **values)

    async def fields(request, required):
        local(request)
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != (
            "application/x-www-form-urlencoded"
        ):
            raise failure(request, 415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise failure(request, 413)
        try:
            raw = parse_qs(
                body.decode(), keep_blank_values=True, strict_parsing=True, max_num_fields=20
            )
        except (ValueError, UnicodeError):
            raise failure(request, 400) from None
        if set(raw) != required | {"csrf_token", "mutation_nonce", "instance_id"} or any(
            len(v) != 1 for v in raw.values()
        ):
            raise failure(request, 400)
        result = {k: v[0] for k, v in raw.items()}
        if not hmac.compare_digest(result["csrf_token"], csrf):
            raise failure(request, 403)
        if result["instance_id"] != setup.instance_id:
            raise failure(request, 409)
        if not nonces.consume(result["mutation_nonce"]):
            raise failure(request, 409)
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
            with suppress(ValueError, OSError, SchedulerBusyError):
                await asyncio.to_thread(function, *args, **kwargs)

        task = asyncio.create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def mutation(function, *args, **kwargs):
        if len(tasks) >= 2:
            raise ValueError("unavailable")
        # Lifecycle acquisition can wait. Keep read-only navigation responsive,
        # and retain ownership if the HTTP caller disconnects before it returns.
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(task)

    async def launch_job(job_id):
        if len(tasks) >= 2:
            raise ValueError("unavailable")
        accepted = asyncio.get_running_loop().create_future()

        async def run_job():
            try:
                claimed = await asyncio.to_thread(instance.scheduler.claim_ai_job, job_id)
                if claimed is None:
                    return
                accepted.set_result(True)
                await asyncio.to_thread(setup.jobs.execute_claimed, claimed)
            except (ValueError, OSError, SchedulerError, SchedulerBusyError):
                pass
            finally:
                if not accepted.done():
                    accepted.set_result(False)

        # Own the claim and execution before awaiting: a disconnected request
        # cannot abandon a newly reserved job, and shutdown drains this task.
        task = asyncio.create_task(run_job())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        if not await asyncio.shield(accepted):
            raise ValueError("unavailable")

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
            await mutation(
                setup.save,
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
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )
        return redirect(request, "/settings/ai")

    @app.post("/settings/ai/control")
    async def control(request: Request):
        values = await fields(request, {"action", "revision"})
        try:
            await mutation(setup.control, values["action"], int(values["revision"]))
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )
        return redirect(request, "/settings/ai")

    @app.post("/settings/ai/model")
    async def model(request: Request):
        values = await fields(request, {"action", "path", "acknowledge", "authority"})
        try:
            if values["acknowledge"] != "explicit":
                raise ValueError("consent")
            if len(tasks) >= 2:
                raise ValueError("unavailable")
            identity = setup.begin_operation(values["action"],
                                             expected_authority=values["authority"])
            launch(setup.run_operation, identity, path=values["path"] or None)
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )
        return redirect(request, "/settings/ai")

    @app.post("/settings/ai/network")
    async def network(request: Request):
        values = await fields(request, {"enabled", "revision", "acknowledge"})
        try:
            if (values["acknowledge"] != "instance-network"
                    or values["enabled"] not in {"yes", "no"}):
                raise ValueError("consent")
            await mutation(setup.set_network, values["enabled"] == "yes", values["revision"])
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(request, error=True, status_code=409,
                                error_key=reason_key(getattr(exc, "code", None)))
        return redirect(request, "/settings/ai")

    @app.post("/settings/ai/model/cancel")
    async def cancel_model(request: Request):
        values = await fields(request, {"operation_id"})
        try:
            setup.cancel_operation(values["operation_id"])
        except ValueError as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )
        return redirect(request, "/settings/ai")

    @app.post("/settings/ai/test/preview")
    async def preview(request: Request):
        await fields(request, set())
        try:
            ref, prepared = setup.preview_test()
            return await render(
                request,
                "ai_preview.html",
                ref=ref,
                prepared=prepared,
                payload=setup.payload(prepared),
                phase="preview",
            )
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )

    @app.post("/settings/ai/test/consent")
    async def consent(request: Request):
        values = await fields(request, {"ref", "acknowledge"})
        try:
            if values["acknowledge"] != "synthetic-test":
                raise ValueError("consent")
            await mutation(setup.approve, values["ref"])
            prepared = setup.previews[values["ref"]]["prepared"]
            return await render(
                request,
                "ai_preview.html",
                ref=values["ref"],
                prepared=prepared,
                payload=setup.payload(prepared),
                phase="consented",
            )
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )

    @app.post("/settings/ai/test/enqueue")
    async def enqueue(request: Request):
        values = await fields(request, {"ref"})
        try:
            await mutation(setup.enqueue, values["ref"])
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )
        return redirect(request, "/operations/ai")

    @app.get("/operations/ai")
    def operations(request: Request):
        from .ai_synthesis_recovery import candidate

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
        dispatchable = set()
        orphaned = {}
        for job in jobs:
            with suppress(ValueError, OSError, SchedulerBusyError):
                orphaned[job["id"]] = candidate(setup.synthesis, job["id"])
        control = setup.jobs.status()
        if control["session_authorized"] and control["mode"] == "enabled":
            for job in jobs:
                if job["status"] == "queued":
                    try:
                        # Pure bounded synthetic preflight, never DNS/credentials/model work.
                        setup.current(job["ai"]["request_ref"], job["ai"]["route"]).prepare()
                        dispatchable.add(job["id"])
                    except (ValueError, OSError, SchedulerBusyError):
                        pass
        return page(
            request,
            "ai_operations.html",
            jobs=jobs,
            receipts=receipts,
            revisions=revisions,
            dispatchable=dispatchable,
            orphaned=orphaned,
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
                await launch_job(job["id"])
            elif values["action"] in {"cancel", "pause", "resume", "retry"}:
                setup.jobs.request_control(
                    job["id"],
                    values["action"],
                    request_id=values["mutation_nonce"],
                    expected_revision=values["revision"],
                )
            else:
                raise ValueError("unavailable")
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )
        return redirect(request, "/operations/ai")

    @app.get("/documents/{document_id}/ai")
    def document_selection(request: Request, document_id: str):
        local(request)
        try:
            document, choices = setup.document_choices(document_id)
            return page(request, "ai_document.html", document=document, choices=choices)
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return page(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )

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
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )
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
            return await render(
                request,
                "ai_preview.html",
                document=document,
                prepared=prepared,
                payload=setup.payload(prepared),
                phase="document",
            )
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return await render(
                request,
                error=True,
                status_code=409,
                error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)),
            )

    from .ai_synthesis_activity import attach_synthesis_routes

    attach_synthesis_routes(app, setup, page=page, fields=fields, redirect=redirect,
                            launch_job=launch_job, local=local, tasks=tasks, mutation=mutation)
