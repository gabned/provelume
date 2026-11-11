# Windows/Gitea qualification and completion metadata, 11 November 2026

PRODUCT owner remains #460 / concordia-s23-integrated-qualification. The
Protocol pin/source and its separate #463 are unchanged. Independent Actions
artifact verification remains BLOCKED_BY_MAINTAINER / NOT_WAIVED; no artifact
ZIP is downloaded by this continuation.

On `cafb32a`, Windows group 1
[130435228499](https://github.com/gabned/provelume/actions/runs/42994543356/job/130435228499)
retains its failed Gitea source/frozen-operator test and ten-minute cancellation.
Its CLI returned 2, but the assertion did not retain the result JSON. The original
cause remains NOT_DEMONSTRATED.

`001156773779796e6700c03625a3b6dd6a0db0c8` fixes that loss of diagnostic context.
Closed phases and recognized error codes exclude exception messages, paths,
credentials and raw subprocess output. Existing error codes, failure exit 2,
successful output and all qualification predicates remain intact; only diagnostic
annotations are added to the original qualifier/native-vault body. The new
failure-context regression fails on the previous source, then passes with the
correction. Full local native6035 PASS/67 SKIP/419 subtests in674.99s, Ruff and
browser42 PASS belong to that source only.

Windows group 0
[130480372944](https://github.com/gabned/provelume/actions/runs/43008044374/job/130480372944)
reports all32 Gitea cases PASS, including the operator and diagnostic/privacy
regressions. The earlier return2 was not reproduced; this observation does not
retroactively establish its cause. Group 1
[130480373068](https://github.com/gabned/provelume/actions/runs/43008044374/job/130480373068)
fails a different existing test: the contained SSH-agent session has no valid
completion proof at parent exit. Its original failure remains separate. The
Protocol workspace also retains preparation HTTP503 from the pinned Ubuntu
snapshot, before native tests; no pin, URL or budget is changed to bypass it.

## Reproducible atomic completion-report defect

The worker flushes and fsyncs metadata to a private temporary file, then renames
it atomically. On Windows, a reader may temporarily deny deletion while that
file is inspected. A single Win32 sharing/lock violation (32 or33) previously
aborted publication: the prepared metadata remained in `.tmp`, the final report
was absent, and the worker returned2. Controlled injection reproduces this exact
loss of completion evidence. It does not establish that this was the exclusive
cause of the observed CI incident; the original worker did not report its error.

Publication now retries only the prepared metadata rename for those two Win32
errors. It remains inside the parent's existing one-second completion window and
the existing protocol deadline. It never retries signing, reissues credentials,
deletes/recreates the destination, accepts a partial report or treats an error as
success. Other permission errors and expired deadlines still fail closed.
Parent admission/completion, the30-second worker limit, IPC restrictions, private
DACL, one host-bound signature, seed/file inspection and containment checks are
unchanged. The parent still requires the same full report before accepting a
session. Transient-fault, permanent-failure and late-recovery regressions retain
these controls; uncontended first publication keeps its original behavior, with
no new limit on a successful first write. The original native IPC/cleanup test
remains unchanged.

No test, fixture, matrix, worker, allocator or gate is removed or reduced; native
540s/job10m, Ubuntu15m and workspace20m stay unchanged. Complete exact-head native
CI and automatic installer qualification remain mandatory. Earlier PASS and FAIL
outcomes, R4–R9, BIND S07 and original findings remain unchanged. Ordinary CPU
qualification cannot dispose of those findings, and S07 experiments are not
redispatched. No merge, release, publication or intermediate PC installation.
