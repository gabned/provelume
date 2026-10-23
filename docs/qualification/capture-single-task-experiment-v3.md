# Prospective Capture single-task experiment — scientific contract v3

Status: SCIENTIFIC CONTRACT FROZEN BEFORE OBSERVATION; coordinator review still required before any execution.
This v3 fixes the final source/schema/activity/budget coordinates in addition to the reviewed differential empirical-envelope contract. Earlier v0/v1/v2 remain preserved. This document grants no independent execution or qualification authority.
This is an ignored design artifact only. A and B have normal immutable local commits and the separately documented synthetic construction matrix v3 passed 106 tests with 12 existing skips on each arm and all 26 contract cases. No real model experiment, calibration or CI run has occurred for this design.

## Question and unchanged boundaries

Hypothesis: when an atomic preparation or publication has exactly one task,
running that task synchronously avoids executor lifecycle work while preserving
the same payload, filesystem checks, writes, fsyncs, marker protocol, rollback,
budgets and failure behavior. Whether this improves the relative Capture gate
is a separate question: a common idle/busy speedup can make that gate worse.

A is the original executor path. B is the proposed synchronous path only for
exactly one task; zero/multiple tasks retain their original behavior. The final
diagnostic source must contain no other intervention. All model, sampling,
configuration identity, native limits, priorities, security controls, ordinary
load, thresholds, network observer and 20-minute job timeout remain unchanged.

## Fixed four-job cohort

There is ONE workflow_dispatch run at pinned workflow head C, attempt 1, with
four matrix jobs and four original artifact ZIPs. GitHub run/job head metadata
is C by design. Actual source checkout and report identity are A or B, bound by
the frozen plan, exact checkout proof and matrix slot. The future accepted
operator must bind original run/attempt, full job-list, four direct-job responses
and artifact pages/ZIP IDs+hashes to all four slots before analysis. It must not
compare API workflow head C to source A/B as though they were the same identity.

| Matrix slot | Ordinary treatment | Micro base order |
|---:|---|---|
| 0 | A | ABBA |
| 1 | B | ABBA |
| 2 | B | BAAB |
| 3 | A | BAAB |

The four fixed matrix slots use maximum parallelism two and fail-fast false.
There is no wave barrier; a next slot may start after either running job ends.
Actual runner identities and start/end times are retained. Slot labels do not
claim a global chronological order across independent runners. The primary
controlled contrasts are within each host, with both micro base orders covered
by each ordinary treatment. No fail-fast, cancellation after a PASS, retry or candidate
selection occurs. All four attempts and their raw results must be retained.

Every job first runs the entire ordinary 60-sample qualification workload,
including all S06/S07/S08/classification, cancellation, cleanup and independent
network controls. Preserve the original 28-gate map and unmodified original
report. These are diagnostic observations of the experiment source, not clean
candidate qualification.

## Appended same-host microcohort

After ordinary execution, create two fresh synthetic instances with the same
prespecified public fixture shape. Use the same pinned store/runtime and the
accepted complete `measure_jobs`, not a short inference/readback substitute.
For each instance, first run one unscored deterministic Capture seed using
the base/ordinary arm and the exact public payload used by measured probes.
Record its result separately, excluded from every measured arm and contrast.
This creates the same first-Original/deduplication condition before measurement.
Then run six idle Capture probes and one complete `measure_jobs` invocation (six scored busy Capture probes plus its original governed native
load, cancellation, next-caller, idle-unload and cleanup behavior). Thus each job
has exactly 12 idle and 12 busy experimental probes.

Idle and busy have separate ordinal counters, each assigned the job's base
order repeated three times. Assignment occurs before a logical call begins,
and a failed call consumes its ordinal. Never allocate arms only to successful
or eligible calls. The first six ordinals belong to instance 0; the last six to
instance 1. For ABBA, busy assignment is:

```
instance 0: A-cold B-warm B-cold A-warm A-cold B-warm
instance 1: B-cold A-warm A-cold B-warm B-cold A-warm
```

BAAB reverses A/B. Each arm consequently has six idle, six busy, three cold and
three warm busy probes, and three busy probes in each instance. Across jobs,
each ordinary arm occurs once with each micro base order.

