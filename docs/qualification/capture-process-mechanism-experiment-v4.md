# C4: full ordinary Capture process mechanism observation

Status: FROZEN_SCIENTIFIC_DESIGN_V4_TEMPORARY_IMPLEMENTATION_AND_CONSTRUCTION_APPROVED. Earlier design versions remain immutable and were not model experiments. Version 2 closes publication; version 3 separates legacy profiling; version 4 only clarifies already implemented clock accounting. No C4 model run or CI dispatch is authorized by this document itself. Root selects exact implementation, construction and immutable source/plan identities before the single prospective cohort. Earlier C4 designs selecting 12 callbacks per job were never executed; this design selects all 19 qualification calls and preserves the six separate final legacy profiling calls unchanged.

## Evidence and question

C2's complete negative cost decision and C3's complete negative clean-preparation decision remain unchanged. C3 demonstrates bounded Atomic single-payload component CPU savings in all eight prespecified comparisons. It fails its separate strict B fresh M6 guard. It neither corrects nor explains the Capture process tail.

The isolated C3 all-96 projection SHA `b03a3917e3d10a7560fd7e216242bce71d1f89f48a4b736cc0b43f7298fa8507` localizes A1 callback 14's 937.653603 ms Capture to submit 41.583405 ms and process 896.070198 ms. Its whole-Capture parent CPU is 108.806989 ms; other same-host B busy process values are 198.611623–234.177642 ms with comparable parent CPU and the same counted write bytes. No process-phase CPU, syscall latency, tracer identity or wait-state timeline was recorded. Low observed leader runqueue time and voluntary-switch counts do not identify a wait cause.

C4 asks where actual process elapsed time and caller CPU are spent, and what the caller/native worker/tracer are observed doing during those intervals. It reproduces the full preceding ordinary load and all governed operations in the same job. It does not offer the unchanged fastpath another opportunity to obtain a favorable guard. Even four ordinary PASS jobs cannot support a clean candidate or activate the disabled correction proof.

## One complete cohort and unchanged workload

One new workflow dispatch, attempt 1, four fixed slots A1/B1/B2/A2, maximum parallelism 2, fail-fast false. Slot labels specify source selection, not a global execution order or synchronized waves. Actual dispatch/source/checkout identities and every run/attempt/listed/direct job response are preserved. A and B use the same original and single-task-fastpath Atomic implementations already tested in C3; no new Product correction is part of C4.

Each job executes the full, unchanged ordinary Linux path: 3 cold runs, 60 warm cases and their original evidence refreshes, deterministic probes, cancellation/unload/error paths, full S06, S07, S08, Iudicium and final network/integrity/cleanup checks. No append, fresh guard cohort or Atomic32 batch is added. Model, corpus, sampling, configuration, resource budgets, admission limits, all original evaluator thresholds and safety controls remain unchanged. Hard job timeout remains 1200 seconds. Earlier C1 full ordinary executions left approximately 172–197 seconds; this is a feasibility reference, not an overhead bound or runtime guarantee.

All **19 existing qualification-stratum deterministic Capture probes per job, 76 selected total**, are selected before execution. No extra Capture is invoked:

| Callback ordinals | Original report path | Count | Original sample values |
|---|---|---:|---|
| 0–2 | `deterministic_idle[i]` | 3 | 0–2 |
| 3–5 | `deterministic_busy[i]` | 3 | 0–2 |
| 6–11 | `s06.deterministic_busy[i]` | 6 | 0–5 |
| 12–13 | `s07.samples[i].probe` | 2 | 700–701 |
| 14–16 | `s08.idle[i]` | 3 | 800–802 |
| 17–18 | `s08.performance[i].probe` | 2 | 810–811 |

The unchanged final `diagnose_ai_capture.diagnose` additionally runs six existing legacy profiling probes per job: three idle and three busy, samples 900–902. They remain a separate DIAGNOSTIC_ONLY stratum in the original report, with no C4 slots, sampling or promotion. Thus the original workload has 25 Capture calls per fully completed job; C4 observes only the 19 qualification calls. The legacy lazy import must bind the original probe, and temporary core hooks must be restored before that profiling begins. No existing profiling call is removed or rerun.

Group, original row index and complete row equality bind a callback; sample number alone does not. S06 has six governed busy probes and no idle group. Source bindings in `qualify_ai_runtime`, `qualify_ai_jobs`, `qualify_ai_setup` and `qualify_ai_synthesis` must all be accounted for, including their lazy imports. Every original returned row is retained verbatim; observer fields are separate. Original input/Original preservation, extraction, search, authority, receipt, resource and native activity validations are not skipped.

## Nine bounded phase records

For each selected successful new-submission path, record exactly these nine source-bound phases. Wrappers apply only to that callback, store, caller TID and transaction scope; unrelated operations and worker threads pass through unchanged.

