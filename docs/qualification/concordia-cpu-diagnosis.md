# S01 CPU diagnostic comparison

Owner: PR #424, `concordia-s01-readiness`. The original binding remains
`1ba49ad7a9bbaa1639126c078bc59dfecf0dcafc8db38b78ce84a588558ee0a6`.
This experiment does not qualify an application candidate or close a finding.

## Retained observations

The starting ledger is [6395673691](https://github.com/gabned/provelume/pull/424#issuecomment-6395673691).
The Linux original ZIPs were downloaded again, SHA-256/size checked against
GitHub metadata, and every member checked by CRC and SHA-256:

| Finding | Original source | Run / job | Artifact | ZIP SHA-256 |
| --- | --- | --- | --- | --- |
| S06 | `8b3f467aa9e7c059e23f22644786ef0f87582cc3` | 40137003485 / 121000536066 | 12577358195 | `d1ed958bdc80176fdb1b1e41d64e936907a6399e7f4722303bcc5c4162295b44` |
| S08 | `e2c9244df692cdd9dbd636a0109a7d920a21ac1b` | 40168713342 / 121094999221 | 12589573097 | `1eebd581928a5270d3574fcff0bb9584b6dccc3d31640863be4511b29c7d7b9b` |

Both originals report Linux 6.17.0-1022-azure, CPython 3.12.15, four logical CPUs,
and AMD EPYC 9V74. S06 samples 2/3 took 0.558215767/0.556407410 seconds against
0.542394072; S08 sample 810 took 0.430448224 against 0.410888852.
They contain submit/process wall times and mandatory worker/network observations,
but no CPU/scheduler/I/O accounting bound to those failed intervals. The separate
capture profiles later in each report describe different samples.

Prior profiling (`c11523b`), inclusive timing (`fb85b4a`) and accounting
(`ec4d166`) remain nonqualifying. Profiling and accounting report EPYC 7763.
That difference is observed; attributing either original failure to CPU model,
runner interference, storage, or product code is still a hypothesis.
The previous workspace's `.agent/concordia-s01/` and continuation pointer were
absent from this environment; recovered GitHub originals are new local copies,
not a restored operational checkpoint.

## Predeclared experiment

Dispatch the existing `ai-runtime-candidate.yml` on the owner branch with
`concordia_diagnostic=true`. One Linux job runs, sequentially and exactly once:

1. Accepted main `096782e32a3d019c3e160c2569507d55cadfd274`.
2. Original S06 source `8b3f467aa9e7c059e23f22644786ef0f87582cc3`.
3. Original S08 source `e2c9244df692cdd9dbd636a0109a7d920a21ac1b`.
4. The dispatch's exact owner candidate.

Each arm uses the same host, interpreter/dependencies, locked acquired model and
native input, path depth and original complete measurement sequence. Each gets a
fresh process, installed store and synthetic Instance. OS caches are not flushed;
order and environment are retained. This is one controlled block, not a statistical
claim or a reproduction of the original runner. A reverse-order option exists for
a subsequent independently justified comparison, never an automatic retry loop.

The original payload, all samples, evaluator, limits, native worker and network
observer are imported directly from the selected source. The driver adds:

- Probe/call identifiers, realtime/monotonic clocks, PID/TID, process/thread CPU,
  user/system time, faults, context switches and block I/O counters around submit
  and process. Errors retain their original identity.
- A separate 10 ms nominal sampler of every visible parent/worker task, including
  scheduler runtime/runqueue wait, task state, I/O and pressure/cgroup counters.
  Actual sampling duration and sampler CPU are retained; short-lived tasks and
  unavailable counters remain incomplete observations.
- `fsync`/`fdatasync` durations alongside every mandatory network syscall trace.
  The original all-descendant network validator still runs. No document bytes,
  model weights, argv or environment values are added to diagnostics.

The whole probe includes submit/process; their inclusive intervals are not
independent additive measurements. Sampling and tracing perturb execution.
All evaluator outcomes and failed gates survive, but every final report and the
experiment manifest say `DIAGNOSTIC_ONLY`, `qualification_eligible:false`.
Workflow completion means only that evidence collection finished.

Hypotheses to distinguish on an actually failed sample are CPU execution cost,
runqueue delay, blocking/storage time and thread coordination. A long wall interval
alone proves none of them. Match its operation timestamps to task accounting and
durability traces; report unmatched time explicitly. Compare the original evaluator's
unchanged per-arm relative threshold as well as the historical absolute values,
without substituting one for the other. No reproduced failure means no attribution.

A proposed correction needs an isolated mechanism change, original/candidate
comparison under the same conditions, and preserved counterexamples. Instrumented
improvement remains diagnostic. Qualification then requires the unchanged corrected
candidate's native tests, all applicable workflows/attempts/jobs and original
artifacts, complete review and fresh preflight. Previous Windows artifacts remain
historical for any newer source; Windows 11/browser/human rows remain unqualified.
No merge, acceptance, lifecycle activation, SDK change, #377 work or release follows
from this experiment.

## Boundary and observer study (second bounded experiment)

The first experiment's [original ledger](https://github.com/gabned/provelume/pull/424#issuecomment-6398357124)
retains zero S06/S08 threshold exceedances on EPYC 9V45. Its 10 ms nominal sampler
took approximately 20 ms per collection; 31/32 submits lacked two interior
snapshots. Those scheduler deltas are UNKNOWN. Repeating that source comparison
would not address this observation gap.

The resumed cloud workspace reports EPYC 9V74, five logical CPUs and kernel
6.18.55. A positive synthetic contention control confirms advancing runqueue
counters despite its missing scheduler-enable sysctl. Different isolation/kernel
and restricted model origin prevent treating it as the original hosted environment. The model HEAD
request through the required session proxy was denied (403); no alternate origin
or proxy bypass is used. Repository self-hosted runner inventory remains 403;
that establishes an API permission gap, not absence of executable hosts. The
existing GitHub workflow is available and its successful prior runs establish
actual hosted execution. No paid host or dedicated hardware is provisioned.

Explicit dispatch with `concordia_observer_study=true` runs one job, four complete
native sequences, once each, on one generic `ubuntu-24.04` host:

| Order | Immutable source | Observation mode |
| --- | --- | --- |
| 1 | original S06 `8b3f467` | boundary |
| 2 | original S06 `8b3f467` | extended |
| 3 | original S08 `e2c9244` | extended |
| 4 | original S08 `e2c9244` | boundary |

Both modes retain the original payload, all native cases, idle measurements,
evaluators, thresholds, worker containment and mandatory post-exit all-thread
network observer. There is no CPU correction or candidate-effect arm. The
boundary mode keeps `strace -ff -ttt -T -e trace=network`, without the polling
sampler. The extended mode adds the previous sampler and fsync/fdatasync trace.
This AB/BA ordering gives an observer contrast on each original source; one
block cannot exclude time drift or prove a causal effect statistically.

Both modes preopen numeric per-task scheduler and I/O counters outside each
original probe, then read them immediately before/after each submit/process.
The current thread, existing parent tasks, native worker tasks, tracer and (when
present) sampler have PID/TID and role bindings. Each collection has start/end
timestamps and thread CPU cost. Exact process/thread CPU and rusage bracket the
method itself. A Python fsync/fdatasync wrapper records per-call wall/thread CPU,
TID and operation, including commit-pool threads; it records no fd/path/content.
The syscall wall interval excludes the wrapper's thread-CPU clock reads, and
separate wrapper timestamps retain their cost as a measured envelope.
All wrappers preserve return values and exceptions. They perturb measurements;
their boundaries and collection time remain explicit rather than subtracted
from the original evaluator's result.

Before any full sequence, two synthetic CPU loops share one logical CPU. Advancing
runtime and a positive runqueue delta in each child are required;
readable zero counters alone do not pass this control. Failed calibration stops
the experiment with the partial manifest retained. Missing/exited task counters
remain UNKNOWN. Tasks created after a probe's inventory are absent from its
stable-task scheduler deltas; process CPU and durability events still cover
their work. The study neither fabricates counters for the historical FAILs nor
guarantees a new FAIL. There is no automatic retry or reverse-order rerun.

Analyze any new exceedance against its own unchanged idle-derived threshold,
then correlate its operation CPU, current-thread runqueue delta, I/O counters,
durability intervals, tracer/sampler CPU and collection costs. Durability wall
time includes scheduling/tracing; parallel calls overlap. These values cannot be
summed into a causal decomposition. Short-lived task work, other blocking and
unmatched time remain explicit. Report a non-reproduction if no sample exceeds
its own threshold. Observer-related differences remain hypotheses until an
isolated controlled comparison demonstrates their mechanism and effect.

Every final report remains `DIAGNOSTIC_ONLY`, `qualification_eligible:false`,
with original evaluator FAIL/NOT_RUN/PASS preserved. Successful collection cannot
close either finding. Any subsequent product correction still needs an isolated
mechanism and controlled effect, followed by full unchanged-candidate native,
original CI/artifact, review and preflight checks. Windows evidence from earlier
bytes remains historical; mandatory Windows11/browser/human rows remain open.

## SMT capture-placement experiment (26 October 2026)

This is a new scheduling condition, not another observer comparison. Both original
failed reports and all four reports in original artifact `12603958772` expose four
logical CPUs on **two physical cores**; the native worker selects logical CPUs
`[0, 2]`, one from each core. The resumed cloud executor instead exposes five
distinct cores, with no exposed SMT siblings. Restricting that executor to four
cores does not recreate the originals' sharing of physical execution resources.
The previous non-reproductions do not establish a hardware cause.

Hypothesis: capture on the SMT sibling of a continuously active native worker can
lose execution throughput without correspondingly large scheduler runqueue wait.
Capture on the worker's exact logical CPU can instead preempt the worker, whose
existing nice value is at least 10. These are distinguishable scheduling
conditions. Neither is declared to explain the historical failed intervals.

The only varied factor is the capture thread's placement. On a verified two-core,
four-thread host, A uses the worker's first logical CPU and B its SMT sibling.
Every idle and busy probe, including newly submitted capture commit tasks,
inherits the same one-CPU condition within an arm. The original four-CPU mask is
restored on every exit, including exceptions. No process-wide affinity, worker
pair, priority, native configuration, product source or capture payload changes.
Every live worker's actual mask must match the declared pair before a probe;
capture pool tasks must retain the declared one-CPU mask. No extra contention
load, sleeps, cache flushes or threshold adjustments are introduced.

One explicit `concordia_smt_study=true` dispatch runs this fixed block once:

| Order | Immutable source | Capture placement | Observation |
| --- | --- | --- | --- |
| 1 | original S06 `8b3f467` | A: same logical CPU | boundary |
| 2 | original S06 `8b3f467` | B: SMT sibling | boundary |
| 3 | original S08 `e2c9244` | B: SMT sibling | boundary |
| 4 | original S08 `e2c9244` | A: same logical CPU | boundary |

Each arm retains its complete original native sequence, fresh store/Instance,
unchanged path depth, interpreter, dependencies, locked model/libraries, corpus,
evaluator and all post-exit network observations. Both sources retain S06 and S08
probes. The limit remains `min(1, 2 * median(same-arm idle capture) + 0.1)` for the
appropriate original idle group. Historical absolute latency is only a reference.
Fixed AB/BA ordering is one bounded block, not a statistical exclusion of drift.

Both conditions retain the same boundary counters, Python durability wrappers and
mandatory network-only `strace`. There is no polling sampler. Newly created commit
tasks additionally record submit/start timestamps, thread CPU/rusage, scheduler
and I/O counters, TID, inherited affinity and complete wrapper envelopes. Method
boundaries include visible cgroup CPU/I/O/pressure counters. Missing counters stay
UNKNOWN; hidden ancestors and host steal time remain limitations. No arguments,
content, environment or descriptor paths are recorded by the new observers.

Observer cost remains inside the original timing where incurred. Retain each
snapshot's wall/thread-CPU duration, task wrapper pre/post envelopes, queue delay,
affinity application/restoration duration and durability wrapper cost. The earlier
hosted study's boundary snapshot medians were 0.76–0.91 ms; this is historical
context, not a cost assumption or subtraction. The new task observer has no
preclaimed cost. Report its measured distribution and any outlier association.
Overlapping wall intervals and process/thread CPU cannot be added as a causal
decomposition. An observed difference needs its actual task/worker overlap and
counter evidence; no FAIL means no attribution.

Stop before acquiring a model or starting a sequence if the actual inherited
topology lacks exactly two physical cores with two allowed logical CPUs each.
Require the existing positive scheduler-counter calibration. Stop on an affinity
mismatch, operation error, per-arm 20-minute timeout, incomplete collection,
non-capture gate failure or final network observer not PASS. Preserve partial
reports and do not automatically retry on another host or reverse the order.
An evaluator's capture FAIL remains a result to retain, not a collection error.

All reports remain DIAGNOSTIC_ONLY / qualification_eligible:false. This experiment
changes no product behavior and cannot itself close either CURRENT finding.
An isolated correction and controlled effect, then all unchanged-candidate native,
original CI/artifact, review and preflight gates, remain necessary. Older Windows
bytes stay historical; Windows11/browser/human gates remain unqualified. The
PR-local legacy owner/binding and deferred lifecycle v2 remain unchanged.

## Tracer-placement control after observed exceedances

The SMT block completed on EPYC 9V74 / Linux 6.17.0-1022-azure / Python 3.12.15:
[run 40279997821](https://github.com/gabned/provelume/actions/runs/40279997821),
original artifact `12633263958`, 4,662,779 bytes, SHA-256
`924f95de3add69e6c5087c5ff1bd4a52b386ffda2fe009eb0d91b0f2b1c19d96`.
All 2,500 ZIP members were read/CRC/hash checked. Four network observers PASS.
There are new S08 capture exceedances with contemporaneous counters: on original
S06 source, samples 810/811 are 0.524169647/0.640234783 against 0.493994258; on
original S08 source, sibling sample 811 is 0.929333192 against 0.537449150.
No targeted S06 capture exceeds its own limit. These are new executions, not
reconstructed historical intervals or a demonstrated product correction.

The simple hypothesis that the SMT sibling is consistently worse is unsupported.
Observer costs also depend on the condition: boundary snapshot medians are
6.1–6.7 ms; task-wrapper medians approximately 4 ms, with much larger tails in
the same-logical arms. The original-S08 failed sample's submit/process boundary
windows contain approximately 0.319 seconds of tracer runtime. Its Python
durability intervals contain long overlapping waits and little calling-thread
CPU; these include ptrace stops and scheduling. No additive attribution to
storage, CPU execution or observer interference is justified by these counters.

The next hypothesis is narrower: competition between the tracer and capture on
the same logical CPU can delay an observed capture while the worker's existing
nice value does not constrain the tracer. Test that mechanism by varying only
the **tracer** CPU. Keep capture and its new pool tasks on logical CPU 1 (the
worker's SMT sibling), with the unchanged native pair `[0, 2]`. A pins the tracer
to CPU 1; B pins it to CPU 3, the sibling of the other selected native core.
The four original-source sequences run once in S06 A/B, then S08 B/A order.
The tracer's child explicitly restores the original four-CPU mask before any
application import, hardware check or worker creation. Each probe verifies the
actual tracer mask, worker pair, capture mask and pool-task masks. No native
priority, configuration, product code or process-wide foreground mask changes.

An explicit `concordia_tracer_study=true` dispatch first requires actual two-core,
four-thread SMT and the exact reported original EPYC 9V74 CPU model. A mismatch
is CAPABILITY_MISSING, before model acquisition, with the original preflight
retained; do not automatically request another generic runner. The available
generic label cannot promise that CPU model. If admitted, use the same canonical
inputs, interpreter/dependencies, path depth, fresh stores/Instances, complete
native payloads and unchanged original evaluators. Each arm keeps its own idle
denominator and the original relative limit, including the fixed capture mask.

Both modes retain exactly the same mandatory all-thread network-only strace,
boundary/cgroup accounting, pool-task observations and durability wrappers.
Measure their cost again in each arm, including tracer runtime/wait and all
observer envelopes. Pinning and restoring masks occur outside the capture clock;
that timing is not subtracted from any result. No arbitrary instrumentation
deduction or historical absolute threshold is used. One AB/BA block cannot rule
out drift or intermittent storage stalls; a later green alone is not a correction.

The positive scheduler calibration, 20-minute arm bounds, full-sequence checks,
affinity checks, non-capture gates and final network PASS stop conditions remain.
Retain every failed evaluator result. No extra arm, reverse block or retry-to-green
follows automatically. A demonstrated tracer effect would identify an observer
mechanism under these conditions, not by itself qualify a product or close either
CURRENT finding. Product changes still require an isolated mechanism and controlled
effect, then all unchanged-candidate gates and fresh Windows byte identities.

## Portable tracer-placement control (26 October 2026)

The maintainer authorized continuing on the existing hosted Linux capacity,
without requiring them to supply EPYC hardware. This is a **new experiment** on
its observed host. The original EPYC 9V74 admission and control above remain
unchanged and unexecuted after CAPABILITY_MISSING; their requirement is not
silently weakened. Historical failed intervals still cannot be reconstructed.

Hypothesis: a tracer sharing the capture's exact logical CPU can delay capture.
The single varied factor within the block is tracer placement: A shares the
capture CPU, B uses the declared other CPU. Capture and all new commit-pool
tasks stay on one fixed CPU throughout every idle and busy probe. The native
pair is still selected by each original source's unchanged distinct-core rule
and checked against the observed pair at every probe. No native priority,
configuration, product implementation or payload is changed.

The deterministic plan reads the actual inherited mask and package/core IDs:

- If both selected native cores expose another allowed logical CPU, capture uses
  the first worker's sibling and tracer B uses the second worker's sibling.
  With the earlier 0/1, 2/3 topology this is worker 0/2, capture 1, tracer A/B 1/3.
- Otherwise, at least four distinct physical cores are required. Capture uses
  the third core and tracer B the fourth, keeping both off the two worker cores.
  On four distinct CPUs 0/1/2/3 this is worker 0/1, capture 2, tracer A/B 2/3.
- Missing/invalid topology or an unsupported asymmetric layout stops admission.
  A larger inherited mask is retained and reported, never cropped to manufacture
  the reference topology. Neither branch establishes equivalence to EPYC 9V74.

The host report retains actual CPU model(s), kernel, machine, Python, allowed
CPUs and core groups. Linux/x86_64/AVX2, CPython 3.12, strace/taskset and advancing
scheduler counters are required before bootstrap/model acquisition. Focused
native tests, including actual strace separation and restoration before the
first application import, then run before any model is acquired. Original
native hardware/resource admission remains mandatory. A missing capability
stops this host; no automatic dispatch on another host or retry follows.

The four complete native sequences run once: original S06 A/B, original S08 B/A.
Each retains the original full payload, evaluator, idle groups, per-arm relative
limits, all observers, fresh stores/Instances, path depth and locked inputs.
The same interpreter/dependencies and observed host are used for all four.
An original capture FAIL remains a result; a later green or a different idle
denominator does not erase it. No historical absolute threshold is substituted.

Boundary/cgroup accounting, pool-task observations, durability wrappers and the
mandatory post-exit all-thread network observer remain unchanged. Record their
cost distributions again: the earlier 6–7 ms snapshot medians are context, not
a subtraction. Keep overlapping durability/tracer/scheduling intervals distinct;
no additive causal decomposition or arbitrary observer deduction is allowed.
One AB/BA block cannot exclude drift, intermittency or hidden host contention.

The existing affinity checks, positive scheduler control, 20-minute arm bounds,
complete collection, non-capture gates and final network PASS stop conditions
remain. Preserve every partial report and failed evaluator result. No extra arm,
reverse order or automatic repetition follows. A non-reproduction is reported
as such. A demonstrated tracer effect explains an observer mechanism on this
host; it is not a product correction or automatic disposition of either finding.

The connected host currently lacks a manual workflow-dispatch tool. Therefore
the permanent workflow binds this execution to the **single direct descendant**
of owner head `8433e64883c55b7cb5fff20ed8bf8b7795af93b5` on PR #424, the
same-repository owner branch, a synchronize event and run attempt 1. It checks
the exact event head, clean checkout and sole parent before admission. Later
descendants record NOT_RUN; reruns do not execute the study. This is an ordinary
authorized PR update with read-only job permissions, not a new owner or trigger
for publication.

The new command is `run --portable-tracer-study`; the separate
`portable-topology --output PATH` admission preserves an existing receipt.
Every final report remains DIAGNOSTIC_ONLY / qualification_eligible:false.
Both historical findings remain CURRENT until an isolated product mechanism and
controlled correction are demonstrated, followed by all unchanged-candidate
native/CI/original-artifact/review/preflight gates. New source makes earlier
Windows byte-bound evidence historical; Windows11 Home/Pro, browser and human
rows remain open. The original binding, PR-local legacy route and deferred v2
activation remain unchanged; no merge, acceptance, #377 or release follows.

### Pre-execution correction after the first portable admission

The first portable job on source `8433e64`, run `40378966947`, job
`121769679800`, passed actual host admission and positive scheduler calibration.
Ruff then rejected two nested context managers in the new accounting-refusal
test (SIM117). Model acquisition and all four native arms were skipped; no
portable capture experiment ran. Original artifact `12677342032` retains the
two trigger/admission reports, 1,179 bytes, GitHub-recorded SHA-256
`5770480b165fe1d925d4b81d336ce0b4115f6b5770a418f54815e530ed00ad60`.

The correction combines the test's context managers without changing the driver,
native product, payload, observation or stop conditions. The one-execution
parent guard above advances to that failed source's normal direct descendant,
still on attempt 1. This is a corrected pre-execution control, not another
equivalent four-arm study or a retry seeking a different CPU model. Retain the
original failed Ruff/jobs/Windows-coverage results. Existing authority continues;
no rebinding of the original workstream, waiver or CPU correction is claimed.


## Predeclared bounded-digest PRODUCT comparison

This is a new condition following the completed portable tracer control, not a
retry of that control or a search for an EPYC model. PR #424 remains the sole
owner and the original binding/legacy route is unchanged. Both historical CPU
findings remain CURRENT.

The isolated function comparison in this session found that
`_bounded_file_digest` requests a full MiB even when a fresh stat has already
observed a tiny journal file. On local Windows/CPython 3.12.14, the fixed AB/BA
component comparison used sizes 0/51/1024/16384/1048579 bytes, 2000 calls per block
for small files and30 for the large case. Timed blocks had no tracemalloc or
profiling observer; separate one-call memory probes used tracemalloc. For51 bytes,
baseline CPU was0.90625/1.015625 seconds per2000 calls versus0.125/0.125 after the
read bound. Peak traced allocations were1058753 versus10178 bytes. These are
component observations, not application timings, RSS or historical attribution.

Hypothesis: unnecessary large temporary read buffers increase Capture's digest
CPU cost, including under concurrent native prefill. The proposed PRODUCT delta
changes only the digest read bound to
`min(1 MiB, fresh_size - bytes_processed + 1)` and rejects observed growth.
The extra byte still detects growth. Fresh path/type/size/identity observations,
limits, hashes, journal formats, fsyncs, pools, barriers and rollback are retained.
Regressions exercise exact sizes, zero/multi-block files, growth, truncation and
same-size mutation. No metadata observation is cached between operations.

Baseline A is immutable owner source
`967222f71d43de7e518d9c55c80167bf1d886c83`; its atomic module is blob
`1f019e176780c3ae85743b6222ca3941d3fa05d0`. B must be its sole direct child.
Admission checks the exact byte replacement and refuses any other PRODUCT,
dependency, SDK or evaluator change. Only the declared diagnostic/test/workflow
paths may accompany that one PRODUCT change. This comparison uses the current
owner baseline, not the historical S06/S08 commit identities.

One full native block, exactly once: S06 A/B followed by S08 B/A. Each arm runs the
entire unchanged qualification sequence, including both S06 and S08 payloads.
Same host/interpreter/dependencies, canonical whole-hash model and seven libraries,
fresh installed store and synthetic Instance, original evaluator and each arm's
own idle-derived thresholds. No cache flush, threshold adjustment or discarded
warm/cold sample. Both relative gate margins and absolute times are retained.

Use the observed portable topology without emulating or seeking a CPU model.
Native workers stay on the original first two physical-core representatives;
Capture and pool tasks stay on the predeclared portable foreground CPU. The tracer
is fixed on that same logical CPU in all four arms. Thus code is the only varied
factor. Record actual hardware, full allowed mask, effective masks, tracee-mask
restoration before application imports and positive scheduler controls.
An admitted Intel/other host does not qualify the historical EPYC9V74 environment.

The workflow admits source factor/topology/scheduler capabilities before bootstrap
or acquisition, then runs full Ruff and the focused native regressions before the
model. Only a same-repository PR424 synchronize/attempt1 whose source is the single
child of A starts this block. Other descendants/reruns record NOT_RUN. The prior
portable source-parent guard is unchanged and does not replay its completed block.
Use `digest-admission` and `run --bounded-digest-study` for this experiment.

Observers and their limitations remain unchanged: accounting/boundary/pool and
durability wrappers plus mandatory post-exit all-thread network observations.
Observer cost is retained, never subtracted; overlapping intervals are not an
additive causal partition. Native-library fsync beyond the Python wrappers stays
outside boundary-mode durability. Report snapshot/wrapper costs and missing data.

Stop before another arm on timeout (20 minutes/arm,85-minute job), application or
network-observer failure, incomplete collection or a non-capture gate failure.
Retain CPU/capture FAILs and all raw results; no retry-to-green or generic-host
search. Every experimental report remains DIAGNOSTIC_ONLY/qualification_eligible:false.
An improvement or later ordinary green alone does not close the old findings.
A complete correction still requires demonstrated mechanism/effect and unchanged-
candidate native/CI/original-artifact/review/preflight qualification. All prior-head
Windows evidence is historical for B; Home/Pro/browser/human gates remain open.
No merge, acceptance, #377, SDK change, lifecycle v2 activation or release follows.


## Predeclared journal-path PRODUCT comparison (28 October 2026)

Both historical CPU findings remain CURRENT. The bounded-digest study did not
establish an application effect. A subsequent fixed Windows pool comparison also
did not establish a consistent benefit; the four-worker pool is unchanged.

The isolated mechanism here is repeated prefix traversal in _journal_path.
Its existing safe_instance_path resolver resolves both the stage and target,
then _journal_path separately checks each journal component again. A Linux
stdlib component comparison on the existing local WSL host measured sixteen
lstat calls per baseline lookup against two with the existing openat2 no-links
helper. In fixed A/B/B/A blocks of 1000 lookups, process CPU seconds were
0.554/0.737 for A and 0.197/0.215 for B. Counts were collected separately from
timing. These are component observations, not historical CPU attribution.

The proposed PRODUCT delta changes only that journal lookup. For an absolute
stage and a supported Linux kernel, kernel_no_links checks the full lexical
chain with RESOLVE_NO_SYMLINKS/NO_MAGICLINKS. The closed journal reference grammar
and both subsequent per-component link checks are retained. Unsupported hosts,
unsupported kernels and relative stages retain the original resolver. An unsafe
kernel result fails closed and never selects fallback. Every lookup observes
current paths afresh; no metadata, identity or digest result is cached. Hashes,
size/type/identity checks, schemas, durability calls, barriers and pool settings
are unchanged. Regressions cover real leaf/middle/ancestor aliases, replacement
between calls, descriptor cleanup, malformed references and fallback behavior.

A first full Capture/preserve/extract/search component block without AI used
Python 3.12.16, fresh Instances and six probes per arm, A/B/B/A exactly once.
All 24 integrity observations passed, but Capture medians were 78.919/101.497 ms
for A and 110.432/81.508 ms for B: APPLICATION_EFFECT_NOT_DEMONSTRATED. Preserve
these results; no equivalent block is repeated to seek a green.

Hypothesis for the next, distinct condition: the redundant path traversal can
become material during native inference with the mandatory all-thread network
tracer. Baseline A is immutable owner 1ad882478636dbd4e5c7fc676fb0d861224e067e;
B is its sole direct child, with only this PRODUCT replacement, these regressions
and this contract. Before execution verify both trees and unchanged qualifier,
evaluator, dependencies and locked inputs. The source factor is the only varied
factor within one complete A/B/B/A block. Each arm runs the entire unchanged
qualify_ai_runtime.py sequence, including both S06 and S08 payloads, and the
original post-exit ai_runtime_network.py observer/evaluator. Each arm uses its
own original idle-derived limits; retain absolute times and margins as well.

Use the already accessible local WSL host, not a dispatch to search for hardware:
Intel i7-1365U, Linux 6.18.33.2-microsoft-standard-WSL2, CPython 3.12.16, twelve
allowed logical CPUs exposing six core groups. Retain the full inherited mask;
no affinity, scheduling priority, quota or host configuration is changed. Native
worker selection retains the original rule. This does not reproduce or qualify
the historical EPYC environment or the still unexecuted strict 9V74 control.
Hardware/resource admission, positive scheduler and actual strace smoke controls,
focused Linux/Windows tests, full Ruff and pin97 precede model acquisition.
The seven native libraries are fully reverified against the current lock. Acquire
the model only from the canonical pinned origin with inherited proxy/CA and full
size/SHA256 verification. No paid capacity or system package installation.

Use one interpreter/dependency environment and equal-length arm paths, fresh
stores and Instances, identical canonical inputs and no cache flushing. Retain
all cold/warm samples. Only the mandatory network-only strace runs during timings;
there is no boundary sampler, pool wrapper, durability wrapper or profiler in
this block. This newly separated observation condition differs from the earlier
instrumented controls. Strace still intercepts syscalls beyond the selected
printed events and can perturb filesystem scheduling; its cost is not subtracted.
No component timing is added to overlapping application intervals. Count probes
are separate from timing. A single reverse block cannot exclude host drift,
thermal effects, intermittent contention or storage stalls.

Stop subsequent arms on a 20-minute arm timeout (85-minute overall bound),
application error, incomplete collection, network observer other than PASS or
any non-capture gate failure. Preserve capture/performance FAILs and every raw
partial report. No automatic retry, extra arm or equivalent replay follows.
If the complete block does not establish a consistent controlled application
effect and relevant failing reproducer, report CAUSE_NOT_DEMONSTRATED; later
greens and this optimization alone do not close either historical finding.
A demonstrated correction still requires all unchanged-candidate native/CI,
original-artifact, review and legacy-preflight checks. Earlier-head Windows byte
proofs are historical; Windows11 Home/Pro, browser and human gates remain open.
The original binding, sole draft owner and PR-local legacy route remain fixed.
No waiver, SDK change, lifecycle v2 activation, merge, acceptance, #377 or release.
