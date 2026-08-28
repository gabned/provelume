from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import uuid4

from .domain import (
    DocumentClassification,
    HierarchyNode,
    ProvenanceEdge,
)
from .hierarchy_model import (
    ALLOWED_PARENT_KINDS,
    CLASSIFICATION_RECORD_SCHEMA_VERSION,
    HIERARCHY_KIND_ORDER,
    HIERARCHY_KINDS,
    HIERARCHY_RECORD_SCHEMA_VERSION,
    MAX_HIERARCHY_DEPTH,
    HierarchyConflictError,
    HierarchyError,
    HierarchyIntegrityError,
    HierarchyNotFoundError,
    canonical_hierarchy_errors,
    classification_edge_id,
    classification_id,
    normalise_node_name,
    portable_node_slug,
)
from .storage import InstanceStore, utc_now


class HierarchyManager:
    def __init__(self, store: InstanceStore):
        self.store = store

    def _state(
        self,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        nodes = {
            str(item.get("id", "")): item
            for item in self.store.list_canonical("hierarchy")
        }
        classifications = {
            str(item.get("id", "")): item
            for item in self.store.list_canonical("classifications")
        }
        documents = {
            str(item.get("id", "")): item
            for item in self.store.list_canonical("documents")
        }
        errors = canonical_hierarchy_errors(nodes, classifications, documents)
        if errors:
            raise HierarchyIntegrityError(errors[0][1])
        return nodes, classifications

    @staticmethod
    def _validate_parent_kind(
        kind: str,
        parent_id: str | None,
        nodes: Mapping[str, Mapping[str, Any]],
    ) -> None:
        if parent_id is None:
            return
        parent_kind = str(nodes[parent_id]["kind"])
        if parent_kind not in ALLOWED_PARENT_KINDS[kind]:
            allowed = ", ".join(sorted(ALLOWED_PARENT_KINDS[kind]))
            raise HierarchyConflictError(
                f"{kind} parent must have one of these kinds: {allowed}"
            )

    @staticmethod
    def _node_sort_key(node: Mapping[str, Any]) -> tuple[str, int, str]:
        return (
            str(node["name"]).casefold(),
            HIERARCHY_KIND_ORDER[str(node["kind"])],
            str(node["id"]),
        )

    @staticmethod
    def _lineage(
        node_id: str,
        nodes: Mapping[str, Mapping[str, Any]],
    ) -> list[Mapping[str, Any]]:
        result: list[Mapping[str, Any]] = []
        current_id: str | None = node_id
        while current_id is not None:
            node = nodes[current_id]
            result.append(node)
            parent_id = node.get("parent_id")
            current_id = parent_id if isinstance(parent_id, str) else None
        return list(reversed(result))

    @staticmethod
    def _children(
        nodes: Mapping[str, Mapping[str, Any]],
    ) -> dict[str | None, list[Mapping[str, Any]]]:
        result: dict[str | None, list[Mapping[str, Any]]] = {}
        for node in nodes.values():
            parent_id = node.get("parent_id")
            selected_parent = parent_id if isinstance(parent_id, str) else None
            result.setdefault(selected_parent, []).append(node)
        for values in result.values():
            values.sort(key=HierarchyManager._node_sort_key)
        return result

    @staticmethod
    def _classification_counts(
        classifications: Iterable[Mapping[str, Any]],
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        primary: dict[str, set[str]] = {}
        secondary: dict[str, set[str]] = {}
        for classification in classifications:
            document_id = str(classification["document_id"])
            primary.setdefault(str(classification["primary_node_id"]), set()).add(
                document_id
            )
            for node_id in classification["secondary_node_ids"]:
                secondary.setdefault(str(node_id), set()).add(document_id)
        return primary, secondary

    def _node_view(
        self,
        node: Mapping[str, Any],
        nodes: Mapping[str, Mapping[str, Any]],
        children: Mapping[str | None, list[Mapping[str, Any]]],
        primary: Mapping[str, set[str]],
        secondary: Mapping[str, set[str]],
    ) -> dict[str, Any]:
        lineage = self._lineage(str(node["id"]), nodes)
        node_id = str(node["id"])
        descendant_ids = self._descendant_ids(node_id, children)
        direct_primary = set(primary.get(node_id, set()))
        direct_secondary = set(secondary.get(node_id, set()))
        subtree_documents: set[str] = set()
        for descendant_id in descendant_ids:
            subtree_documents.update(primary.get(descendant_id, set()))
            subtree_documents.update(secondary.get(descendant_id, set()))
        return {
            **dict(node),
            "depth": len(lineage) - 1,
            "breadcrumbs": [
                {
                    "id": str(item["id"]),
                    "kind": str(item["kind"]),
                    "name": str(item["name"]),
                    "slug": str(item["slug"]),
                }
                for item in lineage
            ],
            "portable_path": "/".join(str(item["slug"]) for item in lineage),
            "document_counts": {
                "primary": len(direct_primary),
                "secondary": len(direct_secondary),
                "associated": len(direct_primary | direct_secondary),
                "subtree": len(subtree_documents),
            },
        }

    @staticmethod
    def _descendant_ids(
        node_id: str,
        children: Mapping[str | None, list[Mapping[str, Any]]],
    ) -> set[str]:
        selected = {node_id}
        pending = [node_id]
        while pending:
            parent_id = pending.pop()
            for child in children.get(parent_id, []):
                child_id = str(child["id"])
                selected.add(child_id)
                pending.append(child_id)
        return selected

    def list_nodes(self) -> list[dict[str, Any]]:
        nodes, classifications = self._state()
        children = self._children(nodes)
        primary, secondary = self._classification_counts(classifications.values())
        result: list[dict[str, Any]] = []

        def append_children(parent_id: str | None) -> None:
            for child in children.get(parent_id, []):
                result.append(
                    self._node_view(
                        child,
                        nodes,
                        children,
                        primary,
                        secondary,
                    )
                )
                append_children(str(child["id"]))

        append_children(None)
        return result

    def tree(self) -> dict[str, Any]:
        flat = self.list_nodes()
        by_parent: dict[str | None, list[dict[str, Any]]] = {}
        for node in flat:
            selected = {**node, "children": []}
            by_parent.setdefault(node.get("parent_id"), []).append(selected)
        for values in by_parent.values():
            values.sort(key=self._node_sort_key)

        def build(parent_id: str | None) -> list[dict[str, Any]]:
            result = []
            for node in by_parent.get(parent_id, []):
                node["children"] = build(str(node["id"]))
                result.append(node)
            return result

        return {
            "schema_version": HIERARCHY_RECORD_SCHEMA_VERSION,
            "nodes": flat,
            "tree": build(None),
        }

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        nodes, classifications = self._state()
        node = nodes.get(node_id)
        if node is None:
            return None
        children = self._children(nodes)
        primary, secondary = self._classification_counts(classifications.values())
        return self._node_view(node, nodes, children, primary, secondary)

    def create_node(
        self,
        kind: str,
        name: str,
        *,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in HIERARCHY_KINDS:
            raise HierarchyError(f"hierarchy kind must be one of: {', '.join(HIERARCHY_KINDS)}")
        selected_name = normalise_node_name(name)
        nodes, _classifications = self._state()
        if parent_id is not None and parent_id not in nodes:
            raise HierarchyNotFoundError(f"hierarchy node not found: {parent_id}")
        self._validate_parent_kind(kind, parent_id, nodes)
        if (
            parent_id is not None
            and len(self._lineage(parent_id, nodes)) >= MAX_HIERARCHY_DEPTH
        ):
            raise HierarchyConflictError(
                f"hierarchy creation exceeds the {MAX_HIERARCHY_DEPTH}-level limit"
            )
        node_id = f"{kind}_{uuid4().hex}"
        now = utc_now()
        node = HierarchyNode(
            schema_version=HIERARCHY_RECORD_SCHEMA_VERSION,
            id=node_id,
            kind=kind,
            name=selected_name,
            slug=portable_node_slug(selected_name, node_id, kind),
            parent_id=parent_id,
            created_at=now,
            updated_at=now,
        )
        self.store.write_hierarchy_node(node)
        return self.get_node(node_id) or {}

    def rename_node(self, node_id: str, name: str) -> dict[str, Any]:
        selected_name = normalise_node_name(name)
        nodes, _classifications = self._state()
        current = nodes.get(node_id)
        if current is None:
            raise HierarchyNotFoundError(f"hierarchy node not found: {node_id}")
        if current["name"] == selected_name:
            return self.get_node(node_id) or {}
        node = HierarchyNode(
            schema_version=HIERARCHY_RECORD_SCHEMA_VERSION,
            id=node_id,
            kind=str(current["kind"]),
            name=selected_name,
            slug=portable_node_slug(selected_name, node_id, str(current["kind"])),
            parent_id=(
                str(current["parent_id"])
                if isinstance(current.get("parent_id"), str)
                else None
            ),
            created_at=str(current["created_at"]),
            updated_at=utc_now(),
        )
        self.store.write_hierarchy_node(node)
        return self.get_node(node_id) or {}

    def move_node(self, node_id: str, parent_id: str | None) -> dict[str, Any]:
        nodes, _classifications = self._state()
        current = nodes.get(node_id)
        if current is None:
            raise HierarchyNotFoundError(f"hierarchy node not found: {node_id}")
        if parent_id is not None and parent_id not in nodes:
            raise HierarchyNotFoundError(f"hierarchy node not found: {parent_id}")
        if parent_id == node_id:
            raise HierarchyConflictError("hierarchy node cannot be its own parent")
        self._validate_parent_kind(str(current["kind"]), parent_id, nodes)
        if parent_id is not None:
            children = self._children(nodes)
            if parent_id in self._descendant_ids(node_id, children):
                raise HierarchyConflictError("hierarchy movement would create a cycle")
            lineage = self._lineage(parent_id, nodes)
            if len(lineage) >= MAX_HIERARCHY_DEPTH:
                raise HierarchyConflictError(
                    f"hierarchy movement exceeds the {MAX_HIERARCHY_DEPTH}-level limit"
                )
        if current.get("parent_id") == parent_id:
            return self.get_node(node_id) or {}
        node = HierarchyNode(
            schema_version=HIERARCHY_RECORD_SCHEMA_VERSION,
            id=node_id,
            kind=str(current["kind"]),
            name=str(current["name"]),
            slug=str(current["slug"]),
            parent_id=parent_id,
            created_at=str(current["created_at"]),
            updated_at=utc_now(),
        )
        self.store.write_hierarchy_node(node)
        return self.get_node(node_id) or {}

    @staticmethod
    def _classification_view(
        classification: Mapping[str, Any],
        nodes: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        def node_reference(node_id: str) -> dict[str, Any]:
            node = nodes[node_id]
            lineage = HierarchyManager._lineage(node_id, nodes)
            return {
                "id": node_id,
                "kind": str(node["kind"]),
                "name": str(node["name"]),
                "slug": str(node["slug"]),
                "breadcrumbs": [str(item["name"]) for item in lineage],
                "portable_path": "/".join(str(item["slug"]) for item in lineage),
            }

        primary_id = str(classification["primary_node_id"])
        secondary_ids = [str(item) for item in classification["secondary_node_ids"]]
        return {
            **dict(classification),
            "primary": node_reference(primary_id),
            "secondary": [node_reference(node_id) for node_id in secondary_ids],
        }

    def classification_views(self) -> dict[str, dict[str, Any]]:
        nodes, classifications = self._state()
        return {
            str(item["document_id"]): self._classification_view(item, nodes)
            for item in classifications.values()
        }

    def get_classification(self, document_id: str) -> dict[str, Any] | None:
        return self.classification_views().get(document_id)

    def classify_document(
        self,
        document_id: str,
        primary_node_id: str,
        *,
        secondary_node_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        nodes, classifications = self._state()
        if self.store.read_canonical("documents", document_id) is None:
            raise HierarchyNotFoundError(f"document not found: {document_id}")
        if primary_node_id not in nodes:
            raise HierarchyNotFoundError(
                f"hierarchy node not found: {primary_node_id}"
            )
        if isinstance(secondary_node_ids, (str, bytes)):
            raise HierarchyError("secondary hierarchy identities must be a sequence")
        selected_secondary = tuple(sorted(set(secondary_node_ids)))
        if primary_node_id in selected_secondary:
            raise HierarchyConflictError(
                "primary hierarchy node cannot also be a secondary association"
            )
        missing = [node_id for node_id in selected_secondary if node_id not in nodes]
        if missing:
            raise HierarchyNotFoundError(f"hierarchy node not found: {missing[0]}")
        associations = (
            ("classified_primary_as", primary_node_id),
            *(("classified_secondary_as", node_id) for node_id in selected_secondary),
        )
        existing_edges: dict[str, dict[str, Any] | None] = {}
        for relation, node_id in associations:
            edge_id = classification_edge_id(document_id, relation, node_id)
            existing_edge = self.store.read_canonical("provenance", edge_id)
            existing_edges[edge_id] = existing_edge
            if existing_edge is not None and (
                existing_edge.get("from_kind") != "document"
                or existing_edge.get("from_id") != document_id
                or existing_edge.get("relation") != relation
                or existing_edge.get("to_kind") != "hierarchy_node"
                or existing_edge.get("to_id") != node_id
            ):
                raise HierarchyIntegrityError(
                    "deterministic classification provenance edge is invalid"
                )
        record_id = classification_id(document_id)
        existing = classifications.get(record_id)
        unchanged = existing is not None and (
            existing["primary_node_id"] == primary_node_id
            and tuple(existing["secondary_node_ids"]) == selected_secondary
        )
        now = utc_now()
        edge_created_at = str(existing["updated_at"]) if unchanged else now
        if not unchanged:
            classification = DocumentClassification(
                schema_version=CLASSIFICATION_RECORD_SCHEMA_VERSION,
                id=record_id,
                document_id=document_id,
                primary_node_id=primary_node_id,
                secondary_node_ids=selected_secondary,
                created_at=str(existing["created_at"]) if existing else now,
                updated_at=now,
            )
            self.store.write_classification(classification)
        for relation, node_id in associations:
            edge_id = classification_edge_id(document_id, relation, node_id)
            if existing_edges[edge_id] is not None:
                continue
            self.store.write_provenance(
                ProvenanceEdge(
                    id=edge_id,
                    from_kind="document",
                    from_id=document_id,
                    relation=relation,
                    to_kind="hierarchy_node",
                    to_id=node_id,
                    created_at=edge_created_at,
                )
            )
        return self.get_classification(document_id) or {}

    def document_ids_for_node(
        self,
        node_id: str,
        *,
        include_descendants: bool = True,
    ) -> set[str]:
        nodes, classifications = self._state()
        if node_id not in nodes:
            raise HierarchyNotFoundError(f"hierarchy node not found: {node_id}")
        selected_nodes = {node_id}
        if include_descendants:
            selected_nodes = self._descendant_ids(node_id, self._children(nodes))
        result: set[str] = set()
        for classification in classifications.values():
            associated = {
                str(classification["primary_node_id"]),
                *(str(item) for item in classification["secondary_node_ids"]),
            }
            if selected_nodes.intersection(associated):
                result.add(str(classification["document_id"]))
        return result
