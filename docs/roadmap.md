# Public product roadmap

This roadmap is the canonical public release forecast for Provelume Core and the self-hosted
Instance. Published tags, dated changelog history and package identity remain immutable.
Forecast entries describe intended sequencing; they do not create an issue, owner pull
request, tag, release or delivery commitment. Planned-version movement follows
[`changelog-policy.md`](changelog-policy.md).

## Status vocabulary

- **Published preview** — immutable tag and public preview release exist.
- **Active implementation** — a canonical issue and one owner product pull request activate the
  bounded release scope; package identity and publication remain separate later steps.
- **Next forecast** — first intended product increment after the published baseline, not yet
  activated until a canonical issue and one owner pull request exist.
- **Forecast** — ordered portfolio slot whose scope may still be refined before activation.
- **Release candidate** — compatibility-freeze and validation release, not general availability.
- **Stable** — the supported 1.0 contract after release-candidate exit gates pass.

## Release lane

| State | Version | Product outcome | Activation |
| --- | --- | --- | --- |
| Published preview | `0.1.0` | Local provenance-first Instance and verified release foundation | #40 (completed) |
| Published preview | `0.2.0` | Local Installation Trust and Privacy & Network Activity transparency | #50 (merged) |
| Published preview | `0.3.0` | Anchored Local Installation Trust | #52 (completed) |
| Published preview | `0.4.0` | Windows product shell preview | #57 (completed) |
| Next forecast | `0.5.0` | Durable ingestion and extractor completion | issue just in time; #5 is an input |
| Forecast | `0.6.0` | Portable Instance lifecycle | issue just in time |
| Forecast | `0.7.0` | Connector framework and safe web intake | issue just in time |
| Forecast | `0.8.0` | Refresh engine and Source lifecycle | issue just in time |
| Forecast | `0.9.0` | Email, Google file and transcript intake | issue just in time |
| Forecast | `0.10.0` | Mobile Capture Inbox and review queue | issue just in time |
| Forecast | `0.11.0` | Knowledge Objects v1 | issue just in time |
| Forecast | `0.12.0` | Productivity connectors and guarded sync preview | issue just in time |
| Forecast | `0.13.0` | Knowledge navigation, relations and deterministic discovery | issue just in time |
| Forecast | `0.14.0` | Knowledge API v1 and read-only MCP | issue just in time |
| Forecast | `0.15.0` | AI gateway and privacy routing | issue just in time |
| Forecast | `0.16.0` | AI receipts, provider adapters and evaluation | issue just in time |
| Forecast | `0.17.0` | Semantic and hybrid search | issue just in time |
| Forecast | `0.18.0` | Self-hosted operations | issue just in time |
| Forecast | `0.19.0` | Windows bootstrap completion | issue just in time |
| Forecast | `0.20.0` | Signed Windows release and safe updater | issue just in time |
| Forecast | `0.21.0` | Business and Cloud contracts preview | issue just in time |
| Release candidate | `0.22.0` | 1.0 compatibility freeze and end-to-end qualification | issue just in time |
| Stable | `1.0.0` | Stable provenance-first platform | issue just in time |

The package and embedded identity are `0.4.0`. The `0.5.0` forecast is not active: only a
canonical issue and one owner product pull request may activate it and add product work under
`Unreleased`.

## Planning and delivery contract

- Activate and deliver one homogeneous release at a time through one canonical issue and one
  owner product pull request.
- Keep implementation separate from version alignment, tag and publication unless a future
  repository-local plan explicitly proves that a combined change remains homogeneous.
- Treat the release table as a forecast, not as a promise that every listed capability or exact
  number will ship unchanged.
- Create future issues just in time. Stable scope, dependency order and acceptance evidence are
  preserved when a forecast slot moves.
- Insert urgent independently releasable work through the atomic forward-shift contract: all
  later unreleased forecast versions move together, published history never moves, and a
  partial or ambiguous shift stops as `ROADMAP_VERSION_SHIFT_CONFLICT`.
- Use `0.x.y` only for corrections, security work or regressions belonging to the `0.x` line;
  do not reserve patch versions for unrelated feature streams.
- Keep originals and canonical knowledge authoritative. Indexes, embeddings, caches, previews
  and summaries remain rebuildable derived state.
- Preserve clean-room, provider independence, no-GitHub runtime, explicit network behavior and
  evidence claims no stronger than the verification actually performed.

## Knowledge representation and navigation contract

