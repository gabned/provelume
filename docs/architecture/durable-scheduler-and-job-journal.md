# Durable scheduler and job journal

`0.8/S01` supplies the first user-controlled scheduling vertical slice published in the `v0.8.0`
Vigilia preview. It schedules safe local validation and derived full-text reindex work.
`0.8/S02` activates the same schema-reserved `source.refresh` kind only for an exact managed folder
Source; see [Durable folder Sources](durable-folder-sources.md). `0.8/S03` activates the closed
maintenance catalogue, incremental reindex and per-item recovery adapters described in
[Maintenance catalogue and reindex recovery](maintenance-catalogue-and-reindex-recovery.md).
`0.8/S04` activates exact Source-scoped reconciliation, durable cursors and lifecycle evidence; see
[Source reconciliation cursors and lifecycle](source-reconciliation-cursors-and-lifecycle.md).

## Storage and authority

Scheduler policies and terminal receipts retain schema 1. Legacy schema-1 jobs remain readable;
Cura cooperative controls and reviewed maintenance plans use strict schema-2 jobs under the same
durable `state/scheduler/`:

```text
state/scheduler/
  policies/policy_<uuid>.json
  jobs/job_<uuid>.json
  receipts/receipt_<job-uuid>.json
```

Policies and jobs are atomically replaceable JSON records. A terminal receipt is write-once and
has the same UUID as its job, so recovery can reconcile the one permitted split commit: a receipt
may be durable before the terminal job update. Deep Instance validation checks filenames, closed
fields, policy/job/receipt identity, attempt history, scope, terminal status and progress bindings.
Unknown or malformed journal entries are findings; reads never repair them.

The scheduler state contains IDs, timestamps, enum values, counts and closed error codes. It does
not contain document text, Source paths, URLs, credentials, provider responses or caller-supplied
idempotency text. A manual idempotency key is hashed with policy identity before persistence.
The random lease token is retained only in the internal durable job record; service, CLI, API and
Browser read views expose worker/timing evidence and `token_present`, never the token itself.

The existing Instance manifest already classifies `state/` as durable and excludes `state/locks/`.
Consequently policies, jobs and receipts participate in verified backup/restore and portable
export/import without an Instance schema migration. The cross-process scheduler mutation lock is
ephemeral, excluded from those archives and automatically released by the operating system after
a process exit.

## Policy contract

Every policy selects exactly one job kind and one scope. All available maintenance kinds require
the current Instance ID. `source.refresh` requires one existing Source ID; execution fails closed
unless that Source has a valid S02 folder contract.

| Control | Closed values and behavior |
| --- | --- |
| State | `disabled`, `enabled`, `paused`; explicit Run now remains an operator action |
| Mode | `manual`, fixed `interval`, or local `calendar` time on selected weekdays |
| Timezone | Explicit IANA name such as `UTC` or `Europe/Rome`, using system data or the public Python-maintained `tzdata` fallback |
| DST | `earliest`, `latest`, `skip`, or bounded `shift_forward` for gaps/folds |
| Quiet window | Optional local start/end; an eligible instant is deferred to the resolved end |
| Jitter | Deterministic policy/revision offset, bounded to 24 hours and monotonic across occurrences |
| Missed run | `skip`, `coalesce`, or `catch_up_one`; never an unbounded backlog |
| Retry | One to eight attempts with capped exponential local backoff |

Intervals are bounded from 60 seconds to one year. Calendar search, DST-gap recovery, missed-run
scan, jitter, retries and leases all have explicit upper bounds. Jitter is a deterministic,
policy-revision offset: it spreads coincident policies without reordering successive occurrence
deadlines. A backward wall-clock change is detected from the last evaluation and recomputes the
next occurrence instead of replaying future work. A forward change, restart, sleep or wake
evaluates the configured missed-run policy and creates at most one job per policy per cycle.

Changing state, schedule or retry policy creates a new policy revision and recomputes its next
occurrence. Job records retain the exact policy revision and retry envelope that created them, so a
later policy edit cannot silently alter already queued work.

## Journal, leases and recovery

A legacy job moves through the closed states `queued`, `running`, `retry_wait`, `succeeded`,
`failed`, `manual_intervention` or `cancelled`. Schema 2 also permits `pausing`, `paused` and
`cancelling` under the cooperative contract below. Only the exclusive lease holder may
heartbeat, checkpoint, succeed or fail a running job. Attempts are consecutive and bounded;
progress counts are non-negative and monotonic across checkpoints.

Checkpoints use consecutive sequence numbers and the phases `prepared`, `executing` and
`committed`. Recovery classifies an expired lease as follows:

