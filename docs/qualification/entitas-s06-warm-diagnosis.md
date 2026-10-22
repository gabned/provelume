# Entitas S06 warm latency investigation

This temporary diagnostic continuation belongs to the existing
`entitas-final-release` workstream, final owner #402 / original PR #403, on
`product/0.14-final-release`. It descends normally from accepted main
`cba9ff6c653bb53327ba397edf980099af90472a`, which retains that original owner
and the accepted #407 correction history. It does not change the PROTOCOL PR #409.

The failing original is #409 source
`ea4b6e07b2d9b0a283d1d8a29d5edcec64dfa8bb`, run `39799577294`, attempt 1,
Windows job `119896122376`, artifact `12434899752`. The complete original ZIP
has SHA256 `c871a45c83baf3bba1ab6166dc6f7aab0deed99c8eedcafcd257096a499d81ad`;
the final report has SHA256
`2654a96fe8799c2acc12ce1adfa9821c4642a732b97a2f6f448c0f218ccfd100`.
It remains 27/28, with `s06_governed=FAIL` and network PASS.

The third warm first-output predicate is 5.843999999999937 seconds against
the unchanged 5-second bound. Native prefill contributes 4.514999999999986
seconds (6.5625 process CPU seconds), model admission 1.2339999999999236
seconds. The earlier warm prefills are 2.1720000000000255 and
1.8279999999999745 seconds; all three reuse 170 tokens, with 112, 107 and
113 remaining input tokens. These measurements localize the variation but do
not establish its historical cause. Scheduler contention, frequency, native
batch behavior and model verification must not be asserted as proven causes.

This continuation adds per-decode wall/CPU observations and retains the exact
synthetic governed requests in the existing observer report. It preserves the
three cold/warm pairs, admission, model, context, affinity, priority, native
configuration, corpus, network controls and every evaluator predicate. No
inference is retried or discarded. All instrumented results are DIAGNOSTIC /
NOT_ACCEPTED, including any green workflow or report. They cannot replace the
failed original or qualify #409. There is no runtime correction proposed yet.

The existing permanent CPU workflow is the execution location. Its first new
attempt supplies Windows evidence without rerunning the failed #409 candidate.
After the fixed diagnostic cohort, examine every batch and its exact synthetic
input before selecting any correction. A correction, diagnostic cleanup and
fresh ordinary source/main qualification remain separate requirements. No
publication signal, tag, release or upload is part of this investigation.

## Fixed-input discriminating experiment

The first diagnostic cohort on `988ece22d933773eb1f3c23a0e875dc6d8e1f66e`
did not reproduce the slowdown. Its Windows runner was AMD Family 25 Model 1,
whereas the original was Model 17. Its fresh synthetic IDs also changed token
counts. Those green results do not diagnose or qualify the failed source.

The next experiment fixes the exact public synthetic requests from artifact
`12447590254`, final report SHA256
`63ed46d8a26b445c5e5a1db3af621ef1c0ed46d6c6f2623637a4becd14e80c80`.
It executes the same three cold/warm pairs in two predetermined cycles A/B:
twelve measured calls and six real self-tests, without retries, dropped samples
or a stop-on-success condition. Errors retain every remaining cell as NOT_RUN.
The ordinary S05/S06/S07/S08/classification workflow remains unchanged and runs
separately; this short native replay does not measure governed dispatch,
reservation, policy polling or durable completion and cannot replace any gate.

Per-batch observations retain wall/process CPU duration, raw process cycles,
user/kernel time, page faults, memory and I/O counters, with explicit PID binding
and unavailable states. System counters describe only the guest; they do not
prove hypervisor steal time. Cycle counts are never converted into MHz or
assumed to prove frequency. Exact source, model, configuration, fixture and
request hashes bind the experiment. The existing disposable WFP control and
calibration surround every real self-test, call and cleanup; its separate audit
never fabricates missing S05 phases.

Code inspection finds one complete GGUF hash in a warm admission, not two.
The separate DLL inventory checks precede and follow that hash. Removing either
check or caching the model hash would require a new independently verified
lifetime proof and would conflict with the complete verification retained in
ADR 0052. No such correction is proposed here.

## Prospective governed native-wait experiment

The fixed replay on `50d93da70c1b9e98fcd8052ad292ae1f3fda6dce` did not
establish a correction. The next experiment tests a new, specific mechanism:
the exact pinned Windows LLVM OpenMP library exports `kmp_get_blocktime` and
`kmp_set_blocktime`. Its workers can consume CPU while waiting after a completed
parallel region. Such observed CPU would be avoidable cost independently of the
historical first-output failure; this experiment does not claim its old cause.

