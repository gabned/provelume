# Durable folder Sources

`0.8/S02` adds a bounded filesystem-Source vertical slice on top of the `0.8/S01` scheduler. It is
unreleased work and does not change the published `0.7.0` package, tag or release identity.

## Explicit authority and scope

A managed folder Source names exactly one configured filesystem path and declares its class as
`local`, `removable` or `network`. The network class means a path already mounted by the operating
system; Provelume does not discover shares, negotiate SMB/NFS, obtain credentials or open a second
transport. Registering a Source creates one exact-scope `source.refresh` policy. Its schedule uses
the existing manual, interval or calendar contract, including explicit timezone, DST, quiet
window, jitter and missed-run policy.

The Source lifecycle is independently `enabled` or `paused`. Pause updates both the Source and its
linked policy. A missing removable or network mount is observable state, not authority to recreate
the mount, remove the Source or delete any Acquisition, Original, Document, Version or provenance
record.

## Durable observation state

Configuration remains additive under Instance schema 2:

```text
provelume.yml
  sources/<source-id>/folder

state/folder-sources/
  observers/<source-id>.json
```

The strict schema-1 observer stores Source/job/run IDs, lifecycle and availability enums,
timestamps, SHA-256 pending/ingested/last-attempted metadata fingerprints, file/byte counts,
stable-observation and clock-change counters, and closed error codes. It never stores configured
paths, file locators, document bytes, extracted text, credentials or caller idempotency text. Deep
Instance validation rejects unknown fields, malformed identities, lifecycle divergence and
observers not bound to a current managed Source.

Observation enumerates only supported regular files inside the configured root. Resolved symlink
escapes fail closed. The fingerprint binds sorted relative locator, size and nanosecond mtime rows;
only the digest and aggregate counts persist. A new fingerprint enters `quiescing`. It becomes
`ready` only after both the configured elapsed window and stable-observation count pass. A backward
clock change resets the quiescence clock and increments durable clock-change evidence rather than
making a negative elapsed interval eligible.

The closed availability/phase combination distinguishes available, missing and attention from
`unobserved`, `paused`, `quiescing`, `ready`, `refreshing` and `current`. Reappearance after mount
loss goes through the same fingerprint/quiescence gate. Periodic scheduler evaluation is the
portable watch baseline; no native OS watcher, daemon or startup task is installed by this slice.

## Refresh, idempotence and recovery

Only a `ready` snapshot can ingest. One deterministic ingestion run is derived from Source ID,
durable change sequence and fingerprint. Its item and Acquisition IDs are deterministic within
that run. If a process exits after canonical Acquisition commit but before the item checkpoint,
replay detects that exact deterministic Acquisition and reconstructs the item checkpoint without
re-reading bytes, changing its timestamp/outcome or creating another event. The active run remains
recoverable across temporary mount loss. A terminal successful run can likewise be reconciled into
observer state without re-reading canonical bytes.

A terminal failed or partially failed run is not mistaken for a successful replay. A bounded
scheduler retry creates a linked durable retry run containing only failed/interrupted items; its
item and Acquisition identities are deterministic for that attempt, and its checkpoint is itself
crash-resumable. Job progress remains monotonic across attempts, preserving earlier error evidence
when a later attempt succeeds.

After ingestion, the Source is observed again. If the fingerprint changed while files were read,
the captured work remains attributable but the Source returns to quiescence and must converge on a
later refresh. An unchanged, successfully completed snapshot becomes `current`; repeated manual or
scheduled jobs skip it without a new Acquisition, Version or Original. Per-item failures produce a
closed scheduler failure and never weaken file, count or byte limits.

Scheduler lease, heartbeat, checkpoint, bounded retry and immutable receipt behavior remains the
S01 contract. A folder receipt truthfully records mounted-network use, whether that attempt wrote
canonical Acquisition evidence and `automatic_deletion: false`. Sleep/wake and forward clock jumps
use the policy's bounded missed-run behavior; restart and stale leases use the same resumable job
and ingestion ledger evidence.

## Local controls and read surfaces

```bash
provelume folder-source-register INSTANCE /path/to/folder \
  --name "Research" --class removable --state enabled \
  --quiescence-seconds 10 --stable-observations 2 \
  --mode interval --timezone Europe/Rome --interval-seconds 300

provelume folder-sources INSTANCE
provelume folder-source INSTANCE SOURCE_ID
provelume folder-source-observe INSTANCE SOURCE_ID
provelume folder-source-state INSTANCE SOURCE_ID paused
provelume folder-source-refresh INSTANCE SOURCE_ID --idempotency-key operator-1
```

The CLI displays the local configured path because it is an explicit local operator surface. The
read-only API and non-local Browser view redact it. The loopback `/sources` EN/IT page exposes
registration, observation, enable/pause and queue-refresh controls with a per-process CSRF token;
it does not create a write API.

Observer state, linked scheduler state and deterministic ingestion ledgers are durable `state/`
artifacts. They participate in verified backup/restore and portable export/import; transient lock
files remain excluded. External working folders are never copied into an Instance archive, and an
archive therefore makes no preservation claim about unacquired Source files.

## Deliberate S02 limits

- native filesystem-event adapters, include/exclude patterns and rename reconciliation remain
  later bounded work;
- the broader maintenance/reindex catalogue belongs to `0.8/S03`;
- connector cursors and full Source lifecycle reconciliation belong to `0.8/S04`;
- resource trends, capacity policies and thresholds belong to `0.8/S05`;
- no timer authorizes repair, purge, retention deletion, Source cleanup, provider writes, cloud
  fallback or hidden network access.
