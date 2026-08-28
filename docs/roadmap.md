# Public product roadmap

This roadmap is the canonical public release forecast for Provelume Core and the self-hosted
Instance. Published tags, dated changelog history and package identity remain immutable.
Forecast entries describe intended sequencing; they do not create an issue, owner pull
request, tag, release or delivery commitment. Planned-version movement follows
[`changelog-policy.md`](changelog-policy.md).

## Status vocabulary

- **Published preview** — immutable tag and public preview release exist.
- **Active implementation** — a canonical parent issue and exactly one current owner product pull
  request activate one bounded release slice; package identity and publication remain separate
  later steps.
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
| Published preview | `0.4.1` | Windows product shell hardening | #62 (completed) |
| Published preview | `0.5.0` | Durable ingestion, configurable local Inbox, document bundles and assurance | #66 and #72 (completed) |
| Next forecast | `0.6.0` | Portable Instance and hierarchical Markdown library | issue just in time |
| Forecast | `0.7.0` | Connector framework and safe web intake | issue just in time |
| Forecast | `0.8.0` | Refresh engine and Source lifecycle | issue just in time |
| Forecast | `0.9.0` | Email, Google file and transcript intake | issue just in time |
| Forecast | `0.10.0` | Unified Capture and Action Center | issue just in time |
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

The package and embedded identity are `0.5.0`. The `0.6.0` forecast is not active: only a
canonical issue and one owner product pull request may activate it and add product work under
`Unreleased`.

## Planning and delivery contract

- Activate one release at a time through one canonical parent issue and keep exactly one current
  owner product pull request for one homogeneous slice. Merge and close one slice's ownership
  before opening the next.
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

### Bounded development slices

Complex forecast releases are implemented through one homogeneous slice per agent turn and owner
pull request, with at most one owner slice open at a time. Planning IDs use `0.N/S01`, `0.N/S02`,
and so on; fine-tuning uses
`0.N/S01/F01`; a micro-adjustment may append `-a`, `-b`, and so on. These IDs create no tag,
package version or dated changelog heading.

Only a separately authorized installable checkpoint changes identity, using package versions such
as `0.5.0a1`, `0.5.0b1` or `0.5.0rc1` and matching SemVer tags such as
`v0.5.0-alpha.1`. Final publication remains `0.5.0`; later released corrections use `0.5.1`,
`0.5.2`, and so on. Collapsed forms such as `0.51` or `0.511` and letter-suffixed package versions
remain human shorthand only because they do not sort consistently across the Python package,
Windows updater and release tooling. See [`changelog-policy.md`](changelog-policy.md).

## Knowledge representation and navigation contract

Markdown is the first-class portable, human-facing format for classic knowledge reading and
navigation; it is not the sole canonical storage model or a second database. Exact acquired files,
including user-authored Markdown, remain preserved under `originals/`. Canonical identities,
versions, objects, relations and provenance remain readable JSON under `knowledge/`. Provelume may
build deterministic Markdown library projections with stable links and portable metadata, but
those projections are derived, rebuildable and never silently overwrite an original or canonical
record.

For a PDF, the exact acquired bytes remain the authoritative Original. A versioned document bundle
provides normalized Markdown, a page map, referenced images/tables and other bounded assets. An
optional viewing/mobile-optimized PDF is a separately hashed derived artifact with a recorded
recipe and quality policy; it never replaces a signed, encrypted or otherwise authoritative
original. Agents later use the Markdown bundle by default and may retrieve a source page or the
Original when extraction is incomplete or ambiguous.

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

The filesystem is a supported navigation surface, not only an implementation detail. The durable
`library/` projection has a root README, hierarchical Area/Subarea and Project paths, per-folder
README indexes, Archive and generated tag/person/Source/date/type views. Every document has one
primary library path and may have multiple secondary classifications without duplicate knowledge.
Area, Project and Collection identities are stable and parent-linked, so renaming or moving a
folder changes neither document identity nor provenance. The built-in Viewer mirrors the same
hierarchy; the library remains understandable with Provelume stopped.

