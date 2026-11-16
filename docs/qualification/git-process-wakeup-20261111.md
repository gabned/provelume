# Bounded Git process wakeup, 11 November 2026

On `ae3dd91526f33eb39f395d8ef79fd35bf8c0b267`, both Windows runner jobs retain
CANCELLED10m and aggregator130520779414 remains BLOCKED:
[group0](https://github.com/gabned/provelume/actions/runs/43018414649/job/130515209309),
[group1](https://github.com/gabned/provelume/actions/runs/43018414649/job/130515209370).
Their four native shards report all tests PASS in507.60/506.17/483.97/501.98s;
all32 Gitea cases and the original contained SSH-worker test pass. Native output
and successful evidence uploads never override cancelled runner jobs. The prior
Gitea return2 cause and exclusive attribution of the earlier SSH failure remain
NOT_DEMONSTRATED. Earlier source-specific outcomes stay in the existing records.

`GitSession.run` checked its child and bounds, then always slept10ms. A child
finishing during that sleep could not wake the monitor. The synthetic Gitea
qualification uses185 Git commands, so that otherwise idle latency accumulates
through real operations. The monitor now waits on child completion for at most
the same10ms. CPython Popen supplies that wait on POSIX; the already contained
Windows process uses its existing owned handle and WaitForSingleObject. Exit
wakes the monitor immediately; timeout continues the original monitor loop;
unexpected native wait results still fail closed. No child or command is retried.

The [Win32 contract](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)
distinguishes process-signaled, timeout and failed waits. The existing command30s,
operation120s, output/input/storage bounds, 250ms storage-check cadence, child
environment, credentials, return-code/final-output checks and process/descendant
containment are unchanged. Windows creation-time Job, poll and close/accounting
methods remain identical; the bounded wait method is the only addition. The
monitor AST is identical after replacing the new bounded wait with its old sleep.
Tests retain the final output-limit refusal even when exit wakes the monitor.

On this local host, five rounds of30 short native Git commands have median0.329s
before and0.107s after. A fresh synthetic Gitea qualification with the same185
commands and successful qualification predicates takes3.018s before and1.451s
after. Full samples, reports and source hashes are retained in the local R10
observation. The after measurement uses the modified worktree; it is a local
diagnostic observation, not a CI prediction or exact-head qualification. It does
not establish an exclusive cloud-host cause and is not an S07 experiment.

No test, matrix, worker count, budget, gate, native recorder/verifier, Protocol
pin/source or workflow changes. New exact-head native and automatic installer CI
remain required. The snapshot Ubuntu preparation outage remains separate.
Independent Actions artifact verification stays BLOCKED_BY_MAINTAINER/NOT_WAIVED:
decoded job logs and authenticated metadata only; no Actions ZIP downloaded.
All R4–R9, original BIND S07 and findings remain unchanged. No merge, publication,
intermediate PC installation or human-test substitution follows.
