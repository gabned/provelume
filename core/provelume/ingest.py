from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from .derived import materialize_extracted_text, provenance_edge
from .domain import Acquisition, Document, DocumentVersion, Source
from .extractors import ExtractionError, extractor_for
from .ingestion_runs import (
    INGESTION_RUN_SCHEMA_VERSION,
    IngestionItemRecord,
    IngestionLedger,
    IngestionRunRecord,
)
from .paths import UnsafePathError, normalise_locator
from .storage import InstanceStore, utc_now

DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_FILES = 1000
MAX_LEDGER_ERROR_CHARS = 2000


class IngestionLimitError(RuntimeError):
    pass


class IngestionInputError(RuntimeError):
    pass


class IngestionRetryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IngestionRunResult:
    run: IngestionRunRecord
    items: tuple[IngestionItemRecord, ...]
    acquisitions: tuple[Acquisition, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "run": asdict(self.run),
            "items": [asdict(item) for item in self.items],
            "acquisitions": [asdict(item) for item in self.acquisitions],
        }


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


def _ensure_source(
    store: InstanceStore,
    canonical_source_path: Path,
    source_name: str | None,
) -> str:
    source_id = store.find_source_for_path(canonical_source_path)
    if source_id is not None:
        return source_id
    source_id = f"src_{uuid4().hex}"
    source = Source(
        id=source_id,
        kind="filesystem",
        name=source_name or canonical_source_path.name,
        created_at=utc_now(),
    )
    store.write_source(source)
    store.register_source_path(source_id, canonical_source_path, name=source.name)
    return source_id


def _new_run(
    ledger: IngestionLedger,
    *,
    source_id: str,
    max_file_bytes: int,
    max_files: int,
    retry_of_run_id: str | None = None,
) -> IngestionRunRecord:
    return IngestionRunRecord(
        schema_version=INGESTION_RUN_SCHEMA_VERSION,
        id=ledger.new_run_id(),
        source_id=source_id,
        started_at=utc_now(),
        completed_at=None,
        status="running",
        item_count=0,
        completed_items=0,
        failed_items=0,
        max_file_bytes=max_file_bytes,
        max_files=max_files,
        retry_of_run_id=retry_of_run_id,
    )


def _new_item(
    ledger: IngestionLedger,
    *,
    run_id: str,
    source_id: str,
    locator: str,
    attempt: int = 1,
    retry_of_item_id: str | None = None,
) -> IngestionItemRecord:
    return IngestionItemRecord(
        schema_version=INGESTION_RUN_SCHEMA_VERSION,
        id=ledger.new_item_id(),
        run_id=run_id,
        source_id=source_id,
        locator=locator,
        status="pending",
        attempt=attempt,
        created_at=utc_now(),
        retry_of_item_id=retry_of_item_id,
    )


def _bounded_error(error: BaseException | str) -> str:
    message = str(error).strip() or error.__class__.__name__
    return message[:MAX_LEDGER_ERROR_CHARS]


def _item_error(error: BaseException, locator: str) -> str:
    if isinstance(error, IngestionLimitError):
        return _bounded_error(error)
    if isinstance(error, UnsafePathError):
        return f"unsafe source locator: {locator}"
    if isinstance(error, FileNotFoundError):
        return f"{locator} is no longer available"
    if isinstance(error, PermissionError):
        return f"{locator} is not readable"
    if isinstance(error, IngestionInputError):
        return _bounded_error(error)
    if isinstance(error, OSError):
        return f"{locator} could not be read ({error.__class__.__name__})"
    return _bounded_error(error)


def _run_error(error: BaseException) -> str:
    if isinstance(error, IngestionLimitError):
        return _bounded_error(error)
    if isinstance(error, UnsafePathError):
        return "source contains a path that escapes its configured root"
    if isinstance(error, OSError):
        return f"configured source could not be enumerated ({error.__class__.__name__})"
    return _bounded_error(error)


