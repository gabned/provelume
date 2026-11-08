# Concordia Windows allocation observations, 8 November 2026

This separate PRODUCT repair refreshes only the literal module allocation hints
from a complete original execution. Four workers, two runner groups, the
540-second native limit, ten-minute workflow limit, fallback, allocator, coverage,
cleanup and every test remain unchanged. Removing only the hint literal makes
the before/after Python AST identical. Protocol 1.5.2 is unchanged.

## Source identity and independent verification

Original [Public CI 42450759217](https://github.com/gabned/provelume/actions/runs/42450759217),
attempt 1, ran S22 source `7afb64111900d671a881443ba1810d6743d26201`.
GitHub independently reports test merge `8db470a497e9e287f6de6da125e8a7c84641e2e2`
with ordered parents main `9c6d89c035e009e342d2c6d5c9ed3081fbcb77e8` and that
source. Its tree equals the source tree `6653f8bc7e3252e6f870ba2dc5dfda066c08fc4b`.
Native runtime: win32 / CPython 3.12.10.

Both original artifacts were independently downloaded, CRC checked and hashed:

- Group 0, artifact 13605867154, 4,796,162 bytes, SHA-256
  `349ff4a9c367bfc42decba1676a0fae297a647bbe6e5ad72903bd10e52493872`.
- Group 1, artifact 13606190976, 4,766,090 bytes, SHA-256
  `5fe962265a9e5466dff5880744695e9e3a8b4c9ea024ed1fe8a3a779db28d7f8`.

All fourteen members were read. The unchanged native `verify_windows_reports`
returned PASS for source/tree/run/attempt/event, 5,960 node IDs, four complete,
disjoint shards and 391 native subtests. Group durations are 471.829 and 426.875
seconds; both exit 0 without timeout. All 278 timing records are complete with
matching selected/completed counts and no failed phase. Unmeasured modules, new
modules and count mismatches retain the existing count fallback.

This source is **not accepted**: its separate installed Windows rsync gate failed.
The timing observations provide allocation weights only. No product, native,
CI, installed, review or acceptance PASS transfers to this repair or any other
candidate. S07 CPU findings remain independently blocking.

## Observed allocation effect and retained failure

The complete source's measured module totals under its original allocation are
387.430 / 310.049 / 405.983 / 348.533 seconds. Replaying the unchanged allocator
with refreshed rounded-millisecond hints places that same measured work at
372.248 / 374.249 / 358.246 / 347.252 seconds. The largest measured shard total
falls from 405.983 to 374.249 seconds. Runner-pair totals change from
697.479 / 754.516 to 746.497 / 705.498 seconds. These exclude unmeasured phases,
collection, setup, cleanup and host variation; they are not execution predictions.

S20 `d3c0903`, run 42446236576/job 128625644515, remains CANCELLED/incomplete.
GitHub's original check annotation explicitly states that the job exceeded
10m0s. The retained artifact has collection plus incomplete shard logs and no
final group/shard receipts. No timing from that interrupted execution is used.
The annotation identifies the outer deadline; incomplete data does not prove
an additional internal timeout or a specific historical resource cause.

This candidate still requires exact native checks, permanent CI, review, normal
expected-head integration and actual-main verification. It grants no exception,
release permission, model-acquisition retry or CPU experiment redispatch.
Identity remains 0.14.0/development. Human methods remain
DEFERRED_BY_MAINTAINER / NOT_RUN; no intermediate installation on the maintainer PC.
