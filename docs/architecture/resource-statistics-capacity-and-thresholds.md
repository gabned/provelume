# Durable resource statistics, capacity and thresholds

Status: bounded `0.8/S05` implementation tracked by issue [#130](https://github.com/gabned/provelume/issues/130). Package, tag and public release identity remain `0.7.0`.

## Authority and measurement boundary

`maintenance.resource_snapshot` is an Instance-scoped scheduler action. It observes regular files below the already selected Instance root and calls the local filesystem capacity interface for that root. It never reads file content, follows a symbolic link, scans a configured Source outside the Instance, opens a provider transport or performs telemetry.

Each regular directory entry contributes one logical file and its reported `st_size` contributes logical bytes. These values are not deduplicated physical blocks, allocated-block counts or storage reservations. Symlinks and special files are excluded. A concurrent disappearance or directory-shape change is a retryable `resource_statistics_changed` result; unreadable metadata is a bounded local-I/O failure. The explicit file and history bounds fail visibly and are never bypassed by sampling or deletion.

The closed authority-aware categories are:

- `configuration` for the Instance configuration and manifest;
- `canonical_originals` for retained Original representation bytes;
- `canonical_records` for canonical knowledge records;
- `derived_assets` for indexes, the Markdown library and state-derived representations;
- `operational_state` for journals, receipts, settings and other durable operational evidence;
- `managed_inbox` for Instance-local staged Inbox files;
- `other` for remaining regular entries below the Instance root.

Only aggregate counts and bytes leave the in-memory walk. Absolute and relative paths, filenames, extensions, content, digests, user idempotency values and filesystem device identifiers are never written to a snapshot, API response or scheduler receipt.

## Capacity and thresholds

Capacity contains exact `total_bytes`, `used_bytes` and `free_bytes` reported for the filesystem containing the Instance root. `reserved_bytes` preserves any platform-reported gap between total space and user-available used/free space instead of inventing equality. Capacity therefore describes that filesystem, not an exclusive Provelume quota. Logical Instance bytes remain a separate aggregate.

An operator may replace four optional local thresholds through the service or CLI:

- `minimum_free_bytes_warning`;
- `minimum_free_bytes_critical`;
- `maximum_instance_bytes_warning`;
- `maximum_instance_bytes_critical`.

The critical minimum-free value cannot exceed its warning value; the critical maximum-Instance value cannot precede its warning value. Boundaries are inclusive. Evaluation produces only the closed state `ok`, `warning` or `critical` and closed codes copied into the immutable observation. Thresholds do not reserve space, stop ingestion, move data, send a notification or authorize any destructive action.

## Durable history and recovery

One immutable `state/resource-statistics/snapshots/resource_<job>.json` record is bound to one exact scheduler job and Instance. Sequence numbers and `previous_snapshot_id` form a contiguous append-only chain. Every later record stores exact file, logical-byte, free-byte and per-category deltas. `elapsed_seconds` is clamped to zero and `clock_reversed: true` records a backwards wall-clock observation without breaking monotonic sequence.

The snapshot ID is derived from the scheduler job ID. If a process stops after the snapshot write but before the scheduler receipt, retry returns the same validated record and cannot create a second observation. Settings and snapshots participate in deep validation, verified backup, restore and portable export/import. There is no automatic retention, compaction or history cleanup; reaching the explicit safety bound fails visibly for operator review.

Every successful receipt and snapshot states:

```text
network_used: false
canonical_mutation: false
automatic_deletion: false
```

## Deliberate non-goals

This slice does not scan folder Sources or mounted network volumes, inspect document types or content, calculate unique physical storage, enforce quotas, predict exhaustion, notify external systems, delete old observations, clean caches, repair state or implement the later `0.13` knowledge analytics and navigation scope.
