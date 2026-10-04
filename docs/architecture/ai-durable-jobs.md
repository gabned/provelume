# Custodia S06: durable governed AI execution

Parent #311, slice #322. [ADR 0032](../adr/0032-durable-ai-jobs.md) defines the
pre-implementation decision. This extends the existing scheduler and S01–S05;
it introduces no second resolver, queue, canonical object or external billing service.

## Entry and current authority

`ProvelumeInstance.bind_ai_execution(current=..., adapters=..., quotes=...)` is an
internal trusted-host seam. Construction/binding performs no dispatch, discovery,
credential lookup, model load or download. `ai_jobs.configure(mode="enabled",
budget=...)`, an explicit `enqueue(request_ref, request_key=..., budget=...)`, and
`run_ai_job(job_id)` are separate actions. Static adapter/model diagnostics say
`governed_job_required`; they never grant inference. No HTTP/UI registration or
synthesis action is added. AI starts off. Each new manager session needs explicit
enablement even if a previous process persisted enabled mode. An ordinary scheduler
background cycle does not dispatch AI jobs.

The host's `current(ref, route)` reads current authoritative Version, association
inventory, every applicable scope rule, consent, preview/redaction, template,
profile/configuration, capability and independent locality evidence. The callback
is a trusted application dependency, never read from job data or model output.
S01/S02 rebuild and revalidate the original binding; a changed approved plan cannot
expand an existing job. ModelStore additionally verifies current registry/revocation,
installation, exact bytes, configuration and fresh session-bound self-test at use.
The qualification helper from S05 is not the product dispatcher.

Supported host policy mutations use `change_authority`, sharing the scheduler's OS
journal lock with authorization. Durable `possible` is the authorization linearization
point. A prior change prevents dispatch; a later change revokes future work and is
checked by existing transport checkpoints, but cannot retract bytes or external costs.
This is not an atomic transaction with arbitrary external policy editors or providers.
Fingerprints bind evidence; neither a hash, localhost nor a local label proves locality.

