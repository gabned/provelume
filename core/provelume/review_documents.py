"""Retained duplicate relations and explicit Version choices; no identity inference."""

from __future__ import annotations

import hashlib
import json
import re

from .action_center import ActionCenter
from .action_center_model import digest, json_bytes
from .duplicates import DuplicateCaseManager
from .review_decisions import (
    assert_review_readable,
    checked_path,
    read_bytes,
    read_json,
    receipt_identifier,
)
from .review_effects import (
    ABSENT,
    PreparedEffect,
    PreparedWrite,
    ReviewError,
    ReviewUnavailable,
    sha256,
)

MAX_VERSIONS = 10_000
MAX_ORIGINAL_BYTES = 256 * 1024 * 1024
_DOCUMENT = re.compile(r"doc_[0-9a-f]{32}\Z")
_VERSION = re.compile(r"ver_[0-9a-f]{32}\Z")


def _record(store, kind, identifier, pattern):
    if not isinstance(identifier, str) or pattern.fullmatch(identifier) is None:
        raise ReviewError("Invalid reviewed identity")
    result = read_json(store, f"knowledge/{kind}/{identifier}.json")
    if result is None or result.get("id") != identifier:
        raise ReviewUnavailable("Reviewed canonical identity is missing or invalid")
    return result


def _version(store, identifier):
    version = _record(store, "versions", identifier, _VERSION)
    if set(version) != {
        "id", "document_id", "sequence", "content_hash", "original_id",
        "media_type", "size_bytes", "acquired_at",
    }:
        raise ReviewUnavailable("Reviewed Version schema is unsupported")
    original_id = version.get("original_id")
    original = _record(store, "originals", original_id, re.compile(r"sha256_[0-9a-f]{64}\Z"))
    expected = f"originals/sha256/{original_id[7:9]}/{original_id[7:]}"
    if (
        original.get("storage_ref") != expected
        or original.get("sha256") != original_id[7:]
        or version.get("content_hash") != original["sha256"]
        or type(original.get("size_bytes")) is not int
        or not 0 <= original["size_bytes"] <= MAX_ORIGINAL_BYTES
        or version.get("size_bytes") != original["size_bytes"]
    ):
        raise ReviewUnavailable("Reviewed Original binding is invalid or exceeds its bound")
    path = checked_path(store, expected)
    try:
        if not path.is_file() or path.stat().st_size != original["size_bytes"]:
            raise ReviewUnavailable("Reviewed Original bytes are unavailable")
        checksum = hashlib.sha256()
        count = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_ORIGINAL_BYTES:
                    raise ReviewUnavailable("Reviewed Original exceeds its bound")
                checksum.update(chunk)
        if count != original["size_bytes"] or checksum.hexdigest() != original["sha256"]:
            raise ReviewUnavailable("Reviewed Original bytes differ from their provenance")
    except OSError as exc:
        raise ReviewUnavailable("Reviewed Original cannot be read") from exc
    return version, original


def _target_versions(store, document_id):
    directory = checked_path(store, "knowledge/versions")
    result = {}
    total = 0
    for index, path in enumerate(directory.iterdir()):
        if index >= MAX_VERSIONS or _VERSION.fullmatch(path.stem) is None or path.suffix != ".json":
            raise ReviewUnavailable("Version inventory is incomplete or unsupported")
        raw = read_bytes(store, f"knowledge/versions/{path.name}")
        if raw is None:
            raise ReviewUnavailable("Version inventory changed")
        total += len(raw)
        if total > 32 * 1024 * 1024:
            raise ReviewUnavailable("Version inventory exceeds its byte bound")
        row = read_json(store, f"knowledge/versions/{path.name}")
        if row is None or row.get("id") != path.stem:
            raise ReviewUnavailable("Version inventory identity is invalid")
        if row.get("document_id") == document_id:
            if type(row.get("sequence")) is not int or row["sequence"] < 1:
                raise ReviewUnavailable("Target Version sequence is invalid")
            result[row["id"]] = row
    if not result or len({row["sequence"] for row in result.values()}) != len(result):
        raise ReviewUnavailable("Target Version sequence is missing or ambiguous")
    return result