Markdown is the first-class portable, human-facing format for classic knowledge reading and
navigation; it is not the sole canonical storage model or a second database. Exact acquired files,
including user-authored Markdown, remain preserved under `originals/`. Canonical identities,
versions, objects, relations and provenance remain readable JSON under `knowledge/`. Provelume may
build deterministic Markdown library projections with stable links and portable metadata, but
those projections are derived, rebuildable and never silently overwrite an original or canonical
record.

The published Knowledge Browser already provides browse, search, document detail, raw extracted-
text preview, version history, provenance, original download and knowledge health. It is also the
built-in Viewer and uses the same application services as the API and CLI. The forecast extends it
with safe rendered Markdown, raw/rendered/original modes and bounded previews for other supported
formats; no view owns exclusive business logic.

Navigation must remain useful offline without AI, embeddings or a vector store. The classic path
is an area/Source/tag/type tree with breadcrumbs, recent and pinned items, full-text search and
saved views. Links and backlinks, version/provenance timelines, related items and explainable
health findings add connected navigation. A graph is an optional secondary overview rather than
the only way to find knowledge; later semantic discovery augments rather than replaces these
deterministic paths.

## Published foundation

### 0.1.0 — Local Foundation Preview + Verified Release Chain

Delivered the portable local Instance, deterministic bounded ingestion and extraction,
provenance-first storage, rebuildable full-text search, read-only API/browser/CLI, and the
least-privilege verified publication chain with offline rebuild evidence, checksums, SBOM,
manifest, attestations and a provider-independent bundle verifier.

### 0.2.0 — Local Installation Trust + Declared Privacy and Network Activity Transparency

Delivered bounded verification of installed files against local PEP 376 `RECORD`, plus a
read-only declared capability/configuration inventory for network behavior. It deliberately
separates local consistency from official origin and declared capability from observed traffic.

### 0.3.0 — Anchored Local Installation Trust

Delivered the remaining release-bundle portion of #20 through #52:

- accept an explicit operator-supplied local release bundle through CLI or trusted server-start
  configuration;
- verify the existing bounded bundle contract without network access;
- validate the released wheel and its internal `RECORD` in memory;
- compare installed Core package bytes with the released wheel bytes;
- preserve RECORD-only verification when no bundle is supplied;
- expose the same layered evidence through CLI, read-only API and EN/IT browser without
  accepting local paths from HTTP clients.

Bundle self-consistency and byte agreement strengthen release linkage but do not by themselves
authenticate the publisher. See [`releases/0.3.0.md`](releases/0.3.0.md).

### 0.4.0 — Windows Product Shell Preview

Delivered the first product-shaped Windows installation before deeper capabilities, so a
non-technical user can install Provelume, open a local Instance and inspect the real
version/update lifecycle without installing Git or Python.

The preview includes a per-user Windows x64 installer with a bundled runtime; launcher/runtime and
Instance-data separation; default Instance creation and existing-Instance selection; local
start/stop/status/browser controls; EN/IT About identity; manual and opt-in startup update checks;
provider-independent Windows update metadata with an explicit initial GitHub Releases transport;
installer size/SHA-256 verification; user-confirmed installer handoff; uninstall that preserves
Instance data; release-bundle publication and Windows install/use/uninstall CI evidence.

It does not include Authenticode, independent publisher authentication, unattended update
application, runtime slots, automatic rollback, interrupted-update recovery, Instance migrations,
32-bit/ARM Windows or non-Windows desktop installers.

This independently releasable product shell displaced the former `0.4.0` forecast. At its
publication, every later unreleased `0.x` slot moved forward atomically through the then-current
`0.21.0` release candidate. The later productivity-connector insertion documented below moves the
current release candidate to `0.22.0`; stable `1.0.0` now depends on `0.22.0`. Earlier published
history remains unchanged. See [`releases/0.4.0.md`](releases/0.4.0.md).

## Forecast release-by-release

### 0.5.0 — Durable Ingestion and Extractor Completion

**Outcome:** turn filesystem ingestion from a vertical slice into a durable, observable and
recoverable subsystem.

**Includes:** persistent ingestion runs and per-item results; bounded per-item failure and retry;
versioned extractor capabilities; optional local OCR only after licensing/packaging review;
rename/removal/supersession provenance; incremental indexing with full rebuild recovery; Source
locking and synthetic scale limits.

**Exit gate:** interrupted and repeated ingestion is idempotent, malformed items do not discard
valid work, incremental and full-rebuild indexes agree, and OCR remains optional with no cloud
dependency.

**Not in this release:** network Sources or generic scheduling.