def _error_code(error: BaseException) -> str:
    if isinstance(error, IngestionLimitError):
        if "byte safety limit" in str(error):
            return "file_too_large"
        return "ingestion_limit"
    if isinstance(error, UnsafePathError):
        return "unsafe_path"
    if isinstance(error, FileNotFoundError):
        return "input_missing"
    if isinstance(error, PermissionError):
        return "input_unreadable"
    if isinstance(error, IngestionInputError):
        return "input_unsupported"
    if isinstance(error, OSError):
        return "input_io_error"
    return "ingestion_failed"


def _close_run(
    ledger: IngestionLedger,
    run: IngestionRunRecord,
    items: list[IngestionItemRecord],
    *,
    error_code: str | None = None,
    error: str | None = None,
) -> IngestionRunRecord:
    completed_items = sum(item.status == "completed" for item in items)
    failed_items = sum(item.status == "failed" for item in items)
    if error_code is not None or (failed_items and not completed_items):
        status = "failed"
    elif failed_items:
        status = "completed_with_errors"
    else:
        status = "completed"
    closed = replace(
        run,
        completed_at=utc_now(),
        status=status,
        item_count=len(items),
        completed_items=completed_items,
        failed_items=failed_items,
        error_code=error_code,
        error=error,
    )
    ledger.write_run(closed)
    return closed


def _process_item(
    store: InstanceStore,
    ledger: IngestionLedger,
    item: IngestionItemRecord,
    path_resolver: Callable[[], Path],
    *,
    max_file_bytes: int,
    retry_extraction: bool,
) -> tuple[IngestionItemRecord, Acquisition | None]:
    running = replace(item, status="running", started_at=utc_now())
    ledger.write_item(running)
    try:
        path = path_resolver()
        acquisition = _ingest_one(
            store,
            item.source_id,
            item.locator,
            path,
            max_file_bytes,
            retry_extraction=retry_extraction,
        )
    except (IngestionInputError, IngestionLimitError, OSError, UnsafePathError) as exc:
        failed = replace(
            running,
            status="failed",
            completed_at=utc_now(),
            error_code=_error_code(exc),
            error=_item_error(exc, item.locator),
        )
        ledger.write_item(failed)
        return failed, None

    if acquisition.outcome == "extraction_failed":
        finished = replace(
            running,
            status="failed",
            completed_at=utc_now(),
            acquisition_id=acquisition.id,
            outcome=acquisition.outcome,
            error_code="extraction_failed",
            error=_bounded_error(acquisition.error or "text extraction failed"),
        )
    else:
        finished = replace(
            running,
            status="completed",
            completed_at=utc_now(),
            acquisition_id=acquisition.id,
            outcome=acquisition.outcome,
        )
    ledger.write_item(finished)
    return finished, acquisition


