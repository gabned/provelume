# Concordia S07 — daily journeys and personal setup

Owner: `product/0.15-s07-ui-setup`, PRODUCT / REPOSITORY_POLICY, PR-local legacy.
Baseline: main `0f61868514e043fa5463f4958eaff992dc6e31ea`, accepted S01–S06
integration #433. Protocol source remains
`02317e02767958faa3de5bb6d245ca3440360d9e`; Lifecycle v2 remains deferred.
Application identity stays 0.14.0 / Entitas / development.

The first increment's post-merge acceptance is retained at #435 comment 6596643672.
Actual main subsequently advanced through #436/#437; acceptance of
`a5786ec2a59cbb3e69ffe9f575504eb0157e5623` is retained at #437 comment 6596813619.
Only then was the remaining S07 owner `product/0.15-s07-setup-coordinator` allocated
in draft #438, with original BIND at comment 6596856526. This document is a
qualification projection; the PR-local ledgers remain the authoritative history.

Scope is #379: Acquisizione, Sorgenti, Documento and the six personal setup
screens, consuming the existing preservation, OCR, review and scheduler services.
Decision K in `docs/architecture/concordia-step-0.md` governs progress, effects,
revision checks, readback and recovery. No setup draft grants replay authority.
S08 and the subsequent Concordia workstreams retain their ordered acceptance
and separate owners. No provider, mirror or final publication belongs to S07.

Source requirements: #379 comments 6241142182 (six screens and AC01–AC15),
6241608718 (T01–T48), 6245685981 (handoff), and the accepted step-0 contract.
Every new candidate result starts NOT_RUN. Automatic source tests, actual browser
observations, installed Windows tests and human observations are separate.

The maintainer is the sole user and will perform manual checks on his Windows 11
Pro 25H2 production PC. VMs, other accounts, Home machines and extra testers are
not prerequisites. Manual, screen-reader, linguistic and real 200% zoom results
remain ASSIGNED_TO_MAINTAINER / NOT_RUN until actually observed. This does not
qualify the wider historical Windows support matrix.

Implementation and qualification are in progress. No UI, runtime, accessibility
or integration PASS follows from this preparation record.

## First implementation increment

The first ordered UI increment adds three read-only daily projections and the
private device-progress primitive. Acquisizione links to file/note Capture modes,
watched folders and real recent Documents. Sources separate role, retention,
configured schedule, live runtime, current bounded input counts, index gaps,
Source OCR consent, component availability and last observed job. Unknown or
partial observations remain visible; retained files are not counted as unfinished
solely because they are still present. Document separates selected text/index from
actual Library materialization, retaining Original, provenance and existing review
controls. Existing source registration, scheduler, Capture, OCR and Inbox services
remain the writers; these projections grant no new authority.

`SetupProgress` stores only the schema, Instance reference, monotonic revision,
step references, configuration digests and real operation references beside the
host launcher settings. It contains no paths, credentials, document bytes or logs.
Reads create nothing; CAS rejects a stale tab. Discard clears unapplied progress,
preserving operation references and revision history. The six-screen coordinator
and its bounded synthetic test operation are the next ordered UI increment; this
foundation does not declare S07 accepted or #379 complete.

The new synthetic source tests cover real keep-file counts (two present / one
without searchable text), read-only byte invariance, unavailable observation,
selected text/index/Library readback, runtime state, both shells/all seven catalogs,
private progress/CAS/reopen/discard and rejected sensitive/foreign references.
Initial targeted run: 7 fixture-setup failures / 18 passes because the test omitted
the existing schema-3 requirement for Preview. Correction sets the test fixture's
actual supported schema; the subsequent targeted run is 25/25 PASS. No product
schema or assertion was weakened. Catalog automatic validation passes with zero
missing keys in seven catalogs; linguistic review remains UNVERIFIED.

Chromium observations in this cloud host did not produce screenshots: the first
attempt stalled and was terminated; the bounded diagnostic attempt timed out
(exit 124). Native HTTP returned 200, but that is not rendered-browser evidence.
Browser reflow and real 200% zoom remain NOT_RUN, assigned to the maintainer.
No screenshots or accessibility PASS are claimed.

