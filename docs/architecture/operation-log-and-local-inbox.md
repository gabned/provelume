# Operation log and local Drop Inbox

Status: active product contract for `0.5/S02` under issue #66. The installed package and
published preview remain `0.4.1` until a separate release-preparation change.

## Navigable operation log

Provelume records high-level product operations under:

```text
state/operations/records/op_<uuid>.json
```

Each schema-versioned record contains one operation type, title, start/completion time, terminal
status, bounded summary, related record identities, integer metrics, an optional bounded error and
an ordered timeline of events. Events contain a timestamp, severity, stable code, bounded message
and scalar details. The ledger stores no credential and its public surfaces do not return configured
absolute Source paths.

Operation attempts are never reused. A new attempt receives a new identifier and may relate to a
previous run, submission, document or future parent operation. Records are updated atomically while
an operation is running and become immutable through the application contract after they close.
Invalid or truncated records do not prevent the rest of the log from being listed.

The log is available through local CLI, read-only API and the built-in browser:

```text
provelume operations INSTANCE
provelume operation INSTANCE OPERATION_ID
GET /api/v1/operations
GET /api/v1/operations/{operation_id}
/operations
/operations/{operation_id}
```

Filters are bounded by operation type, status and result limit. The HTTP surface exposes no start,
retry, edit or delete method.

`0.7/S02` reuses this ledger for every connector definition, instance and Source configuration
mutation. Those records contain only the operation kind, stable connector/Source IDs, changed field
names, closed outcome and integer preservation metrics. They omit provider/account values,
endpoint origins, external credential-reference names, physical paths and secret material.
Disable/remove evidence records zero Original deletions and overwrites; removal itself is a
canonical tombstone, not a purge.

## Local Drop Inbox

Every Instance owns these portable paths:

```text
inbox/drop/
inbox/items/
inbox/submissions/
```

`inbox/items/` is registered as one stable filesystem Source named `Local Inbox`. Submission paths
are normalized beneath a random submission identity, so files with the same external name do not
overwrite one another.

The default submission mode is copy. For every supported file Provelume:

1. resolves and bounds the submitted tree without following a symlink outside its root;
2. hashes the external file, copies it to the Instance, then verifies that the source remained
   unchanged and that the staged copy has the same SHA-256;
3. runs the durable ingestion ledger against the Instance-owned copy;
4. verifies that the exact content-addressed Original is committed;
5. records the submission and operation timeline;
6. refreshes only the derived search index.

`move_after_commit` is an explicit local option. It removes an external source file only after the
above commit and verification steps, and only when a final re-hash proves the external bytes did
not change. Extraction failure, oversize input, unreadable input, copy instability, a changed
source or any uncommitted outcome leaves the external file in place. The Instance-owned staged
copy and committed Original are not deleted by this workflow.

Files placed manually in `inbox/drop/` are processed with move-after-commit semantics:

```text
provelume inbox-process INSTANCE
```

Explicit files or directories use:

```text
provelume inbox-submit INSTANCE SOURCE
provelume inbox-submit INSTANCE SOURCE --move-after-commit
provelume inbox-status INSTANCE
```

Unsupported files are not acquired or removed. Routine Inbox processing performs no network
request and does not add a background watcher or scheduler in this slice.

## Submission evidence

Submission summaries under `inbox/submissions/` relate the Inbox operation, ingestion run and
stable Inbox Source. Per-item evidence includes only the normalized Inbox locator, state, bounded
error, SHA-256, Acquisition identity and whether the external source was removed. Absolute external
paths are not persisted or exposed.

The read-only surfaces are:

```text
GET /api/v1/inbox
GET /api/v1/inbox/submissions
GET /api/v1/inbox/submissions/{submission_id}
/inbox
```

## Explicit exclusions

This slice does not add a filesystem watcher, periodic scheduler, network Source, AI routing,
probable-duplicate decision, destructive Original cleanup, Instance schema migration, package
version change, tag or release publication. Document bundles, duplicate assurance and
incremental/full rebuild integration remain later `0.5` slices.
