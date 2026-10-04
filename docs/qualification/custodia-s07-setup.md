# Custodia S07 qualification

Owner issue #324; branch `product/0.12-s07-ai-privacy`; parent #311 remains open.
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
| S07 synthetic HTTP/consent/controls | 18 PASS in the targeted native Windows run, 21.94s; not a full-suite result |
| Full native Windows/Linux suite | NOT_RUN on final exact head |
| S07 real governed Windows/Linux test | NOT_RUN on final exact head; separate native observer gate added |
| S01–S06, SSRF, lifecycle regression suite | NOT_RUN on final exact head |
| Seven catalog keys and rendered pages | Initial Settings/Operations cases passed; expanded surfaces pending |
| Keyboard/focus, mobile/zoom, System/Light/Dark screenshots | NOT_RUN |
| Manual screen reader | NOT_RUN; DOM assertions cannot substitute |
| Sensitive copy review | Pending |
| Exact-head CI and complete review/thread/finding inventory | NOT_RUN |
| Ordinary integration and actual-main qualification | NOT_RUN |

No external live provider, paid account, real credential, personal content or
existing LAN service is used. Native model evidence is limited to the unchanged
S05 candidate. No Recommended promotion, version change, publication or successor
slice follows from this record.