## Original assurance and decision contract

After a successful hash-verified acquisition commits, routine ingestion, classification,
deduplication, refresh, source disappearance and library rebuild workflows do not overwrite or
delete the acquired Original. Exact duplicate bytes are stored once by content identity, while
each Source observation remains a separate Acquisition. Moving a document between Areas or
Projects changes only canonical classification and rebuildable projections. Staging copies and
derived artifacts have separate, explicit retention policies.

User-directed erasure remains possible without a misleading absolute retention promise. Archive,
remove-from-library, recoverable trash and permanent purge are distinct actions. Purge requires an
impact preview, explicit confirmation, disclosure of known backup/replica boundaries and a
privacy-minimizing receipt; it is never inferred from rejecting an Inbox item, removing a Source
or finding a duplicate. Connector reads do not delete or move provider content by default.

A single `Needs attention` Action Center exposes typed queues for intake, classification,
exact/probable duplicates, version conflicts, extraction errors, Source changes, retention and
later AI proposals. Each item shows preview, provenance/hash, proposed action, reason/confidence,
impact and reversibility. Confirmed rules may automate only bounded non-destructive routing;
destructive or identity-changing decisions always require a human action.

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
- compare installed Core package bytes with released wheel bytes;
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

### 0.4.1 — Windows Product Shell Hardening

Hardened the published `0.4.0` Windows shell without adding a new product capability. The patch
keeps one per-user x64 product identity and the existing Instance format while correcting moved-
Instance recovery, backend readiness and failure reporting, console-free frozen startup, release-
tag/commit validation and reduced-window/DPI behavior.

Release evidence installs the immutable public `0.4.0` executable before the candidate, preserves
a synthetic Instance and launcher settings through upgrade and uninstall, and exercises the
bundled runtime, shortcuts, Unicode paths, EN/IT layout probes and update safety boundaries. The
preview remains unsigned, user-confirmed and non-automatic. See
[`releases/0.4.1.md`](releases/0.4.1.md).

### 0.5.0 — Durable Ingestion, Configurable Local Inbox and Document Bundles

Delivered the five bounded implementation slices from issue #66 and the final configurable-folder
workstream from issue #72:

- persistent ingestion run/item records, per-item failure isolation and explicit crash-safe retry;
- a filesystem Drop Inbox with copy by default and move-after-commit only after exact-byte
  preservation, hash verification and committed Acquisition evidence;
- a navigable, path-redacted operation log for Inbox, bundle, duplicate, assurance, settings and
  rebuild activities;
- deterministic document bundles containing normalized Markdown, page map and bounded assets;
- exact duplicate occurrence preservation plus conservative probable-duplicate review evidence;
- read-only Original assurance with no automatic repair;
- exclusive rebuild locking and normalized incremental/full agreement evidence;
- configurable Inbox display name, Drop folder and managed-copy folder, including external local
  filesystem locations while canonical storage remains inside the Instance.

Exact duplicate bytes may share one content-addressed Original, but every drop or Source observation
retains its own Acquisition and routing evidence. Probable duplicates are not silently merged. No
input is moved before a committed hash-verified acquisition, and a missing external mount is not
silently recreated. See [`releases/0.5.0.md`](releases/0.5.0.md).

## Forecast release-by-release

### 0.6.0 — Portable Instance and Hierarchical Markdown Library

**Depends on:** `0.5.0` ingestion runs.

**Outcome:** make an Instance safely upgradeable, exportable, recoverable and directly navigable
on its filesystem before network Sources or end-user installers are introduced.

**Includes:** versioned schema and forward-only migrations with preflight; automatic backup;
failure restore/rollback; readable export with a deterministic Markdown library projection and
hash-validated import; Instance manifest; stable parent-linked Area/Subarea, Project and Collection
classification identities; one primary library path plus multiple secondary associations; root
and per-folder README indexes; `areas/`, `projects/`, `archive/` and generated tag/person/Source/
date/type views without duplicate originals; Windows-safe deterministic slugs and moves; safe
Markdown rendering in the built-in Viewer with raw/original/download access; distinct archive,
remove-projection, recoverable-trash and explicit-purge semantics; `validate`, `backup`, `restore`,
`export` and `import`; crash recovery; Windows/Linux path compatibility; explicit inclusion or
rebuild of derived state.