Each cancellation poll still reads that authoritative callback, current control and
the owned durable job under the journal lock. Only the pure preparation of an
unchanged complete `CallInputs` value is reused within that attempt. The comparison
baseline is a private deep copy, so changing a nested host dictionary in place is
detected. No saved job fingerprint or object identity establishes freshness. Route
types remain strict (Python's `False == 0` cannot reuse a prepared route). Dispatch
checkpoints and completion always prepare afresh; the snapshot dies with the attempt.

## Records and transitions

Schema-1/2 scheduler jobs stay readable. New AI jobs use schema 3 and kind `ai.execute`.
Producer-owned policies remain disabled/manual; ordinary policy creation cannot enable
automatic AI production. One atomic job record contains the lease, consecutive attempts,
approved binding/request, allowed ordered route fingerprints, fixed deadline, job budget,
reservation/usage facts, control intent and bounded private generic result. The UUID and
Instance-scoped hashed idempotency key remain stable. Duplicate enqueue cannot replace
binding/budget. No prompt, credential, endpoint or Original is persisted in the request.

| Boundary | Durable facts and crash recovery |
| --- | --- |
| Enqueue | Explicit queued job, no reservation or execution authority |
| Claim | Existing cross-process journal lock checks available budget; reservation and lease commit together |
| Authorization | Current inputs, current caps, quote validity, ownership and deadline rechecked |
| Possible execution | `possible` commits before adapter entry; loss of worker or ambiguous callback retains liability |
| Result/accounting | One atomic write stores consumption, result fingerprint and terminal intent |
| Receipt | Existing write-once terminal projection; restart finishes a missing projection without an adapter |

An expired `reserved` lease can release because execution still needs an owned
authorization transaction. Expired `possible` becomes `manual_intervention`/`uncertain`;
it keeps both reservation and concurrency slot until explicit quiescence evidence.
The stale token cannot write another attempt. Duplicate terminal callbacks cannot
replace output, accounting or receipt. Exactly-once remote execution/billing is not
claimed. Crashes are tested with real `os._exit` subprocesses at seven boundaries,
including receipt persistence before the terminal job projection.

The lifecycle lock covers every short mutation before the journal lock, not the
whole inference. This prevents enqueue/control/settlement writes being lost to a
concurrent staged directory swap. Immutable bounded context
and the journal barrier let deterministic capture/search continue. A concurrent restore
forces off and fences the live job as uncertain; it does not assume its worker stopped.

## Budget arithmetic and uncertainty

Resource reservation units conservatively use effective maximum input bytes plus
maximum output tokens, consistent with S02's byte/token proxy. They are admission
units, not a tokenizer or monetary guarantee. Native completed operations report
actual tokenizer input/output counts; interrupted counts remain UNKNOWN and held.
Elapsed milliseconds are separately recorded. Native provider monetary cost is zero,
while time/resources remain nonzero. S03 wire usage stays UNKNOWN because that
profile does not qualify provider-reported counts; explicit adapter/statement facts
can distinguish LOCAL and PROVIDER evidence.

Budgets bound each job, UTC calendar day, attempts, queue and active reservations.
All arithmetic is integer, at most 2^53−1 per supplied amount. Money uses micro-units
of one explicit three-letter currency. `ceil_price` rounds upward. A quote persists
its estimate (optional), defensible maximum, covering units, currency, exact route,
validity interval and evidence fingerprint. Missing/unreliable/incompatible/expired
prices prevent dispatch under a monetary hard cap. No remote catalogue is fetched.
Quotes and tightened current caps are checked again after reservation before dispatch.

UNKNOWN is never zero: held amounts survive restart, date changes, fallback and retry.
Unknown monetary liability also blocks later monetary hard-cap admission. Reported
consumption above a reservation is recorded as an overrun; excess remains debt in
later periods. The application controls admission, not a provider's pricing behavior.
Reservations live in attempts, so there is no second balance to release twice.
Known usage cannot be refunded by reconciliation; duplicate evidence is idempotent
and a changed payload under the same evidence fingerprint is refused.

## Cancellation, pause and bounded continuation

Queued cancellation creates one terminal receipt without an attempt. Pause blocks
claim and preserves retry backoff. Global pause prevents new dispatch but permits
already authorized work to settle; disable persists revocation before requesting
active cancellation. Completion/cancellation order is serialized by the journal.
If cancellation wins, a late result is discarded while known usage remains charged.

The local adapter confirms runtime worker/descendant termination before releasing
the slot. Unmeasured resource usage stays held. External cancellation is best-effort;
after possible transmission an uncertain result neither refunds nor replays. Retry
is limited to declared transient pre-send DNS/connection/rate-limit failures; the
same job's attempt bound, total deadline and persisted exponential backoff apply.
No adapter/SDK retry loop is added. Fallback advances exactly one explicitly allowed
route and repeats current validation and reservation. Deny, local-only, revocation,
missing consent, exhausted budget or ambiguous send never triggers fallback.

`reconcile` requires explicit quiescence, acknowledgement of duplicate execution/cost
risk and a privacy-safe evidence fingerprint. It appends facts without requeueing or
rewriting the terminal receipt. New numeric facts require an explicit LOCAL or
PROVIDER provenance, retained in each evidence entry; quiescence alone cannot turn
UNKNOWN into zero. A new explicit request for an uncertain reference
requires its own recorded risk acknowledgement and retains the previous liability.

## Operations, privacy and portability

Existing Operations control previews/revisions/idempotent command history expose
pause/cancel/resume and due retry. Public AI state includes block reason, routes,
attempts, reservation, usage source, uncertainty and actual actions. Private result
bytes are removed from public job projections. Schema-2 terminal receipts add only
request/binding/result/accounting fingerprints and outcome; their accounting hash
identifies the initial terminal snapshot. Later reconciliation remains append-only
evidence in the job. Generic untrusted output grants no synthesis/canonical authority.

`state/scheduler/ai-control.json` is a validated, Instance-bound schema-1 control
record. No Instance manifest migration is needed: the existing state allowlist
already carries scheduler records. Backup/export include liabilities and private
bounded results; model weights, caches, native installations, self-test grants and
credentials remain outside portable data. Restore/import use the existing staged
transaction, force off, cancel waiting jobs, mark active attempts uncertain and retain
newer destination accounting instead of erasing post-snapshot debt. Different-Instance
replacement with AI accounting is refused. Metadata never reinstalls/requalifies a model.

## Development and qualification

Use Python 3.12 and the canonical bootstrap only when needed. Run
`python scripts/demonstrate_ai_jobs.py` from the activated native environment. It
prints all scenarios and writes `.agent/s06-synthetic-demo.xml`; real spawned-process
barriers and fault injection test contention/crash recovery, not sequential mocks.
No private data, model, credential or external provider is needed.

`python scripts/profile_ai_job_polling.py` compares five alternating pairs of 200
synthetic polls with and without pure preparation reuse, retaining every sample.
Run it alone, without concurrent test/build processes. Both paths assert a fresh
authoritative read for every poll, the same successful job and a single receipt.
It reports wall and thread CPU time; it is not a real-model latency qualification.

`scripts/qualify_ai_runtime.py` preserves every S05 sample and frozen ADR 0031 gate
and adds `qualify_ai_jobs.measure_jobs`: three cold and three warm governed generic
executions, actual token usage, load/generation cancellation, next caller and nine
durable receipts. The existing Windows/Linux workflow observes all worker PIDs from
the complete run. WFP is applied and verified only by the existing disposable CI
controller; bare local Windows stays BLOCKED. Linux requires observed seccomp controls.
The S06 boundary is measured separately; the old S05 PASS is not inherited. These
generic executions are not an S08 synthesis-quality qualification. Recommended is S09.

Native reports separate adapter preparation, verified model admission, final
revalidation and runtime; worker tokenization/reset, prefill wall/process CPU and
generation; polling count/wall/thread CPU; and deterministic capture submit/process.
These are numeric phase observations only. Existing end-to-end timing still includes
all admission/persistence overhead and every sample remains subject to ADR 0031.
The model, payload, byte-substitution checks, two-thread configuration, isolation,
single supervisor deadline and thresholds are unchanged by this instrumentation.

All full native Ruff/pytest, inherited S01–S05/SSRF/lifecycle regressions, exact-head CI,
Protocol policy/ownership/review gates and actual-main checks remain mandatory. Logs
preserve failures. No timeout, DPAPI, ACL, sandbox or fixed threshold is weakened.