The micro treatment applies only during Capture, is restored in `finally`, and
must not change unrelated in-flight atomic transactions. Record and verify
that boundary. Preserve the original S06 trigger after `_first_received`.
Do not retime Capture to native prefill or describe a loaded worker as active
prefill. Record actual request/PID identities and observed activity; parent phase
fields can remain stale while a callback is blocking.

Fresh micro instances do not reproduce the scored ordinary store's accumulated
cardinality. They are matched mechanism experiments; the complete ordinary runs
provide separate evidence under the real preceding load. This distinction must
appear in every report.

The actual sequence is seed instance 0, six idle probes, complete measure_jobs 0,
then seed instance 1, six idle probes, complete measure_jobs 1. Each instance is
fresh and genuinely has its own governed identity. Preserve actual timestamps
and identities; do not rebind them to manufacture cross-arm byte parity. Record
actual native input/output hashes and token counts by cold/warm-variant
condition. Public source/template/input shape and the planned cold/warm/variant
exposures must match the fixed design. Distinct input hashes due to genuine
authority identities are reported and limit causal claims about concurrent
native work; token-count similarity is never called payload parity. No cell is
dropped or relabelled to manufacture a match. The intervention targets only
Capture, after the original first-message trigger; native phase/activity and
these known identity differences remain explicit in interpretation.

## Measurements and recorder controls

For every ordinary and micro Capture, retain wall, thread CPU and parent process
CPU; original submit/process timings; operation roles/counts/bytes; named
prepare/commit/publish, pool setup/task/wait/join, metadata inventory, JSON,
file/directory fsync and lock spans where available. Task spans need their own
thread CPU so parent waiting is not mistaken for useful task work. Record into
bounded RAM inside spans and write only after measurement.

Read available process/thread stat, schedstat, I/O, faults and context-switch
snapshots outside the accepted Capture timer. Keep timestamps and their own
cost. Record missing counters and short-lived-thread losses explicitly. Keep
native worker activity/request correlation; a stale parent phase is not native
phase proof. No extra privileges or resource limits are granted.

Recorder completeness requires all assigned calls, balanced start/end spans,
correct nesting without double-counting inclusive spans, restored treatment,
matching source/configuration/resource identities, and exact cohort sizes.
Unresolved telemetry errors make the affected attribution UNASSESSABLE, without
changing the original ordinary gate result or deleting any sample.

Prespecify before execution two separate checks:

1. Semantic recorder checks using synthetic/fake clocks and filesystem doubles:
   original exception/return propagation, no I/O inside timing spans, thread and
   treatment restoration, failed-call ordinal consumption, complete fixed-count
   assignment, and explicit partial-telemetry handling. No model is run.
2. Recorder calibration after ordinary execution and before the microcohort:
   exactly 256 paired, fixed no-op recorder patterns, with A/B then B/A order
   alternating by pair. These pattern labels name recipes, not product work:
   pattern A has 16 recorded events and pattern B has 6; neither spawns threads
   nor performs filesystem, model, native or proc work. Preserve all 512 raw
   before/after wall, process CPU, thread CPU, rusage and event-count records.
   Every event attempted must be accounted for; errors, truncation or incomplete
   pairs make metrology NOT_EVALUABLE, never a zero observer cost. The exact
   pattern label lists and recorder API are pinned before execution.

For each clock, let e be each raw pattern outer elapsed time divided by its
actual event count, using all 512 observations. Let r be the recorded clock
resolution. Freeze `l = max(0, min(e)-r)` and `u = max(e)+r`. These are empirical
per-event envelope endpoints, not a universal scheduling/observer bound. No raw
measurement, official gate or original report is changed or corrected.

For a paired four-probe cycle, count actual instrumentation events N for each
Capture boundary. Preserve the counts and their provenance. The differential
observer bias of raw mean(A)-mean(B) has the empirical interval:

```
biasLow  = l*mean(N_A) - u*mean(N_B)
biasHigh = u*mean(N_A) - l*mean(N_B)
empirical effect interval = [rawContrast-biasHigh, rawContrast-biasLow]
```

Do not multiply a worst empty-event cost by every common event twice when the
measured range supports a differential envelope. Do not select favorable
calibration observations, subtract an estimated overhead from official times,
use cProfile/I/O time as recorder cost, or revise this rule after outcomes.
Other wrapper bookkeeping, concurrency and scheduling need explicit limits;
these 512 no-op patterns do not establish their universal worst case.

