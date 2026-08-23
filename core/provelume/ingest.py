from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from .derived import materialize_extracted_text, provenance_edge
from .domain import Acquisition, Document, DocumentVersion, Source
from .extractors import ExtractionError, extractor_for
from .paths import UnsafePathError, normalise_locator
from .storage import InstanceStore, utc_now

DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_FILES = 1000


class IngestionLimitError(RuntimeError):
    pass


def _stable_version_id(document_id: str, digest: str) -> str:
    return f"ver_{uuid5(NAMESPACE_URL, f'provelume:{document_id}:{digest}').hex}"


def _iter_files(source: Path, max_files: int) -> list[tuple[str, Path]]:
    source = source.expanduser().resolve(strict=True)
    if source.is_file():
        root = source.parent
        candidates = [source]
    else:
        root = source
        candidates = sorted(path for path in source.rglob("*") if path.is_file())
    accepted: list[tuple[str, Path]] = []
    for candidate in candidates:
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise UnsafePathError(f"symlink escapes source root: {candidate}") from exc
        locator = normalise_locator(relative.as_posix())
        if extractor_for(resolved) is None:
            continue
        accepted.append((locator, resolved))
        if len(accepted) > max_files:
            raise IngestionLimitError(f"source exceeds the {max_files}-file safety limit")
    return accepted


def ingest_filesystem(
    store: InstanceStore,
    source_path: Path | str,
    *,
    source_name: str | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> list[Acquisition]:
    canonical_source_path = Path(source_path).expanduser().resolve(strict=True)
    files = _iter_files(canonical_source_path, max_files)
    source_id = store.find_source_for_path(canonical_source_path)
    if source_id is None:
        source_id = f"src_{uuid4().hex}"
        source = Source(
            id=source_id,
            kind="filesystem",
            name=source_name or canonical_source_path.name,
            created_at=utc_now(),
        )
        store.write_source(source)
        store.register_source_path(source_id, canonical_source_path, name=source.name)

    return [
        _ingest_one(store, source_id, locator, path, max_file_bytes)
        for locator, path in files
    ]


def _ingest_one(
    store: InstanceStore,
    source_id: str,
    locator: str,
    path: Path,
    max_file_bytes: int,
) -> Acquisition:
    observed_at = utc_now()
    size = path.stat().st_size
    if size > max_file_bytes:
        raise IngestionLimitError(f"{locator} exceeds the {max_file_bytes}-byte safety limit")

    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    original = store.store_original_bytes(data)
    existing = store.find_document(source_id, locator)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    if existing is None:
        document_id = f"doc_{uuid4().hex}"
        sequence = 1
    else:
        document_id = existing["id"]
        versions = store.versions_for_document(document_id)
        current = next(
            item for item in versions if item["id"] == existing["current_version_id"]
        )
        if current["content_hash"] == digest:
            acquisition = Acquisition(
                id=f"acq_{uuid4().hex}",
                source_id=source_id,
                locator=locator,
                observed_at=observed_at,
                content_hash=digest,
                outcome="unchanged",
                document_id=document_id,
                version_id=current["id"],
            )
            store.write_acquisition(acquisition)
            store.write_provenance(
                provenance_edge(
                    "source",
                    source_id,
                    "observed",
                    "acquisition",
                    acquisition.id,
                )
            )
            store.write_provenance(
                provenance_edge(
                    "acquisition",
                    acquisition.id,
                    "matched",
                    "version",
                    current["id"],
                )
            )
            return acquisition
        sequence = max(int(item["sequence"]) for item in versions) + 1

    version_id = _stable_version_id(document_id, digest)
    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        sequence=sequence,
        content_hash=digest,
        original_id=original.id,
        media_type=media_type,
        size_bytes=len(data),
        acquired_at=observed_at,
    )
    store.write_version(version)

    if existing is None:
        document = Document(
            id=document_id,
            source_id=source_id,
            locator=locator,
            title=path.name,
            media_type=media_type,
            created_at=observed_at,
            current_version_id=version_id,
        )
    else:
        document = replace(
            Document(**existing), current_version_id=version_id, media_type=media_type
        )
    store.write_document(document)

    acquisition = Acquisition(
        id=f"acq_{uuid4().hex}",
        source_id=source_id,
        locator=locator,
        observed_at=observed_at,
        content_hash=digest,
        outcome="created" if sequence == 1 else "version_created",
        document_id=document_id,
        version_id=version_id,
    )

    extractor = extractor_for(path)
    extraction_error: str | None = None
    try:
        assert extractor is not None
        extraction = extractor.extract(data)
        materialize_extracted_text(store, version_id, extraction)
    except ExtractionError as exc:
        extraction_error = str(exc)

    if extraction_error:
        acquisition = replace(acquisition, outcome="extraction_failed", error=extraction_error)
    store.write_acquisition(acquisition)
    store.write_provenance(
        provenance_edge(
            "source",
            source_id,
            "observed",
            "acquisition",
            acquisition.id,
        )
    )
    store.write_provenance(
        provenance_edge(
            "acquisition",
            acquisition.id,
            "captured",
            "original",
            original.id,
        )
    )
    store.write_provenance(
        provenance_edge(
            "original",
            original.id,
            "materialized_as",
            "version",
            version_id,
        )
    )
    store.write_provenance(
        provenance_edge(
            "version",
            version_id,
            "version_of",
            "document",
            document_id,
        )
    )
    return acquisition
