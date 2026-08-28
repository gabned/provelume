from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

HIERARCHY_RECORD_SCHEMA_VERSION = 1
CLASSIFICATION_RECORD_SCHEMA_VERSION = 1
HIERARCHY_KINDS = ("area", "project", "collection")
MAX_HIERARCHY_DEPTH = 64
MAX_NODE_NAME_CHARS = 120
MAX_SLUG_BASE_CHARS = 64

HIERARCHY_KIND_ORDER = {
    kind: position for position, kind in enumerate(HIERARCHY_KINDS)
}
ALLOWED_PARENT_KINDS = {
    "area": frozenset({"area"}),
    "project": frozenset({"area", "project"}),
    "collection": frozenset({"collection"}),
}
_NODE_ID = re.compile(r"(area|project|collection)_[0-9a-f]{32}\Z")
_CLASSIFICATION_ID = re.compile(r"classification_[0-9a-f]{32}\Z")
_PORTABLE_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?--[0-9a-f]{32}\Z")
_UNSAFE_NAME_CHARACTERS = frozenset("/\\")


class HierarchyError(ValueError):
    pass


class HierarchyNotFoundError(HierarchyError):
    pass


class HierarchyConflictError(HierarchyError):
    pass


class HierarchyIntegrityError(HierarchyError):
    pass


def normalise_node_name(value: str) -> str:
    selected = unicodedata.normalize("NFC", value.strip())
    if not selected:
        raise HierarchyError("hierarchy node name is required")
    if len(selected) > MAX_NODE_NAME_CHARS:
        raise HierarchyError(
            f"hierarchy node name exceeds {MAX_NODE_NAME_CHARS} characters"
        )
    if selected in {".", ".."}:
        raise HierarchyError("hierarchy node name cannot be dot or dot-dot")
    if any(character in _UNSAFE_NAME_CHARACTERS for character in selected):
        raise HierarchyError("hierarchy node name cannot contain path separators")
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in selected):
        raise HierarchyError("hierarchy node name cannot contain control characters")
    return selected


def portable_node_slug(name: str, node_id: str, kind: str) -> str:
    selected_name = normalise_node_name(name)
    if kind not in HIERARCHY_KINDS or _NODE_ID.fullmatch(node_id) is None:
        raise HierarchyError("invalid hierarchy node identity")
    if not node_id.startswith(f"{kind}_"):
        raise HierarchyError("hierarchy node kind does not match its identity")
    decomposed = unicodedata.normalize("NFKD", selected_name)
    ascii_name = decomposed.encode("ascii", "ignore").decode("ascii").casefold()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    if not base:
        base = kind
    base = base[:MAX_SLUG_BASE_CHARS].rstrip("-") or kind
    suffix = node_id.rsplit("_", 1)[1]
    slug = f"{base}--{suffix}"
    if _PORTABLE_SLUG.fullmatch(slug) is None:
        raise HierarchyError("cannot derive a portable hierarchy slug")
    return slug


def classification_id(document_id: str) -> str:
    if not document_id.strip():
        raise HierarchyError("document identity is required")
    digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:32]
    return f"classification_{digest}"


def classification_edge_id(document_id: str, relation: str, node_id: str) -> str:
    digest = hashlib.sha256(
        f"{document_id}\n{relation}\n{node_id}".encode()
    ).hexdigest()[:32]
    return f"edge_{digest}"


def _node_record_errors(
    record_id: str,
    value: Mapping[str, Any],
) -> list[tuple[str, str, str]]:
    path = f"knowledge/hierarchy/{record_id}.json"
    errors: list[tuple[str, str, str]] = []
    kind = value.get("kind")
    name = value.get("name")
    slug = value.get("slug")
    if (
        value.get("schema_version") != HIERARCHY_RECORD_SCHEMA_VERSION
        or _NODE_ID.fullmatch(record_id) is None
        or value.get("id") != record_id
        or kind not in HIERARCHY_KINDS
        or not record_id.startswith(f"{kind}_")
    ):
        errors.append(
            (
                "hierarchy_node_identity_invalid",
                "Hierarchy node schema, ID or kind is invalid",
                path,
            )
        )
        return errors
    try:
        selected_name = normalise_node_name(name) if isinstance(name, str) else None
    except HierarchyError:
        selected_name = None
    if selected_name is None or selected_name != name:
        errors.append(
            (
                "hierarchy_node_name_invalid",
                "Hierarchy node name is empty, unsafe or not normalized",
                path,
            )
        )
    else:
        try:
            expected_slug = portable_node_slug(selected_name, record_id, str(kind))
        except HierarchyError:
            expected_slug = None
        if slug != expected_slug:
            errors.append(
                (
                    "hierarchy_node_slug_invalid",
                    "Hierarchy node slug is not the deterministic portable slug",
                    path,
                )
            )
    parent_id = value.get("parent_id")
    if parent_id is not None and (
        not isinstance(parent_id, str) or _NODE_ID.fullmatch(parent_id) is None
    ):
        errors.append(
            (
                "hierarchy_parent_identity_invalid",
                "Hierarchy parent identity is invalid",
                path,
            )
        )
    if not all(
        isinstance(value.get(field), str) and str(value[field]).strip()
        for field in ("created_at", "updated_at")
    ):
        errors.append(
            (
                "hierarchy_node_timestamp_invalid",
                "Hierarchy node timestamps are invalid",
                path,
            )
        )
    return errors


