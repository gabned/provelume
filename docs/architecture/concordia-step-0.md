# Concordia — step 0 contract and acceptance plan

Status: **PROPOSED / NOT_ACCEPTED**. Campaign [#383](https://github.com/gabned/provelume/issues/383).
This is the reviewable result of the authorized 24 October 2026 reconnaissance.
It specifies the release contract; it does not qualify an implementation, approve
the remaining product choices or authorize operations on personal data/accounts.

## Baseline, authority and sources

GitHub main and the local source both resolve to
`b11e0fcb2fd46b29312c91853f8370443536c703`, tree
`92968c2a53d7a0dd14f15594db04d96b4dd453e7`. Repository ID is 1343746770.
Entitas [#375](https://github.com/gabned/provelume/issues/375) and final
[#402](https://github.com/gabned/provelume/issues/402) were reread CLOSED/completed.
The [delivery receipt](https://github.com/gabned/provelume/issues/402#issuecomment-6386973578)
records official Preview v0.14.0, release 422855449, run 40109628960/attempt 1,
all public assets, receipt, installation kit and readiness. Its statements and
historical exceptions remain scoped to Entitas. No Concordia gate inherits PASS.

The maintainer's 24 October instruction authorizes development, necessary fixes,
tests, push, normal PR/merge and exactly one official application 0.15.0 Preview
publication after every required gate. It requires acceptance of this step first.
Actual account access, personal-file actions, mirror publication and deletion
require their own scoped authorization. SDK draft, other products and lifecycle
v2 activation are excluded. Package/build identity stays 0.14.0/Entitas until the
final identity workstream; this document's version is a planning coordinate.

Current pin: Protocol 1.5.2, source/operational/Work
`02317e02767958faa3de5bb6d245ca3440360d9e`; native verification returned
BYTES_VERIFIED for all 97 files. START/CLI/PRODUCT selection and the historical
START/GIT/PRODUCT selector succeeded. The latter selected the accepted legacy
1.4.9 route, manifest digest
`14aca3db580256571194a833a26e71b674000493403c3d95ed987dd475c570eb`.
Follow [operations](../agent-protocol/operations.md), AGENTS and the selected
canonical contracts. Lifecycle v2 remains DEFERRED_BY_MAINTAINER. Digests prove
integrity, not authority. One PR-local owner and one active product slice govern
the lane; no global lock, status file or parallel operational ledger is added.

Read sources: [roadmap](../roadmap.md#0150--productivity-and-git-connectors-with-guarded-sync-preview),
[release policy](../governance/release-policy.md), #380, #377, #381, #382,
[#383 synthesis](https://github.com/gabned/provelume/issues/383#issuecomment-6247607247),
[common contract](https://github.com/gabned/provelume/issues/383#issuecomment-6246950485),
[A–L register](https://github.com/gabned/provelume/issues/383#issuecomment-6247212676),
[#393 handoff](https://github.com/gabned/provelume/issues/393#issuecomment-6246731644)
and [readiness](https://github.com/gabned/provelume/issues/393#issuecomment-6247033754),
[#391 handoff](https://github.com/gabned/provelume/issues/391#issuecomment-6246563151),
[#379 handoff](https://github.com/gabned/provelume/issues/379#issuecomment-6245685981),
[UI specification](https://github.com/gabned/provelume/issues/379#issuecomment-6241142182)
and [T01–T48 matrix](https://github.com/gabned/provelume/issues/379#issuecomment-6241608718).
Their older active-0.14 snapshots remain historical, not current execution state.

## Approved behavior preserved

The recorded decisions remain requirements, with their original planning authority:

- C: Windows 11 25H2 x64 Home and Pro; clean install, 0.14→0.15 and direct
  0.13→0.15 qualification. No implicit Windows 10, ARM or NAS support.
- D: optional complete official offline IT/EN OCR kit; explicit Yes/Not now in
  setup. Preparing components grants no Source or backlog consent.
- E: authorized per-Source automatic OCR on new acquisitions/Versions lacking
  reliable PDF text; selective preview/start for never-authorized historical
  work; resume only still-valid previously authorized requests.
- F: explicit limited-search completion is permitted, including selected uncertain
  cases with an accepted fresh preview. Empty OCR, error, cancellation, skip and
  setup deferral never establish absence of text or completion themselves.
- G: verified indexing of the actual selected Version/derivation is required before
  exit in the searchable personal profile. Global health or batch success is insufficient.
- Evidence architecture B: each producer owns its evidence; common logical
  resolver, separate maintenance/processing adapters, one scheduler receipt.
  The shared run-union alternative A remains unselected.
- New Inbox defaults to transit, with keep-file available. Existing Sources retain
  identity, behavior and consent until an explicit scoped change.

The linked source register retains the individual decisions and alternatives.
This consolidation does not promote proposed physical formats or prototype UI to
maintainer approval.

## Inventory and technical closure of A–J

The following are design decisions for review, checked against the actual source.
They do not claim new runtime services already exist.

| Topic | Observed baseline | Contract and responsible workstream |
| --- | --- | --- |
| A, startup | `desktop.py::_wait_for_server` polls `/health` for a generic 200; `web.py`/`api.py` retain deep summaries and mandatory installation/Instance opening. | #393 adds the private challenge-bound readiness contract below; preserve `/health` and public API meaning. |
| B, resources | Existing process/port/closed callback guards and lifecycle barriers exist; the Windows smoke retains a 30-second readiness deadline. | #393 owns one cancellable attempt and finite phase deadlines. Keep the existing 30-second normal smoke; test deliberately delayed/timeout cases separately. Do not increase its limit to make a failure pass. |
| C/D, packaging | `ocr_renderer.py` invokes `sys.executable -I ocr_render_worker.py`; source availability does not prove frozen dispatch. Historical proposals name Pillow 12.3.0; accepted source now requires Pillow 13.0.0. | #381 provisioning uses an explicit packaged renderer-worker entry point, no Python/PATH lookup and no GUI-as-interpreter invocation. Freeze exact Windows assets, patch/DLLs/digests/licenses before installed testing; use current accepted security floors. No old Linux component result qualifies Windows. |
| E, authorization | `ocr_jobs.py`, `processing_jobs.py`, review authority and scheduler already own requests, budgets, attempts and receipts. | #381 trigger records Source revision, Version/Original, mode/languages/settings and required stages. Pause prevents new work and reaches existing cooperative boundaries; cancel remains terminal. Policy/material changes invalidate dependent admission/exit previews. Disable never silently removes an already-required stage. Historical opt-in remains selective. |
| F, selection | `storage.py::derived_artifact_for_version` returns the first existing matching artifact; generic `index.py::_insert_document` uses extracted text. OCR has its own complete bundle. This is not a shared verified OCR/annotation selector. | #381 trigger supplies the common explicit selection binding consumed by reading/indexing: Version/Original, existing verified text selection when supported, reliable embedded text, otherwise the authorized complete OCR bundle. Conflicting/ambiguous selections block; no latest-file heuristic, annotation merge or promotion to verified truth. Retain dedicated passive-email validation. |
| F/G, limited result | Generic index insertion returns false when no extracted artifact exists; it does not establish a searchable metadata-only contribution. | #381 trigger owns an explicit bounded title/metadata-only contribution for an approved limited plan, with empty body and visible limitation. Record the exact supported fields and row digest. Until this path and proof exist, limited completion remains blocked. Uncertain OCR requires selected-document acceptance, not a generic empty-string success. |
| G, proof | `processing_jobs.py::execute` returns aggregate counters after refresh. Maintenance has candidate/generation evidence but no common per-contribution proof. | Add producer-owned evidence and common read-only resolver using R1–R8 below. Source-scoped refresh continues `allow_full_rebuild=False`, `recover_missing_derived=False`; only explicitly authorized maintenance may recover missing text. |
| H, concurrency | Existing lifecycle lease, scheduler ownership and guarded local-file handles are reusable; generic atomic storage uses replace semantics. | #382 binds a separate exit operation to the current plan/input and a final guarded proof check. An index writer, policy mutation or source conversion must coordinate through the same existing Instance lifecycle boundary. No new global lock and no GET repair. |
| I, conversion | Folder observer stores Source/job/run identity and stable fingerprints; refresh receipts report no automatic deletion. | Explicit in-place conversion, observer handoff and backlog semantics are proposed below. No new watcher or second ingestion queue. |
| J, projections | Existing Source, scheduler, OCR, ingestion, preferences and index services remain authoritative. | #379 projects each dimension separately; unknown/partial/stale stays visible. #377 uses saved preference, resolved System language and URL override separately. #391-A uses one trimmed query and recoverable HTML 400 for invalid dates only at `/search`; retain other callers, MIME values, UTC acquisition dates and return-context validation. |

### A/B: readiness and ownership

Use `GET /internal/startup-readiness` only in a launcher-owned loopback child with
valid private stdin bootstrap. Keep the proposed closed HMAC/challenge payload,
256-byte bootstrap cap and 2,048-byte response cap from #393. No redirects,
cross-host/port fallback or generic-200 acceptance. Keys never enter argv,
environment, files, logs or child-worker inheritance. Normal unbootstrapped serve
keeps this route unavailable.

Root binding will use the guarded, actually opened local directory identity,
not a normalized path string: on qualified Windows, volume serial plus file ID,
encoded as fixed-width unsigned big-endian values, combined with canonical
Instance ID and the exact endpoint in the existing framed HMAC contract. Parent
and child use one helper; retain parent/root guards while binding, reject reparse
chains and compare the child-opened identity. `maintenance_local_files.py` already
uses typed Windows handles and denies parent rename; it does not yet provide this
directory-binding helper. #393 must implement/test the shared helper, alias and
replacement cases, handle closure and filesystems lacking usable identity.

READY follows installation integrity, selected Instance identity/schema,
required recovery/open checks, service/middleware and application-lifecycle
initialization. No archive enumeration or deep diagnostic is moved into polling.
Critical checks remain blocking; deep diagnostics expose their actual separate
not-requested/pending/complete/failed/unavailable state.

Candidate budgets remain 10s parent preparation, 5s spawn/bootstrap, 60s child
readiness, absolute 75s total, 1s complete probe, 250ms gap, one in flight and at
most 240 starts; cleanup 4+2s. These are limits to test, not measured performance.
Blocking OS work remains owned by the attempt after deadline; late handles are
reconciled, never accepted as ready. Tk/event-loop work does no blocking I/O.
Stop invalidates callbacks immediately, then stops only the owned child/resources.
Unconfirmed cleanup yields STOP_UNCONFIRMED and blocks concurrent retry; no orphaned
thread/child is hidden to satisfy the clock. The normal 30s smoke remains independent.

### F/G: selection, evidence B and R1–R8

The selected contribution binds Instance, Source and policy revision, Document,
Version, Original size/hash, text artifact/bundle ID/hash/generator/settings,
selection/profile/acceptance revision, exact FTS row digest and producer plan/job.
Empty/partial OCR never silently outranks valid text. Page/text corrections keep
their original authority; ambiguous or unsupported annotation indexing blocks the
dependent exit instead of inventing a new merge policy. Thresholds reuse
`ocr_contract.py` defaults (32 significant printable characters, ratio 0.85), with
actual validated settings bound to the request.

Retain producer roots proposed in B, `state/maintenance/index-evidence` and
`state/processing/index-evidence`, with closed versioned validators. Keep existing
maintenance run, job, scheduler receipt and FTS schemas separate. This is a new
derived evidence extension, not an implemented format or a new authority.

| Correction | Required design and proof |
| --- | --- |
| R1 | Immutable content-addressed input; one deterministic `publication_a<attempt>.json` per attempt. Resolve the terminal succeeded receipt's exact attempt, plan and snapshot; never enumerate for a favorable publication. Identical final bytes may be reused; conflicting bytes stop. |
| R2 | Final text selection and durable input snapshot precede active-index publication. Maintenance may build a private candidate/recover only authorized text first; processing fixes/revalidates selection before its active transaction. A changed selection invalidates the attempt. |
| R3 | Distinguish `direct_after_commit` from `reconciled_current_state`. The latter attests now and preserves unknown original actor/time as null. Failed/cancelled receipt remains failed/cancelled; no historical success reconstruction. |
| R4 | Producer success requires finalized, readable snapshot/publication and verified current contribution, then the scheduler alone emits its terminal receipt. Index-commit/proof-write failure leaves exit blocked and recoverable; batch success cannot replace item evidence. |
| R5 | Caps follow actual scheduler retry limits (maximum 8 in current scheduler model), plan/snapshot size and real catalog scope. Current processing inventories all Documents with a 500-record bound before Source filtering; Q1's 1,000 Versions is not proof of compatibility. #381 must reconcile a bounded Source selection/catalog traversal with retained job byte/Version authority and test many Versions, many Documents and multiple Sources at/beyond limits. No automatic batch splitting or cap increase. If this cannot meet Q1, keep the finding and obtain an explicit scope decision. Historical 4MiB/500/16 caps are not qualified defaults. |
| R6 | Producer-specific private staging and no-overwrite finalization, canonical bytes/digest, pinned parent/root identity, idempotent collision checks and existing lock ordering. Generic replace is insufficient. Windows/NTFS races, reparse, partial file and flush/finalization interruptions require native evidence; do not claim stronger power-loss durability than tested. |
| R7 | Deep validators recognize both new roots before operational use; old runs/jobs/receipts retain their validators. Backup uses a coherent producer snapshot under existing lifecycle guards, preserves final history and never treats pending files as proof. Incoherence fails/retries explicitly. Restore without indexes preserves history and invalidates current applicability. No downgrade promise. |
| R8 | Resolver returns exact references/digests/revisions. Under the final H guard, recheck selected text, current row, policy, Original and unchanged input identity/bytes. Coordinate index/policy writers until exit commits. A stale historical success cannot release the input. |

### H: completion and exit recovery

`preserved` requires committed canonical Acquisition/Document/Version/Original and
matching byte verification. `flow_complete` additionally requires every stage in
the still-current explicit plan, including the supported selected/limited index
contribution. `input_exited` requires its own observed, journaled input action.
AI, classification, organization, export and mirror are optional independent work.

Exit order: acquire existing Instance lifecycle/operation ownership; pin allowed
Inbox root/parent chain; validate Source/policy/plan and Original; resolve current
contribution; open the exact input with guards preventing write/replacement;
revalidate identity/bytes; record existing-operation intent; perform the guarded
action against that same input; record its observed result; release guards.
Windows implementation must use a delete-capable handle to the verified object,
deny concurrent writers/deleters and preserve parent identity through disposition.
The current read-only handle helper does not establish this capability. #382 owns
its typed implementation and native race/crash evidence. Failure to acquire the
required guard blocks exit; a path/hash check followed by unguarded unlink is insufficient.

Before commit: retain input, resume canonical ingestion. After commit/before OCR
or index: retain input, resume only authorized jobs. After flow completion/before
exit: revalidate and retry only the exit. After exit/before final receipt: reconcile
the preserved operation and exact input evidence; unexplained absence stays UNKNOWN.
Changed input remains intact and gets a new observation. Keep-file completion
leaves input in place intentionally. Empty-directory cleanup stays inside the
configured Inbox, requires the same boundary/identity guards and removes only
actually empty containers. Input disappearance never archives/trashes/purges knowledge.
Later index failure repairs the index without recreating an Inbox input.

## Product choices I/K/L — concrete proposal awaiting decision

These are **PROPOSTA AI**, not approved by the old planning documents or by this
document's creation. They are the remaining product decision requested from the
maintainer; internal algorithms above do not require separate product votes.

**I — existing Sources.** Convert in place, preserving Source/Document/Version,
history and provenance. Preview the role/policy change and the current backlog;
pause admission, reconcile the owned in-flight run, transfer the one observer and
save a revision-bound policy. Enable transit for future arrivals only after that
confirmation. Existing inputs remain until a second preview selects which already
preserved inputs may exit and which Originals need work. Changed policy/input or
inventory invalidates affected previews. Returning to keep-file stops future exit;
it does not recreate consumed input copies. On interrupted conversion, show the
recorded applied/not-applied/uncertain effects, reconcile and resume without a
second observer. Unsupported/unsafe conversions fail visibly.

**K — setup resume and effects.** Persist a minimal private per-Instance progress
draft: schema/revision, Instance reference, current/completed step references,
configuration revisions and operation IDs. No credentials, document bytes, logs
or external paths in the progress record. Keep unsubmitted sensitive selectors in
memory; reread actual services on resume. A different Instance starts its own draft;
missing/stale references mark the affected step for review. Draft is local device
progress, excluded from portable preference export; it grants no replay authority.
Prepare/Install/Test act only through explicit named actions with visible effects.
The final Apply and finish previews and applies only remaining selected settings,
uses expected revisions and reports partial application/readback; it starts no
backlog or deletion. Back changes navigation; Discard removes only unapplied draft.
Already applied settings, installed components and synthetic test documents remain
visible and have only their actually supported reverse actions. Reload never reruns
an effect. Six existing screens remain the design baseline; #379 validates the real
UI/copy with T01–T48, seven catalogs, keyboard, 320px and real 200% zoom. No prototype
or document approval counts as human/accessibility qualification.

**L — full release promise.** Keep every roadmap provider/identity/scope and mirror
profile in the manifest below. Guarded task write-back supports only completion
state and due date on existing tasks; each provider may expose only capabilities
proved by its stable public API. No title/body/assignee changes, creation/deletion,
email sending or calendar writes. Use one explicit current diff/confirmation per
operation; no automatic background write authority. A provider unable to implement
a promised capability remains a recorded release blocker requiring an explicit
scope decision; a synthetic conformance PASS never qualifies the live provider.
Real-account/remote publication tests are separately authorized, using disposable
synthetic data and exact destinations; this proposal grants none of that authority.

## Complete release workstream manifest

Codes below are planning IDs, not prematurely created issues/owners. Allocate the
actual owner PR just in time and accept actual main before the next owner. Existing
#377/#381/#382/#379/#391 retain their scope; do not close #391 after A alone.

| Order / workstream | Dependency | Exit criteria and evidence |
| --- | --- | --- |
| S00 — this step | Published Entitas, authorized campaign | Common contracts, I/K/L decisions, complete manifest/matrix/authority/recovery accepted; PR qualification and actual-main reconciliation recorded separately. |
| S01 — #393 startup/readiness | S00 accepted | Owned normal launcher/tray lifecycle, private binding, finite budgets, true critical failure/deep-diagnostic separation; exact frozen Windows clean/existing and fault matrix. |
| S02 — #377 language | S01 accepted | Saved value/selector/reopen/export agree in Cura/Current, seven languages/System; other preferences preserved. |
| S03 — #391-A | S02 accepted | Empty/space query, valid/invalid/reversed dates, no false zero, retained context/keyboard; full catalogs and actual internal-browser evidence from its handoff. |
| S04 — #381 provisioning | S03 accepted | Optional complete IT/EN offline kit, exact inventoried native engine/packs/renderer/worker/runtime; installed smoke and missing-component cases. |
| S05 — #381 trigger/backlog | S04 accepted | Per-Source new-work consent, reliable-native skip, complete OCR selection, G proof including approved limited results, selective Original backlog, R1–R7 and catalog-limit reconciliation. |
| S06 — #382 Inbox | S05 accepted | New/existing transit/keep behavior, I decision, guarded input exit, R8, conversion/recovery/races and no Original change/loss. |
| S07 — #379 UI/setup | S06 accepted | K decision, three daily journeys, six setup screens, real runtime/status/counts; T01–T48 and all 15 requirements retain distinct automatic/runtime/human evidence. |
| S08 — #391-B | S07 and A accepted | Friendly type labels/MIME stability; edit search/remove only filters with words/context preserved; no implicit OCR. |
| S09 — personal package qualification | S01–S08 accepted | Complete local path with AI off, OCR-ready/deferred, errors, recovery, exact Windows support/upgrade matrix; not qualification of all Concordia. |
| S10 — connector conformance | S09, Entitas objects | Identity/Source/capability/consent/revision/cursor contracts and provider-neutral Task/CalendarEvent mapping; credential references outside canonical/backup/export data. |
| S11 — Google adapter | S10 | Multiple identities with independently selected Gmail/Drive/Calendar capabilities and Sources; scope/revoke/reauthorize, page/cursor/reset, bounded resync and timezone/recurrence/cancellation. Existing read intake retained; no sending/calendar writes. |
| S12 — iCalendar adapter | S10, S11 acceptance | Multiple local/HTTPS ICS feeds; UID/recurrence-instance provenance, TZID/DST/all-day, exceptions/cancellation, bounded parsing/fetch and explainable duplicates. Local feed works offline. |
| S13 — Asana adapter | S10, S12 acceptance | Multiple OAuth identities and organizations/workspaces/teams/projects as separate Sources; projects/tasks/subtasks/assignees/dates/completion/comments/durable links, pagination/rate-limit/revocation and resync. |
| S14 — Tududi adapter | S10, S13 acceptance | Multiple endpoints/accounts/project-task scopes; stable public API capabilities, visible unsupported cases and isolated cursors/secrets; same task/mapping/recovery matrix. |
| S15 — guarded task write-back | S11–S14 accepted, L decided | Closed completion/due-date fields, per-identity/Source write consent, exact remote/local revisions, human diff/confirmation, idempotency, stale/replay/conflict and timeout-outcome reconciliation; privacy-minimizing audit. No rollback that overwrites newer remote state. |
| S16 — shared mirror contract | S15 accepted | Multiple identities/scope/destination, disabled/manual/scheduled policy, complete immutable staging generation, inventory/dry-run/privacy/size findings, external credentials and final manifest/receipt. Optional Originals/attachments/AI receipts require distinct include rules. |
| S17 — Git transport | S16 | Destination branch/path and commit identity, no needless commit on repeat, non-fast-forward/credentials/interrupt/reconnect; preserve canonical data and last valid remote history. |
| S18 — GitHub profile | S17 | Proven visibility/permissions, separately allowlisted public payload and explicit confirmation; unknown visibility blocks private payload. Disposable endpoint evidence only with scoped authority. |
| S19 — GitLab profile | S17, S18 acceptance | Same hosted contract with independently qualified profile and native credential/visibility errors; no inherited GitHub PASS. |
| S20 — Gitea profile | S17, S19 acceptance | Same hosted contract, exact supported version/API profile and isolated destination; no inherited host qualification. |
| S21 — local-folder mirror | S16, S20 acceptance | Transfer from completed staging to destination staging, final manifest comparison and qualified atomic generation activation; interruption preserves previous active generation. |
| S22 — rsync/SSH mirror | S16, S21 acceptance | Exact host/rsync/SSH versions, pinned host key, explicit credential references, bandwidth/windows/resume, destination staging and qualified activation; missing primitive fails visibly. No backup/restore claim. |
| S23 — integrated Concordia qualification | All above accepted | Provider/identity/revoke/mapping/write-back/mirror/local-only matrices, fresh native/browser/installer/recovery/security/docs and actual-main acceptance for the entire release. |
| Final identity/publication | S23 and every gate accepted | Align package/runtime/installer/changelog/docs/manifest/SBOM/checksums to 0.15.0/Concordia; normal qualified merge, actual-main acceptance, one official Preview dispatch, independent public-byte and provenance/receipt/kit/readiness rereads; only then close final owner and #383. |

Connector remote identity is keyed by connector instance, selected Source, stable
provider item and recurrence identity, with observed provider revision and mapping
version. Never key by display name or merge cross-provider identities because
content matches. Imported observations retain provenance; canonical manual edits
and provider updates use explicit revision/conflict handling. A deleted provider
item becomes an attributed observation/tombstone, not a local purge. Routing uses
only confirmed non-destructive rules for existing Areas/Projects.

Write-back preview binds remote revision/ETag (or a provider-supported equivalent
with proven conditional-write semantics), exact fields/values, current authorization,
Source and idempotency key. Refuse an adapter without a safe concurrency primitive;
read-then-unconditional-write is insufficient. An uncertain network outcome is
reconciled read-only before a new effect. Revocation stops access without deleting
imported knowledge. Calendar-only/local ICS sources expose no task-write control.

Mirrors never consume a live mutable Instance tree. Destination deletion is off;
any later cleanup requires a distinct exact source/destination-manifest preview,
path/byte impact and fresh confirmation. Destination root cannot be canonical,
Original storage, backup inventory or unknown. Changed inventory invalidates consent.
Remote deletion never causes local deletion; local archive/purge never rewrites Git
history. Partial generations cannot become active. Git is not canonical storage;
rsync is not backup proof. Bidirectional/multi-master sync remains excluded.

## Qualification matrix, threats and documentation

Every new row starts **NOT_RUN** on the future candidate. Retain original FAIL,
error and UNKNOWN with source/run/attempt/job and demonstrated correction evidence.
Automatic, browser, installed-runtime and human evidence are different columns,
never interchangeable. Existing human exceptions apply only to their old campaign.

| Matrix | Required cases | Responsible slice / documentation |
| --- | --- | --- |
| Windows | Home/Pro 25H2 x64, per-user/local NTFS, clean, exact official 0.14→candidate and 0.13→candidate; base/no OCR, components disabled, authorized OCR; Q0 empty/Q1 1,000 Versions/Q2 slow diagnostics/Q3 interrupted jobs; cold/warm, normal/fault/cleanup and identity preservation. Record actual build/KB, CPython patch, assets/digests/architecture/permissions. | #393/#381 and integrated gates; Windows architecture/support/install/upgrade EN/IT. Existing 30s normal smoke retained. Source tests or Windows CI image without this exact OS matrix do not attest Home/Pro25H2. |
| Text/Inbox | Reliable PDF, scanned EN/IT, mixed/empty/partial/encrypted/malformed, missing engine/pack/renderer, canceled/stale authorization; index/proof/backup missing or stale; cap boundaries; changed input/reparse/two workers and every commit/OCR/index/exit crash boundary; keep/transit/new/conversion/backlog. | #381/#382, OCR/search/Inbox/backup/recovery EN/IT; R1–R8 mapped above and T09–T16/T23–T34. |
| UX/search | Cura/Current, all seven catalogs/System, themes, keyboard/focus, real browser 320px/200% zoom, empty/loading/error/recovery; test acquisition/read/search/Original and saved-setting readback; T01–T48, AC01–AC15. | #377/#391/#379 and package integration; existing handoffs remain detailed requirements. Human/screen-reader/semantic review remains NOT_RUN/UNVERIFIED until actually performed. |
| Providers | At least two independent instances/selections for each provider, duplicate bytes with distinct provenance, recurrence/exception/cancellation/TZ/DST, page limits/cursors/full-resync/replay, expired/revoked grants, stale/conflicting provider records, unsupported APIs and secret/SSRF/redirect/hostile payloads. | Shared conformance + each adapter; per-provider support/scope/authorization/mapping/recovery guide and public API/version evidence. Synthetic conformance and authorized live qualification recorded separately. |
| Writes | Completion and due-date diffs independently and together; stale local/remote state, double submit/replay, unauthorized field/Source/account, pause/revoke, network failure before/after send and unknown result; no newer-state overwrite or autonomous creation/deletion. | Task write-back; authority/threat/receipt/user guide EN/IT. |
| Mirrors | Multiple destinations/scopes, secret/sensitive-data findings, public/private/unknown visibility, include-rule revocation, changed manifest, NFF, bad host key/credentials, disconnect/resume, repeat no-op, disk-full and interrupted transfer/activation; previous generation preserved and exact final manifest. No network or process invocation when disabled/local-only/no-GitHub/no-rsync. | Shared contract, each transport/host; privacy, components/licenses, atomic activation, recovery and deletion boundaries EN/IT. Actual publication/deletion tests require separate scoped authority. |
| Release | Unchanged-source Ruff/full pytest/diff, canonical byte verification, applicable native tools/catalog/build/release dry-run/offline verification, all permanent workflow/run/attempt/job originals, dependency/license/advisory applicability, complete reviews/findings/threads, fresh effect/policy/owner/ancestry preflight, expected-head normal merge and actual-main checks. | Every candidate, then integrated/final owners; qualification record and closed support/component matrices. Publication uses official repository workflows only. |

Threat delta: foreign startup service/replayed proof, replaced root/input, stale
authorization/derived selection/index proof, write-after-preview, duplicate worker,
hostile PDF/ICS/provider text, overlarge catalog/feed, secret leakage, SSRF, wrong
account/destination, public mirror exposure, SSH host substitution and partial
generation activation. Each threat has a negative/recovery case in the matrix.
Use synthetic fixtures only; no live credentials or personal paths in source/logs/CI.
Local offline AI-Off operation remains complete without any provider or mirror.

## Step 0 exit and current evidence limits

Accept step 0 only when all of these are observed in its owner ledger:

1. Fresh baseline/pin/lane reconciliation and actual scoped user authority.
2. Explicit decisions on the I/K/L proposal, including any requested changes.
3. Static contract review resolves A–J, R1–R8, scope/authority/recovery conflicts and
   assigns every implementation detail/asset/support value to its pre-test gate.
4. Complete manifest, dependency/acceptance order, matrices, threat and EN/IT
   documentation responsibilities, with no omitted Concordia provider/transport.
5. Qualified exact-source documentation candidate, complete applicable CI/reviews/
   originals, fresh normal integration preflight and actual-main acceptance.

This draft meets no acceptance by being written. Product decisions, source PR
qualification/integration and all new runtime/browser/installer/live-provider
qualifications remain pending. Native fixture tests can validate existing seams;
they cannot prove the proposed exit handle, binding, worker or producer evidence.
Exact Windows kit assets and performance/durability claims belong to their actual
candidate, not to fabricated pre-implementation hashes or PASS labels.

The initial local `git ls-remote` failed to connect to the configured proxy; this
is a retained transport failure, not a GitHub repository denial. The connected
GitHub tool can read repository objects. Its availability does not prove arbitrary
shell-network, CI-original-download or installed/internal-browser capability.
Missing required access remains a named dependency while independent work continues.