### 0.6.0 — Portable Instance Lifecycle

**Depends on:** `0.5.0` ingestion runs.

**Outcome:** make an Instance safely upgradeable, exportable and recoverable before network
Sources or end-user installers are introduced.

**Includes:** versioned schema and forward-only migrations with preflight; automatic backup;
failure restore/rollback; readable export with a deterministic Markdown library projection and
hash-validated import; Instance manifest; safe Markdown rendering in the built-in Viewer with
raw/original/download access; `validate`, `backup`, `restore`, `export` and `import`; crash
recovery; Windows/Linux path compatibility; explicit inclusion or rebuild of derived state.

**Exit gate:** N-1 to N migration, failure recovery and cross-platform export/import preserve
originals, versions and provenance; the Markdown projection and Viewer can be regenerated from
canonical state without mutating it.

**Not in this release:** multi-master synchronization or proprietary cloud storage.

### 0.7.0 — Connector Framework and Safe Web Intake

**Depends on:** `0.2.0` network transparency and `0.6.0` lifecycle.

**Outcome:** introduce the first network Source without coupling the Core to one vendor or
hiding external access.

**Includes:** provider-independent Source adapter and versioned capability/conformance manifest;
explicit network policy and external secret references; OAuth 2.0/PKCE authorization boundary for
installed apps; least-privilege scopes; separate provider, account and Source identities; manual
web acquisition with canonical URL and provenance; SSRF, reserved-address, DNS-rebinding and
redirect controls; response/resource limits; conditional metadata; preserved acquired original
plus derived readable text.

Every connector type is multi-instance by contract. A ConnectorDefinition describes reusable
adapter code and capabilities; each ConnectorInstance binds one endpoint, provider identity,
authorization, scope set and policy; each instance may expose any number of independently selected
Sources such as mailboxes, folders, calendars, workspaces, projects or feeds. Connector instances
have stable identities, isolated credentials, cursors, schedules and health. No adapter may rely on
a process-wide singleton account.

**Exit gate:** synthetic hostile-network fixtures fail closed, every acquisition is attributable,
and disabling network capability prevents access without a silent fallback.

**Not in this release:** broad connector catalogue or background scheduling.

### 0.8.0 — Refresh Engine and Source Lifecycle

**Depends on:** `0.7.0` Source contract.

**Outcome:** make refresh, retry and Source state durable without turning every poll into a new
document version.

**Includes:** bounded persistent jobs; manual/periodic/scheduled/conditional policies;
per-ConnectorInstance, per-account and per-Source cursors/checkpoints; conditional requests;
rate-limit handling; retry/backoff/cancellation; instance/Source locking and idempotency; explicit
active/paused/error/missing/superseded/reauthorization-required states; redacted network events
distinct from declared capability; last-attempt, last-success, next-run and bounded resync status.

**Exit gate:** unchanged bytes create no new version, retries are safe, and interrupted jobs
resume or fail visibly with bounded evidence.

### 0.9.0 — Email, Google File and Transcript Intake

**Depends on:** `0.8.0` refresh engine.

**Outcome:** validate the connector framework with communications, cloud files and transcripts
while keeping Gmail, Google Drive, Plaud and every other provider outside the domain model.

**Includes:** provider-neutral email, file and transcript Sources; local EML/mailbox adapter; a
Google connector preview with independently consented read-only Gmail and Drive capabilities;
thread/message/attachment and file/revision identity with deduplication; attachment extraction;
bounded export of supported Google-native files with export format and provenance preserved;
external secret references; transcript profile mapping into canonical documents; provider cursor
state kept inside each adapter.

**Exit gate:** re-import and refresh are idempotent, attachments and Drive revisions retain
provenance, revoked authorization fails visibly without corrupting canonical state, and provider
replacement does not migrate canonical knowledge.

**Not in this release:** Google Calendar, task-provider sync, email sending, or automatic claims,
decisions and tasks derived from communications or transcripts.

### 0.10.0 — Mobile Capture Inbox and Review Queue

**Depends on:** durable ingestion, Sources and the `0.8.0` refresh/job foundation.

**Outcome:** make intentional capture from a phone fast while keeping every submitted item in a
write-safe review flow rather than silently turning it into durable knowledge.

**Includes:** closed review states and transitions; a mobile-responsive Capture Inbox; a bounded,
append-only capture endpoint for files, photos/scans, screenshots, PDFs, URLs, text and audio/voice
notes; exact-original preservation with capture time, submitting device/channel and optional
user note/area; short-lived QR pairing and revocable per-device credentials; upload limits,
content-type verification, malware-safe handling boundary, offline outbox/retry and idempotent
submission.

