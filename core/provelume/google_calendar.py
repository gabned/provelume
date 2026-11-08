"""Google Calendar v3: read-only, bounded pagination and attributed event mapping."""

from __future__ import annotations

import json
import re
from datetime import datetime
from importlib.resources import files
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import tzdata.zoneinfo as shipped_zones

from .google_adapters import GoogleApiAdapter
from .google_contract import GoogleContractError, GoogleCursorInvalidated, GoogleLimits
from .google_oauth import resolve_google_credential
from .productivity_contract import (
    ProductivityError,
    ReadPage,
    fingerprint,
    require,
    temporal,
    text,
    validate_item,
)

ORIGIN = "https://www.googleapis.com/calendar/v3"


def _time(value, default_zone):
    require(type(value) is dict)
    if "date" in value:
        result = {"kind": "date", "value": value["date"], "time_zone": None}
    else:
        name = value.get("timeZone", default_zone)
        text(name, 100)
        require(
            re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", name)
            and all(part not in {"", ".", ".."} for part in name.split("/")),
            "time_zone",
        )
        try:
            with files(shipped_zones).joinpath(*name.split("/")).open("rb") as stream:
                zone = ZoneInfo.from_file(stream, key=name)
            instant = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
            require(instant.tzinfo is not None, "time_zone")
            result = {
                "kind": "instant",
                "value": instant.astimezone(zone).isoformat(),
                "time_zone": name,
            }
        except (KeyError, ValueError, OSError, TypeError):
            raise ProductivityError("time_zone") from None
    temporal(result)
    return result


def map_calendar_event(value, calendar_id, time_zone):
    require(type(value) is dict)
    require(
        type(value.get("attendees", [])) is list
        and all(type(row) is dict for row in value.get("attendees", []))
    )
    identity = text(value.get("id"), 2048)
    state = value.get("status", "confirmed")
    require(type(state) is str and state in {"tentative", "confirmed", "cancelled"})
    missing_times = state == "cancelled" and "start" not in value
    original_start = value.get("originalStartTime")
    if original_start is not None:
        # Validate the original occurrence without substituting its current start.
        _time(original_start, time_zone)
    revision = value.get("etag")
    result = {
        "remote_id": identity,
        "revision": revision or fingerprint(value),
        "revision_kind": "etag" if revision else "content_sha256",
        "kind": "calendar_event",
        "title": value.get("summary", ""),
        "description": value.get("description", ""),
        "state": state,
        "due": None,
        "starts": None if missing_times else _time(value.get("start"), time_zone),
        "ends": None if missing_times else _time(value.get("end"), time_zone),
        "provenance": {
            "container_ids": [calendar_id],
            "parent_id": value.get("recurringEventId"),
            "assignees": [
                row["email"]
                for row in value.get("attendees", [])
                if type(row) is dict and "email" in row
            ],
            "links": [value["htmlLink"]] if value.get("htmlLink") else [],
            "comments": [],
            "uid": value.get("iCalUID"),
            "recurrence_id": json.dumps(original_start, sort_keys=True)
            if original_start is not None
            else None,
            "recurrence": value.get("recurrence", []),
        },
    }
    return validate_item(result)


