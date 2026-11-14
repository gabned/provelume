# Concordia S10 connector conformance

This is the provider-neutral read boundary for S11–S14. It reuses the canonical
ConnectorDefinition, ConnectorInstance and Source identities; the additive
`calendar_read` / `task_read` vocabulary and calendar/iCalendar/tasks Source kinds
do not rewrite existing definitions or Sources. Existing Gmail/Drive intake is
retained. Registering a capability never qualifies a provider or authorizes a
remote operation.

The application service `productivity_connectors()` exposes explicit local policy
and bounded read previews. `productivity-policy` observes one Source without
network or vault access. `productivity-consent` requires the displayed revision,
explicit confirmation, Source-compatible capabilities and disabled/manual/scheduled
mode. Each immutable revision retains its predecessor digest. Missing, corrupt,
linked or discontinuous policy histories fail closed; GET never repairs them.
There is no shared account cursor or implicit grant to another Source.

Admission binds the actual Instance network policy, canonical definition, identity,
Source and exact consent revision. It is rechecked before and after every page,
including the last. Disabling, removing, changing selection, revoking or changing
network authority invalidates the pending preview. A manual grant cannot schedule
work. A provider requiring external authorization must resolve a credential bound
to the exact identity/capability and independently recheck its external revision
before and after each response. Credentials and credential references are absent
from new canonical records, Source policy, previews, backup and export data. The
resolver is a trusted device-external host seam; no plugin code is loaded from
connector manifests, no plaintext secret fallback is introduced, and no provider
credential is accepted through the new CLI.

`ReadPage` has at most 200 mapped items / 2 MiB, bounded opaque continuation and
terminal checkpoint tokens, and no simultaneous continuation/checkpoint. A read
session has at most 50 pages, 5,000 items, 8 MiB and a 60-second wall deadline;
the concrete transport must also enforce its per-request deadline. Cursor cycles,
duplicates, cancellation, incomplete pagination, unsupported mappings and changed
authority return a closed failure with no partial success or cursor advancement.
Previews never mutate canonical data or persist a new sync checkpoint. Concrete
intake must commit its producer-owned evidence before advancing its own cursor;
a failed preview is never a resync or a completed acquisition.

Task and CalendarEvent projections preserve stable remote identity, exact remote
revision and its meaning (ETag/version/content hash), complete description,
container/parent, assignees, comments and safe durable links. A date-only due value
stays a date; floating instants are refused until an explicit source zone exists.
Offset/zone consistency, DST, all-day spans, recurrence UID/instance provenance and
cancellation tombstones remain distinct. An ETag is not inferred from a content
hash, and a content hash cannot establish a conditional-write capability. Unsupported
or oversized values fail visibly rather than silently truncating remote data.
The existing Entitas manual-object write boundary remains authoritative; this
read contract does not forge a manual object edit or enable task write-back.

[S11](concordia-google-s11.md) adds the concrete attributed read intake, canonical
read-only Entitas projection, exact response Originals and complete-generation
cursor publication. Page continuation and whole-Source completeness are distinct;
the pre-existing S10 preview remains side-effect free.

Qualification uses actual synthetic Core Instances, independent identities and
Source histories with closed deterministic adapters. It exercises mid-response
authority/revision changes, no-network admission, cursor loops, date/DST semantics,
malformed mappings, policy integrity and secret absence. These are automatic
conformance observations only. Real Google/iCalendar/Asana/Tududi qualification,
provider provenance/intake, browser controls and live permissions are separate
S11–S14 gates. S15 owns exact conditional-write capability proof and consent;
completion and due date remain its only writable fields. All final acceptance
dependencies and manual DEFERRED_BY_MAINTAINER / NOT_RUN rows are unchanged.