A minimal mobile retrieval view provides recent captures, bounded full-text search, provenance
and version preview, and explicit authenticated original download without persistent device
caching by default.

Reference mobile paths include an iOS Shortcut exposed in the Share Sheet, an Android share-target
companion/reference client and direct camera/file-picker capture. A watched Google Drive drop
folder from `0.9.0` provides the first no-app fallback. A provider-neutral capture-relay contract
may be proven with one optional Telegram bot adapter that accepts only items explicitly sent or
forwarded to the configured bot/chat and declares that content traverses Telegram. Each device,
drop folder, bot and chat is a separate ConnectorInstance or Source.

The same Inbox provides proposal-before-mutation, separately scoped write API with idempotency and
audit journal, CSRF/session protection, user-managed area/tag classification, duplicate decisions
and links, and undo or compensation where technically possible. LAN use is supported first;
capture from outside the LAN requires an explicitly configured trusted network, VPN or hardened
HTTPS exposure rather than a mandatory Provelume cloud relay.

**Exit gate:** accepted, rejected and superseded transitions preserve originals and evidence;
duplicate, replayed, oversized, malformed and unauthorized submissions fail safely; device or bot
revocation stops future capture; queued mobile submissions retry without duplication; and capture
creates no automatic Claim, Decision, Task or CalendarEvent before review.

**Not in this release:** reading arbitrary private chats; automatic audio transcription; mandatory
cloud relay; WhatsApp Cloud API integration; or autonomous classification and durable writes.
WhatsApp remains a later candidate only through a dedicated Business number/API flow, never by
scraping or impersonating a personal WhatsApp account.

### 0.11.0 — Knowledge Objects v1

**Depends on:** `0.10.0` review flow.

**Outcome:** move beyond document-only knowledge with explicit canonical objects and evidence.

**Includes:** Entity/KnowledgeObject identities and aliases; Claims with Evidence references;
Decisions with state and rationale; provider-independent Task/Outcome and
CalendarEvent/Commitment; typed versioned Relations;
stable references independent of paths or GitHub; portable schema migration; minimal service/write
API and review workflow.

**Exit gate:** objects round-trip through export/import, retain provenance through document
version changes and never replace the authoritative original.

### 0.12.0 — Productivity Connectors and Guarded Sync Preview

**Depends on:** the `0.7.0` connector contract, `0.8.0` refresh engine, `0.10.0` review
queue and `0.11.0` provider-independent Task and CalendarEvent objects.

**Outcome:** connect common personal productivity systems without making Google, iCalendar,
Asana or Tududi part of canonical knowledge or granting background write authority by default.

**Includes:** multiple independently configurable instances for every provider. Google supports
multiple identities, with independently scoped Gmail, Drive and Calendar capabilities and
separately selected mailboxes, folders and calendars. iCalendar supports multiple local or HTTPS
ICS feeds with per-feed provenance, timezone, all-day, recurrence, exception and cancellation
handling. Asana supports multiple OAuth identities and, within each identity, multiple
organizations/workspaces, teams and projects as separate Sources. Tududi supports multiple server
endpoints, accounts and project/task scopes.

The adapters cover projects, tasks, subtasks, assignees, due dates, completion state, comments and
durable links; normalized Task/Outcome and CalendarEvent/Commitment mappings; adapter-isolated
provider extensions; per-instance read/write policy; least-privilege consent, external credential
references, reauthorization, connector health, cursor reset and bounded full resync.

Read intake is the default. A guarded task write-back preview is limited to a closed field set,
such as completion state and due date, and requires an explicit diff, human confirmation,
idempotency key, optimistic-concurrency check and privacy-minimizing audit receipt. Unsupported
Tududi or provider capabilities fail visibly instead of being emulated through private or
unstable interfaces.

**Exit gate:** multiple Google accounts, Asana identities/workspaces/projects, Tududi endpoints
and iCalendar feeds remain distinguishable; refresh and full resync are idempotent; recurrence and
cross-provider duplicates are explainable; revoked credentials stop access without damaging
imported knowledge; and a stale or replayed task write cannot overwrite newer provider state.
Local-only mode performs no connector access.

**Not in this release:** email sending; calendar create/update/delete; autonomous task creation or
deletion; generic two-way multi-master synchronization; or a mandatory 1.0 commitment for
additional adapters such as CalDAV, Microsoft 365, IMAP, Notion or Todoist.

