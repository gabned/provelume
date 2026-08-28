# Rebuild coordination, locking and 0.5 integration

Status: active product contract for `0.5/S05` under issue #66. The installed package and
published preview remain `0.4.1`; this slice completes implementation evidence but does not prepare,
tag or publish `0.5.0`.

## Exclusive derived-state lock

Coordinated rebuilds use one Instance-local lock named `derived-rebuild` under:

```text
state/locks/derived-rebuild.json
```

Acquisition uses exclusive file creation and stores a schema version, random ownership token,
purpose and acquisition timestamp. A competing process fails visibly and does not infer that a
lock is stale. Release succeeds only when the on-disk token still belongs to the current lease.
Inspection is read-only, exposes neither token nor physical path, and does not create the lock
directory.

The lock protects the combined bundle, full-text index, duplicate-evidence and deterministic
Markdown-library rebuild boundary. It is not a general scheduler, lease service or distributed
lock.

## Rebuild modes

`provelume rebuild-derived INSTANCE --mode incremental` validates every current document bundle,
reconstructs only missing or invalid bundles, rebuilds the index when missing/out-of-date or when a
current extracted-text artifact is absent, refreshes duplicate evidence and atomically regenerates
the Markdown library.

`--mode full` recomputes every current document bundle from the preserved Original, rebuilds the
full-text index, refreshes duplicate evidence and regenerates the complete Markdown library.
Existing byte-identical deterministic bundle
outputs may remain at their content-addressed path; invalid bundle directories are discarded only
from rebuildable derived state before reconstruction.

`--mode agreement` runs incremental and full passes under the same lock, records normalized
snapshots after each pass and requires their fingerprints to agree. Snapshot components cover:

- canonical knowledge fingerprint;
- current Document/DocumentVersion/content identities;
- validated bundle output fingerprints;
- current derived-artifact identities and checksums;
- normalized index metadata without build time;
- current exact/probable duplicate identities, rules and document membership.
- validated library canonical/content fingerprints, primary paths and file counts.

The canonical fingerprint is captured before and after every mode. Any change fails the rebuild;
reports explicitly state `canonical_mutation: none`.

## Validation and recovery

Bundle validation checks the artifact manifest, generator/version/document/source-hash identities,
manifest checksum, Markdown checksum and size, page-map checksum and structure, and every bounded
asset checksum and size. All references must remain below the expected version-addressed bundle
root. Invalid derived bundle state can be deleted and rebuilt; Originals and canonical JSON are
never repaired or removed by this workflow.

Index reconstruction uses the existing deterministic extracted-text recovery from preserved
Originals. Duplicate scans keep `automatic_action: none`; they update explainable cases but do not
merge Documents or remove occurrences.

## Navigable evidence

Every coordinated attempt creates one `rebuild.derived` operation in the navigable operation log.
Its timeline includes lock acquisition, bundle recovery, child bundle operations, index commit,
duplicate refresh, library commit and optional incremental/full agreement. Reports are retained
under:

```text
state/rebuild/reports/rebuild_<uuid>.json
```

Local mutation and read commands are:

```text
provelume rebuild-derived INSTANCE --mode incremental|full|agreement
provelume rebuild-reports INSTANCE
provelume rebuild-report INSTANCE REBUILD_ID
provelume rebuild-lock INSTANCE
provelume library-rebuild INSTANCE
provelume library-status INSTANCE
```

Read-only API and browser surfaces are:

```text
GET /api/v1/rebuild
GET /api/v1/rebuild/lock
GET /api/v1/rebuild/reports
GET /api/v1/rebuild/reports/{rebuild_id}
/rebuild
/rebuild/{rebuild_id}
```

HTTP exposes no rebuild, lock-acquire, repair or delete method. Empty reads create no rebuild or
lock state.

## Bounds and failure behavior

Document count is bounded per attempt; the bundle builder and duplicate scanner retain their
existing page, asset, text, pair, case and warning limits. A structural limit, lock contention,
Original verification failure, bundle failure, duplicate-scan failure or canonical-fingerprint
change closes the operation as failed and releases an owned lock. No successful report is committed
for an incomplete attempt.

## 0.5 implementation boundary

Together, the five slices provide:

1. durable ingestion runs and crash-safe retry;
2. safe local Drop Inbox and navigable operation log;
3. deterministic Markdown/page-map/asset document bundles;
4. exact/probable duplicate evidence and read-only Original assurance;
5. locked incremental/full rebuild coordination and agreement evidence.

Release preparation remains separate. It must align package/build identity, changelog, tag,
installer metadata and publication only after the merged implementation baseline is reconciled.
