"""Private SSR synthesis surfaces using the existing AI host's form/task controls."""

from fastapi import Request

from .ai_activity import reason_key
from .ai_job_contract import check
from .scheduler_model import SchedulerBusyError


def attach_synthesis_routes(
    app, setup, *, page, fields, redirect, launch_job, local, tasks, mutation
):
    synthesis = setup.synthesis

    def error(request, exc):
        return page(request, error=True, status_code=409,
                    error_key=reason_key(getattr(exc, "code", exc.args[0] if exc.args else None)))

    def preview_page(request, result):
        ref, prepared, document = result
        return page(request, "ai_synthesis.html", phase="preview", ref=ref,
                    prepared=prepared, document=document, payload=setup.payload(prepared))

    def selected_preview(document_id, values):
        document = setup.instance.get_document(document_id)
        check(document is not None and document["current_version"] is not None
              and document["current_version"]["id"] == values["version_id"], "ai_setup_stale")
        choice = values["selection"].split(":")
        check(len(choice) == 2)
        result = synthesis.preview(document_id, *choice, values["task"], values["language"])
        check(result[1][0].manifest.version.version_id == values["version_id"], "ai_setup_stale")
        return result

    @app.get("/documents/{document_id}/synthesis")
    def selection(request: Request, document_id: str):
        local(request)
        try:
            document, choices = synthesis.choices(document_id)
            scopes, _ = setup.document_governance(document)
            policies = synthesis.policies()
            selected = {(r["kind"], r["id"]): r["restriction"] for r in policies["rules"]}
            names = []
            for scope in scopes:
                if scope.kind == "instance":
                    label = setup.instance.store.read_config()["instance"]["name"]
                elif scope.kind == "category":
                    label = document["media_type"]
                else:
                    record = setup.instance.store.read_canonical(
                        "sources" if scope.kind == "source" else "hierarchy", scope.id,
                    )
                    label = record.get("name") or record.get("title") or scope.id
                names.append((scope, label, selected.get((scope.kind, scope.id), "inherit")))
            return page(request, "ai_synthesis.html", phase="selection", document=document,
                        choices=list(dict.fromkeys(c[:2] for c in choices)),
                        scopes=names, policies=policies)
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)

    @app.post("/documents/{document_id}/synthesis/preview")
    async def preview(request: Request, document_id: str):
        values = await fields(request, {"selection", "version_id", "task", "language"})
        try:
            result = await mutation(selected_preview, document_id, values)
            return preview_page(request, result)
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)

    @app.post("/documents/{document_id}/synthesis/policy")
    async def policy(request: Request, document_id: str):
        values = await fields(request, {"kind", "scope_id", "restriction", "revision"})
        try:
            await mutation(synthesis.restrict, document_id, values["kind"], values["scope_id"],
                           values["restriction"], int(values["revision"]))
            return redirect(request, f"/documents/{document_id}/synthesis")
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)

    @app.post("/operations/ai/synthesis/execute")
    async def execute(request: Request):
        values = await fields(request, {"ref", "acknowledge"})
        try:
            check(values["acknowledge"] == "selected-document", "ai_consent_missing")
            row = setup.previews.get(values["ref"])
            check(row is not None and "recipe" in row, "ai_consent_missing")
            check(len(tasks) < 2, "ai_limit_exceeded")
            await mutation(setup.approve, values["ref"])
            job = await mutation(setup.enqueue, values["ref"])
            if job["status"] == "queued":
                await launch_job(job["id"])
            return redirect(request, "/operations/ai")
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)

    @app.get("/operations/ai/{job_id}/synthesis")
    def result(request: Request, job_id: str):
        local(request)
        try:
            job, reference, selections = synthesis.reference(job_id)
            body, document, unavailable = None, None, None
            try:
                body, reference, document, job = synthesis.read(job_id)
            except (ValueError, OSError, SchedulerBusyError):
                unavailable = True
            return page(request, "ai_synthesis.html", phase="result", job=job,
                        reference=reference, body=body, document=document, unavailable=unavailable,
                        document_id=selections[0].version.document_id)
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)

    @app.get("/operations/ai/{job_id}/synthesis/evidence/{index}")
    def evidence(request: Request, job_id: str, index: int):
        local(request)
        try:
            body, reference, document, job = synthesis.read(job_id)
            check(index in body["references"], "ai_result_invalid")
            return page(request, "ai_synthesis.html", phase="evidence", job=job,
                        reference=reference, document=document, segment=body["segments"][index])
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)

    @app.post("/operations/ai/{job_id}/synthesis/discard")
    async def discard(request: Request, job_id: str):
        await fields(request, set())
        try:
            await mutation(synthesis.discard, job_id)
            return redirect(request, f"/operations/ai/{job_id}/synthesis")
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)

    @app.post("/operations/ai/{job_id}/synthesis/regenerate")
    async def regenerate(request: Request, job_id: str):
        await fields(request, set())
        try:
            return preview_page(request, await mutation(synthesis.regenerate, job_id))
        except (ValueError, OSError, SchedulerBusyError) as exc:
            return error(request, exc)
