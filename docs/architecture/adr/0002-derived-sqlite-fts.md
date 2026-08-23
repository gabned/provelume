# ADR 0002: SQLite FTS5 is a derived local search index

- Status: Accepted
- Date: 2026-08-23

## Decision

Use SQLite FTS5 for the first full-text search index. The file lives under `indexes/` and carries a fingerprint of current document versions.

## Why

SQLite is available without an external service, works on Linux and Windows, and is sufficient for the first local vertical slice.

## Consequences

The index may be deleted at any time. Provelume rebuilds it from canonical versions and extracted text, re-extracting preserved originals when necessary. No API contract may treat FTS row IDs or SQLite internals as durable knowledge identity.
