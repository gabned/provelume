# Public product roadmap

This roadmap is the canonical public release forecast for Provelume Core and the self-hosted
Instance. Published tags, dated changelog history and package identity remain immutable.
Forecast entries describe intended sequencing; they do not create an issue, owner pull
request, tag, release or delivery commitment. Planned-version movement follows
[`changelog-policy.md`](changelog-policy.md).

## Status vocabulary

- **Published preview** — immutable tag and public preview release exist.
- **Active development** — a canonical parent tracker exists; completed slices remain recorded and
  a next slice may stay forecast-only between owner pull requests.
- **Active implementation** — a canonical parent issue and exactly one current owner product pull
  request activate one bounded release slice; package identity and publication remain separate
  later steps.
- **Release preparation** — all implementation slices are complete and one reviewed product pull
  request aligns package identity and release evidence; no tag or public release exists yet.
- **Next forecast** — first intended product increment after the published baseline, not yet
  activated until a canonical issue and one owner pull request exist.
- **Forecast** — ordered portfolio slot whose scope may still be refined before activation.
- **Release candidate** — compatibility-freeze and validation release, not general availability.
- **Stable** — the supported 1.0 contract after release-candidate exit gates pass.

## Release lane

| State | Version | Product outcome | Activation | Latin name |
| --- | --- | --- | --- | --- |
| Published preview | `0.1.0` | Local provenance-first Instance and verified release foundation | #40 (completed) | `Fundamentum` |
| Published preview | `0.2.0` | Local Installation Trust and Privacy & Network Activity transparency | #50 (merged) | `Fiducia` |
| Published preview | `0.3.0` | Anchored Local Installation Trust | #52 (completed) | `Ancora` |
| Published preview | `0.4.0` | Windows product shell preview | #57 (completed) | `Fenestra` |
| Published preview | `0.4.1` | Windows product shell hardening | #62 (completed) | `Robur` |
| Published preview | `0.5.0` | Durable ingestion, configurable local Inbox, document bundles and assurance | #66 and #72 (completed) | `Ingressus` |
| Published preview | `0.5.1` | Stability, security, incremental indexing and accessibility hardening | #80 (completed) | `Firmitas` |
| Published preview | `0.6.0` | Portable Instance and hierarchical Markdown library | #95 (completed) | `Bibliotheca` |
| Published preview | `0.6.1` | Purge integrity and ingestion serialization correction | #102 (completed) | `Integritas` |
| Published preview | `0.7.0` | Connector framework and safe web intake | #105 (completed) | `Vinculum` |
| Published preview | `0.8.0` | Scheduler, watched folders and recoverable maintenance | #122, #124, #126, #128 and #130 (completed) | `Vigilia` |
| Active development | `0.9.0` | OCR, email, Google file and transcript intake | #137; S01 completed by #5/#138 | `Lectio` |
| Forecast | `0.10.0` | Unified Capture, Operations and Action Center | issue just in time | `Cura` |
| Forecast | `0.11.0` | Knowledge Objects v1 | issue just in time | `Entitas` |
| Forecast | `0.12.0` | Productivity connectors and guarded sync preview | issue just in time | `Concordia` |
| Forecast | `0.13.0` | Knowledge navigation, statistics, relations and deterministic discovery | issue just in time | `Itinerarium` |
| Forecast | `0.14.0` | Knowledge API v1, read-only MCP and client connections | issue just in time | `Interfacies` |
| Forecast | `0.15.0` | AI gateway and privacy routing | issue just in time | `Custodia` |
| Forecast | `0.16.0` | AI classification, receipts, provider adapters and evaluation | issue just in time | `Iudicium` |
| Forecast | `0.17.0` | Semantic, hybrid and grounded RAG retrieval | issue just in time | `Sensus` |
| Forecast | `0.18.0` | Self-hosted, Synology and QNAP operations | issue just in time | `Domus` |
| Forecast | `0.19.0` | Windows and macOS background agents and bootstrap completion | issue just in time | `Excubitor` |
| Forecast | `0.20.0` | Signed desktop releases and safe updaters | issue just in time | `Renovatio` |
| Forecast | `0.21.0` | Business and Cloud contracts preview | issue just in time | `Societas` |
| Release candidate | `0.22.0` | 1.0 compatibility freeze and end-to-end qualification | issue just in time | `Probatio` |
| Stable | `1.0.0` | Stable provenance-first platform | issue just in time | `Maturitas` |

### Release names and concise outcomes

Each release has one unique Latin codename for human-facing planning and communication. These
names do not replace SemVer, package identity, tags or the immutable published release history.

- **`0.1.0` — `Fundamentum`.** Establishes the local provenance-first Instance, deterministic
  ingestion, browsing and search. It also establishes the verified build and release foundation.
- **`0.2.0` — `Fiducia`.** Makes local installation consistency independently checkable. It also
  exposes network capability and configuration without claiming that unobserved traffic occurred.
- **`0.3.0` — `Ancora`.** Anchors installation trust to an operator-supplied offline release
  bundle. Installed bytes can be compared directly with the wheel published for that release.
- **`0.4.0` — `Fenestra`.** Introduces the first per-user Windows installer, launcher and managed
  runtime. Update checks remain manual or explicitly enabled by the user.
- **`0.4.1` — `Robur`.** Hardens startup, moved-Instance recovery, display scaling and update
  validation. User data remains preserved through supported upgrade and uninstall paths.
- **`0.5.0` — `Ingressus`.** Adds a durable Inbox, ingestion log, document bundles, duplicate
  handling and configurable folders. Originals are preserved before any managed file move.
- **`0.5.1` — `Firmitas`.** Strengthens security, performance and accessibility across the local
  product. Incremental indexing retains a deterministic fallback and explicit recovery behavior.
- **`0.6.0` — `Bibliotheca`.** Adds schema migration, backup, portable transfer and a hierarchical
  Markdown library. Archive, trash and purge remain explicit lifecycle operations.
- **`0.6.1` — `Integritas`.** Corrects purge integrity and serializes competing ingestion work.
  It deliberately adds no new product feature or schema boundary.
- **`0.7.0` — `Vinculum`.** Introduces connector and Source identities, OAuth with PKCE and guarded
  manual web acquisition. Background refresh remains outside this release boundary.
- **`0.8.0` — `Vigilia`.** Adds a user-controlled scheduler, watched folders and a durable job
  lifecycle. Refresh, reindex, maintenance, interruption recovery and resource use stay governed.
- **`0.9.0` — `Lectio`.** Adds local OCR and richer intake for scanned files, email, Google files
  and transcripts. Cloud extraction is never an unannounced requirement or fallback.
- **`0.10.0` — `Cura`.** Unifies capture, mobile access, review and operations/maintenance queues
  in one Action Center. Interrupted work and every destructive choice remain explicit.
- **`0.11.0` — `Entitas`.** Adds evidence-linked objects, claims, decisions, tasks, calendar items
  and relations. Derived structure remains traceable to exact Originals and canonical records.
- **`0.12.0` — `Concordia`.** Adds productivity connectors, guarded task synchronization and
  optional one-way Git, local-folder and rsync mirrors. No mirror provider becomes canonical
  storage or a runtime requirement.
- **`0.13.0` — `Itinerarium`.** Adds navigation, backlinks, health, local statistics and capacity
  views. Deterministic discovery and legacy import remain explainable and fully reconcilable.
- **`0.14.0` — `Interfacies`.** Stabilizes Knowledge API v1 plus desktop, mobile and read-only MCP
  client profiles. ChatGPT and optional native clients need neither Git sync nor public exposure.
