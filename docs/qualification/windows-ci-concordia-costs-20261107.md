# Concordia Windows allocation data, 7 November 2026

This separate PRODUCT repair changes only the literal relative allocation hints
in `pytest_windows_shard.py`. Four workers, the 540-second deadline, fallback,
allocator, test inventory/outcomes, process cleanup, native coverage validators,
workflows and Protocol 1.5.2 remain unchanged. An AST comparison removes only the
hint literal and requires every other function/constant to be identical.

## Immutable source and limits of reuse

Original [Public CI run 42401998711](https://github.com/gabned/provelume/actions/runs/42401998711),
attempt 1, completed successfully on S16 candidate
`94696ba6aec19afa27e0539a1c02673b51f6a7f5`. The recorded PR test merge is
`b2fab829bbf22729d0bc492d766ce1239b7523d5`; its independently read GitHub commit
has parents main `fadeb47f84004d48b282046e36bb3081cd1d878b` and that candidate.
Both merge and candidate have tree `3b5f12d717fee212f594edbca415d515ce415fe7`.
The runtime is win32 / CPython 3.12.10 on a hosted Windows runner.

The source candidate is **not accepted**: its same-root restore replay defect was
subsequently demonstrated and corrected on S16 `1ef7bd9`. Complete native Windows
test execution is a source of relative timing observations only. Neither product
correctness nor passing tests/CI/review/installer evidence is inherited by this
repair, S16's corrected head, S17 or actual main. No result accepts S07's CPU
finding. This is not a Windows 11 Home/Pro 25H2 manual qualification.

## Original bytes and independent checks

- Group 0 artifact `13585952955`: 4,636,265 bytes; ZIP SHA-256
  `98f3c6c1ea719bbf006529a7bcc7fc0bd893815571641fc8fafc8f5446024654`.
- Group 1 artifact `13586680420`: 4,589,942 bytes; ZIP SHA-256
  `71492a5f7eff79c6d04b6622349ae44cd12bcbc68941162c9064e098c7adcd27`.

All fourteen original members were independently read, CRC/hash verified. The
unchanged native `verify_windows_reports` validator returned PASS for exact
commit/tree/run/attempt/event, all 5,755 collected node IDs, disjoint complete four
shards and 391 recorded native subtests. Both groups have exit 0 and no timeout;
durations 420.109 and 377.531 seconds remain inside 540 seconds. Original inventories,
node identities, outcomes and subtests are retained without reduction.

There are 269 unique complete, non-failing module timing records. Each measured
module's selected/completed counts match the original collection, every phase has
zero failures, and finite nonnegative setup/call/teardown totals are checked.
Weights use rounded total milliseconds with the existing minimum of one.
Five fully executed delegated modules have no complete timing observation and
retain the count fallback: `test_agent_protocol_transfer.py` (38),
`test_agent_protocol_v1_4_7.py` (63), `test_agent_protocol_v1_4_9.py` (14),
`test_agent_protocol_work_check.py` (36), `test_agent_protocol_work_recovery.py` (38).
New modules and changed test counts also retain that unchanged fallback.

## Reason for the change

The previous 254 hints came from accepted main `1711f03`, before S09–S16 connector,
write-deferral and mirror tests. The original source's allocation was independently
reconstructed from its full node catalog and matches every observed shard.
Its 269 measured module totals are 391.279 / 401.537 / 260.142 / 289.506 seconds.
The two runner pairs therefore hold 792.816 versus 549.648 seconds of measured
work. Offline application of the unchanged allocator to refreshed hints places
that same measured subset at 689.731 versus 652.734 seconds per runner pair.
These are assignments of historical observations, excluding unmeasured phases,
overhead and host variation; they are not a prediction or new execution PASS.

Original S15 `aef710d` run 42401462777 and corrected S16 `1ef7bd9` run 42405887005
remain CANCELLED/incomplete after their Windows group-0 540-second timeouts.
Their interrupted results supply no timing hints. No workflow or concluded CPU
experiment is rerun, no limit is raised, and no observer cost is subtracted.

The new candidate still requires its own native full checks, permanent exact-head
Windows CI/review, ordinary expected-head merge and actual-main verification.
The original accepted-main repair remains in [its qualification record](windows-ci-20261107.md).
The [explicit read-only S15 decision](https://github.com/gabned/provelume/issues/383#issuecomment-6711131611)
remains separate. Application identity stays 0.14.0/development; no release or
installation on the maintainer PC is performed. Human checks remain
DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official release.
