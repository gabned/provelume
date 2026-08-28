from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .bundles import (
    BUNDLE_GENERATOR,
    BUNDLE_SCHEMA_VERSION,
    _json_bytes,
)
from .paths import safe_instance_path
from .storage import InstanceStore


class DocumentBundleReader:
    """Validate and expose derived bundles without mutating the Instance."""

    def __init__(self, store: InstanceStore):
        self.store = store

    @staticmethod
    def _artifact_id(version_id: str) -> str:
        key = f"{version_id}:document_bundle:{BUNDLE_SCHEMA_VERSION}"
        return f"derived_{uuid5(NAMESPACE_URL, key).hex}"

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _object(value: Any) -> dict[str, Any] | None:
        return value if isinstance(value, dict) else None

    @staticmethod
    def _safe_filename(value: Any) -> str | None:
        if not isinstance(value, str) or not value or value in {".", ".."}:
            return None
        if Path(value).name != value or "/" in value or "\\" in value:
            return None
        return value

    def _artifact_from_path(self, path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        artifact = self._object(value)
        if artifact is None:
            return None
        required = {
            "id",
            "version_id",
            "kind",
            "generator",
            "generator_version",
            "storage_ref",
            "checksum",
            "created_at",
        }
        if not required.issubset(artifact):
            return None
        if (
            artifact.get("kind") != "document_bundle"
            or artifact.get("generator") != BUNDLE_GENERATOR
            or artifact.get("id") != self._artifact_id(str(artifact.get("version_id")))
        ):
            return None
        return artifact

    def _validated_record(
        self,
        artifact: dict[str, Any],
    ) -> dict[str, Any] | None:
        version_id = str(artifact["version_id"])
        version = self.store.read_canonical("versions", version_id)
        if version is None:
            return None
        try:
            manifest_path = safe_instance_path(
                self.store.paths.root,
                str(artifact["storage_ref"]),
            )
            manifest_bytes = manifest_path.read_bytes()
        except (OSError, ValueError):
            return None
        if self._sha256(manifest_bytes) != artifact.get("checksum"):
            return None
        try:
            manifest_value = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        manifest = self._object(manifest_value)
        if manifest is None:
            return None
        if (
            manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION
            or manifest.get("generator") != BUNDLE_GENERATOR
            or manifest.get("version_id") != version_id
            or manifest.get("document_id") != version.get("document_id")
            or manifest.get("source_content_sha256") != version.get("content_hash")
        ):
            return None

        fingerprint = manifest.get("output_fingerprint")
        markdown = self._object(manifest.get("markdown"))
        page_map_meta = self._object(manifest.get("page_map"))
        assets = manifest.get("assets")
        warnings = manifest.get("warnings")
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or markdown is None
            or page_map_meta is None
            or not isinstance(assets, list)
            or not isinstance(warnings, list)
            or not all(isinstance(item, str) for item in warnings)
        ):
            return None
        base = f"state/derived/bundles/{version_id}/{fingerprint}"
        if artifact.get("storage_ref") != f"{base}/manifest.json":
            return None
        expected_fingerprint = self._sha256(
            _json_bytes(
                {
                    "schema_version": BUNDLE_SCHEMA_VERSION,
                    "version_id": version_id,
                    "source_sha256": version["content_hash"],
                    "markdown_sha256": markdown.get("sha256"),
                    "page_map_sha256": page_map_meta.get("sha256"),
                    "assets": [
                        {
                            "id": item.get("id"),
                            "sha256": item.get("sha256"),
                            "size_bytes": item.get("size_bytes"),
                        }
                        for item in assets
                        if isinstance(item, dict)
                    ],
                    "warnings": warnings,
                }
            )
        )
        if expected_fingerprint != fingerprint:
            return None

        try:
            markdown_ref = str(markdown["storage_ref"])
            markdown_path = safe_instance_path(self.store.paths.root, markdown_ref)
            markdown_bytes = markdown_path.read_bytes()
        except (KeyError, OSError, ValueError):
            return None
        if (
            markdown_ref != f"{base}/document.md"
            or self._sha256(markdown_bytes) != markdown.get("sha256")
            or len(markdown_bytes) != markdown.get("size_bytes")
        ):
            return None

        try:
            page_map_ref = str(page_map_meta["storage_ref"])
            page_map_path = safe_instance_path(self.store.paths.root, page_map_ref)
            page_map_bytes = page_map_path.read_bytes()
            page_map_value = json.loads(page_map_bytes.decode("utf-8"))
        except (KeyError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        page_map = self._object(page_map_value)
        if (
            page_map_ref != f"{base}/page-map.json"
            or self._sha256(page_map_bytes) != page_map_meta.get("sha256")
            or page_map is None
            or page_map.get("schema_version") != BUNDLE_SCHEMA_VERSION
            or page_map.get("version_id") != version_id
            or page_map.get("document_id") != version.get("document_id")
            or not isinstance(page_map.get("pages"), list)
            or len(page_map["pages"]) != page_map_meta.get("pages")
        ):
            return None

        validated_assets: list[dict[str, Any]] = []
        if len(assets) != len(
            [item for item in assets if isinstance(item, dict)]
        ):
            return None
        for asset in assets:
            filename = self._safe_filename(asset.get("filename"))
            digest = asset.get("sha256")
            if (
                filename is None
                or not isinstance(digest, str)
                or len(digest) != 64
                or asset.get("id") != f"asset_{digest}"
            ):
                return None
            expected_ref = f"{base}/assets/{filename}"
            if asset.get("storage_ref") != expected_ref:
                return None
            try:
                asset_path = safe_instance_path(self.store.paths.root, expected_ref)
                asset_bytes = asset_path.read_bytes()
            except (OSError, ValueError):
                return None
            if (
                self._sha256(asset_bytes) != digest
                or len(asset_bytes) != asset.get("size_bytes")
            ):
                return None
            validated_assets.append(asset)

        document = self.store.read_canonical(
            "documents",
            str(manifest["document_id"]),
        )
        if document is None:
            return None
        return {
            "artifact": artifact,
            "manifest": {**manifest, "assets": validated_assets},
            "document": document,
            "markdown_bytes": markdown_bytes,
            "page_map": page_map,
        }

    def get(self, version_id: str) -> dict[str, Any] | None:
        artifact_id = self._artifact_id(version_id)
        path = self.store.paths.derived_artifacts / f"{artifact_id}.json"
        artifact = self._artifact_from_path(path)
        if artifact is None or artifact.get("version_id") != version_id:
            return None
        record = self._validated_record(artifact)
        if record is None:
            return None
        return {
            "artifact": record["artifact"],
            "manifest": record["manifest"],
        }

    def for_document(self, document_id: str) -> dict[str, Any] | None:
        document = self.store.read_canonical("documents", document_id)
        if document is None:
            return None
        return self.get(str(document["current_version_id"]))

    def list(self, *, limit: int = 500) -> list[dict[str, Any]]:
        if limit < 1 or not self.store.paths.derived_artifacts.exists():
            return []
        records = []
        for path in self.store.paths.derived_artifacts.glob("derived_*.json"):
            artifact = self._artifact_from_path(path)
            if artifact is None:
                continue
            record = self._validated_record(artifact)
            if record is None:
                continue
            records.append(
                {
                    "artifact": record["artifact"],
                    "manifest": record["manifest"],
                    "document": record["document"],
                }
            )
        records.sort(
            key=lambda item: (
                str(item["artifact"].get("created_at", "")),
                str(item["artifact"].get("id", "")),
            ),
            reverse=True,
        )
        return records[: min(limit, 500)]

    def read_markdown(self, version_id: str) -> str | None:
        artifact_id = self._artifact_id(version_id)
        artifact = self._artifact_from_path(
            self.store.paths.derived_artifacts / f"{artifact_id}.json"
        )
        if artifact is None:
            return None
        record = self._validated_record(artifact)
        if record is None:
            return None
        try:
            return record["markdown_bytes"].decode("utf-8")
        except UnicodeDecodeError:
            return None

    def read_page_map(self, version_id: str) -> dict[str, Any] | None:
        artifact_id = self._artifact_id(version_id)
        artifact = self._artifact_from_path(
            self.store.paths.derived_artifacts / f"{artifact_id}.json"
        )
        if artifact is None:
            return None
        record = self._validated_record(artifact)
        return record["page_map"] if record is not None else None