class DuplicateDecisionProvider:
    domain = "duplicates"
    actions = ("link_exact", "relate", "keep_separate", "new_version")

    def __init__(self, store):
        self.store = store

    def secondary_lock(self, plan):
        return DuplicateCaseManager(self.store).hold_cases()

    def choices(self, subject):
        """Bounded pure UI choices from the same current producer as preview."""
        assert_review_readable(self.store)
        selected, documents, versions = self._subject(subject)
        actions = list(self.actions)
        if selected["queue"] != "exact_duplicate" and "link_exact" in actions:
            actions.remove("link_exact")
        total = 0

        def choice(kind, value, pattern):
            nonlocal total
            row = _record(self.store, kind, value, pattern)
            total += len(json_bytes(row))
            if total > 32 * 1024 * 1024:
                raise ReviewUnavailable("Review choices exceed their byte bound")
            return row

        result = {
            "actions": actions,
            "documents": [
                choice("documents", value, _DOCUMENT) for value in documents
            ],
            "versions": [choice("versions", value, _VERSION) for value in versions],
        }
        assert_review_readable(self.store)
        return result

    def _subject(self, subject):
        items, observations, _ = ActionCenter(self.store)._collection()
        selected = next(
            (
                item
                for item in items
                if item["producer_id"] == subject
                and item["queue"] in {"exact_duplicate", "probable_duplicate"}
            ),
            None,
        )
        if selected is None or not observations[selected["queue"]]["complete"]:
            raise ReviewUnavailable("Complete current duplicate evidence is required")
        if selected["review_state"] in {"rejected", "superseded"}:
            raise ReviewUnavailable("Duplicate proposal is no longer current")
        case = read_json(self.store, f"state/duplicates/cases/{subject}.json")
        if not case or not DuplicateCaseManager._valid_case(case) or not case["current"]:
            raise ReviewUnavailable("Current duplicate case is required")
        documents = [row["document_id"] for row in case["documents"]]
        return selected, documents, [row["version_id"] for row in case["documents"]]

    def preview(self, subject, action, parameters):
        if action not in self.actions:
            raise ReviewError("Unsupported duplicate decision")
        selected, documents, alternatives = self._subject(subject)
        if action == "link_exact" and selected["queue"] != "exact_duplicate":
            raise ReviewError("Similarity cannot authorize an exact duplicate link")
        history_root = checked_path(self.store, f"state/review/{self.domain}")
        prior = {}
        if history_root.exists():
            if not history_root.is_dir():
                raise ReviewUnavailable("Document decision history is not a directory")
            total = 0
            for index, path in enumerate(history_root.iterdir()):
                if index >= 10_000 or re.fullmatch(r"review_[0-9a-f]{32}\.json", path.name) is None:
                    raise ReviewUnavailable("Document decision history is invalid or incomplete")
                relative = f"state/review/{self.domain}/{path.name}"
                raw = read_bytes(self.store, relative)
                row = read_json(self.store, relative)
                if raw is None or row is None or row.get("schema_version") != 1:
                    raise ReviewUnavailable("Document decision history is invalid")
                total += len(raw)
                if total > 32 * 1024 * 1024:
                    raise ReviewUnavailable("Document decision history exceeds its byte bound")
                if row.get("subject") == subject:
                    prior[path.name] = sha256(raw)
        evidence = {
            "proposal": selected,
            "documents": documents,
            "versions": alternatives,
            "prior_decisions": prior,
        }
        version_change = action in {"new_version", "select_current"}
        if version_change:
            required = (
                {"version_id", "target_document_id"}
                if self.domain == "duplicates"
                else {"version_id"}
            )
            if set(parameters) != required:
                raise ReviewError("Select an exact target Document and eligible Version")
            target_id = parameters.get("target_document_id", documents[0])
            version_id = parameters["version_id"]
            if target_id not in documents or version_id not in alternatives:
                raise ReviewError("Selection is outside the reviewed participants")
            target = _record(self.store, "documents", target_id, _DOCUMENT)
            target_raw = read_bytes(self.store, f"knowledge/documents/{target_id}.json")
            if target_raw is None or json.loads(target_raw) != target:
                raise ReviewUnavailable("Target Document changed during observation")
            version, original = _version(self.store, version_id)
            target_versions = _target_versions(self.store, target_id)
            if action == "select_current" and version.get("document_id") != target_id:
                raise ReviewError("Only a Version already owned by the target may become current")
            if target["current_version_id"] == version_id:
                raise ReviewError("The selected Version is already current")
            evidence.update(
                target=target,
                target_preimage=sha256(target_raw),
                selected_version=version,
                original=original,
                target_versions=target_versions,
            )
        elif parameters:
            raise ReviewError("This duplicate relation has no free-form parameters")
        return {
            "input_revision": digest(evidence),
            "evidence": evidence,
            "reason": "Explicit reviewed Version choice"
            if version_change
            else "Explicit relation between retained Documents",
            "confidence": selected.get("proposal", {}).get("confidence"),
            "impact": "Changes current Version; prior identities and Original bytes are retained"
            if version_change
            else "Adds an attributed relation; does not merge or delete Documents",
            "reversibility": "A confirmed choice can restore a prior Version; history remains"
            if version_change
            else "A subsequent relation supersedes the earlier choice without deleting its history",
        }

    def _paths(self, plan, request_id):
        identifier = receipt_identifier(plan["instance_id"], request_id)
        paths = {"history": f"state/review/{self.domain}/{identifier}.json"}
        if plan["action"] in {"new_version", "select_current"}:
            target = plan["provider"]["evidence"]["target"]
            paths["document"] = f"knowledge/documents/{target['id']}.json"
            if plan["action"] == "new_version":
                version_id = (
                    "ver_" + digest([plan["instance_id"], request_id, "review-version"])[:32]
                )
                paths["version"] = f"knowledge/versions/{version_id}.json"
                paths["origin"] = f"knowledge/review-origins/{version_id}.json"
        return paths

    def allowed_paths(self, plan, request_id):
        return frozenset(self._paths(plan, request_id).values())

    def prepare(self, plan, *, request_id, principal, recorded_at):
        paths = self._paths(plan, request_id)
        evidence = plan["provider"]["evidence"]
        result = {
            "decision": plan["action"],
            "subject": plan["subject"],
            "documents": evidence["documents"],
        }
        writes = []
        history = {
            "schema_version": 1,
            "domain": self.domain,
            "subject": plan["subject"],
            "action": plan["action"],
            "principal": principal,
            "recorded_at": recorded_at,
            "plan_revision": plan["plan_revision"],
            "input_revision": plan["provider"]["input_revision"],
            "documents": evidence["documents"],
            "versions": evidence["versions"],
            "previous_current_version_id": None,
            "selected_version_id": None,
        }
        if "document" in paths:
            target, selected = evidence["target"], evidence["selected_version"]
            version_id = selected["id"]
            if "version" in paths:
                version_id = paths["version"].rsplit("/", 1)[1][:-5]
                version = {
                    **selected,
                    "id": version_id,
                    "document_id": target["id"],
                    "sequence": max(row["sequence"] for row in evidence["target_versions"].values())
                    + 1,
                    # No new acquisition occurred; original acquisition time remains factual.
                    "acquired_at": selected["acquired_at"],
                }
                writes.append(
                    PreparedWrite(paths["version"], ABSENT, json_bytes(version), immutable=True)
                )
            history.update(
                previous_current_version_id=target["current_version_id"],
                selected_version_id=version_id,
            )
            writes.append(
                PreparedWrite(
                    paths["document"],
                    evidence["target_preimage"],
                    json_bytes({**target, "current_version_id": version_id}),
                )
            )
            result.update(target_document_id=target["id"], version_id=version_id)
            if "origin" in paths:
                origin = {
                    "schema_version": 1,
                    "id": version_id,
                    "source_version_id": selected["id"],
                    "source_document_id": selected["document_id"],
                    "target_document_id": target["id"],
                    "previous_current_version_id": target["current_version_id"],
                    "original_id": selected["original_id"],
                    "content_hash": selected["content_hash"],
                    "history_ref": paths["history"],
                    "history_sha256": sha256(json_bytes(history)),
                    "principal": principal,
                    "recorded_at": recorded_at,
                }
                writes.append(
                    PreparedWrite(paths["origin"], ABSENT, json_bytes(origin), immutable=True)
                )
        writes.append(PreparedWrite(paths["history"], ABSENT, json_bytes(history), immutable=True))
        return PreparedEffect(
            self.domain,
            plan["action"],
            tuple(writes),
            result,
            paths["history"],
            plan["provider"]["impact"],
            plan["provider"]["reversibility"],
        )


class VersionDecisionProvider(DuplicateDecisionProvider):
    domain = "versions"
    actions = ("select_current", "new_version")

    def _subject(self, subject):
        center = ActionCenter(self.store)
        items, observations, state = center._collection()
        selected = next(
            (
                item
                for item in items
                if item["queue"] == "version_conflict" and item["producer_id"] == subject
            ),
            None,
        )
        proposal = state["proposals"].get(subject)
        if (
            selected is None
            or proposal is None
            or not observations["version_conflict"]["complete"]
            or selected["review_state"] in {"rejected", "superseded"}
        ):
            raise ReviewUnavailable("Complete current Version proposal evidence is required")
        return (
            selected,
            [proposal["target_document_id"]],
            [row["version_id"] for row in proposal["alternatives"]],
        )
