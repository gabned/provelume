# Changelog

All notable public product changes are recorded here. Provelume is pre-1.0 and contracts may still evolve with documented migration paths. Release planning follows [`docs/changelog-policy.md`](docs/changelog-policy.md).

## Unreleased

### Added

- added versioned provider-independent connector definitions, isolated multi-instance connector
  configuration and independently identified connector Sources as additive schema-2 state;
- added deterministic local service and CLI contracts for capability-manifest registration,
  connector-instance creation, Source declaration and a network-free connector inventory;
- added bounded create, inspect, update, enable, disable and tombstone-removal lifecycle contracts
  for connector instances and independently selected Sources, including per-instance endpoint,
  policy, empty cursor envelope and configuration-health state;
- added aligned read-only connector inventory/detail contracts across service, CLI, API and EN/IT
  Browser surfaces, all derived from the same application-service views;
- added Instance-local connector configuration operations with closed status, changed-field names,
  stable related IDs and explicit zero-Original-mutation metrics;
- added provider-independent installed-app OAuth 2.0 authorization request, short-lived state and
  exact callback-completion contracts with mandatory PKCE S256 and explicit consent;
- added reauthorization and local revocation contracts that retain Sources, Acquisitions,
  Documents, Versions, provenance and exact Original bytes;
- added deterministic synthetic adapter conformance coverage for replay, state mismatch, scope
  escalation, callback substitution and secret-bearing adapter results;
- added provider-independent guarded HTTP(S) retrieval that requires an explicit request plus
  current Instance, connector and independently enabled web Source authority at execution time;
- added bounded transient conditional metadata, redirects, time, headers, resource count,
  compressed/decompressed body sizes, decompression ratio, media types and response framing without
  introducing scheduling, refresh state or canonical acquisition;
- included connector definitions, instances and Sources in deep validation, backup, restore and
  portable Instance export/import without changing package or embedded release identity.

### Changed

- expanded the unreleased `0.8.0`–`0.20.0` public forecast with user-controlled watched-folder
  intake, local OCR, legacy archive import, optional Git mirrors, direct MCP client connections,
  privacy-routed AI classification, qualified Synology operations and a Windows background agent,
  while preserving `0.6.1` identity and the active `0.7.0` implementation boundary; assigned one
  unique one-word Latin codename and a concise two-sentence outcome to every published and forecast
  release without changing package, tag or version identity;
- made connector and Source removal retain canonical tombstones instead of deleting identity
  records, and require independently selected Sources to be removed before their parent instance;
- kept S01 schema-1 connector records valid and upgraded each record to lifecycle schema 2 only
  when that exact record is first mutated;
- kept schema-1/schema-2 connector instances valid while new or changed instances use additive
  schema 3 with redacted OAuth status, timestamps, loopback binding and consent metadata;
- accepted the bounded RFC 6749 scope-token character set without lowercasing case-sensitive
  provider scopes, including colon-delimited, mixed-case and URL-shaped read scopes;
- made disabled or removed connector configuration fail closed while leaving acquired Sources,
  Acquisitions, Documents, Versions and Original bytes untouched.
- made explicit primary-endpoint clearing preserve the independent origin allowlist instead of
  silently selecting its first member again.

### Security

- restricted connector credentials to validated external environment or system-keyring references
  and rejected inline secret material;
- kept connector configuration operation evidence free of provider/account values, endpoint
  origins, credential-reference names, physical paths and secret material;
- retained OAuth state and PKCE verifiers only in process memory, consumed valid-state callbacks
  once and rejected expired, replayed, mismatched or scope-escalated callbacks before mutation;
- rejected token, client-secret, authorization-code, verifier and other secret-bearing adapter
  output, while persisting only validated external credential references and redacted metadata;
- required current connector/Instance network policy, exact adapter identity, explicitly allowed
  OAuth endpoint origins and exact high-port loopback redirect binding at request and callback time;
- restricted web transport to unambiguous HTTP(S), exact Source and origin/port authority, public
  IPv4/IPv6 destinations and a bad-port denylist; re-resolved and revalidated every hop immediately
  before a socket pinned to the approved address;
- rejected mixed/non-public DNS answers, rebinding, redirect pivots and downgrade, malformed or
  truncated framing, unsupported encoding, oversized responses and decompression bombs through
  typed errors whose fixed messages contain no URL, credential, token, path or response content;
- serialized authorization request, callback exchange/completion and revocation per connector,
  invalidating sibling requests after success so revocation wins every race and only one exchange
  can commit for one unchanged connector record, including revocation from a separate process-local
  service instance;
