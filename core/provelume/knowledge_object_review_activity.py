"""Shared, local Cura/Current forms for inert drafts and explicit domain review."""

from __future__ import annotations

from copy import deepcopy
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .action_center_model import digest
from .atomic_commit import AtomicCommitError
from .instance_lifecycle import InstanceLifecycleError
from .knowledge_object_activity import BODY_FIELDS, DEFAULT_STATES
from .knowledge_object_contract import OBJECT_KINDS, RELATION_TYPES, STATES
from .knowledge_object_evidence import current_instance_id
from .knowledge_object_review import history_record, proposal_identity
from .review_effects import (
    ReviewConflict,
    ReviewDenied,
    ReviewError,
    ReviewStale,
    ReviewUnavailable,
)
from .review_security import ReviewBrowserSessions, require_local_browser

META = {"nonce", "request_id", "plan_revision", "authority_revision"}
ERRORS = (ValueError, OSError, KeyError, TypeError, AtomicCommitError, InstanceLifecycleError)
KINDS = sorted(OBJECT_KINDS - {"project", "collection"}) + ["relation"]


def _status(exc):
    return 409 if isinstance(exc, (ReviewStale, ReviewConflict)) else (
        403 if isinstance(exc, ReviewDenied) else 503 if isinstance(exc, ReviewUnavailable)
        else 400 if isinstance(exc, ReviewError) else 503
    )


