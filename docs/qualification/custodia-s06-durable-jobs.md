# Custodia S06 qualification record

Slice [#322](https://github.com/gabned/provelume/issues/322), parent #311, after
integrated S01–S05. The sole owner PR ledger binds final source, tree, CI history,
review/finding inventory, merge and actual-main checks. This file does not declare
an unobserved PASS. Candidate implementation is under qualification.

## Scope and reproducible evidence

The [contract](../architecture/ai-durable-jobs.md) and [ADR 0032](../adr/0032-durable-ai-jobs.md)
cover the same scheduler's reservations/lease, current authority, cancellation,
attempts, ordered pre-send fallback, unknown outcome and portable accounting.
`python scripts/demonstrate_ai_jobs.py` executes the public synthetic scenarios,
including spawn barriers and seven real process-death boundaries. Complete logs and
JUnit evidence are retained in `.agent/` and final exact-head evidence in the owner.

Early development probes found and corrected: sampling the claim clock before lock
acquisition; process-start duration leaking into a ten-second synthetic authorization
window; unrecognized scheduler control files preventing backup/export; preserving
backoff across pause; recording reconciliation evidence; quote/current-cap changes
between reservation and dispatch; and preventing lifecycle locking for the duration
of AI inference. Failed probes remain in the owner history, not relabeled PASS.

The initial synthetic demonstration passed 44 scenarios; the later expanded run passed
55, including concurrent capture/restore, restart grants and stale callbacks. Ruff and
diff checks passed. These local results precede native real-inference qualification;
that intermediate result is not exact-head qualification. Full native and final
synthetic results must be observed on the final unchanged candidate.

## Native candidate boundary

The model/runtime, lock, licenses, configuration and ADR 0031 thresholds are unchanged.
The native workflow preserves the complete S05 protocol and adds real S06 scheduler/
gateway runs, three cold/three warm generic execution measurements, token accounting,
load/generation cancellation, worker cleanup and next caller. All worker PIDs join
the existing Linux strace or Windows WFP observation. S06 has its own mandatory gate;
the S05 ledger is not substituted for measuring this changed boundary.

Windows requires the independently verified CI-only WFP rule for the exact worker
interpreter. This code does not install such a control on the user's PC. The restricted
local Windows host, a minimum 8 GiB laptop and the frozen app remain NOT_RUN for real
S06 inference until measured. Native CI profiles are reported separately. External
transport tests are synthetic only; real remote provider qualification is NOT_RUN.
S09 retains Recommended promotion and S08 retains synthesis-quality acceptance.

## Gate state before final ledger

| Gate | Current declaration |
| --- | --- |
| Full native Windows/Linux suites and CI on exact head | Pending observation |
| Real governed Windows execution/no-egress | NOT_RUN until native report |
| Real governed Linux execution/no-egress | NOT_RUN until native report |
| Complete reviews, threads and technical findings | Pending final inventory |
| Integration and actual-main post-merge qualification | Not yet performed |
| Lifecycle v2 enrollment/signing/recovery | DEFERRED_BY_MAINTAINER; accepted PR-local legacy route |

No version/tag/publication, new model, remote provider, credential, paid service,
Protocol update or PC security change is authorized by this record.
