# ADR 0032: governed durable AI attempts in the existing scheduler

Status: implementation contract for Custodia S06 (#322, parent #311).
Written before implementation. ADR 0031 candidate and thresholds are unchanged.

## Decision and invariants

Extend SchedulerStore, its OS journal lock, lease token, queue, coordinator and
terminal receipt recovery. Do not introduce a second queue or database. Existing
schema 1/2 jobs remain valid; AI jobs use a closed schema 3 extension. Each explicit
request has one Instance-scoped idempotency key, immutable approved fingerprints,
one job envelope and consecutive attempts. No schedule automatically creates AI jobs.

All admission, control, authorization and result transactions use the existing
cross-process OS lock. Contention refuses work; it is never permission to continue
unlocked. Budget availability is computed from the complete durable AI attempt
inventory while holding that lock. Reservation and claim are one atomic job write.
No independent mutable balance can drift from attempts. Limits include queue size,
job/UTC-day units, monetary units, attempts, total elapsed time and active reservations.

An attempt records RESERVED before any adapter work, then MAY_HAVE_SENT before
entering execution. Authorization uses an independently supplied current host
authority, not the job's snapshots, and the sole S01/S02 validators. All supported
authority changes share the scheduler barrier. The durable MAY_HAVE_SENT commit is
the linearization point: earlier revocations prevent execution; later revocations
cancel future work best-effort and cannot recall already authorized bytes. The
adapter rechecks current authority at its existing pre-send checkpoints too.
This is not a distributed transaction with a provider or arbitrary file editor.

Every writer checks the current lease token and deadline. Lease expiry fences the
old owner; it does not prove termination. An expired RESERVED attempt can release
its reservation because dispatch requires a second owned transaction. An expired
MAY_HAVE_SENT attempt becomes UNCERTAIN, keeps its reservation and occupies a slot
until explicit reconciliation establishes quiescence. It is never automatically
replayed, retried or sent to a fallback. The same rule covers process death.

The existing Instance lifecycle lock covers admission, then is released before AI
inference: context is immutable and no canonical object is changed. Restore instead
fences active AI records conservatively. This keeps capture/search available while
the journal lock still serializes authority/accounting transactions.

Result, measured/accounted consumption and terminal intent commit together in the
job record. The existing immutable terminal receipt is subsequently materialized;
recovery completes that projection without calling an adapter. Repeated completion
callbacks cannot change a committed attempt, charge twice or publish another result.
Private bounded generic execution output is distinct from privacy-safe public job
state and receipts. It confers no synthesis or canonical authority.

## Accounting

Use integer microcurrency units (one million per named currency unit), integer
resource/token reservation units and integer milliseconds. Round positive rational
prices upward; floats, booleans, negative and unbounded values are invalid. A quote
must bind the exact route/configuration, currency, validity interval and a defensible
maximum charge; an estimate alone cannot authorize a monetary hard cap. Missing or
incompatible quotes block paid dispatch. This is a bounded local admission ledger,
not a price catalogue or external billing platform.

Estimates, defensible upper bounds, locally measured usage, provider-reported usage
and UNKNOWN are separate fields. UNKNOWN retains the reservation, never zero.
Local provider monetary cost is zero only for the managed no-provider execution
path; time, tokens and resources remain accounted. Known consumption is never
refunded. Unknown holds survive restart and period change. Provider excess over a
reservation is recorded as real overrun/debt and remains charged after period change.
Retries and ordered fallback use the original job and period envelopes.

## Controls and recovery

AI is off initially. Installing/qualifying/activating a model never enqueues a job
or enables dispatch. A new process has no execution authority until the host
explicitly binds current sources and requests execution. Binding alone does not
enable that new session. Persisted enabled mode cannot create
a grant after restart, and ordinary background scheduler cycles skip AI attempts.
Pause blocks new dispatch; disable also requests active cancellation and revokes queued work. Job cancellation
before execution releases a reservation; after possible execution it requires worker
settlement, otherwise retains uncertainty. Completion versus cancellation is ordered
by the journal lock. Local adapters terminate their workers on cancellation; remote
cancellation cannot retract content or charges.

Only explicitly selected transient pre-send failures can retry, with persisted
backoff and total deadline. A fallback advances exactly one authorized route after
fresh validation and reservation. Policy, deny/local-only, stale consent, missing
model qualification and budget refusals never trigger fallback. No SDK retry loop.

Portable records include accounting and uncertainty but exclude credentials, weights,
runtime installation and cached qualifications. Restore forces AI off, fences active
leases and blocks automatic dispatch; uncertain holds and known consumption survive.
Import to a different Instance is rejected rather than silently rebinding authority.

## Verification obligations

Controlled barriers and real spawned processes test claim/reservation contention,
crash at every durable boundary, fencing, duplicate callbacks and recovery. Tests
also cover quote validity/rounding, controls, revocations, constrained fallback,
portability, no-effect preflight and inherited S01–S05 regressions. A synthetic demo
and separate real Windows/Linux governed candidate runs are required. Qualification
remains NOT_RUN until observed; S05's earlier PASS does not qualify this new boundary.
