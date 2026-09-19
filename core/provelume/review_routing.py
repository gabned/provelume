"""Pure placement/routing plans and bounded, unpublished domain effects."""

from __future__ import annotations

import json
import re

from .action_center_model import bounded_json, digest, json_bytes
from .hierarchy_model import canonical_hierarchy_errors, classification_edge_id, classification_id
from .review_decisions import (
    _object,
    assert_review_readable,
    checked_path,
    read_bytes,
    receipt_identifier,
    validate_receipt,
)
from .review_effects import (
    ABSENT,
    PreparedEffect,
    PreparedWrite,
    ReviewDenied,
    ReviewError,
    ReviewUnavailable,
    sha256,
)
from .review_routing_model import (
    MAX_NODES,
    MAX_RULES,
    identifier,
    matches,
    placement_parameters,
    selector_prefix,
    validate_history,
    validate_rule,
)


class _Inputs:
    def __init__(self, store):
        self.store = store
        self.hashes = {}
        self.total = 0

    def record(self, relative, *, optional=False):
        raw = read_bytes(self.store, relative)
        self.hashes[relative] = ABSENT if raw is None else sha256(raw)
        if raw is None:
            if not optional:
                raise ReviewUnavailable("Required placement/routing evidence is missing")
            return None
        self.total += len(raw)
        if self.total > 32 * 1024 * 1024:
            raise ReviewUnavailable("Placement/routing observation exceeds its byte bound")
        try:
            result = json.loads(raw, object_pairs_hook=_object)
            if not isinstance(result, dict):
                raise ValueError("object required")
            return bounded_json(result, maximum=8 * 1024 * 1024)
        except (ValueError, UnicodeError) as exc:
            raise ReviewUnavailable("Placement/routing evidence is invalid") from exc

    def inventory(self, relative, maximum):
        directory = checked_path(self.store, relative)
        if not directory.exists():
            return {}
        if not directory.is_dir():
            raise ReviewUnavailable("Placement/routing inventory is not a directory")
        result = {}
        for index, path in enumerate(directory.iterdir()):
            if index >= maximum or not path.name.endswith(".json"):
                raise ReviewUnavailable("Placement/routing inventory is incomplete or invalid")
            record = self.record(f"{relative}/{path.name}")
            if record.get("id") != path.stem or path.stem in result:
                raise ReviewUnavailable("Placement/routing record identity differs from its path")
            result[path.stem] = record
        return dict(sorted(result.items()))


def _nodes(inputs):
    result = inputs.inventory("knowledge/hierarchy", MAX_NODES)
    errors = canonical_hierarchy_errors(result, {}, {})
    if errors:
        raise ReviewUnavailable("Hierarchy evidence is invalid")
    return result


def _destinations(nodes, parameters):
    selected = placement_parameters(parameters)
    if any(
        node not in nodes for node in [selected["primary_node_id"], *selected["secondary_node_ids"]]
    ):
        raise ReviewError("Selected hierarchy destination no longer exists")
    return selected


def _document(inputs, document_id):
    identifier(document_id, "document")
    document = inputs.record(f"knowledge/documents/{document_id}.json")
    if document.get("id") != document_id:
        raise ReviewUnavailable("Document identity is invalid")
    version_id = identifier(document.get("current_version_id"), "version")
    source_id = identifier(document.get("source_id"), "source")
    version = inputs.record(f"knowledge/versions/{version_id}.json")
    if version.get("id") != version_id or version.get("document_id") != document_id:
        raise ReviewUnavailable("Current Version ownership is invalid")
    original_id = identifier(version.get("original_id"), "original")
    original = inputs.record(f"knowledge/originals/{original_id}.json")
    if (
        original.get("id") != original_id
        or original.get("sha256") != version.get("content_hash")
        or original_id != "sha256_" + str(version.get("content_hash"))
        or original.get("size_bytes") != version.get("size_bytes")
    ):
        raise ReviewUnavailable("Original provenance differs from the Current Version")
    source = inputs.record(f"knowledge/sources/{source_id}.json")
    if source.get("id") != source_id:
        raise ReviewUnavailable("Source identity is invalid")
    return document, version, original


