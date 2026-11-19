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

## Phase B: one native sequence after fresh admission

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

The implemented native command below remains NOT_RUN until a separately recorded
dispatch; command availability is not admission or qualification. The model-free
Capture-window preparation below is separate. Any causal PRODUCT
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

## Typed-marker completeness refusal and independent raw crosscheck

Run42355829085/attempt1/job128353602018 on0a733b0 stops after its first kernel
arm. Arithmetic CPU targets remain150ms, with actual330/325clock reads, and the
kernel stream is542656bytes/23855records, within2MiB. All emitted counters match
and stderr is empty. However only typed markers2–7 are present: required markers1
and8 are absent despite their successful fixture writes and clock envelopes.
The independent exact-marker oracle therefore refuses admission. The remaining
arms do not run. This is NOT an application CPU reproduction.

Original artifact13567896248:134898bytes, SHA-256
74fba2c8cb8e4dbaeb5eea76da7bac2cd117ec0674c1fe7c2328ca0af0402978;
all33members were independently checked. No failed result is relabeled.

The next observer-only discriminator records two independent sources concurrently:
the existing typed sys_enter_write predicate as T, and raw_syscalls:sys_enter
register arguments as primary M. On the explicitly supported x86_64 ABI, write
is syscall1, argument0 is FD198 and argument2 is the byte count. The raw probe has
no byte-count range predicate; userspace still requires the exact8fixture markers,
identities and clock envelopes. A typed event cannot substitute for a missing raw
marker. Independent kernel event counts, size/loss/negative/exit/syscall-pairing
and all cost/timeout bounds remain mandatory.

This is a changed marker observation mechanism, not another application/source
or CPU experiment. Raw complete/typed incomplete would isolate an observation-
path difference on that host; both incomplete refuses; both complete leaves the
previous typed gap unexplained. No historical cause is inferred from a later
non-reproduction. Typed markers are retained for comparison and never relied on
for admission. There is one new fixed model-free block; no automatic repetition.