class ObjectProposalInterface:
    def __init__(self, instance, templates, context_factory):
        self.instance = instance
        self.review = instance.object_review
        self.templates = templates
        self.context_factory = context_factory
        self.sessions = ReviewBrowserSessions()

    def render(self, request, page, *, status=200, **values):
        request.state.object_browser_form = True
        context = self.context_factory(request, self.instance, **values)
        context.update(proposal_page=page, proposal_kinds=KINDS, body_fields=BODY_FIELDS,
                       object_states=STATES, relation_types=sorted(RELATION_TYPES))
        return self.templates.TemplateResponse(request=request, name="knowledge_object_review.html",
                                               context=context, status_code=status)

    def retain(self, plan, purpose, identity):
        plan = {**deepcopy(plan), "purpose": purpose, "identity": identity}
        if purpose != "confirm":
            plan["authority_revision"] = current_instance_id(self.instance.store)
            plan["plan_revision"] = digest(plan)
        subject = "object-proposals:" + purpose + ":" + identity
        nonce = self.sessions.issue(subject)
        request_id = self.sessions.retain(nonce, subject, plan)
        return {"nonce": nonce, "request_id": request_id,
                "plan_revision": plan["plan_revision"],
                "authority_revision": plan["authority_revision"]}

    def consume(self, fields, purpose):
        if not META | {"identity"} <= set(fields):
            raise ReviewError("Missing object review confirmation fields")
        identity = fields["identity"]
        if identity != "new":
            proposal_identity(identity)
        subject = "object-proposals:" + purpose + ":" + identity
        return self.sessions.consume(fields["nonce"], subject, fields["plan_revision"],
                                     fields["authority_revision"], fields["request_id"])

    async def fields(self, request):
        require_local_browser(request, mutation=True)
        if request.headers.get("content-type", "").split(";")[0] != (
            "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "Form required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 256 * 1024:
                raise HTTPException(413, "Object review form exceeds its bound")
        try:
            pairs = parse_qs(raw.decode("utf-8", errors="strict"), keep_blank_values=True,
                             strict_parsing=True, max_num_fields=64, errors="strict")
        except (ValueError, UnicodeError) as exc:
            raise ReviewError("Invalid object review form") from exc
        if any(len(values) != 1 for values in pairs.values()):
            raise ReviewError("Duplicate object review fields")
        return {key: values[0] for key, values in pairs.items()}

    def choices(self):
        return self.instance.object_services().list(limit=100)["items"]

    def draft(self, plan, fields):
        before, kind = plan["draft"], plan["kind"]
        data = {k: v for k, v in fields.items() if k not in META | {"identity", "confirmed"}}
        relation = kind == "relation"
        allowed = ({"relation_type", "source", "target", "refresh_source", "refresh_target"}
                   if relation else {"title", "aliases", "state", *BODY_FIELDS[kind]})
        if not set(data) <= allowed:
            raise ReviewError("Unexpected typed object review field")
        if relation:
            refs = {row["id"]: {key: row[key] for key in ("id", "revision", "sha256")}
                    for row in plan["choices"]}
            selected = {}
            for side in ("source", "target"):
                refresh = data.get("refresh_" + side, "")
                if refresh not in {"", "yes"}:
                    raise ReviewError("Invalid relation endpoint selection")
                identity = data.get(side)
                if before.get(side, {}).get("id") == identity and not refresh:
                    selected[side] = before[side]
                else:
                    if identity not in refs:
                        raise ReviewStale("The selected relation endpoint is unavailable")
                    selected[side] = refs[identity]
            return {"kind": "relation", "relation_type": data.get("relation_type"),
                    "state": "active", **selected}
        body = {key: data.get(key, "").replace("\r\n", "\n") for key in BODY_FIELDS[kind]}
        if body.get("due_at") == "":
            body["due_at"] = None
        aliases = data.get("aliases", "").replace("\r\n", "\n")
        return {"kind": kind, "title": data.get("title", "").replace("\r\n", "\n"),
                "state": data.get("state"), "body": body,
                "aliases": (deepcopy(before["aliases"])
                            if aliases == "\n".join(before["aliases"]) else aliases.splitlines())}

    @staticmethod
    def confirmed(fields):
        if fields.get("confirmed") != "yes":
            raise ReviewDenied("Explicit object review confirmation is required")


def attach_object_review_routes(app: FastAPI, instance, templates, context_factory):
    ui = ObjectProposalInterface(instance, templates, context_factory)

    def redirect(request, identity):
        return RedirectResponse("/objects/proposals/" + identity + "?" + urlencode({
            "lang": request.query_params.get("lang", "en"),
        }), status_code=303)

    def error(request, exc):
        return ui.render(request, "error", status=_status(exc), error_status=_status(exc))

    @app.get("/objects/proposals")
    def proposals(request: Request):
        require_local_browser(request)
        try:
            return ui.render(request, "list", rows=ui.review.listing(),
                             history=instance.review_decisions.history(domain="knowledge_objects"))
        except ERRORS as exc:
            return error(request, exc)

    @app.get("/objects/proposals/new")
    def new(request: Request, job_id: str, kind: str = "claim"):
        require_local_browser(request)
        try:
            if kind not in KINDS:
                raise ReviewError("Unsupported proposal kind")
            seed = ui.review.seed(job_id)
            choices = ui.choices() if kind == "relation" else []
            draft = {"kind": kind, "title": seed["text"].splitlines()[0][:240], "aliases": [],
                     "state": DEFAULT_STATES.get(kind, "active"),
                     "body": {field: seed["text"] if field in {
                         "description", "statement", "rationale",
                     } else None if field == "due_at" else ""
                              for field in BODY_FIELDS.get(kind, ())}}
            if kind == "relation":
                draft = {"kind": kind, "relation_type": "relates_to", "state": "active"}
            plan = {"draft": draft, "kind": kind, "choices": choices, "seed": seed}
            return ui.render(request, "draft", plan=plan, draft=draft, identity="new", new=True,
                             envelope=ui.retain(plan, "prepare", "new"), source=seed["source"],
                             stale=False, retained=None)
        except ERRORS as exc:
            return error(request, exc)

    @app.post("/objects/proposals/prepare")
    async def prepare(request: Request):
        try:
            fields = await ui.fields(request)
            plan = ui.consume(fields, "prepare")
            ui.confirmed(fields)
            draft = ui.draft(plan, fields)
            proposal = await run_in_threadpool(
                ui.review.prepare_proposal, plan["seed"]["job_id"], draft, consent=True,
                expected_instance_id=plan["authority_revision"],
                expected_producer_sha256=plan["seed"]["producer_sha256"],
            )
            return redirect(request, proposal["id"])
        except ERRORS as exc:
            return error(request, exc)

    @app.post("/objects/proposals/preview")
    async def preview(request: Request):
        try:
            fields = await ui.fields(request)
            held = ui.consume(fields, "preview")
            action = fields.pop("action", None)
            if action not in {"apply", "reject"}:
                raise ReviewError("Choose an explicit object review action")
            draft = ui.draft(held, fields)
            plan = await run_in_threadpool(instance.review_decisions.preview,
                                          "knowledge_objects", held["identity"], action,
                                          {"draft": draft})
            return ui.render(request, "preview", plan=plan, draft=draft,
                             identity=held["identity"],
                             envelope=ui.retain(plan, "confirm", held["identity"]),
                             source=plan["provider"]["proposal"]["source"])
        except ERRORS as exc:
            return error(request, exc)

    @app.post("/objects/proposals/confirm")
    async def confirm(request: Request):
        try:
            fields = await ui.fields(request)
            if set(fields) != META | {"identity", "confirmed"}:
                raise ReviewError("Unexpected object review confirmation field")
            plan = ui.consume(fields, "confirm")
            ui.confirmed(fields)
            await run_in_threadpool(
                instance.review_decisions.confirm, "knowledge_objects", plan["subject"],
                plan["action"], plan["parameters"], expected_plan_revision=plan["plan_revision"],
                expected_authority_revision=plan["authority_revision"],
                request_id=fields["request_id"], principal="local_browser",
            )
            return redirect(request, plan["subject"])
        except ERRORS as exc:
            return error(request, exc)

    @app.post("/objects/proposals/discard")
    async def discard(request: Request):
        try:
            fields = await ui.fields(request)
            if set(fields) != META | {"identity", "confirmed"}:
                raise ReviewError("Unexpected object proposal discard field")
            plan = ui.consume(fields, "discard")
            ui.confirmed(fields)
            await run_in_threadpool(ui.review.discard, plan["identity"], consent=True,
                                    expected_instance_id=plan["authority_revision"])
            return RedirectResponse("/objects/proposals?" + urlencode({
                "lang": request.query_params.get("lang", "en"),
            }), status_code=303)
        except ERRORS as exc:
            return error(request, exc)

    @app.get("/objects/proposals/{identity}")
    def detail(request: Request, identity: str):
        require_local_browser(request)
        try:
            proposal_identity(identity)
            retained = history_record(instance.store, identity)
            # Retained history remains readable after either derived draft is discarded.
            if retained is not None:
                try:
                    proposal, _ = ui.review._proposal(identity)
                except ReviewUnavailable:
                    proposal = None
                return ui.render(request, "history", identity=identity, retained=retained,
                                 discarded=proposal is None,
                                 discard_envelope=(ui.retain({}, "discard", identity)
                                                   if proposal is not None else None))
            proposal, _ = ui.review._proposal(identity)
            stale = False
            try:
                ui.review.inspect(identity)
            except ERRORS:
                stale = True
            plan = {"draft": proposal["draft"], "kind": proposal["draft"]["kind"],
                    "choices": ui.choices() if proposal["draft"]["kind"] == "relation" else []}
            return ui.render(
                request, "draft", plan=plan, draft=proposal["draft"], new=False,
                identity=identity, source=proposal["source"], stale=stale, retained=None,
                envelope=ui.retain(plan, "preview", identity),
                discard_envelope=ui.retain({}, "discard", identity),
            )
        except ERRORS as exc:
            return error(request, exc)
