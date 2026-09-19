"""Readable domain choices, pure previews and one-use local browser confirmations."""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request

from .atomic_commit import AtomicCommitError
from .instance_lifecycle import InstanceLifecycleError
from .review_decisions import assert_review_readable
from .review_effects import ReviewError, ReviewUnavailable
from .review_i18n import review_labels
from .review_routing import _Inputs, _nodes
from .review_security import ReviewBrowserSessions, require_local_browser, review_json

_ID = re.compile(r"[a-z][a-z0-9_]*_[0-9a-f]{32,64}\Z")
_DOMAINS = {"placement", "routing", "duplicates", "versions", "capabilities"}
_ERRORS = (
    ReviewError,
    InstanceLifecycleError,
    AtomicCommitError,
    OSError,
    ValueError,
    KeyError,
    TypeError,
)


def review_script_integrity() -> str:
    raw = (Path(__file__).parent / "static/review-decisions.js").read_bytes()
    return "sha256-" + base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii")


def review_options(instance, domain, subject):
    """Bounded display choices; only the provider's fresh preview grants eligibility."""
    assert_review_readable(instance.store)
    result = {
        "actions": [],
        "nodes": [],
        "sources": [],
        "documents": [],
        "versions": [],
        "rules": [],
        "subjects": [],
        "defaults": {},
    }
    inputs = _Inputs(instance.store)
    if domain in {"placement", "routing"}:
        result["nodes"] = list(_nodes(inputs).values())
    if domain == "placement":
        if re.fullmatch(r"doc_[0-9a-f]{32}", subject) is None:
            raise ReviewError("Invalid placement subject")
        document = inputs.record(f"knowledge/documents/{subject}.json")
        result["documents"] = [document]
        from .hierarchy_model import classification_id

        current = inputs.record(
            f"knowledge/classifications/{classification_id(subject)}.json", optional=True
        )
        result["defaults"] = (
            {key: current[key] for key in ("primary_node_id", "secondary_node_ids")}
            if current
            else {}
        )
        result["actions"] = ["classify"]
    elif domain == "routing":
        rules = instance.review_routing.rules()
        if subject.startswith("doc_"):
            candidates = instance.review_routing.candidates(subject)
            result["rules"] = [rule for rule in rules if rule["id"] in candidates["rule_ids"]]
            result["actions"] = ["apply_rule"] if result["rules"] else []
            result["documents"] = [inputs.record(f"knowledge/documents/{subject}.json")]
        else:
            if re.fullmatch(r"routing_[0-9a-f]{32}", subject) is None:
                raise ReviewError("Invalid routing subject")
            result["sources"] = list(inputs.inventory("knowledge/sources", 500).values())
            rule = next((row for row in rules if row["id"] == subject), None)
            result["actions"] = ["save_rule", "revoke_rule"] if rule else ["save_rule"]
            result["defaults"] = (
                {
                    **rule["destinations"],
                    "source_id": rule["source_id"],
                    "path_prefix": rule["path_prefix"],
                    "automatic_enabled": rule["automatic_enabled"],
                }
                if rule
                else {}
            )
    elif domain in {"duplicates", "versions"}:
        choices = instance.review_decisions.providers[domain].choices(subject)
        result.update(choices)
    elif domain == "capabilities":
        authority = instance.review_authority
        if subject not in authority.capabilities:
            raise ReviewError("Unknown capability")
        selected = authority.read()["grants"].get(subject)
        result["actions"] = ["configure"]
        result["capability_actions"] = sorted(authority.capabilities[subject])
        result["defaults"] = selected or {
            "mode": "disabled",
            "scope": {"subjects": [], "actions": [], "sources": []},
        }
        result["sources"] = list(inputs.inventory("knowledge/sources", 500).values())
        if subject in {"placement", "routing"}:
            records = inputs.inventory("knowledge/documents", 500)
            result["subjects"] = [
                {"id": key, "label": row.get("title", key)} for key, row in records.items()
            ]
            if subject == "routing":
                result["subjects"].extend(
                    {"id": row["id"], "label": row["path_prefix"] or row["source_id"]}
                    for row in instance.review_routing.rules()
                )
        elif subject == "duplicates":
            result["subjects"] = [
                {"id": key, "label": key} for key in inputs.inventory("state/duplicates/cases", 500)
            ]
        elif subject == "versions":
            from .action_center import ActionCenter

            proposals = ActionCenter(instance.store)._load()["proposals"]
            if len(proposals) > 500:
                raise ReviewUnavailable("Version proposal choices exceed their bound")
            result["subjects"] = [
                {"id": key, "label": row["target_document_id"]} for key, row in proposals.items()
            ]
        else:
            sources = instance.annotations.annotations.sources.list(limit=500)
            if not sources["complete"] or len(sources["items"]) > 500:
                raise ReviewUnavailable("Annotation choices are incomplete")
            result["subjects"] = [
                {"id": row["id"], "label": row.get("title", row["id"])} for row in sources["items"]
            ]
    assert_review_readable(instance.store)
    return result