## Prespecified comparisons

For each complete four-probe ABBA or BAAB cycle, compute mean(A)-mean(B) for
idle and busy separately. A positive value favors B. Every busy cycle contains
one cold and one warm observation per arm. Retain the three cycle contrasts,
all individual measurements, and condition-specific contrasts; do not select
the best cycle or pool different hosts as if they were paired.

### Absolute avoidable-cost verdict

Call the mechanism demonstrated only when every one of the four hosts shows:

- Eligible one-task dispatch removes measured executor administration without
  removing required task work. Compute wall-time union of the specific
  create/submit/future-result/shutdown API spans for each one-task pool, exclude
  overlap with THAT pool's actual task span, then union the remaining intervals
  across pools. Never sum inclusive spans or use an entire pool lifetime that
  can include required parent marker/fsync work. Preserve any cross-pool task
  overlap as a limitation requiring explicit treatment rather than adding time.
- A's measured administration exceeds the empirical recording cost of those
  API/task events, with B's single-task path and unchanged selected filesystem
  calls/outcomes independently confirmed. Reduced pool counts alone are not
  cost proof; direct-branch overhead remains part of the net comparison.
- In idle AND busy conditions, the median of the three paired process-CPU
  contrast intervals has a strictly positive lower endpoint, and raw median
  contrast is positive. Process CPU at submit-through-process includes A's
  executor threads; caller-thread CPU alone can increase when B moves useful
  work inline. This boundary excludes subsequent search and caller bookkeeping.
- Complete Capture wall-time contrast is compatible with no regression within
  the empirical envelope: median upper effect endpoint is nonnegative. Call
  this OBSERVED_COMPATIBILITY, not proven absence of regression.
- Selected durable-operation call counts, roles, bytes and semantic outcomes
  are reconciled across arms and prescribed fixture cardinalities. Distinct
  genuine identity/timestamp hashes are retained, never fabricated as equal.
  Selected wrapped operations are not claimed to be complete kernel I/O.

Report all raw effects, empirical intervals, absolute seconds and percentages,
all cycles and all four hosts. A missing/unsupported component is
NOT_DEMONSTRATED. No arbitrary large millisecond target is introduced.

### Relative gate/headroom verdict, separate from cost proof

For each host/arm, report the raw explicitly diagnostic six-idle/six-busy margin:

```
M(arm) = max(six busy Capture times)
         - min(1, 2 * median(six idle Capture times) + 0.1)
I = M(A) - M(B)                    # positive favors B
```

This does not replace the ordinary evaluator's three-idle/six-busy gate. Propagate
per-row empirical intervals algebraically: for each observed time t and event
count N, its empirical product-time interval is `[t-u*N, t-l*N]`, intersected
with nonnegative durations. If inconsistent, metrology is NOT_EVALUABLE. Max,
median and `min(1, 2*median+0.1)` are monotone. Thus, with busy and idle endpoint
vectors, compute:

```
M_low  = max(busy_low)  - min(1, 2*median(idle_high)+0.1)
M_high = max(busy_high) - min(1, 2*median(idle_low) +0.1)
I_low  = M_A_low  - M_B_high
I_high = M_A_high - M_B_low
```

Preserve raw M/I alongside these empirical intervals. The ONE advancement
criterion is observed compatibility with no material margin regression:
`I_high >= 0` on every host. This is not proven nonregression. Claim observed
headroom benefit only if `I_low > 0` on all four hosts. Report how its magnitude
compares with original excess 0.02200762799997733 seconds as context; it is not
a new CI threshold. Observed busy spread (`max-median`) may be bounded by the
same monotone endpoint method; do not claim reduced population failure rates.

A common idle/busy speedup can worsen M. Absolute avoidable-cost proof and
observed gate/headroom effects remain independent verdicts.

## Decision and time boundaries

