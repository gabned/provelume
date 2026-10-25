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
