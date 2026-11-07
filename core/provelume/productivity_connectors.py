"""Source-bound productivity consent and bounded read sessions on Core identities."""

from __future__ import annotations

import hashlib
import time
from copy import deepcopy

from .connector_model import connector_instance_lifecycle, connector_source_lifecycle
from .connectors import ConnectorManager
from .index_evidence import publish_once
from .instance_lifecycle import InstanceLifecycleManager
from .productivity_contract import (
    MAX_SESSION_BYTES,
    READ_CAPABILITIES,
    ProductivityError,
    fingerprint,
    require,
)
from .review_decisions import checked_path, read_json

ROOT = "state/productivity-connectors"
MAX_POLICY_REVISIONS = 1024
MAX_READ_PAGES = 50
MAX_READ_ITEMS = 5000
MAX_READ_SECONDS = 60
SOURCE_CAPABILITIES = {"tasks": {"task_read"}, "calendar": {"calendar_read"},
                       "icalendar": {"calendar_read"}}


def preview_digest(value):
    return fingerprint([value["authority"], value["items"], value["checkpoint"],
        [(hashlib.sha256(raw).hexdigest() if raw else None, media_type)
         for raw, media_type in value["_originals"]],
        [(hashlib.sha256(raw).hexdigest(), media_type) for raw, media_type in value["_responses"]],
        value["snapshot_mode"], value["schema"], value.get("continuation")],
        maximum=MAX_SESSION_BYTES)


def read_preview(authority, items, originals, responses, checkpoint, mode, *, page=False,
                 continuation=None):
    value = {"schema": "productivity-page-preview/v1" if page else "productivity-read-preview/v1",
             "authority": authority, "items": items, "checkpoint": checkpoint,
             "_originals": originals, "_responses": responses, "snapshot_mode": mode,
             "continuation": continuation, "canonical_mutation": False, "cursor_advanced": False}
    value["sha256"] = preview_digest(value)
    return value