class GoogleCalendarAdapter:
    """Uses the existing Google credential vault and per-capability authority.

    No calendar write, automatic token reset, page replay or retry is performed.
    A 410 is retained as cursor-invalidated until the explicit Source reset.
    """

    def __init__(self, connection, source_id, *, sync_token=None, api=None):
        self.connection = connection
        self.source_id = source_id
        self.sync_token = sync_token
        self.api = api
        self._active_token = None
        self._pages = 0
        self._items = 0
        self.limits = GoogleLimits(max_items_per_page=100, max_json_bytes=2 * 1024 * 1024)
        self._initial = self.binding()

    def binding(self):
        instance, capability, source = self.connection.sources.effective_execution_context(
            self.source_id
        )
        require(source["capability"] == "calendar" and len(source["selectors"]) == 1, "unsupported")
        return {
            "identity_id": instance["connector_instance_id"],
            "selection_sha256": source["selection_sha256"],
            "capability_revision": capability["revision"],
            "capability_sha256": fingerprint(capability),
            "cursor_revision": source["cursor"]["revision"],
        }

    def recheck(self):
        require(self.binding() == self._initial, "stale")

    def _json(self, url, reference):
        api = self.api or GoogleApiAdapter(
            credential_resolver=lambda _reference: self._active_token
        )
        return api._json(url, credential_reference=reference, limits=self.limits)

    def read_page(self, *, identity, source, cursor, credential):
        del credential
        self.recheck()
        require(self._pages < self.limits.max_pages_per_run, "limit")
        self._pages += 1
        require(
            source["id"] == self.source_id and identity["id"] == self._initial["identity_id"],
            "stale",
        )
        record = self.connection.sources.source_record(self.source_id, require_enabled=True)
        selected = record["selectors"][0]
        reference = self.connection._owned_reference(identity["id"], "calendar")
        require(reference is not None, "authorization_required")
        grant = self.connection.vault.read(reference["name"])
        instance_record = self.connection.sources._instance_record(identity["id"])
        require(
            isinstance(grant, dict)
            and grant.get("capability") == "calendar"
            and grant.get("account_binding_sha256")
            == instance_record.get("account_binding_sha256"),
            "authorization_required",
        )
        self._active_token = resolve_google_credential(
            reference, vault=self.connection.vault, transport=self.connection.transport
        )
        try:
            params = {
                "maxResults": self.limits.max_items_per_page,
                "singleEvents": "false",
                "showDeleted": "true",
            }
            if cursor is not None:
                params["pageToken"] = cursor
            if self.sync_token is not None:
                params["syncToken"] = self.sync_token
            url = ORIGIN + "/calendars/" + quote(selected, safe="") + "/events?" + urlencode(params)
            api = self.api or GoogleApiAdapter(
                credential_resolver=lambda _reference: self._active_token
            )
            raw, media_type = api._request(
                url,
                credential_reference=reference,
                limits=self.limits,
                maximum=self.limits.max_json_bytes,
            )
            require(media_type == "application/json", "response")
            try:

                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError("Duplicate response field")
                        result[key] = value
                    return result

                listing = json.loads(raw, object_pairs_hook=unique)
            except (ValueError, UnicodeError):
                raise ProductivityError("response") from None
            require(type(listing) is dict and type(listing.get("items", [])) is list, "response")
            require(len(listing.get("items", [])) <= self.limits.max_items_per_page, "limit")
            zone = listing.get("timeZone")
            if not zone and any(
                "dateTime" in row.get("start", {}) for row in listing.get("items", [])
            ):
                zone = self._json(
                    ORIGIN + "/calendars/" + quote(selected, safe="") + "?fields=id,timeZone",
                    reference,
                ).get("timeZone")
            items = tuple(
                map_calendar_event(row, selected, zone) for row in listing.get("items", [])
            )
            self._items += len(items)
            require(self._items <= self.limits.max_items_per_run, "limit")
            next_page, checkpoint = listing.get("nextPageToken"), listing.get("nextSyncToken")
            require(next_page is not None or checkpoint is not None, "incomplete")
            self.recheck()
            return ReadPage(
                items,
                next_cursor=next_page,
                checkpoint=checkpoint,
                originals=tuple(raw for _ in items),
                response=raw,
                snapshot_mode="delta" if self.sync_token is not None else "full",
            ).validate()
        except GoogleCursorInvalidated:
            raise
        finally:
            self._active_token = None


