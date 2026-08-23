# Changelog

All notable public product changes are recorded here. Provelume is pre-1.0 and contracts may still evolve with documented migration paths.

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
