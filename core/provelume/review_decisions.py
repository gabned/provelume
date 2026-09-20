"""One lifecycle/CAS/atomic boundary for registered domain review providers."""

from __future__ import annotations

import json
import re
import stat
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

from .action_center_model import bounded_json, digest, json_bytes, request_identifier, revision
from .instance_lifecycle import InstanceLifecycleManager
from .review_effects import (
    ABSENT,
    MAX_ENTRY_BYTES,
    PreparedEffect,
    PreparedWrite,
    ReviewConflict,
    ReviewDenied,
    ReviewError,
    ReviewStale,
    ReviewUnavailable,
    relative_path,
    sha256,
)
from .storage import utc_now

MAX_HISTORY = 10_000
_RECEIPT = re.compile(r"review_[0-9a-f]{32}\.json\Z")
_MODES = {"disabled", "proposal-only", "confirm-each", "controlled-automatic"}


def checked_path(store, relative: str) -> Path:
    """Resolve without creating anything; reject links in every existing component."""
    relative_path(relative)
    current = store.paths.root
    target = current / relative
    for part in (None, *relative.split("/")):
        if part is not None:
            current = current / part
        try:
            observed = current.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        # Observe each component once, without following links or caching it
        # across operations. Other filesystem errors remain fail-closed.
        if stat.S_ISLNK(observed.st_mode) or getattr(observed, "st_reparse_tag", 0) == getattr(
            stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003
        ):
            raise ReviewUnavailable("Review evidence cannot traverse links")
        if current != target and not stat.S_ISDIR(observed.st_mode):
            raise ReviewUnavailable("Review evidence parent is not a directory")
    return current


def read_bytes(store, relative: str, *, maximum: int = MAX_ENTRY_BYTES) -> bytes | None:
    path = checked_path(store, relative)
    try:
        try:
            observed = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(observed.st_mode) or observed.st_size > maximum:
            raise ReviewUnavailable("Review evidence has the wrong type or exceeds its bound")
        with path.open("rb") as handle:
            # Most records are tiny. Bound each allocation as well as the total,
            # retaining the extra byte that detects growth beyond the limit.
            chunks, remaining = [], maximum + 1
            while remaining:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            value = b"".join(chunks)
        if len(value) > maximum:
            raise ReviewUnavailable("Review evidence exceeds its bound")
        return value
    except OSError as exc:
        raise ReviewUnavailable("Review evidence cannot be read") from exc


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReviewUnavailable("Duplicate review evidence field")
        result[key] = value
    return result


def decode_json(raw: bytes) -> dict[str, Any]:
    """Validate the same observed bytes that are bound to their evidence digest."""
    try:
        value = json.loads(raw, object_pairs_hook=_object)
        if not isinstance(value, dict):
            raise ValueError("object required")
        return bounded_json(value, maximum=MAX_ENTRY_BYTES)
    except (ValueError, UnicodeError) as exc:
        raise ReviewUnavailable("Review evidence is invalid") from exc


def read_json(store, relative: str) -> dict[str, Any] | None:
    raw = read_bytes(store, relative)
    return None if raw is None else decode_json(raw)


def receipt_identifier(instance_id: str, request_id: str) -> str:
    request_identifier(request_id)
    return "review_" + digest([instance_id, request_id])[:32]


def assert_review_readable(store) -> None:
    """Pure observation: an unfinished journal must never look like committed state."""
    control = InstanceLifecycleManager(store).control_root
    root = control / "transactions"
    if any(path.is_symlink() or path.is_junction() for path in (control, root)):
        raise ReviewUnavailable("Review recovery journal cannot traverse links")
    if not root.exists():
        return
    if not root.is_dir():
        raise ReviewUnavailable("Review recovery journal is invalid")
    for index, path in enumerate(root.iterdir()):
        if index >= 500 or path.name.startswith("review-"):
            raise ReviewUnavailable("Review transaction requires lifecycle recovery")


