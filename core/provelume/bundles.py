from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pypdf import PdfReader

from .derived import provenance_edge
from .domain import DerivedArtifact
from .extractors import ExtractionError, extractor_for
from .operations import OperationLedger
from .paths import safe_instance_path
from .storage import InstanceStore, utc_now

BUNDLE_SCHEMA_VERSION = 1
BUNDLE_GENERATOR = "provelume.document_bundle"
BUNDLE_GENERATOR_VERSION = "1"
DEFAULT_MAX_BUNDLE_DOCUMENTS = 1000
MAX_BUNDLE_PAGES = 500
MAX_BUNDLE_ASSETS = 200
MAX_ASSET_BYTES = 10 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 50 * 1024 * 1024
MAX_BUNDLE_TEXT_CHARS = 2_000_000
MAX_WARNINGS = 200
_SAFE_SUFFIX = re.compile(r"\.[a-zA-Z0-9]{1,8}\Z")


class BundleBuildError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _normalise_text(value: str) -> str:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stripped = [line.rstrip() for line in lines]
    while stripped and not stripped[0]:
        stripped.pop(0)
    while stripped and not stripped[-1]:
        stripped.pop()
    output: list[str] = []
    blank = False
    for line in stripped:
        if not line:
            if not blank:
                output.append("")
            blank = True
        else:
            output.append(line)
            blank = False
    return "\n".join(output)


def _heading(value: str) -> str:
    selected = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    return selected or "Untitled document"


