# Changelog

All notable public product changes are recorded here. Provelume is pre-1.0 and contracts may still evolve with documented migration paths. Release planning follows [`docs/changelog-policy.md`](docs/changelog-policy.md).

## Unreleased

### Changed

- made the connector forecast explicit: read-only Gmail and Google Drive intake in `0.9.0`,
  followed by multiple Google Calendar and iCalendar Sources, Asana and Tududi adapters, and
  narrowly guarded task write-back in `0.12.0`;
- made every connector type multi-instance by contract, including isolated accounts, credentials,
  policies, cursors and independently selected Sources such as multiple Asana identities,
  workspaces and projects or multiple Tududi endpoints;
- expanded `0.10.0` into a review-first Mobile Capture and Retrieval Inbox with QR-paired
  uploads, authenticated recent/search/provenance/original-download access, iOS and Android
  sharing paths, a watched Drive drop folder and an optional privacy-declared Telegram relay,
  while deferring personal-chat access and WhatsApp Business integration;
- established Markdown as the first-class portable classic-navigation format while retaining
  canonical JSON and exact originals, and planned a safe rendered/raw/original Viewer plus tree,
  search, backlinks, timelines, saved views and a secondary relation graph;
- assigned the local filesystem Drop Inbox, PDF-to-Markdown document bundles, page maps, assets,
  optional derived PDF optimization and exact-duplicate handling to `0.5.0`, followed in `0.6.0`
  by a persistent hierarchical Markdown library with stable Areas, Projects, Collections,
  per-folder README indexes and filesystem/Viewer parity;
- defined original-retention assurance and a unified Action Center: routine classification,
  deduplication, source refresh and library moves do not delete acquired originals; ambiguous or
  destructive outcomes enter evidence-backed queues, while archive, projection removal, trash and
  explicit permanent purge remain distinct user actions;
- made normalized Markdown plus page maps and selected assets the default later AI working
  context, with source-page/original fallback and separately reviewable, attributable proposals
  that cannot overwrite an acquired original or extracted document bundle;
- adopted bounded development-slice identifiers (`0.5/S01`, fine-tuning `0.5/S01/F01` and
  micro-adjustment `0.5/S01/F01-a`) so one homogeneous agent turn need not become a package
  release; optional installable checkpoints retain standards-compliant alpha/beta/RC identities;
- atomically inserted the productivity-connector outcome at `0.12.0` and shifted every later
  unreleased `0.x` forecast through the release candidate forward by one slot to `0.22.0`,
  without changing published history, package identity, the `0.5.0`–`0.11.0` sequence or
  stable `1.0.0`.

## 0.4.0 - 2026-08-27

### Added

- activated the `0.4.0` Windows Product Shell Preview through issue #57, with a per-user x64
  installer, bundled runtime, EN/IT launcher, local Instance start/stop/open controls and an
  offline About surface;
- added explicit manual and opt-in startup update checks, bounded GitHub Releases transport,
  provider-independent Windows update metadata and size/SHA-256 verification before a
  user-confirmed installer handoff;
- added Windows packaging, frozen-build diagnostics, install/uninstall CI evidence and release
  bundle publication for the unsigned preview installer.

### Changed

- expanded the canonical public roadmap into an ordered release-by-release forecast through
  `1.0.0`, with explicit dependencies, exit gates and activation boundaries;
- atomically inserted the Windows product shell at `0.4.0`, shifted every later unreleased `0.x`
  forecast through the release candidate forward by one slot, and kept earlier published history
  and stable `1.0.0` unchanged.

## 0.3.0 - 2026-08-27

### Added

- optional Anchored Local Installation Trust across CLI, read-only API and EN/IT browser: an operator-controlled local release bundle is verified offline, its candidate wheel and internal `RECORD` are validated in memory, and installed Core bytes are compared directly with released wheel bytes;

### Changed

- the provider-independent offline release verifier is now also packaged as the shared application-service implementation while remaining a self-contained standard-library script in release bundles;
- browser/API installation evidence is configured only through trusted server-start options and cached for the process lifetime; client-supplied local paths or hashes are rejected;
- defined an atomic forward-shift contract for unplanned release insertions: later unreleased planned versions move forward while released history and the current package identity remain unchanged until release preparation;
- established the public `0.3.0` roadmap and bounded Anchored Local Installation Trust release plan;

## 0.2.0 - 2026-08-27

### Added

- local read-only `Verify installation` capability across CLI, API and EN/IT browser, with PEP 376 RECORD hashing, unexpected-file/path safety checks and explicit separation between package integrity and official origin;
- read-only Privacy & Network Activity inventory across CLI, API and EN/IT browser, with fail-visible capability declarations, endpoint-origin redaction, policy-conflict reporting and an explicit `not_instrumented` traffic boundary;

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