def validate_receipt(value: dict[str, Any], *, instance_id: str | None = None) -> None:
    fields = {
        "schema_version",
        "id",
        "instance_id",
        "request_id",
        "request_digest",
        "domain",
        "subject",
        "action",
        "principal",
        "recorded_at",
        "plan_revision",
        "authority_revision",
        "history_ref",
        "history_sha256",
        "effect",
        "reversibility",
        "result",
        "status",
        "canonical_mutation",
    }
    try:
        if (
            set(value) != fields
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["status"] != "committed"
            or type(value["canonical_mutation"]) is not bool
            or not isinstance(value["instance_id"], str)
            or not re.fullmatch(r"inst_[0-9a-f]{32}", value["instance_id"])
            or (instance_id is not None and value["instance_id"] != instance_id)
            or value["id"] != receipt_identifier(value["instance_id"], value["request_id"])
            or not isinstance(value["result"], dict)
        ):
            raise ValueError("invalid receipt")
        for key in ("request_digest", "plan_revision", "authority_revision", "history_sha256"):
            revision(value[key])
        relative_path(value["history_ref"])
        if not value["history_ref"].startswith("state/review/"):
            raise ValueError("history outside retained review state")
        for key in (
            "domain",
            "subject",
            "action",
            "principal",
            "recorded_at",
            "effect",
            "reversibility",
        ):
            if not isinstance(value[key], str) or not value[key] or len(value[key]) > 4000:
                raise ValueError("invalid receipt text")
        if value["principal"] not in {"local_browser", "local_cli"} and not (
            value["domain"] == "routing"
            and value["action"] == "apply_rule"
            and re.fullmatch(r"rule:routing_[0-9a-f]{32}", value["principal"])
        ):
            raise ValueError("invalid receipt principal")
        if datetime.fromisoformat(value["recorded_at"]).utcoffset() is None:
            raise ValueError("receipt time must be attributed to an offset")
        bounded_json(value)
    except (ValueError, TypeError, KeyError) as exc:
        raise ReviewUnavailable("Retained review receipt is invalid") from exc


