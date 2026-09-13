"""Pure attention projection and atomic, explicitly scoped local review receipts."""

from __future__ import annotations

import copy
import json
import re
from contextlib import contextmanager, nullcontext
from typing import Any

from .action_center_model import (
    ACTIONS,
    AUTHORITY_MODES,
    MAX_ITEMS,
    MAX_PAGE_SIZE,
    MAX_STATE_BYTES,
    QUEUES,
    REVIEW_STATES,
    ActionCenterBusy,
    ActionCenterConflict,
    ActionCenterDenied,
    ActionCenterError,
    ActionCenterStale,
    ActionCenterUnavailable,
    bounded_json,
    digest,
    integer,
    item_identifier,
    make_proposal,
    queue_observation,
    request_identifier,
    revision,
)
from .instance_lifecycle import (
    InstanceLifecycleBusy,
    InstanceLifecycleError,
    InstanceLifecycleManager,
)
from .storage import InstanceStore, utc_now

_ITEM = re.compile(r"aci_[0-9a-f]{32}\Z")
_INSTANCE = re.compile(r"inst_[0-9a-f]{32}\Z")
_DOCUMENT = re.compile(r"doc_[0-9a-f]{32}\Z")
_VERSION = re.compile(r"ver_[0-9a-f]{32}\Z")
_SOURCE = re.compile(r"src_[0-9a-f]{32}\Z")
_ORIGINAL = re.compile(r"sha256_[0-9a-f]{64}\Z")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
VERSION_PROPOSAL_REASONS = ("competing_versions", "conflicting_sources", "manual_comparison")
_SUPPORTED = {
    "intake": ("acknowledge_evidence",),
    "classification": (),
    "exact_duplicate": ("reject_proposal",),
    "probable_duplicate": ("reject_proposal",),
    "version_conflict": ("reject_proposal",),
    "extraction_error": ("acknowledge_evidence",),
    "source_change": ("acknowledge_evidence",),
    "retention": (),
}
_STATE_FIELDS = {"schema_version", "instance_id", "revision", "authority", "proposals", "receipts"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ActionCenterUnavailable("Duplicate Action Center state field")
        result[key] = value
    return result


class ActionCenter:
    """The caller supplies its existing InstanceStore; reads never open or prepare it."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.state / "action-center"
        self.path = self.root / "state.json"
        config = store.read_config()
        self.instance_id = config.get("instance", {}).get("id")
        if not isinstance(self.instance_id, str) or _INSTANCE.fullmatch(self.instance_id) is None:
            raise ActionCenterUnavailable("Action Center requires a valid Instance identity")

    def _safe_path(self) -> None:
        for selected in (self.store.paths.state, self.root, self.path):
            if selected.is_symlink() or selected.is_junction():
                raise ActionCenterUnavailable("Action Center state cannot traverse links")
            if selected.exists() and (
                selected.is_file() if selected != self.path else not selected.is_file()
            ):
                raise ActionCenterUnavailable("Action Center state path has the wrong type")

    def _default(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "instance_id": self.instance_id,
            "revision": 0,
            "authority": {"revision": 0, "rules": []},
            "proposals": {},
            "receipts": {},
        }

    def _load(self) -> dict[str, Any]:
        self._safe_path()
        if not self.path.exists():
            return self._default()
        try:
            if self.path.stat().st_size > MAX_STATE_BYTES:
                raise ActionCenterUnavailable("Action Center state exceeds its byte bound")
            value = json.loads(self.path.read_bytes(), object_pairs_hook=_unique_object)
            if (
                not isinstance(value, dict)
                or set(value) != _STATE_FIELDS
                or type(value["schema_version"]) is not int
                or value["schema_version"] != 1
                or value["instance_id"] != self.instance_id
            ):
                raise ActionCenterUnavailable("Invalid Action Center state identity")
            integer(value["revision"])
            authority = value["authority"]
            if not isinstance(authority, dict) or set(authority) != {"revision", "rules"}:
                raise ActionCenterUnavailable("Invalid Action Center authority state")
            integer(authority["revision"])
            if not isinstance(authority["rules"], list) or len(authority["rules"]) > 500:
                raise ActionCenterUnavailable("Invalid authority rules")
            seen = set()
            for rule in authority["rules"]:
                if (
                    not isinstance(rule, dict)
                    or set(rule) != {"queue", "scope", "mode"}
                    or rule["queue"] not in QUEUES
                    or rule["mode"] not in AUTHORITY_MODES[:-1]
                ):
                    raise ActionCenterUnavailable("Invalid authority rule")
                scope = rule["scope"]
                if (
                    not isinstance(scope, dict)
                    or set(scope) != {"kind", "id"}
                    or scope["kind"] not in {"instance", "source"}
                    or not isinstance(scope["id"], str)
                    or (scope["kind"] == "instance" and scope["id"] != self.instance_id)
                ):
                    raise ActionCenterUnavailable("Invalid authority scope")
                key = (rule["queue"], scope["kind"], scope["id"])
                if key in seen:
                    raise ActionCenterUnavailable("Duplicate authority scope")
                seen.add(key)
            for key in ("proposals", "receipts"):
                if not isinstance(value[key], dict) or len(value[key]) > MAX_ITEMS:
                    raise ActionCenterUnavailable("Action Center history exceeds its bound")
            for request_id, receipt in value["receipts"].items():
                request_identifier(request_id)
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("request_id") != request_id
                    or receipt.get("instance_id") != self.instance_id
                    or receipt.get("canonical_mutation") is not False
                    or receipt.get("kind") not in {"decision", "authority", "version_proposal"}
                ):
                    raise ActionCenterUnavailable("Invalid review receipt")
                common = {
                    "id",
                    "instance_id",
                    "request_id",
                    "request_digest",
                    "principal",
                    "recorded_at",
                    "state_revision",
                    "canonical_mutation",
                    "kind",
                    "input_revision",
                    "queue",
                    "authority_revision",
                    "impact",
                }
                extra = {
                    "decision": {
                        "item_id",
                        "action",
                        "review_state",
                        "decision_revision",
                        "producer_id",
                        "evidence_ref",
                    },
                    "authority": set(),
                    "version_proposal": {"proposal_id", "item_id"},
                }[receipt["kind"]]
                if (
                    set(receipt) != common | extra
                    or receipt.get("principal") not in {"local_browser", "local_cli"}
                    or not isinstance(receipt.get("recorded_at"), str)
                    or receipt.get("queue") not in QUEUES
                ):
                    raise ActionCenterUnavailable("Invalid receipt fields")
                revision(receipt.get("request_digest"))
                revision(receipt.get("input_revision"))
                integer(receipt.get("state_revision"), minimum=1)
                integer(receipt.get("authority_revision"))
                if receipt.get("id") != "acrc_" + digest([self.instance_id, request_id])[:32]:
                    raise ActionCenterUnavailable("Invalid receipt identity")
                if receipt["kind"] == "decision":
                    if (
                        receipt.get("queue") not in QUEUES
                        or receipt.get("action") not in _SUPPORTED[receipt["queue"]]
                        or not isinstance(receipt.get("item_id"), str)
                        or _ITEM.fullmatch(receipt["item_id"]) is None
                        or receipt.get("review_state")
                        != (
                            "accepted"
                            if receipt["action"] == "acknowledge_evidence"
                            else "rejected"
                        )
                        or receipt.get("impact")
                        != (
                            "records_inspection_only"
                            if receipt["action"] == "acknowledge_evidence"
                            else "rejects_proposal_only"
                        )
                        or not isinstance(receipt.get("producer_id"), str)
                        or not isinstance(receipt.get("evidence_ref"), dict)
                    ):
                        raise ActionCenterUnavailable("Invalid decision semantics")
                    integer(receipt.get("decision_revision"), minimum=1)
                    integer(receipt.get("authority_revision"))
            for proposal_id, proposal in value["proposals"].items():
                if (
                    not isinstance(proposal, dict)
                    or set(proposal)
                    != {
                        "id",
                        "instance_id",
                        "source_id",
                        "target_document_id",
                        "expected_current_version_id",
                        "alternatives",
                        "reason",
                        "input_revision",
                    }
                    or proposal.get("id") != proposal_id
                    or proposal.get("instance_id") != self.instance_id
                    or not isinstance(proposal.get("alternatives"), list)
                    or not 2 <= len(proposal["alternatives"]) <= 16
                ):
                    raise ActionCenterUnavailable("Invalid persisted version proposal")
                revision(proposal.get("input_revision"))
                if (
                    proposal.get("reason") not in VERSION_PROPOSAL_REASONS
                    or not isinstance(proposal.get("target_document_id"), str)
                    or _DOCUMENT.fullmatch(proposal["target_document_id"]) is None
                    or not isinstance(proposal.get("expected_current_version_id"), str)
                    or _VERSION.fullmatch(proposal["expected_current_version_id"]) is None
                    or not isinstance(proposal.get("source_id"), str)
                    or _SOURCE.fullmatch(proposal["source_id"]) is None
                ):
                    raise ActionCenterUnavailable("Invalid version proposal binding")
            bounded_json(value, maximum=MAX_STATE_BYTES)
            return value
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ActionCenterError,
        ) as exc:
            if isinstance(exc, ActionCenterUnavailable):
                raise
            raise ActionCenterUnavailable("Action Center state is unreadable or invalid") from exc

    def _write(self, value: dict[str, Any]) -> None:
        bounded_json(value, maximum=MAX_STATE_BYTES)
        self._safe_path()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store._atomic_json(self.path, value)

    @contextmanager
    def _command_guard(self, purpose: str):
        from .duplicates import DuplicateCaseBusyError

        try:
            with InstanceLifecycleManager(self.store)._hold(purpose=purpose):
                yield
        except (InstanceLifecycleBusy, DuplicateCaseBusyError) as exc:
            raise ActionCenterBusy("Another Instance or evidence operation is active") from exc
        except (InstanceLifecycleError, OSError) as exc:
            raise ActionCenterUnavailable(
                "Review state could not be safely read or persisted"
            ) from exc

    def authority(self) -> dict[str, Any]:
        return self._authority_view(self._load())

    def _authority_view(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "revision": state["authority"]["revision"],
            "default_mode": "confirm-each",
            "rules": copy.deepcopy(state["authority"]["rules"]),
            "capabilities": [
                {
                    "queue": queue,
                    "scope_kinds": ["instance", "source"],
                    "modes": [
                        {"mode": mode, "supported": mode != "controlled-automatic"}
                        for mode in AUTHORITY_MODES
                    ],
                    "supported_actions": list(_SUPPORTED[queue]),
                }
                for queue in QUEUES
            ],
        }

    def _mode(self, state: dict[str, Any], item: dict[str, Any]) -> str:
        evidence = item.get("evidence", {})
        source_ids = {evidence.get("source_id")}
        source_ids.update(
            value for value in evidence.get("source_ids", []) if isinstance(value, str)
        )
        selected = "confirm-each"
        for rule in state["authority"]["rules"]:
            if rule["queue"] == item["queue"] and rule["scope"]["kind"] == "instance":
                selected = rule["mode"]
        rank = {"disabled": 0, "proposal-only": 1, "confirm-each": 2}
        for rule in state["authority"]["rules"]:
            if (
                rule["queue"] == item["queue"]
                and rule["scope"]["kind"] == "source"
                and rule["scope"]["id"] in source_ids
                and rank[rule["mode"]] < rank[selected]
            ):
                selected = rule["mode"]
        return selected

    def _version(self, version_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(version_id, str) or _VERSION.fullmatch(version_id) is None:
            raise ActionCenterError("Invalid Version identity")
        version = self.store.read_canonical("versions", version_id)
        if not isinstance(version, dict) or version.get("id") != version_id:
            raise ActionCenterUnavailable("Version evidence is unavailable")
        document_id = version.get("document_id")
        if (
            not isinstance(document_id, str)
            or _DOCUMENT.fullmatch(document_id) is None
            or self.store.read_canonical("documents", document_id) is None
        ):
            raise ActionCenterUnavailable("Version Document evidence is unavailable")
        original_id = version.get("original_id")
        if not isinstance(original_id, str) or _ORIGINAL.fullmatch(original_id) is None:
            raise ActionCenterUnavailable("Invalid Original identity")
        original = self.store.read_canonical("originals", original_id)
        if (
            not isinstance(original, dict)
            or original.get("id") != original_id
            or original.get("sha256") != version.get("content_hash")
            or original.get("size_bytes") != version.get("size_bytes")
        ):
            raise ActionCenterUnavailable("Original evidence does not match the Version")
        return version, original

    def _manual_candidates(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for record in state["proposals"].values():
            target = self.store.read_canonical("documents", record["target_document_id"])
            current = bool(
                target and target.get("current_version_id") == record["expected_current_version_id"]
            )
            for alternative in record["alternatives"]:
                version, original = self._version(alternative["version_id"])
                if (
                    version["original_id"] != alternative["original_id"]
                    or original["sha256"] != alternative["sha256"]
                ):
                    raise ActionCenterUnavailable("Persisted alternative evidence has changed")
            candidate = make_proposal(
                "version_conflict",
                record["id"],
                proposal={
                    "kind": "version_resolution",
                    "reason": record["reason"],
                    "confidence": None,
                    "impact": "proposal_only_no_version_change",
                    "reversible": False,
                    "choices": ["reject_proposal"],
                    "alternatives": record["alternatives"],
                },
                evidence={
                    "document_id": record["target_document_id"],
                    "version_id": record["expected_current_version_id"],
                    "source_id": record["source_id"],
                    "proposal_id": record["id"],
                },
                domain_links=[
                    {"href": "/documents/" + record["target_document_id"], "label": "document"}
                ],
                allowed_actions=["reject_proposal"],
                revision_inputs=record["input_revision"],
            )
            candidate["producer_current"] = current
            result.append(candidate)
        return result

    def _collection(self) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        from .action_center_adapters import collect_proposals

        state = self._load()
        collected = collect_proposals(self.store)
        if not isinstance(collected, dict) or not isinstance(collected.get("items"), list):
            raise ActionCenterUnavailable("Invalid adapter collection")
        candidates = list(collected["items"])
        observations = dict(collected.get("queues", {}))
        for queue in QUEUES:
            if queue not in observations:
                observations[queue] = queue_observation(
                    queue, status="unavailable", reason="producer_unavailable"
                )
        try:
            manual = self._manual_candidates(state)
            candidates.extend(manual)
            observations["version_conflict"] = queue_observation(
                "version_conflict",
                observed_count=len(manual),
                returned=len(manual),
                matched_count=len(manual),
            )
            if digest(manual) != digest(self._manual_candidates(state)):
                observations["version_conflict"] = queue_observation(
                    "version_conflict",
                    status="partial",
                    observed_count=len(manual),
                    reason="snapshot_changed",
                    snapshot_changed=True,
                )
        except (ActionCenterError, OSError, KeyError, TypeError):
            observations["version_conflict"] = queue_observation(
                "version_conflict", status="invalid", reason="version_evidence_unavailable"
            )
        if len(candidates) > MAX_ITEMS:
            candidates = candidates[:MAX_ITEMS]
            observations = {
                queue: queue_observation(
                    queue,
                    status="partial",
                    reason="item_bound",
                    observed_count=MAX_ITEMS,
                    bound=MAX_ITEMS,
                )
                for queue in QUEUES
            }
        if digest(state) != digest(self._load()):
            observations = {
                queue: queue_observation(
                    queue, status="partial", reason="snapshot_changed", snapshot_changed=True
                )
                for queue in QUEUES
            }
        items = []
        seen = set()
        decisions = [
            receipt for receipt in state["receipts"].values() if receipt["kind"] == "decision"
        ]
        for candidate in candidates:
            queue = candidate["queue"]
            if queue not in QUEUES:
                raise ActionCenterUnavailable("Adapter returned an unknown queue")
            revision(candidate["input_revision"])
            selected_id = item_identifier(self.instance_id, queue, candidate["producer_id"])
            if selected_id in seen:
                raise ActionCenterUnavailable("Adapter returned duplicate item identities")
            seen.add(selected_id)
            history = sorted(
                (receipt for receipt in decisions if receipt["item_id"] == selected_id),
                key=lambda receipt: receipt["decision_revision"],
            )
            same = [
                receipt
                for receipt in history
                if receipt["input_revision"] == candidate["input_revision"]
            ]
            review_state = same[-1]["review_state"] if same else "awaiting_review"
            if candidate.get("producer_current") is False:
                review_state = "superseded"
            item = {
                key: copy.deepcopy(value)
                for key, value in candidate.items()
                if key != "producer_current"
            }
            item.update(
                {
                    "id": selected_id,
                    "instance_id": self.instance_id,
                    "revision": candidate["input_revision"],
                    "review_state": review_state,
                    "decision_revision": history[-1]["decision_revision"] if history else 0,
                    "authority_revision": state["authority"]["revision"],
                    "history": [
                        {
                            **receipt,
                            "superseded": receipt["input_revision"] != candidate["input_revision"],
                        }
                        for receipt in history
                    ],
                }
            )
            mode = self._mode(state, item)
            item["authority_mode"] = mode
            item["allowed_actions"] = [
                action
                for action in candidate["allowed_actions"]
                if action in _SUPPORTED[queue]
                and review_state == "awaiting_review"
                and mode == "confirm-each"
                and observations[queue].get("complete") is True
            ]
            items.append(item)
        for selected_id in sorted({receipt["item_id"] for receipt in decisions} - seen):
            history = sorted(
                (receipt for receipt in decisions if receipt["item_id"] == selected_id),
                key=lambda receipt: receipt["decision_revision"],
            )
            latest = history[-1]
            items.append(
                {
                    "id": selected_id,
                    "instance_id": self.instance_id,
                    "queue": latest["queue"],
                    "revision": latest["input_revision"],
                    "input_revision": latest["input_revision"],
                    "producer_id": latest.get("producer_id", selected_id),
                    "producer_available": False,
                    "review_state": latest["review_state"],
                    "decision_revision": latest["decision_revision"],
                    "authority_revision": state["authority"]["revision"],
                    "authority_mode": "proposal-only",
                    "allowed_actions": [],
                    "domain_links": [],
                    "proposal": {
                        "kind": "retained_review_receipt",
                        "reason": "producer_unavailable",
                        "confidence": None,
                        "impact": latest["impact"],
                        "reversible": False,
                        "choices": [],
                    },
                    "evidence": copy.deepcopy(latest.get("evidence_ref", {})),
                    "history": [
                        {
                            **receipt,
                            "superseded": receipt["input_revision"] != latest["input_revision"],
                        }
                        for receipt in history
                    ],
                }
            )
        return (
            sorted(items, key=lambda item: (QUEUES.index(item["queue"]), item["id"])),
            observations,
            state,
        )

    def snapshot(
        self,
        queue: str | None = None,
        state: str = "awaiting_review",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if queue is not None and queue not in QUEUES:
            raise ActionCenterError("Unknown queue")
        if state not in (*REVIEW_STATES, "all"):
            raise ActionCenterError("Unknown review state")
        integer(limit, minimum=1, maximum=MAX_PAGE_SIZE)
        integer(offset)
        try:
            items, observations, stored = self._collection()
        except (ActionCenterUnavailable, OSError, ValueError, KeyError, TypeError):
            items, stored = [], self._default()
            observations = {
                key: queue_observation(key, status="invalid", reason="evidence_unavailable")
                for key in QUEUES
            }
        selected = [
            item
            for item in items
            if (queue is None or item["queue"] == queue)
            and (state == "all" or item["review_state"] == state)
        ]
        queues = {}
        for key in QUEUES:
            count = sum(
                item["queue"] == key and (state == "all" or item["review_state"] == state)
                for item in items
            )
            observation = observations[key]
            queues[key] = {
                **observation,
                "count": count if observation["complete"] else None,
                "observed_count": count,
                "count_relation": "exact"
                if observation["complete"]
                else observation["count_relation"],
                "producer_observed_count": observation["observed_count"],
            }
        relevant = [queues[key] for key in QUEUES if queue is None or key == queue]
        complete = all(value["complete"] for value in relevant)
        snapshot_revision = digest(
            {
                "items": [
                    [item["id"], item["revision"], item["review_state"]] for item in selected
                ],
                "authority": stored["authority"]["revision"],
                "queue": queue,
                "state": state,
                "observations": relevant,
            }
        )
        return {
            "instance_id": self.instance_id,
            "items": selected[offset : offset + limit],
            "queues": queues,
            "total": len(selected) if complete else None,
            "observed_count": len(selected),
            "count_relation": (
                "exact"
                if complete
                else "unknown"
                if any(value["count_relation"] == "unknown" for value in relevant)
                else "at_least"
            ),
            "revision": snapshot_revision,
            "complete": complete,
            "status": (
                "complete"
                if complete
                else "unavailable"
                if any(value["status"] in {"invalid", "unavailable"} for value in relevant)
                else "partial"
            ),
            "limit": limit,
            "offset": offset,
            "authority_revision": stored["authority"]["revision"],
        }

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        if not isinstance(item_id, str) or _ITEM.fullmatch(item_id) is None:
            return None
        items, _observations, _state = self._collection()
        return next((item for item in items if item["id"] == item_id), None)

    @staticmethod
    def _principal(value: str) -> str:
        if value not in {"local_browser", "local_cli"}:
            raise ActionCenterDenied("Unsupported local review principal")
        return value

    def _replay(
        self, state: dict[str, Any], request_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        request_identifier(request_id)
        existing = state["receipts"].get(request_id)
        if existing is None:
            return None
        if existing["request_digest"] != digest(payload):
            raise ActionCenterConflict("Request identity already belongs to different input")
        return {"receipt": copy.deepcopy(existing), "replayed": True}

    def _commit(
        self,
        state: dict[str, Any],
        request_id: str,
        payload: dict[str, Any],
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        if len(state["receipts"]) >= MAX_ITEMS:
            raise ActionCenterUnavailable("Review receipt history reached its bound")
        state["revision"] = integer(state["revision"] + 1)
        receipt = {
            **receipt,
            "id": "acrc_" + digest([self.instance_id, request_id])[:32],
            "instance_id": self.instance_id,
            "request_id": request_id,
            "request_digest": digest(payload),
            "principal": payload["principal"],
            "recorded_at": utc_now(),
            "state_revision": state["revision"],
            "canonical_mutation": False,
        }
        state["receipts"][request_id] = receipt
        self._write(state)
        return {"receipt": copy.deepcopy(receipt), "replayed": False}

    def decide(
        self,
        item_id: str,
        expected_revision: str,
        action: str,
        request_id: str,
        expected_authority_revision: int,
        principal: str = "local_browser",
    ) -> dict[str, Any]:
        if not isinstance(item_id, str) or _ITEM.fullmatch(item_id) is None:
            raise ActionCenterError("Invalid review item identity")
        revision(expected_revision)
        integer(expected_authority_revision)
        request_identifier(request_id)
        if action not in ACTIONS:
            raise ActionCenterDenied("This domain action is not implemented by S03")
        payload = {
            "kind": "decision",
            "item_id": item_id,
            "expected_revision": expected_revision,
            "action": action,
            "authority_revision": expected_authority_revision,
            "principal": self._principal(principal),
        }
        with self._command_guard("action-center-decision"):
            state = self._load()
            replay = self._replay(state, request_id, payload)
            if replay is not None:
                return replay
            initial = self.get_item(item_id)
            if initial is None:
                raise ActionCenterUnavailable("Review item is unavailable")
            guard = nullcontext()
            if initial["queue"] in {"exact_duplicate", "probable_duplicate"}:
                from .duplicates import DuplicateCaseManager

                guard = DuplicateCaseManager(self.store).hold_cases()
            with guard:
                items, observations, state = self._collection()
                item = next((value for value in items if value["id"] == item_id), None)
                if item is None or not observations[item["queue"]]["complete"]:
                    raise ActionCenterUnavailable(
                        "Exact review evidence is unavailable or incomplete"
                    )
                if (
                    item["revision"] != expected_revision
                    or state["authority"]["revision"] != expected_authority_revision
                ):
                    raise ActionCenterStale("Review input or authority changed")
                if item["review_state"] != "awaiting_review":
                    raise ActionCenterConflict(
                        "This exact proposal already has a decision or is superseded"
                    )
                if action not in item["allowed_actions"]:
                    raise ActionCenterDenied("The requested action is unavailable in this scope")
                return self._commit(
                    state,
                    request_id,
                    payload,
                    {
                        "kind": "decision",
                        "item_id": item_id,
                        "queue": item["queue"],
                        "input_revision": expected_revision,
                        "action": action,
                        "review_state": "accepted"
                        if action == "acknowledge_evidence"
                        else "rejected",
                        "impact": "records_inspection_only"
                        if action == "acknowledge_evidence"
                        else "rejects_proposal_only",
                        "authority_revision": expected_authority_revision,
                        "decision_revision": integer(item["decision_revision"] + 1),
                        "producer_id": item["producer_id"],
                        "evidence_ref": {
                            key: value
                            for key, value in item["evidence"].items()
                            if key
                            in {
                                "source_id",
                                "document_id",
                                "version_id",
                                "original_id",
                                "content_hash",
                                "job_id",
                                "run_id",
                                "item_id",
                                "acquisition_id",
                            }
                            and isinstance(value, str)
                            and len(value) <= 256
                        },
                    },
                )

    def set_authority(
        self,
        queue: str,
        mode: str,
        expected_revision: int,
        request_id: str,
        scope: dict[str, str] | None = None,
        principal: str = "local_browser",
    ) -> dict[str, Any]:
        if queue not in QUEUES or mode not in AUTHORITY_MODES:
            raise ActionCenterError("Unknown authority capability or mode")
        if mode == "controlled-automatic":
            raise ActionCenterDenied("Controlled automatic action is not implemented")
        integer(expected_revision)
        scope = bounded_json(scope or {"kind": "instance", "id": self.instance_id})
        if (
            not isinstance(scope, dict)
            or set(scope) != {"kind", "id"}
            or scope["kind"] not in {"instance", "source"}
            or not isinstance(scope["id"], str)
        ):
            raise ActionCenterError("Invalid authority scope")
        if scope["kind"] == "instance" and scope["id"] != self.instance_id:
            raise ActionCenterDenied("Authority belongs to another Instance")
        if scope["kind"] == "source" and _SOURCE.fullmatch(scope["id"]) is None:
            raise ActionCenterError("Invalid Source scope identity")
        payload = {
            "kind": "authority",
            "queue": queue,
            "mode": mode,
            "scope": scope,
            "expected_revision": expected_revision,
            "principal": self._principal(principal),
        }
        with self._command_guard("action-center-authority"):
            state = self._load()
            replay = self._replay(state, request_id, payload)
            if replay is not None:
                return {**replay, "authority": self._authority_view(state)}
            if state["authority"]["revision"] != expected_revision:
                raise ActionCenterStale("Authority changed")
            if (
                scope["kind"] == "source"
                and self.store.read_canonical("sources", scope["id"]) is None
            ):
                raise ActionCenterUnavailable("Authority Source is unavailable")
            rules = [
                rule
                for rule in state["authority"]["rules"]
                if not (rule["queue"] == queue and rule["scope"] == scope)
            ]
            if len(rules) >= 500:
                raise ActionCenterUnavailable("Authority scope count reached its bound")
            rules.append({"queue": queue, "scope": scope, "mode": mode})
            state["authority"] = {
                "revision": integer(expected_revision + 1),
                "rules": sorted(
                    rules,
                    key=lambda rule: (rule["queue"], rule["scope"]["kind"], rule["scope"]["id"]),
                ),
            }
            result = self._commit(
                state,
                request_id,
                payload,
                {
                    "kind": "authority",
                    "queue": queue,
                    "input_revision": digest(payload),
                    "authority_revision": state["authority"]["revision"],
                    "impact": "changes_scoped_review_authority",
                },
            )
            return {**result, "authority": self._authority_view(state)}

    def propose_version_conflict(
        self,
        target_document_id: str,
        expected_current_version_id: str,
        alternatives: list[dict[str, str]],
        reason: str,
        request_id: str,
        expected_authority_revision: int,
        principal: str = "local_browser",
    ) -> dict[str, Any]:
        if (
            not isinstance(target_document_id, str)
            or _DOCUMENT.fullmatch(target_document_id) is None
            or not isinstance(expected_current_version_id, str)
            or _VERSION.fullmatch(expected_current_version_id) is None
        ):
            raise ActionCenterError("Invalid target Document or Version identity")
        if (
            not isinstance(reason, str)
            or _REASON.fullmatch(reason) is None
            or reason not in VERSION_PROPOSAL_REASONS
            or not isinstance(alternatives, list)
            or not 2 <= len(alternatives) <= 16
        ):
            raise ActionCenterError(
                "Version proposal requires a reason and two to sixteen exact alternatives"
            )
        integer(expected_authority_revision)
        alternatives = bounded_json(alternatives)
        for alternative in alternatives:
            if not isinstance(alternative, dict) or set(alternative) != {
                "version_id",
                "original_id",
                "sha256",
            }:
                raise ActionCenterError("Invalid exact version alternative")
            revision(alternative["sha256"])
            if (
                not isinstance(alternative["version_id"], str)
                or _VERSION.fullmatch(alternative["version_id"]) is None
                or not isinstance(alternative["original_id"], str)
                or _ORIGINAL.fullmatch(alternative["original_id"]) is None
            ):
                raise ActionCenterError("Invalid alternative Version or Original identity")
        if len({item["sha256"] for item in alternatives}) < 2 or len(
            {item["version_id"] for item in alternatives}
        ) != len(alternatives):
            raise ActionCenterError(
                "Alternatives must identify distinct Versions and at least two content hashes"
            )
        alternatives.sort(key=lambda item: item["version_id"])
        payload = {
            "kind": "version_proposal",
            "target_document_id": target_document_id,
            "expected_current_version_id": expected_current_version_id,
            "alternatives": alternatives,
            "reason": reason,
            "authority_revision": expected_authority_revision,
            "principal": self._principal(principal),
        }
        with self._command_guard("action-center-version-proposal"):
            state = self._load()
            replay = self._replay(state, request_id, payload)
            if replay is not None:
                return {
                    **replay,
                    "proposal_id": replay["receipt"]["proposal_id"],
                    "item_id": replay["receipt"]["item_id"],
                }
            if state["authority"]["revision"] != expected_authority_revision:
                raise ActionCenterStale("Authority changed")
            document = self.store.read_canonical("documents", target_document_id)
            if document is None or document["current_version_id"] != expected_current_version_id:
                raise ActionCenterStale("Target current Version changed")
            self._version(expected_current_version_id)
            for alternative in alternatives:
                version, original = self._version(alternative["version_id"])
                if (
                    version["original_id"] != alternative["original_id"]
                    or original["sha256"] != alternative["sha256"]
                ):
                    raise ActionCenterStale("Version alternative evidence changed")
            mode = self._mode(
                state,
                {"queue": "version_conflict", "evidence": {"source_id": document["source_id"]}},
            )
            if mode == "disabled":
                raise ActionCenterDenied("Version proposal capability is disabled in this scope")
            if len(state["proposals"]) >= MAX_ITEMS:
                raise ActionCenterUnavailable("Version proposal history reached its bound")
            semantic = {
                key: value
                for key, value in payload.items()
                if key not in {"authority_revision", "principal"}
            }
            proposal_id = "acp_" + digest([self.instance_id, semantic])[:32]
            item_id = item_identifier(self.instance_id, "version_conflict", proposal_id)
            state["proposals"][proposal_id] = {
                "id": proposal_id,
                "instance_id": self.instance_id,
                "source_id": document["source_id"],
                "target_document_id": target_document_id,
                "expected_current_version_id": expected_current_version_id,
                "alternatives": alternatives,
                "reason": reason,
                "input_revision": digest(semantic),
            }
            result = self._commit(
                state,
                request_id,
                payload,
                {
                    "kind": "version_proposal",
                    "proposal_id": proposal_id,
                    "item_id": item_id,
                    "queue": "version_conflict",
                    "input_revision": digest(semantic),
                    "authority_revision": expected_authority_revision,
                    "impact": "proposal_only_no_version_change",
                },
            )
            return {**result, "proposal_id": proposal_id, "item_id": item_id}
