"""Six local setup screens sharing the normal service, CSRF and revision owners."""

import asyncio
import hmac
import secrets
import time
from collections import OrderedDict
from contextlib import suppress
from dataclasses import replace
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .daily_journeys import runtime_state
from .folder_source_activity import _loopback_request
from .ocr_contract import OcrContractError
from .setup_coordinator import SetupCoordinator, startup_available, validate_choices
from .setup_progress import STEPS
from .setup_trial_http import verify_trial_http
from .setup_trials import SetupTrials
from .shell_activity import MutationNonces
from .shell_settings import LANGUAGES

MAX_BODY = 24 * 1024
SELECTORS = {"source_id", "path", "name", "language", "retention", "ocr", "languages",
             "automation", "login_startup", "archive", "receipt", "expected_sha256"}
FIELDS = SELECTORS | {"csrf_token", "mutation_nonce", "revision", "step", "action",
                      "preview_revision"}


def attach_setup_routes(app, instance, templates, context_factory, shell_manager, *, host, port):
    coordinator = SetupCoordinator(instance, shell_manager)
    csrf, nonces, sessions = secrets.token_urlsafe(32), MutationNonces(), OrderedDict()
    lock = asyncio.Lock()

    def session(request):
        now = time.monotonic()
        for key in list(sessions):
            if sessions[key]["expires"] <= now:
                del sessions[key]
        token = request.cookies.get("provelume_setup")
        if token not in sessions:
            while len(sessions) >= 64:
                sessions.popitem(last=False)
            token = secrets.token_urlsafe(32)
            application = coordinator.application()
            if application and application.get("plan"):
                defaults = application["plan"]["preview"]["choices"]
            else:
                defaults = coordinator.defaults()
            sessions[token] = {"expires": now + 1800, "choices": defaults,
                               "selectors": {}, "trial_key": secrets.token_urlsafe(24)}
        sessions[token]["expires"] = now + 1800
        return token, sessions[token]

    def render(request, step, token, draft, *, error=None, saved=False, status=200):
        progress = coordinator.progress.read()
        prepared = coordinator.prepared()
        application = coordinator.application()
        choices = draft["choices"]
        source_id = choices["source_id"]
        source = instance.folder_sources.local_view(source_id) if source_id else None
        trial_id = progress["operations"].get("test")
        trial, trial_problem = None, None
        if trial_id:
            try:
                trial = SetupTrials(instance.store).observations(trial_id)
            except (ValueError, OSError):
                trial_problem = "setup_trial_required"
        capability = None
        with suppress(OcrContractError, OSError, ValueError):
            capability = instance.ocr.capability(replace(instance.ocr.configured_settings(),
                                                       mode="automatic",
                                                       languages=tuple(choices["languages"])))
        preview = None
        blocked = None
        using_application = application and application.get("plan") and (
            application["pending"] or application["complete"] and
            application["plan"]["preview"]["choices"] == choices)
        if step == "summary" and not using_application:
            try:
                preview = coordinator.preview(choices)
            except (ValueError, RuntimeError, OSError) as exc:
                blocked = problem(exc)
        elif using_application:
            preview = application["plan"]["preview"]
        can_continue = True
        if step in {"folders", "ocr", "automation"}:
            try:
                coordinator.check_prepared(validate_choices(choices))
            except (ValueError, OSError) as exc:
                can_continue, blocked = False, problem(exc)
        if step == "ocr" and choices["ocr"] and not (capability and capability["available"]):
            can_continue, blocked = False, "setup_operation_failed"
        if step == "test" and not (trial and trial["complete"]):
            can_continue, blocked = False, "setup_trial_required"
        context = context_factory(
            request, instance, setup_step=step, setup_steps=STEPS, setup_progress=progress,
            setup_choices=choices, setup_selectors=draft["selectors"], setup_prepared=prepared,
            setup_source=source, setup_sources=instance.folder_sources.list_public(),
            setup_runtime=runtime_state(app),
            setup_can_continue=can_continue,
            setup_trial=trial, setup_application=application, setup_preview=preview,
            setup_capability=capability, setup_startup_available=startup_available(),
            setup_kit_preview=draft.get("kit_preview"),
            setup_languages=sorted(LANGUAGES), setup_root=str(instance.root),
            setup_space=instance.store.read_config()["instance"], setup_error=error,
            setup_blocked=blocked or trial_problem, setup_saved=saved, csrf_token=csrf,
            mutation_nonce=nonces.issue())
        response = templates.TemplateResponse(request=request, name="setup.html", context=context,
                                              status_code=status)
        response.set_cookie("provelume_setup", token, max_age=1800, httponly=True,
                            samesite="strict", path="/setup")
        response.headers["Cache-Control"] = "no-store"
        return response

    def problem(exc):
        code = str(exc)
        # Never show arbitrary service exception text (which may contain a path).
        return code if code in PROBLEMS else "setup_operation_failed"

    @app.get("/setup")
    async def setup_page(request: Request):
        if not _loopback_request(request):
            raise HTTPException(status_code=403, detail="Setup requires the local browser")
        step = request.query_params.get("step", coordinator.progress.read()["step"])
        if step not in STEPS:
            raise HTTPException(status_code=404, detail="Unknown setup step")
        async with lock:
            token, draft = session(request)
            return await run_in_threadpool(render, request, step, token, draft)

    @app.post("/setup")
    async def setup_action(request: Request):
        if not _loopback_request(request):
            raise HTTPException(status_code=403, detail="Setup requires the local browser")
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != (
                "application/x-www-form-urlencoded"):
            raise HTTPException(status_code=415, detail="Unsupported setup content type")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY:
                raise HTTPException(status_code=413, detail="Setup request is too large")
            body.extend(chunk)
        try:
            fields = parse_qs(body.decode("utf-8"), keep_blank_values=True,
                              max_num_fields=len(FIELDS), strict_parsing=True)
            if set(fields) - FIELDS or any(len(value) != 1 for value in fields.values()):
                raise ValueError("closed fields")
            fields = {key: values[0] for key, values in fields.items()}
            expected = int(fields["revision"])
            step = fields["step"]
            if step not in STEPS:
                raise ValueError("step")
        except (ValueError, UnicodeError, KeyError) as exc:
            raise HTTPException(status_code=400, detail="Invalid setup fields") from exc
        async with lock:
            token = request.cookies.get("provelume_setup")
            if (token not in sessions or sessions[token]["expires"] <= time.monotonic()
                    or not hmac.compare_digest(fields.get("csrf_token", ""), csrf)
                    or not nonces.consume(fields.get("mutation_nonce", ""))):
                raise HTTPException(status_code=403, detail="Reload the setup form")
            draft = sessions[token]
            try:
                coordinator._current(expected)
                choices = dict(draft["choices"])
                for name in {"source_id", "language", "retention", "automation"} & fields.keys():
                    choices[name] = fields[name] or None
                for name in {"ocr", "login_startup"} & fields.keys():
                    if fields[name] not in {"yes", "no"}:
                        raise ValueError("setup_choices_invalid")
                    choices[name] = fields[name] == "yes"
                if "languages" in fields:
                    choices["languages"] = fields["languages"].split(",")
                validate_choices({**choices,
                                  "source_id": choices["source_id"] or "src_" + "0" * 32})
                if choices["source_id"]:
                    instance.folder_sources.local_view(choices["source_id"])
                draft["choices"] = choices
                draft["selectors"].update({key: value for key, value in fields.items()
                                           if key in {"path", "name", "archive", "receipt",
                                                      "expected_sha256"}})
                action = fields.get("action")
                if action == "prepare":
                    selectors = draft["selectors"]
                    source_id = choices["source_id"]
                    path = selectors.get("path", "")
                    name = selectors.get("name", "")
                    if source_id:
                        view = instance.folder_sources.local_view(source_id)
                        path, name = view["path"], view["name"]
                    await run_in_threadpool(coordinator.prepare, expected, path=path, name=name,
                                            source_id=source_id)
                    prepared = coordinator.prepared()
                    draft["choices"]["source_id"] = prepared["source_id"]
                    if prepared["new_source"] and choices["automation"] == "preserve":
                        draft["choices"]["automation"] = "automatic"
                elif action == "preview_ocr":
                    coordinator._current(expected)
                    draft["kit_preview"] = await run_in_threadpool(
                        coordinator.preview_ocr, archive=draft["selectors"].get("archive", ""),
                        receipt=draft["selectors"].get("receipt", ""),
                        expected_sha256=draft["selectors"].get("expected_sha256", ""))
                elif action == "install_ocr":
                    await run_in_threadpool(coordinator.install_ocr, expected,
                                            archive=draft["selectors"].get("archive", ""),
                                            receipt=draft["selectors"].get("receipt", ""),
                                            expected_sha256=draft["selectors"].get(
                                                "expected_sha256", ""),
                                            preview_revision=draft.get("kit_preview", {}).get(
                                                "revision", ""))
                    draft["selectors"].pop("archive", None)
                    draft["selectors"].pop("receipt", None)
                    draft["kit_preview"] = None
                elif action in {"trial", "new_trial"}:
                    if action == "new_trial":
                        draft["trial_key"] = secrets.token_urlsafe(24)
                    await run_in_threadpool(coordinator.start_trial, expected, choices,
                                            request_key=draft["trial_key"],
                                            fresh=action == "new_trial")
                elif action == "verify":
                    validate_choices(choices)
                    trial_id = coordinator.progress.read()["operations"].get("test")
                    if trial_id is None:
                        raise ValueError("setup_trial_required")
                    await verify_trial_http(app, instance.store, trial_id, host=host, port=port)
                    await run_in_threadpool(coordinator.finish_trial, expected, choices)
                elif action == "apply":
                    await run_in_threadpool(coordinator.apply, expected, choices=choices,
                                            preview_revision=fields.get("preview_revision", ""))
                    # Read the saved preference through normal language resolution.
                    return RedirectResponse("/setup?step=summary", status_code=303)
                elif action == "pause_review":
                    await run_in_threadpool(coordinator.pause_and_review, expected)
                    step = "folders"
                elif action in {"save", "discard", "back", "next"}:
                    target = step
                    index = STEPS.index(step)
                    if action == "next":
                        if step == "folders":
                            coordinator.check_prepared(validate_choices(choices))
                        elif step == "ocr" and choices["ocr"]:
                            from .ocr_contract import require_ocr_available

                            require_ocr_available(instance.ocr.capability(replace(
                                instance.ocr.configured_settings(), mode="automatic",
                                languages=tuple(choices["languages"]))))
                        elif step == "test":
                            await run_in_threadpool(coordinator.preview, choices)
                        target = STEPS[min(index + 1, len(STEPS) - 1)]
                    elif action == "back":
                        target = STEPS[max(0, index - 1)]
                    await run_in_threadpool(coordinator.navigate, expected, target,
                                            selection=choices, discard=action == "discard",
                                            finished=step if action == "next" else None)
                    step = target
                    if action == "discard":
                        draft["choices"], draft["selectors"] = coordinator.defaults(), {}
                        step = "space"
                else:
                    raise HTTPException(status_code=400, detail="Unknown setup action")
            except (ValueError, RuntimeError, OSError) as exc:
                return await run_in_threadpool(render, request, step, token, draft,
                                                error=problem(exc), status=409)
            return await run_in_threadpool(render, request, step, token, draft, saved=True)


PROBLEMS = {"setup_progress_stale", "setup_choices_invalid", "setup_folder_overlap",
            "setup_name_invalid", "setup_source_changed", "setup_permission_failed",
            "setup_prepare_required", "setup_transit_unavailable", "setup_trial_required",
            "setup_source_busy", "setup_global_ocr_needs_review", "setup_authority_needs_review",
            "setup_settings_invalid", "setup_startup_unavailable", "setup_apply_needs_review",
            "setup_preview_stale", "setup_apply_readback_failed", "setup_startup_readback_failed",
            "setup_operation_failed", "setup_apply_pending"}
PROBLEMS.add("setup_kit_authority_required")