def _placement_snapshot(inputs, document_id, parameters):
    document, version, original = _document(inputs, document_id)
    nodes = _nodes(inputs)
    selected = _destinations(nodes, parameters)
    record_id = classification_id(document_id)
    before = inputs.record(f"knowledge/classifications/{record_id}.json", optional=True)
    if canonical_hierarchy_errors(
        nodes, {record_id: before} if before else {}, {document_id: document}
    ):
        raise ReviewUnavailable("Current classification is invalid")
    edges = {}
    for relation, node in _associations(selected):
        edge_id = classification_edge_id(document_id, relation, node)
        edge = inputs.record(f"knowledge/provenance/{edge_id}.json", optional=True)
        if edge is not None and any(
            edge.get(key) != value
            for key, value in {
                "id": edge_id,
                "from_kind": "document",
                "from_id": document_id,
                "relation": relation,
                "to_kind": "hierarchy_node",
                "to_id": node,
            }.items()
        ):
            raise ReviewUnavailable("Existing classification provenance edge is invalid")
        edges[edge_id] = edge
    return {
        "document": document,
        "version": version,
        "original": original,
        "nodes": nodes,
        "before": before,
        "destinations": selected,
        "edges": edges,
    }


def _associations(selected):
    return [
        ("classified_primary_as", selected["primary_node_id"]),
        *(("classified_secondary_as", node) for node in selected["secondary_node_ids"]),
    ]


def _history_ref(instance_id, domain, subject, request_id):
    receipt_id = receipt_identifier(instance_id, request_id)
    return f"state/review/{domain}/history/{subject}/{receipt_id}.json"


def _history(plan, request_id, principal, recorded_at, before, after, *, rule_id=None):
    value = {
        "schema_version": 1,
        "domain": plan["domain"],
        "subject": plan["subject"],
        "action": plan["action"],
        "request_id": request_id,
        "principal": principal,
        "recorded_at": recorded_at,
        "input_revision": plan["provider"]["input_revision"],
        "plan_revision": plan["plan_revision"],
        "before": before,
        "after": after,
        "rule_id": rule_id,
    }
    validate_history(value)
    return value


def _placement_paths(snapshot):
    document_id = snapshot["document"]["id"]
    return {
        f"knowledge/classifications/{classification_id(document_id)}.json",
        *(
            f"knowledge/provenance/{key}.json"
            for key, value in snapshot["edges"].items()
            if value is None
        ),
    }


def _placement_writes(snapshot, inputs, recorded_at):
    document_id = snapshot["document"]["id"]
    before = snapshot["before"]
    selected = snapshot["destinations"]
    unchanged = before is not None and all(before[key] == selected[key] for key in selected)
    after = {
        "schema_version": 1,
        "id": classification_id(document_id),
        "document_id": document_id,
        **selected,
        "created_at": before["created_at"] if before else recorded_at,
        "updated_at": before["updated_at"] if unchanged else recorded_at,
    }
    path = f"knowledge/classifications/{after['id']}.json"
    writes = [] if unchanged else [PreparedWrite(path, inputs[path], json_bytes(after))]
    for relation, node in _associations(selected):
        edge_id = classification_edge_id(document_id, relation, node)
        if snapshot["edges"][edge_id] is not None:
            continue
        edge = {
            "id": edge_id,
            "from_kind": "document",
            "from_id": document_id,
            "relation": relation,
            "to_kind": "hierarchy_node",
            "to_id": node,
            "created_at": after["updated_at"],
        }
        writes.append(
            PreparedWrite(
                f"knowledge/provenance/{edge_id}.json", ABSENT, json_bytes(edge), immutable=True
            )
        )
    return writes, after


