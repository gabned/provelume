# Knowledge Objects v1: closed records and migration design

S01 #376 defines the pure contract; S02 #384 adds canonical storage and explicit portable migration.
The pure contract in `core/provelume/knowledge_object_contract.py` defines inert JSON. The storage
backend has no application/review authority; manual services, API/UI and proposal workflows remain
separate ordered slices. Valid syntax, an evidence
digest and a `reviewed_proposal` origin never establish factual truth or permission.

## Identity, revisions and evidence

An object has schema version 1, stable Instance ID and object ID, kind, revision,
previous revision SHA-256, title, aliases, state, typed body, evidence IDs, origin
and creation/update instants. New object IDs are `obj_` plus 32 lowercase hex digits.
Existing `project_` and `collection_` IDs retain their exact identities and kinds;
promotion must never allocate replacement IDs or infer identity from names/paths.
Aliases are display text, unique within an object after NFC/case folding; matching
aliases across objects do not authorize an identity merge. Titles/text are inert,
including HTML-looking text, and must be escaped at the later presentation boundary.

Canonical JSON uses sorted keys, UTF-8, compact separators and no floats. Records
are bounded to 256 KiB, 8192 traversed values, depth 12, 128 references and 32 aliases.
Duplicate JSON keys, invalid controls/surrogates, unsupported fields/types, future
schemas and path/URL-shaped identities fail closed. Diagnostics contain no content.

Revisions are immutable positive integers. Revision 1 has no predecessor; every
successor retains ID, Instance, kind and creation time and binds the complete prior
record digest. New timestamps cannot precede retained history. The later service
must atomically compare the independently read current revision/preimage before
writing; `validate_successor` alone performs no concurrency control or mutation.

Evidence uses a content-bound `evd_` identity and exact Instance, Document, Version,
Original ID/SHA-256. Its selector is either the entire Original or exact
representation/output/anchor IDs plus a quote hash. No live path, provider URL or
GitHub ID supplies canonical identity. A Document's newer Version does not retarget
old evidence. The later resolver must check actual retained source identities,
representation bindings and bytes; the pure validator proves syntax and internal
digest consistency only. Missing/unavailable evidence is reported, never replaced
with a convenient current Version or claimed as verified. Claim records require
evidence; an assertion remains an attributed assertion, not a certified fact.

## Closed types and relations

| Kind | Body | States |
| --- | --- | --- |
| Entity | description | active, retired |
| Claim | statement, nonempty evidence IDs | asserted, disputed, retracted |
| Decision | nonempty rationale | proposed, decided, superseded, retracted |
| Project / Collection | description, preserved hierarchy ID | active, archived |
| Task | description, optional offset-aware due instant | open, in_progress, completed, cancelled |
| Outcome | description | proposed, achieved, abandoned |
| CalendarEvent | description, start/end instants, time-zone name | tentative, confirmed, cancelled |
| Commitment | description, optional offset-aware due instant | open, fulfilled, cancelled |

Calendar instants require explicit offsets and an increasing absolute interval,
including repeated wall times at a DST transition. Time-zone names are inert syntax
in S01; the later service must resolve a supported IANA zone against the bundled
time-zone data and validate its relationship with the selected instants before
canonical application. No all-day recurrence or provider synchronization is claimed.

Relations have independent stable `rel_` IDs and the same revision chain. Their
closed types are `relates_to`, `about`, `supports`, `contradicts`, `depends_on`,
`part_of`, `fulfills`, `scheduled_for`; state is active or retracted. Both endpoints
bind exact object ID, revision and SHA-256. No self edge or unversioned target is
accepted. Later services must resolve both endpoints in the same Instance, enforce
type compatibility (`fulfills` for Task/Outcome/Commitment and `scheduled_for` for
CalendarEvent), and deny dangling/stale revisions and hierarchy dependency cycles.
S01 does not claim graph integrity from isolated record validation.

## Migration and compatibility plan (execution belongs to S02)

Use an explicit new Instance schema boundary for canonical objects, not an invisible
schema-2 extension: old binaries must reject unsupported object-bearing Instances
before writes/export/restore instead of silently dropping new authoritative data.
Schema 1 continues through its existing registered schema-2 transition before the
new forward transition. Read-only validation must never migrate. Qualify the exact
old/current/future schema matrix; there is no in-place downgrade or implicit grant
of permissions/consents.

1. Under the existing lifecycle serialization, deeply preflight the entire source,
   retained state and Originals. Reject malformed/future records, path collisions,
   symlinks/junctions and unknown canonical state before any target change.
2. Create and independently verify a complete same-Instance backup outside the
   Instance. Bind source schema, identity, complete inventory/digests and unchanged
   preimages; any concurrent change invalidates preparation.
3. Stage additive object/evidence/immutable-revision records and the new manifest.
   Promote existing Project/Collection records with their original IDs and preserve
   hierarchy links/classifications. Never duplicate or replace their authority.
   Retain Source/Document/Version/Original/Knowledge bytes and provenance. Preserve
   preference, Cura-primary/explicit-Current-backup selection, language/appearance,
   AI policies, consents, credentials boundaries and permissions.
4. Use the registered bounded atomic writer and existing lifecycle journal; retain
   backup and preimages before publication. Recover or roll back an interrupted
   transaction deterministically. A foreign replacement fails closed; recovery
   cannot overwrite newer data or call an old result PASS.
5. Deeply validate the new complete Instance before success. Retain migration
   receipt, exact before/after schema and inventory, backup digest and actual outcome.
   Repeating the completed transition is idempotent. Restore uses the supported
   staged same-Instance path; reverting source requires explicitly restoring the
   pre-migration backup, with post-backup changes disclosed rather than erased.

New canonical containers and all immutable revisions must be included in backup,
portable export/import and deep validation/fingerprints. Disposable projections,
indexes and proposals remain separate and rebuildable/removable. Portable import
must verify complete bytes/reference closure before target mutation and preserve
the existing derived-state include/rebuild choice. No network/provider, filesystem
mirror, API stabilization, identity-merge or later-release feature enters migration.

## Qualification and review boundary

S01 synthetic tests cover all closed kinds, exact evidence, revision history,
retained Project/Collection IDs, malformed/hostile JSON, bounded traversal, offset
calendar intervals and absence of I/O/execution in pure validation. They establish
no executed migration, canonical service, machine UI journey or human observation.
S02 owns backup, forward migration, interrupted recovery, old-binary refusal and
portable round trips. Later owners separately qualify manual services, permission/
CSRF-protected API/UI, proposal approval/edit/rejection and integrated resource/
security/no-egress/compatibility behavior on the actual merged source.

The S02 continuation for #384 retains merged #385 and its complete qualification history. An
additional same-host access-metadata test on its actual merge found that umask022 changed private
directories0700 to0755 and files0640 to0600. That image is not accepted for S02. The correction binds
native filesystem permission profiles separately from canonical bytes and retains changed/foreign
images instead of automatically repairing their metadata. POSIX ACL and native Windows DACL cases
emit explicit machine observations; an unsupported host filesystem remains unqualified for that
case. See the [same-host migration/recovery boundary](portable-instance.md).

Existing AI receipts and Action Center remain the only proposal/review foundation.
No object/Claim/Relation proposal creates canonical facts automatically. Human
Windows/UX/accessibility/catalog checks and independent labels remain factual
NOT_RUN/UNVERIFIED/NOT_REVIEWED and explicitly nonblocking for this campaign.
Classifier quality remains NOT_EVALUATED and automatic classification DENIED.
All mandatory native, remote, review/thread, binding, fresh preflight, normal merge,
actual-merge and final official publication/readback gates remain required.
