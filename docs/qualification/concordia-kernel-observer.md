# S07 CPU recovery: kernel event chronology

Owner remains #439 / concordia-s07-cpu-recovery, original BIND6654096835.
Starting head e2342c05463bd71ac7ec3cd96421b7f359330830, accepted main
1711f037b1467d84eb5e145466dad6a6171643fc, Protocol1.5.2/pin02317,
PR-local legacy. This preparation changes no PRODUCT behavior or numeric gate.

## Retained failing anchor

Run42290059975/attempt1/job128140838845, artifact13541917919:
970243bytes, SHA-256
5248db15078cf441570f114390e8030dc79e4f0065caa6b87172580f00cc7c2a.
All2504members, including2476network traces, were independently checked/replayed.
The complete fixed A/B/B/A source-factor block remains permanently stopped.
Arm3, source d5b2cc9f06c14be8c51a082d309dbde0358552e8, cold S08 probe810:
Capture0.44899768599998424s against its own0.392780404000041s limit;
submit0.07195525800034375s/process0.3770424279996405s. The other A arm's cold
process is0.193809269s; B arms are0.170222537/0.161597877s. This is not attribution.

The same original deterministic_probe serves deterministic, governed, setup and
synthesis paths. Recreating an identical historical episode or phase is not a
new gate. A relevant mechanism still needs controlled evidence; no finding is
disposed of and no fixed threshold is relaxed by that clarification.

## Novelty audit before execution

| Completed method | Already observed | Not repeated |
| --- | --- | --- |
| Source/boundary/extended controls | Wall/CPU/rusage, endpoint scheduler/I/O deltas, nominal10ms snapshots | A generic CPU-versus-I/O-versus-scheduler hypothesis is not new |
| Pool prefix/caller spans | Direct prepare/publish/shutdown times and pool envelopes | Pool-shutdown attribution is not new |
| Light/rich bundle | Wrappers/counters and idle-derived budget contrast | No light/rich or reverse/retry block |
| SMT/tracer placement | Topology/affinity/tracer CPU contrast | No changed application placement |
| Digest/journal/path-guard | Isolated PRODUCT factors and syscall-selection control | No source replay; seccomp-BPF selection stays refused |

Those methods do not retain the kernel switch-out state, cross-thread wakeup and
actual switch-in chronology of the same owned task. Endpoint totals cannot
locate one long wakeup-to-run interval. Python wrappers, snapshots and inclusive
fsync times cannot split that interval from the preceding sleep. This is the new
signal; the original network-only strace remains unchanged.

The falsifiable temporal hypothesis: on a newly exceeded Capture process window,
one caller wakeup-to-switch-in residence accounts for at least half the observed
excess over that probe's own original threshold. Competing outcomes are distributed
ready waits, ptrace-stopped residence, sleeping time overlapping futex/fsync,
execution or incomplete observation. This tests an event shape, rather than
merely whether scheduler counters advance. It cannot attribute past intervals.

## Phase A: model-free observer controls

Run scripts/concordia_kernel_observer.py control --output NEW_DIRECTORY exactly
once. The fixed order is network-only/kernel/kernel/network-only. No model,
application Instance, private data, real provider, remote destination or native
inference is used. Each arm is bounded45seconds with process-group cleanup;
the workflow is bounded10minutes. Errors stop before the next arm. No extra,
reverse or automatic retry block. Evidence is exclusively created.

The managed cloud host has no bpftrace/perf/trace-cmd, visible scheduler tracepoint
formats or effective kernel capabilities. A local refusal before fixtures is
retained. Do not elevate or modify that environment. Use only existing ephemeral
ubuntu-24.04 CI capacity for this capability/control phase. Install Ubuntu's exact
bpftrace0.20.2 and strace as diagnostic tools, recording actual package/kernel
identity. No application dependency or pin changes.

The BPF observer follows its controlled -c child and descendants. It records
numeric TIDs, BOOTTIME nanoseconds, raw scheduler state and event kind only:
no paths, buffers, task names, argv, stacks, environment or document/model bytes.
Every event class has an independent kernel emission count. Any count mismatch,
stderr diagnostic/loss, malformed record or stream over2MiB refuses admission.
No larger buffer or loss allowance follows failure.

Required positive/negative controls:

- Two synthetic CPU children on one available CPU must show positive runnable
  residence. This placement is only a fixture, never application qualification.
- Cross-process pipe wake and real futex wait must show blocked/wake/resume.
  Every required child/thread exit must be observed.
- Real fsync entry/exit and ptrace-stopped state must be visible. Inclusive fsync
  wall time is not physical disk time; physical I/O causality stays UNKNOWN.
- Fixed writes to dedicated /dev/null FD198 must match exact independent
  CLOCK_BOOTTIME before/after bounds and the correct TID/marker identity.
  Paired MONOTONIC/BOOTTIME envelopes must prove a stable conversion offset;
  suspend/clock discontinuity refuses. Version0.20.2 nsecs is not assumed to
  use CLOCK_MONOTONIC.
- An overlapping unowned process performs the same markers; all its events
  must be excluded. Kernel output is ordered by event time, not receipt order.
- Original strace -ff -tt -e trace=network must observe the deliberate AF_UNIX
  socket and tracee exits. This is not a native no-egress qualification.
