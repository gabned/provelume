"""Closed, JSON-only contracts for Instance-scoped Action Center evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

QUEUES = (
    "intake",
    "classification",
    "exact_duplicate",
    "probable_duplicate",
    "version_conflict",
    "extraction_error",
    "source_change",
    "retention",
)
REVIEW_STATES = ("awaiting_review", "accepted", "rejected", "superseded")
AUTHORITY_MODES = ("disabled", "proposal-only", "confirm-each", "controlled-automatic")
ACTIONS = ("acknowledge_evidence", "reject_proposal")
MAX_PAGE_SIZE = 500
MAX_ITEMS = 10_000
MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_REVISION = 2**31 - 1
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class ActionCenterError(ValueError):
    code = "invalid_request"


class ActionCenterStale(ActionCenterError):
    code = "stale_revision"


class ActionCenterConflict(ActionCenterError):
    code = "request_conflict"


class ActionCenterUnavailable(ActionCenterError):
    code = "evidence_unavailable"


class ActionCenterDenied(ActionCenterError):
    code = "action_denied"


class ActionCenterBusy(ActionCenterError):
    code = "busy"


def json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ActionCenterError("Action Center values must be finite JSON data") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def bounded_json(value: Any, *, maximum: int = 256 * 1024) -> Any:
    def walk(selected: Any, depth: int) -> None:
        if depth > 16:
            raise ActionCenterError("Action Center JSON exceeds its depth bound")
        if isinstance(selected, dict):
            if len(selected) > MAX_ITEMS or any(not isinstance(key, str) for key in selected):
                raise ActionCenterError("Action Center object is invalid")
            for child in selected.values():
                walk(child, depth + 1)
        elif isinstance(selected, (list, tuple)):
            if len(selected) > MAX_ITEMS:
                raise ActionCenterError("Action Center sequence exceeds its bound")
            for child in selected:
                walk(child, depth + 1)
        elif not isinstance(selected, (str, int, float, bool, type(None))):
            raise ActionCenterError("Action Center values must be JSON data")

    walk(value, 0)
    raw = json_bytes(value)
    if len(raw) > maximum:
        raise ActionCenterError("Action Center JSON exceeds its byte bound")
    return json.loads(raw)


def integer(value: Any, *, minimum: int = 0, maximum: int = MAX_REVISION) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ActionCenterError("Invalid Action Center integer")
    return value


def request_identifier(value: Any) -> str:
    if not isinstance(value, str) or _REQUEST.fullmatch(value) is None:
        raise ActionCenterError("Invalid request identity")
    return value


def revision(value: Any) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ActionCenterError("Invalid input revision")
    return value


def item_identifier(instance_id: str, queue: str, producer_id: str) -> str:
    return (
        "aci_" + digest(["provelume.action-center.item.v1", instance_id, queue, producer_id])[:32]
    )


def make_proposal(
    queue: str,
    producer_id: str,
    *,
    proposal: Mapping[str, Any],
    evidence: Mapping[str, Any],
    domain_links: Sequence[Mapping[str, Any]] = (),
    allowed_actions: Sequence[str] = (),
    revision_inputs: Any = None,
) -> dict[str, Any]:
    if queue not in QUEUES or not isinstance(producer_id, str) or not 1 <= len(producer_id) <= 256:
        raise ActionCenterError("Invalid proposal identity")
    if any(ord(char) < 32 for char in producer_id):
        raise ActionCenterError("Invalid producer identity")
    if not isinstance(proposal, Mapping) or not isinstance(evidence, Mapping):
        raise ActionCenterError("Proposal and evidence must be objects")
    if isinstance(allowed_actions, (str, bytes)) or any(
        action not in ACTIONS for action in allowed_actions
    ):
        raise ActionCenterError("Unsupported Action Center action")
    links = bounded_json(list(domain_links))
    if len(links) > 16:
        raise ActionCenterError("Too many domain links")
    for link in links:
        url = link.get("href", link.get("url")) if isinstance(link, dict) else None
        if (
            not isinstance(url, str)
            or not url.startswith("/")
            or url.startswith("//")
            or "\\" in url
            or any(ord(char) < 32 for char in url)
        ):
            raise ActionCenterError("Domain links must be local absolute paths")
    result = {
        "queue": queue,
        "producer_id": producer_id,
        "proposal": bounded_json(dict(proposal)),
        "evidence": bounded_json(dict(evidence)),
        "domain_links": links,
        "allowed_actions": sorted(set(allowed_actions)),
    }
    semantic = result if revision_inputs is None else bounded_json(revision_inputs)
    result["input_revision"] = digest(
        ["provelume.action-center.input.v1", queue, producer_id, semantic]
    )
    return result


def queue_observation(
    queue: str,
    *,
    status: str | None = None,
    complete: bool | None = None,
    observed_count: int = 0,
    returned: int | None = None,
    matched_count: int | None = None,
    count_relation: str | None = None,
    reason: str | None = None,
    bound: Any = None,
    snapshot_changed: bool = False,
) -> dict[str, Any]:
    if queue not in QUEUES:
        raise ActionCenterError("Unknown queue")
    if complete is not None and type(complete) is not bool:
        raise ActionCenterError("Invalid completeness")
    selected_status = status or ("complete" if complete is not False else "partial")
    if selected_status not in {"complete", "partial", "unavailable", "invalid"}:
        raise ActionCenterError("Invalid observation status")
    if complete is not None and complete != (selected_status == "complete"):
        raise ActionCenterError("Contradictory observation completeness")
    integer(observed_count)
    returned = observed_count if returned is None else integer(returned)
    if matched_count is not None:
        integer(matched_count)
    relation = count_relation or ("exact" if selected_status == "complete" else "unknown")
    if relation not in {"exact", "at_least", "unknown"}:
        raise ActionCenterError("Invalid count relation")
    if selected_status != "complete" and relation == "exact":
        raise ActionCenterError("Incomplete observation cannot claim an exact total")
    if type(snapshot_changed) is not bool or (reason is not None and not isinstance(reason, str)):
        raise ActionCenterError("Invalid observation reason")
    return {
        "queue": queue,
        "status": selected_status,
        "complete": selected_status == "complete",
        "observed_count": observed_count,
        "returned": returned,
        "matched_count": matched_count,
        "count_relation": relation,
        "reason": reason,
        "bound": bounded_json(bound),
        "snapshot_changed": snapshot_changed,
    }
