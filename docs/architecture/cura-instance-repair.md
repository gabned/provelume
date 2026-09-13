# Explicit Instance state repair

`InstanceRepairManager` implements one unscheduled local repair:
`repair.maintenance_redundant_atomic_artifact`. It addresses a stranded file from
the existing atomic writer in `state/maintenance/reindex-runs`. A completed
reindex run can remain valid while a redundant `.reindex_<32hex>.json.<suffix>`
file makes deep Instance validation fail with `maintenance_record_invalid`.

The profile accepts exactly one regular, byte-identical temporary copy of its
existing completed run. The run, matching succeeded scheduler job and terminal
receipt must pass their existing validators and identity checks. The selected
finding must be the only deep validation error. A partial, different or newer
record, unsupported schema, live lease, link/reparse point, pending lifecycle,
retention or atomic transaction, unrelated invalidity or incomplete inventory
denies the operation. There is no inferred cursor, garbage collection or general
repair of unknown state.

## Preview and explicit confirmation

Construct the manager with `InstanceRepairManager(InstanceStore(registered_root))`.
Do not construct `ProvelumeInstance`, call `prepare`, scan a Source or create
directories to show recovery information for an invalid Instance. Root selection
belongs to the local registration/service boundary, never to a browser path.

`preview(profile, relative_path)` is pure. An eligible result exposes `plan_id`,
`input_revision`, `binding`, Instance ID, affected path/size/SHA-256, five context
records, the original validation finding/report, required/free bytes and the
external quarantine destination. The revision hashes the exact named evidence
and bounded run/job/receipt inventory; it is not an Instance content fingerprint.
The actual invalid report retains `content_fingerprint: null`. `unavailable`
contains a closed reason and never grants action authority. Space is observed,
not reserved, so later I/O failure remains possible.

The service retains the complete preview and calls
`prepare_backup(plan, request_id)` only through an explicit POST. This writes and
reopens a verified external capsule, returning `backup_id`, `archive_path`,
`archive_sha256`, `input_revision`, `scope` and `quarantine_path`.

The final, separate confirmation calls
`apply(backup_id, expected_revision, request_id, confirmed_backup_sha256, confirm=True)`.
The route must enforce its normal local-origin, CSRF and one-use confirmation
nonce checks, binding Instance, plan and verified capsule digest. Default
`confirm=False` rejects application. GET never creates a plan, capsule or lock.

`preview_rollback(receipt_id)` describes the exact inverse effect, and
`rollback(receipt_id, expected_revision, request_id, confirm=True)` requires a
separate confirmation. It restores the **known invalid** pre-repair state; it
does not claim to restore a healthy Instance. Changed context or an existing
destination blocks rollback without overwriting it.

## Recovery capsule and write set

The capsule is a distinct `provelume-state-repair-backup`, schema 1, scoped to
`one_file_write_set_and_read_only_context_not_full_instance`. Normal Instance
backup remains strict and still rejects this invalid Instance.

`.<instance>.provelume/repairs/<backup_id>/before.zip` contains exactly eight
entries: a manifest; `affected.bin`; five context copies (committed run, scheduler
job, terminal receipt, config, Instance manifest); and `validation.json`. The
manifest binds every exact safe locator, size and SHA-256, original invalid
report, Instance/root and plan revision. Verification reopens the archive,
checks every payload and the whole archive digest. It rejects duplicate or
case-colliding names, links, encrypted, traversal, unlisted and oversized entries.
No payload is extracted to a caller-selected path. Bounds are 8 MiB per file,
64 MiB per archive and per producer inventory, and 10,000 entries per inventory.
Deep inspection retains its existing complete validation contract.

The sole Instance mutation is a same-filesystem rename of the selected file to
`quarantine.bin` beside the capsule. Canonical records, Originals and derived
files are outside the write set. Context copies are never restored. Capsule,
quarantine and receipts are retained; no scheduled deletion is provided.

## Guards, durable outcomes and interruption

Mutations take the existing lifecycle guard first, then `SchedulerStore.hold`.
This matches the scheduler's lock order; no scheduler job is executed or recovered
by repair. Inputs, complete inventory, capsule and absence of a live lease are
rechecked under these guards. Contention is explicit and has no internal retry.
The existing guards can create/update operational lock files, which are a
documented effect outside the one-file data write set.

Before the rename the manager durably writes external `pending.json` with the
closed operation, capsule binding and proposed receipt. After exact source/target
position, unchanged context and deep postcondition verification, it durably
marks the transaction committed and writes its immutable receipt. File data are
flushed; directory fsync is performed where supported by Python (not Windows).
This is process-interruption recovery, not a promise against every storage failure.

An interrupted prepared apply restores the exact artifact and reports
`repair_failed_restored`, with invalid validation status. An interrupted prepared
rollback compensates back to the valid repaired position. A committed pending
record is finalized without repeating the rename. Unknown schema, altered hash,
changed context, conflicting destination or uncertain position retains pending
evidence and blocks ordinary mutation. Compensation never uses a whole-Instance
restore. Immediate failure and process interruption have distinct receipt error
codes. Replaying the same request returns the original receipt; it does not
reapply an old action after a subsequent rollback.

`InstanceLifecycleManager.prepare` and its ordinary mutation guard reconcile
pending repair first. Compensation and explicit rollback persist `blocked.json`
bound to the immutable invalid-state receipt. Later ordinary mutation remains
blocked while deep validation is invalid, including repeated open attempts.
Another explicit eligible repair may complete and clear this barrier. A valid
manual restoration may pass deep verification; historic receipts remain retained.
Preview and inspection remain read-only and available while mutation is blocked.

Receipts expose actual operation, request/Instance/plan/capsule identity, affected
hash, input/output revision, timestamp and resulting validation status. Statuses
distinguish `repaired`, `rolled_back_to_pre_repair_invalid_state`,
`repair_failed_restored` and `rollback_failed_compensated`. These are local
operation results, not release qualification or a blanket health certification.
