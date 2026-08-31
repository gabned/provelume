from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from .domain import (
    Acquisition,
    ConnectorDefinition,
    ConnectorInstance,
    ConnectorSource,
    DerivedArtifact,
    Document,
    DocumentClassification,
    DocumentDisposition,
    DocumentVersion,
    EmailAttachmentEvidence,
    EmailMessageEvidence,
    EmailMessageObservation,
    HierarchyNode,
    Original,
    ProvenanceEdge,
    Source,
    as_record,
)
from .instance_schema import (
    CURRENT_INSTANCE_SCHEMA_VERSION,
    build_instance_manifest,
    manifest_validation_errors,
)
from .ocr_contract import default_ocr_config, ocr_settings_from_config
from .paths import portable_config_path, resolve_config_path, safe_instance_path

SCHEMA_VERSION = CURRENT_INSTANCE_SCHEMA_VERSION
REQUIRED_CANONICAL_KINDS = (
    "sources",
    "acquisitions",
    "originals",
    "documents",
    "versions",
    "provenance",
)
ADDITIVE_CANONICAL_KINDS = (
    "hierarchy",
    "classifications",
    "dispositions",
    "connector-definitions",
    "connector-instances",
    "email-messages",
    "email-observations",
    "email-attachments",
)
CANONICAL_KINDS = REQUIRED_CANONICAL_KINDS + ADDITIVE_CANONICAL_KINDS


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class InstancePaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "provelume.yml"

    @property
    def manifest(self) -> Path:
        return self.root / "instance-manifest.json"

    @property
    def originals(self) -> Path:
        return self.root / "originals"

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def indexes(self) -> Path:
        return self.root / "indexes"

    @property
    def library(self) -> Path:
        return self.root / "library"

    @property
    def migration_receipts(self) -> Path:
        return self.state / "migrations" / "receipts"

    @property
    def lifecycle_recovery_receipts(self) -> Path:
        return self.state / "lifecycle" / "recovery-receipts"

    def canonical_dir(self, kind: str) -> Path:
        return self.knowledge / kind

    @property
    def derived_artifacts(self) -> Path:
        return self.state / "derived" / "artifacts"

    @property
    def derived_text(self) -> Path:
        return self.state / "derived" / "text"

    @property
    def derived_provenance(self) -> Path:
        return self.state / "derived" / "provenance"


