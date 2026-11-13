# S07 lifecycle CPU diagnostic

This branch owns one diagnostic under the maintainer's isolated-branch instruction. It references [the original #439 BIND](https://github.com/gabned/provelume/pull/439#issuecomment-6654096835) and [the corrected model-free control](https://github.com/gabned/provelume/actions/runs/43109183453/job/130820361576). The diagnostic has no qualification effect. The workflow can run once per attempt-1 push changing its own file on the named branch. Its source check requires the exact diagnostic history on the recorded main and an exact path allowlist. [Initial preparation](https://github.com/gabned/provelume/actions/runs/43111976421/job/130830090204) stopped at Ruff before the model-free controls. The next [preparation](https://github.com/gabned/provelume/actions/runs/43112198310/job/130830889689) passed Ruff and stopped in the model-free network/exit check. Separate, sanitized startup and Capture-control syscall/exit receipts are required by the next correction. The [separate startup receipt](https://github.com/gabned/provelume/actions/runs/43112532066/job/130832020751) identified six clean traces and an extra file without an exit marker. The worker receipt startup.json matched the initial trace prefix. The corrected observer uses startup-network for traces and startup.json for the worker receipt. The [prefix correction](https://github.com/gabned/provelume/actions/runs/43112705221/job/130832624400) passed the startup network check and reached the four-frame fixture. The fixture failed because its temporary transaction-body hook did not bind the adapter instance. The hook now uses a bound method descriptor. The [bound method control](https://github.com/gabned/provelume/actions/runs/43112934805/job/130833442181) observed six clean startup traces and 26 clean fixture traces. The existing parser then rejected the kernel stream with its shared size-or-stderr error. The workflow records both sizes and bounded stderr before applying the unchanged parser. No native sequence started in those preparations.