- kept synthetic adapter exchange outside the Instance-wide configuration lock so independent
  connectors may complete concurrently while their short canonical commits serialize locally;
- made every connector declare an explicit network mode and bounded HTTP(S) origin allowlist while
  the global Instance network policy remains a fail-closed gate and configuration mutations perform
  no network access.

## 0.6.1 - 2026-08-29

### Fixed

- made permanent purge include bounded operational records linked through the selected Document's
  Version and Acquisition identities, preventing retained ingestion locators and dangling
  acquisition references after purge;
- serialized filesystem ingestion, ingestion retry, their derived index refresh and Inbox ingestion
  with the same cross-process Instance lifecycle lock used by permanent purge, so acquisition and
  index maintenance cannot race purge staging, rollback or recovery.

## 0.6.0 - 2026-08-28

### Added

- added a versioned schema-2 `instance-manifest.json` that binds stable Instance identity and an
  explicit include/rebuild policy for retained state, indexes and the Markdown library;
- added read-only deep/fast Instance validation plus local `validate`, `migrate`, `backup` and
  `restore` CLI/application-service contracts;
- added hash-manifested same-Instance ZIP backups with bounded entry, path, symlink, collision,
  size and digest verification;
- added a final deep fingerprint and retained-payload revalidation so a concurrent committed write
  invalidates an in-progress backup instead of being silently omitted;
- added ordered schema-1 to schema-2 migration receipts, verified automatic pre-migration and
  pre-restore backups, external pending-operation evidence and durable recovery receipts.
- added canonical record-schema-1 Area/Subarea, Project and Collection objects with stable opaque
  IDs, bounded acyclic parent links and collision-safe Windows-portable slugs;
- added one deterministic classification record per classified Document, with one primary node,
  sorted unique secondary associations and deterministic retained provenance edges;
- added local hierarchy/classification service and CLI mutations plus aligned read-only API and
  EN/IT Browser hierarchy navigation, breadcrumbs, counts and subtree filtering.
- added a deterministic staged `library/` projection with root/per-folder README indexes,
  Area/Project primary paths, Collection associations, unclassified/archive roots and generated
  Source/date/type views without copying acquired Originals;
- added hash-manifested library status plus local `library-rebuild` and `library-status`
  service/CLI contracts and a read-only status API;
- added safe EN/IT Document Viewer modes for rendered Markdown, raw Markdown, escaped Original
  text and exact Original download;
- added canonical Document dispositions and distinct local archive, unarchive, library exclusion,
  library restoration, recoverable trash and identity-preserving trash restoration actions;
- added preview-bound permanent purge with a short-lived confirmation token, explicit boundary
  acknowledgement, exact live-Instance impact inventory and privacy-minimizing completion receipt;
- added read-only disposition filtering/status in the API and EN/IT Browser while retaining all
  retention mutations as explicit local service/CLI authority.
- added deterministic hash-manifested portable Instance export with canonical readable JSON,
  stable bundle identity and explicit `rebuild` or `include` derived-state policy;
- added aligned local `export` and `import` application-service/CLI contracts, cross-Instance
  replacement import receipts and preserved Instance, hierarchy, classification and disposition
  identity.

### Changed

- made supported schema-1 Instances migrate forward only after deep canonical/Original preflight,
  while unknown future schemas fail before any backup or mutation;
- made deep validation bind each Version hash and size to its retained Original, and replaced stale
  lifecycle-lock deletion with a kernel-released cross-platform OS lock;
- made restore extract and validate off to the side, atomically replace the live Instance on the
  same filesystem and restore the verified pre-operation backup if any step fails;
- excluded disposable `indexes/`, the generated `library/` projection and transient locks from local
  backups while retaining canonical JSON, exact Originals and Instance state artifacts.
- made hierarchy rename and movement preserve node identity, Document references and provenance;
  classification remains idempotent and does not copy knowledge or mutate an Original;
- treated empty hierarchy/classification containers as additive schema-2 state so Instances made
  before this slice remain valid without a second lifecycle migration.
- made coordinated incremental/full/agreement rebuilds include the Markdown library fingerprint
  while preserving the same exclusive derived-state lock and canonical-mutation check;
- kept the implemented Markdown library explicitly disposable under the schema-2 derived-state
  policy and excluded it from local backups;
- made archived Documents project under `library/archive/`, projection-excluded Documents remain
  canonical but absent from `library/`, and trashed Documents leave default browse/search/library
  views until restored.
- made portable import stage, migrate and deeply validate the complete exported Instance before an
  atomic same-filesystem swap, with a verified pre-import target backup and exact rollback.

