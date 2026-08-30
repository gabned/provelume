from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from .derived import materialize_extracted_text, provenance_edge
from .domain import Acquisition, Document, DocumentVersion, Original, Source
from .extractors import ExtractionError, extractor_for
from .index import refresh_search_index
from .ingestion_runs import (
    INGESTION_RUN_SCHEMA_VERSION,
    IngestionItemRecord,
    IngestionLedger,
    IngestionRunRecord,
)
from .instance_lifecycle import InstanceLifecycleManager
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


def _refresh_after_ingestion(
    store: InstanceStore,
    result: IngestionRunResult,
) -> None:
    refresh_search_index(
        store,
        (
            acquisition.document_id
            for acquisition in result.acquisitions
            if acquisition.outcome != "unchanged"
        ),
        recover_missing_derived=False,
    )


def _stable_document_id(source_id: str, locator: str) -> str:
    value = f"provelume:document:{source_id}:{normalise_locator(locator)}"
    return f"doc_{uuid5(NAMESPACE_URL, value).hex}"


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


def _source_for_run(
    store: InstanceStore,
    source_path: Path | str,
    source_name: str | None,
) -> tuple[str, Path]:
    requested = Path(source_path).expanduser()
    source_id = store.find_source_for_path(requested)
    if source_id is not None:
        return source_id, store.source_path(source_id) or requested
    canonical = requested.resolve(strict=True)
    return _ensure_source(store, canonical, source_name), canonical