## Matrix tracking

This table tracks the entire requested matrix, including work not yet delivered
by this first increment. PARTIAL means only the named source-level seam has run;
it is never a PASS for the whole family. Runtime means the installed Windows
profile, separate from synthetic native service tests. All manual cases belong
to the sole maintainer's Windows 11 Pro 25H2 PC. No extra environment is required.

| Family | Automatic source evidence in first increment | Installed runtime | Human |
| --- | --- | --- | --- |
| T01 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T02 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T03 | PARTIAL: both shell/catalog renders; preference persistence remains S02 | NOT_RUN | NOT_RUN |
| T04 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T05 | PARTIAL: folder/Original/Library roles rendered | NOT_RUN | NOT_RUN |
| T06 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T07 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T08 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T09 | PARTIAL: current retention mode projected | NOT_RUN | NOT_RUN |
| T10 | PARTIAL: read-only Source data invariance | NOT_RUN | NOT_RUN |
| T11 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T12 | PARTIAL: actual OCR capability and consent projected | NOT_RUN | NOT_RUN |
| T13 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T14 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T15 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T16 | PARTIAL: UI catalog independent of OCR consent | NOT_RUN | NOT_RUN |
| T17 | PARTIAL: runtime stopped/active/error projection | NOT_RUN | NOT_RUN |
| T18 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T19 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T20 | PARTIAL: host removal capability disclosed | NOT_RUN | NOT_RUN |
| T21 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T22 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T23 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T24 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T25 | PARTIAL: actual index row readback; no trial coordinator | NOT_RUN | NOT_RUN |
| T26 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T27 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T28 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T29 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T30 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T31 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T32 | PARTIAL: two present / one text-pending, then zero pending | NOT_RUN | NOT_RUN |
| T33 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T34 | PARTIAL: private progress stale-CAS rejection | NOT_RUN | NOT_RUN |
| T35 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T36 | PARTIAL: progress reopen, no effects on read | NOT_RUN | NOT_RUN |
| T37 | PARTIAL: discard preserves operation references | NOT_RUN | NOT_RUN |
| T38 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T39 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T40 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T41 | PARTIAL: three real routes in both shells | NOT_RUN | NOT_RUN |
| T42 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T43 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T44 | PARTIAL: decorative icon semantics and shared responsive CSS | NOT_RUN | NOT_RUN |
| T45 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T46 | PARTIAL: seven complete catalogs; human review unverified | NOT_RUN | NOT_RUN |
| T47 | NOT_RUN: six-screen/trial integration remains pending | NOT_RUN | NOT_RUN |
| T48 | PARTIAL: synthetic service calls, no AI consent change | NOT_RUN | NOT_RUN |

The exact original requirements and expected outcomes remain in #379 comment
6241608718. This tracking table does not narrow any family or substitute inherited
backend tests for the required wizard/browser/runtime observations.

| Requirement | Families (original mapping) | Current qualification |
| --- | --- | --- |
| AC01 — Primo avvio e default comprensibili | T01, T03–T05 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC02 — Esistente, identità e preferenze | T02, T10–T11, T41, T47 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC03 — Cartelle, permessi e supporto | T05–T08 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC04 — Transito/conservazione e conversione | T09–T11, T28, T32 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC05 — Readiness, errori e rinvio OCR | T12–T16, T27, T31 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC06 — Trigger OCR e skip nativo | T16, T18, T23–T24 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC07 — Runtime, modalità e avvio | T17–T20, T40 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC08 — Prova delimitata e consultazione reale | T21–T23, T25–T27, T41 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC09 — Integrità ed esito Inbox | T11, T28–T33 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC10 — Crash, ripresa e idempotenza | T14, T30, T33–T34, T36, T39 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC11 — Navigazione, bozza ed uscita | T04, T15, T35–T37, T42 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC12 — Concorrenza, applicazione e read-back | T03, T08, T17, T19, T38–T41 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC13 — Lingue, temi, reflow ed accessibilità | T03, T16, T20, T42–T46 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC14 — Upgrade qualificato | T47 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |
| AC15 — Locale, AI e privacy | T01, T07, T13, T15, T21, T48 | PARTIAL / NOT_ACCEPTED; runtime/human NOT_RUN |

