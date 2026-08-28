from __future__ import annotations

import hashlib
import json
import posixpath
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from .hierarchy import HierarchyManager
from .retention_model import effective_dispositions
from .storage import InstanceStore

LIBRARY_PROJECTION_SCHEMA_VERSION = 1
LIBRARY_GENERATOR = "provelume.markdown_library"
LIBRARY_GENERATOR_VERSION = "1"
LIBRARY_MANIFEST = ".provelume-library.json"
LIBRARY_REBUILD_LOCK = "derived-rebuild"
DEFAULT_MAX_LIBRARY_DOCUMENTS = 1_000
MAX_LIBRARY_DOCUMENTS = 50_000
MAX_LIBRARY_FILES = 100_000
MAX_LIBRARY_FILE_BYTES = 4 * 1024 * 1024
MAX_LIBRARY_MANIFEST_BYTES = 16 * 1024 * 1024
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_DOCUMENT_ID = re.compile(r"doc_[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class LibraryProjectionError(RuntimeError):
    pass


class LibraryProjectionLimitError(LibraryProjectionError):
    pass


@dataclass(slots=True)
class _Index:
    title: str
    description: str
    children: dict[PurePosixPath, str] = field(default_factory=dict)
    documents: dict[str, set[str]] = field(default_factory=dict)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def portable_projection_slug(label: str, stable_id: str, fallback: str) -> str:
    selected = " ".join(label.replace("\r", " ").replace("\n", " ").split())
    decomposed = unicodedata.normalize("NFKD", selected)
    ascii_label = decomposed.encode("ascii", "ignore").decode("ascii").casefold()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_label).strip("-")
    if not base:
        base = fallback
    base = base[:64].rstrip("-") or fallback
    suffix = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:32]
    return f"{base}--{suffix}"