Advancement toward a clean B candidate requires ALL of: mechanism/cost proof on
all four hosts; observed margin compatibility `I_high >= 0` on all four hosts;
and both ordinary B jobs with independently replayed 28/28 PASS. This is the
sole frozen decision contract, not sufficient clean qualification. Every original
A and B gate map remains visible, including failures. A non-performance/security
regression, incomplete cohort, deviation from the prescribed public load shape
or observed margin incompatibility beyond the empirical envelope
blocks the corresponding advancement claim. No failed treatment is rerun to
find a favorable result; a subsequent revision needs a new documented reason.

Required metrology coverage includes exact original-row bindings, complete
accepted S06 lifecycle/consumption/binding/reuse/cancellation/cleanup semantics,
actual worker/request/process identity and measured activity, and network trace
coverage through final appended cleanup. A declared MEASURED string or loaded
process alone is insufficient. Unsupported activity/counter coverage remains
explicitly NOT_DEMONSTRATED; no retiming or favorable-cell retry follows.

The existing ordinary workload owns its original deadlines and is never cut
short to make room. Two complete accepted S06 invocations should fit the
remaining budget (historically roughly two minutes), rather than another full
ordinary run. The fixed budget is 1200 seconds per job, 240 seconds for the complete microcohort and 90 seconds reserved for cleanup/upload. The microcohort starts only when at least 330 seconds remain after ordinary execution and calibration, measured from the actual first workflow step; server job-start time is not falsely asserted. If ordinary
execution leaves insufficient time, preserve the completed ordinary evidence
and mark the fixed microcohort incomplete; do not shorten it, choose cells or
extend the job. All four jobs still execute their original attempts.

After any demonstrated acceptable correction, remove temporary recorder and
experiment selection through normal new commits, then qualify the clean exact
head with every applicable unchanged gate. No diagnostic result is reused as
clean qualification. No publication, tag, release or SDK draft operation is in
this plan.


## Frozen identity and observation schemas

The companion JSON is `scripts/capture_cost_v1_plan.json`; the passive analyzer
is `scripts/analyze_capture_single_task_v1.py`. The workflow C is a normal child
of B. C's run/job metadata identifies C; measured checkouts identify exact A/B.
The JSON pins both source commits, trees, atomic source and three method AST
hashes, unchanged ordinary/evaluator/observer/runtime coordinates, helper bytes,
this scientific document, complete slot names and exact artifact member names.
Only independently reviewed operator copies grant trusted analysis authority;
shipping analyzer bytes in C merely preserves their provenance.

Each original ZIP must contain exact names:

- `capture-cost-v1/telemetry.json`
- `s05-real.json`
- `capture-cost-v1/ordinary-before-network.json`
- `capture-cost-v1/append-worker-trace-integrity.json`

All ordinary and appended runtime histories require raw `s05-network.PID`
trace members and exact API SHA/size, whole-ZIP CRC and raw source-checkout proof.
No basename fallback, guessed matrix completion order, inferred job conclusion or
synthesized success is permitted. One complete raw run, attempt 1, all job-list
pages, four direct-job responses and all artifact pages must identify the cohort.
Unexpected attempts, missing artifacts or unresolved endpoint incoherence close
analysis as NOT_DEMONSTRATED. All original endpoint and acquisition metadata stay
available independently from the comparison result.

Telemetry `capture-cost-temporary-telemetry/v1` requires exactly 38 callbacks:
ordinary idle3/S05busy3/S06busy6, unscored seed2, appended idle12/busy12.
`span_event_attempts` must equal retained span count, no recorder errors or
truncation, every span balanced with raw before/after and parent/thread identity.
Actual ordinary public probe rows are independently rebound to the raw report.
All micro callbacks bind selected source SHA and each of the three method ASTs.

Calibration `capture-cost-recorder-calibration/v1` is exactly 256 paired
16/6-event RAM patterns with alternating AB/BA order; all 512 raw records,
attempt counts, clocks, rusage and resolution are mandatory. Pattern A labels:
`pool.create,pool.submit,pool.task,atomic.payload_write_flush_fsync,os.fsync,
pool.future_result_wait,pool.shutdown_join,pool.create,atomic._publish_entries,
os.replace,pool.submit,pool.task,atomic.directory_fsync,os.fsync,
pool.future_result_wait,pool.shutdown_join`. Pattern B labels:
`atomic.payload_write_flush_fsync,os.fsync,atomic._publish_entries,os.replace,
atomic.directory_fsync,os.fsync`. Neither recipe performs Product work.