class ProductivityConnectors:
    def __init__(self, store):
        self.store = store
        self.connectors = ConnectorManager(store)

    def _records(self, source_id):
        definitions, identities, sources = self.connectors._state()
        source = sources.get(source_id)
        require(source is not None, "source_missing")
        identity = identities[source["connector_instance_id"]]
        definition = definitions[identity["definition_id"]]
        return identity, source, definition

    def policy(self, source_id):
        self._records(source_id)
        directory = checked_path(self.store, f"{ROOT}/{source_id}/policies")
        paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
        require(len(paths) <= MAX_POLICY_REVISIONS, "limit")
        previous = None
        for revision, path in enumerate(paths, 1):
            require(path.name == f"{revision:06d}.json", "integrity")
            value = read_json(self.store, path.relative_to(self.store.paths.root).as_posix())
            require(type(value) is dict and set(value) == {
                "schema", "instance_id", "source_id", "revision", "previous_sha256",
                "capabilities", "mode"}, "integrity")
            require(value["schema"] == "productivity-source-consent/v1"
                    and value["instance_id"] == self.store.read_config()["instance"]["id"]
                    and value["source_id"] == source_id and value["revision"] == revision
                    and value["previous_sha256"] == (fingerprint(previous) if previous else None)
                    and type(value["capabilities"]) is list
                    and all(type(item) is str for item in value["capabilities"])
                    and value["capabilities"] == sorted(set(value["capabilities"]))
                    and set(value["capabilities"]) <= READ_CAPABILITIES
                    and type(value["mode"]) is str
                    and value["mode"] in {"disabled", "manual", "scheduled"}, "integrity")
            previous = value
        return previous

    def consent(self, source_id, *, capabilities, mode, expected_revision, confirmed):
        require(confirmed is True, "consent_required")
        require(type(capabilities) is list and all(type(item) is str for item in capabilities)
                and capabilities == sorted(set(capabilities))
                and set(capabilities) <= READ_CAPABILITIES
                and type(mode) is str and mode in {"disabled", "manual", "scheduled"})
        with InstanceLifecycleManager(self.store)._hold(purpose="productivity-consent"), \
                self.connectors.policy_commit_guard(purpose="productivity-consent"):
            _identity, _source, definition = self._records(source_id)
            require(set(capabilities) <= set(definition["capabilities"])
                    and set(capabilities) <= SOURCE_CAPABILITIES.get(_source["source_kind"], set()),
                    "unsupported")
            require(mode == "disabled" or bool(capabilities), "consent_required")
            previous = self.policy(source_id)
            revision = previous["revision"] if previous else 0
            require(type(expected_revision) is int and revision == expected_revision, "stale")
            require(revision < MAX_POLICY_REVISIONS, "limit")
            value = {"schema": "productivity-source-consent/v1",
                     "instance_id": self.store.read_config()["instance"]["id"],
                     "source_id": source_id, "revision": revision + 1,
                     "previous_sha256": fingerprint(previous) if previous else None,
                     "capabilities": capabilities, "mode": mode}
            publish_once(self.store, f"{ROOT}/{source_id}/policies/{revision + 1:06d}.json", value)
            return value

    def authority(self, source_id, capability, *, scheduled=False):
        require(type(capability) is str and capability in READ_CAPABILITIES, "unsupported")
        require(type(scheduled) is bool)
        identity, source, definition = self._records(source_id)
        require(identity["credential_reference"] is None, "external_credentials_required")
        require(capability in SOURCE_CAPABILITIES.get(source["source_kind"], set()), "unsupported")
        for lifecycle in (connector_instance_lifecycle(identity),
                          connector_source_lifecycle(source)):
            require(lifecycle["enabled"] and lifecycle["lifecycle_state"] == "active", "disabled")
        policy = self.policy(source_id)
        require(policy is not None and policy["mode"] != "disabled"
                and capability in policy["capabilities"]
                and capability in definition["capabilities"], "consent_required")
        require(not scheduled or policy["mode"] == "scheduled", "consent_required")
        network = self.store.read_config()["network"]
        local = definition["network_access"] == "none"
        if not local:
            require(network["external_access"] and identity["network_mode"] == "explicit",
                    "network_disabled")
        # Secret values and references are deliberately absent. Provider adapters
        # resolve device-external authorization only at their own request boundary.
        return {"source_id": source_id, "identity_id": identity["id"],
                "capability": capability, "scheduled": scheduled,
                "sha256": fingerprint([identity, source, definition, policy, network]),
                "policy_sha256": fingerprint(policy)}

    def preview(self, source_id, capability, adapter, *, expected_authority, credentials=None,
                scheduled=False, cancelled=lambda: False):
        """Read a bounded session; no cursor or canonical mutation on preview/failure."""
        admitted = self.authority(source_id, capability, scheduled=scheduled)
        require(admitted["sha256"] == expected_authority, "stale")
        identity, source, _definition = self._records(source_id)
        authorization = None
        if "external_secret_authorization" in _definition["capabilities"]:
            require(credentials is not None, "authorization_required")
            authorization = credentials.resolve(identity["id"], capability).validate(
                identity["id"], capability)
        deadline, cursor, seen, items = time.monotonic() + MAX_READ_SECONDS, None, set(), []
        originals, original_sizes, responses, snapshot_mode = [], {}, [], None
        for _page_number in range(MAX_READ_PAGES):
            require(not cancelled(), "cancelled")
            require(time.monotonic() < deadline, "deadline")
            require(self.authority(source_id, capability, scheduled=scheduled) == admitted, "stale")
            if authorization is not None:
                current = credentials.resolve(identity["id"], capability).validate(
                    identity["id"], capability)
                require(current.revision_sha256 == authorization.revision_sha256, "stale")
            page = adapter.read_page(identity=deepcopy(identity), source=deepcopy(source),
                                     cursor=cursor, credential=deepcopy(
                                         current.payload) if authorization else None).validate()
            require(snapshot_mode is None or snapshot_mode == page.snapshot_mode, "response")
            snapshot_mode = page.snapshot_mode
            if page.response is not None:
                responses.append((page.response, page.media_type))
                original_sizes[hashlib.sha256(page.response).hexdigest()] = len(page.response)
            require(not cancelled(), "cancelled")
            require(time.monotonic() < deadline, "deadline")
            require(self.authority(source_id, capability, scheduled=scheduled) == admitted, "stale")
            if authorization is not None:
                require(credentials.resolve(identity["id"], capability).validate(
                    identity["id"], capability).revision_sha256 == authorization.revision_sha256,
                    "stale")
            items.extend(deepcopy(page.items))
            originals.extend(zip(page.originals, [page.media_type] * len(page.originals),
                                 strict=True)
                             if page.originals else [(None, page.media_type)] * len(page.items))
            for raw in page.originals:
                original_sizes[hashlib.sha256(raw).hexdigest()] = len(raw)
            require(sum(original_sizes.values()) <= MAX_SESSION_BYTES, "limit")
            require(len(items) <= MAX_READ_ITEMS, "limit")
            fingerprint(items, maximum=MAX_SESSION_BYTES)
            if page.next_cursor is None:
                keys = [item["remote_id"] for item in items]
                require(len(keys) == len(set(keys)), "duplicate")
                return read_preview(admitted, items, originals, responses,
                                    page.checkpoint, snapshot_mode)
            require(page.next_cursor not in seen, "cursor_loop")
            seen.add(page.next_cursor)
            cursor = page.next_cursor
        raise ProductivityError("limit")

    def page_preview(self, source_id, capability, page, *, expected_authority, scheduled=False):
        """One actual provider page, explicitly distinct from Source completeness."""
        authority = self.authority(source_id, capability, scheduled=scheduled)
        require(authority["sha256"] == expected_authority, "stale")
        page.validate()
        require(len(page.originals) == len(page.items), "original_required")
        return read_preview(authority, deepcopy(list(page.items)),
            list(zip(page.originals, [page.media_type] * len(page.originals), strict=True)),
            [(page.response, page.media_type)] if page.response is not None else [],
            page.checkpoint, page.snapshot_mode, page=True, continuation=page.next_cursor)
