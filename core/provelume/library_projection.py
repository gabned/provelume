from __future__ import annotations

import json
import os
import posixpath
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any

from .instance_validation import inspect_instance
from .library_projection_model import (
    _DOCUMENT_ID,
    _SHA256,
    DEFAULT_MAX_LIBRARY_DOCUMENTS,
    LIBRARY_GENERATOR,
    LIBRARY_GENERATOR_VERSION,
    LIBRARY_MANIFEST,
    LIBRARY_PROJECTION_SCHEMA_VERSION,
    LIBRARY_REBUILD_LOCK,
    MAX_LIBRARY_FILE_BYTES,
    MAX_LIBRARY_FILES,
    MAX_LIBRARY_MANIFEST_BYTES,
    LibraryLayoutBuilder,
    LibraryProjectionError,
    LibraryProjectionLimitError,
    _json_bytes,
    _sha256,
)
from .locks import InstanceLockLease, InstanceLockManager
from .markdown_viewer import (
    MAX_VIEWER_MARKDOWN_CHARS,
    DocumentContentError,
    DocumentContentReader,
)
from .paths import normalise_locator
from .storage import InstanceStore


def _unsafe_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


class LibraryProjectionManager:
    """Build and validate a deterministic human-readable filesystem projection."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.library
        self.staging_root = store.paths.state / "locks"
        self.content = DocumentContentReader(store)

    def _document_bytes(
        self,
        document: dict[str, Any],
        classification: dict[str, Any] | None,
        path: PurePosixPath,
    ) -> bytes:
        document_id = str(document["id"])
        content = self.content.get(
            document_id,
            max_chars=MAX_VIEWER_MARKDOWN_CHARS,
            build_missing_bundle=True,
        )
        if content is None:
            raise LibraryProjectionError(f"Document not found: {document_id}")
        if content["markdown_truncated"]:
            raise LibraryProjectionLimitError(
                f"Document Markdown exceeds {MAX_VIEWER_MARKDOWN_CHARS} characters: "
                f"{document_id}"
            )
        body = content["markdown"] or "_No readable Markdown representation is available._\n"
        bundle = content.get("bundle")
        if isinstance(bundle, dict):
            for asset in bundle.get("manifest", {}).get("assets", []):
                if not isinstance(asset, dict):
                    continue
                filename = str(asset.get("filename", ""))
                reference = str(asset.get("storage_ref", ""))
                if not filename or not reference:
                    continue
                target = PurePosixPath(
                    posixpath.relpath(
                        reference,
                        start=(PurePosixPath("library") / path).parent.as_posix(),
                    )
                )
                body = body.replace(f"(assets/{filename})", f"({target.as_posix()})")

        original_ref = PurePosixPath(str(content["original"]["storage_ref"]))
        original_link = posixpath.relpath(
            original_ref.as_posix(),
            start=(PurePosixPath("library") / path).parent.as_posix(),
        )
        primary_id = (
            json.dumps(str(classification["primary_node_id"]))
            if classification
            else "null"
        )
        secondary = (
            json.dumps(
                [str(item) for item in classification["secondary_node_ids"]],
                ensure_ascii=False,
            )
            if classification
            else "[]"
        )
        metadata = [
            "---",
            f"provelume_projection_schema: {LIBRARY_PROJECTION_SCHEMA_VERSION}",
            "provelume_projection_is_canonical: false",
            f"provelume_document_id: {json.dumps(document_id)}",
            f"provelume_version_id: {json.dumps(content['version_id'])}",
            f"provelume_source_id: {json.dumps(str(document['source_id']))}",
            f"provelume_primary_node_id: {primary_id}",
            f"provelume_secondary_node_ids: {secondary}",
            f"provelume_original_sha256: {json.dumps(content['original']['sha256'])}",
            "---",
            "",
            (
                "> Generated derived projection. Canonical JSON and the preserved "
                "Original remain authoritative."
            ),
            "",
            f"[Preserved Original]({original_link})",
            "",
        ]
        return ("\n".join(metadata) + body.lstrip("\ufeff")).encode("utf-8")

    def _build_files(
        self,
    ) -> tuple[dict[PurePosixPath, bytes], dict[str, PurePosixPath]]:
        documents, classifications, document_paths, files = LibraryLayoutBuilder(
            self.store
        ).build()
        for document in documents:
            document_id = str(document["id"])
            files[document_paths[document_id]] = self._document_bytes(
                document,
                classifications.get(document_id),
                document_paths[document_id],
            )
        if len(files) > MAX_LIBRARY_FILES:
            raise LibraryProjectionLimitError(
                f"library projection exceeds the {MAX_LIBRARY_FILES}-file safety limit"
            )
        oversized = [
            path for path, data in files.items() if len(data) > MAX_LIBRARY_FILE_BYTES
        ]
        if oversized:
            raise LibraryProjectionLimitError(
                f"library file exceeds the {MAX_LIBRARY_FILE_BYTES}-byte safety limit: "
                f"{oversized[0].as_posix()}"
            )
        return files, document_paths

    @staticmethod
    def _content_manifest(
        files: dict[PurePosixPath, bytes],
        document_paths: dict[str, PurePosixPath],
        *,
        canonical_fingerprint: str,
    ) -> dict[str, Any]:
        entries = [
            {
                "path": path.as_posix(),
                "sha256": _sha256(data),
                "size_bytes": len(data),
            }
            for path, data in sorted(files.items(), key=lambda item: item[0].as_posix())
        ]
        rows = [
            f"{item['path']}:{item['sha256']}:{item['size_bytes']}" for item in entries
        ]
        return {
            "schema_version": LIBRARY_PROJECTION_SCHEMA_VERSION,
            "generator": LIBRARY_GENERATOR,
            "generator_version": LIBRARY_GENERATOR_VERSION,
            "canonical_fingerprint": canonical_fingerprint,
            "content_fingerprint": _sha256("\n".join(rows).encode("utf-8")),
            "documents": len(document_paths),
            "primary_paths": {
                document_id: path.as_posix()
                for document_id, path in sorted(document_paths.items())
            },
            "files": entries,
            "network_used": False,
            "ai_used": False,
        }

    @staticmethod
    def _write_staging(
        staging: Path,
        files: dict[PurePosixPath, bytes],
        manifest: dict[str, Any],
    ) -> None:
        for relative, data in files.items():
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (staging / LIBRARY_MANIFEST).write_bytes(_json_bytes(manifest))

    def _commit_staging(self, staging: Path) -> Path | None:
        target = self.root
        if _unsafe_link(target) or (target.exists() and not target.is_dir()):
            raise LibraryProjectionError("library projection path is not a safe directory")
        previous: Path | None = None
        if target.exists():
            previous = self.staging_root / (
                f".library-previous-{os.getpid()}-{id(staging)}"
            )
            os.replace(target, previous)
        try:
            os.replace(staging, target)
        except Exception as exc:
            if previous is not None and previous.exists() and not target.exists():
                try:
                    os.replace(previous, target)
                except OSError as rollback_exc:
                    raise LibraryProjectionError(
                        "library replacement failed and the previous projection could "
                        "not be restored"
                    ) from rollback_exc
            raise LibraryProjectionError("library staged replacement failed") from exc
        return previous

    def _restore_previous(self, staging: Path, previous: Path | None) -> None:
        """Put the pre-commit projection back without discarding either tree."""

        target = self.root
        try:
            if target.exists():
                os.replace(target, staging)
            if previous is not None:
                os.replace(previous, target)
        except OSError as exc:
            if not target.exists() and staging.exists():
                with suppress(OSError):
                    os.replace(staging, target)
            raise LibraryProjectionError(
                "library post-commit validation failed and rollback could not finish"
            ) from exc

    @staticmethod
    def _deep_fingerprint(store: InstanceStore) -> str:
        validation = inspect_instance(store.paths.root, deep=True)
        fingerprint = validation.get("content_fingerprint")
        if validation.get("status") != "valid" or not isinstance(fingerprint, str):
            raise LibraryProjectionError(
                "Instance deep validation failed before library projection"
            )
        return fingerprint

    def rebuild(
        self,
        *,
        max_documents: int = DEFAULT_MAX_LIBRARY_DOCUMENTS,
        lock_held: bool = False,
    ) -> dict[str, Any]:
        if max_documents < 1:
            raise ValueError("max_documents must be positive")
        documents = self.store.list_canonical("documents")
        if len(documents) > max_documents:
            raise LibraryProjectionLimitError(
                f"Instance exceeds the {max_documents}-document library safety limit"
            )
        lease: InstanceLockLease | None = None
        if not lock_held:
            lease = InstanceLockManager(self.store).acquire(
                LIBRARY_REBUILD_LOCK,
                purpose="Markdown library rebuild",
            )
        staging: Path | None = None
        previous: Path | None = None
        try:
            canonical_before = self._deep_fingerprint(self.store)
            self.staging_root.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(
                    prefix=".library-building-",
                    dir=self.staging_root,
                )
            )
            files, document_paths = self._build_files()
            manifest = self._content_manifest(
                files,
                document_paths,
                canonical_fingerprint=canonical_before,
            )
            self._write_staging(staging, files, manifest)
            staged_status = self._status(staging)
            if staged_status["status"] != "ready":
                raise LibraryProjectionError(
                    "staged library projection failed validation before commit"
                )
            if self._deep_fingerprint(self.store) != canonical_before:
                raise LibraryProjectionError(
                    "canonical state changed while the library projection was staged"
                )
            previous = self._commit_staging(staging)
            try:
                canonical_after = self._deep_fingerprint(self.store)
                if canonical_after != canonical_before:
                    raise LibraryProjectionError(
                        "canonical state changed while the library projection was committed"
                    )
                status = self.status()
                if status["status"] != "ready":
                    raise LibraryProjectionError(
                        "committed library projection failed validation"
                    )
            except Exception:
                try:
                    self._restore_previous(staging, previous)
                except LibraryProjectionError:
                    staging = None
                    raise
                previous = None
                raise
            if previous is not None and previous.exists():
                shutil.rmtree(previous)
                previous = None
            return {
                "schema_version": LIBRARY_PROJECTION_SCHEMA_VERSION,
                "status": "completed",
                "canonical_before": canonical_before,
                "canonical_after": canonical_after,
                "canonical_mutation": "none",
                "content_fingerprint": manifest["content_fingerprint"],
                "documents": manifest["documents"],
                "files": len(manifest["files"]),
                "primary_paths": dict(manifest["primary_paths"]),
                "network_used": False,
                "ai_used": False,
            }
        except (DocumentContentError, OSError, ValueError) as exc:
            raise LibraryProjectionError(str(exc)) from exc
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging)
            if lease is not None:
                InstanceLockManager(self.store).release(lease)

    def status(self) -> dict[str, Any]:
        return self._status(self.root)

    @staticmethod
    def _manifest_status(
        value: dict[str, Any],
        status: str,
        reason: str,
    ) -> dict[str, Any]:
        """Return bounded status metadata without echoing a hostile manifest."""

        return {
            "schema_version": LIBRARY_PROJECTION_SCHEMA_VERSION,
            "status": status,
            "reason": reason,
            "canonical_fingerprint": value["canonical_fingerprint"],
            "content_fingerprint": value["content_fingerprint"],
            "documents": value["documents"],
            "files": len(value["files"]),
            "network_used": False,
            "ai_used": False,
        }

    def _status(self, root: Path) -> dict[str, Any]:
        if _unsafe_link(root):
            return {
                "schema_version": LIBRARY_PROJECTION_SCHEMA_VERSION,
                "status": "invalid",
                "reason": "library_path_invalid",
                "documents": 0,
                "files": 0,
                "content_fingerprint": None,
            }
        if not root.exists():
            return {
                "schema_version": LIBRARY_PROJECTION_SCHEMA_VERSION,
                "status": "missing",
                "documents": 0,
                "files": 0,
                "content_fingerprint": None,
            }
        if not root.is_dir():
            return {
                "schema_version": LIBRARY_PROJECTION_SCHEMA_VERSION,
                "status": "invalid",
                "reason": "library_path_invalid",
                "documents": 0,
                "files": 0,
                "content_fingerprint": None,
            }
        manifest_path = root / LIBRARY_MANIFEST
        try:
            if (
                _unsafe_link(manifest_path)
                or not manifest_path.is_file()
                or manifest_path.stat().st_size > MAX_LIBRARY_MANIFEST_BYTES
            ):
                raise ValueError("manifest too large")
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return {
                "schema_version": LIBRARY_PROJECTION_SCHEMA_VERSION,
                "status": "invalid",
                "reason": "manifest_invalid",
                "documents": 0,
                "files": 0,
                "content_fingerprint": None,
            }
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "schema_version",
                "generator",
                "generator_version",
                "canonical_fingerprint",
                "content_fingerprint",
                "documents",
                "primary_paths",
                "files",
                "network_used",
                "ai_used",
            }
            or value.get("schema_version") != LIBRARY_PROJECTION_SCHEMA_VERSION
            or value.get("generator") != LIBRARY_GENERATOR
            or value.get("generator_version") != LIBRARY_GENERATOR_VERSION
            or value.get("network_used") is not False
            or value.get("ai_used") is not False
            or not isinstance(value.get("files"), list)
            or not isinstance(value.get("primary_paths"), dict)
            or not isinstance(value.get("documents"), int)
            or isinstance(value.get("documents"), bool)
            or value["documents"] < 0
            or value["documents"] > DEFAULT_MAX_LIBRARY_DOCUMENTS
            or len(value["primary_paths"]) != value["documents"]
            or _SHA256.fullmatch(str(value.get("canonical_fingerprint", ""))) is None
            or _SHA256.fullmatch(str(value.get("content_fingerprint", ""))) is None
            or len(value["files"]) > MAX_LIBRARY_FILES
        ):
            return {
                "schema_version": LIBRARY_PROJECTION_SCHEMA_VERSION,
                "status": "invalid",
                "reason": "manifest_contract_invalid",
                "documents": 0,
                "files": 0,
                "content_fingerprint": None,
            }
        actual_paths: set[str] = set()
        for path in root.rglob("*"):
            if _unsafe_link(path):
                return self._manifest_status(value, "modified", "symlink_present")
            if path.is_file():
                actual_paths.add(path.relative_to(root).as_posix())
                if len(actual_paths) > MAX_LIBRARY_FILES + 1:
                    return self._manifest_status(
                        value,
                        "modified",
                        "file_limit_exceeded",
                    )
        rows: list[str] = []
        entry_paths: list[str] = []
        expected_paths = {LIBRARY_MANIFEST}
        for item in value["files"]:
            if not isinstance(item, dict) or set(item) != {
                "path",
                "sha256",
                "size_bytes",
            }:
                return self._manifest_status(value, "invalid", "file_entry_invalid")
            if (
                not isinstance(item["path"], str)
                or not isinstance(item["sha256"], str)
                or _SHA256.fullmatch(item["sha256"]) is None
                or not isinstance(item["size_bytes"], int)
                or isinstance(item["size_bytes"], bool)
                or item["size_bytes"] < 0
                or item["size_bytes"] > MAX_LIBRARY_FILE_BYTES
            ):
                return self._manifest_status(value, "invalid", "file_entry_invalid")
            try:
                relative = normalise_locator(item["path"])
            except ValueError:
                return self._manifest_status(value, "invalid", "file_path_invalid")
            if relative != item["path"]:
                return self._manifest_status(value, "invalid", "file_path_invalid")
            if relative in expected_paths:
                return self._manifest_status(value, "invalid", "file_path_duplicate")
            expected_paths.add(relative)
            entry_paths.append(relative)
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                if _unsafe_link(path) or not path.is_file():
                    raise OSError
                if path.stat().st_size != item["size_bytes"]:
                    return self._manifest_status(value, "modified", "file_changed")
                data = path.read_bytes()
            except OSError:
                return self._manifest_status(value, "modified", "file_missing")
            if _sha256(data) != item.get("sha256") or len(data) != item.get(
                "size_bytes"
            ):
                return self._manifest_status(value, "modified", "file_changed")
            rows.append(f"{relative}:{item['sha256']}:{item['size_bytes']}")
        if entry_paths != sorted(entry_paths):
            return self._manifest_status(value, "invalid", "file_order_invalid")
        document_ids = {
            str(item["id"]) for item in self.store.list_canonical("documents")
        }
        if set(value["primary_paths"]) != document_ids:
            return self._manifest_status(value, "invalid", "primary_identity_invalid")
        primary_values: set[str] = set()
        for document_id, relative in value["primary_paths"].items():
            if (
                _DOCUMENT_ID.fullmatch(document_id) is None
                or not isinstance(relative, str)
            ):
                return self._manifest_status(value, "invalid", "primary_path_invalid")
            try:
                normalized = normalise_locator(relative)
            except ValueError:
                return self._manifest_status(value, "invalid", "primary_path_invalid")
            if (
                normalized != relative
                or relative not in expected_paths
                or not relative.endswith(".md")
                or relative.endswith("/README.md")
                or relative == "README.md"
                or relative in primary_values
            ):
                return self._manifest_status(value, "invalid", "primary_path_invalid")
            primary_values.add(relative)
        if actual_paths != expected_paths:
            return self._manifest_status(value, "modified", "unexpected_files")
        fingerprint = _sha256("\n".join(rows).encode("utf-8"))
        if fingerprint != value.get("content_fingerprint"):
            return self._manifest_status(value, "modified", "fingerprint_changed")
        try:
            canonical = self._deep_fingerprint(self.store)
        except LibraryProjectionError:
            return self._manifest_status(value, "invalid", "canonical_invalid")
        if canonical != value.get("canonical_fingerprint"):
            return self._manifest_status(value, "stale", "canonical_changed")
        return {
            **value,
            "status": "ready",
            "files": len(value["files"]),
        }