def _markdown_label(value: str) -> str:
    selected = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    selected = (
        selected.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    for character in ("\\", "[", "]", "*", "_", "`", "#"):
        selected = selected.replace(character, f"\\{character}")
    return selected or "Untitled"


def _relative_link(from_file: PurePosixPath, target: PurePosixPath) -> str:
    start = from_file.parent.as_posix()
    return posixpath.relpath(target.as_posix(), start=start if start != "." else ".")


class LibraryLayoutBuilder:
    """Derive portable directories, indexes and one primary path per Document."""

    def __init__(self, store: InstanceStore):
        self.store = store

    @staticmethod
    def _ensure_index(
        indexes: dict[PurePosixPath, _Index],
        path: PurePosixPath,
        title: str,
        description: str,
    ) -> _Index:
        selected = indexes.get(path)
        if selected is None:
            selected = _Index(title=title, description=description)
            indexes[path] = selected
        return selected

    @staticmethod
    def _connect(
        indexes: dict[PurePosixPath, _Index],
        parent: PurePosixPath,
        child: PurePosixPath,
        label: str,
    ) -> None:
        indexes[parent].children[child] = label

    def _base_indexes(self) -> dict[PurePosixPath, _Index]:
        instance = self.store.read_config()["instance"]
        indexes: dict[PurePosixPath, _Index] = {}
        root = PurePosixPath(".")
        self._ensure_index(
            indexes,
            root,
            str(instance["name"]),
            (
                "Deterministic derived Markdown library. Canonical JSON and preserved "
                "Originals remain authoritative."
            ),
        )
        roots = {
            PurePosixPath("areas"): (
                "Areas",
                "Stable Area and Subarea navigation.",
            ),
            PurePosixPath("projects"): (
                "Projects",
                "Stable Project navigation, including Area ancestry.",
            ),
            PurePosixPath("archive"): (
                "Archive",
                "Documents explicitly archived while their canonical identity remains intact.",
            ),
            PurePosixPath("unclassified"): (
                "Unclassified",
                "Documents without a current primary library classification.",
            ),
            PurePosixPath("views"): (
                "Generated views",
                "Collection, tag, person, Source, date and media-type indexes.",
            ),
        }
        for path, (title, description) in roots.items():
            self._ensure_index(indexes, path, title, description)
            self._connect(indexes, root, path, title)
        view_roots = {
            PurePosixPath("views/collections"): (
                "Collections",
                "Stable Collection association indexes.",
            ),
            PurePosixPath("views/tags"): (
                "Tags",
                "No canonical tag assignments are defined in Instance schema 2.",
            ),
            PurePosixPath("views/people"): (
                "People",
                "No canonical person assignments are defined in Instance schema 2.",
            ),
            PurePosixPath("views/sources"): (
                "Sources",
                "Generated indexes grouped by canonical Source identity.",
            ),
            PurePosixPath("views/dates"): (
                "Dates",
                "Generated indexes grouped by current acquisition date.",
            ),
            PurePosixPath("views/types"): (
                "Media types",
                "Generated indexes grouped by current media type.",
            ),
        }
        for path, (title, description) in view_roots.items():
            self._ensure_index(indexes, path, title, description)
            self._connect(indexes, PurePosixPath("views"), path, title)
        return indexes

    def _hierarchy_indexes(
        self,
        indexes: dict[PurePosixPath, _Index],
    ) -> dict[str, PurePosixPath]:
        nodes = HierarchyManager(self.store).list_nodes()
        node_paths: dict[str, PurePosixPath] = {}
        roots = {
            "area": PurePosixPath("areas"),
            "project": PurePosixPath("projects"),
            "collection": PurePosixPath("views/collections"),
        }
        for node in nodes:
            kind = str(node["kind"])
            current = roots[kind]
            parent = current
            for crumb in node["breadcrumbs"]:
                current /= str(crumb["slug"])
                self._ensure_index(
                    indexes,
                    current,
                    str(crumb["name"]),
                    f"Stable {str(crumb['kind']).capitalize()} projection index.",
                )
                self._connect(indexes, parent, current, str(crumb["name"]))
                parent = current
            node_paths[str(node["id"])] = current
        return node_paths

    def _dated_index(
        self,
        indexes: dict[PurePosixPath, _Index],
        acquired_at: str,
    ) -> PurePosixPath:
        date = acquired_at[:10] if _DATE.fullmatch(acquired_at[:10]) else "unknown"
        root = PurePosixPath("views/dates")
        if date == "unknown":
            selected = root / "unknown"
            self._ensure_index(
                indexes,
                selected,
                "Unknown date",
                "Documents whose current acquisition date is unavailable.",
            )
            self._connect(indexes, root, selected, "Unknown date")
            return selected
        current = root
        labels = (date[:4], date[5:7], date[8:10])
        for position, label in enumerate(labels):
            parent = current
            current /= label
            description = (
                "Generated acquisition year index."
                if position == 0
                else "Generated acquisition month index."
                if position == 1
                else "Generated acquisition day index."
            )
            self._ensure_index(indexes, current, label, description)
            self._connect(indexes, parent, current, label)
        return current

    def _document_layout(
        self,
        indexes: dict[PurePosixPath, _Index],
        node_paths: dict[str, PurePosixPath],
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, PurePosixPath],
    ]:
        dispositions = effective_dispositions(self.store)
        documents = sorted(
            (
                item
                for item in self.store.list_canonical("documents")
                if dispositions[str(item["id"])]["projected"]
            ),
            key=lambda item: (str(item["title"]).casefold(), str(item["id"])),
        )
        sources = {
            str(item["id"]): item for item in self.store.list_canonical("sources")
        }
        classifications = {
            str(item["document_id"]): item
            for item in self.store.list_canonical("classifications")
        }
        paths: dict[str, PurePosixPath] = {}
        for document in documents:
            document_id = str(document["id"])
            classification = classifications.get(document_id)
            disposition = dispositions[document_id]
            primary_id = (
                str(classification["primary_node_id"]) if classification else None
            )
            directory = (
                PurePosixPath("archive")
                if disposition["status"] == "archived"
                else node_paths[primary_id]
                if primary_id is not None
                else PurePosixPath("unclassified")
            )
            filename = (
                portable_projection_slug(
                    str(document["title"]),
                    document_id,
                    "document",
                )
                + ".md"
            )
            paths[document_id] = directory / filename
            relation = (
                "archived"
                if disposition["status"] == "archived"
                else "primary"
                if classification
                else "unclassified"
            )
            indexes[directory].documents.setdefault(document_id, set()).add(relation)
            indexes[PurePosixPath(".")].documents.setdefault(document_id, set()).add(
                "primary path"
            )
            if classification and disposition["status"] != "archived":
                for node_id in classification["secondary_node_ids"]:
                    indexes[node_paths[str(node_id)]].documents.setdefault(
                        document_id,
                        set(),
                    ).add("secondary")

            source = sources[str(document["source_id"])]
            source_path = PurePosixPath("views/sources") / portable_projection_slug(
                str(source["name"]),
                str(source["id"]),
                "source",
            )
            self._ensure_index(
                indexes,
                source_path,
                str(source["name"]),
                "Generated canonical Source index.",
            )
            self._connect(
                indexes,
                PurePosixPath("views/sources"),
                source_path,
                str(source["name"]),
            )
            indexes[source_path].documents.setdefault(document_id, set()).add("source")

            version = self.store.read_canonical(
                "versions",
                str(document["current_version_id"]),
            )
            if version is None:
                raise LibraryProjectionError(
                    f"Document has no readable current Version: {document_id}"
                )
            date_path = self._dated_index(indexes, str(version["acquired_at"]))
            indexes[date_path].documents.setdefault(document_id, set()).add("date")

            media_type = str(version["media_type"])
            type_path = PurePosixPath("views/types") / portable_projection_slug(
                media_type,
                media_type,
                "type",
            )
            self._ensure_index(
                indexes,
                type_path,
                media_type,
                "Generated current media-type index.",
            )
            self._connect(
                indexes,
                PurePosixPath("views/types"),
                type_path,
                media_type,
            )
            indexes[type_path].documents.setdefault(document_id, set()).add("type")
        return documents, classifications, paths

    @staticmethod
    def _index_bytes(
        path: PurePosixPath,
        index: _Index,
        documents: dict[str, dict[str, Any]],
        document_paths: dict[str, PurePosixPath],
    ) -> bytes:
        readme = path / "README.md"
        lines = [
            f"# {_markdown_label(index.title)}",
            "",
            index.description,
            "",
            (
                "> Generated derived index. Edits here never mutate canonical knowledge "
                "or preserved Originals."
            ),
        ]
        if index.children:
            lines.extend(["", "## Folders", ""])
            for child, label in sorted(
                index.children.items(),
                key=lambda item: (item[1].casefold(), item[0].as_posix()),
            ):
                target = child / "README.md"
                lines.append(
                    f"- [{_markdown_label(label)}]({_relative_link(readme, target)})"
                )
        if index.documents:
            lines.extend(["", "## Documents", ""])
            ordered = sorted(
                index.documents,
                key=lambda document_id: (
                    str(documents[document_id]["title"]).casefold(),
                    document_id,
                ),
            )
            for document_id in ordered:
                document = documents[document_id]
                relations = ", ".join(sorted(index.documents[document_id]))
                lines.append(
                    f"- [{_markdown_label(str(document['title']))}]"
                    f"({_relative_link(readme, document_paths[document_id])})"
                    f" — {relations}"
                )
        if not index.children and not index.documents:
            lines.extend(["", "_No entries._"])
        return ("\n".join(lines).rstrip() + "\n").encode("utf-8")

    def build(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, PurePosixPath],
        dict[PurePosixPath, bytes],
    ]:
        indexes = self._base_indexes()
        node_paths = self._hierarchy_indexes(indexes)
        documents, classifications, document_paths = self._document_layout(
            indexes,
            node_paths,
        )
        document_map = {str(item["id"]): item for item in documents}
        index_files = {
            path / "README.md": self._index_bytes(
                path,
                index,
                document_map,
                document_paths,
            )
            for path, index in indexes.items()
        }
        return documents, classifications, document_paths, index_files
