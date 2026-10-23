# Prospective Capture mechanism experiment C2

Status: FROZEN SCIENTIFIC CONTRACT BEFORE C2 OBSERVATIONS. Execution requires
verified exact source/input bindings and completed construction checks. This
document grants no independent dispatch authority. This is a distinct experiment
following the complete C1 result.
Earlier plans, original four job failures and both formal refusals remain intact.

## Reason and scope

C1, workflow head b00525333940baae5bb1698d77f5d865e46c01b0, run 39884284376
attempt 1, completed all four original jobs with actual conclusion failure.
Each job completed its ordinary workload and emitted an original 28-PASS map,
complete telemetry without recorder errors and all 512 calibration patterns.
The appended experiment executed zero cells. Its predeclared guard required
330 seconds remaining; observed remaining seconds were A1 172.3210163116455,
B1 197.10716271400452, B2 180.8599729537964, A2 172.7952265739441.
Entry exit 42, observer exit 0 and appended-trace exit 1 were retained on all
four jobs. The C1 formal analysis remains NOT_DEMONSTRATED and its separate
formal ordinary replay remains REFUSED. C1's both-B-jobs-success condition is
false and cannot be recovered by this experiment.

C2 tests the same prospective hypothesis: a synchronous exactly-one-task path
avoids executor lifecycle cost while preserving required atomic work. Its
controlled measurements run in fresh fixtures in dedicated jobs. The full
preceding ordinary workload is independently preserved and replayed from C1 as
CONTROL_ONLY evidence. C2 does not claim that its fresh measurements followed
that load on the same host, or that they demonstrate headroom after that load.
No claim about the historical cause of PR409's 5.844 seconds or 7ec's slow
Capture follows. A later clean exact candidate must execute and pass every
ordinary qualification and post-merge check anew.

## Fixed cohort and unchanged boundaries

ONE new workflow_dispatch run at immutable C2 workflow head, attempt 1, contains
four jobs and four original ZIPs. Fixed slots are A1, B1, B2, A2. Maximum
parallelism is two, fail-fast is false, and there is no wave barrier. Actual
runner identity and all actual start/end times are retained. Source checkout
A/B and workflow head C2 are different identities and must be bound separately.

| Slot | Checkout/base arm | Micro order |
|---|---|---|
| A1 | A | ABBA |
| B1 | B | ABBA |
| B2 | B | BAAB |
| A2 | A | BAAB |

`cells.ordinary_arm` remains an internal compatibility field naming the
checkout/base arm; it does not imply an ordinary workload in C2. The exact
atomic A/B source hashes and the three selected method AST hashes are unchanged
from C1. A/B/C2 are normal immutable descendants; no history is rewritten.
Only reviewed diagnostic helpers, workflow, plan and passive analysis change.

Job timeout remains 1200 seconds. Native model, runtime lock, sampling, two
physical cores, three-GiB native address-space limit, two-GiB peak-RSS bound,
priority, security controls and every existing evaluator threshold remain
unchanged. The fixed C2 micro allocation is 600 seconds, with 90 seconds reserved for
closure/upload and a 690-second remaining-time admission guard. This is a new
diagnostic-stage allocation inside the same 1200-second job budget. C1 timing
observations give a 104–105-second lower-bound interval inside each original
ordinary S06. Doubling it gives a 209–211-second engineering sizing reference
for two passes, before initial self-tests, seeds, idle probes and unrecorded
outer gaps. This is not an observed or guaranteed duration for future fresh
instances; 240 seconds would be a borderline allocation on that reference. C1 provisioning to recorder start
was 33–36 seconds. These observations support the dedicated allocation but do
not guarantee a universal runtime. Original C1 allocation240/guard330 is unchanged. No ordinary workload is shortened or reclassified.
C2 contains no ordinary report or synthetic substitute for one.

Every host creates TWO genuinely fresh synthetic instances. For each instance:
run one unscored base-arm seed with the constant public Capture bytes; run six
idle probes; run the complete accepted measure_jobs once, including all six
scored native jobs, its refreshes, both cancellations, next caller and cleanup.
The global idle and busy schedules separately repeat the base order three times.
The first six ordinals belong to instance 0 and the last six to instance 1.
Every failed call consumes its assigned ordinal. All 24 measured probes and two
seeds remain visible. Every arm has six idle, six busy, three cold and three warm
busy observations, and three busy observations in each fresh instance.

The original after-first-received trigger remains unchanged. Actual input and
output hashes, token counts, native requests and PID/start identities are
retained. Distinct genuine authority/context identities are not rebound to
manufacture cross-arm payload equality. Parent phase is only the last received
observation. Positive CPU evidence is not prefill or continuous-activity proof;
zero lower bounds remain valid observations without exclusion or retiming.

## Recorder, source and network evidence

Telemetry schema is capture-cost-temporary-micro-telemetry/v1, top mode
MICRO_ONLY_V2, identity regime MICRO_ONLY_WITH_SEPARATE_ORDINARY_CONTROL.
The exact callback inventory is two unscored_seed, twelve appended_idle and
twelve appended_governed_busy. All ordinary callback counts are zero,
ordinary_actual_row_binding is empty and the ordinary report passed to flush
is None. No fake ordinary body is produced. The appended report, raw span,
process-counter, native-call and calibration shapes retain their reviewed C1
interfaces. Missing or unsupported required data produces NOT_DEMONSTRATED.