- Retain all marker and whole-fixture costs in every arm. A marker above the
  predeclared5ms per-marker control bound refuses admission. No cost is subtracted
  from a later scored sample. Whole-arm time includes tool startup and is not
  presented as per-Capture overhead.

MODEL_FREE_CONTROL_COMPLETE certifies only those controls on that exact host.
It does not grant native admission: complete syscall pairing and event-to-Capture
window binding/cost validation still precede a real measurement.

## Phase B: discriminating design, execution locked

After complete Phase A evidence, bind exact marker identities to original Capture
submit/process windows without changing payload, original clocks/evaluator or
results. Require the complete operation/task inventory and observed exits.
Decode raw scheduler states only against the recorded actual kernel event format;
unknown format or missing intervals refuses. Unexplained time remains UNKNOWN.

The intended measurement is one complete original sequence on immutable baseline
d5, original network-only strace, inherited application placement, exact locked
model/runtime/configuration, fresh equal-depth store and unchanged1200s execution/
60s observation bounds. No second source/correction arm, added load, changed gate,
sampler, Python CPU accounting, pool/durability wrapper, profiler or seccomp-BPF
syscall-selection optimization. Marker work and measured costs survive scoring.

On an actual relevant original FAIL, evaluate the temporal prediction on that
same scored interval. Split switch-out-to-wakeup and wakeup-to-switch-in into
disjoint intervals. Retain inclusive syscall overlap separately: overlap alone
is not causal proof. No exceedance means NON_REPRODUCTION and a permanent stop.
Source/input/host drift, missing events/overflow, application/network or non-timing
failure stops collection. All reports stay DIAGNOSTIC_ONLY with original gates
and every FAIL preserved.

Phase B is a design, not a dispatched or qualified command. Any causal PRODUCT
correction is subsequent work under the same owner, followed by exact-candidate
native/CI/review/preflight and actual-main acceptance. Existing ABBA is never
resumed. S07/S08 remain NOT_ACCEPTED, S09 unopened, identity0.14.0/development,
release NOT_PUBLISHED. All manuals remain DEFERRED_BY_MAINTAINER / NOT_RUN until
the completed official release on the maintainer's Windows11Pro25H2 PC.

## Official observer reference

The [versioned bpftrace0.20.2 manual](https://github.com/bpftrace/bpftrace/blob/v0.20.2/man/adoc/bpftrace.adoc)
defines tracepoint arguments, nsecs, -c/cpid, async printf and map counters.
BEGIN precedes other probe attachment and is not an attachment barrier. Actual
fork/marker/exit completeness is required. Lost output is never accepted.

## First preparation refusal, before any fixture

Run42354986579/attempt1/job128351009422 on637e207 stopped before the control
command. Ubuntu bpftrace0.20.2-1ubuntu4.3 and strace6.8-0ubuntu2 were available.
The ordinary user could not inspect the root-restricted tracefs event path; the
workflow then tried to mount it, and mount correctly reported it already mounted.
Artifact13567237734 (513bytes, SHA-256
c6348484e760c818857a66b4e376c987432f744e61313522fa685d5a9a95deeb)
retains the two original package/kernel records; both members were verified.
All other jobs, including old studies and ordinary model acquisition, were skipped.
No fixture, BPF program or native measurement ran.

The pre-execution correction performs both the presence check and format reads
with the same root access as the declared observer controller. Existing mounted
tracefs is reused; the mount remains conditional. This corrects preparation,
without a completed control/native replay, increased bound or alternate observer.

## First collected kernel arm: refused output volume

Corrected source b40e946 ran42355254547/attempt1/job128351834366. The original
network-only arm completed; the first kernel arm attached/exited successfully
with empty observer stderr. Its3467493-byte stream exceeded the unchanged2MiB
bound, so admission refused and arms2/3 never started. No model was acquired.
Artifact13567855250 is826906bytes, SHA-256
186c44627fc13c2e949b83d18e3953a09e0085ba7e604d544fbc04291ebab8f4;
all29members and original logs were independently read/verified.

Forensic counts, not admission:93270switch records,65722wake records,62futex
records,8markers,2fsync records and complete recorded fixture metadata.
The original stdout also explicitly reports18335lost events. Independent kernel
counts are107980switches/69347wakes:14710switches+3625wakes are missing, exactly
matching that loss report. An unmatched switch-out in semantic forensics is
therefore not repaired or accepted. Both loss and size independently refuse.
The two CPU children alone generated22162/16551switch-outs. The fixture's
process_time call at every spin performs kernel CPU-clock observations under
ptrace; this was a clock-polling workload rather than the intended arithmetic
CPU contention control.

The corrected synthetic fixture performs4096arithmetic iterations between clock
reads, retaining the same150ms per-child CPU target, two children and placement.
It records actual CPU time/clock-read counts/checksum and refuses above2048reads.
The2MiB cap, default64-page-per-CPU ring buffer, original strace, collector, native
gates and all timeouts are retained. No buffer, loss allowance or timeout is raised.
Syscall controls additionally require paired enter/exit records rather than entry
presence alone. The refused oversized stream is not admitted by offline analysis.
This is a changed observer-validity fixture, not a repeated native CPU experiment
or a larger output allowance. No PRODUCT correction or finding resolution follows.
