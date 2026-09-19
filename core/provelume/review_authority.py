"""Explicit, retained, scoped grants for reviewed domain effects.

Configuration itself is a local confirmed decision. It cannot grant an automatic
identity-changing action; only the implemented safe routing action is eligible.
"""

from __future__ import annotations

import json
import re

from .action_center_model import digest, json_bytes
from .review_decisions import (
    assert_review_readable,
    checked_path,
    read_bytes,
    read_json,
    receipt_identifier,
    validate_receipt,
)
from .review_effects import (
    ABSENT,
    PreparedEffect,
    PreparedWrite,
    ReviewError,
    ReviewUnavailable,
    sha256,
)

AUTHORITY_PATH = "state/review/authority.json"
MODES = {"disabled", "proposal-only", "confirm-each", "controlled-automatic"}
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


class ReviewAuthority:
    domain = "capabilities"
    actions = ("configure",)

    def __init__(self, store, capabilities):
        self.store = store
        self.capabilities = {key: frozenset(value) for key, value in capabilities.items()}
        if self.domain in self.capabilities:
            raise ReviewError("Capability configuration cannot grant itself")

    def _grant(self, domain, value):
        if (
            domain not in self.capabilities
            or not isinstance(value, dict)
            or set(value) != {"mode", "scope"}
        ):
            raise ReviewUnavailable("Unsupported review capability")
        mode, scope = value["mode"], value["scope"]
        if (
            not isinstance(mode, str) or mode not in MODES
            or not isinstance(scope, dict)
            or set(scope) != {"subjects", "actions", "sources"}
        ):
            raise ReviewUnavailable("Invalid review capability scope")
        for key in ("subjects", "actions", "sources"):
            entries = scope[key]
            if (
                not isinstance(entries, list)
                or len(entries) > 100
                or any(not isinstance(x, str) or not x or len(x) > 256 for x in entries)
                or entries != sorted(set(entries))
            ):
                raise ReviewUnavailable("Capability scope must be bounded and canonical")
        if (
            not scope["subjects"]
            or not scope["actions"]
            or not set(scope["actions"]) <= self.capabilities[domain]
        ):
            raise ReviewUnavailable("Capability requires explicit supported subjects and actions")
        if "*" in scope["subjects"] and scope["subjects"] != ["*"]:
            raise ReviewUnavailable("Wildcard scope cannot mix individual subjects")
        if any(re.fullmatch(r"src_[0-9a-f]{32}", x) is None for x in scope["sources"]):
            raise ReviewUnavailable("Capability source scope is invalid")
        if mode == "controlled-automatic" and (
            domain != "routing" or scope["actions"] != ["apply_rule"]
        ):
            raise ReviewUnavailable("Only safe routing application can be automatic")
        return value

    def read(self):
        assert_review_readable(self.store)
        state = read_json(self.store, AUTHORITY_PATH)
        assert_review_readable(self.store)
        if state is None:
            state = {"schema_version": 1, "generation": 0, "grants": {}}
        if (
            set(state) != {"schema_version", "generation", "grants"}
            or type(state["schema_version"]) is not int
            or state["schema_version"] != 1
            or type(state["generation"]) is not int
            or not 0 <= state["generation"] <= 10_000
            or not isinstance(state["grants"], dict)
            or len(state["grants"]) > len(self.capabilities)
        ):
            raise ReviewUnavailable("Retained review authority is invalid or unsupported")
        for domain, value in state["grants"].items():
            self._grant(domain, value)
        self._validate_history(state)
        assert_review_readable(self.store)
        return state

    def _validate_history(self, state):
        """The effective grant must be the result of the retained confirmed chain."""
        root = checked_path(self.store, "state/review/authority-history")
        current = {"schema_version": 1, "generation": 0, "grants": {}}
        rows, total = [], 0
        instance_id = self.store.read_config()["instance"]["id"]
        if root.exists():
            if not root.is_dir():
                raise ReviewUnavailable("Authority history is not a directory")
            for index, path in enumerate(root.iterdir()):
                if index >= 10_000 or re.fullmatch(r"review_[0-9a-f]{32}\.json", path.name) is None:
                    raise ReviewUnavailable("Authority history is invalid or exceeds its bound")
                relative = f"state/review/authority-history/{path.name}"
                raw = read_bytes(self.store, relative)
                history = read_json(self.store, relative)
                if raw is None or history is None or set(history) != {
                    "schema_version", "principal", "recorded_at", "capability", "before", "after",
                }:
                    raise ReviewUnavailable("Authority history is missing or unsupported")
                total += len(raw)
                if total > 32 * 1024 * 1024:
                    raise ReviewUnavailable("Authority history exceeds its byte bound")
                receipt = read_json(self.store, f"state/review/receipts/{path.name}")
                validate_receipt(receipt, instance_id=instance_id)
                if (
                    receipt["id"] != path.stem or receipt["domain"] != "capabilities"
                    or receipt["action"] != "configure"
                    or receipt["subject"] != history["capability"]
                    or receipt["history_ref"] != relative
                    or receipt["history_sha256"] != sha256(raw)
                    or receipt["principal"] != history["principal"]
                    or receipt["recorded_at"] != history["recorded_at"]
                    or type(history["schema_version"]) is not int or history["schema_version"] != 1
                    or not isinstance(history["after"], dict)
                    or type(history["after"].get("generation")) is not int
                ):
                    raise ReviewUnavailable("Authority history differs from its confirmation")
                rows.append(history)
        for history in sorted(rows, key=lambda row: row["after"]["generation"]):
            after, domain = history["after"], history["capability"]
            if (
                history["before"] != current
                or set(after) != {"schema_version", "generation", "grants"}
                or not isinstance(after["grants"], dict) or domain not in after["grants"]
            ):
                raise ReviewUnavailable("Authority history chain is incomplete")
            selected = self._grant(domain, after["grants"][domain])
            expected = {"schema_version": 1, "generation": current["generation"] + 1,
                        "grants": {**current["grants"], domain: selected}}
            if after != expected:
                raise ReviewUnavailable("Authority history changes unconfirmed grants")
            current = expected
        if current != state:
            raise ReviewUnavailable("Effective authority differs from its confirmed history")
        return total

    def resolve(self, domain, subject, action):
        state = self.read()
        if domain == self.domain and action == "configure" and subject in self.capabilities:
            selected = {
                "mode": "confirm-each",
                "scope": {"subjects": [subject], "actions": [action], "sources": []},
            }
        else:
            selected = state["grants"].get(
                domain,
                {"mode": "disabled", "scope": {"subjects": [], "actions": [], "sources": []}},
            )
        scope = selected["scope"]
        allowed = action in scope["actions"] and (
            subject in scope["subjects"] or "*" in scope["subjects"]
        )
        source = None
        if scope["sources"]:
            if re.fullmatch(r"doc_[0-9a-f]{32}", subject):
                record = read_json(self.store, f"knowledge/documents/{subject}.json")
                source = record.get("source_id") if record else None
            # A new rule has no retained source yet. Grant its exact subject
            # without source filtering, or create it before a source-scoped grant.
            allowed = allowed and source in scope["sources"]
        return {
            "revision": digest(
                {
                    "state": state,
                    "domain": domain,
                    "subject": subject,
                    "action": action,
                    "source": source,
                }
            ),
            "mode": selected["mode"] if allowed else "disabled",
            "scope": scope,
            "automatic_allowed": bool(
                allowed
                and domain == "routing"
                and action == "apply_rule"
                and selected["mode"] == "controlled-automatic"
            ),
        }

    def preview(self, subject, action, parameters):
        if action != "configure" or subject not in self.capabilities:
            raise ReviewError("Unsupported capability configuration")
        selected = self._grant(subject, parameters)
        state = self.read()
        raw = read_bytes(self.store, AUTHORITY_PATH)
        if (raw is None and state["generation"] != 0) or (
            raw is not None and json.loads(raw) != state
        ):
            raise ReviewUnavailable("Review authority changed during observation")
        if state["generation"] >= 10_000:
            raise ReviewUnavailable("Authority history reached its bound")
        return {
            "input_revision": digest(state),
            "snapshot": state,
            "history_bytes": self._validate_history(state),
            "preimage": ABSENT if raw is None else sha256(raw),
            "evidence": {
                "capability": subject,
                "before": state["grants"].get(subject),
                "after": selected,
            },
            "reason": "Explicit local grant or revocation of a bounded review capability",
            "confidence": None,
            "impact": "Changes which future effects may be confirmed in this scope",
            "reversibility": (
                "A new confirmed configuration can revoke the grant; "
                "committed effects retain their history"
            ),
        }

    def _history_ref(self, instance_id, request_id):
        return f"state/review/authority-history/{receipt_identifier(instance_id, request_id)}.json"

    def allowed_paths(self, plan, request_id):
        return frozenset({AUTHORITY_PATH, self._history_ref(plan["instance_id"], request_id)})

    def prepare(self, plan, *, request_id, principal, recorded_at):
        state = plan["provider"]["snapshot"]
        selected = self._grant(plan["subject"], plan["parameters"])
        candidate = {
            "schema_version": 1,
            "generation": state["generation"] + 1,
            "grants": {**state["grants"], plan["subject"]: selected},
        }
        history_ref = self._history_ref(plan["instance_id"], request_id)
        history = {
            "schema_version": 1,
            "principal": principal,
            "recorded_at": recorded_at,
            "capability": plan["subject"],
            "before": state,
            "after": candidate,
        }
        if plan["provider"]["history_bytes"] + len(json_bytes(history)) > 32 * 1024 * 1024:
            raise ReviewUnavailable("Authority history would exceed its byte bound")
        return PreparedEffect(
            self.domain,
            "configure",
            (
                PreparedWrite(
                    AUTHORITY_PATH, plan["provider"]["preimage"], json_bytes(candidate)
                ),
                PreparedWrite(history_ref, ABSENT, json_bytes(history), immutable=True),
            ),
            {
                "generation": candidate["generation"],
                "capability": plan["subject"],
                "mode": selected["mode"],
            },
            history_ref,
            "Changed explicit scoped review capability",
            "Revoke by a new confirmed configuration",
        )