def review_summary(plan, labels):
    """Visible before/after values derive from the retained server plan, not the client."""
    domain, action, data = plan["domain"], plan["action"], plan["provider"]
    changes = []

    def display(value):
        if value is None or value == []:
            return labels["none"]
        if isinstance(value, bool):
            return labels["yes"] if value else labels["no"]
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    def change(label, before, after):
        changes.append({"label": label, "before": display(before), "after": display(after)})

    if domain == "placement" or (domain == "routing" and action == "apply_rule"):
        snapshot = data["snapshot"]
        before, after = snapshot["before"], snapshot["destinations"]
        names = {key: row["name"] + " · " + key for key, row in snapshot["nodes"].items()}

        def node(value):
            return names.get(value, value) if value else None

        change(
            labels["primary"],
            node(before["primary_node_id"]) if before else None,
            node(after["primary_node_id"]),
        )
        change(
            labels["secondary"],
            [node(x) for x in before["secondary_node_ids"]] if before else [],
            [node(x) for x in after["secondary_node_ids"]],
        )
        effect, reverse = (
            "effect_placement",
            "reverse_placement" if before else "reverse_first_placement",
        )
    elif domain == "routing":
        before, after = data["before"] or {}, data["after"]
        for field, label in (
            ("source_id", "source"),
            ("path_prefix", "path_prefix"),
            ("enabled", "enabled"),
            ("automatic_enabled", "automatic"),
        ):
            change(labels[label], before.get(field), after[field])
        for field, label in (("primary_node_id", "primary"), ("secondary_node_ids", "secondary")):
            change(
                labels[label],
                before.get("destinations", {}).get(field),
                after["destinations"][field],
            )
        effect, reverse = "effect_rule", "reverse_rule"
    elif domain == "capabilities":
        before, after = data["evidence"]["before"] or {}, data["evidence"]["after"]
        change(labels["mode"], labels.get(before.get("mode", "disabled")), labels[after["mode"]])
        for key, label in (
            ("subjects", "subjects"),
            ("actions", "actions"),
            ("sources", "sources"),
        ):
            old = before.get("scope", {}).get(key, [])
            new = after["scope"][key]
            if key == "actions":
                old, new = [labels.get(x, x) for x in old], [labels.get(x, x) for x in new]
            change(labels[label], old, new)
        effect, reverse = "effect_permission", "reverse_permission"
    else:
        evidence = data["evidence"]
        if action in {"new_version", "select_current"}:
            change(labels["target"], evidence["target"]["id"], evidence["target"]["id"])
            selected_version = evidence["selected_version"]["id"]
            if action == "new_version":
                selected_version = labels["from_version"] + " " + selected_version
            change(labels["version"], evidence["target"]["current_version_id"], selected_version)
            effect, reverse = "effect_version", "reverse_version"
        else:
            change(labels["action"], None, labels[action])
            change(labels["subjects"], evidence["documents"], evidence["documents"])
            effect, reverse = "effect_relation", "reverse_relation"
    return {
        "changes": changes,
        "impact": labels[effect],
        "reversibility": labels[reverse],
        "confidence": data["confidence"],
        "evidence": data["evidence"],
        "ambiguous": len(data.get("matched_rule_ids", [])) > 1,
    }