def _new_run(
    ledger: IngestionLedger,
    *,
    source_id: str,
    max_file_bytes: int,
    max_files: int,
    retry_of_run_id: str | None = None,
    record_id: str | None = None,
) -> IngestionRunRecord:
    return IngestionRunRecord(
        schema_version=INGESTION_RUN_SCHEMA_VERSION,
        id=record_id or ledger.new_run_id(),
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
    record_id: str | None = None,
) -> IngestionItemRecord:
    return IngestionItemRecord(
        schema_version=INGESTION_RUN_SCHEMA_VERSION,
        id=record_id or ledger.new_item_id(),
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
    acquisition_id: str | None = None,
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
            acquisition_id=acquisition_id,
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


def _reconcile_committed_acquisition(
    store: InstanceStore,
    ledger: IngestionLedger,
    item: IngestionItemRecord,
    acquisition_id: str,
) -> tuple[IngestionItemRecord, Acquisition] | None:
    """Finish an interrupted item from its already-canonical Acquisition."""

    record = store.read_canonical("acquisitions", acquisition_id)
    if record is None:
        return None
    acquisition = Acquisition(**record)
    if acquisition.source_id != item.source_id or acquisition.locator != item.locator:
        raise IngestionInputError(
            "deterministic Acquisition identity belongs to another ingestion item"
        )
    extraction_failed = acquisition.outcome == "extraction_failed"
    finished = replace(
        item,
        status="failed" if extraction_failed else "completed",
        started_at=item.started_at or acquisition.observed_at,
        completed_at=acquisition.observed_at,
        acquisition_id=acquisition.id,
        outcome=acquisition.outcome,
        error_code="extraction_failed" if extraction_failed else None,
        error=(
            _bounded_error(acquisition.error or "text extraction failed")
            if extraction_failed
            else None
        ),
    )
    ledger.write_item(finished)
    return finished, acquisition


def _close_changed_interrupted_run(
    store: InstanceStore,
    ledger: IngestionLedger,
    run: IngestionRunRecord,
    items: list[IngestionItemRecord],
    *,
    deterministic_acquisitions: bool,
) -> IngestionRunResult:
    """Reconcile commits but never read bytes from a changed Source snapshot."""

    finished_items: list[IngestionItemRecord] = []
    acquisitions: list[Acquisition] = []
    for item in items:
        if item.status in {"completed", "failed"}:
            finished_items.append(item)
            if item.acquisition_id is not None:
                record = store.read_canonical("acquisitions", item.acquisition_id)
                if record is not None:
                    acquisitions.append(Acquisition(**record))
                    continue
            if item.status == "failed":
                continue
            raise IngestionInputError(
                "completed interrupted item references a missing Acquisition"
            )
        deterministic_acquisition_id = None
        if deterministic_acquisitions:
            value = f"provelume:ingestion-acquisition:{run.id}:{item.locator}"
            deterministic_acquisition_id = f"acq_{uuid5(NAMESPACE_URL, value).hex}"
            reconciled = _reconcile_committed_acquisition(
                store,
                ledger,
                item,
                deterministic_acquisition_id,
            )
            if reconciled is not None:
                finished, acquisition = reconciled
                finished_items.append(finished)
                acquisitions.append(acquisition)
                continue
        completed_at = utc_now()
        failed = replace(
            item,
            status="failed",
            started_at=item.started_at or completed_at,
            completed_at=completed_at,
            acquisition_id=None,
            outcome=None,
            error_code="input_io_error",
            error="Source snapshot changed before the interrupted item could resume",
        )
        ledger.write_item(failed)
        finished_items.append(failed)

    closed = _close_run(ledger, run, finished_items)
    return IngestionRunResult(
        run=closed,
        items=tuple(finished_items),
        acquisitions=tuple(acquisitions),
    )


def _run_ingestion_filesystem_locked(
    store: InstanceStore,
    source_path: Path | str,
    *,
    source_name: str | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
    run_id: str | None = None,
    reconcile_only: bool = False,
) -> IngestionRunResult:
    source_id, configured_source_path = _source_for_run(store, source_path, source_name)
    ledger = IngestionLedger(store)
    existing_run = ledger.get_run(run_id) if run_id is not None else None
    if existing_run is not None and existing_run.get("source_id") != source_id:
        raise IngestionInputError("durable ingestion run belongs to another Source")
    if existing_run is not None and existing_run.get("status") != "running":
        existing_items = ledger.items_for_run(str(existing_run["id"]))
        acquisitions = []
        for item in existing_items:
            acquisition_id = item.get("acquisition_id")
            if isinstance(acquisition_id, str):
                record = store.read_canonical("acquisitions", acquisition_id)
                if record is not None:
                    acquisitions.append(Acquisition(**record))
                elif item.get("status") == "completed":
                    raise IngestionInputError(
                        "terminal ingestion run references a missing Acquisition"
                    )
        return IngestionRunResult(
            run=IngestionRunRecord(**existing_run),
            items=tuple(IngestionItemRecord(**item) for item in existing_items),
            acquisitions=tuple(acquisitions),
        )
    run = (
        IngestionRunRecord(**existing_run)
        if existing_run is not None
        else _new_run(
            ledger,
            source_id=source_id,
            max_file_bytes=max_file_bytes,
            max_files=max_files,
            record_id=run_id,
        )
    )
    ledger.write_run(run)
    if reconcile_only:
        if existing_run is None:
            raise IngestionInputError("cannot reconcile an ingestion run that was not started")
        return _close_changed_interrupted_run(
            store,
            ledger,
            run,
            [IngestionItemRecord(**item) for item in ledger.items_for_run(run.id)],
            deterministic_acquisitions=run_id is not None,
        )

    try:
        canonical_source_path = configured_source_path.expanduser().resolve(strict=True)
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

    previous_items = {str(item["locator"]): item for item in ledger.items_for_run(run.id)}
    items = []
    for locator, _path in files:
        previous = previous_items.get(locator)
        if previous is not None:
            items.append(IngestionItemRecord(**previous))
            continue
        deterministic_item_id = None
        if run_id is not None:
            value = f"provelume:ingestion-item:{run.id}:{locator}"
            deterministic_item_id = f"item_{uuid5(NAMESPACE_URL, value).hex}"
        items.append(
            _new_item(
                ledger,
                run_id=run.id,
                source_id=source_id,
                locator=locator,
                record_id=deterministic_item_id,
            )
        )
    run = replace(run, item_count=len(items))
    ledger.write_run(run)
    for item in items:
        ledger.write_item(item)

    finished_items: list[IngestionItemRecord] = []
    acquisitions: list[Acquisition] = []
    for item, (_locator, path) in zip(items, files, strict=True):
        if item.status in {"completed", "failed"}:
            finished_items.append(item)
            acquisition_id = item.acquisition_id
            if acquisition_id is not None:
                record = store.read_canonical("acquisitions", acquisition_id)
                if record is not None:
                    acquisitions.append(Acquisition(**record))
                    continue
            if item.status == "failed":
                continue
        deterministic_acquisition_id = None
        if run_id is not None:
            value = f"provelume:ingestion-acquisition:{run.id}:{item.locator}"
            deterministic_acquisition_id = f"acq_{uuid5(NAMESPACE_URL, value).hex}"
            reconciled = _reconcile_committed_acquisition(
                store,
                ledger,
                item,
                deterministic_acquisition_id,
            )
            if reconciled is not None:
                finished, acquisition = reconciled
                if finished_items and finished_items[-1].id == item.id:
                    finished_items[-1] = finished
                else:
                    finished_items.append(finished)
                acquisitions.append(acquisition)
                continue
        finished, acquisition = _process_item(
            store,
            ledger,
            item,
            lambda selected=path: selected,
            max_file_bytes=max_file_bytes,
            retry_extraction=False,
            acquisition_id=deterministic_acquisition_id,
        )
        if finished_items and finished_items[-1].id == item.id:
            finished_items[-1] = finished
        else:
            finished_items.append(finished)
        if acquisition is not None:
            acquisitions.append(acquisition)

    closed = _close_run(ledger, run, finished_items)
    return IngestionRunResult(
        run=closed,
        items=tuple(finished_items),
        acquisitions=tuple(acquisitions),
    )


def run_ingestion_filesystem(
    store: InstanceStore,
    source_path: Path | str,
    *,
    source_name: str | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> IngestionRunResult:
    """Ingest one filesystem Source under the Instance mutation lock."""

    with InstanceLifecycleManager(store)._hold(purpose="filesystem-ingestion"):
        result = _run_ingestion_filesystem_locked(
            store,
            source_path,
            source_name=source_name,
            max_file_bytes=max_file_bytes,
            max_files=max_files,
        )
        _refresh_after_ingestion(store, result)
        return result


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


def _retry_ingestion_run_locked(
    store: InstanceStore,
    run_id: str,
    *,
    retry_run_id: str | None = None,
    deterministic_acquisitions: bool = False,
    reconcile_only: bool = False,
) -> IngestionRunResult:
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
    existing = ledger.get_run(retry_run_id) if retry_run_id is not None else None
    if existing is not None:
        if (
            existing.get("source_id") != source_id
            or existing.get("retry_of_run_id") != run_id
        ):
            raise IngestionRetryError("durable retry run binding is inconsistent")
        existing_items = ledger.items_for_run(str(existing["id"]))
        if existing.get("status") != "running":
            acquisitions = []
            for existing_item in existing_items:
                acquisition_id = existing_item.get("acquisition_id")
                if isinstance(acquisition_id, str):
                    record = store.read_canonical("acquisitions", acquisition_id)
                    if record is None and existing_item.get("status") == "completed":
                        raise IngestionRetryError(
                            "terminal retry run references a missing Acquisition"
                        )
                    if record is not None:
                        acquisitions.append(Acquisition(**record))
            return IngestionRunResult(
                run=IngestionRunRecord(**existing),
                items=tuple(IngestionItemRecord(**item) for item in existing_items),
                acquisitions=tuple(acquisitions),
            )
        run = IngestionRunRecord(**existing)
        items = [IngestionItemRecord(**item) for item in existing_items]
    else:
        run = _new_run(
            ledger,
            source_id=source_id,
            max_file_bytes=max_file_bytes,
            max_files=max_files,
            retry_of_run_id=run_id,
            record_id=retry_run_id,
        )
        items = []
        for previous_item in retryable:
            item_id = None
            if retry_run_id is not None:
                value = f"provelume:ingestion-retry-item:{run.id}:{previous_item['id']}"
                item_id = f"item_{uuid5(NAMESPACE_URL, value).hex}"
            items.append(
                _new_item(
                    ledger,
                    run_id=run.id,
                    source_id=source_id,
                    locator=str(previous_item["locator"]),
                    attempt=int(previous_item.get("attempt", 1)) + 1,
                    retry_of_item_id=str(previous_item["id"]),
                    record_id=item_id,
                )
            )
        run = replace(run, item_count=len(items))
        ledger.write_run(run)
        for item in items:
            ledger.write_item(item)

    if reconcile_only:
        return _close_changed_interrupted_run(
            store,
            ledger,
            run,
            items,
            deterministic_acquisitions=deterministic_acquisitions,
        )

    finished_items: list[IngestionItemRecord] = []
    acquisitions: list[Acquisition] = []
    for item in items:
        if item.status in {"completed", "failed"}:
            finished_items.append(item)
            if item.acquisition_id is not None:
                record = store.read_canonical("acquisitions", item.acquisition_id)
                if record is not None:
                    acquisitions.append(Acquisition(**record))
                    continue
            if item.status == "failed":
                continue
            raise IngestionRetryError("completed retry item references a missing Acquisition")
        deterministic_acquisition_id = None
        if deterministic_acquisitions:
            value = f"provelume:ingestion-acquisition:{run.id}:{item.locator}"
            deterministic_acquisition_id = f"acq_{uuid5(NAMESPACE_URL, value).hex}"
            reconciled = _reconcile_committed_acquisition(
                store,
                ledger,
                item,
                deterministic_acquisition_id,
            )
            if reconciled is not None:
                finished, acquisition = reconciled
                finished_items.append(finished)
                acquisitions.append(acquisition)
                continue
        finished, acquisition = _process_item(
            store,
            ledger,
            item,
            lambda locator=item.locator: _safe_retry_path(source_path, locator),
            max_file_bytes=max_file_bytes,
            retry_extraction=True,
            acquisition_id=deterministic_acquisition_id,
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


def retry_ingestion_run(store: InstanceStore, run_id: str) -> IngestionRunResult:
    """Retry failed ingestion under the Instance mutation lock."""

    with InstanceLifecycleManager(store)._hold(purpose="filesystem-ingestion-retry"):
        result = _retry_ingestion_run_locked(store, run_id)
        _refresh_after_ingestion(store, result)
        return result


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


def _extract_version(
    store: InstanceStore,
    version_id: str,
    path: Path,
    data: bytes,
) -> str | None:
    extractor = extractor_for(path)
    if extractor is None:
        raise IngestionInputError(f"no extractor is available for {path.name}")
    try:
        extraction = extractor.extract(data)
        materialize_extracted_text(store, version_id, extraction)
    except ExtractionError as exc:
        return str(exc)
    return None


def _record_matching_acquisition(
    store: InstanceStore,
    *,
    source_id: str,
    locator: str,
    observed_at: str,
    digest: str,
    document_id: str,
    version_id: str,
    path: Path,
    data: bytes,
    retry_extraction: bool,
    acquisition_id: str | None = None,
) -> Acquisition:
    outcome = "unchanged"
    extraction_error: str | None = None
    if retry_extraction and store.derived_artifact_for_version(version_id) is None:
        extraction_error = _extract_version(store, version_id, path, data)
        outcome = "extraction_failed" if extraction_error else "extraction_recovered"

    acquisition = Acquisition(
        id=acquisition_id or f"acq_{uuid4().hex}",
        source_id=source_id,
        locator=locator,
        observed_at=observed_at,
        content_hash=digest,
        outcome=outcome,
        document_id=document_id,
        version_id=version_id,
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
            version_id,
        )
    )
    return acquisition


def _record_version_acquisition(
    store: InstanceStore,
    *,
    source_id: str,
    locator: str,
    observed_at: str,
    digest: str,
    document_id: str,
    version_id: str,
    original: Original,
    path: Path,
    data: bytes,
    base_outcome: str,
    acquisition_id: str | None = None,
) -> Acquisition:
    extraction_error: str | None = None
    if store.derived_artifact_for_version(version_id) is None:
        extraction_error = _extract_version(store, version_id, path, data)
    outcome = "extraction_failed" if extraction_error else base_outcome
    acquisition = Acquisition(
        id=acquisition_id or f"acq_{uuid4().hex}",
        source_id=source_id,
        locator=locator,
        observed_at=observed_at,
        content_hash=digest,
        outcome=outcome,
        document_id=document_id,
        version_id=version_id,
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


def _ingest_one(
    store: InstanceStore,
    source_id: str,
    locator: str,
    path: Path,
    max_file_bytes: int,
    *,
    retry_extraction: bool = False,
    acquisition_id: str | None = None,
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
        document_id = _stable_document_id(source_id, locator)
        versions = store.versions_for_document(document_id)
    else:
        document_id = existing["id"]
        versions = store.versions_for_document(document_id)
        current = next(
            item for item in versions if item["id"] == existing["current_version_id"]
        )
        if current["content_hash"] == digest:
            return _record_matching_acquisition(
                store,
                source_id=source_id,
                locator=locator,
                observed_at=observed_at,
                digest=digest,
                document_id=document_id,
                version_id=current["id"],
                path=path,
                data=data,
                retry_extraction=retry_extraction,
                acquisition_id=acquisition_id,
            )

    matching = next(
        (item for item in versions if item["content_hash"] == digest),
        None,
    )
    if matching is None:
        sequence = max((int(item["sequence"]) for item in versions), default=0) + 1
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
        version_created = True
    else:
        if matching["original_id"] != original.id:
            raise IngestionInputError(
                f"stored Version identity does not match current bytes for {locator}"
            )
        version_id = str(matching["id"])
        version_created = False

    if existing is None:
        created_at = min(
            (str(item["acquired_at"]) for item in versions),
            default=observed_at,
        )
        document = Document(
            id=document_id,
            source_id=source_id,
            locator=locator,
            title=path.name,
            media_type=media_type,
            created_at=created_at,
            current_version_id=version_id,
        )
        base_outcome = "created"
    else:
        document = replace(
            Document(**existing),
            current_version_id=version_id,
            media_type=media_type,
        )
        if version_created:
            base_outcome = "version_created"
        else:
            was_observed = any(
                acquisition["version_id"] == version_id
                for acquisition in store.list_canonical("acquisitions")
            )
            base_outcome = "version_reused" if was_observed else "version_created"
    store.write_document(document)

    return _record_version_acquisition(
        store,
        source_id=source_id,
        locator=locator,
        observed_at=observed_at,
        digest=digest,
        document_id=document_id,
        version_id=version_id,
        original=original,
        path=path,
        data=data,
        base_outcome=base_outcome,
        acquisition_id=acquisition_id,
    )