| Phase | Exact callable binding | Inclusive parent |
|---|---|---|
| process | `capture_adapter.CaptureAdapter.process` | selected Capture |
| lifecycle entry/recovery | returned context manager `__enter__` from `instance_lifecycle.InstanceLifecycleManager._hold(purpose='capture-acquire')` | process |
| submission inventory | `CaptureAdapter._submission_locked` | process |
| acquisition | `CaptureAdapter._acquire_locked` | process |
| atomic prepare | `atomic_commit.AtomicInstanceCommit._prepare` | acquisition |
| atomic publish | `AtomicInstanceCommit._publish_entries` | acquisition |
| assurance | `CaptureAdapter._assure` | acquisition |
| review routing | `capture_adapter.route_committed_acquisitions_locked`, the alias actually called | process |
| index refresh | `capture_adapter.refresh_search_index`, the alias actually called | process |

Atomic records require the same transaction/store/owner under acquisition, with profile key `capture-acquisition` and kind `capture.acquire`. The lifecycle record ends when original `__enter__` returns; original `__exit__` is delegated normally and its cost remains in process residual. Recording an entire lifecycle context as an entry duration is forbidden.

Each phase stores source/AST identity, callback ID, phase ID, parent ID, caller PID/TID, monotonic-wall and caller-thread-CPU start/end, return/exception outcome and instrumentation-error state. The fixed boundary recipe is wall, thread CPU, original callable, thread CPU, wall: four clock reads per phase, at most 36 per successful callback. The process-root phase additionally reads process CPU immediately around its original body, adding two reads (38 phase-clock reads). The callback additionally has two outer monotonic envelope reads, before the unchanged probe and after Original verification/search, for 40 diagnostic clock reads total per selected callback. Those two envelope reads are outside the original Capture clock. Calibration recipes contain only the 38 phase-clock reads, with no callback envelope. It is net parent PROCESS CPU, including parent pool/other threads, excluding the observer and native child. Caller-thread CPU excludes worker-thread work. Other parent-thread roles remain unmeasured. No per-I/O, per-fsync, per-pool-task or per-future timing wrapper is installed.

The original `deterministic_probe` is called unchanged; no C3 AST copy is needed. Original `capture_seconds`, submit/process/search floats and all returned fields remain verbatim. If an outer original-probe CPU value is additionally retained, it is labeled probe CPU including Original verification and search; it must never be labeled Capture CPU. The seven ordinary qualification/report/network script bytes remain identical across baseline and A/B/dispatch sources.

All intervals and their nesting are checked independently. Process residual is process wall minus the union of its direct child intervals; acquisition residual is acquisition wall minus the union of prepare/publish/assurance. Inclusive records are never summed as independent work. Residuals are unassigned intervals, not named syscalls or proof of blocking. Negative CPU deltas, crossed intervals, repeated unexpected phase identities, missing phases and limits remain visible and make the corresponding observation incomplete. They do not raise into or truncate original Product execution.

## Fixed parent observer

A persistent observer process is the qualifier entry's parent under the unchanged `strace -ff -tt -e trace=network` invocation. Existing native worker seccomp, priority, memory/CPU controls and network checks remain unchanged. Parent-to-descendant `/proc` access uses existing permissions; no capabilities, ptrace grant, Yama change, socket, shared resource tracker or acknowledgement is introduced.

The observer and entry share a prefaulted 4096-byte fixed-layout memory block containing exactly 19 once-published immutable callback descriptors and one active-slot byte. Descriptor ownership, the actual Python 3.12 mapping descriptor behavior and closure are verified before dispatch. Its FD is passed only to the entry and closed after mapping; it must not leak to a native worker. Entry writes an active callback descriptor before the original Capture clock and clears it after Original/search or in a failure-preserving finally. There is no per-phase I/O or acknowledgement. Phase/sample alignment is computed afterwards from monotonic timestamps.

Publication is bounded and source-specific: each descriptor has a unique immutable generation and payload, is initialized once before its callback, and is never reused. The writer publishes its single active-slot byte after initializing that descriptor and clears it afterwards. Reader reads active byte, immutable generation/payload, active byte. A changed or invalid byte/generation is INCOHERENT and retained; there is no retry, spin, writer wait or acknowledgement. This is a concrete Linux x86-64 publication recipe, not a formal portable-memory-ordering guarantee. An unsupported platform is observability incomplete, not silently supported.

The persistent observer wakes at a fixed 50 ms schedule. While inactive it performs no periodic target `/proc` reads. One-time identity/bootstrap and final own-cost observations are distinguished from active samples. While active it reads only the fixed interfaces for at most three targets: qualifier/caller process, its currently observed native worker, and actual tracer. It retains all sampled TIDs up to 16 per target. It does not scan arguments, environment, stacks or FD paths.

Per sample preserve scheduled/actual start and completion, generation/callback identity, observed PID/start-time/TID identity, read availability/errno and raw supported fields: stat state/PPID/start ticks/CPU/fault counters, status TracerPid/context switches, schedstat, IO counters, wchan and first syscall-number/state token. No syscall arguments are collected. A denied syscall file, zero wchan or disappearing thread is explicit unavailable/unknown evidence, not a no-wait observation. PID reuse, before-only/after-only TIDs and counter quantization remain explicit.