class InstanceStore:
    def __init__(self, root: Path | str):
        self.paths = InstancePaths(Path(root).expanduser().resolve())
        self._open_preparation: dict[str, Any] | None = None

    @classmethod
    def initialise(
        cls,
        root: Path | str,
        *,
        name: str = "Provelume Instance",
    ) -> InstanceStore:
        store = cls(root)
        existing = store.paths.config.exists()
        store.paths.root.mkdir(parents=True, exist_ok=True)
        for path in (
            store.paths.originals,
            store.paths.indexes,
            store.paths.state,
            store.paths.derived_artifacts,
            store.paths.derived_text,
            store.paths.derived_provenance,
        ):
            path.mkdir(parents=True, exist_ok=True)
        for kind in CANONICAL_KINDS:
            store.paths.canonical_dir(kind).mkdir(parents=True, exist_ok=True)
        if not existing:
            created_at = utc_now()
            config = {
                "schema_version": SCHEMA_VERSION,
                "instance": {
                    "id": f"inst_{uuid4().hex}",
                    "name": name,
                    "created_at": created_at,
                },
                "ui": {"language": "en"},
                "network": {"external_access": False, "update_checks": False},
                "ocr": default_ocr_config(),
                "sources": {},
            }
            store._atomic_text(
                store.paths.config,
                yaml.safe_dump(config, sort_keys=False),
            )
            store._atomic_json(
                store.paths.manifest,
                build_instance_manifest(config),
            )
        if existing:
            return cls.open(root)
        store.validate()
        return store

    @classmethod
    def open(cls, root: Path | str) -> InstanceStore:
        store = cls(root)
        from .instance_lifecycle import InstanceLifecycleManager

        store._open_preparation = InstanceLifecycleManager(store).prepare()
        store.validate()
        return store

    def validate(self) -> None:
        if not self.paths.config.is_file():
            raise FileNotFoundError(f"not a Provelume Instance: {self.paths.config}")
        config = self.read_config()
        if config.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported Provelume Instance schema version")
        instance = config.get("instance")
        if (
            not isinstance(instance, dict)
            or not isinstance(instance.get("id"), str)
            or not instance["id"].startswith("inst_")
            or not isinstance(instance.get("name"), str)
            or not instance["name"].strip()
            or not isinstance(instance.get("created_at"), str)
            or not instance["created_at"].strip()
        ):
            raise ValueError("invalid Provelume Instance identity")
        ocr_settings_from_config(config)
        manifest = self.read_manifest()
        errors = manifest_validation_errors(manifest, config=config)
        if errors:
            raise ValueError(errors[0])

    def read_config(self) -> dict[str, Any]:
        with self.paths.config.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle) or {}
        if not isinstance(value, dict):
            raise ValueError("invalid provelume.yml")
        return value

    def read_manifest(self) -> dict[str, Any]:
        if not self.paths.manifest.is_file():
            raise FileNotFoundError(
                f"missing Provelume Instance manifest: {self.paths.manifest}"
            )
        return self._read_json(self.paths.manifest)

    def write_config(self, config: dict[str, Any]) -> None:
        self._atomic_text(self.paths.config, yaml.safe_dump(config, sort_keys=False))

    def register_source_path(self, source_id: str, path: Path, *, name: str) -> None:
        config = self.read_config()
        sources = config.setdefault("sources", {})
        current = sources.get(source_id)
        preserved = dict(current) if isinstance(current, dict) else {}
        sources[source_id] = {
            **preserved,
            "kind": "filesystem",
            "name": name,
            "path": portable_config_path(self.paths.root, path),
        }
        self.write_config(config)

    def find_source_for_path(self, path: Path) -> str | None:
        target = path.resolve()
        for source_id, item in (self.read_config().get("sources") or {}).items():
            configured = item.get("path")
            if not isinstance(configured, str):
                continue
            if resolve_config_path(self.paths.root, configured) == target:
                return str(source_id)
        return None

    def source_path(self, source_id: str) -> Path | None:
        item = (self.read_config().get("sources") or {}).get(source_id)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return None
        return resolve_config_path(self.paths.root, item["path"])

    def write_canonical(self, kind: str, record: Any) -> None:
        payload = as_record(record)
        path = self.paths.canonical_dir(kind) / f"{payload['id']}.json"
        self._atomic_json(path, payload)

    def read_canonical(self, kind: str, record_id: str) -> dict[str, Any] | None:
        path = self.paths.canonical_dir(kind) / f"{record_id}.json"
        if not path.is_file():
            return None
        return self._read_json(path)

    def list_canonical(self, kind: str) -> list[dict[str, Any]]:
        directory = self.paths.canonical_dir(kind)
        if not directory.exists():
            return []
        return [self._read_json(path) for path in sorted(directory.glob("*.json"))]

    def write_source(self, source: Source) -> None:
        self.write_canonical("sources", source)

    def write_connector_definition(self, definition: ConnectorDefinition) -> None:
        self.write_canonical("connector-definitions", definition)

    def write_connector_instance(self, instance: ConnectorInstance) -> None:
        self.write_canonical("connector-instances", instance)

    def write_connector_source(self, source: ConnectorSource) -> None:
        self.write_canonical("sources", source)

    def write_acquisition(self, acquisition: Acquisition) -> None:
        self.write_canonical("acquisitions", acquisition)

    def write_original(self, original: Original) -> None:
        self.write_canonical("originals", original)

    def write_document(self, document: Document) -> None:
        self.write_canonical("documents", document)

    def write_version(self, version: DocumentVersion) -> None:
        self.write_canonical("versions", version)

    def write_provenance(self, edge: ProvenanceEdge) -> None:
        self.write_canonical("provenance", edge)

    def write_hierarchy_node(self, node: HierarchyNode) -> None:
        self.write_canonical("hierarchy", node)

    def write_classification(self, classification: DocumentClassification) -> None:
        self.write_canonical("classifications", classification)

    def write_disposition(self, disposition: DocumentDisposition) -> None:
        self.write_canonical("dispositions", disposition)

    def write_email_message_evidence(self, evidence: EmailMessageEvidence) -> None:
        self.write_canonical("email-messages", evidence)

    def write_email_message_observation(
        self,
        observation: EmailMessageObservation,
    ) -> None:
        self.write_canonical("email-observations", observation)

    def write_email_attachment_evidence(
        self,
        evidence: EmailAttachmentEvidence,
    ) -> None:
        self.write_canonical("email-attachments", evidence)

    def write_derived_artifact(self, artifact: DerivedArtifact) -> None:
        path = self.paths.derived_artifacts / f"{artifact.id}.json"
        self._atomic_json(path, as_record(artifact))

    def write_derived_provenance(self, edge: ProvenanceEdge) -> None:
        path = self.paths.derived_provenance / f"{edge.id}.json"
        self._atomic_json(path, as_record(edge))

    def list_derived_artifacts(self) -> list[dict[str, Any]]:
        paths = sorted(self.paths.derived_artifacts.glob("*.json"))
        return [self._read_json(path) for path in paths]

    def list_derived_provenance(self) -> list[dict[str, Any]]:
        paths = sorted(self.paths.derived_provenance.glob("*.json"))
        return [self._read_json(path) for path in paths]

    def store_original_bytes(self, data: bytes) -> Original:
        digest = hashlib.sha256(data).hexdigest()
        original_id = f"sha256_{digest}"
        relative = f"originals/sha256/{digest[:2]}/{digest}"
        target = safe_instance_path(self.paths.root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            self._atomic_bytes(target, data)
        existing = self.read_canonical("originals", original_id)
        if existing is None:
            original = Original(
                id=original_id,
                sha256=digest,
                size_bytes=len(data),
                storage_ref=relative,
                created_at=utc_now(),
            )
            self.write_original(original)
            return original
        return Original(**existing)

    def original_bytes(self, original_id: str) -> bytes:
        record = self.read_canonical("originals", original_id)
        if record is None:
            raise KeyError(original_id)
        path = safe_instance_path(self.paths.root, record["storage_ref"])
        return path.read_bytes()

    def find_document(self, source_id: str, locator: str) -> dict[str, Any] | None:
        for document in self.list_canonical("documents"):
            if document["source_id"] == source_id and document["locator"] == locator:
                return document
        return None

    def versions_for_document(self, document_id: str) -> list[dict[str, Any]]:
        versions = [
            item
            for item in self.list_canonical("versions")
            if item["document_id"] == document_id
        ]
        return sorted(versions, key=lambda item: int(item["sequence"]))

    def derived_artifact_for_version(
        self,
        version_id: str,
        kind: str = "extracted_text",
    ) -> dict[str, Any] | None:
        for artifact in self.list_derived_artifacts():
            if artifact["version_id"] == version_id and artifact["kind"] == kind:
                path = safe_instance_path(self.paths.root, artifact["storage_ref"])
                if path.exists():
                    return artifact
        return None

    def read_derived_text(self, artifact: dict[str, Any]) -> str:
        path = safe_instance_path(self.paths.root, artifact["storage_ref"])
        return path.read_text(encoding="utf-8")

    def write_derived_text(self, artifact_id: str, text: str) -> tuple[str, str]:
        relative = f"state/derived/text/{artifact_id}.txt"
        target = safe_instance_path(self.paths.root, relative)
        encoded = text.encode("utf-8")
        self._atomic_bytes(target, encoded)
        return relative, hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"expected JSON object in {path}")
        return value

    def _atomic_json(self, path: Path, payload: dict[str, Any]) -> None:
        self._atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        InstanceStore._atomic_bytes(path, content.encode("utf-8"))

    @staticmethod
    def _atomic_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def knowledge_fingerprint(self) -> str:
        pairs = sorted(
            f"{item['id']}:{item['current_version_id']}"
            for item in self.list_canonical("documents")
        )
        return hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest()

    def provenance_for_ids(self, ids: Iterable[str]) -> list[dict[str, Any]]:
        wanted = set(ids)
        edges = self.list_canonical("provenance") + self.list_derived_provenance()
        return [
            edge
            for edge in edges
            if edge["from_id"] in wanted or edge["to_id"] in wanted
        ]