| Finding | Original job | Observed Capture / own limit (s) |
| --- | --- | --- |
| Deterministic 1 | [126918981396](https://github.com/gabned/provelume/actions/runs/41928461608/job/126918981396) | 0.467447869 / 0.409724258 |
| S06 1 and 5 | [127531293383](https://github.com/gabned/provelume/actions/runs/42109002130/job/127531293383) | 0.441381141 and 0.560081222 / 0.364834536 |
| S06 2 | [127552733141](https://github.com/gabned/provelume/actions/runs/42115157949/job/127552733141) | 0.479963418 / 0.422237996 |
| S06 5 | [127569128458](https://github.com/gabned/provelume/actions/runs/42119880008/job/127569128458) | 0.433143564 / 0.400895138 |

PRODUCT executes from immutable `19249382a1bb9bfbe5ce7d15d00e2ac70a21c3f2`, tree `e5c104cf0b753d4da5326eda691703506f37d83b`. Main `2918c3968168e426986bd8fcd7d485f102c11f7b` and owner head `efc915815bd5a1dcad3246c135043b6111394f47` are checked separately. Reviewed observer helpers come from the owner head. The source, pin, qualifier, network observer, fixtures and dependencies are pinned. Ordinary CPU CI has no matching trigger on this branch.

The admission uses the original kernel collector, 2 MiB stream cap, exact event counters, 5 ms marker bound, fork/exit inventory and benign startup environment. Four fresh model-free frames verify complete TID/clock binding on the actual runner, plus a known delay after acquiring the capture lock and a negative control with the same delay in the transaction body. Admission is valid only on the same boot and placement and for the existing 900-second freshness window. The unchanged locked native inputs are acquired after admission and verified before execution. The observer uses its existing 1200-second execution and 60-second network validation bounds.

One original full sequence observes deterministic slot 1 and S06 slots 1, 2 and 5. The probe times and original gates are recorded without subtracting observer cost. For each selected sample the three lock purposes are distinct, and the full index refresh is measured independently. An exceedance larger than the combined Capture pre-yield windows rules out those windows as a sufficient direct explanation for that observed sample. A compatible window reports caller CPU, blocked time and ready time. The outcome leaves historical causality open. A sample within its own original limit reports NON_REPRODUCTION. Missing binding, network failure or another failed non-Capture check stops the analysis.

The four findings remain CURRENT / NOT_DEMONSTRATED. Independent artifact verification remains BLOCKED_BY_MAINTAINER / NOT_WAIVED.

The [previous admission](https://github.com/gabned/provelume/actions/runs/43113165922/job/130834230736) produced 4,365,439 kernel bytes against the existing 2,097,152-byte limit. Kernel chronology now opens at each successful lock acquisition and closes at its first yield. Full-probe markers still bind the three ordered windows to the original sample. The network trace and task inventory span the whole process. The two Capture scopes and the search-index lock have separate chronology, and the full search-index refresh retains separate wall and caller CPU timings. The synthetic fixture exercises the existing futex and fsync pairing check inside its fourth probe, alongside the unchanged positive and negative delay controls. No trace is truncated and the original limits stay in force.

The [first windowed admission](https://github.com/gabned/provelume/actions/runs/43170669129/job/131022921374) recorded 488,804 kernel bytes and passed the network controls, then stopped at marker corroboration. The owner [documented gaps in the typed entry tracepoint](https://github.com/gabned/provelume/blob/efc915815bd5a1dcad3246c135043b6111394f47/docs/qualification/concordia-kernel-observer.md#L207). The independent corroboration now pairs each raw marker entry with the write syscall exit and verifies the returned byte count, exact caller, order and clock envelope. A missing or incomplete observation still refuses admission.

## Direct Capture inventory experiment

The [previous completed sequence](https://github.com/gabned/provelume/actions/runs/43170959759/job/131023870446) is retained at `ed48e20b7e59e10ddf51624051665fb0089e231d` as NON_REPRODUCTION. This next, single diagnostic uses exact source `a713f0141799fea60b7caa1a0e62826f3b373bf9` of [the S06 1 and 5 failures](https://github.com/gabned/provelume/actions/runs/42109002130/job/127531293383). The two slots both ran warm and under the same 364.834536 ms threshold. The observed totals were 441.381141 and 560.081222 ms, with 317.100805 ms in submit for slot 1 and 523.012562 ms in process for slot 5. Other profiler samples in the same job reported two inventory calls taking about 20–32 ms cumulatively. They did not observe the worker and cannot explain either exceedance.

The one factor is the full journal inventory called directly from submit and from the process-side submission lookup, both in the transaction body. Observe each call with the same-caller clock and paired kernel markers, plus the number of validated records. Measure the complete index refresh separately. A model-free positive control adds a known delay inside the acquisition-side inventory. A negative control adds the same delay in the transaction body after that inventory. The synthetic syscall control proves the collector still captures and pairs futex and fsync. In native read-only windows, a syscall kind can be absent. Every observed pair and kernel counter must still reconcile.

The one-shot selector requires the recorded Linux CPU model and four logical CPUs from the historical job. It keeps the original full native sequence, locked inputs, all evaluator gates and timing formulas, network trace, marker and trace limits and original timeouts. If host admission fails, model acquisition and native execution are skipped. If a slot does not exceed its own original-evaluator limit, it remains NON_REPRODUCTION. If the observed direct inventories are shorter than a reproduced excess, those inventories are insufficient to explain it on that sample. Otherwise the observed scheduler and CPU chronology is compatible with a contribution and does not establish historical causality. No automatic retry or qualification follows.

## Same-runner EPYC 7763 comparison

The [original-profile attempt](https://github.com/gabned/provelume/actions/runs/43181174144/job/131057242025) stopped before model acquisition. This separately authorized one-shot uses the same historical source and probe, but admits an EPYC 7763 runner with four logical CPUs. The historical 9V45 failures remain unchanged.

One model-free instance on that runner uses the original deterministic Capture probe and its synthetic payload. It primes the journal and observes slots 7 and 11, producing 7/8 and 11/12 validated records in submit/acquire. The counts account for the three original idle probes and three deterministic busy probes before S06 slots 1 and 5. The selector requires the same counts for the corresponding native slots. The comparison uses the same source, boot, placement, observer and input-store depth. It contrasts the two inventories and records the index refresh separately. The controls use an independent synthetic Instance with no native worker. Their timing is diagnostic, and the comparison does not match all Instance state, cache history or historical hardware.

Run only one complete original native sequence after host and model-free admission, on the very same runner. Its three original idle probes remain uninstrumented and alone determine its original dynamic gate. The separate matched controls do not feed that gate. Original evaluator, other checks, workload, locked inputs, positive/negative and network controls, capture limits and timeouts remain in force. An inadmissible runner, failed control or mismatched counts prevents an attributed comparison. There is no automatic retry or second native sequence.

## Admission of EPYC 9V74

The [7763-only admission](https://github.com/gabned/provelume/actions/runs/43185714736/job/131072226312) observed a 9V74 with four logical CPUs and stopped before model acquisition. This authorized single attempt also admits that exact 9V74 profile, alongside the already admitted 7763 profile. A 9V74 was recorded in the original deterministic-slot-1 and S06-slot-2 findings. The S06 1/5 source and timing findings are still those from the historical 9V45. Compare only the observations from the same runner and boot. Host, model-free controls, journal cardinality, workload, threshold and stop rules remain as described above. There is no retry.

## Admission of all three authorized CPU profiles

The [9V74/7763 attempt](https://github.com/gabned/provelume/actions/runs/43186309363/job/131074213727) stopped before model acquisition when assigned a 9V45. This one-shot admits 9V45, 9V74 or 7763 with four logical CPUs. It keeps the same-host, same-boot and placement controls, including matched journal counts, before the single original native sequence. The native result records the assigned CPU and whether its model matches the historical S06 1/5 CPU. An equal model does not establish the same historical VM, load or a causal correction. The thresholds, evaluator, workload, deadlines and stop rules are unchanged.

## Committed-manifest window in S06 slot 5

The [completed inventory comparison](https://github.com/gabned/provelume/actions/runs/43186935165/job/131076316954) remains NON_REPRODUCTION. This one-shot isolates only the Capture acquisition commit in S06 slot 5, on the unchanged original source. The observation starts when that commit's pool has drained and ends after the real sync of the directory containing its final `committed` manifest. It keeps the production calls and measures caller wall time, CPU time and scheduler intervals. It validates both caller fsync pairs. The search index is measured separately.

The same-runner model-free comparison primes 11 captures before the selected probe and requires the same manifest byte count, entry count and preimage count as the native slot. Positive and negative controls place a known delay inside the write window or after the real directory sync. The synthetic syscall control, original network observations, source and host checks, pinned inputs and deadlines remain. Only the original native idle probes feed the evaluator. Admit 9V45, 9V74 or 7763 with four logical CPUs. Run the original native sequence once after admission. A non-reproduction or compatible timing alone leaves historical causality open.

## Post-commit integrity readback in S06 slot 5

The [completed manifest comparison](https://github.com/gabned/provelume/actions/runs/43290610054/job/131435541524) remains NON_REPRODUCTION. This one-shot binds only the direct call to `CaptureAdapter._assure` after the transaction commit in `_acquire_locked` on the original source. It observes caller wall time, thread CPU and scheduler intervals without changing the verification or the bytes it reads. The search-index refresh remains separate.

The model-free control primes eleven captures before the selected probe on the same runner. Admission exercises the original Capture semantics, a known delay inside the readback, another delay after it, and the synthetic futex/fsync control. The native comparison requires matching read counts, payload length and derived verification. It also reports total bytes read. The original idle probes alone feed the evaluator. Use one complete native sequence after admission with the same host, boot, placement, pinned inputs, evaluator, thresholds, network observer, deadlines and stop rules. There is no retry.

## Durable staging cleanup in S06 slot 5

The [completed integrity readback comparison](https://github.com/gabned/provelume/actions/runs/43303365936/job/131480099880) remains NON_REPRODUCTION. This single experiment times the original Capture acquisition commit from the successful path's staging-tree removal through the real sync of the parent directory. The final manifest and its staging-directory sync precede this window. Rollback, post-commit integrity readback and search-index refresh stay outside the window. The trace verifies a caller fsync pair, and the observer verifies that the staging tree is absent after the commit returns. The original end-to-end timing includes observer overhead.

The model-free controls on the same runner and boot localize a 120 ms delay inside the cleanup and a separate 120 ms delay after it. They exercise the futex/fsync tracer and match the number of transaction entries and preimages in the selected model-free and native probes. The original idle probes determine the threshold. The existing host allowlist, locked inputs, network checks, observer bounds, original sequence and stop rules apply. Run that sequence once after admission. The comparison can establish the size of the cleanup window in the observed sample. The historical cause remains open.

## Capture transaction pool shutdown in S06 slot 5

The [staging cleanup comparison](https://github.com/gabned/provelume/actions/runs/43309733257/job/131502344920) remains NON_REPRODUCTION. This experiment observes only the successful acquisition pool shutdown in S06 slot 5, after publication of the entries and before writing the committed manifest. It measures the caller's wall time, thread CPU time and scheduler intervals. The kernel task trace binds each pool worker to a caller fork during the probe and records its exit separately. The report records the last exit relative to the shutdown return and whether the caller was blocked at that time. The index refresh remains separate.

The model-free controls localize a 120 ms delay inside the window and a separate delay outside it. They also exercise futex and fsync tracing. The model-free comparison on the same runner and boot must match the number of transaction entries, preimages and pool workers. The original idle probes alone determine the gate. The host allowlist, workload, locked inputs, trace bounds, network controls, deadlines and stop rules still apply. One original sequence may run after admission.

### Shutdown return and kernel exit are separate events

The [first admission attempt](https://github.com/gabned/provelume/actions/runs/43314088018/job/131517426823) stopped before model acquisition. The earlier check required kernel exits within the shutdown window. CPython 3.12 joins its thread-state lock, which may release the caller before the kernel records the native thread exit. The timer now stops at the original shutdown return, before writing the close marker. Verify the same workers' creation and exit separately using the complete task trace, classify exits relative to the return and the sample, and report the last exit with the reconciled clock bounds. The runner still needs to pass all controls before the one native sequence.

### Historical EPYC 9V45 profile

The [corrected pool shutdown observer](https://github.com/gabned/provelume/actions/runs/43315093534/job/131520894565) completed on EPYC 7763 without reproducing the S06 slot 5 exceedance. This next attempt accepts only the historical EPYC 9V45 CPU model with four logical CPUs. It reuses the corrected shutdown window, separate kernel exit evidence and same-runner model-free controls. It retains the original sequence, inputs, evaluator and observer bounds. The assigned GitHub-hosted runner is inspected once and a different profile stops admission before model acquisition.

### Capture entry publication on another EPYC profile

The [9V45-only attempt](https://github.com/gabned/provelume/actions/runs/43318737437/job/131533508161) stopped before model acquisition when GitHub assigned a 7763. This experiment admits an EPYC 7763 or 9V74 with four logical CPUs. It observes the acquisition's original `_publish_entries` call, including its verification, atomic moves, and wait for destination-directory fsyncs. The window closes on return from publication, before transaction pool shutdown and the committed manifest. Each expected destination-directory fsync must have a pair in the trace from a worker in the Capture pool. The separate index measurement remains available.

The same-runner model-free probe matches entry, preimage, and destination-directory counts. The controls retain the 120 ms delay inside and outside the window, traced synthetic futex/fsync, original Capture semantics, placement and network checks. The original sequence runs once after admission. Its own idle probes determine the Capture threshold with the unchanged evaluator.

### Destination-directory flush results

The [entry publication experiment](https://github.com/gabned/provelume/actions/runs/43321709404/job/131543750515) observed longer publication under native load without an S06 slot 5 exceedance. This experiment measures only the successive `flush.result()` calls inside the acquisition's `_publish_entries`. Each call is linked to the corresponding pool worker's kernel fsync pair. The outer marker bounds tracing to publication. The reported caller CPU, blocked and ready times are clipped to the individual waits. The trace records fsync completion relative to wait entry and return, including clock uncertainty.

The positive 120 ms control is inside the first measured wait. The negative control is after publication. The syscall, semantic, network, placement and matched transaction-shape controls still run without a model on the same runner. The accepted CPU profiles, observer limits and original evaluator are unchanged. Run one original native sequence after admission and observe only S06 slot 5.

### Destination path validation

The [directory flush comparison](https://github.com/gabned/provelume/actions/runs/43370253609/job/131704090332) observed no S06 slot 5 exceedance or increase in the waits under load. This experiment measures only the original `_instance_target` calls made directly by `_publish_entries` for the acquisition. The publication markers bound kernel tracing. The measured wall, caller CPU, blocked and ready times cover only the individual validations. The original directory fsync pairing remains checked across publication.

All controls and the native probe use the same instance root depth on the same runner. The matched model-free sample must also have the same destination path depths, entry, preimage and directory counts. The two 120 ms controls inject a delay inside or immediately after the first validation. The original workload, evaluator, inputs, trace bounds and stop rules apply. One native sequence may run after admission.

### Path validation during entry registration

This experiment measures the original `_instance_target` calls made by `AtomicInstanceCommit.add` when `_acquire_locked` registers entries for S06 slot 5. It binds the registering transaction to its subsequent commit. The individual timings end before commit begins. The enclosing trace also retains the publication fsync check. The search index is timed separately.

The paired model-free probe on the same runner and boot must match the instance root depth, all relative target depths and the entry, preimage and directory counts. Delay controls distinguish time inside the first lookup from time immediately after it. The original inputs, workload, controls, evaluator and bounds apply. Run one native sequence after admission.

Compare the calls and depth profile of registered entries independently of the manifest entries. Preparation skips already identical files. Check publication fsync pairs against the directories in the resulting manifest.

## Staging writer waits in submit and process

The [entry-registration attempt](https://github.com/gabned/provelume/actions/runs/43386419832/job/131755852243)
stopped on the host admission check. This experiment observes a different factor
on the original source: the interval from the first staging writer submission in
`AtomicInstanceCommit._prepare()` to the last original `write.result()` return.
It binds each future to the successful file fsync in its own writer thread.
The submit and acquisition commits have separate windows. Directory fsyncs after
the writer scope, the prepared manifest, publication, and pool shutdown are
outside the measured intervals. The complete search-index refresh stays separate.

Observe deterministic slot 1 and S06 slots 1, 2 and 5 in one original native
sequence. Model-free controls on the same boot and placement match Instance
depth, prior Capture count and staging write counts by kind. Report staged
byte counts, caller wall and CPU time, scheduler wait, and per-future fsync
timing. Use the same 120 ms inside/outside delay controls for each phase,
synthetic syscall control, original network and semantic checks, observer limits,
locked inputs, evaluator and deadlines. Only the original idle measurements
determine the Capture limit. Admit EPYC 7763, 9V74 or 9V45 with four logical CPUs.

If the combined window is shorter than a reproduced excess, it is insufficient
to explain that sample. Compatibility is diagnostic, and a within-limit result
is NON_REPRODUCTION. A diagnostic conclusion does not establish the cause of
any historical finding or qualify a candidate.

The [first staging attempt](https://github.com/gabned/provelume/actions/runs/43511793221/job/132183615512)
observed an Intel Xeon 6975P-C with four logical CPUs and stopped at the EPYC
selector. The follow-up selects that exact Xeon profile. The original hardware
check already ran on that profile. The Linux controls must still pass before
input acquisition, and the admission and native sequence must use the same
runner, boot and placement. The comparison applies to the observed Xeon host.