All 512 paired calibration records, alternating AB/BA order and 16/6-event RAM
recipes, remain mandatory. Every attempted span event must be retained and
balanced; telemetry errors or truncation close attribution. Process CPU includes
A's pool threads, measured from actual Capture submit entry through process
return. Per-thread snapshots have explicit limits for transient threads.

Selected wrapped operation kinds/roles/counts/explicit bytes are recomputed from
raw spans and must agree across arms separately for idle and busy. Coverage is
all patched Python os.fsync/replace/rename calls while a callback is active and
explicit journal/store atomic argument bytes. Kernel buffered writes and native
C I/O are not observed. Semantic outcomes, all fsyncs and marker/rollback checks
are preserved; fewer recorded pools alone do not prove a correction.

Original ZIP member names and artifact/job names are fixed by the companion
JSON and the independently selected workflow. Exact source HEAD/parent/tree,
workflow HEAD/parent, plan SHA, clean after-status, entry/network exit zero and
all source status/head/tree exit zero are required. All four listed and direct
job conclusions must actually be success. No conclusion is synthesized from
steps or log availability. Raw run/attempt/job-list/direct-job/artifact pages
and original ZIP API size/SHA/CRC are bound to every slot.

The independent network analysis reads every raw c2-network.PID trace member,
checks all registered and appended worker PIDs, and applies the unchanged
accepted all-thread network predicate: every recorded socket/connect/sendto/
sendmsg/sendmmsg call must return EPERM. Complete two-pass governed lifecycle,
all twelve native calls, resource/topology identity and final cleanup are
mandatory. A producer's network verdict alone is never trusted.

## Prespecified mathematics and decision

The reviewed C1 mathematical functions are reused unchanged. No threshold or
formula is selected after C2 observations. For each clock, all 512 raw no-op
patterns give per-event costs e, recorded resolution r, and empirical endpoints
l=max(0,min(e)-r), u=max(e)+r. These are empirical recorder observations, not a
universal bound on scheduling or other bookkeeping. Raw official times are
never corrected or replaced.

For each four-probe cycle and idle/busy condition, retain raw mean(A)-mean(B),
actual Capture event counts, differential bias interval
[l*mean(N_A)-u*mean(N_B), u*mean(N_A)-l*mean(N_B)] and the resulting empirical
effect interval. Retain all three cycles and all four hosts.

An avoidable-cost verdict requires on EVERY host, in BOTH idle and busy:
positive raw median parent-process CPU contrast and positive lower endpoint of
the median empirical CPU effect interval; Capture-wall upper effect endpoint
nonnegative (observed compatibility only); positive measured eligible A pool
administration after its empirical recording envelope; no unsupported cross-pool
task overlap; zero eligible B one-task pools; equal selected required-operation
counts/roles/explicit bytes and successful semantic outcomes. Pool administration
is the union of create/submit/future-result/shutdown APIs minus THAT pool's task
overlap, then the union of residuals across pools, never whole pool lifetime.

For each arm compute the explicitly fresh-fixture diagnostic metric
M=max(six busy)-min(1 second,2*median(six idle)+0.1 second), I=M_A-M_B.
Propagate every row's [max(0,t-uN),t-lN] endpoints through monotone max/median/min
exactly as in C1. ALL FOUR hosts must have I_upper>=0 for advancement: this is
observed compatibility with no material regression within the empirical
envelope, not proven nonregression. Headroom benefit requires I_lower>0 on all
four hosts and is scoped only to these fresh fixtures. Busy max-minus-median
spread remains separately reported; no population failure-rate claim follows.

The single C2 preparation condition is: all four cost proofs, all four fresh M6
compatibility checks, all four actual producer jobs success, complete fixed
cohort/source/native/network/security evidence, and the separately pinned
independent C1 full ordinary CONTROL_ONLY dataset. This condition permits
preparing a clean correction candidate; it grants no qualification. All final
clean exact-head native/remote/ordinary gates and normal preflight/merge/post
checks remain mandatory. No publication, tag, release or SDK draft is authorized.

## Separate C1 control dataset

The pinned external bundle schema is capture-cost-C1-ordinary-control/v1,
result FULL_ORDINARY_LOAD_REPLAYED_CONTROL_ONLY, scope
CONTROL_ONLY_NO_CORRECTION_SUPPORT, qualification and correction_support
NOT_GRANTED. It binds C1's actual run/attempt, four actual failure conclusions,
original manifest/plan, accepted210 evaluator/observer and independent execution
receipt. Each slot retains entry42/append1/observer0 and the insufficient-guard
observation. Original and independently recomputed 28-gate maps must match and
all be PASS; full prior-load coverage, nonperformance predicates and independent
network observation must verify. C1 formal REFUSED/NOT_DEMONSTRATED remains
explicit. The bundle's controls cannot replace any final candidate check.

Analyzer exit zero and COMPLETE_FRESH_MECHANISM_COMPARISON mean that all four
comparisons were evaluable. They do not establish a beneficial effect or permit
advancement. The trusted proof adapter must require the explicit
clean_candidate_preparation_supported boolean and each constituent all-four
cost, fresh-margin compatibility and actual-job-success boolean to be true,
with all source/control/network identities verified; exit status alone is
insufficient. A complete negative experiment remains retained as a negative
result and is never rerun to seek a favorable outcome.