def execute_calendar_job(manager, job, request, *, checkpoint=None):
    """One bounded scheduler slice; continuation is distinct from Source completion."""
    import time
    from dataclasses import replace

    from .google_connection import GoogleConnectionManager
    from .productivity_connectors import ProductivityConnectors
    from .productivity_generations import ProductivityGenerations
    from .productivity_intake import ProductivityIntake
    from .storage import utc_now

    source_id, job_id = request["source_id"], job["id"]
    connection = getattr(manager, "calendar_connection", None) or GoogleConnectionManager(
        manager.store
    )
    source = manager.sources.source_record(source_id, require_enabled=True)
    if source["cursor"].get("reset_origin") == "invalidated":
        raise GoogleCursorInvalidated()
    limits = GoogleLimits.from_mapping(request["limits"])
    page_size = source["cursor"].get("calendar_page_size", min(limits.max_items_per_page, 200))
    require(page_size <= limits.max_items_per_page, "limit")
    adapter = GoogleCalendarAdapter(
        connection, source_id, api=getattr(manager, "calendar_api", None)
    )
    adapter.limits = replace(
        limits,
        max_items_per_page=page_size,
        max_json_bytes=min(limits.max_json_bytes, 2 * 1024 * 1024),
    )
    host, intake = ProductivityConnectors(manager.store), ProductivityIntake(manager.store)
    scheduled = job.get("reason") in {"scheduled", "coalesced", "catch_up"}
    authority = host.authority(source_id, "calendar_read", scheduled=scheduled)
    binding = {**adapter._initial, "authority_sha256": authority["sha256"]}
    generations = ProductivityGenerations(manager.store, source_id)
    state = generations.prepare(binding, page_size)
    adapter.sync_token = state["base_checkpoint"]
    progress = {"processed": 0, "skipped": 0, "errors": 0}
    manager._write_run(job_id, request, status="running", progress=progress)
    deadline, total_bytes = time.monotonic() + 60, 0

    def cancelled():
        return manager._cancel_requested(job_id)

    try:
        for _page in range(limits.max_pages_per_run):
            require(not cancelled(), "cancelled")
            require(time.monotonic() < deadline, "deadline")
            if (
                _page
                and limits.max_items_per_run - progress["processed"] - progress["skipped"]
                < page_size
            ):
                break
            require(
                host.authority(source_id, "calendar_read", scheduled=scheduled) == authority,
                "stale",
            )
            identity = manager.store.read_canonical("connector-instances", authority["identity_id"])
            canonical_source = manager.store.read_canonical("sources", source_id)
            page = adapter.read_page(
                identity=identity,
                source=canonical_source,
                cursor=state["page_token"],
                credential=None,
            )
            require(time.monotonic() < deadline, "deadline")
            total_bytes += len(page.response or b"")
            require(total_bytes <= min(limits.max_total_bytes_per_run, 8 * 1024 * 1024), "limit")
            preview = host.page_preview(
                source_id,
                "calendar_read",
                page,
                expected_authority=authority["sha256"],
                scheduled=scheduled,
            )
            generations.check_page(state, preview)
            # The ordinary scheduler owns the outer Instance lifecycle barrier.
            result = intake.import_page_locked(
                preview, cancelled=cancelled, recheck=adapter.recheck
            )
            progress["processed"] += sum(row["status"] == "imported" for row in result["results"])
            progress["skipped"] += sum(row["status"] == "unchanged" for row in result["results"])
            require(
                progress["processed"] + progress["skipped"] <= limits.max_items_per_run, "limit"
            )
            with host.connectors.policy_commit_guard(purpose="google-calendar-checkpoint"):
                require(not cancelled(), "cancelled")
                require(
                    host.authority(source_id, "calendar_read", scheduled=scheduled) == authority,
                    "stale",
                )
                adapter.recheck()
                current = manager.sources.source_record(source_id)
                now, complete = utc_now(), page.next_cursor is None
                updated = {
                    **current,
                    "cursor": {
                        **current["cursor"],
                        "provider_cursor": page.next_cursor,
                        "page_ordinal": 0 if complete else state["pages"] + 1,
                        "calendar_page_size": page_size,
                        "page_fingerprints": [],
                        "resync_required": False,
                        "reset_origin": None,
                        "last_attempt_at": now,
                        "last_success_at": now,
                        "last_status": "complete" if complete else "checkpointed",
                    },
                    "health": {
                        "status": "ready",
                        "code": "google_read_succeeded",
                        "checked_at": now,
                    },
                    "updated_at": now,
                }
                source_path = (
                    (manager.sources.sources / (source_id + ".json"))
                    .relative_to(manager.store.paths.root)
                    .as_posix()
                )
                state = generations.publish_page(
                    state, preview, result, metadata=[(source_path, updated)]
                )
            if checkpoint is not None:
                checkpoint(progress)
            if complete:
                break
        status = "completed" if state["status"] == "completed" else "continuation_available"
        manager._write_run(job_id, request, status=status, progress=progress)
        return progress
    except ProductivityError as error:
        if error.code in {"cursor_invalidated", "cursor_loop"}:
            raise GoogleCursorInvalidated() from None
        code = {
            "cancelled": "google_cancelled",
            "stale": "google_input_changed",
            "limit": "google_backfill_limit_exceeded",
            "deadline": "google_retryable_failure",
            "authorization_required": "google_authorization_required",
        }.get(error.code, "google_payload_invalid")
        manager._write_run(job_id, request, status="failed", progress=progress, error_codes=[code])
        raise GoogleContractError(code, "Calendar read did not complete") from None