Before execution, fix four complete blocks in order A1/B1/B2/A2. Each block
contains all three governed cold/warm pairs, for 24 measured calls and twelve
real self-tests, with the existing cancellation/next-caller checks afterward.
A uses the observed native default; B sets zero blocktime and verifies readback.
Every request restores and verifies the prior value. An already-zero default is
an ineffective intervention and cannot support a correction. Thread count, the
same two physical cores, process affinity, below-normal priority, model, hash,
memory budget, authority checkpoints and every ordinary gate stay unchanged.

Run the complete ordinary S05 preceding workload once before the shared ABBA
sequence: three cold/busy runs, all sixty corpus cases, cancellation, idle unload
and worker-error observations. The blocks share that preceding load and then
accumulate their own governed load; this is not four independent repetitions of
the full preceding workload. Fix and save all six exact governed payload bytes
and hashes before the first block, using the same actual synthetic Instance.
Every cell checks those hashes; the four blocks must agree on each input,
result fingerprint and input/reuse/output token counts. No payload override
bypasses governed validation. Save every completed cell and keep the entire
predetermined plan, including any NOT_RUN cells after an error. Do not retry or
stop after a PASS. The existing twelve-minute job budget remains fixed.

After each measured native request, observe one explicitly planned 300 ms sleep
window before returning its result. Retain process CPU/cycles/user/kernel,
memory/fault/I/O and own-thread identity/counters at both ends. There is no
requested inference, hash or busy loop in that window. The callback after native
nodes always returns false, preserves graph fusion, and records bounded top-16
wall/thread-CPU intervals and callback overhead during prefill. These intervals
include synchronization and cannot name an opcode or distinguish arithmetic
from spin by themselves. Own-thread accounting does not establish scheduler
ready/wait state; no such state is inferred. The unchanged ordinary observer
runs separately without either intervention or extra idle windows.

Predeclared support criteria, evaluated over the entire cohort: baseline idle
CPU totals at least 0.6 seconds; B totals at most 25% of A; both B block totals
are at most 25% of each A block; exact input/result/token parity; B warm-first
median and prefill maximum each at most 110% of A; verified native settings and
restoration; unchanged two-core/below-normal/3 GiB bounds. These are diagnostic
comparison criteria only. Every individual result remains visible, including
tails and failures. WFP calibration and every recorded worker PID through the
complete preceding workload, cohort, cancellation and cleanup remain required.
Any supported correction then requires a clean candidate with temporary
instrumentation removed and complete ordinary exact-head qualification.

## Complete prospective result and diagnostic cleanup

Source `5af1bf5039a41a1b8bfcbee32c31d30b2bcd88f4`,
[run 39845510739, attempt 1, job 120057608187](https://github.com/gabned/provelume/actions/runs/39845510739/job/120057608187),
completed the entire predetermined cohort once. The original artifact
`12454944310` is 65,003 bytes, SHA-256
`c1cd880c6d204b3354c58ae5e8faeee1f30f4e1a024edb87687a2ce12441f0eb`;
both ZIP members were fully read and CRC-verified. Its final report SHA-256 is
`79b5bba695510586fa49d41127537dc2508a5efbe2d618a76227c3f3cd0319ce`.
Re-evaluation of all retained cells reproduces every predeclared comparison.

All 24 calls and fifteen self-tests, including the existing final controls,
completed after the full shared S05 preceding load. All four blocks have exact
input/result/token parity and the same selected logical CPUs `[0, 2]`, two
physical cores and unchanged resource limits. Native default/readback and
restoration, own-thread counters and native interval telemetry are complete.
WFP calibration and the complete 23-worker-PID audit pass with no worker events.
There are no recorded failures, retries or omitted cells.

Idle CPU seconds are A1 `1.0`, B1 `0`, B2 `0.03125`, A2 `0.921875`:
`1.921875` under the observed default versus `0.03125` under zero blocktime,
a 98.37% reduction. Both intervention blocks beat both baseline blocks under
the predetermined comparison. Warm first-output medians are 3.6095 seconds
under the default and 2.9845 under the intervention; the prefill-tail comparison
also passes. The requested 300 ms sleep windows have observed Windows clock
durations of approximately 297–313 ms; all individual measurements remain in
the original report rather than being rounded into a different result.

This demonstrates prospective avoidable post-inference CPU cost and supports
the narrow Windows OpenMP wait correction. It does not establish the historical
cause of the original 5.844-second failure, identify opcode or scheduler states,
or qualify any candidate. The original #409 CPU FAIL, #408 HTTP 403 and earlier
laboratory fullsuite FAIL remain unchanged. The diagnostic result is
**NOT_QUALIFIED**.

A separate normal cleanup commit restores the seven executable paths changed
by this investigation to their accepted-main bytes and removes its five
temporary modules/scripts/fixture. The complete diagnostic implementations and
fixed-input fixture remain available at immutable source
`5af1bf5039a41a1b8bfcbee32c31d30b2bcd88f4`; all preceding commits and attempts
are preserved. This document retains the plan, provenance and outcome. The
subsequent PRODUCT correction and its ordinary qualification remain separate.
