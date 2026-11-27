"""Isolated RFC5545 mapping worker. Bytes in, bounded JSON out; no network or vault."""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

import tzdata.zoneinfo as shipped_zones

from .productivity_contract import fingerprint, require, temporal, text, validate_item

MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 5000
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def _zone(name):
    text(name, 100)
    require(re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", name)
            and all(part not in {".", ".."} for part in name.split("/")), "time_zone")
    try:
        with files(shipped_zones).joinpath(*name.split("/")).open("rb") as stream:
            return ZoneInfo.from_file(stream, key=name)
    except (OSError, ValueError):
        raise ValueError("Unsupported explicit feed zone") from None


def _one(component, key, default=None):
    value = component.get(key, default)
    require(not isinstance(value, list), "duplicate")
    return value


def _when(value, zone_name):
    instant = value.dt if hasattr(value, "dt") else value
    if isinstance(instant, datetime):
        original = str(getattr(value, "params", {}).get("TZID", ""))
        # Known TZIDs use shipped tzdata, independent of the host/cache. Custom
        # VTIMEZONE values are converted to exact UTC instants, retaining TZID
        # separately and the complete definition in the acquired Original.
        if original:
            try:
                zone = _zone(original)
                instant = instant.replace(tzinfo=zone)
            except ValueError:
                require(instant.tzinfo is not None, "time_zone")
                instant = instant.astimezone(UTC)
        elif instant.tzinfo is None:
            require(zone_name is not None, "time_zone")
            instant = instant.replace(tzinfo=_zone(zone_name))
        else:
            instant = instant.astimezone(UTC)
        key = getattr(instant.tzinfo, "key", None) or "UTC"
        # RFC5545 floating/nonexistent wall times use the pre-gap offset.
        # Normalize the resulting instant into the zone before strict validation.
        instant = instant.astimezone(UTC).astimezone(_zone(key))
        result = {"kind": "instant", "value": instant.isoformat(), "time_zone": key}
    else:
        require(isinstance(instant, date), "time_zone")
        result = {"kind": "date", "value": instant.isoformat(), "time_zone": None}
    temporal(result)
    return result


def _values(component, key):
    value = component.get(key, [])
    return value if isinstance(value, list) else [value]


def map_event(component, feed_id, zone_name, *, cancelled=False):
    uid = text(str(_one(component, "UID", "")), 1800)
    recurrence = _one(component, "RECURRENCE-ID")
    recurrence_id = (
        recurrence.to_ical().decode("utf-8") + ";TZID="
        + str(getattr(recurrence, "params", {}).get("TZID", ""))
        if recurrence is not None else None
    )
    status = "cancelled" if cancelled else str(_one(component, "STATUS", "CONFIRMED")).lower()
    require(status in {"tentative", "confirmed", "cancelled"}, "unsupported")
    start, end = _one(component, "DTSTART"), _one(component, "DTEND")
    duration = _one(component, "DURATION")
    require(end is None or duration is None, "invalid")
    require(start is not None or status == "cancelled", "incomplete")
    if start is not None and end is None:
        if duration is not None:
            end = start.dt + duration.dt
        elif type(start.dt) is date:
            end = start.dt + timedelta(days=1)
        else:
            # RFC5545 timed events without DTEND/DURATION are instantaneous.
            # Preserve that source value; never invent an end after the start.
            end = start.dt
    rules = []
    for key in ("RRULE", "RDATE", "EXDATE", "EXRULE"):
        for value in _values(component, key):
            params = ";".join(f"{name}={item}" for name, item in sorted(value.params.items()))
            rules.append(key + (";" + params if params else "") + ":"
                         + value.to_ical().decode("utf-8"))
    zones = {key.lower(): str(getattr(value, "params", {}).get("TZID", "")) or None
             for key, value in (("starts", start), ("ends", end), ("recurrence", recurrence))}
    result = {
        "remote_id": json.dumps([uid, recurrence_id], ensure_ascii=False, separators=(",", ":")),
        "revision": fingerprint(base64.b64encode(component.to_ical()).decode("ascii")),
        "revision_kind": "content_sha256", "kind": "calendar_event",
        "title": str(_one(component, "SUMMARY", "")),
        "description": str(_one(component, "DESCRIPTION", "")), "state": status,
        "due": None, "starts": _when(start, zone_name) if start is not None else None,
        "ends": _when(end, zone_name) if end is not None else None,
        "provenance": {"container_ids": [feed_id], "parent_id": uid if recurrence else None,
                       "uid": uid, "recurrence_id": recurrence_id, "recurrence": rules,
                       "assignees": [str(value) for value in _values(component, "ATTENDEE")],
                       "comments": [str(value) for value in _values(component, "COMMENT")],
                       "links": [str(value) for value in _values(component, "URL")],
                       "original_time_zones": zones},
    }
    return validate_item(result)


def parse_feed(raw, feed_id, zone_name=None):
    from icalendar import Calendar

    require(type(raw) is bytes and 0 < len(raw) <= MAX_FEED_BYTES, "limit")
    lines = raw.decode("utf-8-sig").replace("\r\n", "\n").split("\n")
    require(len(lines) <= 30000 and all(len(line) <= 128 * 1024 for line in lines), "limit")
    stack, components = [], 0
    for line in lines:
        upper = line.upper()
        if upper.startswith("BEGIN:"):
            stack.append(upper[6:])
            components += 1
            require(len(stack) <= 8 and components <= 6500, "limit")
        elif upper.startswith("END:"):
            require(stack and stack.pop() == upper[4:], "invalid")
    require(not stack, "incomplete")
    calendar = Calendar.from_ical(raw)
    require(calendar.name == "VCALENDAR" and str(calendar.get("VERSION")) == "2.0")
    require(str(calendar.get("METHOD", "PUBLISH")) in {"PUBLISH", "CANCEL"}, "unsupported")
    require(all(not component.errors for component in calendar.walk()), "invalid")
    require(all(component.name in {"VEVENT", "VTIMEZONE"}
                for component in calendar.subcomponents), "unsupported")
    zone_name = zone_name or str(calendar.get("X-WR-TIMEZONE", "")) or None
    if zone_name is not None:
        _zone(zone_name)
    events = calendar.walk("VEVENT")
    require(len(events) <= MAX_EVENTS, "limit")
    values = [map_event(component, feed_id, zone_name,
                        cancelled=str(calendar.get("METHOD")) == "CANCEL") for component in events]
    identities = [value["remote_id"] for value in values]
    require(len(identities) == len(set(identities)), "duplicate")
    return values


def main():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--input", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        arguments = sys.argv[1:]
        if arguments[:1] == ["--internal-icalendar-worker"]:
            arguments = arguments[1:]
        options = parser.parse_args(arguments)
        if sys.platform != "win32":
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (10, 11))
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        require(not options.input.is_symlink() and not options.output.is_symlink(), "location")
        with options.input.open("rb") as stream:
            header = json.loads(stream.readline(16384))
            raw = stream.read(MAX_FEED_BYTES + 1)
        if header.get("mode") == "fetch":
            from .icalendar_feeds import _fetch_https_direct

            output = _fetch_https_direct(header["location"], time.monotonic() + 30)
            require(len(output) <= MAX_FEED_BYTES, "limit")
        else:
            values = parse_feed(raw, header["feed_id"], header.get("time_zone"))
            output = json.dumps({"items": values}, ensure_ascii=False).encode("utf-8")
            require(len(output) <= MAX_OUTPUT_BYTES, "limit")
        with options.output.open("xb") as stream:
            stream.write(output)
        return 0
    except Exception:
        # Payload/provider parsing errors never echo private source values.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