**Exit gate:** N-1 to N migration, failure recovery and cross-platform export/import preserve
originals, versions and provenance; the Markdown projection and Viewer can be regenerated from
canonical state without mutating it; Area/Project rename or movement preserves stable references;
and no classification or library operation deletes an Original. Permanent purge proves explicit
authorization and reports known backup/replica limits instead of claiming broader erasure.

**Not in this release:** autonomous classification, multi-master synchronization or proprietary
cloud storage.

**Suggested slices:** `0.6/S01` schema migration, backup and recovery; `0.6/S02` stable
Area/Subarea/Project/Collection hierarchy; `0.6/S03` filesystem library, README indexes and
Viewer parity; `0.6/S04` archive/trash/purge and retention boundaries; `0.6/S05` portable
export/import and cross-platform qualification.

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

The initial connector capability is read intake. Provider deletion or movement is a separate
future write capability and Source disappearance never cascades into deletion of an acquired
Original.

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

### 0.10.0 — Unified Capture and Action Center

**Depends on:** durable ingestion, hierarchical classification, Sources and the `0.8.0`
refresh/job foundation.

**Outcome:** unify local, connector and mobile capture decisions in one evidence-backed Action
Center rather than silently turning submitted items into durable or destructively changed
knowledge.

**Includes:** closed review states and transitions; a mobile-responsive Capture Inbox and
`Needs attention` Action Center; typed intake/classification/exact-duplicate/probable-duplicate/
version-conflict/extraction-error/Source-change/retention queues; a bounded,
append-only capture endpoint for files, photos/scans, screenshots, PDFs, URLs, text and audio/voice
notes; exact-original preservation with capture time, submitting device/channel and optional
user note/Area/Project; short-lived QR pairing and revocable per-device credentials; upload
limits, content-type verification, malware-safe handling boundary, offline outbox/retry and
idempotent submission.

A minimal mobile retrieval view provides recent captures, bounded full-text search, provenance
and version preview, and explicit authenticated original download without persistent device
caching by default.

Reference mobile paths include an iOS Shortcut exposed in the Share Sheet, an Android share-target
companion/reference client and direct camera/file-picker capture. A watched Google Drive drop
folder from `0.9.0` provides the first no-app fallback. A provider-neutral capture-relay contract
may be proven with one optional Telegram bot adapter that accepts only items explicitly sent or
forwarded to the configured bot/chat and declares that content traverses Telegram. Each device,
drop folder, bot and chat is a separate ConnectorInstance or Source.

Each Action Center item provides proposal-before-mutation, preview, provenance/hash, reason and
confidence, impact, reversibility and a bounded choice set. Users can confirm or correct
hierarchical Area/Project placement, create a reusable non-destructive routing rule, link an exact
duplicate occurrence, or choose new-version/separate/related handling for probable duplicates.
Destructive and identity-changing decisions never become automatic rules.

The same Inbox provides a separately scoped write API with idempotency and audit journal,
CSRF/session protection, distinct archive/remove-projection/trash/purge decisions and undo or
compensation where technically possible. Rejection quarantines an acquisition according to an
explicit retention policy; it does not imply purge. LAN use is supported first;
capture from outside the LAN requires an explicitly configured trusted network, VPN or hardened
HTTPS exposure rather than a mandatory Provelume cloud relay.

**Exit gate:** accepted, rejected and superseded transitions preserve originals and evidence;
duplicate, replayed, oversized, malformed and unauthorized submissions fail safely; device or bot
revocation stops future capture; queued submissions retry without duplication; exact duplicates
retain every Acquisition; probable duplicates remain separate until decided; ignored queue items
cause no destructive action; and capture creates no automatic Claim, Decision, Task or
CalendarEvent before review.