The [Linux v7.0 raw syscall definition](https://github.com/torvalds/linux/blob/v7.0/include/trace/events/syscalls.h)
declares syscall id and six raw arguments populated by syscall_get_arguments.
Both actual kernel event formats are retained by the control workflow. Other
architectures refuse instead of inheriting this ABI claim. Actual Capture-window
binding and native admission remain locked until the observer is complete.

## Verified observer discriminator and one real Capture binding preparation

Run42356627852/attempt1/job128356018540 on53a359b completes the declared four
model-free arms. Raw markers are8/8 in each kernel arm; concurrently typed markers
are1/0. The observation-path difference is therefore demonstrated on that host,
without attributing a PRODUCT failure. Both raw streams (547173/548111bytes) fit
the unchanged2MiB limit; independent emission counts, clock/identity checks,
positive/negative controls and owned exits pass. All marker envelopes are at most
135481ns, below the unchanged5ms control bound. These are fixture costs, not
native Capture overhead or a deduction from any scored sample.

Original artifact13567059850:1116143bytes, SHA-256
b5e0b71570a5788f2983793c589fd31cf72b0472a101648f8f4e728f62c1c52f.
All65members were independently read/CRC/SHA checked; original analyses replay
identically after normal JSON tuple/list serialization. The earlier three
refusals remain refused. This observation does not resolve an application finding.

The next preparation control is a single real AI-Off original deterministic_probe
on immutable d5, sample810. scripts/concordia_capture_marker_fixture.py applies
only in its fresh process, preserving original returns/exceptions and restoring
methods afterward. It writes four exact markers at submit/process start/end.
Frame markers9/10 are outside the original probe clock. Actual Original/search
and default-off checks are mandatory; marker costs remain inside Capture timing
and are never subtracted.

To keep the existing output bound, the explicit CAPTURE_BINDING header enables
scheduler/wakeup/futex/fsync emission only between frame9and10. Ownership fork/
exit records and raw markers remain visible throughout; no schema or loss gate
is weakened. Default observer-control mode still records its full fixture.
Import/Instance-initialization/cleanup work outside the original probe is excluded
from this application window, rather than increasing buffers to record it.

Invoke the existing workflow with observer-study=true, kernel-control=true and
observer-source=capture-binding. This selects the separate capture-binding command;
it does not rerun the completed four-arm controls or any native/source study.
The same existing ephemeral host/tool and45s execution/10min job bounds apply.
A fresh temporary canonical Git worktree supplies exact clean d5; no model,
real account, remote destination or external credentials enter the fixture.

The local real-original fixture already preserves Original/search/default-off,
exact marker order9/1/2/3/4/10 and original source identity. Its local marker
envelopes are at most5678ns; local kernel correlation remains NOT_RUN because
that environment lacks tracepoint access. CI must independently match every raw
marker to its own TID/BOOT clock envelope, preserve all tracee exits and prove
stable BOOTTIME/MONOTONIC conversion. A typed record cannot stand in for a missing
raw record. The result is CAPTURE_WINDOW_BINDING_OBSERVED, never native acceptance.

For the later one-sequence native experiment, gate emission only for the declared
S08cold sample810 frame, preserving all other original scored samples/reports.
Analyze scheduler state inside that frame rather than joining across disabled
windows. Any other FAIL survives but cannot supply attribution to an unobserved
interval. Exact native host/source/input/containment/marker gates still precede
execution. No native inference is requested by these preparation controls.

## Native driver and admission contract

`scripts/concordia_kernel_native.py` implements the one native experiment, under
the same owner and original BIND. Its sole selector is `native-cold-810`, with
observer-study and kernel-control both true, on the exact owner branch/attempt1.
Every previous study and the standalone model-free control job is excluded.
No fixed four-arm block, completed source contrast or inference experiment repeats.

Before acquisition or inference, `admit` checks committed source, fresh accepted
main, unchanged baseline/qualifier/evaluator/corpora and current kernel/tool/CPU/
cgroup/identity/placement. Actual tracepoint formats are retained. State decoding
accepts only the independently recovered sched_switch print contract from the
verified42358282166 artifact; another format refuses. The baseline's actual
containment must deny socket/process creation, keep the original two-worker-CPU
policy and remain visible under the unchanged network-only strace.

One fresh-host AI-Off Capture binding is an admission prerequisite, distinct from
the completed observer experiment. It runs with the ordinary runner identity,
not root. Only bpftrace uses the ephemeral job's existing sudo capability; its
child drops to the original user before strace/application execution. A clean
environment excludes workflow credentials. The full original process-limit
envelope is restored before dropping privilege with setpriv, because bpftrace
may raise its own memlock limit; neither the application limits nor placement are
increased. Child UID/GID/groups, affinity, nice and every process limit must match
the admitted runner. Exact six raw markers, clock envelopes,
owned fork/exit and original trace inventories, paired syscalls and the unchanged
5ms marker-cost bound must pass. This refreshes host evidence; it supplies no CPU
acceptance. Admission expires after15minutes and is consumed with exclusive creation.

The BPF pairing addition retains an owned futex/fsync entry timestamp in a map,
without emitting work outside the frame. If its exit is inside the frame, the
actual earlier entry is emitted; an entry inside the frame retains its actual
later exit. Both emissions have independent kernel counters. No synthetic syscall
exit or duration is fabricated. The2MiB/default-buffer/loss gates are unchanged;
incomplete pairing refuses. Scheduler emission still covers only frame9–10.

`run` verifies every locked model/runtime byte before and after copying to a fresh
equal-depth store. It consumes one clean immutable d5 worktree and invokes the
original complete measure function without replacing its evaluator, configuration,
model, inference, payload, cancellation, pool or durability logic. Marker wrappers
activate only during the original synthesis probe810; all other probes return
their original results. Sample810 may occur only once. Module origins, actual
child identity/placement, all original reports and the full strace are retained.

Application execution remains bounded1200s and the original network observation
60s. The separate30min workflow budget includes bootstrap/acquisition; it does not
extend either execution bound. All native failures and the unchanged stop-control
projection survive. The original report is retained before network evaluation,
and a separate copy receives the original evaluator. Costs are recorded, never
deducted. Frame/submit/process markers are matched to their TID/BOOTTIME envelopes;
the prediction uses that cold probe's own unchanged idle-derived Capture limit.

An incomplete event/identity/clock/exit/marker/cost observation stays UNKNOWN.
With complete evidence, no cold810 Capture exceedance is NON_REPRODUCTION and
permanently closes this experiment. A supported or refuted event shape is only
temporal evidence; neither establishes a PRODUCT correction or historical cause.
Every other original FAIL remains an independent finding. All S07/S08 acceptance,
ordinary exact-head CI/review/integration and final release gates remain separate.

Commands, only after source review and the retained pre-execution declaration:

```bash
.venv/bin/python scripts/concordia_kernel_native.py admit --output .agent/kernel-native-admission
.venv/bin/python scripts/ai_runtime_acquire.py --directory "$NATIVE_INPUTS" --accept-licenses --include-model
.venv/bin/python scripts/concordia_kernel_native.py run --inputs "$NATIVE_INPUTS" \
  --admission .agent/kernel-native-admission/admission.json --output .agent/kernel-native-sequence
```

## Native admission refusal before acquisition

Run42361189975/attempt1/job128369747525 on7006228 reaches the fresh-host AI-Off
binding and exits its original Capture successfully. Admission refuses its stream
with `unrecognized event output`: bpftrace's retained `-k` diagnostics identify
`map_delete_elem` returning-2 when the pairing addition deletes a recorded-entry
map key that was never set outside the frame. No model is acquired and no native
inference runs. Artifact13570001400 is288568bytes, SHA-256
e53269bbf676ccee995b5e0e7f7ba6bcb841d1a92f4dce7219de2738a01629ab;
all32members, including the1151074-byte raw stream, were independently read,
CRC checked and hashed. The failed stream remains refused and is not filtered
into admission.

The correction guards deletion with the map's existing nonzero entry. It changes
no event emission predicate, counter, parser, bound, buffer, timeout or scientific
outcome rule. The next invocation is a changed preparation recovering this exact
diagnosed helper failure; no completed native experiment is repeated. Actual
fresh-host admission must still succeed before model acquisition or inference.

## Executed sequence: original network FAIL, experiment UNKNOWN

Run42361533300/attempt1/job128370775319 on be4f1e7 passes fresh-host admission
and locked acquisition, then executes the single complete original d5 sequence.
Artifact13569993525 is896966bytes, SHA-256
7fb35a80a2f314cc3737b6ab9f5d580f1563cd52a78361517a4a227aeb0a4671.
All670members were independently restored/read/CRC checked/hashed. The original
network evaluator returns FAIL: the harness startup issues two AF_UNIX sockets
and failed ENOENT connections to /var/run/nscd/socket. Every other original gate
passes, including S08. The original FAIL is preserved; the experiment is STOPPED /
UNKNOWN, never a qualifying PASS or resolution of any historical CPU finding.

Cold810 Capture is0.235864707s, below its own unchanged0.371726774s limit.
Independent forensic replay retains complete marker clocks,623original traces,
627owned exits and paired2962futex/52fsync operations. It observes no new Capture
excess. This temporal non-exceedance does not override the original network FAIL,
promote UNKNOWN to valid NON_REPRODUCTION, or establish historical causality.
No equivalent inference redispatch follows this completed sequence.

The driver had removed benign HOME along with credentials. A separate two-case
model-free startup control demonstrates that Path.home() under that environment
issues exactly the same two NSS sockets, while retaining the original HOME
issues none. The correction retains only PATH/LANG/PYTHONNOUSERSITE/HOME, removes
the unnecessary passwd-name lookup, and checks the actual driver's complete
startup/import/source/host path under original strace before any possible model
acquisition. No credential or extra ambient variable is inherited.

The explicit `native-admission-only` workflow selector verifies that correction
on a fresh real host without acquiring a model or executing inference; acquisition
and sequence steps are guarded to native-cold-810 only. This is preparation
verification, not reopening the stopped experiment. Incomplete chronology stays
UNKNOWN even when the timing is below its threshold. Original reports, evaluator,
strace and all bounds remain unchanged. Existing findings remain CURRENT /
NOT_DEMONSTRATED; further progress requires a distinct demonstrated hypothesis
or an explicit product decision, rather than a repeated equivalent measurement.
