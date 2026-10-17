"""Host-owned, reviewed authority for bounded, rebuildable local document work.

This domain cannot enable AI, change an Original or classify a Document. Native
OCR, ASR and AI tasks retain their existing explicit controls and consent; they
are deliberately absent from this automatic action allowlist.
"""

import re
from datetime import UTC, datetime, timedelta

from .action_center_model import digest, json_bytes, revision
from .classification_autonomy import MODES, instant, utc
from .review_decisions import assert_review_readable, receipt_identifier, validate_receipt
from .review_effects import (
    ABSENT,
    PreparedEffect,
    PreparedWrite,
    ReviewDenied,
    ReviewError,
    ReviewUnavailable,
)
from .review_routing import _document, _Inputs
from .review_routing_model import identifier, selector_prefix

ROOT = "state/review/processing"
OPERATIONS = ("extract", "representation", "index")
MAX_POLICIES = 128
MAX_INPUT_BYTES = 25 * 1024 * 1024
IMPACT = "rebuildable-local-derived-only"
_POLICY_FIELDS = {
    "schema_version", "id", "revision", "mode", "path_prefix", "operations",
    "expires_at", "max_jobs", "max_input_bytes", "source_sha256", "host_revision",
    "last_receipt", "principal", "created_at", "updated_at",
}
_HISTORY_FIELDS = {
    "schema_version", "domain", "subject", "action", "request_id", "principal",
    "recorded_at", "plan_revision", "before", "after", "execution", "result",
}


def policy_path(source_id):
    identifier(source_id, "source")
    return f"{ROOT}/policies/{source_id}.json"


def host_revision(store):
    # Include source configuration, privacy and resource limits. A change needs a
    # new explicit review; content/labels/model answers are never configuration.
    return digest(store.read_config())


def defers_inline_processing(store, source_id):
    """An opted-in Source acquires Originals independently of derived execution.

    Presence selects the reviewed path, including a damaged/unreadable policy.
    A corrupt policy can only defer work; it cannot restore legacy automation.
    """
    from .review_decisions import checked_path

    try:
        path = checked_path(store, policy_path(source_id))
        return path.exists() or path.is_symlink()
    except (ReviewError, OSError, ValueError):
        return True


def has_processing_policies(store):
    from .review_decisions import checked_path

    try:
        root = checked_path(store, ROOT + "/policies")
        return root.exists() and (not root.is_dir() or next(root.iterdir(), None) is not None)
    except (ReviewError, OSError, ValueError):
        return True


def validate_policy(value):
    try:
        if (not isinstance(value, dict) or set(value) != _POLICY_FIELDS
                or type(value["schema_version"]) is not int or value["schema_version"] != 1):
            raise ValueError("policy fields")
        identifier(value["id"], "source")
        if (type(value["revision"]) is not int or not 1 <= value["revision"] <= 10_000
                or not isinstance(value["mode"], str) or value["mode"] not in MODES
                or selector_prefix(value["path_prefix"]) != value["path_prefix"]
                or not isinstance(value["operations"], list) or not value["operations"]
                or any(not isinstance(x, str) for x in value["operations"])
                or value["operations"] != sorted(set(value["operations"]))
                or not set(value["operations"]) <= set(OPERATIONS)
                or type(value["max_jobs"]) is not int or not 1 <= value["max_jobs"] <= 1000
                or type(value["max_input_bytes"]) is not int
                or not 1 <= value["max_input_bytes"] <= MAX_INPUT_BYTES
                or value["principal"] not in {"local_browser", "local_cli"}
                or not isinstance(value["last_receipt"], str)
                or re.fullmatch(r"review_[0-9a-f]{32}", value["last_receipt"]) is None):
            raise ValueError("policy scope")
        revision(value["host_revision"])
        revision(value["source_sha256"])
        for field in ("expires_at", "created_at", "updated_at"):
            if utc(value[field]) != value[field]:
                raise ValueError("canonical time")
    except (ValueError, KeyError, TypeError) as exc:
        raise ReviewUnavailable("Processing policy is invalid or unsupported") from exc