class DocumentBundleManager:
    """Build deterministic, version-addressed Markdown document bundles."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.state / "derived" / "bundles"
        self.operations = OperationLedger(store)

    @staticmethod
    def _artifact_id(version_id: str) -> str:
        key = f"{version_id}:document_bundle:{BUNDLE_SCHEMA_VERSION}"
        return f"derived_{uuid5(NAMESPACE_URL, key).hex}"

    def _version_and_document(
        self,
        version_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        version = self.store.read_canonical("versions", version_id)
        if version is None:
            raise BundleBuildError(f"DocumentVersion not found: {version_id}")
        document = self.store.read_canonical("documents", version["document_id"])
        if document is None:
            raise BundleBuildError(
                f"Document not found for DocumentVersion: {version_id}"
            )
        return version, document

    def _verified_original(
        self,
        version: dict[str, Any],
    ) -> tuple[dict[str, Any], bytes]:
        original = self.store.read_canonical("originals", version["original_id"])
        if original is None:
            raise BundleBuildError(
                f"Original not found for DocumentVersion: {version['id']}"
            )
        data = self.store.original_bytes(original["id"])
        digest = _sha256(data)
        if (
            digest != version["content_hash"]
            or digest != original["sha256"]
            or len(data) != int(original["size_bytes"])
        ):
            raise BundleBuildError(
                f"Original verification failed for DocumentVersion: {version['id']}"
            )
        return original, data

    @staticmethod
    def _asset_suffix(name: str) -> str:
        suffix = Path(name).suffix.lower()
        return suffix if _SAFE_SUFFIX.fullmatch(suffix) else ".bin"

    def _pdf_pages(
        self,
        data: bytes,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise BundleBuildError("encrypted PDF requires a password")
        except BundleBuildError:
            raise
        except Exception as exc:
            raise BundleBuildError(
                f"PDF document bundle could not be opened ({exc.__class__.__name__})"
            ) from exc
        if len(reader.pages) > MAX_BUNDLE_PAGES:
            raise BundleBuildError(
                f"PDF exceeds the {MAX_BUNDLE_PAGES}-page bundle safety limit"
            )

        pages: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        warnings: list[str] = []
        total_asset_bytes = 0
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = _normalise_text(page.extract_text() or "")
            except Exception as exc:
                text = ""
                warnings.append(
                    f"Page {page_number} text extraction failed "
                    f"({exc.__class__.__name__})."
                )
            if len(text) > MAX_BUNDLE_TEXT_CHARS:
                text = text[:MAX_BUNDLE_TEXT_CHARS]
                warnings.append(
                    f"Page {page_number} text was truncated at the bundle safety limit."
                )

            page_assets: list[str] = []
            if len(assets) < MAX_BUNDLE_ASSETS:
                try:
                    images = list(page.images)
                except Exception as exc:
                    images = []
                    warnings.append(
                        f"Page {page_number} assets could not be inspected "
                        f"({exc.__class__.__name__})."
                    )
                for image_number, image in enumerate(images, start=1):
                    if len(assets) >= MAX_BUNDLE_ASSETS:
                        warnings.append(
                            f"Asset extraction stopped at {MAX_BUNDLE_ASSETS} files."
                        )
                        break
                    try:
                        image_data = bytes(image.data)
                    except Exception as exc:
                        warnings.append(
                            f"Page {page_number} asset {image_number} was skipped "
                            f"({exc.__class__.__name__})."
                        )
                        continue
                    if len(image_data) > MAX_ASSET_BYTES:
                        warnings.append(
                            f"Page {page_number} asset {image_number} exceeded the "
                            "per-asset safety limit."
                        )
                        continue
                    if total_asset_bytes + len(image_data) > MAX_TOTAL_ASSET_BYTES:
                        warnings.append(
                            "Asset extraction stopped at the total byte safety limit."
                        )
                        break
                    digest = _sha256(image_data)
                    suffix = self._asset_suffix(getattr(image, "name", "asset.bin"))
                    filename = (
                        f"asset-p{page_number:04d}-{image_number:03d}-"
                        f"{digest[:16]}{suffix}"
                    )
                    media_type = (
                        mimetypes.guess_type(filename)[0]
                        or "application/octet-stream"
                    )
                    asset = {
                        "id": f"asset_{digest}",
                        "page": page_number,
                        "sequence": image_number,
                        "filename": filename,
                        "sha256": digest,
                        "size_bytes": len(image_data),
                        "media_type": media_type,
                        "data": image_data,
                    }
                    assets.append(asset)
                    page_assets.append(asset["id"])
                    total_asset_bytes += len(image_data)
            pages.append(
                {
                    "number": page_number,
                    "label": str(page_number),
                    "text": text,
                    "asset_ids": page_assets,
                    "extraction_status": "text" if text else "no_text",
                }
            )
        return pages, assets, warnings[:MAX_WARNINGS]

    def _single_page(
        self,
        document: dict[str, Any],
        data: bytes,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        extractor = extractor_for(Path(document["locator"]))
        if extractor is None:
            raise BundleBuildError(
                f"No document-bundle extractor for {document['media_type']}"
            )
        try:
            extraction = extractor.extract(data)
        except ExtractionError as exc:
            raise BundleBuildError(str(exc)) from exc
        text = _normalise_text(extraction.text)
        if len(text) > MAX_BUNDLE_TEXT_CHARS:
            text = text[:MAX_BUNDLE_TEXT_CHARS]
            warnings = ["Extracted text was truncated at the bundle safety limit."]
        else:
            warnings = []
        return (
            [
                {
                    "number": 1,
                    "label": "document",
                    "text": text,
                    "asset_ids": [],
                    "extraction_status": "text" if text else "no_text",
                }
            ],
            [],
            warnings,
        )

    @staticmethod
    def _markdown_and_page_map(
        document: dict[str, Any],
        version: dict[str, Any],
        pages: list[dict[str, Any]],
        assets: list[dict[str, Any]],
    ) -> tuple[bytes, dict[str, Any]]:
        assets_by_id = {asset["id"]: asset for asset in assets}
        lines = [f"# {_heading(document['title'])}", ""]
        page_map: list[dict[str, Any]] = []
        for page in pages:
            start_line = len(lines) + 1
            lines.extend([f"## Page {page['label']}", ""])
            text = page["text"]
            if text:
                lines.extend(text.split("\n"))
            else:
                lines.append("_No extractable text._")
            if page["asset_ids"]:
                lines.extend(["", "### Assets", ""])
                for asset_id in page["asset_ids"]:
                    asset = assets_by_id[asset_id]
                    lines.append(
                        f"- [{asset['filename']}](assets/{asset['filename']})"
                    )
            lines.append("")
            end_line = len(lines) - 1
            page_map.append(
                {
                    "number": page["number"],
                    "label": page["label"],
                    "markdown_start_line": start_line,
                    "markdown_end_line": end_line,
                    "text_sha256": _sha256(text.encode("utf-8")),
                    "text_chars": len(text),
                    "asset_ids": list(page["asset_ids"]),
                    "extraction_status": page["extraction_status"],
                }
            )
        markdown = ("\n".join(lines).rstrip() + "\n").encode("utf-8")
        return markdown, {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "document_id": document["id"],
            "version_id": version["id"],
            "pages": page_map,
        }

    def _materialize(
        self,
        document: dict[str, Any],
        version: dict[str, Any],
        markdown: bytes,
        page_map: dict[str, Any],
        assets: list[dict[str, Any]],
        warnings: list[str],
    ) -> tuple[DerivedArtifact, dict[str, Any]]:
        page_map_bytes = _json_bytes(page_map)
        public_assets = [
            {key: value for key, value in asset.items() if key != "data"}
            for asset in assets
        ]
        fingerprint_source = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "version_id": version["id"],
            "source_sha256": version["content_hash"],
            "markdown_sha256": _sha256(markdown),
            "page_map_sha256": _sha256(page_map_bytes),
            "assets": [
                {
                    "id": asset["id"],
                    "sha256": asset["sha256"],
                    "size_bytes": asset["size_bytes"],
                }
                for asset in public_assets
            ],
            "warnings": warnings,
        }
        fingerprint = _sha256(_json_bytes(fingerprint_source))
        relative_root = (
            f"state/derived/bundles/{version['id']}/{fingerprint}"
        )
        relative_markdown = f"{relative_root}/document.md"
        relative_page_map = f"{relative_root}/page-map.json"
        for asset in public_assets:
            asset["storage_ref"] = (
                f"{relative_root}/assets/{asset['filename']}"
            )

        manifest = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "generator": BUNDLE_GENERATOR,
            "generator_version": BUNDLE_GENERATOR_VERSION,
            "document_id": document["id"],
            "version_id": version["id"],
            "source_content_sha256": version["content_hash"],
            "media_type": version["media_type"],
            "output_fingerprint": fingerprint,
            "markdown": {
                "storage_ref": relative_markdown,
                "sha256": _sha256(markdown),
                "size_bytes": len(markdown),
            },
            "page_map": {
                "storage_ref": relative_page_map,
                "sha256": _sha256(page_map_bytes),
                "pages": len(page_map["pages"]),
            },
            "assets": public_assets,
            "warnings": warnings,
            "limits": {
                "max_pages": MAX_BUNDLE_PAGES,
                "max_assets": MAX_BUNDLE_ASSETS,
                "max_asset_bytes": MAX_ASSET_BYTES,
                "max_total_asset_bytes": MAX_TOTAL_ASSET_BYTES,
                "max_text_chars": MAX_BUNDLE_TEXT_CHARS,
            },
        }
        manifest_bytes = _json_bytes(manifest)
        relative_manifest = f"{relative_root}/manifest.json"
        final_directory = safe_instance_path(self.store.paths.root, relative_root)
        final_directory.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=".bundle-building-",
                dir=final_directory.parent,
            )
        )
        try:
            (temporary / "assets").mkdir()
            (temporary / "document.md").write_bytes(markdown)
            (temporary / "page-map.json").write_bytes(page_map_bytes)
            for asset in assets:
                (temporary / "assets" / asset["filename"]).write_bytes(
                    asset["data"]
                )
            (temporary / "manifest.json").write_bytes(manifest_bytes)
            if final_directory.exists():
                shutil.rmtree(temporary)
            else:
                try:
                    os.replace(temporary, final_directory)
                except FileExistsError:
                    shutil.rmtree(temporary)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

        artifact = DerivedArtifact(
            id=self._artifact_id(version["id"]),
            version_id=version["id"],
            kind="document_bundle",
            generator=BUNDLE_GENERATOR,
            generator_version=BUNDLE_GENERATOR_VERSION,
            storage_ref=relative_manifest,
            checksum=_sha256(manifest_bytes),
            created_at=utc_now(),
        )
        self.store.write_derived_artifact(artifact)
        self.store.write_derived_provenance(
            provenance_edge(
                "version",
                version["id"],
                "bundled_to",
                "derived_artifact",
                artifact.id,
            )
        )
        return artifact, manifest

    def build_version(
        self,
        version_id: str,
        *,
        parent_operation_id: str | None = None,
    ) -> dict[str, Any]:
        version, document = self._version_and_document(version_id)
        artifact_id = self._artifact_id(version_id)
        operation = self.operations.start(
            "bundle.build",
            f"Build document bundle for {document['title']}",
            summary="Build Markdown, page-map and bounded asset derived state.",
            parent_operation_id=parent_operation_id,
            related={
                "document_id": document["id"],
                "version_id": version_id,
                "artifact_id": artifact_id,
            },
        )
        try:
            _original, data = self._verified_original(version)
            self.operations.append(
                operation.id,
                "bundle.original_verified",
                "Verified the exact Original against the DocumentVersion hash.",
                details={
                    "version_id": version_id,
                    "sha256": version["content_hash"],
                    "size_bytes": len(data),
                },
            )
            is_pdf = (
                version["media_type"] == "application/pdf"
                or Path(document["locator"]).suffix.lower() == ".pdf"
            )
            if is_pdf:
                pages, assets, warnings = self._pdf_pages(data)
            else:
                pages, assets, warnings = self._single_page(document, data)
            markdown, page_map = self._markdown_and_page_map(
                document,
                version,
                pages,
                assets,
            )
            artifact, manifest = self._materialize(
                document,
                version,
                markdown,
                page_map,
                assets,
                warnings,
            )
            self.operations.append(
                operation.id,
                "bundle.committed",
                "Committed a deterministic document bundle.",
                details={
                    "artifact_id": artifact.id,
                    "output_fingerprint": manifest["output_fingerprint"],
                    "pages": len(pages),
                    "assets": len(assets),
                    "warnings": len(warnings),
                },
            )
            status = "completed_with_errors" if warnings else "completed"
            closed = self.operations.close(
                operation.id,
                status=status,
                summary=(
                    f"Built {len(pages)} page entries, {len(assets)} assets and "
                    f"{len(markdown)} Markdown bytes."
                ),
                metrics={
                    "pages": len(pages),
                    "assets": len(assets),
                    "markdown_bytes": len(markdown),
                    "warnings": len(warnings),
                },
            )
            return {
                "artifact": asdict(artifact),
                "manifest": manifest,
                "operation": asdict(closed),
            }
        except Exception as exc:
            current = self.operations.get_record(operation.id)
            if current is not None and current.status == "running":
                self.operations.append(
                    operation.id,
                    "bundle.failed",
                    "Document bundle construction failed.",
                    level="error",
                    details={"error_type": exc.__class__.__name__},
                )
                self.operations.close(
                    operation.id,
                    status="failed",
                    summary="Document bundle construction failed.",
                    error_code="bundle_build_failed",
                    error=exc.__class__.__name__,
                )
            if isinstance(exc, BundleBuildError):
                raise
            raise BundleBuildError(
                f"Document bundle failed ({exc.__class__.__name__})"
            ) from exc

    def build_document(
        self,
        document_id: str,
        *,
        version_id: str | None = None,
        parent_operation_id: str | None = None,
    ) -> dict[str, Any]:
        document = self.store.read_canonical("documents", document_id)
        if document is None:
            raise BundleBuildError(f"Document not found: {document_id}")
        selected = version_id or str(document["current_version_id"])
        version = self.store.read_canonical("versions", selected)
        if version is None or version["document_id"] != document_id:
            raise BundleBuildError(
                f"DocumentVersion does not belong to Document: {selected}"
            )
        return self.build_version(
            selected,
            parent_operation_id=parent_operation_id,
        )

    def build_all(
        self,
        *,
        max_documents: int = DEFAULT_MAX_BUNDLE_DOCUMENTS,
    ) -> dict[str, Any]:
        documents = self.store.list_canonical("documents")
        if len(documents) > max_documents:
            raise BundleBuildError(
                f"Instance exceeds the {max_documents}-document bundle safety limit"
            )
        operation = self.operations.start(
            "bundle.build_all",
            "Build current document bundles",
            summary="Build one deterministic bundle for each current DocumentVersion.",
        )
        results = []
        failures = []
        for document in sorted(documents, key=lambda item: item["id"]):
            try:
                result = self.build_document(
                    document["id"],
                    parent_operation_id=operation.id,
                )
                results.append(result)
                self.operations.append(
                    operation.id,
                    "bundle.child_completed",
                    f"Built a bundle for {document['title']}.",
                    details={
                        "document_id": document["id"],
                        "version_id": document["current_version_id"],
                    },
                )
            except BundleBuildError as exc:
                failures.append(
                    {
                        "document_id": document["id"],
                        "version_id": document["current_version_id"],
                        "error": str(exc)[:2000],
                    }
                )
                self.operations.append(
                    operation.id,
                    "bundle.child_failed",
                    f"Bundle construction failed for {document['title']}.",
                    level="warning",
                    details={
                        "document_id": document["id"],
                        "version_id": document["current_version_id"],
                    },
                )
        if failures and results:
            status = "completed_with_errors"
        elif failures:
            status = "failed"
        else:
            status = "completed"
        closed = self.operations.close(
            operation.id,
            status=status,
            summary=(
                f"Built {len(results)} of {len(documents)} current document bundles."
            ),
            metrics={
                "documents_total": len(documents),
                "bundles_completed": len(results),
                "bundles_failed": len(failures),
            },
        )
        return {
            "operation": asdict(closed),
            "completed": results,
            "failed": failures,
        }

    def _manifest_for_artifact(
        self,
        artifact: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            path = safe_instance_path(
                self.store.paths.root,
                str(artifact["storage_ref"]),
            )
            with path.open("r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION
            or manifest.get("version_id") != artifact.get("version_id")
            or manifest.get("generator") != BUNDLE_GENERATOR
        ):
            return None
        return manifest

    def get(self, version_id: str) -> dict[str, Any] | None:
        artifact = self.store.derived_artifact_for_version(
            version_id,
            "document_bundle",
        )
        if artifact is None:
            return None
        manifest = self._manifest_for_artifact(artifact)
        if manifest is None:
            return None
        return {"artifact": artifact, "manifest": manifest}

    def for_document(self, document_id: str) -> dict[str, Any] | None:
        document = self.store.read_canonical("documents", document_id)
        if document is None:
            return None
        return self.get(str(document["current_version_id"]))

    def list(self, *, limit: int = 500) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        records = []
        for artifact in self.store.list_derived_artifacts():
            if artifact.get("kind") != "document_bundle":
                continue
            manifest = self._manifest_for_artifact(artifact)
            if manifest is None:
                continue
            document = self.store.read_canonical(
                "documents",
                str(manifest["document_id"]),
            )
            records.append(
                {
                    "artifact": artifact,
                    "manifest": manifest,
                    "document": document,
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
        record = self.get(version_id)
        if record is None:
            return None
        try:
            path = safe_instance_path(
                self.store.paths.root,
                record["manifest"]["markdown"]["storage_ref"],
            )
            return path.read_text(encoding="utf-8")
        except (OSError, KeyError, ValueError):
            return None

    def read_page_map(self, version_id: str) -> dict[str, Any] | None:
        record = self.get(version_id)
        if record is None:
            return None
        try:
            path = safe_instance_path(
                self.store.paths.root,
                record["manifest"]["page_map"]["storage_ref"],
            )
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None
