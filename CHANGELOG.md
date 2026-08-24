# Changelog

All notable public product changes are recorded here. Provelume is pre-1.0 and contracts may still evolve with documented migration paths.

## Unreleased

## 0.1.0 - 2026-08-24

### Added

- provider-independent standard-library offline release verifier with bounded path/checksum/evidence validation, JSON output and optional externally trusted manifest SHA-256 anchor;
- reviewed target-specific Ubuntu x86_64 / CPython 3.12.14 build-input lock with exact wheel SHA-256 identities and offline verification;
- least-privilege reusable release pipeline that requires deterministic candidate output, separately provisioned offline rebuild evidence and a passed final release-assurance report before official publication;
- final bundle verifier covering manifest identities, SHA256SUMS, path safety and required build-assurance assets;
- deterministic local DOCX, CSV and EML text extraction using Python standard-library facilities only;
- deterministic local XLSX cell extraction from bounded OOXML worksheet/shared-string data;
- local PNG/JPEG metadata extraction for format and dimensions without image decoding or OCR;
- bounded ZIP archive inspection with member listing and supported nested-member text extraction in memory;
- bounded extractor safeguards for extracted text, OOXML package structure, CSV rows/columns, EML MIME parts, XLSX sheets/rows/cells, ZIP traversal, symlinks, encryption, member sizes and compression ratios;
- traceable-release foundation with semantic tag/source validation, Python wheel/source builds, SHA-256 checksums, CycloneDX SBOM, provider-independent release manifest and GitHub artifact attestations;
- normal-CI dry run of the release packaging/SBOM/manifest path without publishing a release;
- public release governance, verification documentation and an ADR that explicitly separates traceable builds from future reproducible-release claims;
- byte-for-byte comparison of wheel and source distribution built from two independent clean source copies;
- portable `build-determinism.json` evidence with source fingerprint, timestamp input, toolchain, platform and both artifact hashes;
- public JSON Schema and ADR for the deterministic Python distribution contract;
- schema-versioned build identity embedded before deterministic artifact creation;
- offline `provelume build-info` CLI and `GET /api/v1/build-info` read-only API;
- EN/IT Knowledge Browser Security page for version, tag, commit, source channel and explicit verification boundaries;
- public build-info JSON Schema and ADR separating descriptive identity from local integrity/signature/provenance verification;
- portable schema-1 Instance directory with readable canonical JSON and content-addressed originals;
- Source, Acquisition, Original, Document, DocumentVersion, DerivedArtifact and ProvenanceEdge contracts;
- local TXT, Markdown and PDF ingestion with hashing, deduplication, version detection and safe failure preservation;
- rebuildable SQLite FTS5 local search;
- read-only Knowledge API v1;
- minimal EN/IT Knowledge Browser with browse, search, document detail, version history, provenance and knowledge health;
- CLI for init, ingestion, index rebuild, health and local serving;
- generic Docker Compose and synthetic public demo source;
- Linux/Windows CI test matrix and clean-room repository guardrails.

### Changed

- official release permissions are isolated in a final tag-only job; candidate, rebuild and assembly stages are read-only and the older standalone rebuild workflows are retired in favor of one shared gate;
- derived text materialization is shared by ingestion and index rebuild so extractor identity, artifact identity and derived provenance remain stable when rebuildable state is deleted;
- search-index rebuild selects the extractor from the canonical document locator instead of assuming every non-PDF original is plain text;
- CI uses a pinned Node-24-capable `setup-python` action revision; cross-platform tests track Python 3.12 while the current official Linux release build is pinned to Python 3.12.14;
- Hatchling is pinned exactly and reproducible archive mode is explicit;
- normal CI and official releases share the same fail-closed deterministic distribution builder;
- deterministic-build evidence is included in release checksums, release manifest assets and provenance attestations;
- normal CI installs the built wheel and verifies embedded development identity from the executable package;
- official tag builds require matching official metadata and validate it from the installed wheel before publication;
- `/health` reports build-identity status without claiming that installation verification was performed.

### Explicitly not included

OCR, semantic/vector search, external AI providers, cloud connectors, SaaS tenancy, billing, Windows installer/updater and advanced editing remain later milestones.
