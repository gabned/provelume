# Public product roadmap

This roadmap is the canonical public release forecast for Provelume Core and the self-hosted
Instance. Published tags, dated changelog history and package identity remain immutable.
Forecast entries describe intended sequencing; they do not create an issue, owner pull
request, tag, release or delivery commitment. Planned-version movement follows
[`changelog-policy.md`](changelog-policy.md).

## Status vocabulary

- **Published preview** — immutable tag and public preview release exist.
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
| Next forecast | `0.4.0` | Durable ingestion and extractor completion | issue just in time; #5 is an input |
| Forecast | `0.5.0` | Portable Instance lifecycle | issue just in time |
| Forecast | `0.6.0` | Connector framework and safe web intake | issue just in time |
| Forecast | `0.7.0` | Refresh engine and Source lifecycle | issue just in time |
| Forecast | `0.8.0` | Email and transcript intake | issue just in time |
| Forecast | `0.9.0` | Inbox and review queue | issue just in time |
| Forecast | `0.10.0` | Knowledge Objects v1 | issue just in time |
| Forecast | `0.11.0` | Relations, knowledge health and deterministic discovery | issue just in time |
| Forecast | `0.12.0` | Knowledge API v1 and read-only MCP | issue just in time |
| Forecast | `0.13.0` | AI gateway and privacy routing | issue just in time |
| Forecast | `0.14.0` | AI receipts, provider adapters and evaluation | issue just in time |
| Forecast | `0.15.0` | Semantic and hybrid search | issue just in time |
| Forecast | `0.16.0` | Self-hosted operations | issue just in time |
| Forecast | `0.17.0` | Windows bootstrap preview | issue just in time |
| Forecast | `0.18.0` | Signed Windows release and safe updater | issue just in time |
| Forecast | `0.19.0` | Business and Cloud contracts preview | issue just in time |
| Release candidate | `0.20.0` | 1.0 compatibility freeze and end-to-end qualification | issue just in time |
| Stable | `1.0.0` | Stable provenance-first platform | issue just in time |

The package and embedded identity are `0.3.0`. Only an activated release may add work under
`Unreleased`, and only a separate reviewed release-preparation change may align package
identity, dated changelog history and tag intent.

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

## Forecast release-by-release

### 0.4.0 — Durable Ingestion and Extractor Completion

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

### 0.5.0 — Portable Instance Lifecycle

**Depends on:** `0.4.0` ingestion runs.

**Outcome:** make an Instance safely upgradeable, exportable and recoverable before network
Sources or end-user installers are introduced.

**Includes:** versioned schema and forward-only migrations with preflight; automatic backup;
failure restore/rollback; readable export and hash-validated import; Instance manifest;
`validate`, `backup`, `restore`, `export` and `import`; crash recovery; Windows/Linux path
compatibility; explicit inclusion or rebuild of derived state.

**Exit gate:** N-1 to N migration, failure recovery and cross-platform export/import preserve
originals, versions and provenance.

**Not in this release:** multi-master synchronization or proprietary cloud storage.

### 0.6.0 — Connector Framework and Safe Web Intake

**Depends on:** `0.2.0` network transparency and `0.5.0` lifecycle.

**Outcome:** introduce the first network Source without coupling the Core to one vendor or
hiding external access.

**Includes:** provider-independent Source adapter and capability manifest; explicit network
policy and secret references; manual web acquisition with canonical URL and provenance; SSRF,
reserved-address, DNS-rebinding and redirect controls; response/resource limits; conditional
metadata; preserved acquired original plus derived readable text.

**Exit gate:** synthetic hostile-network fixtures fail closed, every acquisition is attributable,
and disabling network capability prevents access without a silent fallback.

**Not in this release:** broad connector catalogue or background scheduling.

### 0.7.0 — Refresh Engine and Source Lifecycle

**Depends on:** `0.6.0` Source contract.

**Outcome:** make refresh, retry and Source state durable without turning every poll into a new
document version.

**Includes:** bounded persistent jobs; manual/periodic/scheduled/conditional policies;
conditional requests; retry/backoff/cancellation; Source locking and idempotency; explicit
active/paused/error/missing/superseded states; redacted network events distinct from declared
capability; last-attempt, last-success and next-run status.

