"""Bounded local object API and shared Cura/Current manual forms."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .atomic_commit import AtomicCommitError
from .instance_lifecycle import InstanceLifecycleError
from .knowledge_object_contract import (
    OBJECT_KINDS,
    RELATION_TYPES,
    STATES,
    KnowledgeObjectError,
    canonical_bytes,
)
from .knowledge_object_evidence import bounded_json, current_instance_id, object_path, require
from .review_security import ReviewBrowserSessions, require_local_browser, review_json

API = "/api/v1/knowledge-objects"
MAX_DOWNLOAD = 25 * 1024 * 1024
ENVELOPE = {"nonce", "request_id", "instance_id", "expected_sha256", "confirmed", "data"}
BODY_FIELDS = {
    kind: ("statement",) if kind == "claim" else ("rationale",) if kind == "decision"
    else ("description", "due_at") if kind in {"task", "commitment"}
    else ("description", "starts_at", "ends_at", "time_zone") if kind == "calendar_event"
    else ("description",)
    for kind in OBJECT_KINDS
}
DEFAULT_STATES = {
    "entity": "active", "claim": "asserted", "decision": "proposed", "project": "active",
    "collection": "active", "task": "open", "outcome": "proposed",
    "calendar_event": "tentative", "commitment": "open",
}


def _error(exc):
    if isinstance(exc, HTTPException):
        return exc
    code = exc.code if isinstance(exc, KnowledgeObjectError) else "unavailable"
    status = {"denied": 403, "conflict": 409, "not_found": 404, "limit": 413}.get(code, 400)
    if code in {"integrity", "schema", "unavailable"}:
        status = 503
    return HTTPException(status, "knowledge_object_" + code)


ERRORS = (KnowledgeObjectError, InstanceLifecycleError, AtomicCommitError, OSError)


class ObjectInterface:
    def __init__(self, instance, templates, context_factory):
        self.instance = instance
        self.services = instance.object_services()
        self.templates = templates
        self.context_factory = context_factory
        self.sessions = ReviewBrowserSessions()

    @staticmethod
    def subject(identity, relation):
        return ("relation:" if relation else "object:") + (identity or "new")

    def get(self, identity, relation=False):
        result = self.services.get(identity, relation=relation)
        require(result is not None, "not_found")
        return result

    def plan(self, identity=None, relation=False, *, kind="entity", version_id=None):
        require(kind in OBJECT_KINDS)
        before = self.get(identity, relation) if identity else None
        choices = self.services.list(limit=100)["items"] if relation else []
        plan = {
            "plan_revision": before["sha256"] if before else "ABSENT",
            "authority_revision": current_instance_id(self.instance.store),
            "identity": identity, "relation": relation, "before": before,
            "kind": before["record"].get("kind") if before and not relation else kind,
            "choices": choices,
            "seed_evidence": self.services.evidence_for_version(version_id) if version_id else None,
        }
        subject = self.subject(identity, relation)
        nonce = self.sessions.issue(subject)
        request_id = self.sessions.retain(nonce, subject, plan)
        return plan, {
            "nonce": nonce, "request_id": request_id,
            "instance_id": plan["authority_revision"],
            "expected_sha256": plan["plan_revision"],
        }

    def consume(self, identity, relation, value):
        require(value["confirmed"] is True, "denied")
        require(value["instance_id"] == current_instance_id(self.instance.store), "conflict")
        return self.sessions.consume(
            value["nonce"], self.subject(identity, relation), value["expected_sha256"],
            value["instance_id"], value["request_id"],
        )

    def save(self, identity, relation, value):
        canonical_bytes(value["data"])
        plan = self.consume(identity, relation, value)
        data = value["data"]
        require(type(data) is dict)
        options = {"consent": True, "expected_instance_id": plan["authority_revision"]}
        if identity:
            require(set(data) == {"changes", "evidence"})
            return self.services.update(
                identity, data["changes"], evidence=data["evidence"],
                expected_sha256=plan["plan_revision"], relation=relation, **options,
            )
        if relation:
            require(set(data) == {"relation_type", "source", "target", "evidence"})
            return self.services.create_relation(**data, **options)
        require(set(data) == {"kind", "title", "body", "state", "aliases", "evidence"})
        return self.services.create(**data, **options)

    def render(self, request, *, page, status_code=200, **values):
        if page == "form":
            # Native navigation POST otherwise serializes Origin as null under
            # no-referrer. Keep the referrer local, without accepting null Origin.
            request.state.object_browser_form = True
        context = self.context_factory(request, self.instance, **values)
        context.update(
            object_page=page, object_kinds=sorted(OBJECT_KINDS - {"project", "collection"}),
            relation_types=sorted(RELATION_TYPES), body_fields=BODY_FIELDS,
            object_states=STATES, default_states=DEFAULT_STATES,
        )
        return self.templates.TemplateResponse(
            request=request, name="knowledge_objects.html", context=context,
            status_code=status_code,
        )

    def sources(self, view):
        rows = []
        for status in view["evidence"]:
            row = self.services._read("object-evidence", status["id"])
            rows.append({**status, "record": row})
        return rows

    def form_data(self, plan, fields):
        before = plan["before"]["record"] if plan["before"] else None
        relation = plan["relation"]
        expected = {"state", "retain", "add_evidence"}
        if relation:
            expected |= {"relation_type", "source", "target", "refresh_source", "refresh_target"}
        else:
            expected |= {"title", "aliases", *BODY_FIELDS[plan["kind"]]}
        require(set(fields) <= expected)
        for name in ("add_evidence", "refresh_source", "refresh_target"):
            require(fields.get(name, "") in {"", "yes"})
        retained = fields.get("retain", [])
        old_evidence = before["evidence_ids"] if before else []
        require(len(retained) == len(set(retained)) and set(retained) <= set(old_evidence))
        evidence = []
        if fields.get("add_evidence") == "yes":
            require(plan["seed_evidence"] is not None)
            evidence.append(plan["seed_evidence"])
        evidence_ids = list(retained)
        for row in evidence:
            if row["id"] not in evidence_ids:
                evidence_ids.append(row["id"])
        if relation:
            refs = {r["id"]: {k: r[k] for k in ("id", "revision", "sha256")}
                    for r in plan["choices"]}
            selected = {}
            for side in ("source", "target"):
                identity = fields.get(side)
                if before and identity == before[side]["id"] and not fields.get("refresh_" + side):
                    selected[side] = before[side]
                else:
                    require(identity in refs, "conflict")
                    selected[side] = refs[identity]
            data = {"relation_type": fields.get("relation_type"), **selected}
        else:
            body = {key: fields.get(key, "").replace("\r\n", "\n")
                    for key in BODY_FIELDS[plan["kind"]]}
            if "due_at" in body and body["due_at"] == "":
                body["due_at"] = None
            alias_text = fields.get("aliases", "").replace("\r\n", "\n")
            # Existing canonical aliases may themselves contain newlines. An
            # untouched display must not split their retained boundaries.
            aliases = (deepcopy(before["aliases"])
                       if before and alias_text == "\n".join(before["aliases"])
                       else alias_text.splitlines())
            data = {"title": fields.get("title", "").replace("\r\n", "\n"),
                    "aliases": aliases, "body": body}
        if before:
            data.update(state=fields.get("state"), evidence_ids=evidence_ids)
            changes = {key: val for key, val in data.items() if val != before[key]}
            require(bool(changes), "unchanged")
            return {"changes": changes, "evidence": evidence}
        if relation:
            require(fields.get("state", "active") == "active")
        else:
            data.update(kind=plan["kind"], state=fields.get("state"))
        return {**data, "evidence": evidence}

    async def read_form(self, request):
        require_local_browser(request, mutation=True)
        require(request.headers.get("content-type", "").split(";")[0]
                == "application/x-www-form-urlencoded")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            require(len(body) <= 256 * 1024, "limit")
        try:
            values = parse_qs(body.decode("utf-8", errors="strict"), keep_blank_values=True,
                              strict_parsing=True, max_num_fields=160, errors="strict")
        except (ValueError, UnicodeError):
            raise KnowledgeObjectError() from None
        require(all(len(v) == 1 or k == "retain" for k, v in values.items()))
        result = {k: v if k == "retain" else v[0] for k, v in values.items()}
        require(ENVELOPE - {"data"} <= set(result))
        require(result.pop("confirmed") == "yes", "denied")
        relation = result.pop("relation", "")
        require(relation in {"0", "1"})
        identity = result.pop("identity", "") or None
        envelope = {key: result.pop(key) for key in ENVELOPE - {"data", "confirmed"}}
        envelope["confirmed"] = True
        # Consume before interpreting selections; the server-held plan owns all preimages.
        plan = self.consume(identity, relation == "1", envelope)
        envelope["data"] = self.form_data(plan, result)
        return plan, envelope

    def save_form(self, plan, value):
        # A new private session is unnecessary: read_form consumed the original exactly once.
        data = value["data"]
        options = {"consent": True, "expected_instance_id": plan["authority_revision"]}
        if plan["identity"]:
            return self.services.update(
                plan["identity"], **data, relation=plan["relation"],
                expected_sha256=plan["plan_revision"], **options,
            )
        if plan["relation"]:
            return self.services.create_relation(**data, **options)
        return self.services.create(**data, **options)


def attach_object_routes(app: FastAPI, instance, templates, context_factory):
    ui = ObjectInterface(instance, templates, context_factory)

    @app.get(API)
    def object_list(request: Request, relation: bool = False, limit: int = Query(50, ge=1, le=100),
                    after: str | None = None):
        require_local_browser(request)
        try:
            return ui.services.list(relation=relation, limit=limit, after=after)
        except ERRORS as exc:
            raise _error(exc) from None

    @app.get(API + "/authorization")
    def authorization(request: Request, identity: str | None = None, relation: bool = False):
        require_local_browser(request)
        try:
            _plan, envelope = ui.plan(identity, relation)
            return {**envelope, "expires_in_seconds": 600, "one_use": True}
        except ERRORS as exc:
            raise _error(exc) from None

    @app.get(API + "/evidence")
    def evidence(request: Request, version_id: str):
        require_local_browser(request)
        try:
            return {"record": ui.services.evidence_for_version(version_id),
                    "truth": "NOT_VERIFIED", "mutated": False, "network_used": False}
        except ERRORS as exc:
            raise _error(exc) from None

    @app.get(API + "/{identity}/history")
    def history(request: Request, identity: str, relation: bool = False,
                offset: int = Query(0, ge=0, le=1024), limit: int = Query(20, ge=1, le=100)):
        require_local_browser(request)
        try:
            rows = ui.services.history(identity, relation=relation)
            return {"items": rows[offset:offset + limit], "total": len(rows),
                    "mutated": False, "truth": "NOT_VERIFIED"}
        except ERRORS as exc:
            raise _error(exc) from None

    @app.get(API + "/{identity}")
    def object_get(request: Request, identity: str, relation: bool = False):
        require_local_browser(request)
        try:
            return ui.get(identity, relation)
        except ERRORS as exc:
            raise _error(exc) from None

    async def mutation(request, identity, relation):
        value = await review_json(request, ENVELOPE)
        try:
            return await run_in_threadpool(ui.save, identity, relation, value)
        except ERRORS as exc:
            raise _error(exc) from None

    @app.post(API)
    async def object_create(request: Request, relation: bool = False):
        return await mutation(request, None, relation)

    @app.post(API + "/{identity}")
    async def object_update(request: Request, identity: str, relation: bool = False):
        return await mutation(request, identity, relation)

    @app.get("/objects")
    def objects_page(request: Request, relation: bool = False, after: str | None = None):
        require_local_browser(request)
        try:
            result = ui.services.list(relation=relation, after=after)
            if relation:
                for row in result["items"]:
                    record = ui.services._head(row["id"], True)
                    row["relation_type"] = record["relation_type"]
                    row["endpoints"] = []
                    for side in ("source", "target"):
                        ref = record[side]
                        head = ui.services._head(ref["id"])
                        row["endpoints"].append({
                            "title": head["title"] if head and head["revision"] == ref["revision"]
                            else None, "revision": ref["revision"],
                        })
            return ui.render(request, page="list", result=result, relation=relation)
        except ERRORS as exc:
            raise _error(exc) from None

    @app.get("/objects/new")
    def new_page(request: Request, kind: str = "entity", relation: bool = False,
                 version_id: str | None = None):
        require_local_browser(request)
        try:
            require(kind not in {"project", "collection"}, "hierarchy_authority")
            plan, envelope = ui.plan(relation=relation, kind=kind, version_id=version_id)
            return ui.render(request, page="form", plan=plan, envelope=envelope, relation=relation)
        except ERRORS as exc:
            raise _error(exc) from None

    @app.get("/objects/sources")
    def sources_page(request: Request, identity: str | None = None, relation: bool = False,
                     kind: str = "entity", document_id: str | None = None):
        require_local_browser(request)
        try:
            require(kind in OBJECT_KINDS)
            if identity:
                ui.get(identity, relation)
            versions = []
            if document_id:
                require(re.fullmatch(r"doc_[0-9a-f]{32}", document_id) is not None)
                versions = instance.versions(document_id)[:20]
            return ui.render(
                request, page="sources", identity=identity, relation=relation, kind=kind,
                documents=instance.recent_documents(limit=50), versions=versions,
            )
        except ERRORS as exc:
            raise _error(exc) from None

    @app.post("/objects/save")
    async def save_page(request: Request):
        try:
            plan, value = await ui.read_form(request)
            result = await run_in_threadpool(ui.save_form, plan, value)
            query = urlencode({"relation": int(plan["relation"]),
                               "lang": request.query_params.get("lang", "en")})
            return RedirectResponse("/objects/" + result["record"]["id"] + "?" + query, 303)
        except (*ERRORS, HTTPException, ValueError) as exc:
            error = _error(exc)
            if error.status_code == 403:
                raise error from None
            return ui.render(request, page="error", status_code=error.status_code,
                             error_status=error.status_code)

    @app.get("/objects/versions/{version_id}/original")
    def exact_original(request: Request, version_id: str):
        require_local_browser(request)
        try:
            evidence = ui.services.evidence_for_version(version_id)
            original = bounded_json(object_path(
                instance.store, "knowledge/originals/" + evidence["original_id"] + ".json",
            ))
            require(original["size_bytes"] <= MAX_DOWNLOAD, "limit")
            with object_path(instance.store, original["storage_ref"]).open("rb") as stream:
                payload = stream.read(MAX_DOWNLOAD + 1)
            require(len(payload) <= MAX_DOWNLOAD, "limit")
            require(len(payload) == original["size_bytes"]
                    and hashlib.sha256(payload).hexdigest() == evidence["original_sha256"],
                    "evidence_unavailable")
            return Response(payload, media_type="application/octet-stream", headers={
                "Content-Disposition": 'attachment; filename="original.bin"',
                "Cache-Control": "no-store",
            })
        except ERRORS as exc:
            raise _error(exc) from None

    @app.get("/objects/{identity}/edit")
    def edit_page(request: Request, identity: str, relation: bool = False,
                  version_id: str | None = None):
        require_local_browser(request)
        try:
            plan, envelope = ui.plan(identity, relation, version_id=version_id)
            return ui.render(request, page="form", plan=plan, envelope=envelope, relation=relation)
        except ERRORS as exc:
            raise _error(exc) from None

    @app.get("/objects/{identity}/history")
    def history_page(request: Request, identity: str, relation: bool = False,
                     offset: int = Query(0, ge=0, le=1024)):
        require_local_browser(request)
        try:
            rows = ui.services.history(identity, relation=relation)
            return ui.render(request, page="history", identity=identity, relation=relation,
                             rows=rows[offset:offset + 20], total=len(rows), offset=offset)
        except ERRORS as exc:
            raise _error(exc) from None

    @app.get("/objects/{identity}")
    def detail_page(request: Request, identity: str, relation: bool = False,
                    revision: int | None = Query(None, ge=1, le=1024)):
        require_local_browser(request)
        try:
            view = ui.get(identity, relation)
            if revision is not None:
                rows = ui.services.history(identity, relation=relation)
                require(revision <= len(rows), "not_found")
                view = ui.services._view(deepcopy(rows[revision - 1]), relation)
            return ui.render(request, page="detail", view=view, relation=relation,
                             sources=ui.sources(view), historical=revision is not None)
        except ERRORS as exc:
            raise _error(exc) from None