Additional regression coverage exercises the bundled Capture renderer: a successful
local receipt offers Apri documento for its exact Instance, while paired, stale or
malformed identities do not gain a canonical-document link. Two intermediate Node
fixture failures (immutable injected dependency, then missing mock DOM dataset)
are retained in the owner evidence; the fixture was corrected without changing
product checks. The combined targeted run is **59 PASS**. The initial full run was
explicitly interrupted after a source change at 3,188 PASS / 20 SKIP / 419 subtests;
it is **INTERRUPTED**, not a full-suite PASS. Final native and exact-head remote
qualification belong to the unchanged committed candidate and its PR ledger.

A subsequent source review found two edge states: an unobserved non-local Source
must display an unknown input count rather than its initialized zero, and Capture
must require an acquired receipt before offering a Document link. Both are fixed
with negative/state regression coverage (32 targeted PASS). The superseded
`d8cfe62` full local run was interrupted after the source correction; any teardown
KeyboardInterrupt/pytest stash diagnostic belongs to that interruption. Its
partial results are not reused as final qualification. Fresh final native/CI
results bind the corrected head recorded in the owner PR.

The final state review also checks stale Source consent and Inbox policy against
their actual current revisions. A missing/disconnected Inbox retains its configured
role and retention choice while showing an unavailable observation and blocked
policy; settings changes do not leave a misleading active-consent label. A real
approved metadata-only result is shown as title/metadata search without body text,
with unchanged Originals. Accepted limited OCR has its own visible label. The
progress reader reuses the launcher's symlink/reparse guard and refuses oversized,
duplicate-key or excessively nested records without overwriting them.

The complete targeted set for this increment is **66 PASS**. The superseded
`5476b1c` full run was interrupted at 2,961 PASS / 20 SKIP / 419 subtests because
these state corrections changed its source. Source checks have not been weakened;
only the final unchanged-head full run and remote histories can qualify integration.

## Remaining S07 owner — bounded trial integration in progress

The current draft adds exact named synthetic input bindings and a durable one-shot
permit, consumed by the existing ingestion, OCR, Inbox and scheduler owners. It
does not enable a whole-folder watcher, alter Source/global consent, issue manual
OCR commands or copy data directly into canonical storage. Acquisition uses the
original deterministic ingestion run/item/acquisition identities and guarded reads
of the exact permitted bytes. The existing `ocr.execute` owner emits the index
proof and terminal receipt; reliable native text uses its actual index-only skip.
Trial input disposition shares S06's final guarded proof/disposition implementation.

Explicit consultation verification requests actual Document/Original routes through
the application's HTTP stack, checks the response statuses/body identities and
Original bytes, and retains each success/failure in ordered operation receipts.
Readback checks the exact Version's content-column FTS match; a title match cannot
qualify search. A failed new consultation blocks current completion without
rewriting earlier successful acquisition, Original preservation or legitimate exit.
Read/reopen does not replay operations. The six-screen coordinator, scoped Source
activation/handoff and complete rendered/frozen/manual qualification are still in
progress; this backend increment does not accept S07 or close #379/#383.

The first real two-document run retained two failures: the missing initial scoped
index update, and `ocr_decompression_limit_exceeded` for the public recipe's
38,576-byte scan. The index now updates only the two selected contributions, with
`recover_missing_derived=False` and `allow_full_rebuild=False`; an existing index
needing global repair keeps its separate maintenance gate. A new empty space may
prepare its empty index through the explicit trial action before acquisition.

