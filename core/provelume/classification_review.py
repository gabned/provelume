"""Reviewed classification rules and decisions in the existing atomic boundary."""

import base64
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

from .action_center_model import digest, json_bytes, revision
from .classification_autonomy import (
    IMPACT,
    MAX_POLICIES,
    MODES,
    eligible,
    instant,
    policy_identifier,
    quality_scope,
    utc,
    validate_policy,
)
from .hierarchy_model import classification_id
from .review_decisions import (
    assert_review_readable,
    decode_json,
    read_bytes,
    receipt_identifier,
    validate_receipt,
)
from .review_effects import (
    ABSENT,
    PreparedClassificationRemoval,
    PreparedEffect,
    PreparedWrite,
    ReviewConflict,
    ReviewDenied,
    ReviewError,
    ReviewStale,
    ReviewUnavailable,
    sha256,
)
from .review_routing import _document, _Inputs, _nodes, _placement_paths, _placement_snapshot
from .review_routing import _placement_writes as placement_writes
from .review_routing_model import identifier, placement_parameters, selector_prefix

ROOT = "state/review/iudicium"
MAX_CLASS_BYTES = 16 * 1024
_JOB = re.compile(r"job_[0-9a-f]{32}\Z")
_RECEIPT = re.compile(r"review_[0-9a-f]{32}\Z")
_HISTORY = {
    "schema_version",
    "domain",
    "subject",
    "action",
    "request_id",
    "principal",
    "recorded_at",
    "input_revision",
    "plan_revision",
    "policy_before",
    "policy_after",
    "classification_before",
    "classification_after",
    "classification_before_raw",
    "classification_before_sha256",
    "classification_after_sha256",
    "source_identity",
    "job_id",
    "assessment_sha256",
    "undo_of",
    "result",
}


def _policy_path(policy_id):
    return f"{ROOT}/policies/{policy_identifier(policy_id)}.json"


def _history_path(subject, receipt_id):
    return f"{ROOT}/history/{subject}/{receipt_id}.json"


def _source(document, version, original):
    return {
        "document_id": document["id"],
        "version_id": version["id"],
        "original_id": original["id"],
        "source_id": document["source_id"],
        "content_hash": version["content_hash"],
    }


def _class_path(document_id):
    return f"knowledge/classifications/{classification_id(document_id)}.json"


def _encoded(raw):
    return None if raw is None else base64.b64encode(raw).decode("ascii")


def _decoded(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > (MAX_CLASS_BYTES + 2) // 3 * 4:
        raise ReviewUnavailable("Retained classification preimage exceeds its bound")
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) > MAX_CLASS_BYTES:
            raise ValueError("classification preimage too large")
        return raw
    except ValueError as exc:
        raise ReviewUnavailable("Retained classification preimage is invalid") from exc


