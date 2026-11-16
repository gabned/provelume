"""Closed provider-neutral S10 read contract, preserving date and revision meaning."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from importlib.resources import files
from typing import Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tzdata.zoneinfo as shipped_zones

MAX_PAGE_ITEMS = 200
MAX_RECORD_BYTES = 1024 * 1024
MAX_CURSOR_BYTES = 8192
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_SESSION_BYTES = 8 * 1024 * 1024
READ_CAPABILITIES = frozenset({"calendar_read", "task_read"})


class ProductivityError(ValueError):
    """Closed diagnostics; no provider response, endpoint or secret in messages."""

    def __init__(self, code="invalid"):
        self.code = code
        super().__init__("productivity_" + code)


def require(condition, code="invalid"):
    if not condition:
        raise ProductivityError(code)


def text(value, maximum=8192, *, empty=False):
    require(type(value) is str and (empty or bool(value)) and len(value) <= maximum)
    require(not any(ord(char) < 32 and char not in "\n\t" for char in value))
    return value


def fingerprint(value, *, maximum=MAX_RECORD_BYTES):
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ProductivityError() from None
    require(len(raw) <= maximum, "limit")
    return hashlib.sha256(raw).hexdigest()


def temporal(value):
    """Dates stay dates; floating instants require an explicit provider zone."""
    require(type(value) is dict and set(value) == {"kind", "value", "time_zone"})
    text(value["value"], 80)
    if value["kind"] == "date":
        require(value["time_zone"] is None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["value"]))
        try:
            return date.fromisoformat(value["value"])
        except ValueError:
            raise ProductivityError() from None
    require(value["kind"] == "instant")
    try:
        instant = datetime.fromisoformat(value["value"].replace("Z", "+00:00"))
        require(instant.tzinfo is not None)
        name = text(value["time_zone"], 100)
        require(re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", name)
                and all(part not in {".", ".."} for part in name.split("/")), "time_zone")
        with files(shipped_zones).joinpath(*name.split("/")).open("rb") as stream:
            zone = ZoneInfo.from_file(stream, key=name)
        require(instant.astimezone(zone).utcoffset() == instant.utcoffset(), "time_zone")
        return instant
    except (ValueError, OSError, ZoneInfoNotFoundError):
        raise ProductivityError("time_zone") from None


def local_instant(day, clock, name):
    """Explicit day/clock/zone input; never guess an ambiguous or missing DST offset."""
    temporal({"kind": "date", "value": day, "time_zone": None})
    require(type(clock) is str and re.fullmatch(r"\d{2}:\d{2}", clock) is not None)
    require(type(name) is str and re.fullmatch(
        r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", name)
        and all(part not in {".", ".."} for part in name.split("/")), "time_zone")
    try:
        with files(shipped_zones).joinpath(*name.split("/")).open("rb") as stream:
            selected = ZoneInfo.from_file(stream, key=name)
        local = datetime.fromisoformat(day + "T" + clock)
        first = local.replace(tzinfo=selected, fold=0)
        second = local.replace(tzinfo=selected, fold=1)

        require(first.utcoffset() == second.utcoffset()
                and first.astimezone(UTC).astimezone(selected).replace(tzinfo=None) == local,
                "time_zone")
        result = {"kind": "instant", "value": first.isoformat(), "time_zone": name}
        temporal(result)
        return result
    except (OSError, ValueError):
        raise ProductivityError("time_zone") from None


def validate_item(value):
    """Validate the complete mapped item before any consumer can see a page."""
    require(type(value) is dict and set(value) == {
        "remote_id", "revision", "revision_kind", "kind", "title", "description",
        "state", "due", "starts", "ends", "provenance"})
    fingerprint(value)
    text(value["remote_id"], 2048)
    text(value["revision"], 2048)
    require(type(value["revision_kind"]) is str
            and value["revision_kind"] in {"etag", "version", "content_sha256"})
    if value["revision_kind"] == "content_sha256":
        require(re.fullmatch(r"[0-9a-f]{64}", value["revision"]) is not None)
    text(value["title"], 240, empty=value["kind"] == "calendar_event")
    text(value["description"], 128 * 1024, empty=True)
    require(type(value["kind"]) is str and value["kind"] in {"task", "calendar_event"})
    require(type(value["state"]) is str)
    if value["kind"] == "task":
        require(value["state"] in {"open", "in_progress", "completed", "cancelled"})
        require(value["starts"] is None and value["ends"] is None)
        if value["due"] is not None:
            temporal(value["due"])
    else:
        require(value["state"] in {"tentative", "confirmed", "cancelled"})
        require(value["due"] is None)
        # Cancellation tombstones may omit times; they never fabricate a span.
        if value["state"] == "cancelled" and value["starts"] is None:
            require(value["ends"] is None)
        else:
            start, end = temporal(value["starts"]), temporal(value["ends"])
            require(type(start) is type(end) and (start < end or (
                isinstance(start, datetime) and start == end)), "time_range")
    provenance = value["provenance"]
    require(type(provenance) is dict and set(provenance) - {
        "original_time_zones", "response_sha256", "display_names", "task_context"} == {
        "container_ids", "parent_id", "assignees", "links", "comments", "uid", "recurrence_id",
        "recurrence"})
    if "task_context" in provenance:
        context = provenance["task_context"]
        require(value["kind"] == "task" and type(context) is dict and set(context)
                == {"status", "start_date", "start_time", "time_zone"})
        for key in context:
            if context[key] is not None:
                text(context[key], 100)
    if "display_names" in provenance:
        names = provenance["display_names"]
        require(type(names) is dict and set(names) == {"assignees", "containers", "parent"})
        for key in ("assignees", "containers"):
            require(type(names[key]) is dict and len(names[key]) <= 128, "limit")
            for identity, label in names[key].items():
                text(identity, 2048)
                text(label, 500)
        if names["parent"] is not None:
            text(names["parent"], 500)
    if "response_sha256" in provenance:
        require(type(provenance["response_sha256"]) is list
                and len(provenance["response_sha256"]) <= 256, "limit")
        require(all(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest)
                    for digest in provenance["response_sha256"]), "integrity")
    if "original_time_zones" in provenance:
        zones = provenance["original_time_zones"]
        require(type(zones) is dict and set(zones) == {"starts", "ends", "recurrence"})
        for zone in zones.values():
            if zone is not None:
                text(zone, 100)
    for name, maximum in (("container_ids", 128), ("assignees", 100), ("links", 100),
                          ("comments", 200), ("recurrence", 128)):
        require(type(provenance[name]) is list and len(provenance[name]) <= maximum, "limit")
        for item in provenance[name]:
            text(item, 32768 if name == "comments" else 2048, empty=name == "comments")
    for name in ("parent_id", "uid", "recurrence_id"):
        if provenance[name] is not None:
            text(provenance[name], 2048)
    for link in provenance["links"]:
        require(not any(char.isspace() for char in link), "link")
        try:
            parsed = urlsplit(link)
            _port = parsed.port
        except ValueError:
            raise ProductivityError("link") from None
        require(parsed.scheme in {"http", "https"} and parsed.hostname
                and parsed.username is None and parsed.password is None, "link")
    return value


@dataclass(frozen=True)
class ReadPage:
    items: tuple[dict, ...]
    next_cursor: str | None = None
    checkpoint: str | None = None
    originals: tuple[bytes, ...] = field(default=(), repr=False)
    media_type: str = "application/json"
    response: bytes | None = field(default=None, repr=False)
    snapshot_mode: str = "full"

    def validate(self):
        require(type(self.items) is tuple and len(self.items) <= MAX_PAGE_ITEMS, "limit")
        for item in self.items:
            validate_item(item)
        fingerprint(self.items, maximum=MAX_PAGE_BYTES)
        identities = [item["remote_id"] for item in self.items]
        require(len(identities) == len(set(identities)), "duplicate")
        for cursor in (self.next_cursor, self.checkpoint):
            if cursor is not None:
                text(cursor, MAX_CURSOR_BYTES)
        require(not (self.next_cursor is not None and self.checkpoint is not None))
        require(self.media_type in {"application/json", "text/calendar"})
        require(type(self.originals) is tuple and (not self.originals
                or len(self.originals) == len(self.items)))
        require(all(type(raw) is bytes and raw for raw in self.originals))
        unique = {hashlib.sha256(raw).hexdigest(): len(raw) for raw in self.originals}
        require(sum(unique.values()) <= MAX_PAGE_BYTES, "limit")
        require(self.response is None or (type(self.response) is bytes
                and 0 < len(self.response) <= MAX_PAGE_BYTES), "limit")
        require(type(self.snapshot_mode) is str and self.snapshot_mode in {"full", "delta"})
        return self


@dataclass(frozen=True)
class ReadCredential:
    identity_id: str
    capability: str
    revision_sha256: str
    payload: dict = field(repr=False, compare=False)

    def validate(self, identity_id, capability):
        require(self.identity_id == identity_id and self.capability == capability
                and type(self.revision_sha256) is str
                and re.fullmatch(r"[0-9a-f]{64}", self.revision_sha256) is not None,
                "authorization_required")
        require(type(self.payload) is dict, "authorization_required")
        fingerprint(self.payload, maximum=16 * 1024)
        return self


class CredentialResolver(Protocol):
    """Device-external backend; references and payloads never enter Core records."""

    def resolve(self, identity_id: str, capability: str) -> ReadCredential: ...


class ReadAdapter(Protocol):
    """Adapters enforce transport bounds; the host owns authority and commit."""

    def read_page(self, *, identity: dict, source: dict, cursor: str | None,
                  credential: dict | None) -> ReadPage: ...
