"""Presentation-only navigation and bounded retrieval context for Cura."""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import Request

RETRIEVAL_KEYS = {
    "/browse": frozenset(
        {"lang", "source_id", "media_type", "area", "hierarchy_id", "disposition"}
    ),
    "/search": frozenset({"lang", "q", "source_id", "media_type", "date_from", "date_to"}),
}
DOCUMENT_ID = re.compile(r"doc_[0-9a-f]{32}\Z")
PRIMARY = (
    ("overview", "/", "house"),
    ("knowledge", "/browse", "library"),
    ("capture", "/inbox", "inbox"),
    ("search", "/search", "search"),
    ("attention", "/attention", "triangle-alert"),
)
KNOWLEDGE_PATHS = frozenset(
    {
        "/browse",
        "/bundles",
        "/representations",
        "/perceptio",
        "/photos",
        "/audio",
        "/video",
        "/file-families",
        "/duplicates",
        "/ocr",
        "/email",
        "/transcripts",
    }
)


def shell_snapshot(request: Request):
    if not hasattr(request.state, "shell_settings_snapshot"):
        manager = getattr(request.app.state, "shell_settings_manager", None)
        request.state.shell_settings_snapshot = manager.load() if manager is not None else None
    return request.state.shell_settings_snapshot


def script_integrity() -> str:
    raw = (Path(__file__).parent / "static/cura-shell.js").read_bytes()
    return "sha256-" + base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii")


def retrieval_url(path: str, values: list[tuple[str, str]], *, fragment: str = "") -> str:
    if path not in RETRIEVAL_KEYS:
        return ""
    allowed = RETRIEVAL_KEYS[path]
    # Repeated keys have ambiguous FastAPI semantics; retain the last supplied value.
    selected = {
        key: value for key, value in values if key in allowed and value and len(value) <= 500
    }
    if "lang" in selected and selected["lang"] not in {"en", "it"}:
        selected.pop("lang")
    query = urlencode(sorted(selected.items()))
    result = path + ("?" + query if query else "")
    if fragment and DOCUMENT_ID.fullmatch(fragment):
        result += "#result-" + fragment
    return result


def validated_return(value: str | None) -> str:
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return ""
    try:
        parsed = urlsplit(value)
        pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=12)
    except ValueError:
        return ""
    if parsed.scheme or parsed.netloc or "\\" in value or parsed.path not in RETRIEVAL_KEYS:
        return ""
    if any(key not in RETRIEVAL_KEYS[parsed.path] for key, _ in pairs):
        return ""
    if any(len(value) > 500 or any(ord(c) < 32 or c == "\\" for c in value) for _, value in pairs):
        return ""
    if any(key == "lang" and value not in {"en", "it"} for key, value in pairs):
        return ""
    if len({key for key, _ in pairs}) != len(pairs):
        return ""
    fragment = (
        parsed.fragment.removeprefix("result-") if parsed.fragment.startswith("result-") else ""
    )
    if parsed.fragment and not DOCUMENT_ID.fullmatch(fragment):
        return ""
    return retrieval_url(parsed.path, pairs, fragment=fragment)


def navigation_context(
    request: Request, language: str, t: Callable[[str], str], navigation: list[dict[str, Any]]
) -> dict[str, Any]:
    path = request.url.path
    return_to = validated_return(request.query_params.get("return_to"))
    owner = "management"
    if path == "/":
        owner = "overview"
    elif path == "/search":
        owner = "search"
    elif path.startswith("/inbox"):
        owner = "capture"
    elif path.startswith("/attention"):
        owner = "attention"
    elif path.startswith("/documents/"):
        owner = "search" if return_to.startswith("/search") else "knowledge"
    elif any(path == p or path.startswith(p + "/") for p in KNOWLEDGE_PATHS):
        owner = "knowledge"
    primary = [
        {
            "id": key,
            "href": f"{route}?lang={language}",
            "label": t(f"cura.nav.{key}"),
            "icon": icon,
            "current": owner == key,
        }
        for key, route, icon in PRIMARY
    ]
    primary.append(
        {
            "id": "management",
            "href": f"/management?lang={language}",
            "label": t("cura.nav.management"),
            "icon": "sliders-horizontal",
            "current": owner == "management",
        }
    )
    special = []
    management = {
        key: {"label": t(f"cura.management.{key}"), "links": []}
        for key in ("sources", "preferences", "operations", "support")
    }
    for group in navigation:
        for item in group["links"]:
            route = urlsplit(item["href"]).path
            if route in {"/", "/browse", "/search", "/inbox"}:
                continue
            if route in KNOWLEDGE_PATHS:
                special.append(item)
            else:
                category = "support"
                if route in {"/sources", "/connectors", "/google/connect"}:
                    category = "sources"
                elif route in {"/settings", "/settings/shell"}:
                    category = "preferences"
                elif route in {
                    "/operations",
                    "/scheduler",
                    "/assurance",
                    "/rebuild",
                    "/maintenance",
                }:
                    category = "operations"
                management[category]["links"].append(item)

    def filter_link(**changes: str | None) -> str:
        values = dict(request.query_params.multi_items())
        values["lang"] = language
        for key, value in changes.items():
            if value is None:
                values.pop(key, None)
            else:
                values[key] = value
        return retrieval_url(path, list(values.items()))

    def document_link(
        document_id: str, mode: str | None = None, *, provenance: bool = False
    ) -> str:
        if not DOCUMENT_ID.fullmatch(document_id):
            raise ValueError("invalid document link identity")
        destination = f"/documents/{document_id}" + ("/provenance" if provenance else "")
        query = {"lang": language}
        if mode in {"rendered", "raw", "original"}:
            query["mode"] = mode
        back = return_to
        if path in RETRIEVAL_KEYS:
            pairs = list(request.query_params.multi_items())
            pairs = [(k, v) for k, v in pairs if k != "lang"] + [("lang", language)]
            back = retrieval_url(path, pairs, fragment=document_id)
        if back:
            query["return_to"] = back
        return destination + "?" + urlencode(query)

    active = []
    for key, value in request.query_params.multi_items():
        if key in RETRIEVAL_KEYS.get(path, ()) and key != "lang" and value:
            if key == "disposition" and value == "active":
                continue
            active.append({"key": key, "value": value[:500], "clear": filter_link(**{key: None})})
    return {
        "cura_navigation": primary,
        "knowledge_links": special,
        "management_groups": list(management.values()),
        "filter_link": filter_link,
        "document_link": document_link,
        "return_to": return_to,
        "return_label": t(
            "cura.back.search" if return_to.startswith("/search") else "cura.back.knowledge"
        ),
        "active_filters": active,
    }