- **`0.15.0` — `Custodia`.** Adds a replaceable AI gateway with local, remote and fallback policy
  by scope. Privacy, redaction, budgets and network use remain visible and user-controlled.
- **`0.16.0` — `Iudicium`.** Adds guarded AI classification, receipts, review rules and provider
  evaluation. The end-to-end intake flow resists prompt injection and keeps every catalog action
  reviewable or reversible.
- **`0.17.0` — `Sensus`.** Adds semantic, hybrid and grounded RAG retrieval across canonical
  knowledge. Chunks, embeddings and indexes remain derived and rebuildable, while every context
  passage stays bound to exact source evidence.
- **`0.18.0` — `Domus`.** Qualifies self-hosted, Synology and QNAP operation with containers,
  rsync/SSH backup transport and restore evidence. Capacity, upgrade and rollback boundaries stay
  explicit.
- **`0.19.0` — `Excubitor`.** Adds Windows tray and macOS menu-bar agents with start-at-login
  operation. Watched intake and maintenance can continue while the interface is closed and can
  always be paused.
- **`0.20.0` — `Renovatio`.** Adds signed Windows and notarized macOS artifacts with safe updaters.
  Manual, notification-only and controlled-automatic modes retain verification and rollback.
- **`0.21.0` — `Societas`.** Introduces organization, workspace, tenant and role contracts without
  forking Core. Encryption and administrative boundaries remain explicit and portable.
- **`0.22.0` — `Probatio`.** Freezes the intended 1.0 compatibility surface for end-to-end,
  security, recovery and support qualification. Release-candidate evidence decides stable readiness.
- **`1.0.0` — `Maturitas`.** Establishes the stable support perimeter and finalized public
  contracts, artifacts and operating paths. It is a maturity gate, not a container for late new
  features.

## Public website synchronization contract