class PlacementProvider:
    domain = "placement"
    actions = ("classify",)

    def __init__(self, store):
        self.store = store
        self.instance_id = store.read_config()["instance"]["id"]

    def preview(self, subject, action, parameters):
        if action not in self.actions:
            raise ReviewDenied("Unsupported placement action")
        inputs = _Inputs(self.store)
        snapshot = _placement_snapshot(inputs, subject, parameters)
        return {
            "input_revision": digest(inputs.hashes),
            "inputs": inputs.hashes,
            "snapshot": snapshot,
            "evidence": {
                "document_id": subject,
                "version_id": snapshot["version"]["id"],
                "original_id": snapshot["original"]["id"],
                "content_hash": snapshot["version"]["content_hash"],
            },
            "reason": "explicit_placement",
            "confidence": None,
            "impact": (
                "Update primary and secondary classification; "
                "preserve Original, Version and prior provenance edges."
            ),
            "reversibility": (
                "A later confirmed placement can restore the prior destinations; "
                "retained history remains."
            )
            if snapshot["before"] is not None
            else (
                "A later review can change placement. Removing classification back to "
                "unclassified is not supported; retained history remains."
            ),
        }

    def allowed_paths(self, plan, request_id):
        snapshot = plan["provider"]["snapshot"]
        return frozenset(
            _placement_paths(snapshot)
            | {_history_ref(self.instance_id, self.domain, plan["subject"], request_id)}
        )

    def prepare(self, plan, *, request_id, principal, recorded_at):
        data = plan["provider"]
        writes, after = _placement_writes(data["snapshot"], data["inputs"], recorded_at)
        history_ref = _history_ref(self.instance_id, self.domain, plan["subject"], request_id)
        history = _history(
            plan, request_id, principal, recorded_at, data["snapshot"]["before"], after
        )
        writes.append(PreparedWrite(history_ref, ABSENT, json_bytes(history), immutable=True))
        return PreparedEffect(
            self.domain,
            plan["action"],
            tuple(writes),
            {"classification": after},
            history_ref,
            data["impact"],
            data["reversibility"],
        )