This independently releasable outcome takes the former `0.12.0` slot. Every later unreleased
forecast moves forward atomically by one through the `0.22.0` release candidate. Published
history, the numbering and relative order of `0.5.0`–`0.11.0`, and stable `1.0.0` remain
unchanged; the connector-related scope expansions in `0.7.0`–`0.11.0` are explicit above.

### 0.13.0 — Knowledge Navigation, Relations and Deterministic Discovery

**Depends on:** `0.11.0` objects.

**Outcome:** make documents and objects coherently navigable and diagnosable before introducing
embeddings.

**Includes:** a mature Knowledge Browser/Viewer with classic Markdown-library and structured
navigation; area/Source/tag/type trees and breadcrumbs; recent, pinned and saved views; safe
rendered/raw/original document modes; outgoing links and backlinks; version/provenance timelines;
related document/object views with a visible reason for each suggestion; an optional secondary
relation graph; explainable stale/conflict/missing-evidence/superseded/orphaned health states;
deterministic detectors; full-text object/relation search; filters; documented ranking; portable
references and complete navigation/relation-index rebuild.

**Exit gate:** every health finding identifies its evidence and rule, deterministic rebuilds
agree, every related result explains its deterministic path, keyboard and mobile navigation reach
the same knowledge, and discovery remains fully useful without AI or a vector store.

### 0.14.0 — Knowledge API v1 and Read-only MCP

**Depends on:** stable object and discovery contracts.

**Outcome:** stabilize the shared client contract and prove that the browser contains no
exclusive business logic.

**Includes:** paginated and bounded Knowledge API v1 contracts; schemas and compatibility policy
for documents, objects, provenance, search, related and health; read/write scope separation;
a versioned capture-submission contract, a mobile read profile for recent/search/detail/
provenance/original-download and mobile-client conformance fixtures, all distinct from read-only
MCP tools for search and retrieval; aligned CLI/browser services; reference clients;
version negotiation and pre-1.0 deprecation policy.

**Exit gate:** at least two clients pass the same conformance fixtures and no interface exposes
unauthorized local paths, secrets or writes.

### 0.15.0 — AI Gateway and Privacy Routing

**Depends on:** `0.14.0` contracts and `0.2.0` network transparency.

**Outcome:** introduce inference as a replaceable adapter, never as the foundation of canonical
knowledge.

**Includes:** capability-based provider registry; deterministic fake adapter and at least one
optional OpenAI-compatible adapter; external secret references; source/data-category/local-only
policy; no silent cloud fallback; bounded budget, retry and cancellation; explicit provider and
network disclosure before execution.

**Exit gate:** local-only fails closed, provider substitution leaves canonical knowledge intact,
and denied data never reaches a provider in policy tests.

### 0.16.0 — AI Receipts, Provider Adapters and Evaluation

**Depends on:** `0.15.0` gateway.

**Outcome:** make AI-assisted proposals attributable, reviewable and replaceable.

**Includes:** privacy-aware receipts with capability/model/policy/template/source/output identity;
versioned templates; additional optional adapters behind the same capability contract; structured
object proposals; mandatory review for initial durable writes; sanitized conformance/evaluation
fixtures; provider replacement tests; configurable receipt retention with minimum provenance.

**Exit gate:** the same fixture can be evaluated across adapters, every durable proposal is
traceable to source and policy, and logs contain neither secrets nor raw private content.

### 0.17.0 — Semantic and Hybrid Search

**Depends on:** `0.16.0` gateway and receipts.

**Outcome:** add semantic retrieval while keeping embeddings entirely derived and replaceable.

**Includes:** separate embedding adapter; model/dimension/chunking identity and privacy policy;
local vector-store baseline plus optional adapters; complete rebuild from canonical state;
model/store migration; explainable full-text plus semantic ranking; consistent filters; stale,
incompatible and missing-index health.

**Exit gate:** delete-and-rebuild and provider-replacement tests preserve canonical objects,
privacy routing and deterministic fallback search.

### 0.18.0 — Self-hosted Operations

**Depends on:** `0.6.0` lifecycle and mature application contracts.

**Outcome:** make the public repository operable as a self-hosted product without GitHub at
runtime.

**Includes:** immutable packages/containers with build identity; supported runtime profile;
configuration separated from data; secret references; health/readiness and redacted logs;
documented init/start/stop/status/backup/restore/upgrade/rollback; N-1 to N migration; local
authentication for non-loopback exposure; provider-neutral reverse-proxy/TLS guidance.