class ProcessingReview:
    domain = "processing"
    actions = ("save_policy", "revoke_policy", "run")

    def __init__(self, store, *, clock=None):
        self.store = store
        self.instance_id = store.read_config()["instance"]["id"]
        self.clock = clock or (lambda: datetime.now(UTC))

    def history_record(self, receipt_id, inputs):
        if (not isinstance(receipt_id, str)
                or re.fullmatch(r"review_[0-9a-f]{32}", receipt_id) is None):
            raise ReviewError("Invalid processing confirmation")
        receipt = inputs.record(f"state/review/receipts/{receipt_id}.json")
        validate_receipt(receipt, instance_id=self.instance_id)
        identifier(receipt["subject"], "source")
        path = f"{ROOT}/history/{receipt['subject']}/{receipt_id}.json"
        if receipt["domain"] != self.domain or receipt["history_ref"] != path:
            raise ReviewDenied("Another review domain supplies no processing authority")
        row = inputs.record(path)
        if (set(row) != _HISTORY_FIELDS or type(row["schema_version"]) is not int
                or row["schema_version"] != 1 or row["action"] not in self.actions
                or row["principal"] not in {"local_browser", "local_cli"}
                or receipt["history_sha256"] != inputs.hashes[path]
                or any(row[k] != receipt[k] for k in (
                    "domain", "subject", "action", "request_id", "principal", "recorded_at",
                    "plan_revision", "result"))
                or row["result"] != {"policy": row["after"], "execution": row["execution"],
                                     "decision_origin": "explicit_manual_review"}):
            raise ReviewUnavailable("Processing history differs from its confirmation")
        for key in ("before", "after"):
            if row[key] is not None:
                validate_policy(row[key])
                if row[key]["id"] != receipt["subject"]:
                    raise ReviewUnavailable("Processing history changes another Source")
        if row["action"] == "run":
            from .processing_jobs import validate_plan

            validate_plan(row["execution"])
            if (row["after"] != row["before"] or row["after"] is None
                    or row["execution"]["scope"]["id"] != row["subject"]
                    or row["execution"]["parameters"]["policy_receipt"]
                    != row["after"]["last_receipt"]):
                raise ReviewUnavailable("Processing confirmation changes its reviewed policy")
        elif (row["execution"] is not None or row["after"] is None
              or row["after"]["last_receipt"] != receipt_id
              or (row["action"] == "revoke_policy" and row["after"]["mode"] != "disabled")):
            raise ReviewUnavailable("Processing policy history has another effect")
        return row, receipt

    def policy(self, source_id, inputs=None):
        assert_review_readable(self.store)
        inputs = inputs or _Inputs(self.store)
        value = inputs.record(policy_path(source_id), optional=True)
        current, seen = value, set()
        while current is not None:
            validate_policy(current)
            receipt_id = current["last_receipt"]
            if receipt_id in seen or len(seen) >= 10_000:
                raise ReviewUnavailable("Processing policy history exceeds its bound")
            seen.add(receipt_id)
            row, _ = self.history_record(receipt_id, inputs)
            previous = row["before"]
            if (row["subject"] != source_id or row["after"] != current
                    or row["action"] not in {"save_policy", "revoke_policy"}
                    or current["revision"] != (1 if previous is None else previous["revision"] + 1)
                    or (previous is None and row["action"] != "save_policy")
                    or (previous is not None and current["created_at"] != previous["created_at"])):
                raise ReviewUnavailable("Effective processing policy has unconfirmed history")
            if row["action"] == "revoke_policy":
                unchanged = set(current) - {
                    "mode", "revision", "last_receipt", "principal", "updated_at",
                }
                if any(current[key] != previous[key] for key in unchanged):
                    raise ReviewUnavailable("Processing revocation changed its scope")
            current = previous
        assert_review_readable(self.store)
        return value

    def policies(self):
        inputs = _Inputs(self.store)
        rows = inputs.inventory(f"{ROOT}/policies", MAX_POLICIES)
        return [self.policy(key, inputs) for key in rows]

    def preview(self, subject, action, parameters):
        identifier(subject, "source")
        if action not in self.actions or not isinstance(parameters, dict):
            raise ReviewDenied("Unsupported processing choice")
        inputs = _Inputs(self.store)
        before = self.policy(subject, inputs)
        source = inputs.record(f"knowledge/sources/{subject}.json")
        if source["id"] != subject:
            raise ReviewUnavailable("Processing Source identity differs")
        execution, after = None, before
        if action == "save_policy":
            required = {"mode", "path_prefix", "operations", "expires_at", "max_jobs",
                        "max_input_bytes"}
            if set(parameters) != required:
                raise ReviewError("Review the exact processing operations, scope and limits")
            if not self.clock() < instant(parameters["expires_at"]) <= (
                self.clock() + timedelta(days=90)
            ):
                raise ReviewError("Processing expiry must be within the next ninety days")
            if before is None and len(inputs.inventory(f"{ROOT}/policies", MAX_POLICIES)) >= (
                MAX_POLICIES
            ):
                raise ReviewUnavailable("Processing policy inventory is full")
            stamp = utc(self.clock().isoformat())
            after = {
                "schema_version": 1, "id": subject,
                "revision": 1 if before is None else before["revision"] + 1,
                **parameters, "path_prefix": selector_prefix(parameters["path_prefix"]),
                "expires_at": utc(parameters["expires_at"]),
                "source_sha256": inputs.hashes[f"knowledge/sources/{subject}.json"],
                "host_revision": host_revision(self.store),
            }
            validate_policy({**after, "last_receipt": "review_" + "0" * 32,
                             "principal": "local_browser", "created_at": stamp,
                             "updated_at": stamp})
        elif action == "revoke_policy":
            if parameters or before is None:
                raise ReviewError("No current processing policy to disable")
            after = {**before, "mode": "disabled", "revision": before["revision"] + 1}
        else:
            if set(parameters) != {"version_id", "operation"}:
                raise ReviewError("Review one exact Version and supported operation")
            from .processing_jobs import ProcessingJobs

            execution = ProcessingJobs(self.store, review=self).plan(
                subject, parameters["version_id"], parameters["operation"], manual=True,
            )
            inputs.hashes["execution"] = digest(execution)
        return {
            "before": before, "after": after, "execution": execution,
            "inputs": inputs.hashes,
            "input_revision": digest(inputs.hashes), "confidence": None,
            "evidence": {"source": {"id": source["id"], "name": source["name"]},
                         "host_revision": host_revision(self.store),
                         "execution": execution, "network_used": False,
                         "classification_authority": False, "ai_consent_granted": False},
            "reason": "reviewed_processing_" + action, "impact": IMPACT,
            "reversibility": "Disable the policy; remove and rebuild derived outputs.",
        }

    def allowed_paths(self, plan, request_id):
        paths = {f"{ROOT}/history/{plan['subject']}/"
                 f"{receipt_identifier(self.instance_id, request_id)}.json"}
        if plan["action"] != "run":
            paths.add(policy_path(plan["subject"]))
        return frozenset(paths)

    def prepare(self, plan, *, request_id, principal, recorded_at):
        if principal not in {"local_browser", "local_cli"}:
            raise ReviewDenied("Processing changes require an independent local reviewer")
        data, action, subject = plan["provider"], plan["action"], plan["subject"]
        receipt_id = receipt_identifier(self.instance_id, request_id)
        path = f"{ROOT}/history/{subject}/{receipt_id}.json"
        after, writes = data["after"], []
        if action != "run":
            after = {**after, "last_receipt": receipt_id, "principal": principal,
                     "created_at": (data["before"] or {}).get("created_at", utc(recorded_at)),
                     "updated_at": utc(recorded_at)}
            validate_policy(after)
            writes.append(PreparedWrite(policy_path(subject), data["inputs"][policy_path(subject)],
                                        json_bytes(after)))
        result = {"policy": after, "execution": data["execution"],
                  "decision_origin": "explicit_manual_review"}
        row = {
            "schema_version": 1, "domain": self.domain, "subject": subject,
            "action": action, "request_id": request_id, "principal": principal,
            "recorded_at": recorded_at, "plan_revision": plan["plan_revision"],
            "before": data["before"], "after": after,
            "execution": data["execution"], "result": result,
        }
        writes.append(PreparedWrite(path, ABSENT, json_bytes(row), immutable=True))
        return PreparedEffect(self.domain, action, tuple(writes), result, path,
                              data["impact"], data["reversibility"])


