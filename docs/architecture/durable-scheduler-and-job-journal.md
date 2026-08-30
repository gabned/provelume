# Durable scheduler and job journal

`0.8/S01` adds the first user-controlled scheduling vertical slice without changing the published
`0.7.0` package identity. It schedules only safe local validation and derived full-text reindex
work. Source refresh is represented in the closed policy schema so later slices do not need a
second scheduler, but it cannot be enabled or queued until its executor and Source-reconciliation
contract exist.

## Storage and authority

Scheduler state is additive schema-1 durable state under `state/scheduler/`:

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

Every policy selects exactly one job kind and one scope. `maintenance.validate` and
`search.reindex` require the current Instance ID. The reserved `source.refresh` kind requires one
existing Source ID and remains fail-closed in this slice.

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

A job moves through the closed states `queued`, `running`, `retry_wait`, `succeeded`, `failed`,
`manual_intervention` or `cancelled`. Only a worker holding the random exclusive lease token may
heartbeat, checkpoint, succeed or fail a running job. Attempts are consecutive and bounded;
progress counts are non-negative and monotonic across checkpoints.

Checkpoints use consecutive sequence numbers and the phases `prepared`, `executing` and
`committed`. Recovery classifies an expired lease as follows:

| Durable evidence | Recovery action |
| --- | --- |
| No committed effect for a current local executor | `restart_only`; requeue within attempt bound |
| Future Source refresh checkpoint | `resumable`; preserved for its later executor contract |
| `committed` checkpoint without a terminal receipt | `manual_intervention`; never infer success |
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
`canonical_mutation: false` and `automatic_deletion: false`.

## Executable work and runtime boundary

`maintenance.validate` performs deep read-only Instance validation. `search.reindex` atomically
replaces only the rebuildable SQLite FTS generation and its metadata. Neither executor can repair,
purge, apply retention, acquire a Source, contact a provider or delete canonical knowledge.

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

## Deliberate S01 limits

- `source.refresh` cannot be enabled or run; watched folders, mount loss and quiescence belong to
  `0.8/S02`.
- The broader maintenance/reindex catalogue and per-operation checkpoint adapters belong to
  `0.8/S03`.
- Connector cursors, Source reconciliation and lifecycle states belong to `0.8/S04`.
- Resource policies and capacity/statistics evidence belong to `0.8/S05`.
- There is no hidden network access, cloud fallback, canonical duplication, automatic repair,
  purge, retention action, destination cleanup or release/version change in this slice.