### Reliability and security

- added crash recovery for interrupted migrations and restores without treating a partial write
  as success, plus hostile/archive regressions for cross-Instance restore and tampered Originals;
- kept external Source, Drop and managed-copy folders outside backup claims so an Instance archive
  does not imply preservation of files that were never acquired.
- added deep validation for hierarchy identities, parent kinds/cycles/depth, deterministic slugs,
  classification references and required association-provenance bindings.
- made a complete library rebuild bind deep canonical/Original fingerprints before and after
  staging, restore the previous projection on swap failure and reject modified, stale, symlinked,
  oversized or path-invalid projection state;
- escaped raw HTML in rendered Markdown and made authored links/images inert so Viewer content
  cannot emit document-controlled navigation, resource loading or active elements;
- made Original downloads verify current Version/Original hash and size bindings before returning
  attachment bytes;
- made every non-purge retention action synchronize canonical disposition, search and library state
  under the lifecycle lock, roll back on ordinary failure and report zero Original deletion;
- made purge stage exact lineage targets transactionally, restore interrupted pre-commit work,
  finish committed cleanup on reopen and reject stale, malformed or path-tampered evidence;
- retained shared content-addressed Originals still referenced by another Document and reported
  configured Source, managed-backup, external-replica and large-state-scan limits without claiming
  broader erasure.
- rejected traversal, absolute/drive-qualified paths, non-NFC names, Windows reserved names,
  case/file-directory collisions, links, undeclared entries, partial payloads and stale or
  hash-mismatched portable bundles before target mutation;
- restricted authoritative portable payloads to registered canonical JSON and Original
  `storage_ref` values, omitting unreferenced files below authoritative directories;
- compared every included search-index row with current canonical identities, filter fields,
  titles and derived content on both export and staged import;
- published completed portable archives with atomic no-replace semantics and identity-bound
  cleanup so a competing destination writer is neither overwritten nor deleted;
- recovered interrupted imports by restoring the verified pre-import backup under the same
  kernel-released lifecycle lock, without treating partial replacement as success.

## 0.5.1 - 2026-08-28

### Security

- restricted `provelume serve` to explicit loopback bind targets and rejected wildcard, LAN and
  arbitrary hostnames until a separately authenticated network-serving contract exists;
- rejected non-local HTTP Host headers and added restrictive CSP, clickjacking, MIME-sniffing,
  referrer, browser-permission, cross-origin and private-cache response headers;
- documented latest-preview security handling, the unsupported LAN/Internet serving boundary,
  unsigned Windows status and private reporting path without claiming repository settings active.

### Changed

- disabled the interactive `/api/docs` surface while keeping the read-only versioned API directly
  available inside the packaged local application;
- preserved the current path, search text, dates and filters when switching between EN and IT;
- added weekly Dependabot proposals for Python and GitHub Actions dependencies; every proposal
  remains an ordinary review/CI input and receives no tag or release authority;
- centralized identical post-ingestion index-refresh orchestration and documented the current
  large-module pressure map with separately owned follow-up work.

### Accessibility

- added a keyboard-visible skip link, stable main landmark, translated navigation label,
  current-page state, visible focus treatment and wrapping primary navigation.

### Performance

- replaced the complete FTS rebuild after every ingestion or Inbox submission with a
  transactional refresh of only Documents whose searchable current Version changed;
- added schema-2 search metadata that records the current Document-to-Version map and uses a
  safe complete rebuild for legacy, missing, malformed or inconsistent derived state.

### Reliability

- made complete search-index rebuilds stage a flushed SQLite database and matching metadata,
  retaining or restoring the previous valid pair if either replacement fails.

## 0.5.0 - 2026-08-28

### Added

- added schema-versioned, Instance-local ingestion run and item records with atomic lifecycle
  states, counts, safety limits, Acquisition linkage and retry lineage under `state/ingestion/`;
- added explicit retry of only failed or interrupted ingestion items, including crash-safe
  reconciliation after partial Original, Version, Document or extraction writes;
- added a local Drop Inbox with copy-by-default capture and optional move-after-verified-commit;
- added an Instance-local, path-redacted and navigable operation log for Inbox capture, ingestion,
  bundle builds, duplicate scans, Original assurance, settings changes and coordinated rebuilds;
- added CLI, read-only API and EN/IT browser list/detail surfaces for operation evidence;
- added deterministic version-addressed document bundles with normalized Markdown, page maps,
  bounded assets, generator identity and output fingerprints;
- added exact current-content duplicate evidence that preserves every Document, locator and
  Acquisition even when byte-identical content shares one content-addressed Original;