def run_ingestion_filesystem(
    store: InstanceStore,
    source_path: Path | str,
    *,
    source_name: str | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> IngestionRunResult:
    canonical_source_path = Path(source_path).expanduser().resolve(strict=True)
    source_id = _ensure_source(store, canonical_source_path, source_name)
    ledger = IngestionLedger(store)
    run = _new_run(
        ledger,
        source_id=source_id,
        max_file_bytes=max_file_bytes,
        max_files=max_files,
    )
    ledger.write_run(run)

    try:
        files = _iter_files(canonical_source_path, max_files)
    except (IngestionLimitError, OSError, UnsafePathError) as exc:
        closed = _close_run(
            ledger,
            run,
            [],
            error_code=_error_code(exc),
            error=_run_error(exc),
        )
        return IngestionRunResult(run=closed, items=(), acquisitions=())

    items = [
        _new_item(
            ledger,
            run_id=run.id,
            source_id=source_id,
            locator=locator,
        )
        for locator, _path in files
    ]
    run = replace(run, item_count=len(items))
    ledger.write_run(run)
    for item in items:
        ledger.write_item(item)

    finished_items: list[IngestionItemRecord] = []
    acquisitions: list[Acquisition] = []
    for item, (_locator, path) in zip(items, files, strict=True):
        finished, acquisition = _process_item(
            store,
            ledger,
            item,
            lambda selected=path: selected,
            max_file_bytes=max_file_bytes,
            retry_extraction=False,
        )
        finished_items.append(finished)
        if acquisition is not None:
            acquisitions.append(acquisition)

    closed = _close_run(ledger, run, finished_items)
    return IngestionRunResult(
        run=closed,
        items=tuple(finished_items),
        acquisitions=tuple(acquisitions),
    )


def _safe_retry_path(source_path: Path, locator: str) -> Path:
    configured = source_path.expanduser().resolve(strict=True)
    root = configured.parent if configured.is_file() else configured
    candidate = (root / normalise_locator(locator)).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(f"retry item escapes source root: {locator}") from exc
    if configured.is_file() and candidate != configured:
        raise UnsafePathError(f"retry item does not match configured file Source: {locator}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    if extractor_for(candidate) is None:
        raise IngestionInputError(f"retry item is no longer a supported file: {locator}")
    return candidate


def retry_ingestion_run(store: InstanceStore, run_id: str) -> IngestionRunResult:
    ledger = IngestionLedger(store)
    previous = ledger.get_run(run_id)
    if previous is None:
        raise IngestionRetryError(f"ingestion run not found: {run_id}")
    previous_items = ledger.items_for_run(run_id)
    retryable = [item for item in previous_items if item.get("status") != "completed"]
    if not retryable:
        raise IngestionRetryError(f"ingestion run has no failed or interrupted items: {run_id}")

    source_id = str(previous["source_id"])
    source_path = store.source_path(source_id)
    if source_path is None:
        raise IngestionRetryError(f"ingestion Source is not configured: {source_id}")
    max_file_bytes = int(previous["max_file_bytes"])
    max_files = int(previous["max_files"])
    run = _new_run(
        ledger,
        source_id=source_id,
        max_file_bytes=max_file_bytes,
        max_files=max_files,
        retry_of_run_id=run_id,
    )
    items = [
        _new_item(
            ledger,
            run_id=run.id,
            source_id=source_id,
            locator=str(previous_item["locator"]),
            attempt=int(previous_item.get("attempt", 1)) + 1,
            retry_of_item_id=str(previous_item["id"]),
        )
        for previous_item in retryable
    ]
    run = replace(run, item_count=len(items))
    ledger.write_run(run)
    for item in items:
        ledger.write_item(item)

    finished_items: list[IngestionItemRecord] = []
    acquisitions: list[Acquisition] = []
    for item, previous_item in zip(items, retryable, strict=True):
        finished, acquisition = _process_item(
            store,
            ledger,
            item,
            lambda locator=item.locator: _safe_retry_path(source_path, locator),
            max_file_bytes=max_file_bytes,
            retry_extraction=previous_item.get("outcome") == "extraction_failed",
        )
        finished_items.append(finished)
        if acquisition is not None:
            acquisitions.append(acquisition)

    closed = _close_run(ledger, run, finished_items)
    return IngestionRunResult(
        run=closed,
        items=tuple(finished_items),
        acquisitions=tuple(acquisitions),
    )


def ingest_filesystem(
    store: InstanceStore,
    source_path: Path | str,
    *,
    source_name: str | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> list[Acquisition]:
    return list(
        run_ingestion_filesystem(
            store,
            source_path,
            source_name=source_name,
            max_file_bytes=max_file_bytes,
            max_files=max_files,
        ).acquisitions
    )


def _ingest_one(
    store: InstanceStore,
    source_id: str,
    locator: str,
    path: Path,
    max_file_bytes: int,
    *,
    retry_extraction: bool = False,
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
            outcome = "unchanged"
            extraction_error: str | None = None
            if retry_extraction:
                artifact = store.derived_artifact_for_version(current["id"])
                if artifact is not None:
                    outcome = "extraction_already_recovered"
                else:
                    extractor = extractor_for(path)
                    if extractor is None:
                        raise IngestionInputError(
                            f"retry item is no longer a supported file: {locator}"
                        )
                    try:
                        extraction = extractor.extract(data)
                        materialize_extracted_text(store, current["id"], extraction)
                        outcome = "extraction_recovered"
                    except ExtractionError as exc:
                        outcome = "extraction_failed"
                        extraction_error = str(exc)
            acquisition = Acquisition(
                id=f"acq_{uuid4().hex}",
                source_id=source_id,
                locator=locator,
                observed_at=observed_at,
                content_hash=digest,
                outcome=outcome,
                document_id=document_id,
                version_id=current["id"],
                error=extraction_error,
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
