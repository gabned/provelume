# Document retention and live-Instance purge

Status: active Unreleased product contract for `0.6/S04` under issue #95. Package and embedded
release identity remain `0.5.1`; this implementation slice does not create a tag or release.

## Distinct actions

Provelume has no generic knowledge `Delete`. Each action states its authority and reversibility:

| Action | Canonical lineage | Default browse/search | Markdown library | Reversible |
| --- | --- | --- | --- | --- |
| Archive | retained | archive filter/search | one primary file under `archive/` | yes |
| Remove from library | retained | unchanged | excluded | yes |
| Recoverable trash | retained | hidden | excluded | yes |
| Permanent purge | selected lineage removed | absent | absent | no |

Archive preserves classification but moves the one primary projection into `archive/`. Remove from
library changes only projection inclusion. Recoverable trash stores the prior active/archive and
library-inclusion state so restoration returns the same Document identity and retained lineage to
that exact state. Repeated non-destructive transitions are idempotent.

None of archive, unarchive, library exclusion/restoration, trash or trash restoration deletes an
Original or any canonical lineage record. Each changed transition writes one deterministic
`knowledge/dispositions/disp_*.json` record, monotonically advances its revision and synchronizes
search and library derived state under the Instance lifecycle lock. An ordinary synchronization
failure restores the previous canonical bytes and derived views or fails visibly if rollback cannot
be verified.

## Visibility and local authority

The effective default for a Document without an explicit disposition record is active and included
in the library. Active, archived, trashed and all-state filters are available through the
application service, read-only API and EN/IT Browser. Trashed Documents are removed from the search
index and generated library and are absent from the default Document list; exact local lookup
remains available so an operator can inspect and restore them.

Mutations are local service/CLI authority. The read-only loopback HTTP API exposes disposition
status but has no generic `DELETE`, retention mutation or purge method. This avoids granting
destructive authority to the unauthenticated local reading surface.

## Permanent-purge authorization

Permanent purge is possible only while a Document remains in recoverable trash:

1. `purge-preview` takes the lifecycle lock and recovers any interrupted purge.
2. Deep Instance validation must succeed.
3. Provelume inventories and hashes exact current live-Instance targets and reports counts, bytes,
   shared Originals retained and known boundary evidence.
4. A random short-lived token is stored only as SHA-256 evidence and bound to the Document,
   disposition revision, canonical fingerprint, impact digest and target-inventory digest.
5. `purge-document` requires that token plus `--acknowledge-boundaries`.
6. Deep validation and the complete binding are recomputed immediately before mutation. Any state
   or impact change makes the preview stale and requires a new one.

The token expires after 15 minutes. A wrong, expired, malformed, target-mismatched or stale token
fails without deletion. The preview itself may include the Document ID and title because it is the
operator-facing impact decision; the durable completion receipt does not.

## Live-Instance target boundary

The target set contains the selected Document, its Versions, Acquisitions, classifications,
disposition and connected retained provenance; its derived artifacts, derived provenance and
document-bundle files; and its content-addressed Original record/bytes only when no other remaining
Version references that Original. Bounded Instance-state files containing the raw Document identity
are included when safely inspectable. A shared Original is explicitly counted and retained.

The impact inventory binds every targeted path to its category, size and SHA-256. Internal paths are
used for the digest but are not copied into the durable privacy receipt. Targets are bounded to
100,000 safe regular files. State files larger than the 16 MiB per-file content-scan limit are
counted and reported as not content-scanned; the receipt therefore does not imply that uninspected
operational content was erased.

Purge is limited to the live Instance. It does not modify configured Source files or managed backup
archives. Managed backup archives are counted as boundary evidence and may retain pre-purge
content. External backups and replicas are not observable. No result claims broader or physical-
media erasure, and the operation uses neither network nor AI capability.

## Transaction and interruption recovery

Before moving a target, Provelume writes a strictly validated pending journal in the Instance's
external lifecycle-control directory. Targets move atomically on the same filesystem into a unique
`state/locks/.purge-stage-*` tree. While the journal is `prepared`, any ordinary failure or process
restart restores staged files in reverse order, rebuilds search/library views and closes the
operation as failed. The live Instance must pass deep validation before the journal can become
`committed`.

After commit, staged bytes are irreversibly removed and derived views are rebuilt. If cleanup is
interrupted, reopening the Instance finishes the committed transaction rather than restoring
purged lineage. Journal schema, IDs, sorted normalized targets, stage location, preview location and
receipt structure are validated fail-closed before recovery; path-tampered evidence is never used
for deletion. Reusing the same valid token after completion returns the existing receipt instead of
repeating the mutation.

## Privacy-minimizing receipt

The durable receipt under `state/retention/purge-receipts/` contains only hashed Document and token
identity, operation/impact identity, removal counts, shared-Original evidence, boundary counts and
the explicit no-network/no-AI declarations. It excludes the raw Document ID, title, target paths and
Source paths. This receipt proves the recorded live-Instance transaction and its stated limits; it
is not proof of erasure from backups, replicas, Source systems or storage media.

## Local interfaces

```text
provelume archive-document INSTANCE DOCUMENT_ID
provelume unarchive-document INSTANCE DOCUMENT_ID
provelume remove-from-library INSTANCE DOCUMENT_ID
provelume restore-to-library INSTANCE DOCUMENT_ID
provelume trash-document INSTANCE DOCUMENT_ID
provelume restore-from-trash INSTANCE DOCUMENT_ID
provelume purge-preview INSTANCE DOCUMENT_ID
provelume purge-document INSTANCE DOCUMENT_ID --confirm TOKEN --acknowledge-boundaries
```

Equivalent `ProvelumeInstance` service methods provide the same boundary. Read-only HTTP surfaces
are `GET /api/v1/documents?disposition=...` and
`GET /api/v1/documents/{document-id}/disposition`.

## Slice boundary

`0.6/S05` now transfers retained dispositions and privacy-bounded purge receipts as manifested
Instance state, while configured Sources, external backups and replicas remain outside the bundle
claim. See [`portable-export-import.md`](portable-export-import.md). These slices introduce no HTTP
mutation authority, autonomous retention rule, connector deletion propagation, cloud erasure,
storage sanitization or release activation.