def attach_domain_review_routes(
    app: FastAPI, instance: Any, templates: Any, context_factory: Callable[..., dict[str, Any]]
) -> None:
    sessions = ReviewBrowserSessions(maximum=64)

    def scope(domain, subject):
        if domain not in _DOMAINS or (
            domain != "capabilities"
            and (not isinstance(subject, str) or _ID.fullmatch(subject) is None)
        ):
            raise HTTPException(404, "Review subject not found")
        return domain + ":" + subject

    def context(request, **values):
        result = context_factory(request, instance, **values)
        result["rl"] = review_labels(result.get("lang", "en"))
        return result

    def page(request, template, status=200, **values):
        return templates.TemplateResponse(
            request=request, name=template, context=context(request, **values), status_code=status
        )

    @app.get("/review/capabilities")
    def capabilities(request: Request):
        require_local_browser(request)
        try:
            assert_review_readable(instance.store)
            state = instance.review_authority.read()
            rows = [
                {"domain": domain, "mode": state["grants"].get(domain, {}).get("mode", "disabled")}
                for domain in sorted(instance.review_authority.capabilities)
            ]
            return page(request, "review_capabilities.html", rows=rows, unavailable=False)
        except _ERRORS:
            return page(request, "review_capabilities.html", status=503, rows=[], unavailable=True)

    @app.get("/review/routing")
    def routing(request: Request):
        require_local_browser(request)
        try:
            rows = instance.review_routing.rules()
            return page(
                request,
                "review_rules.html",
                rows=rows,
                new_rule="routing_" + uuid4().hex,
                unavailable=False,
            )
        except _ERRORS:
            return page(
                request, "review_rules.html", status=503, rows=[], new_rule=None, unavailable=True
            )

    @app.get("/review/decisions/{domain}/{subject}")
    def decision(request: Request, domain: str, subject: str):
        require_local_browser(request)
        selected_scope = scope(domain, subject)
        try:
            options = review_options(instance, domain, subject)
            history = instance.review_decisions.history(domain=domain, subject=subject)
            authorities = {
                action: instance.review_decisions.authority_resolver(domain, subject, action)
                for action in options["actions"]
            }
        except _ERRORS:
            return page(
                request,
                "review_decision.html",
                status=503,
                domain=domain,
                subject=subject,
                unavailable=True,
            )
        integrity = review_script_integrity()
        request.state.review_script_integrity = integrity
        return page(
            request,
            "review_decision.html",
            domain=domain,
            subject=subject,
            options=options,
            history=history,
            authorities=authorities,
            unavailable=False,
            csrf_token=sessions.issue(selected_scope),
            review_integrity=integrity,
        )

    @app.post("/review/decisions/{domain}/{subject}/preview")
    async def preview(request: Request, domain: str, subject: str):
        selected_scope = scope(domain, subject)
        fields = await review_json(request, {"csrf_token", "action", "parameters"})
        sessions.check(fields["csrf_token"], selected_scope)
        try:
            plan = instance.review_decisions.preview(
                domain, subject, fields["action"], fields["parameters"]
            )
            labels = context(request)["rl"]
            summary = review_summary(plan, labels)
            request_id = sessions.retain(fields["csrf_token"], selected_scope, plan)
            return {
                "plan_revision": plan["plan_revision"],
                "authority_revision": plan["authority_revision"],
                "request_id": request_id,
                "summary": summary,
                "mutated": False,
                "confirmable": plan["authority"]["mode"]
                in {"confirm-each", "controlled-automatic"},
            }
        except _ERRORS as exc:
            raise HTTPException(
                409, "Review evidence or choices changed; request a fresh review"
            ) from exc

    @app.post("/review/decisions/{domain}/{subject}/confirm")
    async def confirm(request: Request, domain: str, subject: str):
        selected_scope = scope(domain, subject)
        fields = await review_json(
            request, {"csrf_token", "plan_revision", "authority_revision", "request_id"}
        )
        plan = sessions.consume(
            fields["csrf_token"],
            selected_scope,
            fields["plan_revision"],
            fields["authority_revision"],
            fields["request_id"],
        )
        try:
            return instance.review_decisions.confirm(
                domain,
                subject,
                plan["action"],
                plan["parameters"],
                expected_plan_revision=plan["plan_revision"],
                expected_authority_revision=plan["authority_revision"],
                request_id=fields["request_id"],
                principal="local_browser",
            )
        except _ERRORS as exc:
            raise HTTPException(409, "Review confirmation was denied; open a fresh review") from exc