**Exit gate:** a clean supported host can install, operate, upgrade, roll back and recover an
Instance using only published artifacts and documentation.

### 0.19.0 — Windows Bootstrap Completion

**Depends on:** the `0.4.0` product shell preview and `0.18.0` operations.

**Outcome:** converge the early Windows product shell with mature self-hosted lifecycle and
operations, completing the supported non-technical bootstrap rather than replacing the preview
with a second launcher.

**Includes:** hardened launcher/runtime/Instance separation; guided prerequisite and compatibility
detection; complete create/open/start/stop/status/browser/diagnostics behavior; redacted logs;
spaces, Unicode and case-insensitive path support; lifecycle-aware failure recovery; uninstall
that preserves the Instance; final bootstrap support matrix and migration from the `0.4.0`
preview installation.

**Exit gate:** install/use/uninstall and failure-recovery fixtures pass on supported Windows
targets without deleting user knowledge.

### 0.20.0 — Signed Windows Release and Safe Updater

**Depends on:** `0.19.0` bootstrap and the verified release chain.

**Outcome:** complete the Windows lifecycle with authenticated artifacts, backup, health and
rollback.

**Includes:** provider-independent signed release manifest and key lifecycle policy; Windows code
signing; pre-install signature/hash/compatibility verification; runtime slots separate from the
Instance; backup/migration/restart/health/automatic rollback; interrupted-update recovery;
Stable/Preview/Dev channels; pin/defer/disable policy; offline update bundle.

**Exit gate:** tampered, revoked, incompatible and interrupted updates fail safely, while the
previous healthy runtime and Instance remain recoverable.

### 0.21.0 — Business and Cloud Contracts Preview

**Depends on:** stable API, packaging and enforceable privacy boundaries.

**Outcome:** define reusable Business/Cloud contracts before accepting organizational data,
without creating a proprietary Core fork.

**Includes:** organization/workspace/tenant context with a simple personal default; owner/admin/
member/viewer RBAC; content-minimizing audit schema; administrative provider/Source/retention/
export policies; separated connector credential administration; tenant-aware exit path;
provider-neutral encryption/KMS boundary; isolation and authorization conformance tests.

**Exit gate:** personal self-hosted behavior remains intact and the same public contracts pass
cross-tenant isolation tests without vendor-specific domain logic.

### 0.22.0 — 1.0 Release Candidate

**Depends on:** every release required by the approved 1.0 support perimeter.

**Outcome:** freeze compatibility and exercise all 1.0 gates without adding a new feature stream.

**Includes:** Instance, Knowledge API/MCP and artifact contract freeze; supported migration,
upgrade and rollback matrix; export/import and Windows/Linux interoperability; no-GitHub,
no-external-AI and local-only tests; provider replacement and vector rebuild; at least two real
clients; synthetic performance limits; focused security review; complete licensing, notices,
support and deprecation documentation.

**Exit gate:** the candidate remains stable for the documented qualification period with all
1.0 blockers closed or explicitly removed from the support perimeter.

### 1.0.0 — Stable Provenance-first Platform

**Depends on:** successful `0.22.0` qualification.

**Outcome:** declare the proven support perimeter stable; do not add new functionality during
release preparation.

**Includes:** release-candidate fixes and hardening only; final version/changelog; migration,
compatibility and support policy; final artifacts, signatures, provenance, SBOM, verifier and
release notes; documentation of the actually available Community, Personal and Business
surfaces; immutable stable tag from the reviewed `main` result.

**Exit gate:** supported systems can install and verify the release, the Instance remains
portable, provider independence and no-AI/no-GitHub modes pass, update/rollback is supported,
trust/privacy claims are evidence-backed, and self-hosted, Dedicated and Cloud use the same
public Core contracts.

## Cross-cutting work without an activated release slot

- #1 — repository protection and security settings audit; this is a repository-setting outcome,
  not product runtime scope.
- #5 — optional local OCR and remaining ingestion inputs; the compatible subset is a candidate
  input to `0.5.0`, subject to clean-room, licensing and packaging review.
- #24 — immutable OCI builder lock and pinned-container cross-job rebuild evidence; this remains
  independent release-assurance hardening until an atomic planning change places it.
- Detached provider-independent signing, key rotation and revocation before any release that
  claims authenticated provider-independent origin.
- Observed runtime network-activity instrumentation and egress enforcement only after a separate
  privacy, platform and support decision.

This work is not part of `0.4.0` and receives a version only through an atomic planning change.
