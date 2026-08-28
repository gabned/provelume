# Derived search-index contract

The full-text search database under `indexes/search.sqlite3` is derived, local-only
state. Canonical Source, Acquisition, Original, Document, DocumentVersion and
provenance JSON records remain authoritative.

## Complete rebuild

An explicit rebuild constructs a replacement SQLite FTS database in a temporary
file inside the Instance indexes directory. Provelume closes and flushes the
complete candidate and stages matching metadata before installing the pair. The
previous database and metadata are retained until both replacements succeed and
are restored if either install fails. A failed build therefore leaves the previous
complete database and metadata available together.

The rebuild may recover missing extracted text from preserved Originals when the
caller explicitly allows recovery. The normal post-ingestion path never retries a
failed extractor silently.

## Incremental refresh

Search metadata schema 2 records the current Document-to-DocumentVersion mapping
alongside the knowledge fingerprint and indexed-row count. After ingestion,
Provelume selects only Acquisitions whose outcome may have changed searchable
state. Rows for those Documents are deleted and reinserted in one SQLite
transaction.

Incremental refresh is used only when all of these conditions hold:

- the SQLite database and schema-2 metadata both exist;
- the metadata fingerprint matches its recorded Document map;
- every non-selected Document still points to the recorded current Version;
- the physical FTS row count matches metadata.

Any missing, legacy, malformed, inconsistent or externally changed derived state
falls back to the complete rebuild path. Existing `0.5.0` schema-1 metadata is
therefore upgraded transparently without changing canonical Instance records.

## Performance boundary

Adding or changing one supported file no longer rereads extracted text for every
unchanged Document. The implementation still reads the small canonical Document
catalog to prove that non-selected rows remain valid. A future revision counter
or catalog index may reduce that catalog check further without changing the
canonical authority boundary.
