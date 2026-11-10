# S23 Windows allocation observations, 10 November 2026

This PRODUCT correction refreshes relative weights for 290 measured modules,
including five previously unobservable native-subtest modules.
The allocator,
fallback, complete test membership, four workers, two runner groups, native
540-second deadline, ten-minute job cap and all checks remain unchanged.
The data-only predecessor has identical Python AST after removing the hint
assignment. A subsequent observer correction recognizes native subtest reports
for timing completeness, as detailed below. Allocation, execution, native CI
recorder/verifier, Protocol implementation, fixtures, pin and workflows are unchanged.

## Completed native-subtest measurements

The corrected observer runs on source
`74b76b041885456d3c1264442ee44aac68d12e79`,
[42862418198/a1](https://github.com/gabned/provelume/actions/runs/42862418198).
Group 1 [129991771447](https://github.com/gabned/provelume/actions/runs/42862418198/job/129991771447)
succeeds. Group 0 [129991771089](https://github.com/gabned/provelume/actions/runs/42862418198/job/129991771089)
retains CANCELLED and the aggregator remains blocked. Every record below is
complete, has the exact selected/completed parent count, and has no failed phase.
No interrupted module supplies a cost:

| Module | Parents | Previous count fallback (ms) | Observed total (ms) / new rounded weight |
| --- | ---: | ---: | ---: |
| `test_agent_protocol_transfer.py` | 38 | 38,000 | 56,061.9328 / 56,062 |
| `test_agent_protocol_v1_4_7.py` | 63 | 63,000 | 473.1313 / 473 |
| `test_agent_protocol_v1_4_9.py` | 14 | 14,000 | 1,886.5470 / 1,887 |
| `test_agent_protocol_work_check.py` | 36 | 36,000 | 7,076.7102 / 7,077 |
| `test_agent_protocol_work_recovery.py` | 38 | 38,000 | 70,010.2503 / 70,010 |

The changed timing-test module also has a complete three-parent record,
2,511 ms rounded, replacing its count-mismatched fallback. The other 284 existing
weights remain unchanged. All values are observed setup/call/teardown totals;
no multiplication, timeout change or cost for missing work is introduced.

Both independent collections contain 6,017 distinct raw node IDs with identical
module counts. Some volatile parameter display labels differ, so byte equality
of raw labels is not claimed. Allocation uses only the matching module counts;
the unchanged native descriptor-based CI verifier retains responsibility for
actual case identity, disjointness and full coverage. Independent artifact
verification is still blocked, not replaced by this log analysis.

The 271 eligible complete module records in these logs are replayed as the same
measured subset: 500.851 / 476.144 / 329.734 / 275.378 seconds before, and
430.943 / 403.997 / 382.064 / 365.102 seconds with the six data updates. This
excludes interrupted/unstarted work and is not a total-runtime prediction.

The new subprocess regression also runs on pytest 8.4.2: its skipped subtest is
reported as a skipped outer call there, while pytest 9 reports a passed parent
with native child reports. Both explicit behaviors are asserted; the failed
fixture still exits 1 in both versions. Product development continues to use
the runtime declared in `pyproject.toml`.

## Native subtest timing completeness

Source `715a9c91eb40e4faa95e7be967b14e48a7b30bac` retains a group-1 timeout
in [129979291836](https://github.com/gabned/provelume/actions/runs/42858833101/job/129979291836).
Shard 2 ends at 83%, while shard 3 completes in 476.63 seconds. Group 0
[129979292536](https://github.com/gabned/provelume/actions/runs/42858833101/job/129979292536)
succeeds. This is not a full timeout resolution or a qualified Windows run.

Five native-subtest modules have no eligible timing record, so they retain the
count fallback: `test_agent_protocol_transfer.py`, `test_agent_protocol_v1_4_7.py`,
`test_agent_protocol_v1_4_9.py`, `test_agent_protocol_work_check.py`, and
`test_agent_protocol_work_recovery.py`. The transfer module (38 parent tests)
is assigned to the interrupted shard. These missing costs are not imputed.

The timing observer treated legitimate `_pytest.subtests` reports as duplicate
parent call phases, invalidating the whole module's timing. The native CI
recorder already distinguishes these reports and remains unchanged. The observer
now recognizes the same exact report types, using only the outer call duration
(which includes its children), so subtests are not counted twice. A failed,
unexpected or nonfinite child still invalidates the module's cost. Normal pytest
results and all native parent/subtest outcome and coverage controls remain intact.

A real subprocess regression includes a successful parent with passed/skipped
subtests and a parent with a failed subtest. It fails on the old observer
(identical at `28ed865` and `715a9c9`), passes on the correction, retains process
exit 1 for the failing fixture, and emits an eligible cost only for the successful
module. Older pytest's outer-call failure behavior is also retained. Existing
failure, interruption, targeted invocation and process cleanup checks remain.

This fixes missing diagnostic data, not the underlying Protocol fixtures or
execution deadline. A fresh ordinary Windows execution must supply complete
measurements before any additional allocation correction; this source is not
declared timeout-resolved merely because its observer is repaired.

## Source and retained failure

The final data source is the complete four-shard execution of
[42855973908/a1](https://github.com/gabned/provelume/actions/runs/42855973908),
source `eca220c91da649a4d5867e2874d1128b73f6aa9a`, test merge
`702ed6eb2ad0bfa65c90f99b9fe81a74510d47cf` with ordered parents main
`2918c3968168e426986bd8fcd7d485f102c11f7b` and that source, matching tree
`9e5e77c4d5197398feb42f9bd55d2a102faae042`.

All four shard executions finish successfully (322.55 / 341.22 / 506.38 /
465.21 seconds), with 6,016 distinct collected node IDs. The decoded logs supply
285 complete non-failing module records. Each has matching selected/completed
counts and no failed phase; no interrupted record supplies a weight. Existing
weights for unmeasured modules and the original count fallback are preserved.

[Group 0 / 129968966573](https://github.com/gabned/provelume/actions/runs/42855973908/job/129968966573)
succeeds. [Group 1 / 129968966904](https://github.com/gabned/provelume/actions/runs/42855973908/job/129968966904)
retains GitHub conclusion CANCELLED. Its test step succeeds in the native bound,
artifact upload succeeds, and cleanup ends at 16:46:34 UTC after job start
16:36:30 UTC; the original annotation reports the unchanged 10m0s cap. No step
or job outcome is renamed to override this refusal. The aggregator remains
blocked; complete native test execution alone does not qualify that run.

Replaying this complete measured work with the unchanged allocator gives:

| Shard | Two-weight allocation measured subtotal (s) | Refreshed data subtotal (s) |
| --- | ---: | ---: |
| 0 | 271.173 | 373.283 |
| 1 | 285.489 | 389.280 |
| 2 | 502.104 | 387.280 |
| 3 | 453.357 | 362.281 |

The largest measured subtotal falls by 112.825 seconds. This is a replay of
the same measured work, not a prediction across different hosts or a claim
that allocation alone explains all historical wall-clock variation. Source,
native gates, full Windows execution, aggregator and all other workflows must
be qualified again on the refreshed head. No execution budget changes.

Artifact metadata only (no independent download): group 0 ID `13784305495`,
4,837,197 bytes, SHA-256
`e9c87c8807679c2fad71c591fab68acc9077607f59e043c2ef805aa0800c6965`;
group 1 ID `13782034844`, 4,817,285 bytes, SHA-256
`81fba241863e73a8ca830a1a5a75f2d5ebb3162bc48c814e6e3ce25357755fb2`.

## Preserved initial two-weight correction

[Run 42852003038, attempt 1](https://github.com/gabned/provelume/actions/runs/42852003038)
executes source `30113f09875829da7dff78adb4f8f3fea3d8a84b`. GitHub test merge
`6ac296c6d1bf633a41c6c0026a5748f3943ac67b` has ordered parents main
`2918c3968168e426986bd8fcd7d485f102c11f7b` and that source; its tree equals
the candidate tree `10d4b140c4e60398b28f06a0ee912c5026ba84f4`.

[Group 0, job 129954903048](https://github.com/gabned/provelume/actions/runs/42852003038/job/129954903048)
remains CANCELLED at the ten-minute cap. Its test step fails at the unchanged
native deadline; shard 0 ends during portable-transfer tests, while shard 1
completes in 502.42 seconds. This preserves the earlier `28ed865` cancellation
[128776896656](https://github.com/gabned/provelume/actions/runs/42495494320/job/128776896656).
Reusing the immutable Windows snapshot API binding removed redundant setup but
did not resolve the timeout. Neither cancellation is called a deadlock.

[Group 1, job 129954902269](https://github.com/gabned/provelume/actions/runs/42852003038/job/129954902269)
succeeds; its two shards complete in 426.39 and 377.57 seconds.

## Two completed observations

Decoded original GitHub job logs contain the independent collection of 6,016
distinct node IDs and 262 complete, non-failing module timing records. Each used
record has `complete=true`, matching selected/completed counts and zero failed
setup/call/teardown phases. Both selected records belong to shard 0:

| Module | Tests | Previous weight | Observed setup + call + teardown |
| --- | ---: | ---: | ---: |
| `tests/test_agent_protocol_v1_2.py` | 15 | 121,588 ms | 158,551.1144 ms |
| `tests/test_concordia_integrated_s23.py` | 1 | 1,000 ms count fallback | 56,309.7021 ms |

The new weights are the rounded observed milliseconds, with no multiplier or
changed budget. The interrupted portable module and unstarted modules supply
no new weight. All other historical weights remain unchanged. A Protocol test
module's observed execution weight is PRODUCT allocation data; it does not
adopt the separate, unaccepted Protocol PR #463 or change its fixtures.

Replaying the unchanged allocator on the same 6,016 actual node IDs assigns
the same measured subset as follows:

| Shard | Previous measured subtotal (s) | Updated measured subtotal (s) |
| --- | ---: | ---: |
| 0 | 440.886 | 392.224 |
| 1 | 478.468 | 425.545 |
| 2 | 341.225 | 424.862 |
| 3 | 373.099 | 391.047 |

The largest measured subtotal decreases by 52.924 seconds. These are observations
of the same completed work under two assignments, not a prediction of total
execution time. Missing module phases, collection, cleanup, reporting and host
variation remain outside these totals. Complete disjoint coverage remains
mandatory on the new head, including the previously interrupted work.

## Evidence limits and qualification

Only decoded job logs and authenticated source/merge metadata were read here.
The maintainer's independent Actions artifact verification block remains in
force. Group 0 artifact metadata is retained: ID `13781153319`, 3,344,001 bytes,
SHA-256 `e6ea17d6a70894826e3da82fe3e6cf484ce39324e81772b9ad21c60d0de67936`;
its bytes were not downloaded or independently verified. No artifact-qualified
PASS follows from this allocation replay.

The new head needs its own complete native suite and permanent Windows execution
with the unchanged aggregator. Source `30113f0` native 6,029 PASS / 67 SKIP /
419 subtests and browser 42 PASS remain historical observations of that source.
All older failures, findings and BIND receipts remain unchanged. S07 experiments
are not redispatched; normal CPU qualification cannot close original findings.
No merge, publication, intermediate PC installation or release identity change
is authorized by these observations. Manual checks remain deferred / NOT_RUN.