[`provelume.com`](https://provelume.com/) is a public projection of released facts and explicitly
labelled forecast direction; it does not activate work, replace this roadmap or make an unreleased
capability available. Every page distinguishes the website build identity from the latest
published Core release. An ambiguous footer such as `Provelume vX` is prohibited unless it says
whether X identifies the site or Core. English and Italian pages, release links, `facts.json`,
`llms.txt`, feature availability and the Wishlist move in one reviewable website change or retain a
visible last-verified date and known mismatch.

An immediate bounded website workstream should align the homepage, Features, Public facts,
Wishlist and machine-readable records with published Core `0.8.0`, including the completed
`0.5.0`–`0.8.0` capabilities and an exact `v0.8.0` evidence link. It must label the active
`0.9/S01` contract as unreleased and unavailable, and keep every later capability planned. This
website-only correction can begin now and changes neither the Core package identity nor release
history.

After every verified Core tag and asset publication, the website receives a bounded availability
sync in the same delivery cycle: current version/release link, supported platforms and formats,
newly available features, limitations, security/privacy implications, upgrade path and
documentation are updated from release evidence. Forecast changes update only the Wishlist/roadmap
view and keep `planned`, `preview`, `release candidate` and `available` visually distinct. A
website-only deployment increments only its own build identity; a hotfix updates affected facts
and download links without inventing a marketing milestone.

The larger editorial updates belong at these evidence gates:

| Evidence gate | Website update | Appropriate audience action |
| --- | --- | --- |
| Now, published `0.8.0` | Correct version/build labels, Features, Facts, Wishlist and release links in EN/IT; add bounded scheduler, folder-Source, recovery and maintenance documentation. | Invite a small technical early-adopter group for the capabilities actually published in Vigilia; keep active Lectio work visibly unavailable until publication. |
| Published `0.9.0` | Add OCR/input-format, language, quality and local/cloud privacy matrices. | Invite document-heavy users with an explicit supported-format perimeter. |
| Published `0.10.0` | Rework the primary use-case path around Capture, Action Center, Operations and mobile PWA onboarding. | Begin a controlled public beta: this is the first coherent daily-use experience. |
| Published `0.12.0` | Add an integrations/mirrors chooser for Git, local folders and rsync with one-way and deletion boundaries. | Reach users who need portable publication or NAS mirrors without implying mandatory GitHub. |
| Published `0.14.0` | Publish Knowledge API, MCP, ChatGPT, client-permission and mobile/native conformance guides. | Begin developer/client dissemination with copyable, versioned connection examples. |
| Published `0.17.0` | Add grounded RAG, citation, privacy-routing, index-health and evaluation explanations. | Reach AI/RAG evaluators only after citation and permission-isolation evidence exists. |
| Published `0.18.0` | Add Linux, Synology and QNAP deployment, backup/restore and support-matrix pages. | Broaden to self-hosted and NAS users after published restore evidence. |
| Published `0.20.0` | Add a download centre for signed Windows and notarized macOS installers, channels and updater policies. | Start broad non-technical desktop-preview distribution after rollback qualification. |
| Published `0.21.0` | Explain actual Business/Cloud contract status, roles and exit paths without implying a managed service exists. | Speak to organizations only within the published preview perimeter. |
| Published `0.22.0` | Publish the release-candidate matrix, migrations, known limits, feedback/security paths and 1.0 blockers. | Begin broad release-candidate diffusion and structured qualification. |
| Published `1.0.0` | Make stable install/download the primary call to action and publish final editions, support and compatibility facts. | Begin general distribution only for the support perimeter proven by `0.22.0`. |

Every website deployment checks EN/IT semantic parity, current release and checksum/provenance
links, planned-versus-available badges, internal links, structured facts, accessibility,
performance and the declared analytics/form/third-party-resource posture. The site never receives
private Instance content, unpublished roadmap claims or release credentials, and a website outage
cannot block installation or verification through the public repository.

Published package and embedded identity are aligned to `0.8.0`. Issues #122, #124, #126, #128 and
#130 completed `0.8/S01` through `0.8/S05`; their implementation PRs #123, #125, #127, #129 and
#131 are merged on `main`. The release-blocking scheduler correction was completed through
#133/#134, and release preparation was merged through #135.

The immutable [`v0.8.0`](https://github.com/gabned/provelume/releases/tag/v0.8.0) tag resolves to
commit `d20e63079adf85829723cab86766266a8bc6cdcd`. Official release workflow run
[`33315580878`](https://github.com/gabned/provelume/actions/runs/33315580878) published the public
prerelease with 22 unique, nonempty assets; API digests, `SHA256SUMS`, package identities and both
offline bundle verifiers were observed successfully. `0.9.0 Lectio` is active development under
parent tracker [#137](https://github.com/gabned/provelume/issues/137). Its first bounded slice was
completed through [#5](https://github.com/gabned/provelume/issues/5) and owner
[PR #138](https://github.com/gabned/provelume/pull/138): it defines the local/offline contract,
licensing and optional packaging without changing the published `0.8.0` identity or claiming that
OCR execution is already available. `0.9/S02` remains the next forecast-only slice with no issue,
branch or owner pull request.

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

## User-controlled automation and interoperability contract

Capabilities that can observe files, contact a network service, send content to an inference
provider, publish a mirror or install an update expose distinct user-selectable modes rather than
one ambiguous automation switch. Where technically applicable the modes are **disabled/offline**,
**manual**, **assisted with confirmation** and **controlled automatic**. The default remains the
least-networked non-destructive mode, and changing mode records a privacy-minimizing operation.

Mode and policy may be set at Instance, ConnectorInstance, Source and, where data handling needs
it, Area or Project scope. The narrowest explicit policy wins; a child may further restrict but
never silently broaden a parent network, data-category, retention or write boundary. A dry run,
impact preview, pause/resume control, bounded resource schedule and visible last/next-action state
remain available wherever background work exists. Destructive, identity-changing and external
provider-write actions never become unconfirmed automation merely because a broader mode is on.

Direct API/MCP access and portable export remain the primary provider-independent integration
surfaces. A Git-backed mirror is an optional compatibility and human-navigation surface, not
canonical storage, mandatory backup or a runtime dependency. GitHub, GitLab, Gitea and another
standards-compatible remote may be qualified behind the same Git capability; local-only and
no-GitHub modes remain complete product paths.

## Scheduling, maintenance and local observability contract

Every refresh, watcher, reindex, rebuild, validation, assurance, backup or maintenance capability
uses one durable job contract rather than its own hidden timer. Where applicable a user may choose
disabled, run now, fixed interval, local calendar schedule, event-assisted or conditional
execution at Instance or narrower Source scope. Policies expose timezone, daylight-saving
behavior, earliest/latest window, quiet hours, bounded jitter, minimum interval, concurrency and
CPU, battery, metered-network, bandwidth and disk limits. Last attempt, last success, next due
time, policy revision and the reason a run executed, waited, coalesced or was skipped remain
visible.

Downtime never creates an unbounded catch-up storm. Each policy explicitly chooses skip,
coalesce-to-one or one bounded catch-up after restart, sleep/wake, clock correction or mount
reconnection. Retry uses typed transient/permanent failures, capped exponential backoff and a
user-visible retry time; provider rate limits can lengthen but never silently shorten a user's
minimum interval.

Jobs carry stable identity, kind, scope, idempotency key, policy revision, attempt, lease,
heartbeat, checkpoint, progress and a terminal receipt. After interruption, stale leases are
detected and the job becomes resumable, safely restartable or manual-intervention-required rather
than falsely successful. Resume begins only from a committed checkpoint; replay cannot create a
second Acquisition, Version, index generation, backup or external publication. Users may pause,
resume, retry, cancel or restart when that action is safe, while force repair and generic
`fix everything` controls remain excluded.

The maintenance catalogue distinguishes rebuildable work from canonical mutation. Incremental or
full search reindex, Markdown-library rebuild, Source reconciliation, Instance validation,
Original assurance, duplicate scan, backup creation/verification and redacted diagnostics may be
manual or scheduled once their owning release supports them. Full rebuilds expose estimated work,
free-space preflight and a dry run where meaningful. A repair that changes canonical state remains
a separate preview, backup and confirmation flow; a schedule never upgrades a read-only check into
automatic repair, purge or retention deletion.

Local statistics are derived, timestamped and rebuildable from canonical manifests and bounded
operation evidence. They report counts and exact bytes for Sources, Acquisitions, Documents,
Versions, Originals, derived bundles, indexes, library projections, queues, trash and configured
backup inventories, with filters by type, Source, Area, Project, status and time. Growth,
throughput, duplicate reuse/storage savings, extraction/OCR coverage, queue age, job duration and
failure rate may be summarized; disk-exhaustion forecasts are labelled estimates with their
window and assumptions. Every view distinguishes canonical, derived, cache and external-replica
bytes so a number cannot be mistaken for reclaimable space.

Statistics and diagnostics perform no telemetry or implicit network access. Document content,
sensitive titles, secrets and physical paths are excluded from aggregate exports by default; a
content-free support bundle contains only explicit selected configuration classes, build identity,
redacted health, job receipts and checksums. Threshold notifications link to the evidence and safe
response, while low space pauses new acquisitions before integrity is endangered and never
triggers silent deletion.

## Client and platform contract

The responsive Knowledge Browser and versioned API remain complete baseline clients; desktop or
mobile applications do not own exclusive business logic or canonical state. Capabilities are
declared per client and support level, and an unsupported platform path fails visibly rather than
silently dropping capture, background work or security controls.

Mobile delivery starts with an installable responsive web/PWA surface, revocable device pairing,
offline capture outbox and explicit iOS Share Sheet/Shortcut and Android share-target reference
paths in `0.10.0`. Camera, file, photo/scan, screenshot, URL, text and voice-note capture are
separate user actions. Minimal recent/search/detail/provenance retrieval can avoid persistent
device caching; offline knowledge copies, biometric unlock and content-bearing push notifications
remain independently consented capabilities. Every non-loopback browser connection, including a
phone on the LAN or a trusted VPN/private tunnel, requires authenticated HTTPS for installation,
service-worker offline behavior and the PWA share target. Any explicitly supported plain-HTTP
fallback disables those capabilities visibly. No connection choice requires a Provelume cloud
relay.

`0.14.0` freezes mobile client profiles and conformance fixtures so optional native iOS and Android
companions or third-party clients can replace the reference paths without changing Core. Native
app-store distribution is a separately qualified delivery decision, not a prerequisite for the
PWA, API or self-hosted product. Device loss or revocation stops future access without deleting
knowledge already preserved in the Instance.

`0.19.0` adds a qualified macOS application/menu-bar and per-user LaunchAgent beside the Windows
launcher/tray agent. Selected-folder access, Keychain credential references, path normalization,
sleep/wake, removable/network volumes, Apple Silicon and any retained Intel support are explicit
matrix entries. `0.20.0` then adds Windows code signing and macOS Developer ID signing,
notarization and stapling; Time Machine and other host backups remain external replicas until a
Provelume manifest verification proves a restorable backup.

## Grounded retrieval and RAG contract

RAG is a versioned retrieval interface over canonical Provelume knowledge, not another canonical
store, an opaque chat history or a requirement to publish documents to Git. Deterministic
full-text retrieval is available first; `0.14.0` freezes its API/MCP contract and `0.17.0` adds
semantic and hybrid ranking behind that same contract. A Git or filesystem mirror may remain an
independently selected client context, but direct API/MCP retrieval is the authoritative path for
current permissions, provenance and index freshness.

Authorization and Source/Area/Project filters run before candidate text reaches ranking, caching
or a model. Search returns bounded result handles rather than ambient filesystem access. Context
assembly resolves those handles into excerpts carrying a stable evidence reference, Document and
Version identity, Original hash, page/section/span where available, extraction identity, index
generation, freshness and ranking components. Truncation is explicit, citations remain openable,
and an absent, stale or unauthorized passage cannot be silently substituted.

Chunking profiles are versioned by parser, boundaries, overlap and tokenizer/model assumptions.
Chunks, embeddings, vector indexes, reranking features and answer caches are derived generations:
they can be invalidated and rebuilt from canonical Versions without changing knowledge. A
committed Version schedules incremental indexing; deletion, scope change and revocation invalidate
affected candidates before the next query. If a semantic generation is unavailable or stale, the
request visibly falls back to authorized deterministic search or fails according to the selected
profile rather than using mismatched vectors.

Knowledge API and MCP expose separate bounded operations to search knowledge, assemble context,
open an evidence citation and retrieve an authorized document section. A retrieval receipt records
query/profile identity, filters, authorized candidate/result identities, index generations,
selected evidence and token/size budget without copying private content into operational logs.
ChatGPT, a local model or another client may generate from that context. An optional
`answer-with-sources` operation in `0.17.0` uses the `0.15.0` AI gateway and the same receipt; it is
read-only, cites every supported assertion, distinguishes insufficient or conflicting evidence
and never converts an answer into classification or another durable write.

Retrieved document content remains untrusted input. Prompt-like text cannot expand tool scope,
change retrieval policy, reveal excluded candidates or authorize a write; provider routing,
redaction preview, token budget and local-only policy apply after authorization and before model
delivery. Synthetic evaluation measures citation validity, retrieval quality, stale-index
behavior, permission isolation, prompt-injection resistance and deterministic fallback without
requiring private user documents or telemetry.

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
start/stop/status/browser controls; EN/IT About identity; update checks disabled by default, a
manual `Check now` action and an optional check at startup; comparison of the embedded local
version with the selected Stable or Preview online catalogue; a visible available/up-to-date
result that leaves download and installation to the user; provider-independent Windows update
metadata with an explicit initial GitHub Releases transport; installer size/SHA-256 verification;
user-confirmed installer handoff; uninstall that preserves Instance data; release-bundle
publication and Windows install/use/uninstall CI evidence.

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

### 0.5.1 — Stability, Security, Performance and Accessibility Baseline

Consolidated the rapid `0.5.0` product growth without changing canonical Instance schema or adding
a new product capability. The correction restricts local serving to explicit loopback targets,
rejects hostile Host values, adds private-response security headers, disables the unbounded
interactive API documentation surface and preserves EN/IT navigation state with keyboard-visible
accessibility improvements.

Post-ingestion full-text indexing now refreshes only Documents whose searchable current Version
changed when schema-2 derived metadata and the physical database agree. Missing, legacy, malformed
or inconsistent derived state falls back to a complete rebuild, and a failed complete replacement
restores the previous database/metadata pair. Dependency-update proposals remain ordinary PR/CI
inputs with no release authority; the preview security/support and maintainability boundaries are
explicit. See [`releases/0.5.1.md`](releases/0.5.1.md).

## Release record and forecast

### 0.6.0 — Portable Instance and Hierarchical Markdown Library

**Depends on:** the published `0.5.1` correction over `0.5.0` durable ingestion.

**Outcome:** delivered an Instance that is safely upgradeable, exportable, recoverable and directly
navigable on its filesystem before network Sources are introduced.

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

`S01`, `S02`, `S03`, `S04` and `S05` are implemented and were delivered sequentially through issue
#95. The release aligns package/build identity at `0.6.0` and qualifies a real immutable public
`0.5.1 → 0.6.0` Windows upgrade, schema-1 to schema-2 migration, Instance preservation,
deterministic builds and portable export/import. See
[`releases/0.6.0.md`](releases/0.6.0.md).

### 0.6.1 — Purge Integrity and Ingestion Serialization Correction

**Depends on:** the published `0.6.0` Portable Instance and hierarchical Markdown library.

**Outcome:** corrected live-Instance purge completeness and serialized every supported local
ingestion path with purge, without adding a product capability or canonical schema migration.

**Includes:** bounded removal of ingestion and operational records linked through the purged
Document's Version and Acquisition identities; one shared cross-process Instance lifecycle lock
covering filesystem ingestion, ingestion retry, their derived search-index refresh, Inbox
ingestion and permanent purge; focused race and dangling-reference regressions.

**Exit gate:** purge leaves no bounded operational locator or Acquisition reference for the
selected lineage; ingestion and index maintenance cannot enter while purge owns the lifecycle
lock; the full Linux/Windows, deterministic build, offline rebuild, bundle and public `0.6.0 →
0.6.1` Windows upgrade evidence remains green.

**Not in this release:** dependency maintenance, Agent Development Protocol changes, connectors,
network Sources or any `0.7.0` implementation.

Issue #102 completed the correction. The release aligns package/build identity at `0.6.1` and
retains the unsigned, user-confirmed preview update boundary. See
[`releases/0.6.1.md`](releases/0.6.1.md).

### 0.7.0 — Connector Framework and Safe Web Intake

**Depends on:** `0.2.0` network transparency and the corrected `0.6.1` lifecycle baseline.

**Outcome:** introduces the first network Source without coupling the Core to one vendor or
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

The local lifecycle can update and disable an instance or Source independently. Removal retains a
canonical tombstone so existing Acquisitions, Documents and Original provenance remain valid; it
does not trigger provider deletion, local purge or Original replacement. S02 cursor envelopes stay
empty and configuration health stays network-free until later execution contracts exist.

**Exit gate:** synthetic hostile-network fixtures fail closed, every acquisition is attributable,
and disabling network capability prevents access without a silent fallback.

The five completed slices are:

- `0.7/S01`: connector definitions, identities, capability manifests and local network policy;
- `0.7/S02`: independent ConnectorInstance/Source lifecycle and aligned service, CLI, API and
  EN/IT Browser views;
- `0.7/S03`: installed-app OAuth 2.0 with PKCE S256, revocation and reauthorization preservation;
- `0.7/S04`: guarded Source-bound HTTP(S) transport with hostile-network qualification;
- `0.7/S05`: atomic one-URL manual acquisition, immutable Original retention, deterministic
  readable-text derivation and backup/restore/export/import qualification.

Version alignment and the immutable changelog were published at `0.7.0` through the trusted
workflow after exact-head review and merge. The tag and public prerelease point to commit
`1e1731969552497c2d3fe79b1c26eccdaad712c0`; see
[`releases/0.7.0.md`](releases/0.7.0.md).

**Not in this release:** background refresh, watched folders, OCR, email or Google Drive intake,
AI classification, MCP, Git mirrors, a Windows background agent or Authenticode signing.

### 0.8.0 — Refresh Scheduler, Watched Folders and Source Lifecycle

**Depends on:** `0.7.0` Source contract.

**Slice status:** all five bounded slices are complete and merged. Issue #122 / PR #123 implements
`0.8/S01`: strict manual/interval/calendar policies, clocks, durable jobs, leases, heartbeat,
checkpoint/recovery, bounded retry and receipts. Issue #124 / PR #125 implements `0.8/S02`:
explicit local/removable/mounted-network filesystem Sources, portable scheduled watching,
quiescence, mount-loss state and an idempotent `source.refresh` executor. Issue #126 / PR #127
implements `0.8/S03`: a closed maintenance catalogue, dry-run estimates and full/incremental FTS
generations with per-item checkpoint and activation recovery. Issue #128 / PR #129 implements
`0.8/S04`: exact filesystem Source reconciliation, monotonic cursors and closed lifecycle states.
Issue #130 / PR #131 implements `0.8/S05`: append-only Instance file/byte/category trends,
filesystem capacity and observable warning/critical thresholds.

**Outcome:** make schedules, local-folder observation, refresh, reindex, retry and Source/job state
durable without turning every timer, filesystem event or poll into a new document version.

**Includes:** bounded persistent jobs; disabled, manual, periodic, scheduled, event-assisted and
conditional policies; one or more independently configured local, removable, UNC/SMB or mounted
Drop folders as filesystem Sources; recursive and non-recursive scope, include/exclude patterns,
temporary-file rejection and a configurable quiescence window so a file is never acquired while
still being written; initial scan plus periodic reconciliation so missed or coalesced watcher
events cannot create silent gaps.

Every job policy has Instance/ConnectorInstance/Source scope as applicable and supports run now,
fixed interval or local calendar time with an explicit timezone and daylight-saving rule. It also
records quiet and maintenance windows, bounded jitter, minimum/maximum interval, concurrency and
one closed missed-run policy: skip, coalesce to one or run one bounded catch-up. Sleep/wake, clock
correction, restart and a long-disconnected mount cannot enqueue an unbounded backlog. Conditional
HTTP metadata, provider rate limits and exponential backoff reduce unnecessary transfers without
silently changing the user-selected minimum refresh frequency.

Each folder retains the existing copy-by-default, leave-in-place and explicitly selected
move-after-commit behavior. Move remains impossible before exact-byte preservation, hash
verification and committed Acquisition evidence. A missing external folder or network mount is
reported and never silently recreated; reconnection performs an idempotent reconciliation.
Content identity distinguishes rename/movement from a changed Version without treating path alone
as identity.

The same engine provides per-ConnectorInstance, per-account and per-Source cursors/checkpoints;
conditional requests; rate-limit handling; retry/backoff/cancellation; instance/Source locking and
idempotency; explicit active/paused/error/missing/superseded/reauthorization-required states;
redacted local/network events distinct from declared capability; last-attempt, last-success,
next-run and bounded resync status; quiet hours plus CPU, battery and metered-network limits where
the host exposes them.

The durable journal records job identity/kind/scope, idempotency key, policy revision, attempt,
lease, heartbeat, checkpoint, progress, processed/skipped/error counts, duration and terminal
receipt. An interrupted or stale-leased job is classified as resumable, restart-only or requiring
manual intervention; replay begins from committed evidence and cannot duplicate an Acquisition,
Version, index generation, backup or publication.

The first maintenance catalogue covers incremental or full FTS reindex, Markdown-library rebuild,
Source reconciliation, Instance validation, Original assurance, duplicate scan and verified backup
creation/verification to an explicit target. These actions can use the scheduler while the current
runtime is active; always-on execution while the interface is closed depends on the qualified
self-hosted or desktop agents in `0.18.0` and `0.19.0`. Reindex and library work mutate only
rebuildable generations. Validation and assurance remain read-only, and no timer can authorize
repair, purge, retention deletion or destination cleanup.

**Exit gate:** unchanged bytes and duplicate watcher events create no new Version, partially
written files are never committed, rename and changed-content behavior is explainable, unavailable
mounts fail visibly without data loss, retries are safe, timezone/DST and missed-run fixtures stay
bounded, and interruption at every checkpoint resumes, restarts or fails with exact evidence and no
duplicate canonical or derived state.

**Bounded slices:** `0.8/S01` durable scheduler, journal, leases and clocks (#122/#123);
`0.8/S02` local/removable/network-folder Sources, portable watching, quiescence and mount-loss
recovery (#124/#125); `0.8/S03` maintenance/reindex catalogue and interruption recovery
(#126/#127); `0.8/S04` filesystem Source reconciliation, cursors and lifecycle states (#128/#129);
`0.8/S05` resource policies, statistics evidence and end-to-end recovery fixtures (#130/#131).
All are merged and published as the bounded `v0.8.0` preview documented in
[`releases/0.8.0.md`](releases/0.8.0.md).

### 0.9.0 — OCR, Email, Google File and Transcript Intake

**Depends on:** `0.8.0` refresh engine.

**Outcome:** make scans and images readable through a replaceable local OCR baseline, then validate
the connector framework with communications, cloud files and transcripts while keeping every
extractor and provider outside the canonical domain model.

**Includes:** the optional local OCR increment tracked by #5 with explicit packaging, licensing and
platform support evidence; scanned PDF, TIFF and supported image inputs; disabled, automatic when
no trustworthy text exists, forced and selected-page modes; explicit language selection or bounded
language detection; rotation/orientation and conservative deskew; page-level text, coordinates,
confidence and warnings; separately identified layout/table and barcode/QR observations when a
supported adapter can produce them. Engine, version, languages, settings and source-page identity
remain recorded in a rebuildable derived artifact, and OCR never replaces the Original or
pretends uncertain handwriting is verified text.

Native OCR and image/PDF processing run behind bounded resource, decompression, page, pixel and
time limits with hostile/corrupt fixtures. Local OCR is the offline baseline. A later remote OCR or
vision provider must pass through the `0.15.0` AI/privacy gateway and cannot become a silent
fallback.

The release also includes provider-neutral email, file and transcript Sources; local EML/mailbox
adapter; a Google connector preview with independently consented read-only Gmail and Drive
capabilities; thread/message/attachment and file/revision identity with deduplication; attachment
extraction and OCR eligibility; bounded export of supported Google-native files with export format
and provenance preserved; external secret references; transcript profile mapping into canonical
documents; provider cursor state kept inside each adapter.

**Exit gate:** local OCR can be removed and rebuilt without changing canonical knowledge; existing
trustworthy text is not needlessly degraded; low-confidence pages remain visibly uncertain;
hostile, oversized and unsupported inputs fail safely; re-import and refresh are idempotent;
attachments and Drive revisions retain provenance; revoked authorization fails visibly without
corrupting canonical state; and provider replacement does not migrate canonical knowledge.

**Not in this release:** Google Calendar, task-provider sync, email sending, or automatic claims,
decisions and tasks derived from communications or transcripts.

**Suggested slices:** `0.9/S01` OCR contract, licensing and packaging; `0.9/S02` bounded local OCR
and document bundles; `0.9/S03` email identity and intake; `0.9/S04` Gmail/Drive adapters;
`0.9/S05` transcript profiles; `0.9/S06` cross-source qualification and correction findings.

**Current status:** parent tracker #137 remains open and `0.9/S01` was completed by the
pre-existing #5 and owner PR #138. S01 defines the contract, licensing and optional packaging
only; it ships no OCR execution adapter. `0.9/S02` is the next forecast-only slice and has no
issue, branch or owner pull request. S03–S06 likewise have no operational issues.

### 0.10.0 — Unified Capture, Operations and Action Center

**Depends on:** durable ingestion, hierarchical classification, Sources and the `0.8.0`
refresh/job foundation.

**Outcome:** unify local, connector and mobile capture decisions plus background operations and
maintenance in one evidence-backed Action Center rather than hiding submitted items or interrupted
work.

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

An Operations & Maintenance view lists every schedule and current/recent job with scope, policy,
last attempt/success, next due time, progress, throughput, checkpoint, resource wait, retry time
and terminal receipt. It distinguishes queued, running, pausing, paused, blocked, interrupted,
resumable, restart-only, failed and completed states. From the same evidence users can run now,
pause, resume, retry, cancel or safely restart; a control is absent when the job contract cannot
honour it. Interrupted work links to the exact checkpoint and recommended safe action instead of a
generic error or `fix everything` button.

Maintenance actions include incremental/full reindex, library rebuild, Source reconciliation,
validation, Original assurance, duplicate scan, backup verification and a content-free redacted
diagnostic bundle. Estimated item count, bytes, temporary disk need and expected authority
boundary precede heavy work. Repair remains a distinct preview/backup/confirmation operation, and
capacity warnings can pause new ingestion without deleting Originals, derived state, logs or old
backups automatically.

Queue notifications are separately configurable as disabled, in-application only, host desktop/
browser/mobile PWA or a later explicitly configured provider channel. Notification previews omit
document content and sensitive titles by default, support quiet hours and aggregation, and link back to the
same authoritative queue item rather than creating a second decision surface.

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

**Suggested slices:** `0.10/S01` Action Center state model and local queues; `0.10/S02` Operations &
Maintenance schedules, job control and interruption recovery; `0.10/S03`
classification/duplicate/version-conflict decisions and reusable safe routing; `0.10/S04` mobile
PWA capture, device pairing and offline retry; `0.10/S05` iOS, Android, Drive-drop and Telegram
reference paths; `0.10/S06` mobile retrieval, authorization and end-to-end assurance fixtures.

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

### 0.12.0 — Productivity and Git Connectors with Guarded Sync Preview

**Depends on:** the `0.7.0` connector contract, `0.8.0` refresh engine, `0.10.0` review
queue and `0.11.0` provider-independent Task and CalendarEvent objects.

**Outcome:** connect common personal productivity and Git mirror systems without making Google,
iCalendar, Asana, Tududi, GitHub or another host part of canonical knowledge or granting
background write authority by default.

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

A provider-independent Git mirror capability supports multiple independently configured local or
remote repositories and qualifies GitHub, GitLab and Gitea reference profiles without requiring
any one host at runtime. Each mirror selects Instance/Area/Project scope, destination branch and
path, and one of disabled, manual publish or scheduled one-way publish. The default payload is the
human-readable Markdown library plus bounded portable metadata; exact Originals, private
attachments and AI receipts require separate explicit include rules and a pre-publish inventory.

Every publish provides a dry-run diff, content/size limits, secret and sensitive-data findings,
external credential references, commit identity and a privacy-minimizing receipt. A policy may
block on any finding or require confirmation. A hosted profile verifies repository visibility when
the provider can prove it; unknown visibility fails closed for private payloads, while publishing
to a public repository requires a separately allowlisted content scope and explicit confirmation.
Remote failure, non-fast-forward state or rejected credentials leave canonical knowledge and the
last valid mirror untouched. Remote deletion never causes local deletion, and local archive/purge
never rewrites remote history. Bidirectional multi-master Git synchronization remains excluded; a
remote repository may instead be imported through the explicit legacy-import boundary in
`0.13.0`.

A provider-independent filesystem mirror capability qualifies a local-folder target and an
`rsync` over SSH reference profile beside Git. It publishes only from an atomically completed
library/export staging generation, never from a live mutable Instance tree, and supports disabled,
manual or scheduled one-way transfer with dry-run inventory, bandwidth/maintenance windows,
resume, destination host-key verification, external credential references and a final
source/destination manifest comparison. Files transfer into a destination-side staging generation;
only a verified complete manifest may be atomically activated, preserving the previous active
generation after interruption. A target that cannot provide the qualified activation primitive
fails visibly instead of exposing a mixed or partial generation. The destination may be a user-
controlled server, NAS or mounted path; `rsync` availability and version stay part of the host
support matrix rather than a hidden runtime assumption.

Destination deletion is disabled by default. If a user explicitly enables cleanup for a derived
mirror, Provelume first presents the exact destination-only path/byte impact and never applies it
to an Original store, canonical Instance, backup inventory or unknown destination root. Cleanup
approval is bound to the exact source and destination manifests used by that preview; any change
invalidates the plan and requires a fresh preview and confirmation before transfer or deletion.
Rsync is a transport and mirror mechanism, not evidence that a backup is complete or restorable;
verified backup replication and restore drills are qualified separately in `0.18.0`.
Bidirectional rsync or two concurrently writable Instances remain excluded.

**Exit gate:** multiple Google accounts, Asana identities/workspaces/projects, Tududi endpoints,
iCalendar feeds, Git and rsync mirrors remain distinguishable; refresh and full resync are idempotent;
recurrence and cross-provider duplicates are explainable; revoked credentials stop access without
damaging imported knowledge; a stale or replayed task write cannot overwrite newer provider state;
and repeated one-way Git or filesystem publication produces no needless commit or transfer.
Local-only/no-GitHub/no-rsync mode performs no connector or mirror access.

**Not in this release:** email sending; calendar create/update/delete; autonomous task creation or
deletion; generic two-way multi-master synchronization; Git or rsync as canonical storage or
mandatory backup; or a mandatory 1.0 commitment for additional adapters such as CalDAV, Microsoft
365, IMAP, Notion or Todoist.

**Suggested slices:** keep each provider adapter in its own owner slice after shared conformance
contracts; implement shared mirror identity/staging/dry-run first, then Git publication, hosted
profiles and the local/rsync one-way adapter without mixing them with task write-back.

This independently releasable outcome takes the former `0.12.0` slot. Every later unreleased
forecast moves forward atomically by one through the `0.22.0` release candidate. Published
history, the numbering and relative order of `0.5.0`–`0.11.0`, and stable `1.0.0` remain
unchanged; the Inbox/library/assurance expansions in `0.5.0`, `0.6.0` and `0.10.0`, and the
connector-related scope expansions in `0.7.0`–`0.11.0`, are explicit above.

### 0.13.0 — Knowledge Navigation, Statistics, Relations and Deterministic Discovery

**Depends on:** `0.11.0` objects.

**Outcome:** make documents and objects coherently navigable, measurable and diagnosable before
introducing embeddings.

**Includes:** a mature Knowledge Browser/Viewer over the existing filesystem library and
structured objects; Area/Subarea/Project/Collection and Source/tag/type trees with breadcrumbs;
per-folder outlines and ordered/pinned sections; recent and saved views; safe
rendered/raw/original document modes; outgoing links and backlinks; version/provenance timelines;
related document/object views with a visible reason for each suggestion; an optional secondary
relation graph; explainable stale/conflict/missing-evidence/superseded/orphaned health states;
deterministic detectors; full-text object/relation search; filters; documented ranking; portable
references and complete navigation/relation-index rebuild.

A local Statistics & Capacity view reports timestamped counts and exact bytes across Sources,
Acquisitions, Documents, Versions, Originals, derived bundles, indexes, library projections,
queues, trash and configured backup inventories. It distinguishes canonical, derived, cache and
external-replica space; supports type, Source, Area, Project, status and time filters; and shows
growth, throughput, extraction/OCR coverage, duplicate reuse, queue age, job duration/failure rate
and labelled disk-capacity forecasts. Statistics are incrementally maintained but fully
rebuildable from manifests and operation evidence, perform no telemetry and never make deletion or
retention decisions.

A generic legacy filesystem/Markdown archive importer provides a clean-room migration path for
existing personal knowledge trees without naming or depending on a private instance. An
operator-authored mapping manifest relates source folders to Areas/Projects, pairs exact originals
with same-name or explicitly mapped Markdown sidecars, preserves portable relative links where
safe, inventories unsupported or ambiguous items and proposes rather than guesses classifications.
Import offers dry-run, copy-only staging, bounded batches, resume, idempotent replay and a final
reconciliation report covering source paths, byte counts, hashes, imported Acquisitions, links,
unresolved items and zero source deletion. Synthetic fixtures qualify the public behavior; private
data and mappings never enter the repository.

**Exit gate:** every health finding identifies its evidence and rule; deterministic navigation,
relation and statistics rebuilds agree with canonical counts and bytes; every related result
explains its deterministic path; keyboard and mobile navigation reach the same knowledge;
discovery remains fully useful without AI or a vector store; and a repeated legacy import is
reconcilable without duplicate Documents or lost source bytes.

**Suggested slices:** build deterministic navigation and health, then local statistics/capacity,
before the generic legacy-import profile; qualify import through synthetic folder/sidecar/link
fixtures in a separate final slice.

### 0.14.0 — Knowledge API v1, Read-only MCP and Client Connections

**Depends on:** stable object and discovery contracts.

**Outcome:** stabilize the shared client and grounded-retrieval contract and prove that the
browser contains no exclusive business logic.

**Includes:** paginated and bounded Knowledge API v1 contracts; schemas and compatibility policy
for documents, hierarchical classification, Action Center queues, objects, provenance, search,
related, retention and health; read/write scope separation with permanent purge excluded from
read-only clients and MCP;
a versioned capture-submission contract; installable-PWA and optional-native mobile profiles for
recent/search/detail/provenance/original-download plus mobile-client conformance fixtures, all
distinct from read-only MCP tools for search and retrieval; aligned CLI/browser services;
reference clients; version negotiation and pre-1.0 deprecation policy.

Read-only retrieval tools separately search knowledge, assemble a bounded context from result
handles, open an exact evidence citation and retrieve an authorized document section. Responses
use the shared evidence-reference and retrieval-receipt schemas, expose deterministic rank and
freshness, and retain the same shape when `0.17.0` later adds semantic ranking. Context assembly
never grants broader access than the search that produced the handles, and client-supplied handles
are reauthorized at use time.

Connection profiles cover local MCP clients, authenticated remote HTTPS MCP and a private-tunnel
transport without making any tunnel vendor part of the Core contract. ChatGPT is qualified as one
optional client through its supported remote/private connection path, alongside a generic MCP
conformance client and a local Codex-style client. Users choose which tools, Areas, Projects,
Sources and Original-download capability each connection may see; connections are revocable,
read-only by default and expose neither physical paths nor external credential references.

Git mirror and MCP are independent choices: a user may use direct MCP only, Git mirror only, both
or neither. No client connection requires publishing knowledge to GitHub or exposing a private
Instance directly to the public Internet.

**Exit gate:** at least two clients plus the mobile profile pass the same conformance fixtures; an
authenticated private connection can be revoked without restarting or corrupting the Instance;
citations resolve to the exact authorized Version evidence; and no interface exposes unauthorized
knowledge, local paths, secrets or writes.

**Suggested slices:** freeze the API and evidence references first, add local read-only
search/context/citation MCP second, then qualify remote authentication, mobile/native profiles and
private transport without adding write authority.

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

Users may select disabled/local-only, a specific local model endpoint, a specific remote provider
or an explicit ordered fallback at Instance, Source, Area or Project scope. A fallback may narrow
but never override a local-only or denied-data rule. Provider/model allowlists, per-job and periodic
budgets, content minimization/redaction preview, metered-network policy and an operator-visible
estimate remain independent controls. Optional remote OCR/vision also uses this gateway and never
silently replaces the local `0.9.0` OCR path.

**Exit gate:** local-only fails closed, provider substitution leaves canonical knowledge intact,
and denied data never reaches a provider in policy tests.

### 0.16.0 — AI Classification, Receipts, Provider Adapters and Evaluation

**Depends on:** `0.15.0` gateway.

**Outcome:** complete the user-controlled folder-to-knowledge path by making AI-assisted
classification attributable, reviewable, safely applicable and replaceable.

**Includes:** privacy-aware receipts with capability/model/policy/template/source/output identity;
versioned templates; additional optional adapters behind the same capability contract; structured
object and classification proposals delivered through the same Action Center; immutable separation
between extracted Markdown and AI-authored output; sanitized conformance/evaluation fixtures;
provider replacement tests; configurable receipt retention with minimum provenance.

Classification has explicit disabled, proposal-only, confirm-each and controlled-automatic modes.
Every proposal is bound to the exact Document Version/Original hash and may select only current
allowlisted Area, Project, Collection, tag and relation identities through a closed schema. It
includes reason, evidence references and calibrated confidence; stale proposals fail before
mutation. Initial durable writes and every new or broadened rule require review. A corrected,
confirmed non-destructive rule may later route matching items automatically within its exact scope,
threshold and expiry, with pause, dry-run, undo/compensation and a visible operation receipt.
Destructive actions, permanent purge, external provider writes and identity merges remain outside
automatic classification.

Extracted/OCR text, document metadata and linked content are treated as untrusted data rather than
instructions. Classification adapters receive no ambient tools or connector secrets; embedded
prompt-like content cannot broaden scope, change policy, select a provider or authorize a write.
Closed-output validation, adversarial document fixtures, indirect prompt-injection tests and
content-leakage checks fail closed before an Action Center proposal exists.

An optional guarded MCP profile may submit a classification proposal or confirm an already visible
proposal through the same optimistic-concurrency and approval boundary; it never turns the
`0.14.0` read-only profile into implicit write authority. The end-to-end reference workflow proves
watched-folder acquisition, exact Original preservation, extraction/OCR, privacy-routed inference,
review or confirmed-rule application, hierarchy/library rebuild, direct MCP retrieval and optional
one-way Git publication as independently selectable steps.

**Exit gate:** the same fixture can be evaluated across adapters; every durable proposal and
applied classification is traceable to source, policy and exact input; prompt injection cannot
create or broaden a proposal; disabling AI stops inference without stopping deterministic
ingestion; the complete folder-to-knowledge workflow can be paused, retried and reconciled without
duplicate knowledge or Original loss; and logs contain neither secrets nor raw private content.

**Suggested slices:** `0.16/S01` receipts/templates/evaluation; `0.16/S02` closed classification
proposals; `0.16/S03` review, rule and guarded-apply modes; `0.16/S04` adversarial isolation and
optional write-scoped MCP; `0.16/S05` complete folder-to-knowledge qualification.

### 0.17.0 — Semantic, Hybrid and Grounded RAG Retrieval

**Depends on:** `0.16.0` gateway and receipts.

**Outcome:** add semantic and grounded RAG retrieval through the stable client contract while
keeping every chunk, embedding and index entirely derived and replaceable.

**Includes:** separate embedding adapter; versioned parser/chunk/overlap/model/dimension/tokenizer
identity and privacy policy; local vector-store baseline plus optional adapters; incremental
Version-bound indexing plus manual or scheduled complete rebuild from canonical state;
model/store migration; explainable full-text plus semantic ranking and optional reranking;
consistent pre-retrieval authorization filters; stale, incompatible and missing-index health;
index/chunk/vector counts and bytes, coverage, lag, generation age and rebuild progress.

The primary RAG boundary remains retrieval rather than a proprietary chat surface. API/MCP clients
receive bounded passages with exact Version, Original, page/section/span and index-generation
citations, then ChatGPT or another selected model may answer from them. The optional gateway-owned
`answer-with-sources` path uses the same authorized retrieval receipt and privacy routing, reports
insufficient or conflicting evidence, and grants no classification, mutation or connector-write
authority.

**Exit gate:** delete-and-rebuild, interrupted reindex, model/store migration and provider-
replacement tests preserve canonical objects, privacy routing and deterministic fallback search;
citations resolve after incremental updates; removed or unauthorized content disappears before
the next query; and synthetic RAG evaluation detects unsupported citations, prompt-injection scope
expansion and cross-scope leakage.

### 0.18.0 — Self-hosted, Synology and QNAP Operations

**Depends on:** `0.6.0` lifecycle and mature application contracts.

**Outcome:** make the public repository operable as an always-on self-hosted product, including
qualified Synology and QNAP container profiles, without GitHub at runtime.

**Includes:** immutable multi-architecture packages/containers with build identity and an explicit
supported CPU/host matrix; configuration separated from data; secret references; health/readiness
and redacted logs; documented init/start/stop/status/backup/restore/upgrade/rollback; N-1 to N
migration; local authentication for non-loopback exposure; provider-neutral reverse-proxy/TLS
guidance; retention and purge reporting that distinguishes the live Instance from backups and
external replicas. The durable scheduler runs refresh, indexing, backup verification and permitted
maintenance inside explicit windows and resource/disk thresholds even when no browser is open.

The Synology profile covers DSM Container Manager and Portainer-compatible Compose, bind/named
volume choices, UID/GID and ACL diagnostics, NAS/local/UNC Source mounts, reverse proxy and TLS,
restart/health policies, resource limits, log rotation, verified backup/restore and immutable-image
upgrade with rollback. It documents integration boundaries for Hyper Backup or another external
backup system without claiming that an unverified external copy is restorable. A native DSM
package receives an explicit feasibility/support decision and is not required for the container
profile.

The QNAP profile covers supported QTS and QuTS hero systems through Container Station Compose V2,
shared-folder/bind/named-volume choices, UID/GID and ACL diagnostics, NAS/local/network Source
mounts, reverse proxy and TLS, restart/health policies, resource limits, log rotation and
immutable-image upgrade with rollback. HBS 3, storage snapshots and external rsync jobs are
documented as integration boundaries: none is called a valid Provelume backup until the received
portable bundle and manifest have been verified and a restore drill succeeds. A native QPKG
receives a separate feasibility, signing, update and support decision and is not required for the
Container Station profile.

Backup/export modes include ordinary operator-managed archives and an optional encrypted portable
bundle with explicit key-recovery and lost-key warnings. Qualified targets include local/mounted
storage and one-way `rsync` over SSH: Provelume creates an atomic bundle, transfers with pinned host
identity and externally held credentials, rereads and verifies the destination manifest, records a
receipt and can schedule a bounded restore drill. Rsync never reads a live mutable Instance, never
becomes bidirectional synchronization and is transport rather than proof of recoverability. Keys
remain outside the Instance and backup payload; encryption never weakens manifest/hash
verification.

Self-hosted update policy is separate from the desktop updater and offers disabled, notify,
download/stage and controlled automatic container replacement only after verified backup,
migration preflight and health-based rollback are available. Capacity thresholds warn first and
can pause acquisition, indexing or backup staging; they never silently purge Originals, derived
generations, logs, snapshots or old backups.

**Exit gate:** a clean supported Linux host plus one documented Synology and one documented QNAP
architecture can install, operate, schedule, upgrade, roll back and recover an Instance using only
published artifacts and documentation; permission, mount-loss, low-space, interrupted job,
rsync/host-key, backup-key-loss and interrupted-upgrade failures remain visible and recoverable
within their documented boundaries.

**Suggested slices:** immutable multi-architecture runtime; generic self-hosted lifecycle and
always-on scheduler; Synology/DSM profile; QNAP QTS/QuTS hero profile; encrypted local/rsync backup,
restore drill and container-update recovery; final support-matrix qualification remain separate
owner slices.

### 0.19.0 — Windows and macOS Background Agents and Bootstrap Completion

**Depends on:** the `0.4.0` product shell preview and `0.18.0` operations.

**Outcome:** converge the early Windows product shell with mature operations and add a native-feel
macOS bootstrap, so both desktop systems can run watched intake and maintenance without an open
browser.

**Includes:** shared hardened launcher/runtime/Instance separation; guided prerequisite and
compatibility detection; complete create/open/start/stop/status/browser/diagnostics behavior;
redacted logs; spaces, Unicode, case and path-normalization fixtures; lifecycle-aware failure
recovery; uninstall that preserves the Instance; and a final desktop support matrix.

Windows retains migration from the `0.4.0` preview installation, UNC/network-share support, a
per-user background agent and tray surface, with an explicitly qualified elevated-service option
only if needed. macOS adds an application/menu-bar surface and per-user LaunchAgent, Keychain
credential references, explicit selected-folder access, removable/network-volume handling and an
Apple Silicon baseline; any Intel support remains an explicit matrix entry rather than an
assumption.

The platform agent makes watched folders, scheduled refresh/reindex/maintenance, Action Center
notifications and permitted AI/Git work operate while the main window is closed. Users may choose
manual runtime or start-at-login; pause all background activity or one Source; define quiet hours
and CPU/battery/metered-network limits; and open the exact queue or failure from a content-
minimizing notification. Disabled background mode performs no hidden work, and closing the UI
never ambiguously changes the selected policy. Sleep/wake and disconnected-volume recovery obey
the scheduler's bounded missed-run and checkpoint contracts.

**Exit gate:** install/use/uninstall, login-start, pause/resume, sleep/wake, network-volume loss and
failure-recovery fixtures pass on supported Windows and macOS targets without duplicate
processing, hidden network activity or deletion of user knowledge.

**Suggested slices:** complete shared launcher/bootstrap recovery before adding platform agents;
then qualify Windows startup/tray/optional-service and macOS app/menu-bar/LaunchAgent behavior in
separate slices before cross-platform recovery fixtures.

### 0.20.0 — Signed Desktop Releases and Safe Updaters

**Depends on:** `0.19.0` bootstrap and the verified release chain.

**Outcome:** complete the Windows and macOS lifecycle with authenticated installers, backup,
health, safe self-update and rollback.

**Includes:** provider-independent signed release manifest, update catalogue and key lifecycle
policy; Windows code signing plus a signed installer; macOS Developer ID signing, notarization and
stapling for the application and chosen installer image/package; pre-install signature/hash/
compatibility verification; runtime slots separate from the Instance; backup/migration/restart/
health/automatic rollback; interrupted-update recovery; Stable/Preview/Dev channels; offline
update bundles; and one explicit, user-selectable update policy rather than an ambiguous
auto-update switch:

- **Disabled/offline:** no background check, download or update network access; the installed
  version remains visible locally and a manual offline bundle remains possible.
- **Manual check only:** `Check now` compares the exact installed version with the selected online
  channel, then shows availability, release notes, security relevance, compatibility/migration
  impact and download size; the user decides whether to download and install.
- **Notify only:** an opt-in startup or scheduled check may notify about a newer version but never
  downloads or installs it.
- **Download and ask:** an opt-in check may download and verify an eligible update, but
  installation still requires explicit confirmation.
- **Controlled automatic install:** a separate opt-in policy, enabled only after signing, backup,
  health-check and rollback gates are established, with a maintenance window and no forced
  downgrade or channel switch.

All online modes disclose the contacted catalogue and the minimal version/platform metadata sent;
no Instance content is transmitted. Every mode supports Stable/Preview/Dev channel selection,
version pinning, skip-this-version, defer-until, metered-network and battery-aware controls,
security-update prominence, an update/rollback history and a one-click return to manual-only mode.
Policy changes and automatic actions receive privacy-minimizing audit entries.

The Windows or macOS background agent may execute the selected check/download/install policy while
the main window is closed, but only within the same persisted mode, maintenance-window, battery,
metered-network, backup and rollback gates. Exiting or pausing Provelume exposes whether update
checks remain enabled rather than silently leaving an updater behind. Platform-specific updater
privilege, quarantine, locked-file and application-bundle replacement failures retain the previous
healthy runtime.

**Exit gate:** every policy is testably distinct and persists across restart on Windows and macOS;
Disabled/offline performs no update network access; manual and notification modes never install; a
pinned, skipped or deferred release is respected; automatic install cannot run outside its opt-in
policy and maintenance window; and tampered, revoked, unnotarized, incompatible, downgraded or
interrupted updates fail safely while the previous healthy runtime and Instance remain
recoverable.

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

**Includes:** Instance, Knowledge API/MCP/RAG and artifact contract freeze; supported migration,
upgrade and rollback matrix; export/import and Windows/macOS/Linux interoperability;
watched-folder/OCR/
classification/Git/rsync-mirror end-to-end qualification; scheduler, interruption, maintenance,
statistics and low-space recovery; generic Linux plus documented Synology and QNAP operations;
Windows and macOS background-agent and updater recovery; mobile/PWA capture and retrieval;
no-GitHub, no-rsync, no-external-AI and local-only tests; provider replacement and vector rebuild;
at least two real clients; citation and permission-isolation tests; synthetic performance limits;
focused security review; complete licensing, notices, support and deprecation documentation.
Website/release/facts parity must keep every forecast feature visibly unavailable.

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
- #24 — immutable OCI builder lock and pinned-container cross-job rebuild evidence; this remains
  independent release-assurance hardening until an atomic planning change places it.
- Detached provider-independent signing, key rotation and revocation before any release that
  claims authenticated provider-independent origin.
- Observed runtime network-activity instrumentation and egress enforcement only after a separate
  privacy, platform and support decision.

This cross-cutting work is not activated and receives a version only through an atomic planning
change.
