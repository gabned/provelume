# Durable ingestion runs

Status: active product contract for `0.5/S01` under issue #66. The installed package and
published preview remain `0.4.1` until a separate release-preparation change.

## Purpose

Filesystem ingestion is an operator action that may contain many independent items. One malformed,
oversized, unreadable or extraction-failing file must not discard valid work or erase the evidence
needed to understand and retry the failure.

The run ledger is local operational state. It does not replace canonical Sources, Acquisitions,
Originals, Documents, DocumentVersions or provenance, and it does not change Instance schema
version 1.

## On-disk contract

Records are schema-versioned JSON under:

```text
state/ingestion/runs/run_<uuid>.json
state/ingestion/items/item_<uuid>.json
```

A run is written with `running` status before item processing. It records Source identity, start and
completion time, closed status, item counts, safety limits and optional retry lineage. Closed states
are `completed`, `completed_with_errors` and `failed`.

Every supported item is written as `pending` before processing, then atomically becomes `running`
and finally `completed` or `failed`. The record contains only a normalized Source-relative locator,
attempt number, acquisition linkage, outcome, bounded error code/message and optional retry-item
lineage. Absolute Source paths are not returned by the service, CLI or HTTP API.

The ledger may be updated to close a state transition, but attempts are not overwritten: a retry
creates a new run and new item records linked to the prior attempt.

## Commit and failure boundary

Canonical writes retain their existing order: exact bytes are hashed and stored content-addressed,
then Version, Document, Acquisition and provenance records are committed. The operational item is
closed only after that processing returns. A process interruption can therefore leave an item
`pending` or `running` even when some canonical writes already committed.

Retry is idempotent across that boundary. Re-reading the same Source-relative item and exact bytes
creates an `unchanged` Acquisition rather than a second DocumentVersion or Original. An extraction
failure still preserves the Original, DocumentVersion and Acquisition; an explicit retry may
materialize the missing derived text against the same current bytes and records
`extraction_recovered`.

Item-level input failures are isolated. The remaining items continue and the run closes with exact
completed/failed counts. Source-level enumeration failures close the run with a bounded run error.
No `0.5/S01` path moves, deletes or rewrites a Source input.

## Retry contract

`provelume retry-ingestion INSTANCE RUN_ID` selects only prior `failed`, `pending` or `running`
items. It uses the prior run's safety limits, creates new lineage records and fails visibly when a
Source-relative input no longer exists or is no longer supported. Completed items are not replayed.
A closed run with no failed or interrupted items is not retryable.

The application service exposes list/detail/retry methods. HTTP remains read-only:

```text
GET /api/v1/ingestion/runs
GET /api/v1/ingestion/runs/{run_id}
```

No HTTP retry or ingestion mutation endpoint is introduced in this slice.

## Derived indexing

Post-ingestion index refresh indexes only derived text already produced by that run. It does not
silently re-run a failed extractor and make the durable result misleading. A separately requested
full `rebuild-index` retains its existing ability to reconstruct missing derived text from preserved
Originals. Index files remain disposable acceleration state and never determine run history.

## Privacy, network and assurance

The ledger performs no network request, sends no Instance content and stores no credential. Error
text is bounded and path-redacted before it can appear through the read-only API. Records are
Instance-local and survive process restart or index deletion.

This slice does not add a Drop Inbox watcher, move-after-commit, scheduler, OCR dependency, network
Source, duplicate decision, destructive cleanup, schema migration, package-version change, tag or
release publication.
