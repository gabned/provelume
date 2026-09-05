# Durable folder Sources

`0.8/S02` supplies the bounded filesystem-Source vertical slice published in the `v0.8.0` Vigilia
preview on top of the `0.8/S01` scheduler.

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

## Emendatio enrollment qualification

`0.10.1/S01` adds a read-only validation step to the service, CLI and EN/IT local
Browser. Select an existing local folder, a connected removable volume, a network
volume already mounted by the operating system, or an explicit Windows UNC path
such as `\\server\share\folder` on a Windows-hosted Instance. UNC requires the
`network` class and both server and share. A single regular file remains supported.
URLs, device paths, drive-relative Windows paths, alternate streams, special files
and paths overlapping reserved Instance storage are rejected before enrollment.
Windows selectors on other hosts report the unsupported platform; they are never
silently registered as relative POSIX paths. Filesystem identity also guards an
Instance reached through a different mount or Windows share alias.

```bash
provelume folder-source-validate INSTANCE /path/to/folder --class removable --lang en
```

In the local Browser, **Validate path** / **Verifica percorso** preserves the entered
name, path, class and schedule without creating a Source or policy. Registration
always validates again; a previous successful preview cannot authorize enrollment
after a mount disappears. Invalid schedules likewise fail before canonical writes.
The check opens only the selected directory or regular file to test read access;
it neither recursively scans nor reads document bytes. It has a five-second caller
deadline and at most two read-only filesystem workers per process. A blocked OS
request can outlive that deadline, but cannot later enroll, retry or recover a
Source. Further requests report busy until a slot is released. Browser validation
runs outside the event loop so an unavailable mount does not block other pages.

Closed, path-redacted EN/IT diagnostics distinguish unavailable local paths,
disconnected removable mounts, unreachable network paths, permission denial,
Windows authentication/session failures, invisible mapped drives, unsupported
selectors, reserved storage and timeout/busy checks. Authenticate or mount through
the operating system using the same user/session as Provelume; a mapped drive in
another or elevated session may be invisible. Retry explicitly after correction.
Provelume does not discover shares, collect passwords, change networking or recover
volumes in the background.

The public `identity_fingerprint` is SHA-256 over a versioned domain and the durable
Source ID. It is separate from the observer's content/metadata fingerprints. Opening
the same normalized configured path after reconnect reuses that Source and policy;
restart, reconciliation, backup/restore and portable transfer preserve this identity.
Loss of a mount changes availability and diagnostics, never historical Originals
or canonical records. Read views use stored configuration without probing mounts.
Moving a source to a different configured location is not automatic reassignment
of its identity. The existing transfer contract retains external path configuration
but never packages an external mount or its credentials.

Regressions cover all three classes, rejected selectors, synthetic Windows error
codes/session visibility, resource limits, failed validation without writes, reconnect
and transfer. The permanent Windows matrix additionally exercises an existing local
administrative UNC share, actual file ingestion, disappearance/reappearance and an
Instance alias. That test must succeed on Windows; synthetic cases do not substitute
for its exact-head result. It creates no shares or credentials and changes no LAN
or firewall configuration.

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

If the fingerprint changes while a run is interrupted, recovery first reconciles any already
committed deterministic Acquisitions, closes unread items without reading bytes from the changed
snapshot, and only then permits a new quiesced run to ingest that new snapshot.

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
- the maintenance/reindex catalogue is implemented separately by `0.8/S03`; folder observation
  does not broaden its authority;
- exact filesystem Source reconciliation and lifecycle evidence are implemented separately by
  `0.8/S04`; provider/connector network cursors remain later work;
- `0.8/S05` implements Instance-root resource trends, capacity policies and thresholds without
  scanning this external Source volume;
- no timer authorizes repair, purge, retention deletion, Source cleanup, provider writes, cloud
  fallback or hidden network access.