**Exit gate:** unchanged bytes create no new version, retries are safe, and interrupted jobs
resume or fail visibly with bounded evidence.

### 0.8.0 — Email and Transcript Intake

**Depends on:** `0.7.0` refresh engine.

**Outcome:** validate the connector framework with communications and transcripts while keeping
Gmail, Plaud and any other provider outside the domain model.

**Includes:** provider-neutral email Source; local EML/mailbox adapter and one optional remote
adapter; thread/message/attachment identity and deduplication; attachment extraction; external
secret references; transcript profile mapping into canonical documents; provider cursor state
kept inside the adapter.

**Exit gate:** re-import and refresh are idempotent, attachments retain provenance, and provider
replacement does not migrate canonical knowledge.

**Not in this release:** automatic claims, decisions or tasks derived from transcripts.

### 0.9.0 — Inbox and Review Queue

**Depends on:** durable ingestion and Sources.

**Outcome:** add the first write-safe curation flow without turning the browser into a generic
editor.

**Includes:** closed review states and transitions; inbox for items requiring classification;
proposal-before-mutation; separately scoped write API with idempotency and audit journal;
CSRF/session protection; user-managed area/tag classification; duplicate decisions and links;
undo or compensation where technically possible.

**Exit gate:** accepted, rejected and superseded transitions preserve originals and evidence;
unauthorized, duplicate and replayed writes fail safely.

### 0.10.0 — Knowledge Objects v1

**Depends on:** `0.9.0` review flow.

**Outcome:** move beyond document-only knowledge with explicit canonical objects and evidence.

**Includes:** Entity/KnowledgeObject identities and aliases; Claims with Evidence references;
Decisions with state and rationale; provider-independent Task/Outcome; typed versioned Relations;
stable references independent of paths or GitHub; portable schema migration; minimal service/write
API and review workflow.

**Exit gate:** objects round-trip through export/import, retain provenance through document
version changes and never replace the authoritative original.

### 0.11.0 — Relations, Knowledge Health and Deterministic Discovery

**Depends on:** `0.10.0` objects.

**Outcome:** make objects navigable and diagnosable before introducing embeddings.

**Includes:** related document/object views; explainable stale/conflict/missing-evidence/
superseded/orphaned health states; deterministic detectors; full-text object/relation search;
filters; documented ranking; portable references and complete relation-index rebuild.

**Exit gate:** every health finding identifies its evidence and rule, deterministic rebuilds
agree, and discovery remains fully useful without AI or a vector store.

### 0.12.0 — Knowledge API v1 and Read-only MCP

**Depends on:** stable object and discovery contracts.

**Outcome:** stabilize the shared client contract and prove that the browser contains no
exclusive business logic.

**Includes:** paginated and bounded Knowledge API v1 contracts; schemas and compatibility policy
for documents, objects, provenance, search, related and health; read/write scope separation;
read-only MCP tools for search and retrieval; aligned CLI/browser services; reference client;
version negotiation and pre-1.0 deprecation policy.

**Exit gate:** at least two clients pass the same conformance fixtures and no interface exposes
unauthorized local paths, secrets or writes.

### 0.13.0 — AI Gateway and Privacy Routing

**Depends on:** `0.12.0` contracts and `0.2.0` network transparency.

**Outcome:** introduce inference as a replaceable adapter, never as the foundation of canonical
knowledge.

**Includes:** capability-based provider registry; deterministic fake adapter and at least one
optional OpenAI-compatible adapter; external secret references; source/data-category/local-only
policy; no silent cloud fallback; bounded budget, retry and cancellation; explicit provider and
network disclosure before execution.

**Exit gate:** local-only fails closed, provider substitution leaves canonical knowledge intact,
and denied data never reaches a provider in policy tests.

### 0.14.0 — AI Receipts, Provider Adapters and Evaluation

**Depends on:** `0.13.0` gateway.

**Outcome:** make AI-assisted proposals attributable, reviewable and replaceable.

