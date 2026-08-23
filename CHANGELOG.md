# Changelog

All notable public product changes are recorded here. Provelume is pre-1.0 and contracts may still evolve with documented migration paths.

## Unreleased

### Added

- deterministic local DOCX, CSV and EML text extraction using Python standard-library facilities only;
- bounded extractor safeguards for extracted text, DOCX package structure, CSV rows/columns and EML MIME parts.

### Changed

- derived text materialization is shared by ingestion and index rebuild so extractor identity, artifact identity and derived provenance remain stable when rebuildable state is deleted;
- search-index rebuild selects the extractor from the canonical document locator instead of assuming every non-PDF original is plain text.

## 0.1.0 - 2026-08-23

### Added

- portable schema-1 Instance directory with readable canonical JSON and content-addressed originals;
- Source, Acquisition, Original, Document, DocumentVersion, DerivedArtifact and ProvenanceEdge contracts;
- local TXT, Markdown and PDF ingestion with hashing, deduplication, version detection and safe failure preservation;
- rebuildable SQLite FTS5 local search;
- read-only Knowledge API v1;
- minimal EN/IT Knowledge Browser with browse, search, document detail, version history, provenance and knowledge health;
- CLI for init, ingestion, index rebuild, health and local serving;
- generic Docker Compose and synthetic public demo source;
- Linux/Windows CI test matrix and clean-room repository guardrails.

### Explicitly not included

OCR, semantic/vector search, external AI providers, cloud connectors, SaaS tenancy, billing, Windows installer/updater and advanced editing remain later milestones.
