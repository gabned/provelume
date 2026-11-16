# Closed Git exception context in Gitea qualification

On source `5feb0590419ff2698c1fa523e93917559a0c3d0c`, the original
[Windows group 0](https://github.com/gabned/provelume/actions/runs/43033609515/job/130566619025),
[group 1](https://github.com/gabned/provelume/actions/runs/43033609515/job/130566618736)
and [native aggregator](https://github.com/gabned/provelume/actions/runs/43033609515/job/130572222118)
all succeed in attempt 1. The unchanged native verifier reports 6,050 node IDs,
four complete disjoint shards and 391 subtests for test merge
`49e1bab4ec632e02a47e0a02d16c213081342629`, whose tree equals that source.
Group durations are 502 and 593 seconds, inside the unchanged ten-minute limit.
The original Gitea module passes all 32 cases; the original contained SSH worker
test passes. These results do not transfer to a new commit.

The same source's
[standalone installed OCR job](https://github.com/gabned/provelume/actions/runs/43033609194/job/130566616015)
fails in `gitea-server-qualify` with exit 2 / `git_unavailable` / `UNKNOWN`.
All eight recorded fixture preparation commands return zero. Unlike the earlier
E342 interruption failure, this diagnostic does not identify an interrupted
publication. The OS cause is **NOT_DEMONSTRATED**. Forty subsequent local
invocations of the unchanged synthetic qualifier pass and do not reproduce it.

`GitSession.run` already retains the original exception as `__context__` when
it maps an OS/subprocess failure to `git_unavailable`. The optional Gitea failure
evidence now reads that existing context through bounded traversal. It emits
only an allowlisted operation, recognized code sites, a closed exception kind
and bounded integer `errno`/`winerror`. It never emits messages, paths, command
arguments, subprocess output, or raw credential values. Unknown operations and
numeric fields remain `OTHER`/null. Private interruption wrapping retains this
context too. Successful qualification reports remain unchanged.

Twelve regressions exercise actual and synthetic wrapper paths, interruption
wrapping, missing-file/sharing failures, subprocess failures and unexpected
attribute types. Before the change they fail because context is absent; after
the change they pass with the original error codes and UNKNOWN result intact.
The complete qualifier AST is identical after removing only the added optional
diagnostic statements. Git/Windows process execution, SSH, original native
tests, all deadlines, retry behavior, predicates, matrix and pinned workflows
are byte unchanged from the source above.

This repairs loss of diagnostic evidence; it does not claim to repair the
underlying installed OS failure. A new exact-source automatic qualification is
required. Independent Actions artifact verification remains
BLOCKED_BY_MAINTAINER / NOT_WAIVED. Original S23/S07 seals, findings and every
previous result remain in force; no publication, intermediate maintainer-PC
installation, waiver, or Protocol adoption is authorized.
