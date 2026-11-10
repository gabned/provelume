# S23 Windows allocation observations, 10 November 2026

This PRODUCT correction updates two relative module weights. The allocator,
fallback, complete test membership, four workers, two runner groups, native
540-second deadline, ten-minute job cap and all checks remain unchanged.
Removing the `_MODULE_COST_HINTS` assignment makes the before/after Python AST
identical. No Protocol implementation, fixture, pin or workflow changes.

## Source and retained failure

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
