"""Local browser review sessions: bounded JSON, exact Origin, expiring one-use plans."""

from __future__ import annotations

import ipaddress
import json
import secrets
import threading
from collections import OrderedDict
from copy import deepcopy
from time import monotonic

from fastapi import HTTPException, Request

from .web_security import trusted_request_host


def require_local_browser(request: Request, *, mutation: bool = False) -> None:
    if not trusted_request_host(request.headers.get("host", "")) or request.client is None:
        raise HTTPException(403, "Local browser required")
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = request.client.host == "testclient" and request.url.hostname == "testserver"
    if not local:
        raise HTTPException(403, "Local browser required")
    if mutation and (
        request.headers.get("origin", "").rstrip("/") != str(request.base_url).rstrip("/")
        or request.headers.get("sec-fetch-site") in {"cross-site", "none"}
    ):
        raise HTTPException(403, "Same-origin review required")


async def review_json(request: Request, fields: set[str], *, maximum: int = 256 * 1024) -> dict:
    require_local_browser(request, mutation=True)
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(415, "JSON review required")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise HTTPException(413, "Review request exceeds its byte limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate field")
            result[key] = value
        return result

    try:
        value = json.loads(
            body,
            object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HTTPException(400, "Invalid review JSON") from exc
    if not isinstance(value, dict) or set(value) != fields:
        raise HTTPException(400, "Invalid review fields")
    return value


class ReviewBrowserSessions:
    """Memory only. Reading a page never persists a plan, lock or journal."""

    def __init__(self, *, seconds: int = 600, maximum: int = 64):
        self.seconds = seconds
        self.maximum = maximum
        self.lock = threading.Lock()
        self.sessions: OrderedDict[str, dict] = OrderedDict()

    def _prune(self):
        now = monotonic()
        for token, row in list(self.sessions.items()):
            if now - row["created"] >= self.seconds:
                del self.sessions[token]

    def issue(self, subject: str) -> str:
        with self.lock:
            self._prune()
            while len(self.sessions) >= self.maximum:
                self.sessions.popitem(last=False)
            token = secrets.token_urlsafe(32)
            self.sessions[token] = {
                "created": monotonic(),
                "subject": subject,
                "plan": None,
                "request_id": secrets.token_hex(24),
            }
            return token

    def _get(self, token, subject):
        self._prune()
        if not isinstance(token, str) or len(token) > 128:
            raise HTTPException(403, "Invalid review nonce")
        value = self.sessions.get(token)
        if value is None or value["subject"] != subject:
            raise HTTPException(409, "Review expired; open a new review")
        return value

    def check(self, token: str, subject: str) -> None:
        with self.lock:
            self._get(token, subject)

    def retain(self, token: str, subject: str, plan: dict) -> str:
        with self.lock:
            row = self._get(token, subject)
            row["plan"] = deepcopy(plan)
            row["request_id"] = secrets.token_hex(24)
            return row["request_id"]

    def consume(
        self, token: str, subject: str, plan_revision: str, authority_revision: str, request_id: str
    ) -> dict:
        with self.lock:
            row = self._get(token, subject)
            plan = row["plan"]
            if (
                not isinstance(plan, dict)
                or plan.get("plan_revision") != plan_revision
                or plan.get("authority_revision") != authority_revision
                or row["request_id"] != request_id
            ):
                raise HTTPException(409, "Reviewed selection changed; open a new review")
            del self.sessions[token]
            return deepcopy(plan)
