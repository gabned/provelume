# Source reconciliation cursors and lifecycle

`0.8/S04` supplies the bounded, read-only reconciliation slice included in the `0.8.0` Vigilia
release candidate. It compares one explicitly selected managed filesystem Source with current
canonical Document, Version, Original and Acquisition evidence. It never ingests, repairs, purges,
deletes or rewrites canonical knowledge. The public tag remains `v0.7.0` until the separate trusted
release workflow completes.

## Exact scope and authority

`maintenance.source_reconcile` requires an exact managed Source ID. Its policy uses the existing
manual, interval or local-calendar schedule with explicit timezone, DST, quiet window,
deterministic jitter, missed-run policy and bounded retry. Policies remain explicitly disabled,
enabled or paused. Source configuration remains independently enabled or paused.

The action may read a configured local, removable or mounted-network filesystem path. It does not
open HTTP, provider, cloud or other network transport and has no fallback. A terminal receipt marks
`network_used: true` when the selected Source is declared mounted-network, while always reporting
`canonical_mutation: false` and `automatic_deletion: false`.

## Classification and privacy

Each supported stable file is compared with the exact current canonical lineage for the same
Source. The closed classifications are:

| Classification | Meaning |
| --- | --- |
| `current` | locator and SHA-256 content match current Version evidence |
| `changed` | the locator exists but content differs |
| `renamed` | an unclaimed canonical digest appears at one new locator |
| `untracked` | observed content has no current canonical match |
| `missing` | current canonical locator is absent from the snapshot |

Rename inference is deterministic and one-to-one. It is evidence for the operator, not a canonical
rename or new Acquisition. Ambiguous equal-content candidates remain bounded and deterministic;
no locator becomes canonical identity.

Persisted plans contain only Source-bound SHA-256 locator identities, content digests, byte counts,
classifications and fingerprints. Configured paths and relative locators remain in process memory
and are never written to the reconciliation journal, scheduler receipt, API or Browser. Document
content and credentials are never journaled.

## Durable state and lifecycle

Schema-versioned records are atomically replaced under durable Instance state:

```text
state/source-reconciliation/
  cursors/src_<uuid>.json
  runs/reconcile_<job-uuid>.json
```

A run binds one scheduler job and Source to its exact configuration, canonical and observed
snapshot fingerprints, plan digest, plan revision, monotonic item cursor, closed classification
counts and cumulative scheduler-progress base. One durable cursor per Source records revision,
last attempt/success, bound job/run revision, lifecycle code, last counts and resync requirement.

The operational states are exactly `active`, `paused`, `missing`, `error`, `superseded` and
`reauthorization_required`. Permission loss requires manual intervention; missing mounts and paused
Sources complete visibly without retry storms; bounded I/O failures use closed local retry;
snapshot changes become `superseded` and replan on the next bounded attempt. No state transition
silently creates a path, Source, Acquisition or Version.

## Lease, checkpoint and replay

The S01 journal supplies exclusive leases, heartbeat, attempt bounds and terminal receipts. For
each planned item S04 commits the scheduler checkpoint before atomically advancing its own cursor.
After a crash in that split, replay permits exactly one scheduler item ahead and advances the run
cursor without recounting work. A completed run is made durable before the Source lifecycle
cursor; replay completes that second split exactly once before producing the scheduler receipt.

Before resuming any scanning run, reconciliation rebuilds the Source and canonical plan. An exact
digest resumes the existing revision. Any changed Source/configuration/canonical snapshot closes
the old revision as superseded and starts one higher revision from current scheduler progress.
Terminal run/cursor bindings are idempotent, so crash, restart, sleep/wake, stale lease and clock
recovery cannot duplicate a classification count or canonical record.

The final snapshot is rebuilt after the last item. If it differs, the attempt fails with the closed
transient `source_reconciliation_superseded` code instead of publishing stale success. Unsafe or
malformed canonical evidence fails closed. No reconciliation error contains an operating-system
path, document content or credential.

## Persistence, validation and surfaces

Reconciliation state is durable `state/`, so verified backup/restore and portable export/import
preserve it without an Instance-schema migration. Deep validation checks strict fields, filenames,
IDs, digests, clocks, counts, plan/cursor/run/job/Source bindings and the explicit no-mutation
claims. It reports corrupt state and performs no repair.

Local controls and reads are:

```bash
provelume maintenance-policy-create INSTANCE maintenance.source_reconcile \
  --source-id SOURCE_ID --state enabled --mode interval --timezone Europe/Rome \
  --interval-seconds 3600
provelume maintenance-run INSTANCE maintenance.source_reconcile \
  --source-id SOURCE_ID --idempotency-key operator-request-1
provelume maintenance-source-cursors INSTANCE
provelume maintenance-source-runs INSTANCE
provelume maintenance-source-run INSTANCE RECONCILIATION_RUN_ID
```

The read-only API exposes `/api/v1/maintenance/source-cursors` and
`/api/v1/maintenance/source-runs` list/detail routes. The loopback EN/IT Maintenance Browser has
the same Source selection and evidence; only a CSRF-protected local form may queue Run now.

## Deliberate limits

- S04 does not add a native filesystem-event service, daemon or hidden background process.
- Provider, connector, HTTP conditional-request and remote authorization cursors remain later work.
- S05 implements durable Instance file/category/trend/capacity statistics, thresholds and resource
  policies without extending reconciliation authority to Source-volume scans.
- Reconciliation does not import untracked files, mutate moved Documents, repair missing state,
  clean destinations, delete derived data or publish a release.
