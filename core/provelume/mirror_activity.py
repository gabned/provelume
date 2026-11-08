"""Passive mirror inventory and explicit local staging controls with bounded CSRF forms."""

import hmac
import secrets
from urllib.parse import parse_qs, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .google_activity import _loopback_request
from .mirror_contract import fingerprint, require
from .mirror_jobs import local_preview


def attach_mirror_routes(app, instance, templates, context_factory):
    csrf = secrets.token_urlsafe(32)

    @app.get("/mirrors")
    def page(request: Request):
        try:
            values = context_factory(request, instance)
            engine = instance.mirrors()
            values.update(
                mirrors=engine.view(),
                plan=None,
                manifest=None,
                csrf_token=csrf,
                editable=_loopback_request(request),
                notice=request.query_params.get("notice"),
                git_plan=None,
                git_status=instance.git_mirrors().status(),
                profiles={row["id"]: row["profile"] for row in engine.view()["identities"]},
                receipt=None,
            )
            plan_id = request.query_params.get("plan")
            if plan_id:
                plan = engine.plan(plan_id)
                values.update(
                    plan={**plan, "plan_sha256": fingerprint(plan)},
                    manifest=engine.snapshots.verify(plan["generation"]),
                )
                git_plan = engine._load("git/plans/" + plan_id + ".json")
                if git_plan is not None:
                    _plan, git_plan = instance.git_mirrors().git_plan(plan_id)
                    values.update(
                        git_plan=git_plan,
                        git_plan_sha256=fingerprint(git_plan),
                        receipt=engine._load("receipts/" + plan_id + ".json"),
                    )
            return templates.TemplateResponse(
                request=request,
                name="mirrors.html",
                context=values,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        except (ValueError, KeyError, OSError, TypeError):
            raise HTTPException(409, "Mirror inventory unavailable") from None

    def action(fields):
        require(fields.get("confirm") == "yes", "consent_required")
        selected = fields.get("action")
        allowed = {
            "access": {"revision", "enabled", "github", "rsync"},
            "prepare": {"destination_id", "revision"},
            "disable": {"destination_id", "revision"},
            "discard": {"plan_id", "plan_sha256"},
            "git-prepare": {"destination_id", "revision"},
            "git-initialize": {"destination_id", "destination_sha256"},
            "git-publish": {"plan_id", "plan_sha256", "git_plan_sha256"},
            "git-reconcile": {"plan_id"},
            "github-prepare": {"destination_id", "revision"},
            "github-publish": {
                "plan_id",
                "plan_sha256",
                "git_plan_sha256",
                "transfer_sha256",
                "public_confirm",
            },
            "github-reconcile": {"plan_id"},
            "gitlab-prepare": {"destination_id", "revision"},
            "gitlab-publish": {
                "plan_id",
                "plan_sha256",
                "git_plan_sha256",
                "transfer_sha256",
                "public_confirm",
            },
            "gitlab-reconcile": {"plan_id"},
            "gitea-prepare": {"destination_id", "revision"},
            "gitea-publish": {
                "plan_id",
                "plan_sha256",
                "git_plan_sha256",
                "transfer_sha256",
                "public_confirm",
            },
            "gitea-reconcile": {"plan_id"},
        }
        require(selected in allowed and set(fields) == allowed[selected] | {"action", "confirm"})
        engine = instance.mirrors()
        if selected.startswith(("git-", "github-", "gitlab-", "gitea-")):
            hosted = selected.startswith(("github-", "gitlab-", "gitea-"))
            git = {
                "git": instance.git_mirrors,
                "github": instance.github_mirrors,
                "gitlab": instance.gitlab_mirrors,
                "gitea": instance.gitea_mirrors,
            }[selected.split("-", 1)[0]]()
            selected = (
                selected.replace("github-", "git-", 1)
                .replace("gitlab-", "git-", 1)
                .replace("gitea-", "git-", 1)
            )
            if selected == "git-initialize":
                git.initialize_local(
                    fields["destination_id"],
                    expected_destination_sha256=fields["destination_sha256"],
                    confirmed=True,
                )
                return {"notice": "saved"}
            if selected == "git-prepare":
                plan = git.prepare(
                    fields["destination_id"],
                    expected_revision=int(fields["revision"]),
                    confirmed=True,
                )
                return {"plan": plan["id"]}
            if selected == "git-publish":
                extra = {}
                if hosted:
                    require(fields["public_confirm"] in {"yes", "no"})
                    extra = {
                        "expected_transfer_sha256": (
                            fields["transfer_sha256"] if fields["public_confirm"] == "yes" else None
                        )
                    }
                outcome = git.publish(
                    fields["plan_id"],
                    expected_plan_sha256=fields["plan_sha256"],
                    expected_git_plan_sha256=fields["git_plan_sha256"],
                    confirmed=True,
                    **extra,
                )
            else:
                outcome = git.reconcile(fields["plan_id"], confirmed=True)
            complete = outcome.get("receipt", {}).get("schema") == "provelume-mirror-receipt/v1"
            return {"plan": fields["plan_id"], "notice": "saved" if complete else "unavailable"}
        if selected == "access":
            require(all(fields[key] in {"yes", "no"} for key in ("enabled", "github", "rsync")))
            engine.set_access(
                enabled=fields["enabled"] == "yes",
                github=fields["github"] == "yes",
                rsync=fields["rsync"] == "yes",
                expected_revision=int(fields["revision"]),
                confirmed=True,
            )
            return {"notice": "saved"}
        if selected == "prepare":
            plan = local_preview(
                engine, fields["destination_id"], expected_revision=int(fields["revision"])
            )
            return {"plan": plan["id"]}
        if selected == "disable":
            engine.disable(
                fields["destination_id"], expected_revision=int(fields["revision"]), confirmed=True
            )
        else:
            engine.discard(
                fields["plan_id"], expected_plan_sha256=fields["plan_sha256"], confirmed=True
            )
        return {"notice": "saved"}

    @app.post("/mirrors")
    async def control(request: Request):
        if not _loopback_request(request):
            raise HTTPException(403, "Local mirror controls only")
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "Invalid mirror control form")
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > 16384:
                raise HTTPException(413, "Mirror control form too large")
        try:
            fields = parse_qs(
                body.decode(), strict_parsing=True, keep_blank_values=True, max_num_fields=12
            )
            require(all(len(values) == 1 for values in fields.values()))
            fields = {key: values[0] for key, values in fields.items()}
            require(hmac.compare_digest(fields.pop("csrf_token", ""), csrf))
        except ValueError:
            raise HTTPException(403, "Invalid mirror control token") from None
        try:
            result = await run_in_threadpool(action, fields)
        except (ValueError, KeyError, OSError, TypeError) as error:
            code = getattr(error, "code", "unavailable")
            notice = (
                "limit"
                if code in {"limit", "generation_limit", "plan_limit", "deadline"}
                else (
                    "representation_required"
                    if code == "representation_required"
                    else "unavailable"
                )
            )
            result = {"notice": notice}
            if fields.get("plan_id"):
                try:
                    instance.mirrors().plan(fields["plan_id"])
                except (ValueError, KeyError, OSError, TypeError):
                    pass
                else:
                    result["plan"] = fields["plan_id"]
        query = urlencode({"lang": context_factory(request, instance)["lang"], **result})
        return RedirectResponse(
            "/mirrors?" + query, status_code=303, headers={"Cache-Control": "no-store"}
        )
