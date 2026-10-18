# Knowledge Object proposals and explicit review

S05 #396 extends the existing synthesis receipt, Action Center and registered
domain-review transaction. Its implementation-stage identity was0.13.0/Iudicium.
The separate [0.14.0/Entitas final workstream](../releases/0.14.0.md) aligns current
identity; qualification and actual publication remain separate GitHub gates.

## Preparing a draft

Open an already completed document excerpt, then choose **Prepare draft**. The
existing governed `summary` or `key-points` result supplies attributable selected
text. The local user chooses Entity, Claim, Decision, Task, Outcome, CalendarEvent,
Commitment or Relation and reviews every typed field. Project/Collection creation
continues through its existing hierarchy owner.

This operation starts no inference and selects no new provider. It does not claim
that the model extracted dates, entity types or graph edges. The existing producer
supports its existing English/Italian task templates; the shared review interface
uses all seven shipped UI catalogs. Dates, time zones and Relation endpoints are
explicit user choices. Available source bytes never establish an assertion's truth.

Preparing a draft requires a valid current producer result, actual successful
terminal scheduler job and its immutable AI receipt. The receipt's entire AI
snapshot, including result/accounting fingerprints, must match the validated job.
The base result must still match the recipe/reference body digest. The draft binds
Instance, exact Version/Original, current Document source, representation descriptor,
actual output byte hashes and the producer's source-governance/scope-policy snapshot.
Source, governance, scope-policy and producer changes invalidate the operation;
there is no implicit substitution of today's Version or another result.

The closed, content-addressed `objprop_` record lives under
`state/derived/object-proposals/`. It grants no write permission. It is bounded to
256 KiB and the inventory to 128 saved drafts. Producer job/receipt reads have
the existing review-reader 8 MiB cap. Unknown/duplicate JSON fields,
nonfinite/deep input, linked paths, filename/record mismatches and foreign identities
fail closed. Existing derived-result bounds still apply, including its 1 MiB source
profile. The first Evidence selector covers the whole exact Original; the retained
producer reference separately identifies the selected excerpt ranges. No selected
quotation is invented for canonical Evidence.

## Inspecting, editing and deciding

The new **Object proposals** Action Center queue is a bounded inventory. It offers
a domain-review link and requires a fresh evidence read; it supplies no schema-1
inspection action that could approve canonical facts. Existing Action Center state,
authority rules and inspection receipt bytes are read without a migration or a
default grant. A terminal domain decision removes that draft from the pending
queue, while its retained receipt remains in domain history.

`knowledge_objects` review authority defaults to disabled. The existing explicit
capability workflow can grant `apply` and/or `reject` for named proposals or all
subjects, optionally scoped to canonical Sources. Controlled automatic authority
is forbidden for this domain. Configuring review authority grants neither inference
consent nor provider/device permissions. Disabling AI does not revoke a separately
confirmed manual review grant: an existing valid proposal may still be read and
reviewed without a provider, model call or renewed inference session.
The source-governance and scope-policy snapshots must still match; changing an AI
scope restriction blocks review of the saved draft while leaving disposal available.

The shared `/objects/proposals` forms support inspection, typed edits, preview,
approval, rejection, disposal and retained history in Cura and its explicit
reversible Current backup. There is no raw JSON editor in this flow. Exact local
Host/loopback and Origin checks, closed bounded forms and expiring one-use
server-held plans protect every POST. Identity, origin, Evidence and canonical
timestamps cannot be supplied by model/browser fields. Preview and GET never
recover a pending transaction or claim it committed. A fresh confirmation owns
lifecycle before the producer-journal lock and revalidates source, producer,
independent capability, graph closure and every canonical write preimage.

Relation drafts retain their pinned endpoint revisions. Changing an endpoint
requires an explicit choice or refresh; a stale unchanged endpoint blocks approval.
CalendarEvent uses the existing shipped IANA-zone and explicit-offset validation.
Edited fields are previewed before a distinct explicit final confirmation.

## Atomic application and retained provenance

The registered `ReviewDecisions` coordinator publishes canonical head, immutable
revision, any new Evidence, domain history and the coordinator receipt in one
bounded review transaction. It does not call manual creation and then attempt to
append a receipt. Shared storage graph preparation is IO-free; manual services
retain their existing consent and `manual` origin contract.

Canonical IDs derive from the proposal identity. Approval creates revision 1 with
the coordinator's actual recorded time, not the draft's preparation time. Exact
content-addressed revision paths are independently derived with that same trusted
time, then checked against the provider effect. Extra writes are denied. Replaying
the same committed request returns its existing receipt; a conflicting request or
second terminal decision cannot create another canonical record.

Objects retain `origin.kind: reviewed_proposal` and their exact `proposal_id`.
Relations retain the closed S01 schema without an added origin field: their
immutable first revision is bound by the retained domain receipt. Later manual
object edits may have manual current origin while preserving the reviewed first
revision. Deep Instance validation checks reviewed revision origins against the
matching committed domain history and exact first revision.

Retained domain history lives under `state/review/object-proposals/`. It records
proposal/draft hashes, producer receipt/reference, source identity, actual manual
decision, edited flag, canonical revision reference and coordinator receipt. It
does not retain raw rejected draft text. Rejection writes history and a receipt
without canonical mutation. The existing 10,000-receipt history bound is checked
before adding a new object decision.

## Disposal, recovery and portability

Explicit disposal removes only the derived proposal. It remains available when
AI is off, a source changed, or the base excerpt was removed. Corrupt/foreign/linked
records are preserved and refused. Removing either derived draft does not erase a
canonical record or its authoritative history; removing the upstream excerpt
blocks new canonical review until a new valid proposal is prepared.

Interrupted application remains behind the existing read barrier and registered
lifecycle recovery. No GET repairs or writes an apparent successful receipt.
Canonical objects, exact Evidence, immutable revisions and retained review history
survive backup/restore and both portable derived-state choices. The existing AI
accounting portability rule remains: an AI-bearing bundle can replace the same
Instance, while a foreign Instance import is refused with verified rollback.
No identity rebinding, liability removal or automatic inference restart is added.

Machine tests use synthetic model responses and data. Human Windows/UX/accessibility
tests remain NOT_RUN, linguistic review UNVERIFIED, labels NOT_REVIEWED, real
classifier quality NOT_EVALUATED and automatic classification DENIED. S06 owns
integrated qualification; no release readiness or security verdict follows from
this implementation document.
