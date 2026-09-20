# Attributed OCR and transcript annotations

Cura S05 exposes `/review/annotations` and an editor for an exact `repr_…` or
`derived_…` result. Current and Preview use the same provider and shared review
coordinator. The normal application attaches these routes; the recovery app does
not expose a mutation path. Capabilities default to disabled and require explicit
local configuration. Browser operations remain manual even when a domain policy
uses controlled automatic mode.

## Evidence and editing

The reader consumes existing OCR document bundles, native audio/video ASR
representations and subtitle cue bundles. It does not schedule extraction or
ensure missing state. Each result is bound to its canonical Version, the streamed
Original checksum and size, result/output identity, recipe and implementation or
engine/model identity. Every native output is checked before editing. Missing,
changed, corrupt, linked or oversized evidence denies saving; it is never an
empty successful result or an invitation to transfer old edits to a new result.

Selecting a segment seeks the local audio/video player to its authentic time
anchor or selects the OCR page/region. PNG/JPEG image regions use the attested
source-pixel dimensions. PDFs use the browser's same-origin native PDF viewer and
page fragments; its own zoom and page navigation are browser controls, and a PDF
region is reported numerically rather than represented as an exact overlay on
that viewer. TIFF display and audio/video codec support depend on the browser.
Unsupported or unattested media remains explicit; subtitle cue timing alone does
not attest an accompanying recording. No HTML or SVG original is embedded.

Unknown confidence stays unknown. Previous/next uncertainty navigation includes
unknown scores and scores below 0.5; it does not infer quality. Text editing is
keyboard accessible, including Ctrl/Cmd+Enter to preview. Splits retain the
original anchors on both children; merges retain the union of adjacent segments'
lineage and anchors. Neither operation invents finer time/region alignment.
Speaker labels are attributed proposals, never verified person identities.

Preview shows a before/after diff bound to the same source/history head as its
plan. Saving is a separate explicit action. Further edits invalidate the pending
preview. Undo previews a selected earlier state and appends a new revision; it
never removes the previous journal. A fresh editor load displays the retained
history. The editor preserves a draft when a confirmation fails, but requires a
fresh review before another save.

## Retained state and atomic publication

`state/review/annotations/<subject>/<six-digit revision>.json` contains append-only
`annotation_revision.schema.json` records. Every record includes exact source
bindings and authentic baseline anchors, edited segments and lineage, predecessor
SHA256, request ID, local principal, timestamp, action and optional undo target.
Its content-addressed ID binds every other field. The runtime additionally checks
source identity, reference integrity, anchor containment, contiguous hash chains,
undo contents and bounds which JSON Schema alone cannot express.

`AnnotationProvider.preview` reads evidence without writing. `allowed_paths`
returns exactly the next immutable journal member. `prepare` performs no IO and
returns one PreparedEffect with a history_ref into that immutable write. The
shared ReviewDecisions coordinator owns lifecycle locking, fresh authority/input
comparison, exact preimages, request replay and the single transaction containing
both effect and shared receipt. There is no second annotation receipt publisher
or inverted secondary lock. Annotation actions are `save` and `undo`; automatic
principals are not allowed. Existing Original, Version, representation corrections
and engine output remain untouched.

RepresentationBundleManager public `materialize`, `remove` and `rebuild` acquire
the same lifecycle boundary before reading or changing derived evidence. Their
`_materialize_locked`, `_remove_locked` and `_rebuild_locked` internals are only for
callers which already hold that boundary. Existing profile callers use the public
methods. Removal/rebuild does not remove or rewrite retained human history.

ROOT integration uses `annotation_state_findings(store, deep=…)` to validate
retained chains and Original bindings. A genuinely absent derived result can
coexist with retained history, while corrupt present evidence is a finding.
Shared receipt/history cross-checks must detect missing journal members, including
removed tails. Backup, restore, portable transfer, validation and assurance own
preservation of `state/review`; their integration is separate from this provider.

## Bounds and browser security

The editor contract closes at 1,000 segments, 500,000 text characters, 100
operations per preview, 64 retained revisions per source, 1 MiB source state,
2 MiB journal/JSON evidence, 64 MiB total verified native outputs and 512 MiB
Original bytes. The inventory inspects at most 1,000 source members and reports
incomplete results. These editor bounds do not change existing representation
schema enums or ceilings. A reached limit denies the operation without deleting
history. Browser JSON requests are bounded to 256 KiB.

Local Host/origin checks, session-bound single-use confirmation nonces, bounded
in-memory session capacity and expiry protect the browser activity. No state is
published by nonce creation. All engine/user strings are inserted with textContent,
textarea values or escaped JSON attributes. The fixed external script has a
computed integrity hash authorized by the editor-specific CSP. Only attested PDF
media gets same-origin frame permission; object embedding stays forbidden.

Generated English and Italian labels are product content, not a claim of human
linguistic review. Automatic route/model/security tests are distinct from browser
visual observations, native Windows observations and release qualification.
