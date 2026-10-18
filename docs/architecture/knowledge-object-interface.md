# Local manual object interface

S04 [#390](https://github.com/gabned/provelume/issues/390) exposes the accepted
[manual services](knowledge-object-services.md) through a local browser boundary.
The Knowledge objects entry belongs to Knowledge in both Cura and Current. The
same forms and services serve both interfaces; changing the existing interface
preference remains explicit and reversible. There is no provider connection,
automatic assertion, classification permission or AI proposal activation.

## Personal journey

1. Open a document and its version history. **Create an object from this version**
   selects that exact retained Version, including an older one. Alternatively use
   **Choose an exact source version** in the object form, select a document and
   then a Version. The compact chooser displays 50 recent documents and the
   selected document's 20 newest versions; the existing document history and
   exact-Version API remain available for other retained versions.
2. Choose Entity, Claim, Decision, Task, Outcome, Calendar event or Commitment.
   Fill the typed fields and explicitly select any sources. A Claim requires a
   source. Aliases are one per line. Confirm this single operation before saving.
   Project/Collection creation, names and parents retain the existing hierarchy
   commands (`hierarchy-create`, `hierarchy-rename`, `hierarchy-move`); existing
   Project/Collection object metadata can be inspected and edited here without
   replacing their identities or bypassing that authority.
3. Inspect the object, its evidence availability and immutable history. Historical
   revisions are read only. **Edit current revision** always opens a fresh current
   head; a form opened before another edit cannot overwrite that edit.
4. Relations select exact source and target object revisions. A later object edit
   makes an endpoint historical. Keeping the same endpoint selection preserves
   the existing reference; advancing it requires the explicit refresh checkbox.
   Retraction can preserve historical endpoints and unavailable attribution.
5. After a document changes, retained evidence still identifies the old Version
   and Original. After explicit purge or missing/corrupted bytes, availability
   becomes unavailable; reading never derives a replacement or retargets evidence.
   A pure withdrawal can retain that attribution. Other substantive edits still
   require available evidence. Availability never verifies an assertion's truth.

Browser forms attach whole Originals. The existing closed text-page evidence
contract remains accepted by the underlying service and API; the form does not
guess excerpts, anchors or media coordinates. Exact Original delivery is an inert
attachment, independently bounded to **25 MiB** and rehashed over the bytes actually
returned. Larger Originals can remain attributable under the service's separate
512 MiB resolution budget; this delivery limit does not change availability or
portable export. No active HTML or media rendering is added by this download.

Task and Commitment due dates are optional explicit-offset instants. Calendar
events require two explicit-offset instants and a matching shipped IANA zone.
For example, `2026-10-18T09:00:00+02:00` with `Europe/Rome`. There is no implicit
local offset, all-day event, recurrence or external calendar synchronization.

## Local HTTP preview contract

This is a minimal first-party preview API, not a stabilized integration/MCP
contract. Every endpoint requires the existing trusted local Host and loopback
browser client. Existing filesystem/user permissions remain authoritative. There
is no bearer credential, persisted browser grant, mobile-device grant or CORS
expansion. The HTTP service remains bound to loopback by the existing host policy.

Prefix: `/api/v1/knowledge-objects`. Use `relation=true` for Relation operations.

| Method/path | Behavior |
| --- | --- |
| `GET /` | Head summaries, `limit=1..100`, optional `after` identity cursor; history is explicitly unchecked |
| `GET /{id}` | Verified current history, fresh evidence availability and current/historical Relation endpoints |
| `GET /{id}/history` | Immutable records, `offset=0..1024`, `limit=1..100`; bounded complete chain verified first |
| `GET /evidence?version_id=ver_…` | Prepare an inert whole-Original Evidence record without saving it |
| `GET /authorization[?identity=…]` | A ten-minute, one-use operation/Instance/current-preimage envelope |
| `POST /` | Explicit manual creation |
| `POST /{id}` | Explicit current-preimage update |

There is no delete endpoint. Read operations do not repair state or write grants.
Only successful object form HTML uses `Referrer-Policy: same-origin`, so native
browser POST navigation retains its same-Origin header. It still discloses no
referrer to external origins. Other responses retain `no-referrer`; `Origin: null`
is refused and cannot substitute for a local browser confirmation.
The shared browser history renders 20 revisions per page; selecting one follows
its exact immutable revision. Both catalogs and service return availability
separately from `truth: NOT_VERIFIED`.

Both POST operations require exact same Origin and an `application/json` object
containing exactly `nonce`, `request_id`, `instance_id`, `expected_sha256`,
`confirmed` and `data`. Copy the four envelope strings from a fresh authorization
response. `confirmed` must be the literal JSON `true`, not a truthy string/number.
Creation authorization uses preimage `ABSENT`; updates bind the actual current
SHA-256. The memory-only envelope is bound to object/Relation and its identity,
is consumed once, and cannot survive expiry/restart or become a saved permission.
The expected Instance identity is checked again inside the lifecycle write lock.

Object creation `data` has exactly `kind`, `title`, `body`, `state`, `aliases` and
`evidence` (a list of full validated Evidence records). Relation creation has
exactly `relation_type`, `source`, `target`, `evidence`; each endpoint is the
existing `{id, revision, sha256}` reference. Updates have exactly `changes` and
`evidence`; the accepted S03 mutable field whitelist and all graph/history/source
validators still apply. Clients cannot choose canonical identity, revision,
timestamps, origin, Instance or proposal authority.

Input is streamed with a 256 KiB cap. Duplicate JSON keys, nonfinite constants,
unsupported/extra fields and excessive nesting fail closed. HTML forms use the
same byte cap, bounded field count, exact scalar fields and per-operation nonce;
they normalize browser CRLF text back to LF before comparing against the reviewed
record. Only fields actually changed are submitted to the service, preserving the
pure-withdrawal exception without rewriting unchanged text or evidence.
Existing valid multiline titles, bodies and alias boundaries survive unchanged
when another field is edited. Textareas preserve their first newline as well as
trailing whitespace; browser CRLF is normalized back to the canonical LF form.
An unchanged alias display retains its original entries, including embedded
newlines; explicitly edited alias text uses the documented one-alias-per-line
entry profile. No identity merging or automatic alias normalization is performed.

Authority/Origin errors return 403, expired/replayed/stale plans and preimages
409, missing records 404, unsupported media 415 and resource limits 413. Other
invalid input returns 400; integrity/schema/storage failures return redacted
503 responses. A failed/expired form requires inspecting the current record and
opening a fresh form; there is no blind retry or automatic merge of changes.

## Qualification boundaries

Synthetic HTTP/browser journeys exercise confirmation, Host/Origin/loopback,
nonce subject/expiry/replay, conflict handling, closed/hostile input, exact older
Original delivery, evidence disappearance, withdrawal, endpoint staleness and
explicit refresh, hierarchy authority and typed calendar instants.
The Linux CI job inherits its bounded 15-minute execution budget from the accepted
separate [Protocol owner #395](https://github.com/gabned/provelume/pull/395), main
`2a299bbf2485198e00dc640fb31e42ed9332406d`. It includes dependency setup and the complete
expanded suite; the original ten-minute cancellation at 98% is retained. The Product
delta carries no CI workflow change. Every test and independent product
responsiveness/resource limit remains intact, as do the Windows group/report and
native Protocol workspace settings.
The shared
pages use escaped text, labeled controls, native links/buttons, semantic history,
existing themes/reflow, skip links and both existing base layouts. All seven
catalogs retain `linguistic_review: UNVERIFIED`; automatic catalog checks do not
claim human linguistic, screen-reader, visual or Windows desktop acceptance.

No preference, consent, permission, Original or existing canonical identity is
rewritten merely by visiting these pages. Existing explicit library/index rebuild
and portable include/rebuild choices continue to govern export/import. Actual
human observations remain NOT_RUN/UNVERIFIED and labels NOT_REVIEWED where no
review was performed. Real classifier quality remains NOT_EVALUATED and automatic
classification remains DENIED. Receipt-bound reviewed proposals belong to S05.