The old compressed scan and its original public recipe remain unchanged evidence.
The new recipe `scripts/generate_setup_trial_fixtures.py` stores the identical
raster pixels with zlib level 0. New scan: 3,869,707 bytes, SHA-256
`cf6f97c71c1f2b3752d37a335e0985edf2104c6b9b0b3fbf9543a3813ae21b97`.
Native PDF: unchanged 880 bytes, SHA-256
`3c04a38cad5c5ddcf98f1b8686bd8a2139f0a38b0682f048236a8cdf4a72414b`.
No OCR limit, DPI, dependency pin, snapshot, workflow, gate or threshold was
relaxed. The sentinel is generated for test preparation and is never packaged or
permitted as an input. Resource reproducibility is separate from service results.

Current Linux service evidence includes real Tesseract 5.5.0, English data,
Pillow 13.0.0 and the already accepted OCR-profile PDFium wheel 5.13.0 (its exact
checked-in workflow hash was verified before provisioning the missing component).
The synthetic scan automatically produces an OCR job/derived contribution, native
PDF skips OCR, Original bytes and unrelated sentinel remain unchanged, and keep
disposition is physically observed without modifying existing Source settings.
This is Linux automatic service evidence, not Italian-pack, installed Windows-kit,
human, linguistic, screen-reader or real-zoom qualification. All required methods
and unexecuted variants retain their own outcomes. The known Spanish `/sources`
320px reflow finding remains open; no CSS correction is qualified here.

## Remaining owner #438 — coordinator candidate