Selected wrapped operation projection is typed per raw span:
`{span_id,label,kind,role,bytes,observer:false,outcome}`. Labels map as follows:
`os.fsync -> fsync`, `os.replace -> replace`, `os.rename -> rename`,
`atomic.payload_write_flush_fsync -> write_journal_payload`,
`store.atomic_bytes -> store_atomic_bytes`. Roles and known explicit byte counts
are retained. Counts and explicit byte totals must agree across arms separately
for idle and busy; projection must equal raw span recomputation. Coverage means
ALL PATCHED PYTHON os.fsync/replace/rename calls while callback active and explicit
journal/store argument bytes only. Kernel buffered writes, native C I/O and full
kernel-I/O causality are NOT OBSERVED. No such stronger claim is permitted.

Every busy probe binds one actual governed sample and exactly one native call
by fresh-instance pass, PID/start time/request and input/output hashes/tokens;
all 12 unique governed calls are mandatory. Source/model/configuration, exact
within-host CPU topology, two physical cores, memory limit, priority, seccomp,
first-attempt semantics, consumption, bindings/reuse, cancellations, receipts,
next caller and cleanup remain intact. The accepted search-time formula is also
checked against the six recorded idle rows of that fresh pass; the independent
ordinary evaluator keeps its original three-row baseline and all thresholds.

Activity coverage requires process counters and PID/start/request identity for
all 12 probes. Let Q be native CPU accounting tick duration, D its observed
user+system tick delta, O the wall time in the snapshot bracket outside the
actual Capture API boundary. The recorded conservative lower bound is
`max(0,(D-2)*Q-2*O)`, using two tick quantizations and the two permitted CPUs.
Zero is VALID observed data; never exclude, retime or retry it. Cost proof is
scoped to the configured real S06 path. Claim CPU activity within Capture only
for positive bounds, and never infer continuous CPU use or native prefill.
The parent's phase is explicitly only its last observation.

## Independent ordinary replay contract

The operator's JSON is keyed by string ordinal `0`,`1`,`2`,`3`. Each entry has
schema `capture-cost-independent-ordinary-replay/v1`, raw report SHA256, accepted
evaluator SHA256, accepted observer SHA256, actual source commit, original and
independently recomputed 28-gate map, original/recomputed status and a complete
named nonperformance factorization. The analyzer requires exact raw gate-map
agreement and `all_nonperformance_controls_pass:true`; this boolean is operator
output, never a candidate-provided verdict. The operator separately pins its
reviewed source, original inputs and actual isolated execution receipt.

The fixed factorization retains EVERY accepted evaluator predicate except:
(1) the five purely temporal standalone gates cold_load/cold_first/cold_total/
warm_first/warm_total; their complete 3/60 shapes, present finite nonnegative
measurements and all sixty warm `cold:false` identities remain mandatory;
(2) only `capture_seconds <= limit` comparisons within deterministic, S06,
S07 and S08_performance aggregate gates. Every search comparison, complete warm
preparation predicate including its timings, all memory/resource/security,
cancellation/unload including their timings, semantic/accounting/binding/reuse,
quality/abstention/reference/Iudicium and complete network predicate is retained.
Missing/unsupported predicates cannot be true. This never changes an evaluator
or promotes a FAIL report. Both B ordinary maps must still be genuine 28/28 PASS.

All four ordinary runs require the full original 3 cold/60 warm/preparations,
3 idle/3 S05 busy/6 S06 busy/2 S06 cancellation/S07/S08/Iudicium sequences,
final integrity/cleanup and complete independently observed network phases.
Early-aborted or exception-masked FAIL is not a completed load control.

## Frozen decision record

The companion JSON records one advancement conjunction: all four absolute cost
proofs; all four empirical M6 improvement upper endpoints nonnegative; both B
ordinary maps independently 28/28 PASS; complete identities, telemetry, workload,
nonperformance controls and network coverage. These are necessary conditions to
prepare a clean candidate, never qualification. Headroom benefit requires all
four lower endpoints positive; spread benefit is a separate descriptive result.
No universal observer bound, historical-cause claim, population reliability
claim, threshold tolerance, qualification reuse or release permission follows.