class ReviewDecisions:
    """Providers prepare only. The integrator supplies registered commit/recovery hooks."""

    def __init__(
        self,
        store,
        providers,
        *,
        authority_resolver,
        transaction_factory=None,
        mutation_guard=None,
    ):
        self.store = store
        self.instance_id = store.read_config().get("instance", {}).get("id")
        if not isinstance(self.instance_id, str) or not re.fullmatch(
            r"inst_[0-9a-f]{32}", self.instance_id
        ):
            raise ReviewUnavailable("Review requires a valid Instance identity")
        self.providers = {}
        for provider in providers:
            if provider.domain in self.providers:
                raise ReviewError("Duplicate review domain registration")
            self.providers[provider.domain] = provider
        self.authority_resolver = authority_resolver
        self.transaction_factory = transaction_factory
        self.mutation_guard = mutation_guard

    def _provider(self, domain, action):
        provider = self.providers.get(domain)
        if provider is None or action not in provider.actions:
            raise ReviewDenied("Unsupported review domain or action")
        return provider

    def _assert_readable(self):
        # A visible file from an unfinished journal is not a committed receipt.
        # GET only observes the barrier; lifecycle recovery belongs to mutation/open.
        assert_review_readable(self.store)

    def preview(self, domain: str, subject: str, action: str, parameters: dict) -> dict:
        self._assert_readable()
        provider = self._provider(domain, action)
        if not isinstance(subject, str) or not subject or len(subject) > 256:
            raise ReviewError("Invalid review subject")
        if not isinstance(parameters, dict):
            raise ReviewError("Review parameters must be an object")
        parameters = bounded_json(parameters)
        proposal = bounded_json(
            provider.preview(subject, action, parameters), maximum=2 * 1024 * 1024
        )
        revision(proposal.get("input_revision"))
        required = {"evidence", "reason", "confidence", "impact", "reversibility"}
        if not required.issubset(proposal):
            raise ReviewUnavailable("Provider omitted required review evidence")
        authority = bounded_json(self.authority_resolver(domain, subject, action))
        if (
            not isinstance(authority, dict)
            or authority.get("mode") not in _MODES
            or not isinstance(authority.get("scope"), dict)
            or type(authority.get("automatic_allowed")) is not bool
        ):
            raise ReviewUnavailable("Effective review authority is invalid")
        revision(authority.get("revision"))
        plan = {
            "schema_version": 1,
            "instance_id": self.instance_id,
            "domain": domain,
            "subject": subject,
            "action": action,
            "parameters": parameters,
            "provider": proposal,
            "authority": authority,
            "authority_revision": authority["revision"],
        }
        plan["plan_revision"] = digest(plan)
        self._assert_readable()
        return plan

    def _receipt(self, request_id: str) -> dict | None:
        identifier = receipt_identifier(self.instance_id, request_id)
        result = read_json(self.store, f"state/review/receipts/{identifier}.json")
        if result is not None:
            validate_receipt(result, instance_id=self.instance_id)
            history = read_bytes(self.store, result["history_ref"])
            if history is None or sha256(history) != result["history_sha256"]:
                raise ReviewUnavailable("Review receipt history is missing or changed")
        return result

    def confirm(
        self,
        domain: str,
        subject: str,
        action: str,
        parameters: dict,
        *,
        expected_plan_revision: str,
        expected_authority_revision: str,
        request_id: str,
        principal: str = "local_browser",
    ) -> dict:
        self._confirmation_input(
            domain, subject, action, parameters,
            expected_plan_revision=expected_plan_revision,
            expected_authority_revision=expected_authority_revision,
            request_id=request_id, principal=principal,
        )
        with InstanceLifecycleManager(self.store)._hold(purpose="review-decision"):
            return self._confirm_locked(
                domain, subject, action, parameters,
                expected_plan_revision=expected_plan_revision,
                expected_authority_revision=expected_authority_revision,
                request_id=request_id, principal=principal,
            )

    def _confirmation_input(
        self,
        domain: str,
        subject: str,
        action: str,
        parameters: dict,
        *,
        expected_plan_revision: str,
        expected_authority_revision: str,
        request_id: str,
        principal: str = "local_browser",
    ) -> tuple:
        provider = self._provider(domain, action)
        revision(expected_plan_revision)
        revision(expected_authority_revision)
        request_identifier(request_id)
        automatic = isinstance(principal, str) and re.fullmatch(
            r"rule:routing_[0-9a-f]{32}", principal
        )
        if principal not in {"local_browser", "local_cli"} and not automatic:
            raise ReviewDenied("Unsupported review principal")
        if self.transaction_factory is None or self.mutation_guard is None:
            raise ReviewDenied("Review mutation requires a registered atomic recovery profile")
        payload = bounded_json(
            {
                "domain": domain,
                "subject": subject,
                "action": action,
                "parameters": parameters,
                "plan_revision": expected_plan_revision,
                "authority_revision": expected_authority_revision,
                "principal": principal,
            }
        )
        return provider, automatic, payload

    def _confirm_locked(
        self,
        domain: str,
        subject: str,
        action: str,
        parameters: dict,
        *,
        expected_plan_revision: str,
        expected_authority_revision: str,
        request_id: str,
        principal: str = "local_browser",
    ) -> dict:
        """Internal caller owns lifecycle; all confirmation checks still apply."""
        provider, automatic, payload = self._confirmation_input(
            domain, subject, action, parameters,
            expected_plan_revision=expected_plan_revision,
            expected_authority_revision=expected_authority_revision,
            request_id=request_id, principal=principal,
        )
        self.mutation_guard(self.store)
        previous = self._receipt(request_id)
        if previous is not None:
            if previous["request_digest"] != digest(payload):
                raise ReviewConflict(
                    "Request identity already belongs to different review input"
                )
            return {"receipt": previous, "result": previous["result"], "replayed": True}
        # Select secondary locks from request identities, not client plan data.
        preliminary = {
            "domain": domain,
            "subject": subject,
            "action": action,
            "parameters": bounded_json(parameters),
        }
        secondary = getattr(provider, "secondary_lock", lambda plan: nullcontext())
        with secondary(preliminary):
            plan = self.preview(domain, subject, action, parameters)
            if (
                plan["authority_revision"] != expected_authority_revision
                or plan["plan_revision"] != expected_plan_revision
            ):
                raise ReviewStale("Review inputs or authority changed; request a new preview")
            authority = plan["authority"]
            if authority["mode"] not in {"confirm-each", "controlled-automatic"}:
                raise ReviewDenied("Effective authority does not allow this decision")
            if automatic and (
                domain != "routing"
                or action != "apply_rule"
                or authority["mode"] != "controlled-automatic"
                or not authority["automatic_allowed"]
                or plan["parameters"].get("rule_id") != principal.removeprefix("rule:")
            ):
                raise ReviewDenied(
                    "Automatic review is restricted to explicitly enabled routing"
                )
            recorded_at = utc_now()
            effect = provider.prepare(
                plan, request_id=request_id, principal=principal, recorded_at=recorded_at
            )
            if (
                not isinstance(effect, PreparedEffect)
                or effect.domain != domain
                or effect.action != action
            ):
                raise ReviewUnavailable("Provider returned another domain effect")
            allowed = provider.allowed_paths(plan, request_id)
            if not isinstance(allowed, frozenset) or any(
                relative_path(x) != x for x in allowed
            ):
                raise ReviewUnavailable("Provider has no exact write allowlist")
            if any(
                write.relative not in allowed
                or write.relative.startswith("state/review/receipts/")
                for write in effect.writes
            ):
                raise ReviewDenied("Provider write falls outside its subject allowlist")
            identifier = receipt_identifier(self.instance_id, request_id)
            receipt = {
                "schema_version": 1,
                "id": identifier,
                "instance_id": self.instance_id,
                "request_id": request_id,
                "request_digest": digest(payload),
                "domain": domain,
                "subject": subject,
                "action": action,
                "principal": principal,
                "recorded_at": recorded_at,
                "plan_revision": plan["plan_revision"],
                "authority_revision": plan["authority_revision"],
                "history_ref": effect.history_ref,
                "history_sha256": sha256(
                    next(x.data for x in effect.writes if x.relative == effect.history_ref)
                ),
                "effect": effect.effect,
                "reversibility": effect.reversibility,
                "result": effect.result,
                "status": "committed",
                "canonical_mutation": any(
                    write.relative.startswith("knowledge/") for write in effect.writes
                ),
            }
            validate_receipt(receipt, instance_id=self.instance_id)
            writes = (
                *effect.writes,
                PreparedWrite(
                    f"state/review/receipts/{identifier}.json",
                    ABSENT,
                    json_bytes(receipt),
                    immutable=True,
                ),
            )
            for write in writes:
                before = read_bytes(self.store, write.relative)
                if (ABSENT if before is None else sha256(before)) != write.expected_sha256:
                    raise ReviewStale("Review write preimage changed")
            transaction = self.transaction_factory(identifier)
            for write in writes:
                transaction.add(write.relative, write.data, immutable=write.immutable)
            transaction.commit()
            return {"receipt": receipt, "result": effect.result, "replayed": False}

    def history(
        self, *, domain: str | None = None, subject: str | None = None, limit: int = 100
    ) -> dict:
        self._assert_readable()
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ReviewError("Review history limit must be between 1 and 500")
        root = checked_path(self.store, "state/review/receipts")
        if not root.exists():
            return {"items": [], "complete": True, "count_relation": "exact", "observed_count": 0}
        if not root.is_dir():
            raise ReviewUnavailable("Review receipt history is not a directory")
        records = []
        total_bytes = 0
        complete = True
        for index, path in enumerate(root.iterdir()):
            if index >= MAX_HISTORY:
                complete = False
                break
            if _RECEIPT.fullmatch(path.name) is None:
                raise ReviewUnavailable("Unexpected retained review history entry")
            value = read_json(self.store, path.relative_to(self.store.paths.root).as_posix())
            if value is None:
                raise ReviewUnavailable("Review history changed during observation")
            validate_receipt(value, instance_id=self.instance_id)
            if path.stem != value["id"]:
                raise ReviewUnavailable("Review receipt identity differs from its path")
            total_bytes += len(json_bytes(value))
            retained = read_bytes(self.store, value["history_ref"])
            if retained is None or sha256(retained) != value["history_sha256"]:
                raise ReviewUnavailable("Review receipt history is missing or changed")
            total_bytes += len(retained)
            if total_bytes > 32 * 1024 * 1024:
                complete = False
                break
            if (domain is None or value["domain"] == domain) and (
                subject is None or value["subject"] == subject
            ):
                records.append(value)
        records.sort(key=lambda item: (item["recorded_at"], item["id"]), reverse=True)
        self._assert_readable()
        return {
            "items": records[:limit],
            "complete": complete and len(records) <= limit,
            "count_relation": "exact" if complete else "at_least",
            "observed_count": len(records),
        }
