# Windows allocation evidence, 7 November 2026

This PRODUCT qualification repair refreshes allocation data from a complete,
successful **accepted-main** execution. It does not change the test suite, native
CI budget, worker count, validator, publication permission or human qualification.
No failed/interrupted module supplies a measured cost. No workflow is rerun.

## Exact source and original artifacts

- Repository: `gabned/provelume`, ID `1343746770`.
- Accepted main: `1711f037b1467d84eb5e145466dad6a6171643fc`, tree
  `b3be5a42b3e209ab4646e4ce690edbf1b0b1b448`.
- Original push run [42119226225](https://github.com/gabned/provelume/actions/runs/42119226225),
  attempt 1, Public repository CI, terminal success.
- Recorded runtime: win32, CPython 3.12.10, hosted Windows runner. This is not a
  claim of the maintainer's Windows 11 Pro 25H2 manual matrix.
- Group 0 artifact `13458009048`: 4,358,553 bytes, ZIP SHA-256
  `12173b2be436e100e429b3915d25f80f74ead6ad747fbf396d58d011496b941b`.
- Group 1 artifact `13458500690`: 4,352,210 bytes, ZIP SHA-256
  `a2925446c2f367b74e6f52bbae6705269457b3820b979288427c6d89cc6e3b53`.

All fourteen members were independently CRC/read/hash verified. Both groups
record exit 0, no timeout, four complete child reports and the exact accepted-main
commit/tree/run/attempt identity. Their durations were 374.672 and 387.250 seconds
inside the unchanged 540-second bound. All four inventories agree; their selected
sets are disjoint and their union contains exactly the same 5,437 collected node
IDs. Parent tests, subtests, collection identities and source hashes remain in the
original reports; no reduced inventory is substituted.

The original child logs contain 254 complete, non-failing
`provelume-windows-module` observations. Each selected/completed count and all
setup/call/teardown outcomes are checked before use. Costs are rounded total
setup/call/teardown milliseconds, with a minimum allocation weight of one.
Missing observations and test-count changes still use the existing count fallback.
No interrupted candidate result is filled in, extrapolated or subtracted.

## Reason for the repair

The prior hints came from accepted main in October and covered 231 modules.
Concordia qualification has more collected modules and changed counts. For
example the October hint for `test_agent_protocol_consumer.py` contains six
tests; accepted main now collects sixty. That count mismatch falls back to
60,000 allocation units while the complete accepted-main measurement is 93,545
milliseconds. This stale weighting is independent of execution limits.

S12 candidate `0cf3089` separately preserved a Windows group-0 timeout at 540
seconds while its other group completed in 364.735 seconds. S14 also preserved
incomplete Windows coverage. Those failures remain failures; their interrupted
modules do not provide these refreshed weights. This change updates the prior
accepted-main data used by the existing deterministic greedy allocator. It does
not assert that the new candidate has passed Windows before its own execution.

## Gate inventory retained

`SHARD_COUNT`, all minimum/default/maximum timeout constants and the count fallback
are unchanged. Every collected module is still assigned intact to exactly one of
four workers. Native run/attempt/head/tree/source, complete parent/subtest coverage,
disjoint union, child failures, process-tree termination and final aggregation
checks are unchanged. No protected workflow or Agent Protocol source changes.

The existing allocation, module-timing and Windows orchestration tests exercise
the unchanged algorithms with these hints. Exact-candidate Ruff/full pytest/diff,
permanent Windows CI, reviews and ordinary main acceptance remain mandatory.
Historical passing test outcomes are never transferred between heads: only
relative allocation data is reused. These timings are neither execution budgets
nor a causal explanation of any CPU qualification result.

This repair does not accept S07–S15, close the CPU finding, resolve the independent
S15 public-provider write blocker, change 0.14.0/development identity or authorize
publication. Human manuals remain DEFERRED_BY_MAINTAINER / NOT_RUN until the
completed official release on the maintainer's existing Windows 11 Pro 25H2 PC.