The preceding matrix and browser failures belong to the first increment. They
remain historical observations. The owner [#438](https://github.com/gabned/provelume/pull/438)
now implements all six screens at `/setup`, in both delivered shells, and links
Acquisition, Sources and Document to that same coordinator. **S07 is not accepted.**
Exact-source native/browser/installed results and their original failures belong
in #438's public ledger. No row below promotes an unexecuted variant or human test.

K uses the existing private device progress record: Instance, navigation/completed
steps, revision digests and operation references. Unsubmitted selectors remain in
a bounded session; missing or stale selections need review. GET only reads current
services and receipts. Prepare can create only the chosen separate local folder
and its own temporary permission probe; a new Source remains paused. Existing
Sources keep their identity and activity. New Space creation/selection uses the
existing native launcher, preserving its startup binding; names are validated
before creating files. The wizard does not relocate or replace the active Space.

The official offline-kit service now offers a read-only, build-bound inventory
preview. Install rechecks that preview and invokes the same importer. A matching
release receipt or an independently checked explicit SHA-256 uses the existing
provisioning authority routes; neither establishes independent publisher identity.
Development kit material remains a candidate. Preview/preparation grants no Source,
backlog or AI consent and does not enable global OCR. Actual engine/pack/renderer
readiness remains distinct from selected settings and kit bytes.

Trial-owned filenames are reserved before copying. The existing observer and
normal ingestion exclude only those names, including after an interrupted copy.
One-shot authority is consumed by the existing ingestion, automatic OCR, scheduler
and S06 Inbox owners; no second watcher, queue, temporary Source grant or manual
OCR is introduced. Cancellation and repeated browser submissions do not resurrect
a job. A new trial is a separate explicit action and creates new Documents.

Apply binds the current preferences, Source, schedule, consents, root and displayed
Inbox inventory. It changes selected remaining settings and reads them back,
retaining each stage's intent/result. New-Source activation excludes its initial
backlog using bounded metadata. Existing consent scopes cannot be widened for
unrelated Sources. Not now preserves an absent OCR policy. A durable admission
barrier prevents incomplete application from starting general Source/AI intake.
Interrupted policy/observer activation finishes the same observer. If unrelated
preferences changed during a partial application, the explicit Pause and review
operation pauses admission and preserves applied effects, components, Documents
and external preferences; remaining choices require a fresh review/trial.

A completed trial receipt is consumed before Apply. The old permit then stays
stale for future producer/exit work when its settings change. A separate read-only
post-Apply check still verifies its Original bytes, selected contribution and exact
content search; it grants no new producer authority. A later failed probe,
changed Original or missing index prevents a false completed summary.

The existing installed OCR workflow additionally runs the frozen setup entry for
keep and transit, exact IT/EN resources, automatic scan/native producers, six
actual HTTP template responses, kit preview/import, targeted Apply and a future
native acquisition through the configured Source with real quiescence. Its
Windows runner result does not attest the maintainer's Windows 11 Pro 25H2 PC.
No workflow, dependency, snapshot, OCR limit or gate was relaxed.

Current source exercises are listed below. `PARTIAL` covers only the named cases;
all other variants retain NOT_RUN. Browser observations are separate from HTTP
form/service tests. The exact browser combination inventory and candidate identity
must be read from the owner ledger, not inferred from this table.

| Family | Automatic source exercises | Browser | Installed runtime | Manual |
| --- | --- | --- | --- | --- |
| T01 | PARTIAL: six read-only screens, defaults, no intake | separate ledger | pending exact CI | NOT_RUN |
| T02 | PARTIAL: existing identity preserved; native selector retained | NOT_RUN selector | pending exact CI | NOT_RUN |
| T03 | PARTIAL: saved language/readback, seven catalogs, both shells | separate ledger | pending exact CI | NOT_RUN |
| T04 | PARTIAL: invalid new name creates no files; native retry | NOT_RUN native entry | pending exact CI | NOT_RUN |
| T05 | PARTIAL: internal/Input/Original roles and paths | separate ledger | pending exact CI | NOT_RUN |
| T06 | PARTIAL: local create, overlap/root/identity negatives | separate ledger | pending exact CI | NOT_RUN |
| T07 | PARTIAL: own probe, sentinel/config unchanged | separate ledger | pending exact CI | NOT_RUN |
| T08 | PARTIAL: live root and permission guards | NOT_RUN permission matrix | pending exact CI | NOT_RUN |
| T09 | PARTIAL: transit default, explicit keep, runtime capability | separate ledger | pending exact CI | NOT_RUN |
| T10 | PARTIAL: existing activity/identity and scope preservation | NOT_RUN full variants | pending exact CI | NOT_RUN |
| T11 | PARTIAL: existing S06 conversion owner; revision/inventory gate | NOT_RUN full conversion | pending exact CI | NOT_RUN |
| T12 | PARTIAL: selected versus actual OCR capability | separate ledger | pending exact CI | NOT_RUN |
| T13 | PARTIAL: read-only kit inventory; import separate, no consent | NOT_RUN real kit browser | pending exact CI | NOT_RUN |
| T14 | PARTIAL: importer reuse/fault contracts; no GET replay | NOT_RUN all kit faults | pending exact CI | NOT_RUN |
| T15 | PARTIAL: explicit Not now; no new OCR grant or fake text | separate ledger | pending exact CI | NOT_RUN |
| T16 | PARTIAL: independent UI and OCR languages | separate ledger | pending exact CI | NOT_RUN |
| T17 | PARTIAL: desired mode and real runtime separate | separate ledger | pending exact CI | NOT_RUN |
| T18 | PARTIAL: existing Source/scheduler; future-only baseline | NOT_RUN slow copy matrix | pending exact CI | NOT_RUN |
| T19 | PARTIAL: preserve startup; installed-only action/readback | NOT_RUN OS sign-in | pending exact CI | NOT_RUN |
| T20 | PARTIAL: unsupported startup/transit disclosed on Linux | separate ledger | pending exact CI | NOT_RUN |
| T21 | PARTIAL: exact resources; active Source, sentinel, no AI grant | separate ledger | pending exact CI | NOT_RUN |
| T22 | PARTIAL: native acquisition/Original/body search | separate ledger | pending exact CI | NOT_RUN |
| T23 | PARTIAL: real automatic English scan, exact search | separate ledger | pending IT/EN CI | NOT_RUN |
| T24 | PARTIAL: real native index-only skip | separate ledger | pending exact CI | NOT_RUN |
| T25 | PARTIAL: exact Version content-column match | separate ledger | pending exact CI | NOT_RUN |
| T26 | PARTIAL: real Document/Original responses, hashes, failed probe | separate ledger | pending exact CI | NOT_RUN |
| T27 | PARTIAL: failed consultation blocks; same Documents retry | NOT_RUN all browser faults | pending exact CI | NOT_RUN |
| T28 | PARTIAL: same S06 guarded exit; Linux unavailable disclosed | NOT_RUN Linux transit | pending exact CI | NOT_RUN |
| T29 | PARTIAL: actual keep outcome and unchanged inputs | separate ledger | pending exact CI | NOT_RUN |
| T30 | PARTIAL: changed/corrupt/foreign inputs and permits refused | NOT_RUN every fault | pending exact CI | NOT_RUN |
| T31 | PARTIAL: OCR failure/cancel cannot establish completion | NOT_RUN all failures | pending exact CI | NOT_RUN |
| T32 | PARTIAL: existing shared counts; no absent-to-zero inference | separate ledger | pending exact CI | NOT_RUN |
| T33 | PARTIAL: selected preparation/trial/Apply crash boundaries | NOT_RUN full crash matrix | pending exact CI | NOT_RUN |
| T34 | PARTIAL: nonce/CAS/replay/cancel/session restart | separate ledger | pending exact CI | NOT_RUN |
| T35 | PARTIAL: selection/dependency digests, stale trial gate | NOT_RUN every change | pending exact CI | NOT_RUN |
| T36 | PARTIAL: read-only resume from real operation references | separate ledger | pending exact CI | NOT_RUN |
| T37 | PARTIAL: discard preserves effects/references/Documents | NOT_RUN human exit variants | pending exact CI | NOT_RUN |
| T38 | PARTIAL: stale prefs/Source/root/settings reject old Apply | NOT_RUN all concurrent changes | pending exact CI | NOT_RUN |
| T39 | PARTIAL: per-stage recovery and explicit pause/re-review | NOT_RUN complete UI faults | pending exact CI | NOT_RUN |
| T40 | PARTIAL: targeted readback, missing proof prevents completion | separate ledger | pending exact CI | NOT_RUN |
| T41 | PARTIAL: shared services and setup links on three daily pages | separate ledger | pending exact CI | NOT_RUN |
| T42 | PARTIAL: labels, order, current step, error focus markup | pending exact observations | pending exact CI | NOT_RUN |
| T43 | No screen-reader PASS inferred | NOT_RUN screen reader | NOT_RUN | NOT_RUN |
| T44 | PARTIAL: text/icons, scoped targets/focus/styles | separate ledger | pending exact CI | NOT_RUN |
| T45 | PARTIAL: scoped responsive setup CSS | separate ledger; real zoom NOT_RUN | pending exact CI | NOT_RUN |
| T46 | PARTIAL: complete catalogs, linguistic UNVERIFIED | separate ledger | pending exact CI | NOT_RUN |
| T47 | No upgrade/platform acceptance inherited | NOT_RUN | NOT_RUN exact release matrix | NOT_RUN |
| T48 | PARTIAL: synthetic local pipeline, consent/data invariants | separate ledger | pending exact CI | NOT_RUN |

AC01–AC15 retain the exact family mapping above and remain PARTIAL/NOT_ACCEPTED
until their required variants and methods have actual evidence. In particular,
AC13 has no human linguistic/screen-reader/real-zoom PASS, and AC14 has no exact
Concordia upgrade/platform PASS. The Spanish `/sources` 320px finding is still
open; scoped setup CSS is not a qualified correction to that page.

The [maintainer check sheet](concordia-ui-s07-pc.md) uses only his Windows 11 Pro
25H2 production PC/account with synthetic test inputs. It requests no VM, extra
account or other tester. This candidate keeps version 0.14.0/development; later
owners and release identity/publication stay gated by the accepted plan.

The follow-up review reproduced the original Spanish Source registration overflow
and a long synthetic filename expanding the Current Document header at 320px.
The candidate now constrains only Source registration controls and permits the
Document header/breadcrumb to wrap; this is not a prior-head correction or a
human reflow PASS. Exact-head automated browser qualification must establish the
result before that finding can change state. Selected OCR components and their
localized errors are shown separately, and a trial using different draft settings
cannot enable Continue or mark the new choice complete. Scan search links use the
language actually proved by that trial. The summary separates saved settings,
current runtime/Source activity and the actual trial result.
