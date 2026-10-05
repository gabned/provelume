# Custodia S07 qualification

Owner issue #324; PR #325; branch `product/0.12-s07-ai-privacy`; parent #311 remains open.
Status: implementation and qualification in progress, not integrated.

Accepted baseline main: `cace42aaa1744f6b0012c2a0264b1dec8f660234`.
Protocol 1.5.0: `7287e2c3c6dd42d1aad1c7eac3c68043f8a0cf69`, 97 verified files.
Development follows CLI/PRODUCT PR-local legacy, PRODUCT/v2 repository policy;
Lifecycle v2 is DEFERRED_BY_MAINTAINER. Host model/effort: UNKNOWN/UNKNOWN.

S06 is integrated and qualified in
[its final ledger](https://github.com/gabned/provelume/pull/323#issuecomment-5982834212).
Its local 540-second timeout, exit124 and 65 observed failed nodes remain historical
FAIL. Not all historical traces were classified. Those observations are not S07
results, nor grounds to reopen the completed predecessor.

## Local observations

Python 3.12.14 and Node 24.16.0 were observed. Canonical bootstrap completed without
tracked dependency changes. The first targeted Windows run had 9 passed/7 failed:
all seven failed at protected-parent opening, before the new configuration could
be read. An ordinary-process retry hit the previous pytest temporary directory's
permissions (16 setup errors); no ACL, DPAPI or sandbox changes were made.

With fresh isolated temporary/cache directories, 15 cases passed and one executable
fixture failed. The first fixture lacked a defensible zero-cost quote; after that
correction its result did not match the closed S06 result envelope. Both fixture
defects were corrected without weakening production validation. Subsequent results
must be recorded against their actual candidate; these failures remain failures.

## Required evidence matrix

| Gate | Current recorded outcome |
| --- | --- |
| Full Ruff and diff whitespace | PASS on working implementation; repeat exact head |
| S07 synthetic HTTP/consent/controls and S06 process demonstration | Latest follow-up: 116 PASS, 141.21s, native Windows; not a full-suite result. Initial 18 and intermediate 113 PASS retained. |
| Full native Windows/Linux suite | Initial exact-head public CI PASS; local full runs FAIL as recorded below; follow-up exact head pending |
| S07 real governed Windows/Linux test | Initial Linux PASS / Windows FAIL; `1e12e99` PASS all 19 gates on both hosts; later UI corrections require their own exact-head CI |
| S01–S06, SSRF, lifecycle regression suite | NOT_RUN on final exact head |
| Seven catalog keys and rendered pages | Initial Settings/Operations cases passed; expanded surfaces pending |
| Keyboard/focus, mobile/zoom, System/Light/Dark screenshots | Partial historical Settings observations retained in the [visual matrix](custodia-s07/visual-matrix.md); final-head browser gate BLOCKED |
| Manual screen reader | NOT_RUN; DOM assertions cannot substitute |
| Sensitive copy review | Author review recorded in visual matrix; independent linguistic review NOT_RUN |
| Exact-head CI and complete review/thread/finding inventory | Initial head: 12 successful workflows, one failed native-runtime workflow; no submitted reviews or inline threads observed on resume. Final inventory pending. |
| Ordinary integration and actual-main qualification | NOT_RUN |

No external live provider, paid account, real credential, personal content or
existing LAN service is used. Native model evidence is limited to the unchanged
S05 candidate. No Recommended promotion, version change, publication or successor
slice follows from this record.

## Initial exact head and resumed qualification

Initial head `537376dfc239cadd51ca7ada81f5d4d10c983e32` retains its original
[owner binding](https://github.com/gabned/provelume/pull/325#issuecomment-5988899061).
The binding is not recreated for follow-up commits. Baseline main remains `cace42a`.

The first full local run completed all four shard processes in 529.67 seconds,
exit 1. Its invocation incorrectly passed Windows backslashes through pytest's
environment argument parsing and shared one base temporary directory across the
shards. Observed traces include overlong paths, missing files and scheduler records;
not every traceback is classified. Log SHA-256:
`60247466d4b3f393b70d66202eda265207120e1de05957c423da76fa75628910`.

The resumed local run removed that override and supplied a fresh temporary root,
leaving shard allocation, the 540-second deadline and process cleanup solely to the
canonical supervisor. It returned exit 124, with supervisor duration 542.50 seconds
including cleanup, wrapper duration 545.578 seconds. This is FAIL, not a completed
suite. Ruff and whitespace passed. Log SHA-256:
`43a8406a5968fd7bc5992ae74c91dfdc87b2bafb7ef06ce407f4d0314323ffe2`.
The source tree included only the uncommitted warm-measurement correction relative
to initial head during that run; HEAD stability alone is not exact-tree identity.
No ACL, DPAPI, sandbox, test selection or timeout was changed.

Initial-head independent public CI passed. The
[native measurement run](https://github.com/gabned/provelume/actions/runs/37269584797)
passed all 19 gates on Linux. Windows passed all inherited 18 S05/S06 gates,
including observed network isolation, but failed `s07_setup`: cold first/total
9.858/16.468 seconds; purported warm first/total 8.047/13.797 seconds. Both samples
reported zero reused input tokens. The warm first-result limit remains 5 seconds.

The S07 harness had unnecessarily rerun self-test and activation between cold and
warm user tests, replacing the native prefix. The follow-up performs setup once,
then two separately previewed/consented jobs in the same session. It additionally
requires observed worker activity throughout the concurrent capture/search probe,
the original ADR relative latency bounds, cold load bound and actual warm prefix
reuse. This correction and stronger evidence checks require fresh native runs;
the earlier Linux PASS and Windows FAIL are not rewritten or transferred.

The first expanded synthetic demonstration recorded 98 PASS / 8 FAIL. One new
fixture constructed an invalid template identifier/partialness pair; seven tried
to extract a form from a correctly blocked preview that exposed no consent form.
Both fixture mistakes were corrected without changing production authority rules.
The successful successor run is recorded in the owner ledger against its commit.

## Follow-up measurements on 1e12e99

Exact head `1e12e993cae7e39271e368fd2ffed3b4055b082f` passed independent full
Windows/Linux CI and all 19 native observer gates in
[run 37279663170](https://github.com/gabned/provelume/actions/runs/37279663170).
The stronger S07 checks passed without relaxing ADR thresholds:

| Native host | Cold first / total (s) | Warm first / total (s) | Warm prefix reused | Concurrent capture maximum (s) |
| --- | --- | --- | --- | --- |
| Windows 2025 | 9.625 / 15.516 | 3.469 / 9.094 | 175 tokens | 0.391 |
| Ubuntu 24.04 | 10.839 / 19.069 | 3.635 / 12.365 | 175 tokens | 0.525 |

Both samples on each host observed the live worker throughout capture/search and
passed matched-idle relative limits. Network observation passed independently.
These are the observed CI profiles, not a laptop or live external-provider claim.

The local exact-head full run used a new short temporary root and still returned
canonical exit124/540s (supervisor with cleanup: 542.58s). Before interruption,
2477 passed, 99 skipped and 29 failed nodes were observed; no complete-suite total
is claimed. This does not establish a common cause for the failed nodes. Log hash:
`d6f0dbf22b0bc884cbd882209c8df6fd5fa9a7f35669a040a7b48cdfdb67a031`.
The accepted independent native CI route remains necessary; no timeout increase,
security modification or identical local rerun is used to manufacture a pass.

The final UI follow-up restricts dispatch visibility to a currently valid session
and synthetic preflight, cancellation to lifecycle operations with actual cancel
support, and verification to present model files. The server retains every check.
External destination, current budget and accounting are visible in the private
preview without DNS, credential or network activity. The expanded demonstration
passes 116 tests; final-head CI/review observations remain in the same owner PR.