def scoped_inputs(store, source_id, version_id, operation, *, review):
    """Use canonical host identities only, never instructions found in content."""
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ReviewDenied("This transformation has no automatic processing authority")
    identifier(version_id, "version")
    version = store.read_canonical("versions", version_id)
    if version is None:
        raise ReviewUnavailable("Processing Version is missing")
    inputs = _Inputs(store)
    document, current, original = _document(inputs, version["document_id"])
    from .retention_model import effective_dispositions

    dispositions = effective_dispositions(store)
    disposition = dispositions[document["id"]]
    inputs.hashes["dispositions"] = digest(dispositions)
    if (disposition["status"] != "active" or disposition["library_visibility"] != "included"
            or type(original["size_bytes"]) is not int or original["size_bytes"] < 0):
        raise ReviewDenied("Processing cannot override retention, visibility or invalid size")
    policy = review.policy(source_id, inputs)
    source = inputs.record(f"knowledge/sources/{source_id}.json")
    if (policy is None or current["id"] != version_id or document["source_id"] != source_id
            or source["id"] != source_id):
        raise ReviewDenied("Processing needs a current Version in its reviewed Source")
    prefix = policy["path_prefix"]
    if (policy["mode"] in {"disabled", "proposal-only"}
            or instant(policy["expires_at"]) <= review.clock()
            or operation not in policy["operations"]
            or (prefix and document["locator"] != prefix
                and not document["locator"].startswith(prefix + "/"))
            or original["size_bytes"] > policy["max_input_bytes"]
            or policy["host_revision"] != host_revision(store)
            or policy["source_sha256"] != inputs.hashes[f"knowledge/sources/{source_id}.json"]):
        raise ReviewDenied("Processing policy is expired, denied or outside its current scope")
    return inputs, policy, document, current, original
