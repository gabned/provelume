# Agent Development Protocol 1.4.2

Protocol 1.4.2 adds operational evidence to the auditable continuation contract.
The canonical implementation is developed in Core campaign
[#200](https://github.com/gabned/provelume/issues/200). Distribution is complete
only after that campaign contains the verified five-repository closure receipt.
A branch, issue, preliminary merge SHA or passing unit test is not distribution.

## Compatibility and authority

Lifecycle remains 1.2; campaign and handoff retain schema 2, discriminated by
`protocol_version`. The 1.4.0 and 1.4.1 validators and historical receipts remain
unchanged. Use the validator matching the recorded version. The new validator
can migrate schema 1 deterministically; it does not relabel existing 1.4.1
receipts as 1.4.2 proof. Operational receipts add `operational_evidence` to their
hashed content. Initialization and schema migration set it to null.

The operational distribution envelope is `NO_PRODUCTION`. All earlier lifecycle,
review, trusted-base change control, exact-head CI, checkpoint and release gates
remain mandatory. Maxithlon retains `DEPLOYMENT_LEVEL_C`, BrickMS retains
`CODE_ONLY_PRODUCTION_B`, and the site retains `UPSTREAM_RELEASE_VERIFIED`.
The descriptive registry does not become a runtime vendor or an authority source.
This protocol distribution does not publish a product version, tag or release,
deploy anything, access credentials, change environments or create `AGENT_STATUS.md`.

Workflow classification: `KEEP_AND_HARDEN` for `.github/workflows/ci.yml`.
Existing checks, names, permissions and trusted-base execution remain; the
additional files receive executable-mode/offline checks and repository test coverage.

## Observation boundary

Evidence validation is offline and executes no commands. The synchronizer alone
reads local Git through fixed commands without a shell or network operation.
A JSON field saying `GITHUB_CONNECTOR` is
not authentication. The caller must collect complete observations through an
authorized connector, including pagination, actual PR and commit objects,
repository policy, CI attempts/jobs, review threads and maintainer identity.
Never synthesize missing observations from desired outcomes. Keep actual
snapshots under ignored `.agent/`; public tests use synthetic data only.

Current operations require observations within 15 minutes, with at most 30
seconds of clock skew. Historical campaign receipts validate their frozen
observations against their recorded PR observation time; replaying a historical
receipt does not authorize a new action. Every newly appended critical receipt
is checked against the current clock before its digest is generated.

## CI and waits

Workflow event identity includes repository, run ID, exact head and
`run_attempt`. Attempt histories start at 1 and are contiguous. A previous
terminal attempt cannot be rewritten or removed. All workflow-run and job
pages must be complete. The latest attempt of the latest observed run for each
applicable workflow must succeed; an older green cannot cover a new pending or
failed run. A retained failure followed by an explicitly observed success is
valid history; validation never launches a rerun.

Workflow identity includes its trigger, expressed as `workflow@event` in the
required set. In particular, successful `pull_request_target` scope checks cannot
replace failing `pull_request` candidate tests from the same workflow file.
The run retains its separate `workflow` and closed `event` fields.
GitHub-managed checks can report `dynamic` (for example Code Quality); retain
that observed trigger and workflow path with the same attempt/history gates.
Do not omit it from the CI inventory or relabel it as a repository workflow.

`validate-wait` accepts only a freshly observed live run and the exact connector
handle ending in `/actions/runs/{id}/attempts/{attempt}`. Its deadline is bounded
to one hour. Expiry requests observation of that same handle and makes no
campaign transition. Elapsed time is not failure, completion or authorization.
Polling and automatic retries remain disabled.

## PR identity, exceptions and merge

The PR snapshot carries exact repository, number, base, head, tree, complete
changed paths and patches. Its body must contain one matching `BASE_SHA`,
`HEAD_SHA`, `TREE_SHA` and `CHANGED_PATHS_COMPLETE: TRUE` declaration.
`render-pr-identity` replaces these declarations deterministically; it cannot
invent missing repository observations.

An authorized technical changelog exception binds the verified human maintainer,
authorization reference, PR, base/head, full path digest and exact patch digest.
The authorized patch must equal the observed patch and add exactly one technical
Protocol line to `CHANGELOG.md`. It cannot waive another gate or authorize
product edits. Frozen baseline paths cannot contain paths absent from the PR.

Authorization can come from an actual GitHub maintainer comment or an existing
explicit user instruction. The latter retains the authoritative goal's thread ID,
creation timestamp and verbatim instruction, using a `codex-goal:THREAD:CREATED_AT`
reference. This is a provenance identifier, not a web link or a fabricated GitHub
comment. The caller must verify that the instruction covers the proposed exception;
the receipt binds that existing authority to the exact current patch. It cannot
expand authority, waive gates or require a duplicate approval for work already
authorized. `authorization_source` is `GITHUB_COMMENT` or `USER_INSTRUCTION`.

Post-merge evidence requires observed merged/closed state, the actual merge
commit, accepted tree, squash or merge parents and ancestry from the current
default commit. A provisional GitHub merge SHA is insufficient. Applicable
post-merge CI must bind that observed default commit.
Its policy reference also binds that current default; an older policy cannot
omit checks added by the audited default. All latest observed applicable workflows
must succeed; the required set is a minimum inventory, not a waiver for other runs.

For Protocol campaigns, `GATES_PASSED` and `PR_MERGED` receipts require operational
evidence embedded in the receipt digest. The validator binds the evidence to
the retained PR/head and the exact workflow attempt or actual merge. Dropping
the evidence and recomputing the outer digest still fails validation.

## Late findings and closure

A late finding records both the original merged PR/build and a separately
reconciled corrective PR. A resolved label alone is insufficient: the observed
thread resolution must bind the original head and corrective head/merge.
The prior terminal ledger must be an exact prefix of the retained ledger;
the correction is appended, without reopening or replacing an old entry.

`generate-audit` validates exactly five repositories and emits a digest-bound
receipt accepted directly by `validate-audit`. Each repository supplies its
profile, default commit, actual integration evidence and applicable CI/reviews.
Open campaign PRs, unresolved findings, missing repositories, stale observations
and vendor drift block closure. The canonical source must be an audited Core
merge. Observed vendor bytes bind their default commits and must match the
canonical SHA-256, Git blob and mode. The registry supplies its locally selected
path, blob and final provenance; private paths/content are never fixtures in Core.
The registry path must be part of its actual integration, and its content must
identify all four executable repositories, final defaults and integration PRs.
Downstream generated manifest and provenance documents also require exact bytes,
Git blobs and modes observed at their respective default commits. Core has no
self-referential committed source manifest.

`generate-audit` enforces live freshness. `validate-audit` verifies the protected
digest and replays all nested observations against the receipt's original audit
time, so archived proof remains verifiable without refreshing its timestamps.
Generation also validates that original time anchor before emitting a receipt.
Historical validation never establishes current readiness or authorizes a new action.

## Offline synchronization

`sync-vendor SOURCE TARGET --commit COMMIT` copies the four explicitly listed
validator files and generates a manifest and provenance document. It performs
no network operation or product edit. `--check` reports drift without writes.
Symlink targets and paths outside the selected repository are rejected. The
source must be a clean Git root with the canonical Core origin and HEAD exactly
equal to COMMIT. Committed blobs and modes must match the source files; ignored
Git replacement objects cannot substitute content. The caller still verifies
that COMMIT is the intended public canonical merge through its authorized connector.
POSIX replacements apply and verify the declared permissions, and rollback
restores prior bytes and permissions. Mode-only drift fails `--check`. Windows
does not expose POSIX executable bits: the caller must stage and verify the
declared Git modes in the target index/tree before publication on every platform.
Git reads disable lazy fetching and all transports, including inherited transport
permissions; a missing promisor object fails locally without contacting a remote.

The new command interfaces are exposed by `tools/agent_protocol_v1_4_2.py`.
Operational input shapes and positive/adversarial examples are executable in
`tests/test_agent_protocol_v1_4_2_ops.py`. Repository CI runs these alongside the
unchanged earlier-protocol regressions and the full Core suite.
