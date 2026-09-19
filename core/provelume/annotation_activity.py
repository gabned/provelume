"""One editor for Current and Preview; only the shared coordinator can save."""

from __future__ import annotations

import base64
import difflib
import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from .annotation_i18n import annotation_labels
from .annotation_model import SOURCE_ID, AnnotationError
from .review_effects import ReviewError
from .review_security import ReviewBrowserSessions, require_local_browser, review_json


def annotation_script_integrity() -> str:
    raw = (Path(__file__).parent / "static" / "annotation-editor.js").read_bytes()
    return "sha256-" + base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii")


def attach_annotation_routes(
    app: FastAPI, instance: Any, templates: Any, context_factory: Callable[..., dict[str, Any]]
) -> None:
    from .atomic_commit import AtomicCommitError
    from .instance_lifecycle import InstanceLifecycleError

    unavailable_errors = (
        AnnotationError,
        ReviewError,
        InstanceLifecycleError,
        AtomicCommitError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    )
    sessions = ReviewBrowserSessions(maximum=32)
    reader = instance.annotations.annotations

    def subject_checked(subject):
        if SOURCE_ID.fullmatch(subject) is None:
            raise HTTPException(404, "Annotation source not found")

    def values(request, **extra):
        context = context_factory(request, instance, **extra)
        context["al"] = annotation_labels(context.get("lang", "en"))
        return context

    @app.get("/review/annotations")
    def annotation_list(request: Request, version_id: str | None = None):
        require_local_browser(request)
        if version_id is not None and re.fullmatch(r"ver_[0-9a-f]{32}", version_id) is None:
            raise HTTPException(400, "Invalid Version filter")
        try:
            inventory = reader.sources.list(version_id=version_id)
        except unavailable_errors:
            inventory = {"items": [], "complete": False}
        return templates.TemplateResponse(
            request=request,
            name="annotation_list.html",
            context=values(request, inventory=inventory),
        )

    @app.get("/review/annotations/{subject}")
    def annotation_editor(request: Request, subject: str):
        require_local_browser(request)
        subject_checked(subject)
        unavailable = False
        try:
            model = reader.read(subject)
        except unavailable_errors:
            unavailable = True
            try:
                history = reader.history(subject)
                last = history["records"][-1] if history["records"] else None
                model = (
                    {
                        "source": last["source"],
                        "segments": last["segments"],
                        "revision": last["revision"],
                        "head": history["head"],
                        "history": [
                            {
                                k: row[k]
                                for k in (
                                    "id",
                                    "revision",
                                    "action",
                                    "principal",
                                    "recorded_at",
                                    "restores_revision",
                                )
                            }
                            for row in history["records"]
                        ],
                    }
                    if last
                    else None
                )
            except unavailable_errors:
                model = None
        try:
            authority = instance.review_decisions.authority_resolver("annotations", subject, "save")
        except unavailable_errors:
            authority = {"mode": "disabled"}
            unavailable = True
        editable = not unavailable and authority.get("mode") in {
            "confirm-each",
            "controlled-automatic",
        }
        token = sessions.issue(subject) if editable else None
        integrity = annotation_script_integrity()
        context = values(
            request,
            model=model,
            subject=subject,
            unavailable=unavailable,
            editable=editable,
            csrf_token=token,
            annotation_integrity=integrity,
        )
        request.state.annotation_script_integrity = integrity
        return templates.TemplateResponse(
            request=request, name="annotation_editor.html", context=context
        )

    @app.get("/review/annotations/{subject}/media")
    def annotation_media(request: Request, subject: str):
        require_local_browser(request)
        subject_checked(subject)
        try:
            path, media_type = reader.sources.media(subject)
        except unavailable_errors as exc:
            raise HTTPException(404, "Bound media is unavailable") from exc
        if media_type == "application/pdf":
            request.state.annotation_pdf_media = True
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/review/annotations/{subject}/preview")
    async def annotation_preview(request: Request, subject: str):
        subject_checked(subject)
        fields = await review_json(request, {"csrf_token", "action", "parameters"})
        sessions.check(fields["csrf_token"], subject)
        try:
            before = reader.read(subject)
            plan = instance.review_decisions.preview(
                "annotations", subject, fields["action"], fields["parameters"]
            )
            if plan["authority"]["mode"] not in {"confirm-each", "controlled-automatic"}:
                raise HTTPException(403, "Capability does not allow annotation saves")
            snapshot = plan["provider"]["snapshot"]
            if before["head"] != snapshot["head"] or before["source"] != snapshot["source"]:
                raise AnnotationError("annotation_stale", "Preview input changed")
            # The displayed diff and the confirmed plan share the same exact input.
            changed = plan["provider"]["snapshot"]["segments"]
            diff = list(
                difflib.unified_diff(
                    [
                        f"{row['speaker_label'] or ''}: {row['text']}\n"
                        for row in before["segments"]
                    ],
                    [f"{row['speaker_label'] or ''}: {row['text']}\n" for row in changed],
                    fromfile="before",
                    tofile="after",
                )
            )
            request_id = sessions.retain(fields["csrf_token"], subject, plan)
            return {
                "plan_revision": plan["plan_revision"],
                "authority_revision": plan["authority_revision"],
                "request_id": request_id,
                "segments": changed,
                "diff": diff,
                "impact": plan["provider"]["impact"],
                "mutated": False,
            }
        except unavailable_errors as exc:
            raise HTTPException(409, "Annotation evidence changed or is unavailable") from exc

    @app.post("/review/annotations/{subject}/confirm")
    async def annotation_confirm(request: Request, subject: str):
        subject_checked(subject)
        fields = await review_json(
            request, {"csrf_token", "plan_revision", "authority_revision", "request_id"}
        )
        plan = sessions.consume(
            fields["csrf_token"],
            subject,
            fields["plan_revision"],
            fields["authority_revision"],
            fields["request_id"],
        )
        try:
            return instance.review_decisions.confirm(
                "annotations",
                subject,
                plan["action"],
                plan["parameters"],
                expected_plan_revision=plan["plan_revision"],
                expected_authority_revision=plan["authority_revision"],
                request_id=fields["request_id"],
                principal="local_browser",
            )
        except unavailable_errors as exc:
            raise HTTPException(
                409,
                "Annotation save outcome is unconfirmed; "
                "check history and recovery before a fresh review",
            ) from exc
