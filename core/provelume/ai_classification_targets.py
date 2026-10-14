"""Current canonical destinations for Iudicium; no inference or write authority."""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from .ai_context import ClassificationTarget, TaskTemplate
from .ai_contract import digest
from .hierarchy_model import canonical_hierarchy_errors, classification_id
from .review_decisions import assert_review_readable, read_bytes
from .review_effects import ReviewError, ReviewStale, ReviewUnavailable, sha256
from .review_routing import _document, _Inputs, _nodes

MAX_TARGETS = 64


def _allowlist(value):
    if type(value) is not tuple or not 1 <= len(value) <= MAX_TARGETS:
        raise ReviewError("Classification requires one to sixty-four explicit target identities")
    for row in value:
        if (
            type(row) is not tuple
            or len(row) != 2
            or type(row[0]) is not str
            or type(row[1]) is not str
            or row[0] not in {"area", "project", "collection", "document_type"}
        ):
            raise ReviewError("Classification target identities are closed kind/id pairs")
    if len(set(value)) != len(value) or len({row[1] for row in value}) != len(value):
        raise ReviewError("Classification targets must have distinct identities")
    return value


@dataclass(frozen=True, slots=True)
class CurrentClassificationTargets:
    """An immutable observation, never a permission or model-quality receipt.

    revision binds the actual record bytes, complete hierarchy, current placement
    and exact Document/Version/Original/Source metadata. Original payload integrity
    is checked by the existing context producer before gateway execution.
    """

    instance_id: str
    document_id: str
    version_id: str
    original_id: str
    source_id: str
    allowlist: tuple[tuple[str, str], ...]
    targets: tuple[ClassificationTarget, ...]
    revision: str

    def template(self, language):
        if type(language) is not str or language not in {"en", "it"}:
            raise ReviewError("Classification task language is unsupported")
        return TaskTemplate(f"classification-{language}-v1", False, self.targets)

    def revalidate(self, store):
        fresh = resolve_classification_targets(store, self.document_id, self.allowlist)
        if fresh != self:
            raise ReviewStale("Classification source, placement or target inventory changed")
        return fresh


def _observe(store, document_id, allowlist):
    assert_review_readable(store)
    inputs = _Inputs(store)
    document, version, original = _document(inputs, document_id)
    nodes = _nodes(inputs)  # Existing bounded inventory and canonical hierarchy validator.
    placement_id = classification_id(document_id)
    placement = inputs.record(f"knowledge/classifications/{placement_id}.json", optional=True)
    if canonical_hierarchy_errors(
        nodes, {placement_id: placement} if placement is not None else {},
        {document_id: document},
    ):
        raise ReviewUnavailable("Current classification is invalid")
    targets = []
    for kind, target_id in allowlist:
        # The existing CATEGORY governance namespace identifies recorded MIME.
        # This describes the current format, never a new semantic taxonomy or a
        # grant to rewrite media_type. The maintainer delegated this choice.
        if kind == "document_type":
            media_type = document.get("media_type")
            if (
                type(media_type) is not str
                or target_id != "media_" + digest(media_type)
                or re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", media_type) is None
            ):
                raise ReviewUnavailable("Document-type target is not the current canonical MIME")
            targets.append(ClassificationTarget(kind, target_id, media_type))
            continue
        node = nodes.get(target_id)
        if node is None or node["kind"] != kind:
            raise ReviewUnavailable("Classification target is missing or has another kind")
        # Labels come only from the current canonical record. They remain untrusted
        # template payload data; they cannot carry policy or mutation instructions.
        targets.append(ClassificationTarget(kind, target_id, node["name"]))
    config_path = store.paths.config.relative_to(store.paths.root).as_posix()
    raw_config = read_bytes(store, config_path, maximum=128 * 1024)
    if raw_config is None:
        raise ReviewUnavailable("Classification Instance configuration is missing")
    try:
        config = yaml.safe_load(raw_config)
        instance_id = config["instance"]["id"]
    except (yaml.YAMLError, TypeError, KeyError, UnicodeError) as exc:
        raise ReviewUnavailable("Classification Instance configuration is invalid") from exc
    if type(instance_id) is not str or re.fullmatch(r"inst_[0-9a-f]{32}", instance_id) is None:
        raise ReviewUnavailable("Classification Instance identity is invalid")
    inputs.hashes[config_path] = sha256(raw_config)
    return CurrentClassificationTargets(
        instance_id, document_id, version["id"], original["id"], document["source_id"],
        allowlist, tuple(targets), digest(inputs.hashes),
    )


def resolve_classification_targets(store, document_id, allowlist):
    """Read-only, explicit identity resolution; never resolve by model-supplied label.

    Two bounded observations bracket uncoordinated edits without creating a read
    lock. Mutation callers still need the existing lifecycle/CAS boundary and fresh
    gateway, policy, scope, consent and independently qualified quality evidence.
    """
    allowlist = _allowlist(allowlist)
    first = _observe(store, document_id, allowlist)
    if _observe(store, document_id, allowlist) != first:
        raise ReviewStale("Classification inputs changed during target resolution")
    return first