- added conservative probable-duplicate cases with published title/text-overlap rules,
  confidence, evidence and `automatic_action: none`;
- added read-only Original assurance for hash, size, storage-reference and canonical
  Source/Document/Version/Acquisition consistency without automatic repair;
- added an exclusive Instance rebuild lock plus incremental, full and agreement rebuild modes for
  bundles, full-text search and duplicate evidence;
- added configurable Inbox display name, Drop folder and managed-copy folder through local CLI and
  a loopback/CSRF-protected EN/IT settings page;
- added support for relative Instance-local paths and absolute folders elsewhere on the local
  filesystem, with a read-only settings API that redacts external absolute paths.

### Changed

- isolated oversized, unreadable, missing and extraction-failing items so valid files in the same
  ingestion run still commit, index and remain visible;
- made retries preserve idempotent Original and DocumentVersion identity while creating a separate
  Acquisition for every observation or attempt;
- stopped post-ingestion index refresh from silently re-running a failed extractor; explicit full
  rebuild retains deterministic recovery from preserved Originals;
- moved new Inbox submission summaries into Instance state while retaining read compatibility with
  legacy `inbox/submissions/` evidence;
- made the stable Inbox Source name and managed-copy path follow validated settings while retaining
  the same Source identity across display-name or Drop-folder changes;
- made missing external Drop or managed folders fail visibly instead of silently recreating a path
  where a removable disk, network mount or profile directory disappeared;
- blocked managed-copy relocation after Inbox Documents or Acquisitions exist until a separately
  designed verified relocation workflow can preserve every binding and crash-recovery boundary;
- made incremental/full rebuild agreement compare normalized deterministic output rather than a
  timestamp-bearing bundle-manifest checksum, while still verifying every manifest, Markdown,
  page-map and asset checksum independently;
- made every duplicate and assurance operation non-destructive: no automatic merge, deletion,
  replacement or repair is inferred from a finding;
- expanded the public roadmap with bounded development-slice identifiers, portable Markdown
  navigation, original-assurance boundaries, mobile capture and multi-instance connector planning;
- inserted productivity connectors at `0.12.0` and shifted the remaining unreleased forecast
  atomically through the `0.22.0` release candidate without changing published history.

### Security and verification

- rejected Drop/managed paths that are equal, nested, contain the Instance or overlap canonical
  Originals, knowledge, state, indexes, configuration or retained submission evidence;
- canonicalized paths before overlap checks so existing symlinks cannot bypass the filesystem
  boundary;
- limited full physical paths to local CLI and loopback browser settings; operation records and
  public API/browser views retain only bounded scope and redacted locators;
- kept canonical Originals, readable knowledge JSON, derived state, indexes, operations and reports
  inside the Instance even when Drop or managed working folders are external;
- verified the release candidate with Ruff and the full suite on Ubuntu and Windows, clean-room
  checks, deterministic independent builds, release-bundle verification and Windows installer
  upgrade/preservation evidence from the immutable public `0.4.1` preview.

### Explicitly not included

OCR, a background filesystem watcher, generic scheduling, network Sources, AI classification,
semantic/vector search, automatic duplicate merge, automatic repair, external canonical storage,
managed-folder migration, Authenticode, unattended update application, runtime slots and automatic
rollback remain later milestones.

## 0.4.1 - 2026-08-27

### Fixed

- stopped the launcher from silently creating a replacement when a previously selected Instance
  was moved or removed, kept Choose/Create recovery controls available, and made
  missing/non-writable Instance failures explicit in EN/IT;
- prevented a repeated Open action from launching the browser while the backend is still starting,
  preserved the real startup-failure state and reported an unexpected backend exit;
- allowed the console-free frozen launcher to start its loopback backend without requiring
  Uvicorn console streams;
- bound Windows update-manifest commit identity to the commit resolved by the release tag instead
  of accepting any syntactically valid commit;
- made the launcher fit reduced work areas through a vertically scrollable layout, requested modern
  Windows DPI awareness and aligned enabled/disabled controls with backend and update state.

### Verification

- expanded synthetic update regressions for malformed, oversized, unknown, incompatible, timed-out
  and interrupted responses, including partial-file cleanup and stale-result protection;
- expanded Windows packaging evidence to cover the public `0.4.0` installer, default and Unicode
  paths, shortcuts, unsigned status, one stable AppId, launcher settings and Instance preservation,
  bundled-runtime isolation, loopback readiness, reinstall/uninstall and EN/IT layout probes at
  100%, 125%, 150% and 200% DPI.

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