**Not in this release:** reading arbitrary private chats; automatic audio transcription; mandatory
cloud relay; WhatsApp Cloud API integration; or autonomous classification and durable writes.
WhatsApp remains a later candidate only through a dedicated Business number/API flow, never by
scraping or impersonating a personal WhatsApp account.

**Suggested slices:** `0.10/S01` Action Center state model and local queues; `0.10/S02`
classification/duplicate/version-conflict decisions and reusable safe routing; `0.10/S03` mobile
capture, device pairing and offline retry; `0.10/S04` iOS, Android, Drive-drop and Telegram
reference paths; `0.10/S05` mobile retrieval, authorization and end-to-end assurance fixtures.

### 0.11.0 — Knowledge Objects v1

**Depends on:** `0.10.0` review flow.

**Outcome:** move beyond document-only knowledge with explicit canonical objects and evidence.

**Includes:** Entity/KnowledgeObject identities and aliases; Claims with Evidence references;
Decisions with state and rationale; the stable Project/Collection identities introduced for the
filesystem library promoted without replacement into the object model; provider-independent
Task/Outcome and CalendarEvent/Commitment; typed versioned Relations;
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

Connector items can propose routing into existing Areas and Projects, but only confirmed
non-destructive rules may apply that routing automatically. No connector deletion is inferred from
local archive, deduplication, Source removal or permanent purge.

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
unchanged; the Inbox/library/assurance expansions in `0.5.0`, `0.6.0` and `0.10.0`, and the
connector-related scope expansions in `0.7.0`–`0.11.0`, are explicit above.

### 0.13.0 — Knowledge Navigation, Relations and Deterministic Discovery

**Depends on:** `0.11.0` objects.

**Outcome:** make documents and objects coherently navigable and diagnosable before introducing
embeddings.

**Includes:** a mature Knowledge Browser/Viewer over the existing filesystem library and
structured objects; Area/Subarea/Project/Collection and Source/tag/type trees with breadcrumbs;
per-folder outlines and ordered/pinned sections; recent and saved views; safe
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
for documents, hierarchical classification, Action Center queues, objects, provenance, search,
related, retention and health; read/write scope separation with permanent purge excluded from
read-only clients and MCP;
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
optional OpenAI-compatible adapter; a bounded agent document-context contract that selects
normalized Markdown, page map and minimum required assets by default and retrieves source pages or
the Original only when permitted and needed; external secret references; source/data-category/
local-only policy; no silent cloud fallback; bounded budget, retry and cancellation; explicit
provider and network disclosure before execution.

**Exit gate:** local-only fails closed, provider substitution leaves canonical knowledge intact,
and denied data never reaches a provider in policy tests.

### 0.16.0 — AI Receipts, Provider Adapters and Evaluation

**Depends on:** `0.15.0` gateway.

**Outcome:** make AI-assisted proposals attributable, reviewable and replaceable.

**Includes:** privacy-aware receipts with capability/model/policy/template/source/output identity;
versioned templates; additional optional adapters behind the same capability contract; structured
object and classification proposals delivered through the same Action Center; immutable separation
between extracted Markdown and AI-authored output; mandatory review for initial durable writes;
sanitized conformance/evaluation fixtures; provider replacement tests; configurable receipt
retention with minimum provenance.

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
authentication for non-loopback exposure; provider-neutral reverse-proxy/TLS guidance; retention
and purge reporting that distinguishes the live Instance from backups and external replicas.

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
- #5 — optional local OCR and remaining ingestion inputs; OCR was not included in `0.5.0` and
  requires a future clean-room, licensing, packaging and support decision.
- #24 — immutable OCI builder lock and pinned-container cross-job rebuild evidence; this remains
  independent release-assurance hardening until an atomic planning change places it.
- Detached provider-independent signing, key rotation and revocation before any release that
  claims authenticated provider-independent origin.
- Observed runtime network-activity instrumentation and egress enforcement only after a separate
  privacy, platform and support decision.

This work is not part of `0.5.0` and receives a version only through an atomic planning change.
