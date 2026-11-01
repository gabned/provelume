# Concordia S05: Source OCR, explicit selection and index evidence

Status: **PREPARATION CANDIDATE / NOT_ACCEPTED**. This work is stacked on the
S01–S04 candidate in #431. Its implementation and synthetic checks do not accept
that prerequisite or qualify a production-PC observation. The existing owner and
historical receipts of #431 remain unchanged. Application identity remains
0.14.0/development; S06 input exit and subsequent Concordia slices are excluded.

## Consent and intake

The `ocr_sources` review provider uses the existing local authority, pure preview,
one-use browser confirmation and lifecycle/CAS transaction. Its Source policy
records the exact Source/configuration revision, OCR settings, languages and
confirmation. Installing a kit or changing global OCR settings grants none of
this authority. Local review capabilities and Source consent remain distinct.

An enabled Source policy applies to future PDF acquisitions only. Reobserving an
unchanged file does not create a request. The ingestion owner admits committed
acquisitions through the existing `ocr.execute` scheduler; a durable initial
request can exist before component inspection. Missing components therefore
remain an actual scheduler outcome, rather than a successful ingestion implying
successful OCR. Original acquisition and derived completion stay distinct.

Global OCR disablement prevents new OCR execution. Reliable native PDF text and
an already selected valid derivation can be indexed without starting OCR. Source,
settings, Version, Original or authority changes invalidate dependent requests.
Disabling future admission does not mark a required unfinished stage complete.
The existing scheduler owns cooperative page boundaries, pause/resume, retry
budgets and terminal cancellation. A cancelled permit cannot be replayed into a
new job; a different request requires its own explicit authorization.

Historical work requires a separate exact Version selection and fresh preview.
It reads the preserved managed Originals, without rereading the Source path.
One permit selects at most 1,000 current PDF Versions and 25 MiB of Original input;
each job retains the existing OCR page, byte, time and retry limits. Direct
Version/Document/Original reads replace an Instance-wide 500-Document inventory
before Source filtering. Browser choices use the existing 10,000-record catalogue
bound and a 1,000-Version Source selection bound. Exceeding a bound is visible;
there is no automatic splitting or limit increase. Superseded Versions need the
existing explicit current-Version decision before this active-index profile.

## Selected text and limited results

The shared reading/indexing selector binds the Version and Original, exact
registered artifact, generator/settings and every OCR page's observations and
text checksums. Full page coverage is checked against the producer's frozen page
plan. No latest-file selection, partial bundle, empty OCR success or automatic
promotion to verified truth is used. Reliable native text keeps the existing
32-significant-character / 0.85 printable-ratio defaults and actual settings.

Uncertain complete OCR requires explicit acceptance for that Version and bundle.
Alternatively, a reviewed metadata-only profile indexes the title with an empty
body; Source, media type and acquisition time remain exact filter fields. This is
an explicit search limitation, not a declaration that the document has no text.
The confirmation records the selection and permits its exact index request.
Unsupported annotation indexing blocks the dependent contribution; human
corrections keep their separate authority and are never silently merged or
overruled by engine text. Passive email validation retains its dedicated path.
Source bundle metadata records `derived-complete`, independently of the scheduler
outcome: retaining uncertain text for review cannot label its failed index job a
success. Final search applicability still requires the exact terminal proof.

## Producer evidence and recovery

Source OCR and reviewed processing indexing own `state/processing/index-evidence`;
maintenance indexing owns its separate `state/maintenance/index-evidence` root.
Versioned producer adapters share one per-Version applicability resolver. Existing
maintenance run/job/receipt schemas are unchanged; new proof packets remain
separate from those historical records.

Each attempt freezes its final selection and content-addressed input snapshot
before active FTS publication. One deterministic `publication_a<attempt>.json`
binds that snapshot, selection revision, exact seven-field row digest and physical
producer directory. Final records use pinned local parents, private staging,
flush and no-overwrite publication. Identical bytes are reusable; conflicting
bytes block. Attempt/file bounds derive from the scheduler's maximum eight
attempts. Native filesystem guarantees remain those of the existing helpers;
untested power-loss or Windows race durability is not claimed.

The read-only resolver follows the exact terminal scheduler receipt and attempt,
never a directory search for a favorable result. It rechecks the current request,
Source consent, Original bytes, selection and actual FTS row. A snapshot or batch
success alone is insufficient. A failed/cancelled attempt retains that outcome.
Repair can attest `reconciled_current_state`, with unknown original actor/time
remaining null; it cannot reconstruct historical success. The scheduler emits
terminal success only after final evidence publication and readback.

Deep validation recognizes the new evidence and selection state before backup.
Backup uses existing lifecycle ownership and retains final history. Restore
preserves evidence while old physical-root/index applicability must be rechecked;
the historical receipt alone cannot certify the restored current contribution.
There is no GET repair or Inbox deletion.

## Qualification boundaries

Automatic tests use synthetic PDFs, synthetic engine adapters, actual review
transactions, the existing scheduler, real FTS rows and native local-file helpers.
They cover future-only consent, selective historical permits, reliable-text skip,
complete selection, explicit limited results, idempotency, cancellation, page
pause/resume, proof-write interruption/retry, exact-attempt resolution, changed
Original/text/row refusal, backup/restore and Source/catalogue limits. Seven
catalogues and both existing layouts retain separate rendering checks.

Exact-source Ruff, full pytest, diff-check and applicable permanent CI are required
on the final committed candidate. Installed component and earlier field-package
results remain bound to their original source/installer hashes. They do not
qualify the new Source path by transfer.

Production-PC installation, real desktop/browser use, language review and manual
Windows observations remain **ASSIGNED_TO_MAINTAINER / NOT_RUN**. The maintainer
is the sole current user and uses Windows 11 Pro 25H2 on his production PC; no VM,
Home edition, extra account or additional tester is a prerequisite. No runtime
data or personal files are used by these automatic tests.
