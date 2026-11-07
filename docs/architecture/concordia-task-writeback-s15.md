# Concordia S15 guarded task writes and provider blocker

This PRODUCT candidate consumes exact S14 under the
[ordered development/testing authorization](https://github.com/gabned/provelume/issues/383#issuecomment-6706150974).
It implements the guard, confirmation, recovery and synthetic automatic contract.
**Public-provider task write-back is NOT_QUALIFIED and S15 is NOT_ACCEPTED.** The
observed Tududi public profile cannot satisfy its promised atomic condition; Asana
has no proved public conditional primitive. Neither is silently removed from the
[approved L scope](concordia-step-0.md). S07 and all predecessor gates remain open.

## Closed operation and authority

Only completion and due date on an existing Source-attributed Task are accepted.
Title, body, assignee, creation, deletion, calendar changes and email sending are
refused before provider dispatch. Due date supports clearing, date-only and exact
zoned instants. Explicit local day/time/zone input uses shipped timezone data;
ambiguous or missing DST offsets fail rather than being guessed.

Write consent is distinct from read consent and is scoped to identity, Source,
allowed fields and device/Instance location. Imported consent cannot authorize
writes at another root. Changing consent creates an immutable revision before its
active pointer is published. A current complete Source observation, exact local
object digest, current read authority and external credential epoch are required.
No imported capability JSON or synthetic PASS can enable a public provider.
The default runtime has no qualified public write adapter.

An explicit preview reads the current remote state, retains only the selected
before/after fields and binds its exact strong remote revision. A mismatched
acquired observation requires a fresh Source read. A preview expires after fifteen
minutes; all changes must be reviewed and confirmed separately. Passive views,
reloads and navigation never read credentials or contact a provider. The page is
linked from read-only acquired Tasks; their existing manual-edit refusal remains.
Controls require loopback, bounded forms, CSRF, closed fields and exact revisions.
Seven governed language catalogues distinguish unavailable capabilities,
confirmation, conflict, not-applied, confirmed and unknown outcomes. Human and
linguistic review remain separate from automatic qualification.

Under the lifecycle/connector guard, a single durable Source record claims the
confirmed operation before any remote call. This is the dispatch linearization
point. The guard is released before HTTP; revocation cannot undo an operation
already dispatched. Double submits, restarts and interrupted calls never send that
operation again. A Source with an uncertain operation blocks new writes.

The transport must perform an actual atomic remote compare-and-set on the exact
revision. A client GET followed by an unconditional PATCH/PUT cannot implement
this contract. A conflict preserves the newer remote state without compensation.
No rollback ever writes a previous value over a later remote revision.

Timeout or malformed/uncertain response remains UNKNOWN. Recovery calls only a
read-only operation-receipt query. Coincidentally matching current field values,
or reading the old state while a request might still run, proves neither application
nor non-application. Missing terminal proof stays UNKNOWN. Audit receipts retain
operation identity, outcome, field names and hashes, without raw task title,
description, provider item ID, due values or credentials. A confirmed write does
not fabricate a manual canonical edit: an independent ordinary Source read
acquires the new attributed observation.

## Qualification boundary

`task_writeback_qualification.py` supplies a closed network-free synthetic CAS
adapter, available only through the explicit qualification injection seam and its
exact synthetic provider/adapter profile. Normal application requests cannot
activate it. Native tests cover independent/both fields, stale local/remote state,
wrong Source/account authority, confirmation/replay, before/after-send uncertainty,
process interruption, revoke before/after dispatch, read-only operation recovery,
private receipts, portable consent separation and actual seven-language HTTP
preview/confirmation. Public Asana/Tududi remain refused even after synthetic PASS.

`--ocr-command task-writeback-qualify <fresh-target>` executes native Core services,
single dispatch/replay, uncertain receipt recovery, independent Source reread and
offline portable reconstruction in the installed executable. Its report explicitly
retains `public_provider_writeback: NOT_QUALIFIED` and `release_gate: BLOCKED`.
The permanent installed offline Windows job invokes it. Browser productivity
cells render real unavailable-provider controls and the retained synthetic diff
in both modes, seven languages and two widths. Automatic rendering does not
constitute human acceptance or a live-provider PASS.

Real-account writes remain NOT_RUN without their specific authorization. All
manuals remain DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official release
on the maintainer's Windows 11 Pro 25H2 PC. No intermediate personal installation
occurs. Identity remains 0.14.0/development and this work does not publish.

## Original public Tududi conditional proof

The permanent driver `scripts/qualify_tududi_conditional.js` has no remote target
argument. It refuses to run outside its exact dedicated synthetic database,
test environment and checked public route bytes. Driver SHA-256:
`65a283e5f1c7adfc9aaeb56c9c30b1456f4de0230d977c463b379288a3cf84bb`.
This is external public-provider capability evidence, not Core candidate CI.

The provider source is the untouched stable Tududi v2.1.0 commit
`e03bc361bc7fa49a475fca9952b345822d1d5f11`. The reviewed/executed task route file
has SHA-256 `0ddd89797d4c89e0968aadc7d6876f857f98452ece78f0a3dafc0b6ec8ce6782`.
Its root package lock is 868,989 bytes, SHA-256
`262dcc7f658417a4d2c07b2468ba28371583311fe72c82c0c5c09ed3b535c75c`.
The disposable image uses locked production dependencies without install scripts;
image ID `sha256:66e0738c0df7cda3ce5b7785a6118f6294b4da0e1fa3fda130b6c443aaf20502`.
Node was v22.23.4; PostgreSQL 16.15 used image digest
`sha256:5264710be20f409750ac6dc4e5706dcef929c87e241605463f0f9aefa932a8d9`.

Before admission the database had zero public tables; Docker independently
reported the dedicated network as internal. Neither container published ports
or mounted host credential directories or the workspace. Only the owned driver file
was mounted read-only. The fixture created one synthetic user/token/task in its
dedicated temporary database. No real account or remote destination was contacted.
Each HTTP request had a fixed 15-second deadline, with a fixed 180-second driver
deadline and 240-second supervisor. No condition, payload or bound changed during
the admitted proof.

The predeclared assertion was that a syntactically valid, certainly nonmatching
strong `If-Match` must prevent overwriting a newer due date. Sequence:

1. GET existing synthetic task: due date 7 November 2026, HTTP 200.
2. Another actor PATCHes only due date to 9 November: HTTP 200, readback 9 November.
3. The stale caller PATCHes only due date to 8 November with
   `If-Match: "concordia-predeclared-never-matching"`.
4. Expected HTTP 412 and retained 9 November. Actual **HTTP 200 and 8 November**.
   An independent final SQL read also returned one task, due date 8 November.

Result: **CONDITIONAL_PRIMITIVE_FAIL**. The server exposes an ETag but its PATCH
handler ignores this precondition. Public source independently shows an
unconditional `task.update(taskAttributes)` without an exact revision predicate.
The admitted proof is concluded and is not retried for a favorable result.

The original admitted log is 1,592 bytes, SHA-256
`69969ebb94a6a7bcd0b6d3e5a6dcc8e2b2bdb4ce2c19db703bb34cb2a7d581d5`.
Extracted report is 1,063 bytes, SHA-256
`34d45f1ef3671c716fd1b6dc35926d6689b2a078c6dce712ae74a74e1cb7bcea`.
Earlier preparation failures are retained separately: buildx first attempted a
read-only host cache directory, then used a writable workspace cache without
changing Docker credentials/proxy/CA; an initial container entry could not read
the public driver before Node loaded it (NOT_RUN, no API requests). After fixing
that file permission the fresh-database precondition was checked. No inference
or S07 diagnostic was dispatched. The owned database/container/network were
removed after evidence collection; public source/build/proof receipts are retained.

Asana's independently reviewed public OpenAPI commit
`e5c7dec74dcea63207156a7cc96d06f82075a1d3` documents no task-update conditional
revision parameter. No real Asana write probe was authorized or executed. Its
capability remains NOT_PROVEN, rather than being inferred from the Tududi result.

## Concrete product decision and impact

The approved L rule says a missing promised provider capability is a release
blocker requiring an explicit scope decision; it cannot be closed by this
synthetic guard PASS. The alternatives are:

- **Keep the full approved promise:** retain S15/release blocked until stable
  public atomic primitives and independently qualified provider behavior exist.
  Current read-only connectors and independent development remain available.
- **Explicitly defer unsupported task writes for Concordia:** retain read-only
  Asana/Tududi and the guard, but amend L/manifest/user documentation openly.
  This is a scope reduction requiring the maintainer's decision, not an automatic
  acceptance or a claimed completed live S15.
- **Authorize a separately versioned server capability:** for self-hosted Tududi,
  add and qualify a real server-side conditional update in a separately scoped
  workstream. A GET/PATCH proxy is insufficient. It requires a new supported
  server profile and exact deployment authorization; Asana still needs its own
  independent solution or explicit deferral.

Until an explicit decision changes that scope, the first alternative remains in
force. No permission is inferred to alter a provider deployment, issue remote
writes, weaken exact-revision safety or publish Concordia. S16–S23 development
authorization remains separate from these outstanding acceptance/release gates.