class RoutingProvider:
    domain = "routing"
    actions = ("save_rule", "revoke_rule", "apply_rule")

    def __init__(self, store):
        self.store = store
        self.instance_id = store.read_config()["instance"]["id"]

    def _rules(self, inputs):
        rules = inputs.inventory("state/review/routing/rules", MAX_RULES)
        count = 0
        for rule in rules.values():
            validate_rule(rule)
            relative = f"state/review/routing/history/{rule['id']}"
            directory = checked_path(self.store, relative)
            if not directory.is_dir():
                raise ReviewUnavailable("Routing rule confirmation history is missing")
            rows = []
            for path in directory.iterdir():
                count += 1
                if count > 10_000 or re.fullmatch(r"review_[0-9a-f]{32}\.json", path.name) is None:
                    raise ReviewUnavailable("Routing history is invalid or exceeds its bound")
                history_ref = f"{relative}/{path.name}"
                history = inputs.record(history_ref)
                validate_history(history)
                receipt = inputs.record(f"state/review/receipts/{path.name}")
                validate_receipt(receipt, instance_id=self.instance_id)
                if (
                    history["domain"] != "routing"
                    or history["action"] not in {"save_rule", "revoke_rule"}
                    or history["subject"] != rule["id"]
                    or history["rule_id"] != rule["id"]
                    or receipt["id"] != path.stem
                    or receipt["history_ref"] != history_ref
                    or receipt["history_sha256"] != inputs.hashes[history_ref]
                    or receipt["result"] != {"rule": history["after"]}
                    or receipt["canonical_mutation"]
                    or any(
                        receipt[key] != history[key]
                        for key in (
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
                    raise ReviewUnavailable("Routing history differs from its confirmation")
                rows.append(history)
            current = None
            for history in sorted(rows, key=lambda row: row["after"]["revision"]):
                after = history["after"]
                if (
                    history["before"] != current
                    or after["revision"] != (current["revision"] + 1 if current else 1)
                    or after["created_at"]
                    != (current["created_at"] if current else history["recorded_at"])
                    or after["updated_at"] != history["recorded_at"]
                    or after["principal"] != history["principal"]
                    or (history["action"] == "save_rule" and not after["enabled"])
                    or (
                        history["action"] == "revoke_rule"
                        and (
                            current is None
                            or after
                            != {
                                **current,
                                "revision": current["revision"] + 1,
                                "enabled": False,
                                "automatic_enabled": False,
                                "updated_at": history["recorded_at"],
                                "principal": history["principal"],
                            }
                        )
                    )
                ):
                    raise ReviewUnavailable("Routing confirmation history chain is incomplete")
                current = after
            if current != rule:
                raise ReviewUnavailable("Effective routing rule differs from its confirmed history")
        inputs.rule_history_count = count
        return rules

    def rules(self):
        assert_review_readable(self.store)
        result = list(self._rules(_Inputs(self.store)).values())
        assert_review_readable(self.store)
        return result

    def candidates(self, document_id):
        """Pure routing discovery; zero/ambiguous matches never imply automatic admission."""
        assert_review_readable(self.store)
        inputs = _Inputs(self.store)
        document, _version, _original = _document(inputs, document_id)
        before = inputs.record(
            f"knowledge/classifications/{classification_id(document_id)}.json", optional=True
        )
        if before is not None:
            if canonical_hierarchy_errors(
                _nodes(inputs),
                {classification_id(document_id): before},
                {document_id: document},
            ):
                raise ReviewUnavailable("Current classification is invalid")
            assert_review_readable(self.store)
            return {
                "rule_ids": [],
                "automatic_rule_id": None,
                "reason": "already_classified",
                "complete": True,
            }
        locator = selector_prefix(document.get("locator"))
        rules = self._rules(inputs)
        selected = [
            rule for rule in rules.values() if matches(rule, document["source_id"], locator)
        ]
        assert_review_readable(self.store)
        return {
            "rule_ids": [x["id"] for x in selected],
            "complete": True,
            "automatic_rule_id": selected[0]["id"]
            if len(selected) == 1 and selected[0]["automatic_enabled"]
            else None,
            "reason": "unique_match"
            if len(selected) == 1
            else "ambiguous_matches"
            if selected
            else "no_match",
        }

    def preview(self, subject, action, parameters):
        if action not in self.actions:
            raise ReviewDenied("Unsupported routing action")
        inputs = _Inputs(self.store)
        rules = self._rules(inputs)
        snapshot = None
        if action == "apply_rule":
            if not isinstance(parameters, dict) or set(parameters) != {"rule_id"}:
                raise ReviewError("Routing application requires one exact rule")
            rule_id = identifier(parameters["rule_id"], "rule")
            rule = rules.get(rule_id)
            if rule is None or not rule["enabled"]:
                raise ReviewDenied("Routing rule is missing or revoked")
            snapshot = _placement_snapshot(inputs, subject, rule["destinations"])
            if snapshot["before"] is not None:
                raise ReviewDenied("Routing only applies to unclassified Documents")
            document = snapshot["document"]
            locator = selector_prefix(document.get("locator"))
            matched = [
                item["id"]
                for item in rules.values()
                if matches(item, document["source_id"], locator)
            ]
            if rule_id not in matched:
                raise ReviewDenied("Document does not match the selected routing rule")
            automatic_eligible = len(matched) == 1 and rule["automatic_enabled"]
            before, after = None, rule["destinations"]
        else:
            rule_id = identifier(subject, "rule")
            if inputs.rule_history_count >= 10_000:
                raise ReviewUnavailable("Routing confirmation history has reached its bound")
            before = rules.get(rule_id)
            path = f"state/review/routing/rules/{rule_id}.json"
            inputs.hashes.setdefault(path, ABSENT)
            matched, automatic_eligible = [], False
            if action == "revoke_rule":
                if parameters != {} or before is None:
                    raise ReviewError("Revocation requires an existing rule and no parameters")
                after = {**before, "enabled": False, "automatic_enabled": False}
            else:
                fields = {
                    "source_id",
                    "path_prefix",
                    "primary_node_id",
                    "secondary_node_ids",
                    "automatic_enabled",
                }
                if (
                    not isinstance(parameters, dict)
                    or set(parameters) != fields
                    or type(parameters["automatic_enabled"]) is not bool
                ):
                    raise ReviewError("Routing rule parameters are closed")
                source_id = identifier(parameters["source_id"], "source")
                source = inputs.record(f"knowledge/sources/{source_id}.json")
                if source.get("id") != source_id:
                    raise ReviewUnavailable("Routing Source identity is invalid")
                selected = _destinations(
                    _nodes(inputs),
                    {key: parameters[key] for key in ("primary_node_id", "secondary_node_ids")},
                )
                after = {
                    "source_id": source_id,
                    "path_prefix": selector_prefix(parameters["path_prefix"]),
                    "destinations": selected,
                    "enabled": True,
                    "automatic_enabled": parameters["automatic_enabled"],
                }
                if before is None and len(rules) >= MAX_RULES:
                    raise ReviewDenied("Routing rule inventory has reached its bound")
            rule = before
        return {
            "input_revision": digest(inputs.hashes),
            "inputs": inputs.hashes,
            "observation_bytes": inputs.total,
            "snapshot": snapshot,
            "rule_id": rule_id,
            "rule": rule,
            "before": before,
            "after": after,
            "matched_rule_ids": matched,
            "automatic_eligible": automatic_eligible,
            "evidence": {
                "rule_id": rule_id,
                "rule_revision": rule["revision"] if rule else None,
                "source_id": snapshot["document"]["source_id"] if snapshot else after["source_id"],
            },
            "reason": "ambiguous_routing_proposal"
            if len(matched) > 1
            else "explicit_source_path_routing",
            "confidence": None,
            "impact": "Apply classification to this unclassified Document."
            if action == "apply_rule"
            else "Persist a revisioned Source/path rule for later Documents and acquisitions.",
            "reversibility": (
                "Classification can be corrected with a new review; "
                "rules can be edited or revoked. Prior history remains."
            ),
        }

    def allowed_paths(self, plan, request_id):
        data = plan["provider"]
        paths = (
            _placement_paths(data["snapshot"])
            if plan["action"] == "apply_rule"
            else {f"state/review/routing/rules/{identifier(plan['subject'], 'rule')}.json"}
        )
        return frozenset(
            paths | {_history_ref(self.instance_id, self.domain, plan["subject"], request_id)}
        )

    def prepare(self, plan, *, request_id, principal, recorded_at):
        data = plan["provider"]
        if plan["action"] == "apply_rule":
            if principal.startswith("rule:") and not data["automatic_eligible"]:
                raise ReviewDenied("Ambiguous or manually enabled routing requires confirmation")
            writes, after = _placement_writes(data["snapshot"], data["inputs"], recorded_at)
            before = data["snapshot"]["before"]
            result = {
                "classification": after,
                "rule_id": data["rule_id"],
                "rule_revision": data["rule"]["revision"],
            }
        else:
            if principal not in {"local_browser", "local_cli"}:
                raise ReviewDenied("Routing rules require an attributed local decision")
            before = data["before"]
            after = {
                **data["after"],
                "schema_version": 1,
                "id": data["rule_id"],
                "revision": before["revision"] + 1 if before else 1,
                "created_at": before["created_at"] if before else recorded_at,
                "updated_at": recorded_at,
                "principal": principal,
            }
            validate_rule(after)
            path = f"state/review/routing/rules/{data['rule_id']}.json"
            writes = [PreparedWrite(path, data["inputs"][path], json_bytes(after))]
            result = {"rule": after}
        history_ref = _history_ref(self.instance_id, self.domain, plan["subject"], request_id)
        history = _history(
            plan, request_id, principal, recorded_at, before, after, rule_id=data["rule_id"]
        )
        # Conservatively reserve the validated receipt's maximum encoded size,
        # plus the new state and history, without rereading or performing effects.
        if (
            data["observation_bytes"]
            + len(json_bytes(history))
            + len(json_bytes(after))
            + 256 * 1024
            > 32 * 1024 * 1024
        ):
            raise ReviewUnavailable("Routing confirmation would exceed its observation byte bound")
        writes.append(PreparedWrite(history_ref, ABSENT, json_bytes(history), immutable=True))
        return PreparedEffect(
            self.domain,
            plan["action"],
            tuple(writes),
            result,
            history_ref,
            data["impact"],
            data["reversibility"],
        )
