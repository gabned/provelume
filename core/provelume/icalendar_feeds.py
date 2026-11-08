"""Explicit local/HTTPS iCalendar feeds with external locations and exact Originals."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .connectors import ConnectorManager
from .google_credentials import GoogleCredentialVault
from .icalendar_worker import MAX_FEED_BYTES, MAX_OUTPUT_BYTES, _zone
from .instance_lifecycle import InstanceLifecycleManager
from .productivity_connectors import ProductivityConnectors
from .productivity_contract import ProductivityError, ReadPage, fingerprint, require, text
from .productivity_intake import ProductivityIntake


def _local_path(value, forbidden):
    path = Path(value)
    require(path.is_absolute() and not path.is_relative_to(forbidden), "location")
    require(not any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)),
            "location")
    require(not path.resolve().is_relative_to(forbidden.resolve()), "location")
    return path


def _origin(url):
    text(url, 8192)
    require(not any(char.isspace() for char in url), "location")
    try:
        value = urlsplit(url)
        _port = value.port
    except ValueError:
        raise ProductivityError("location") from None
    require(value.scheme == "https" and value.hostname and value.username is None
            and value.password is None and not value.fragment, "location")
    return "https://" + value.netloc


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_https_direct(location, deadline):
    _origin(location["location"])
    headers = {"Accept": "text/calendar", "User-Agent": "Provelume iCalendar readonly"}
    if location.get("authorization"):
        headers["Authorization"] = location["authorization"]
    request = Request(location["location"], headers=headers, method="GET")
    try:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "deadline")
        with build_opener(_NoRedirect()).open(request, timeout=min(30, remaining)) as response:
            require(response.status == 200, "response")
            require(len(response.headers) <= 100
                    and len(response.headers.as_bytes()) <= 65536, "response")
            require(response.headers.get("Content-Encoding", "identity").lower() == "identity",
                    "unsupported")
            require(response.headers.get_content_type() in {"text/calendar", "application/ics",
                    "application/octet-stream", "text/plain"}, "response")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                require(len(response.headers.get_all("Content-Length")) == 1, "response")
                require(declared.isdecimal() and int(declared) <= MAX_FEED_BYTES, "limit")
            chunks, size = [], 0
            while True:
                require(time.monotonic() < deadline, "deadline")
                sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                require(sock is not None, "unsupported")
                sock.settimeout(min(30, deadline - time.monotonic()))
                chunk = response.read1(min(65536, MAX_FEED_BYTES + 1 - size))
                require(time.monotonic() < deadline, "deadline")
                if not chunk:
                    require(declared is None or int(declared) == size, "incomplete")
                    return b"".join(chunks)
                chunks.append(chunk)
                size += len(chunk)
                require(size <= MAX_FEED_BYTES, "limit")
    except HTTPError as error:
        code = "authorization_required" if error.code in {401, 403} else (
            "rate_limited" if error.code == 429 else "response")
        raise ProductivityError(code) from None
    except (OSError, URLError):
        raise ProductivityError("transport") from None


def _isolated_result(header, raw, deadline, *, timeout, maximum, network=False):
    environment = {key: value for key, value in os.environ.items() if key.upper() in {
        "PATH", "HOME", "LANG", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"
    }}
    environment["PYTHONNOUSERSITE"] = "1"
    if network:
        environment.update({key: value for key, value in os.environ.items() if key.upper() in {
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"
        }})
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--internal-icalendar-worker"]
    else:
        environment["PYTHONPATH"] = str(Path(__file__).absolute().parent.parent)
        command = [sys.executable, "-m", "provelume.icalendar_worker"]
    header = json.dumps(header).encode() + b"\n"
    try:
        remaining = min(timeout, deadline - time.monotonic())
        require(remaining > 0, "deadline")
        with TemporaryDirectory(prefix="provelume-icalendar-") as directory:
            source, output = Path(directory) / "input", Path(directory) / "output"
            source.write_bytes(header + raw)
            result = subprocess.run(command + ["--input", str(source), "--output", str(output)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=environment, timeout=remaining, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            require(result.returncode == 0 and output.is_file() and not output.is_symlink()
                    and output.stat().st_size <= maximum, "parse")
            return output.read_bytes()
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ProductivityError("parse") from None


def fetch_https(location, deadline):
    # The owner bounds DNS, TLS, headers and the whole body, including hosts
    # whose DNS resolver does not honor a socket timeout.
    return _isolated_result({"mode": "fetch", "location": location}, b"", deadline,
                            timeout=30, maximum=MAX_FEED_BYTES, network=True)


def parse_isolated(raw, feed_id, zone_name, deadline):
    data = _isolated_result({"mode": "parse", "feed_id": feed_id, "time_zone": zone_name},
                            raw, deadline, timeout=15, maximum=MAX_OUTPUT_BYTES)
    try:
        values = json.loads(data)
        require(type(values) is dict and set(values) == {"items"}, "parse")
        return values["items"]
    except ValueError:
        raise ProductivityError("parse") from None


class FeedAdapter:
    def __init__(self, manager, source_id):
        self.manager, self.source_id = manager, source_id
        self.location = manager.location(source_id)
        self.revision = fingerprint(self.location)
        self.raw, self.items = None, None
        self.deadline = time.monotonic() + 60

    def recheck(self):
        require(fingerprint(self.manager.location(self.source_id)) == self.revision, "stale")

    def read_page(self, *, identity, source, cursor, credential):
        del credential
        require(source["id"] == self.source_id and source["connector_instance_id"]
                == identity["id"], "stale")
        self.recheck()
        if self.raw is None:
            self.raw = self.manager.read(self.location, self.deadline)
            require(0 < len(self.raw) <= MAX_FEED_BYTES, "limit")
            self.items = parse_isolated(self.raw, source["external_id"],
                                       self.location.get("time_zone"), self.deadline)
        require(cursor is None or (type(cursor) is str and cursor.isdecimal()), "cursor")
        start = int(cursor or 0)
        require(start % 200 == 0 and start <= len(self.items), "cursor")
        values = tuple(self.items[start:start + 200])
        more = start + len(values) < len(self.items)
        self.recheck()
        return ReadPage(values, next_cursor=str(start + len(values)) if more else None,
                        checkpoint=None if more else hashlib.sha256(self.raw).hexdigest(),
                        originals=(self.raw,) * len(values), media_type="text/calendar",
                        response=self.raw if start == 0 else None).validate()


class IcalendarFeeds:
    def __init__(self, store, *, vault=None, transport=None):
        self.store, self.connectors = store, ConnectorManager(store)
        self.host = ProductivityConnectors(store)
        self.vault = vault if vault is not None else GoogleCredentialVault(
            forbidden_root=store.paths.root, namespace="productivity")
        self.transport = transport or fetch_https
        self.network_used = False

    @staticmethod
    def slot(source_id):
        require(re.fullmatch(r"src_[0-9a-f]{32}", source_id) is not None, "source_missing")
        return "productivity_feed_" + source_id

    def location(self, source_id):
        identity, source, definition = self.host._records(source_id)
        require(definition["provider"] == "icalendar" and source["source_kind"] == "icalendar",
                "unsupported")
        value = self.vault.read(self.slot(source_id))
        require(type(value) is dict and value.get("source_id") == source_id
                and value.get("identity_id") == identity["id"]
                and value.get("external_id") == source["external_id"], "authorization_required")
        if value["kind"] == "https":
            require(_origin(value["location"]) in identity["allowed_origins"], "location")
        else:
            require(value["kind"] == "local" and definition["network_access"] == "none",
                    "location")
        return value

    @staticmethod
    def selection(kind, location):
        return "feed_" + fingerprint([kind, str(location)])

    def reconnect(self, source_id, *, kind, location, expected_policy_revision, confirmed,
                  authorization=None, time_zone=None):
        require(confirmed is True, "consent_required")
        with InstanceLifecycleManager(self.store)._hold(purpose="icalendar-reconnect"), \
                self.connectors.policy_commit_guard(purpose="icalendar-reconnect"):
            return self._reconnect_locked(source_id, kind=kind, location=location,
                expected_policy_revision=expected_policy_revision, authorization=authorization,
                time_zone=time_zone)

    def _reconnect_locked(self, source_id, *, kind, location, expected_policy_revision,
                          authorization, time_zone):
        identity, source, definition = self.host._records(source_id)
        require(definition["provider"] == "icalendar"
                and source["external_id"] == self.selection(kind, location), "stale")
        policy = self.host.policy(source_id)
        require(policy is not None and policy["revision"] == expected_policy_revision, "stale")
        self.validate_location(kind, location, authorization, time_zone)
        slot = self.slot(source_id)
        previous = self.vault.read(slot)
        self.vault.write(slot, {"source_id": source_id, "identity_id": identity["id"],
            "external_id": source["external_id"], "kind": kind, "location": str(location),
            "authorization": authorization, "time_zone": time_zone,
            "revision": previous["revision"] + 1 if previous else 1})
        return {"source_id": source_id, "status": "device_connection_saved"}

    def validate_location(self, kind, location, authorization, time_zone):
        require(kind in {"local", "https"})
        if time_zone is not None:
            _zone(time_zone)
        if authorization is not None:
            text(authorization, 4096)
            require(kind == "https" and not any(char in authorization for char in "\r\n\t"))
        if kind == "local":
            _local_path(location, self.store.paths.root)
        else:
            _origin(location)

    def add(self, *, name, kind, location, confirmed, authorization=None, time_zone=None):
        require(confirmed is True, "consent_required")
        text(name, 200)
        self.validate_location(kind, location, authorization, time_zone)
        origin = _origin(location) if kind == "https" else None
        definition = self.connectors.register_definition({
            "adapter_key": "concordia-icalendar-" + kind, "adapter_version": "1.0.0",
            "display_name": "iCalendar " + kind, "provider": "icalendar",
            "conformance_profile": "provelume.connector.v1", "adapter_protocol_version": 1,
            "capabilities": ["manual_read", "source_selection", "calendar_read"],
            "authorization_modes": ["none"], "source_kinds": ["icalendar"],
            "data_categories": ["calendar.event"], "multi_instance": True,
            "network_access": "explicit_only" if origin else "none"})
        identity = self.connectors.create_instance(
            definition["id"], name=name, provider_identity="icalendar",
            account_identity="feed-local:" + uuid4().hex,
            network_mode="explicit" if origin else "disabled",
            allowed_origins=[origin] if origin else [])
        source = self.connectors.add_source(identity["id"], name=name, source_kind="icalendar",
                                            external_id=self.selection(kind, location))
        try:
            self.vault.write(self.slot(source["id"]), {
                "source_id": source["id"], "identity_id": identity["id"],
                "external_id": source["external_id"], "kind": kind, "location": str(location),
                "authorization": authorization, "time_zone": time_zone, "revision": 1})
            self.host.consent(source["id"], capabilities=["calendar_read"], mode="manual",
                              expected_revision=0, confirmed=True)
        except Exception:
            self.connectors.disable_instance(identity["id"])
            raise
        return {"identity_id": identity["id"], "source_id": source["id"], "mode": "manual"}

    def read(self, location, deadline):
        if location["kind"] == "https":
            self.network_used = self.transport is fetch_https
            return self.transport(location, deadline)
        path = _local_path(location["location"], self.store.paths.root)
        try:
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_FEED_BYTES, "limit")
                raw = stream.read(MAX_FEED_BYTES + 1)
                after = os.fstat(stream.fileno())
                _local_path(path, self.store.paths.root)
                require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                        and path.stat().st_ino == after.st_ino, "stale")
                require(time.monotonic() < deadline, "deadline")
                return raw
        except OSError:
            raise ProductivityError("local_io") from None

    def preview(self, source_id, *, scheduled=False, cancelled=lambda: False):
        authority = self.host.authority(source_id, "calendar_read", scheduled=scheduled)
        adapter = FeedAdapter(self, source_id)
        result = self.host.preview(source_id, "calendar_read", adapter,
                    expected_authority=authority["sha256"], scheduled=scheduled,
                    cancelled=cancelled)
        return result, adapter

    def refresh(self, source_id, *, cancelled=lambda: False):
        preview, adapter = self.preview(source_id, cancelled=cancelled)
        return ProductivityIntake(self.store).accept(preview, cancelled=cancelled,
                                                     recheck=adapter.recheck)

    def duplicates(self):
        groups = {}
        for source in self.store.list_canonical("sources"):
            if source.get("kind") != "connector" or source.get("source_kind") != "icalendar":
                continue
            for row in ProductivityIntake(self.store).records(source["id"]):
                item = row["item"]
                key = (item["provenance"]["uid"], item["provenance"]["recurrence_id"])
                groups.setdefault(key, []).append({"source_id": source["id"],
                    "document_id": row["document_id"], "version_id": row["version_id"]})
        return [{"uid": uid, "recurrence_id": occurrence, "members": members,
                 "reason": "same_uid_and_instance_in_independent_sources", "merged": False}
                for (uid, occurrence), members in groups.items() if len(members) > 1]