| Durable evidence | Recovery action |
| --- | --- |
| No committed effect for a current local executor | `restart_only`; requeue within attempt bound |
| Source refresh executing checkpoint | `resumable`; replay uses its durable Source/run evidence |
| Full/incremental reindex checkpoint | `resumable`; replay validates its candidate or exact active generation |
| Source reconciliation checkpoint | `resumable`; replay reconciles the one-ahead cursor split and revalidates the Source snapshot |
| OCR page checkpoint | `resumable`; replay verifies page-result checksums and continues without publishing or duplicating completed pages |
| Other `committed` checkpoint without a terminal receipt | `manual_intervention`; never infer success |
| Attempt bound exhausted | `manual_intervention` with a closed recovery error |
| Immutable receipt already exists | Reconcile the terminal job from the exact receipt; do not run again |
| Wall clock earlier than the last heartbeat | Expire the stale lease and apply the same bounded recovery rules |

The active worker refreshes its lease while a local operation runs. Search reindex and validation
also take the existing Instance lifecycle lock, so they do not race ingestion, retention,
backup/restore, import or manual web acquisition. Lifecycle contention leaves a queued job
unclaimed and consumes no attempt; a later bounded runtime cycle may claim it safely.

Each terminal receipt states job/policy/scope identity, attempts, completion time, progress,
bounded cumulative attempt duration, terminal status and a closed error class/code. It explicitly
records network use, canonical
mutation and automatic deletion. Both S01 executors report `network_used: false`,
`canonical_mutation: false` and `automatic_deletion: false`. S02 Source refresh reports mounted
network use and canonical Acquisition mutation truthfully; automatic deletion remains false.

## Cura cooperative controls

`SchedulerCoordinator.job_capabilities(job_id)` and `preview_job_control(job_id, action)` are pure
reads. A detail preview validates the bound producer checkpoint; list views instead use the cheap
`scheduler_control.public_control_progress(job)` projection without scanning producers. Reads do
not promote old jobs, create state or acquire a mutation lock. Unsupported running executors expose
no stop controls. The three cooperative kinds are `search.reindex`, `search.reindex.incremental`
and `maintenance.source_reconcile`.

`control_job(job_id, action, expected_revision=..., request_id=..., expected_checkpoint=...)`
requires the exact preview revision; resume/retry/restart may additionally bind its checkpoint.
Only a digest of request identity and payload enters the bounded command history. Repeating the
same request returns its stored command receipt; changed payload under that identity fails closed.
A command receipt proves acceptance of the control request, not terminal success.

| Request | Durable transition and effect |
| --- | --- |
| Pause queued/retry-wait | `paused`, no worker claim; retry eligibility is preserved |
| Pause running | `pausing`; the lease holder acknowledges `paused` after a safe durable boundary |
| Cancel queued/retry-wait/paused | one cancelled terminal receipt; no executor starts |
| Cancel running/pausing | `cancelling`; the lease holder writes the terminal receipt at the boundary |
| Resume paused | same job, `queued`, same validated plan/cursor and remaining attempt budget |
| Safe retry | due `retry_wait` to `queued`, same job; never bypass backoff or attempt bounds |
| Fresh restart | explicit new linked job with a fresh plan/attempt history; a paused parent is cancelled |

The total attempt bound remains at most eight. A pause closes its attempt without an error and a
resume consumes another attempt. An exhausted or changed checkpoint requires an explicit fresh
restart. Missing/corrupt reindex candidates deny explicit resume; an exact one-item-ahead candidate
retains the existing idempotent recovery contract. Source resume revalidates its entire bound
snapshot. Restart never resets the parent's attempts or removes its candidate, history or receipt.
One restart intent stores the immutable child admission record; recovery verifies its terminal
parent receipt and lineage before creating or accepting the child. A further fresh restart belongs
to the child. Immediate cancellation similarly persists intent before its receipt-first terminal
commit, allowing interrupted commands to reconcile without execution.

Each schema-2 job has `execution_plan` (null for legacy admission) and a strict `control` envelope:
schema/revision, bounded commands, pending request, commit barrier, parent/restart intent,
completion intent, network-use observation and one progress sample. History is capped at 128
commands and the envelope at 1 MiB; exhausted capacity denies further commands without pruning
evidence. The validator rejects unbound transitions, invalid units, duplicate command identities,
unsupported fields and contradictory lease/attempt evidence. Schema-1 reads remain byte-preserving;
promotion happens only at an explicit mutation or a cooperative worker claim.

