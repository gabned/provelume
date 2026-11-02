# Concordia S07 — daily journeys and personal setup

Owner: `product/0.15-s07-ui-setup`, PRODUCT / REPOSITORY_POLICY, PR-local legacy.
Baseline: main `0f61868514e043fa5463f4958eaff992dc6e31ea`, accepted S01–S06
integration #433. Protocol source remains
`02317e02767958faa3de5bb6d245ca3440360d9e`; Lifecycle v2 remains deferred.
Application identity stays 0.14.0 / Entitas / development.

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