class ClassificationReview:
    domain = "iudicium"
    actions = ("save_policy", "revoke_policy", "apply", "undo")

    def __init__(self, store, *, instance=None, clock=None):
        self.store, self.instance = store, instance
        self.instance_id = store.read_config()["instance"]["id"]
        self.clock = clock or (lambda: datetime.now(UTC))
        self._bound_producer = None
        self._locked_producer = ContextVar("iudicium_review_producer", default=None)

    def bind(self, producer):
        if producer.instance.store is not self.store:
            raise ReviewDenied("Another Instance cannot supply classification evidence")
        self._bound_producer = producer

    def producer(self):
        current = self._locked_producer.get() or self._bound_producer
        if current is None:
            if self.instance is None:
                raise ReviewUnavailable("Classification evidence reader is unavailable")
            from .ai_setup import AiSetup

            current = AiSetup(self.instance, bind_execution=False).classification
            self.bind(current)
        return current

    @contextmanager
    def secondary_lock(self, plan):
        if plan["action"] not in {"apply", "save_policy"}:
            yield
            return
        producer = self.producer()
        with producer.setup.jobs.journal.hold():
            token = self._locked_producer.set(producer)
            try:
                yield
            finally:
                self._locked_producer.reset(token)

    def assessment(self, job_id):
        if not isinstance(job_id, str) or _JOB.fullmatch(job_id) is None:
            raise ReviewError("Invalid assessment job")
        producer = self.producer()
        if self._locked_producer.get() is not None:
            return producer._read_locked(job_id)
        return producer.observe(job_id)

    def _history(self, receipt_id, inputs):
        if not isinstance(receipt_id, str) or _RECEIPT.fullmatch(receipt_id) is None:
            raise ReviewError("Invalid reviewed application identity")
        receipt = inputs.record(f"state/review/receipts/{receipt_id}.json")
        validate_receipt(receipt, instance_id=self.instance_id)
        expected_path = _history_path(receipt["subject"], receipt_id)
        if receipt["domain"] != self.domain or receipt["history_ref"] != expected_path:
            raise ReviewUnavailable("Another domain cannot supply classification authority")
        history = inputs.record(expected_path)
        if (
            set(history) != _HISTORY
            or type(history["schema_version"]) is not int
            or history["schema_version"] != 1
            or receipt["history_sha256"] != inputs.hashes[expected_path]
            or history["result"] != receipt["result"]
            or any(
                history[k] != receipt[k]
                for k in (
                    "domain",
                    "subject",
                    "action",
                    "request_id",
                    "principal",
                    "recorded_at",
                    "plan_revision",
                )
            )
        ):
            raise ReviewUnavailable("Classification review history is not receipt-bound")
        if history["action"] not in self.actions:
            raise ReviewUnavailable("Unsupported classification review history")
        revision(history["input_revision"])
        if history["principal"] not in {"local_browser", "local_cli"}:
            raise ReviewUnavailable("Classification history has no independent local reviewer")
        if history["classification_after_sha256"] != ABSENT:
            revision(history["classification_after_sha256"])
        before = _decoded(history["classification_before_raw"])
        if (
            history["classification_before_sha256"]
            != (ABSENT if before is None else sha256(before))
            or (None if before is None else decode_json(before)) != history["classification_before"]
        ):
            raise ReviewUnavailable("Classification preimage differs from retained history")
        for key in ("policy_before", "policy_after"):
            if history[key] is not None:
                validate_policy(history[key])
        if history["result"] != {
            "policy": history["policy_after"],
            "classification": history["classification_after"],
            "job_id": history["job_id"],
            "undo_of": history["undo_of"],
            "decision_origin": "explicit_manual_review",
        }:
            raise ReviewUnavailable("Classification history result differs from its effect")
        if history["action"] in {"save_policy", "revoke_policy"}:
            policy_identifier(history["subject"])
            if (
                history["policy_after"] is None
                or history["policy_after"]["id"] != history["subject"]
                or any(
                    history[key] is not None
                    for key in (
                        "classification_before",
                        "classification_after",
                        "source_identity",
                        "classification_before_raw",
                        "undo_of",
                    )
                )
                or history["classification_after_sha256"] != ABSENT
            ):
                raise ReviewUnavailable("Policy history changes an unrelated classification")
            if (
                history["action"] == "revoke_policy"
                and history["policy_after"]["mode"] != "disabled"
            ):
                raise ReviewUnavailable("Policy revocation did not disable the policy")
        else:
            identifier(history["subject"], "document")
            if not isinstance(history["job_id"], str) or _JOB.fullmatch(history["job_id"]) is None:
                raise ReviewUnavailable("Classification history has no execution identity")
            revision(history["assessment_sha256"])
            if history["action"] == "apply":
                index_path = f"{ROOT}/applications/{history['job_id']}.json"
            else:
                if (
                    not isinstance(history["undo_of"], str)
                    or _RECEIPT.fullmatch(history["undo_of"]) is None
                ):
                    raise ReviewUnavailable("Undo history has no application identity")
                index_path = f"{ROOT}/undo/{history['undo_of']}.json"
            if inputs.record(index_path) != {
                "receipt_id": receipt_id,
                "job_id": history["job_id"],
                "document_id": history["subject"],
            }:
                raise ReviewUnavailable("Classification application index differs from its receipt")
        return history, receipt

    def policy(self, policy_id, inputs=None):
        assert_review_readable(self.store)
        inputs = inputs or _Inputs(self.store)
        value = inputs.record(_policy_path(policy_id), optional=True)
        if value is None:
            return None
        current, seen = value, set()
        while current is not None:
            validate_policy(current)
            receipt_id = current["last_receipt"]
            if receipt_id in seen or len(seen) >= 10_000:
                raise ReviewUnavailable(
                    "Classification policy history is cyclic or exceeds its bound"
                )
            seen.add(receipt_id)
            history, _receipt = self._history(receipt_id, inputs)
            if (
                current["id"] != policy_id
                or history["policy_after"] != current
                or history["action"] not in {"save_policy", "revoke_policy", "apply"}
            ):
                raise ReviewUnavailable(
                    "Effective classification policy differs from confirmed history"
                )
            previous = history["policy_before"]
            if previous is None:
                if (
                    history["action"] != "save_policy"
                    or current["revision"] != 1
                    or current["used"]
                ):
                    raise ReviewUnavailable("Classification policy origin is invalid")
            elif history["action"] == "apply":
                unchanged = set(current) - {"last_receipt", "used"}
                if current["used"] != previous["used"] + 1 or any(
                    current[k] != previous[k] for k in unchanged
                ):
                    raise ReviewUnavailable("Classification policy usage history differs")
            else:
                if (
                    current["revision"] != previous["revision"] + 1
                    or current["created_at"] != previous["created_at"]
                    or current["id"] != previous["id"]
                ):
                    raise ReviewUnavailable("Classification policy revision history differs")
                if history["action"] == "save_policy" and current["used"] != 0:
                    raise ReviewUnavailable("A newly reviewed policy has unexplained usage")
                if history["action"] == "revoke_policy":
                    unchanged = set(current) - {
                        "last_receipt",
                        "revision",
                        "mode",
                        "updated_at",
                        "principal",
                    }
                    if any(current[k] != previous[k] for k in unchanged):
                        raise ReviewUnavailable("Policy revocation changed its reviewed scope")
            current = previous
        assert_review_readable(self.store)
        return value

    def policies(self):
        assert_review_readable(self.store)
        inputs = _Inputs(self.store)
        rows = inputs.inventory(f"{ROOT}/policies", MAX_POLICIES)
        result = [self.policy(key, inputs) for key in rows]
        assert_review_readable(self.store)
        return result

    def _proposal(self, inputs, job_id):
        body, reference, document, job, targets = self.assessment(job_id)
        inputs.hashes["assessment:" + job_id] = digest([body, reference, targets.revision])
        return body, reference, document, job, targets

    def preview(self, subject, action, parameters):
        if action not in self.actions or not isinstance(parameters, dict):
            raise ReviewDenied("Unsupported classification review action")
        inputs = _Inputs(self.store)
        data = {
            "policy_before": None,
            "policy_after": None,
            "placement": None,
            "classification_before_raw": None,
            "source_identity": None,
            "job_id": None,
            "assessment_sha256": None,
            "undo_of": None,
            "extra_paths": [],
            "segments": [],
            "quality": None,
            "target_labels": {},
            "source_labels": {},
        }
        if action == "save_policy":
            policy_identifier(subject)
            required = {
                "job_id",
                "path_prefix",
                "target_ids",
                "languages",
                "expires_at",
                "mode",
                "max_applications",
            }
            if set(parameters) != required:
                raise ReviewError(
                    "A policy needs an explicit reviewed scope, expiry and impact budget"
                )
            body, ref, _doc, _job, targets = self._proposal(inputs, parameters["job_id"])
            nodes = _nodes(inputs)
            source = inputs.record(f"knowledge/sources/{targets.source_id}.json")
            data["target_labels"] = {key: row["name"] for key, row in nodes.items()}
            data["source_labels"] = {targets.source_id: source["name"]}
            selected = parameters["target_ids"]
            if (
                not isinstance(selected, list)
                or not 1 <= len(selected) <= 64
                or any(not isinstance(x, str) for x in selected)
                or len(set(selected)) != len(selected)
                or any(x not in nodes for x in selected)
            ):
                raise ReviewError("Policy targets must be distinct current canonical identities")
            hashes = {
                key: inputs.hashes[f"knowledge/hierarchy/{key}.json"] for key in sorted(selected)
            }
            expires = instant(parameters["expires_at"])
            if not self.clock() < expires <= self.clock() + timedelta(days=90):
                raise ReviewError("Policy expiry must be within the next ninety days")
            if not isinstance(parameters["mode"], str) or parameters["mode"] not in MODES:
                raise ReviewError("Unsupported classification policy mode")
            before = self.policy(subject, inputs)
            rows = inputs.inventory(f"{ROOT}/policies", MAX_POLICIES)
            if before is None and len(rows) >= MAX_POLICIES:
                raise ReviewUnavailable("Classification policy inventory is full")
            after = dict(
                schema_version=1,
                id=subject,
                revision=1 if before is None else before["revision"] + 1,
                source_id=targets.source_id,
                path_prefix=selector_prefix(parameters["path_prefix"]),
                target_hashes=hashes,
                profile_fingerprint=ref["route"],
                languages=parameters["languages"],
                expires_at=utc(parameters["expires_at"]),
                mode=parameters["mode"],
                impact=IMPACT,
                max_applications=parameters["max_applications"],
                used=0,
            )
            quality = quality_scope(ref["route"], hashes, after["languages"])
            after["quality_revision"] = quality["revision"]
            stamp = utc(self.clock().isoformat())
            validate_policy(
                {
                    **after,
                    "last_receipt": "review_" + "0" * 32,
                    "principal": "local_browser",
                    "created_at": stamp,
                    "updated_at": stamp,
                }
            )
            # Commit identities/timestamps are deliberately absent from preview digests.
            data.update(
                policy_before=before,
                policy_after=after,
                quality=quality,
                job_id=parameters["job_id"],
                assessment_sha256=ref["body_sha256"],
            )
        elif action == "revoke_policy":
            if parameters:
                raise ReviewError("Policy revocation has no caller-selected effect")
            before = self.policy(subject, inputs)
            if before is None:
                raise ReviewUnavailable("Classification policy is missing")
            after = {**before, "revision": before["revision"] + 1, "mode": "disabled"}
            data.update(policy_before=before, policy_after=after)
        elif action == "apply":
            identifier(subject, "document")
            required = {"job_id", "policy_id", "primary_node_id", "secondary_node_ids", "reviewed"}
            if set(parameters) != required or parameters["reviewed"] is not True:
                raise ReviewDenied(
                    "Classification needs an independent explicit manual destination review"
                )
            body, ref, _doc, _job, targets = self._proposal(inputs, parameters["job_id"])
            if targets.document_id != subject or body["assessment"]["status"] != "selected":
                raise ReviewDenied("No current selected assessment for this Document")
            policy = self.policy(parameters["policy_id"], inputs)
            if policy is None:
                raise ReviewUnavailable("Classification policy is missing")
            destinations = placement_parameters(
                {key: parameters[key] for key in ("primary_node_id", "secondary_node_ids")}
            )
            snapshot = _placement_snapshot(inputs, subject, destinations)
            hashes = {}
            for key in policy["target_hashes"]:
                inputs.record(f"knowledge/hierarchy/{key}.json")
                hashes[key] = inputs.hashes[f"knowledge/hierarchy/{key}.json"]
            quality = eligible(
                policy,
                source_id=targets.source_id,
                locator=snapshot["document"]["locator"],
                profile=ref["route"],
                language=ref["recipe"]["template"].split("-")[1],
                target_hashes=hashes,
                now=self.clock(),
            )
            before = snapshot["before"]
            previous = (
                set()
                if before is None
                else {
                    before["primary_node_id"],
                    *before["secondary_node_ids"],
                }
            )
            chosen = {destinations["primary_node_id"], *destinations["secondary_node_ids"]}
            if not previous.symmetric_difference(chosen) <= set(hashes):
                raise ReviewDenied(
                    "Placement would change a destination outside reviewed policy scope"
                )
            index = f"{ROOT}/applications/{parameters['job_id']}.json"
            if inputs.record(index, optional=True) is not None:
                raise ReviewConflict("This assessment already has a retained application")
            raw = read_bytes(self.store, _class_path(subject), maximum=MAX_CLASS_BYTES)
            if (ABSENT if raw is None else sha256(raw)) != inputs.hashes[_class_path(subject)]:
                raise ReviewStale("Classification changed during review")
            data.update(
                policy_before=policy,
                placement=snapshot,
                classification_before_raw=_encoded(raw),
                quality=quality,
                source_identity=_source(
                    snapshot["document"], snapshot["version"], snapshot["original"]
                ),
                job_id=parameters["job_id"],
                assessment_sha256=ref["body_sha256"],
                extra_paths=[index],
                segments=body["segments"],
            )
        else:
            identifier(subject, "document")
            if set(parameters) != {"application"}:
                raise ReviewError("Undo requires the exact committed application receipt")
            history, _receipt = self._history(parameters["application"], inputs)
            if history["action"] != "apply" or history["subject"] != subject:
                raise ReviewDenied("Undo cannot substitute another application or Document")
            document, version, original = _document(inputs, subject)
            if _source(document, version, original) != history["source_identity"]:
                raise ReviewStale("The application's Document or Version changed")
            path = _class_path(subject)
            current = inputs.record(path)
            if inputs.hashes[path] != history["classification_after_sha256"]:
                raise ReviewConflict("A later classification cannot be overwritten by undo")
            index = f"{ROOT}/undo/{parameters['application']}.json"
            if inputs.record(index, optional=True) is not None:
                raise ReviewConflict("The application was already undone")
            before = history["classification_before"]
            snapshot = (
                None
                if before is None
                else _placement_snapshot(
                    inputs,
                    subject,
                    {key: before[key] for key in ("primary_node_id", "secondary_node_ids")},
                )
            )
            raw = read_bytes(self.store, path, maximum=MAX_CLASS_BYTES)
            if raw is None or sha256(raw) != inputs.hashes[path]:
                raise ReviewStale("Classification changed during undo review")
            data.update(
                placement=snapshot,
                classification_before_raw=_encoded(raw),
                source_identity=history["source_identity"],
                undo_of=parameters["application"],
                job_id=history["job_id"],
                assessment_sha256=history["assessment_sha256"],
                undo_classification=before,
                undo_raw=history["classification_before_raw"],
                current_classification=current,
                extra_paths=[index],
            )
        data["inputs"] = inputs.hashes
        data["input_revision"] = digest(inputs.hashes)
        data["evidence"] = {
            "job_id": data["job_id"],
            "source": data["source_identity"],
            "quality": data["quality"],
            "decision_origin": "explicit_manual_review",
        }
        data["reason"] = "reviewed_classification_" + action
        data["confidence"] = None
        data["impact"] = IMPACT
        data["reversibility"] = (
            "Restore the prior classification after a fresh conflict-safe review."
        )
        return data

    def allowed_paths(self, plan, request_id):
        data, subject = plan["provider"], plan["subject"]
        result = {
            _history_path(subject, receipt_identifier(self.instance_id, request_id)),
            *data["extra_paths"],
        }
        if plan["action"] in {"save_policy", "revoke_policy"}:
            result.add(_policy_path(subject))
        elif plan["action"] == "apply":
            result |= _placement_paths(data["placement"])
            result.add(_policy_path(data["policy_before"]["id"]))
        else:
            result.add(_class_path(subject))
            if data["placement"] is not None:
                result |= _placement_paths(data["placement"])
        return frozenset(result)

    def prepare(self, plan, *, request_id, principal, recorded_at):
        if principal not in {"local_browser", "local_cli"}:
            raise ReviewDenied("Unqualified classification cannot be automatically applied")
        data, action, subject = plan["provider"], plan["action"], plan["subject"]
        receipt_id = receipt_identifier(self.instance_id, request_id)
        path = _history_path(subject, receipt_id)
        stamp = utc(recorded_at)
        writes, before, after, after_hash = [], None, None, ABSENT
        policy_after = data["policy_after"]
        if action in {"save_policy", "revoke_policy"}:
            previous = data["policy_before"]
            policy_after = {
                **policy_after,
                "last_receipt": receipt_id,
                "created_at": previous["created_at"] if previous else stamp,
                "updated_at": stamp,
                "principal": principal,
            }
            validate_policy(policy_after)
        elif action == "apply":
            policy_after = {
                **data["policy_before"],
                "used": data["policy_before"]["used"] + 1,
                "last_receipt": receipt_id,
            }
            writes, after = placement_writes(data["placement"], data["inputs"], recorded_at)
            before = data["placement"]["before"]
            after_hash = next(
                (sha256(w.data) for w in writes if w.relative == _class_path(subject)),
                data["inputs"][_class_path(subject)],
            )
        else:
            before, after = data["current_classification"], data["undo_classification"]
            raw = _decoded(data["undo_raw"])
            current_hash = data["inputs"][_class_path(subject)]
            if raw is None:
                writes.append(PreparedClassificationRemoval(_class_path(subject), current_hash))
            else:
                edge_writes, _ = placement_writes(data["placement"], data["inputs"], recorded_at)
                writes.extend(w for w in edge_writes if w.relative != _class_path(subject))
                if sha256(raw) != current_hash:
                    writes.append(PreparedWrite(_class_path(subject), current_hash, raw))
                after_hash = sha256(raw)
        if policy_after is not None:
            validate_policy(policy_after)
            policy_path = _policy_path(policy_after["id"])
            writes.append(
                PreparedWrite(policy_path, data["inputs"][policy_path], json_bytes(policy_after))
            )
        result = {
            "policy": policy_after,
            "classification": after,
            "job_id": data["job_id"],
            "undo_of": data["undo_of"],
            "decision_origin": "explicit_manual_review",
        }
        for index in data["extra_paths"]:
            writes.append(
                PreparedWrite(
                    index,
                    ABSENT,
                    json_bytes(
                        {
                            "receipt_id": receipt_id,
                            "job_id": data["job_id"],
                            "document_id": subject,
                        }
                    ),
                    immutable=True,
                )
            )
        raw_before = _decoded(data["classification_before_raw"])
        history = dict(
            schema_version=1,
            domain=self.domain,
            subject=subject,
            action=action,
            request_id=request_id,
            principal=principal,
            recorded_at=recorded_at,
            input_revision=data["input_revision"],
            plan_revision=plan["plan_revision"],
            policy_before=data["policy_before"],
            policy_after=policy_after,
            classification_before=before,
            classification_after=after,
            classification_before_raw=data["classification_before_raw"],
            classification_before_sha256=ABSENT if raw_before is None else sha256(raw_before),
            classification_after_sha256=after_hash,
            source_identity=data["source_identity"],
            job_id=data["job_id"],
            assessment_sha256=data["assessment_sha256"],
            undo_of=data["undo_of"],
            result=result,
        )
        writes.append(PreparedWrite(path, ABSENT, json_bytes(history), immutable=True))
        return PreparedEffect(
            self.domain, action, tuple(writes), result, path, data["impact"], data["reversibility"]
        )