def canonical_hierarchy_errors(
    nodes: Mapping[str, Mapping[str, Any]],
    classifications: Mapping[str, Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    structurally_valid_nodes: dict[str, Mapping[str, Any]] = {}
    for record_id, value in nodes.items():
        node_errors = _node_record_errors(record_id, value)
        errors.extend(node_errors)
        if not node_errors:
            structurally_valid_nodes[record_id] = value

    for record_id, value in structurally_valid_nodes.items():
        parent_id = value.get("parent_id")
        if parent_id is not None and parent_id not in structurally_valid_nodes:
            errors.append(
                (
                    "hierarchy_parent_missing",
                    "Hierarchy node references a missing parent",
                    f"knowledge/hierarchy/{record_id}.json",
                )
            )
        elif isinstance(parent_id, str) and (
            structurally_valid_nodes[parent_id].get("kind")
            not in ALLOWED_PARENT_KINDS[str(value["kind"])]
        ):
            errors.append(
                (
                    "hierarchy_parent_kind_invalid",
                    "Hierarchy parent kind is not allowed for this node kind",
                    f"knowledge/hierarchy/{record_id}.json",
                )
            )

    for record_id in structurally_valid_nodes:
        seen: set[str] = set()
        current_id: str | None = record_id
        depth = 0
        while current_id is not None and current_id in structurally_valid_nodes:
            if current_id in seen:
                errors.append(
                    (
                        "hierarchy_cycle",
                        "Hierarchy parent relationships contain a cycle",
                        f"knowledge/hierarchy/{record_id}.json",
                    )
                )
                break
            seen.add(current_id)
            depth += 1
            if depth > MAX_HIERARCHY_DEPTH:
                errors.append(
                    (
                        "hierarchy_depth_exceeded",
                        f"Hierarchy exceeds the {MAX_HIERARCHY_DEPTH}-level limit",
                        f"knowledge/hierarchy/{record_id}.json",
                    )
                )
                break
            parent = structurally_valid_nodes[current_id].get("parent_id")
            current_id = parent if isinstance(parent, str) else None

    for record_id, value in classifications.items():
        path = f"knowledge/classifications/{record_id}.json"
        document_id = value.get("document_id")
        primary_id = value.get("primary_node_id")
        secondary_ids = value.get("secondary_node_ids")
        if (
            value.get("schema_version") != CLASSIFICATION_RECORD_SCHEMA_VERSION
            or _CLASSIFICATION_ID.fullmatch(record_id) is None
            or value.get("id") != record_id
            or not isinstance(document_id, str)
            or record_id != classification_id(document_id)
        ):
            errors.append(
                (
                    "classification_identity_invalid",
                    "Document classification schema or identity is invalid",
                    path,
                )
            )
            continue
        if document_id not in documents:
            errors.append(
                (
                    "classification_document_missing",
                    "Classification references a missing Document",
                    path,
                )
            )
        if not isinstance(primary_id, str) or primary_id not in structurally_valid_nodes:
            errors.append(
                (
                    "classification_primary_missing",
                    "Classification references a missing primary hierarchy node",
                    path,
                )
            )
        if (
            not isinstance(secondary_ids, list)
            or not all(isinstance(item, str) for item in secondary_ids)
            or secondary_ids != sorted(set(secondary_ids))
            or primary_id in secondary_ids
        ):
            errors.append(
                (
                    "classification_secondary_invalid",
                    "Secondary classifications must be sorted, unique and exclude the primary",
                    path,
                )
            )
        elif any(item not in structurally_valid_nodes for item in secondary_ids):
            errors.append(
                (
                    "classification_secondary_missing",
                    "Classification references a missing secondary hierarchy node",
                    path,
                )
            )
        if not all(
            isinstance(value.get(field), str) and str(value[field]).strip()
            for field in ("created_at", "updated_at")
        ):
            errors.append(
                (
                    "classification_timestamp_invalid",
                    "Classification timestamps are invalid",
                    path,
                )
            )
    return errors


def classification_provenance_errors(
    classifications: Mapping[str, Mapping[str, Any]],
    provenance: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    for record_id, classification in classifications.items():
        document_id = classification.get("document_id")
        primary_id = classification.get("primary_node_id")
        secondary_ids = classification.get("secondary_node_ids")
        if (
            not isinstance(document_id, str)
            or not isinstance(primary_id, str)
            or not isinstance(secondary_ids, list)
            or not all(isinstance(item, str) for item in secondary_ids)
        ):
            continue
        for relation, node_ids in (
            ("classified_primary_as", (primary_id,)),
            ("classified_secondary_as", tuple(secondary_ids)),
        ):
            for node_id in node_ids:
                edge_id = classification_edge_id(document_id, relation, node_id)
                edge = provenance.get(edge_id)
                if edge is None:
                    errors.append(
                        (
                            "classification_provenance_missing",
                            "Classification is missing its deterministic provenance edge",
                            f"knowledge/classifications/{record_id}.json",
                        )
                    )
                elif (
                    edge.get("from_kind") != "document"
                    or edge.get("from_id") != document_id
                    or edge.get("relation") != relation
                    or edge.get("to_kind") != "hierarchy_node"
                    or edge.get("to_id") != node_id
                ):
                    errors.append(
                        (
                            "classification_provenance_invalid",
                            "Classification provenance edge does not match its association",
                            f"knowledge/provenance/{edge_id}.json",
                        )
                    )
    return errors
