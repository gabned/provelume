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

The first immutable head `7ef4d22e67150d3b84d4d8fd9726862c0714bf06` produced
two actionable full-CI regressions: the missing AI job label in Operations and the
generic job-inventory fixture attempting to bypass governed AI admission. Both are
corrected without dropping the all-kinds assertion. A further controlled audit
reproduced enqueue/control/settlement writes during a restore lifecycle lock;
three regressions failed before the lock-order correction. The expanded synthetic
demo subsequently passed 58 cases. Reconciliation also retains explicit LOCAL or
PROVIDER provenance for new numeric facts, including duplicate-evidence checks.

The complete local Windows suite on that first head reached the unchanged canonical
540-second shard deadline (561.17 seconds including supervisor closure), exit 1.
Focused diagnostics reproduced the known restricted-host DPAPI credential-store
failure and backup verification/maintenance failure. Complete logs are retained;
this is not a local PASS and no security restriction or timeout is changed.

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

Native run [37191972291](https://github.com/gabned/provelume/actions/runs/37191972291)
on the first head measured all six governed jobs per host successfully, nine receipts,
both cancellations, next caller and final off. All 17 inherited S05 dimensions,
including independent network observation, passed. The added S06 gate **failed**:
maximum warm first output was **8.956 s on Linux / 7.844 s on Windows**, above
the unchanged **5 s** threshold. The governed S02 payload is larger than the S05
bounded factual corpus; successful execution does not waive its latency gate.
No sample is discarded, payload shortened, threshold raised or S05 PASS transferred.
The next corrected head requires its own full observation; integration stays blocked
while any mandatory gate fails. Exact-head outcomes and all attempts belong in PR #323.

On `8da33e31aa9bf8345e66fb8823809d5eecfcafd3`, independent full-suite
[CI 37193010041](https://github.com/gabned/provelume/actions/runs/37193010041)
passed (Linux 3453 passed/23 skipped; Windows 3386 passed/90 skipped).
The synthetic demo passed 58 tests. The local full Windows suite again reached
the canonical 540-second deadline (561.31 s including closure); the known host
DPAPI/protected-directory failures remain recorded rather than waived.
[Native run 37193010036](https://github.com/gabned/provelume/actions/runs/37193010036)
still failed: S06 warm first output max 6.622 s Linux/5.047 s Windows; Linux also
had a 2.846 s concurrent capture and a 5.833 s inherited S05 warm-first sample.
Both native profiles passed independent no-egress observation, cancellations,
cleanup, next caller and the nine-receipt checks. The
[complete ledger](https://github.com/gabned/provelume/pull/323#issuecomment-5978767470)
also records the separate trusted-base guard's HTTP 403 before validation. No
integration occurred and no existing failure is erased by subsequent runs.

### Latency/responsiveness follow-up

Profiling identified repeated S01/S02 context reconstruction at every 20 ms
supervision poll. The same owner now reuses only that pure computation within an
attempt, comparing all fresh authoritative inputs with a private deep copy.
Controlled concurrent tests invalidate reuse for in-place policy/consent changes,
Version, qualification and profile changes; controls, lease, deadline, strict route
types, adapter checkpoints and subsequent attempts retain independent checks.
`scripts/profile_ai_job_polling.py` measures five alternating before/after pairs
on the same synthetic host without removing current reads or journal locks.

Native numeric phase timings now distinguish adapter/model admission, polling,
worker prefill/generation and capture submit/process. Full S02 payload, locked
candidate/configuration, byte verification, containment and ADR 0031 thresholds
are unchanged. This optimization does not itself establish a native PASS: fresh
unchanged-head Windows/Linux observations belong in the sole PR ledger. The user
requested this follow-up before reconsidering integration; the owner remains draft.

## Gate state before final ledger

| Gate | Current declaration |
| --- | --- |
| Full native Windows/Linux suites and CI on exact head | 8da33e3 PASS in independent CI; latency follow-up needs fresh observation |
| Real governed Windows execution/no-egress | 8da33e3: latency FAIL, no-egress PASS; follow-up needs fresh measurement |
| Real governed Linux execution/no-egress | 8da33e3: latency/responsiveness FAIL, no-egress PASS; follow-up needs fresh measurement |
| Complete reviews, threads and technical findings | Pending final inventory |
| Integration and actual-main post-merge qualification | Not yet performed |
| Lifecycle v2 enrollment/signing/recovery | DEFERRED_BY_MAINTAINER; accepted PR-local legacy route |

No version/tag/publication, new model, remote provider, credential, paid service,
Protocol update or PC security change is authorized by this record.