Caps are 128 active rounds per callback (6.4 seconds at nominal cadence), 2432 per job, 16 TIDs per target, three targets, 192 attempted reads and 262144 read bytes per round, and 16 MiB retained encoded observation bytes. Attempted reads are observer bookkeeping, not a kernel-syscall count. Sampler RSS has a separately declared 64 MiB limit and actual maximum accounting; encoded-byte size is never presented as RSS. No new resource budget is granted. Caps bound observation, not execution. A cap, read/publication-coherence error, missing descriptor, overflow or observer failure sets observability incomplete and retains partial results; **all ordinary calls and checks continue wherever their original execution allows**. No automatic retry, retiming, sample replacement or Capture rerun occurs. All wakeups, late/missed scheduled deadlines, active/inactive counts, read counts, actual sampler wall/CPU/RSS and errors are recorded. A missed 50 ms deadline is not relabeled as an observed interval.

The observer itself adds traced syscalls and may perturb the target. At six TIDs the design estimate is approximately 90 traced calls per active round; this is not a measured overhead or bound. Actual cost and cadence are mandatory. Sampler records describe observations at instants; repeated states are occupancy samples, not proof that a syscall or wait persisted continuously between samples.

Before the full ordinary measurement, execute exactly 512 empty nine-span recorder recipes under the same network strace. Preserve every raw wall/thread-CPU/process-CPU boundary/outcome and clock resolution. The root process-CPU pair is part of the recipe. These are RAM/no-op recorder calibrations, not Product, model, Atomic or IO workloads. Do not subtract calibration values from any original ordinary measurement or present observed calibration extrema as a universal bound. Sampler latency, own CPU, reads and cadence are accounted from its actual execution; no separate fresh model control run is introduced.

Before source/plan freeze, one prespecified isolated construction cohort exercises meaningful synthetic thread and IO-wait visibility, descriptor lifetime/inheritance, callback/phase/alias binding, original return and exception preservation, lifecycle CM semantics, immutable-publication incoherence and every cap/error path. All failures and revisions remain retained. Construction is not model evidence or candidate qualification.

## Analysis contract and limits

An independent offline operator selected by root first verifies raw metadata, exact source/plan/helper bytes, complete original archive CRC/hash identities and original report/telemetry bindings in a credential-free context. The unchanged accepted evaluator and network observer are replayed separately. Original 28 gate maps and return codes, actual run/attempt/job conclusions and source/observer outcomes remain separate. Preserve an exact before-network ordinary report copy and its actual copy exit code before the canonical observer runs; the copy must succeed for complete source/data binding. A copy failure does not skip the original network observer. A real performance FAIL with a full report may yield a complete mechanism dataset; timeout, crash, missing rows or original early abort yield a partial dataset. Completed steps and available logs never synthesize job SUCCESS.

For every one of 76 selected callbacks, report original submit/process/total/search wall, net parent PROCESS CPU, all nine phase wall/caller CPU intervals, inclusive/exclusive union residuals and all aligned state/counter samples. Report every callback and group; ordering by latency is for inspection, not favorable cohort selection. Original latency formulas and all values remain unchanged.

Prespecified mechanism evidence classes are observations, not exclusive causal verdicts: caller CPU share; sampled runnable/runqueue evidence; observed fsync/metadata/read/write syscall state; observed futex state; sampled trace-stop state and tracer scheduling/activity; unknown/unavailable. File-level or SQLite attribution requires actual evidence beyond a phase name and a syscall number. An observed `D`, `S`, `t`, zero physical IO count or wall-minus-CPU gap alone does not identify cause. Other thread roles and unsampled transient lifetimes remain unknown. Permission-denied fields cannot support the corresponding mechanism claim.

C4 has **no clean-candidate preparation or correction-support boolean**. Qualification and correction support remain NOT_GRANTED. All-PASS ordinary reports do not convert C3's failed decision into a pass. A new Product correction requires a newly demonstrated avoidable process cost, defect or correctable variability and a separately prespecified controlled comparison verifying its effect. Exact-head clean final native/full ordinary gates, updated preflight, normal merge and post-merge acceptance remain mandatory later.

If the long process wait does not recur, report that finite-cohort limit with all observed ordinary results. Do not rerun an unchanged candidate for a favorable outcome. Any next experiment needs a new discriminating observation or source finding that these complete data justify.


## Fixed source interfaces

Plan schema `capture-process-mechanism-experiment/v4`; mode `FULL_ORDINARY_PROCESS_MECHANISM_V4`; regime `FULL_ORDINARY_ALL19_PROCESS_OBSERVATION_NOT_QUALIFICATION`. Canonical counts are `callbacks_per_job=19` and `callback_count_total=76`, with no micro/work/cleanup budget fields. Three diagnostic helper source hashes use the existing `helper_sha256` full-repository-path mapping. Telemetry schema is `capture-process-temporary-telemetry/v4`; sampler `capture-process-proc-observation/v4`; entry `capture-process-entry-execution/v4`; observer `capture-process-observer-execution/v4`. Passive analysis schema is `independent-capture-process-mechanism-analysis/v4`, with complete/partial mechanism-data results only and qualification/correction support NOT_GRANTED.