**Includes:** privacy-aware receipts with capability/model/policy/template/source/output identity;
versioned templates; additional optional adapters behind the same capability contract; structured
object proposals; mandatory review for initial durable writes; sanitized conformance/evaluation
fixtures; provider replacement tests; configurable receipt retention with minimum provenance.

**Exit gate:** the same fixture can be evaluated across adapters, every durable proposal is
traceable to source and policy, and logs contain neither secrets nor raw private content.

### 0.15.0 — Semantic and Hybrid Search

**Depends on:** `0.14.0` gateway and receipts.

**Outcome:** add semantic retrieval while keeping embeddings entirely derived and replaceable.

**Includes:** separate embedding adapter; model/dimension/chunking identity and privacy policy;
local vector-store baseline plus optional adapters; complete rebuild from canonical state;
model/store migration; explainable full-text plus semantic ranking; consistent filters; stale,
incompatible and missing-index health.

**Exit gate:** delete-and-rebuild and provider-replacement tests preserve canonical objects,
privacy routing and deterministic fallback search.

### 0.16.0 — Self-hosted Operations

**Depends on:** `0.5.0` lifecycle and mature application contracts.

**Outcome:** make the public repository operable as a self-hosted product without GitHub at
runtime.

**Includes:** immutable packages/containers with build identity; supported runtime profile;
configuration separated from data; secret references; health/readiness and redacted logs;
documented init/start/stop/status/backup/restore/upgrade/rollback; N-1 to N migration; local
authentication for non-loopback exposure; provider-neutral reverse-proxy/TLS guidance.

**Exit gate:** a clean supported host can install, operate, upgrade, roll back and recover an
Instance using only published artifacts and documentation.

### 0.17.0 — Windows Bootstrap Preview

**Depends on:** `0.16.0` operations.

**Outcome:** let a non-technical Windows user create or open a local Instance without manual Git
or Python setup.

**Includes:** launcher separate from runtime and Instance data; guided prerequisite detection;
Instance directory picker; create/open/start/stop/status/browser/diagnostics; redacted logs;
spaces, Unicode and case-insensitive path support; uninstall that preserves the Instance;
preview installer and support matrix.

**Exit gate:** install/use/uninstall and failure-recovery fixtures pass on supported Windows
targets without deleting user knowledge.

### 0.18.0 — Signed Windows Release and Safe Updater

**Depends on:** `0.17.0` bootstrap and the verified release chain.

**Outcome:** complete the Windows lifecycle with authenticated artifacts, backup, health and
rollback.

**Includes:** provider-independent signed release manifest and key lifecycle policy; Windows code
signing; pre-install signature/hash/compatibility verification; runtime slots separate from the
Instance; backup/migration/restart/health/automatic rollback; interrupted-update recovery;
Stable/Preview/Dev channels; pin/defer/disable policy; offline update bundle.

**Exit gate:** tampered, revoked, incompatible and interrupted updates fail safely, while the
previous healthy runtime and Instance remain recoverable.

### 0.19.0 — Business and Cloud Contracts Preview

**Depends on:** stable API, packaging and enforceable privacy boundaries.

**Outcome:** define reusable Business/Cloud contracts before accepting organizational data,
without creating a proprietary Core fork.

**Includes:** organization/workspace/tenant context with a simple personal default; owner/admin/
member/viewer RBAC; content-minimizing audit schema; administrative provider/Source/retention/
export policies; separated connector credential administration; tenant-aware exit path;
provider-neutral encryption/KMS boundary; isolation and authorization conformance tests.

**Exit gate:** personal self-hosted behavior remains intact and the same public contracts pass
cross-tenant isolation tests without vendor-specific domain logic.

### 0.20.0 — 1.0 Release Candidate

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

**Depends on:** successful `0.20.0` qualification.

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
  input to `0.4.0`, subject to clean-room, licensing and packaging review.
- #24 — immutable OCI builder lock and pinned-container cross-job rebuild evidence; this remains
  independent release-assurance hardening until an atomic planning change places it.
- Detached provider-independent signing, key rotation and revocation before any release that
  claims authenticated provider-independent origin.
- Observed runtime network-activity instrumentation and egress enforcement only after a separate
  privacy, platform and support decision.

This work is not part of `0.3.0` and receives a version only through an atomic planning change.