Worker and resume/retry/restart paths hold the Instance lifecycle guard before the existing
`state/locks/scheduler-journal.oslock`. Running pause/cancel requests take only the journal lock so
they can reach a worker that already owns lifecycle. They persist intent and do not mutate its
producer. Reindex acknowledges after SQLite fsync, scheduler checkpoint and durable cursor;
reconciliation also polls between files and hash chunks during discovery. A durable journal commit
barrier precedes index activation or reconciliation publication. Requests arriving after it are
rejected; the worker finishes publication. `CooperativeStop` is a dedicated control exception,
distinct from domain failures. Expired leases honor pending pause/cancel and never silently requeue
the interrupted command. Mounted-network use observed before a stop survives in the final receipt.

Progress states its actual unit (`documents` or `source_items`), completed count, exact plan total,
checkpoint and wait reason. Before discovery establishes a plan, counts and total are unknown.
Rate uses two samples from the same attempt, plan and unit, never paused time; it is absent when
not meaningful. A list cannot treat an unknown denominator as zero or fabricate percentage/ETA.
Capacity admission remains a separate service concern; controls do not invent capacity wait reasons.

## Executable work and runtime boundary

`maintenance.validate` performs deep read-only Instance validation. `search.reindex` and
`search.reindex.incremental` build isolated rebuildable SQLite FTS generations.
`maintenance.library_rebuild`, `maintenance.original_assurance` and
`maintenance.duplicate_scan` reuse their existing local bounded contracts. `source.refresh`
observes one explicit managed folder and ingests only after its S02 quiescence gate. No executor
can repair, purge, apply retention, contact a provider or delete canonical knowledge.
`maintenance.source_reconcile` reads one exact managed Source and canonical provenance, persists
only Source-bound hashes and counts, and performs no ingestion or canonical mutation.
`maintenance.resource_snapshot` reads only local Instance filesystem metadata and capacity,
persists one idempotent aggregate observation per job, and never enforces its warning or critical
thresholds.
`maintenance.backup_verify` verifies one explicitly registered local archive against the immutable
reviewed target and archive digest. Its policy must be manual, and admission requires exact target
parameters and plan revision. The verification service creates no competing job receipt; this
journal owns the terminal result. It never restores, replaces Instance state or chooses a target.
`ocr.execute`, added by `0.9/S02`, executes only a previously persisted exact local OCR request.
Its idempotency binds source and component identity; page checkpoints survive retry or stale lease;
only a complete derived bundle is promoted. It reports no network use or canonical mutation. OCR
configuration and queueing remain explicit through their dedicated local controls rather than a
generic recurring scheduler policy.

An explicit CLI cycle evaluates policies and executes a bounded number of jobs:

```bash
provelume scheduler-policy-create INSTANCE \
  --kind maintenance.validate --state enabled --mode interval \
  --timezone Europe/Rome --interval-seconds 3600 \
  --quiet-start 22:00 --quiet-end 06:00 --missed-run-policy coalesce

provelume scheduler-policy-create INSTANCE \
  --kind search.reindex --state paused --mode calendar \
  --timezone Europe/Rome --calendar-time 03:30 --weekday 0 --weekday 3

provelume scheduler-policy-state INSTANCE POLICY_ID enabled
provelume scheduler-run-now INSTANCE POLICY_ID --idempotency-key operator-request-1
provelume scheduler-run INSTANCE --max-jobs 4
provelume scheduler-policies INSTANCE
provelume scheduler-jobs INSTANCE --limit 100
provelume scheduler-job INSTANCE JOB_ID
provelume scheduler-receipts INSTANCE --limit 100
```

The loopback Knowledge Browser evaluates one bounded job at a time while its qualified application
runtime is active and exposes a read-only EN/IT Scheduler page. The API exposes status, policies,
jobs and receipts through read-only `GET` routes. Policy and execution mutations remain explicit
local service/CLI authority; the unauthenticated loopback API adds no write route.

This is not an always-on system service. Scheduling while the Browser is closed depends on the
later qualified self-hosted and desktop-agent work; S01 does not register a daemon, startup task or
hidden process.

## Deliberate S01–S04 limits

- S02 watching is bounded scheduler polling while a qualified runtime is active; it installs no
  native filesystem-event service, daemon or startup task.
- Backup creation and verification are catalogued but unavailable to the scheduler until an exact
  destination can be bound without persisting a path or granting destination cleanup authority.
- Provider/connector network cursors remain later work; S04 implements only managed filesystem
  Source reconciliation and lifecycle state.
- Resource policies and capacity/statistics evidence are implemented by `0.8/S05` through
  idempotent Instance-scoped snapshots.
- There is no hidden network access, cloud fallback, canonical duplication, automatic repair,
  purge, retention action, destination cleanup or release/version change in this slice.
