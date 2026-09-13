# Operations, maintenance and local capacity admission

`OperationsMaintenance` projects the existing scheduler journals without opening,
preparing, recovering or running an Instance. Its public interfaces are
`snapshot(limit=100, offset=0)` and `job(job_id)`. Neither takes a writer lock nor
creates directories. Producer job kinds come from `SCHEDULER_JOB_KINDS`, including
backup verification and every intake executor; the view does not invent a second
job catalogue or scheduler.

## Complete and partial observations

The reader inventories policies, jobs, receipts and local Source identities with
10,000 entries per directory, 4 MiB per record and 64 MiB read budget per directory.
It rejects links/reparse points, nonregular entries, unexpected filenames and
records that fail their existing scheduler validator. Source reads establish
local membership from bounded identity records; they do not open external Sources
or claim deep validation of the full canonical domain.

Each opened file is compared against real device/inode/size/mtime identity before
and after reading. Windows inventory uses `Path.lstat`: cached `DirEntry.stat`
does not supply the same device/inode values as an opened NTFS descriptor. A final
bracket across all directories detects changes that occur while another journal
is being read. Instance identity is checked again at completion. No GET recovery,
scan, acquire, enqueue, receipt synthesis or archive verification is performed.

Coverage explicitly returns complete, partial or unavailable; observed valid
records remain distinct from unknown totals. Corrupt, unreadable, oversized,
foreign or changed evidence never becomes an empty complete result. Pagination
does not change coverage. A detail uses one bounded collection, including a job
beyond the first page; a missing job in incomplete evidence is unavailable rather
than a proved absence. Snapshot revisions bind validated records and coverage,
without adding the polling timestamp to that semantic revision.

Jobs retain their producer state and recovery state. `display_state=completed`
describes a producer's succeeded status; a verified terminal receipt additionally
requires the owner's exact job/receipt comparison and a stable complete job and
receipt inventory. Missing or mismatched proof has `terminal_receipt=null`,
`terminal_receipt_status=unavailable` and unknown `last_success_at`. Policy and
kind histories expose their own completeness. `last_attempt_at` comes from actual
attempts, never `last_evaluated_at`; successful time comes from matching terminal
evidence. No review, provenance or execution result is inferred from scheduling.

Public lease redaction remains owned by `public_job_record`. Progress uses the
cheap `public_control_progress` projection of recorded observations, counters and
checkpoints; listing does not calculate executor capabilities or read a referenced
backup. These views are observations, never reusable authority for a later action.
The scheduler's normal guarded command preflight remains the action boundary.

## Instance-bound host policy

`CapacityAdmission` stores `capacity-admission.json` under the external
`.<instance>.provelume` host control directory. It is private host-local policy
bound to the selected Instance ID, outside portable Instance content. Copying it
to a different Instance is rejected. `status()` is a pure read. A missing policy
means revision zero and explicit `observe_only`; malformed or JSON-null existing
policy is unavailable, not a default policy.

The closed schema validates types, modes, bounds, timezone-aware timestamps,
chronology and a contiguous receipt sequence. Current revision equals the receipt
count and current mode equals the last receipt; each request digest binds its mode
and prior revision. Duplicate request IDs/JSON fields and unsupported schemas are
rejected. The whole file is bounded to 64 KiB and 128 retained receipts; full
history is explicit and is never silently trimmed.

`configure(mode, expected_revision=..., request_id=...)` takes the lifecycle guard,
checks CAS and records the exact request receipt atomically with policy state.
The same request/binding returns its original receipt; a reused key with different
inputs is a conflict. A replay is historical acknowledgement, not a claim that an
old mode is still current. Status provides the current mode and revision.
Clock reversal against the latest persisted receipt/wait blocks a new write.

The modes are:

- `observe_only`: explicitly permits the check without a capacity guarantee; no
  resource scan or free-space claim is invented.
- `paused`: denies new intake with `manual_pause`.
- `pause_on_critical`: uses current validated thresholds and current filesystem
  capacity. An Instance metadata-size scan occurs only if a size threshold is
  active. With no configured critical threshold, malformed/unknown settings,
  unreadable capacity, overflow or observation drift, it denies with
  `capacity_unavailable`.

## Current admission observation, not a permit

`check_admission(required_bytes=0, record_wait=False)` validates an integer byte
requirement in the existing signed-64-bit range. It observes live free space and,
when needed, current Instance size. It never reads an old resource snapshot as an
admission guarantee. Threshold settings are bracketed and policy is read again
before returning; policy drift raises an explicit conflict.

For critical checks, `observation.free_bytes` and `instance_bytes` describe current
observed quantities, with `instance_bytes=null` when not measured. The threshold
evaluation concerns projected size/free space after `required_bytes` and exposes
`projected_free_bytes`, `projected_instance_bytes` and
`evaluation_scope=projected_after_required_bytes`. Impossible byte requirements
are denied even if an optional warning threshold is absent. Observation and
threshold revisions remain separate from the admission policy revision.

With `record_wait=True`, the lifecycle guard serializes the check and any
persisted wait update. A denial records its reason, actual observation time,
required bytes and current policy revision. A subsequent persisted allowed check
or policy change clears that last wait. Plain GET does neither. `last_wait` means
**last recorded wait**, not a live capacity assertion, running-job state or full
history; `last_wait_is_live_capacity=false` makes that limit explicit.

Every result declares `reusable_permit=false`. S06 owns calling admission at its
serialized intake effect boundary; this S04 API alone neither integrates that
consumer nor reserves space. Resource changes after observation remain possible.
No admission mode deletes content, stops running work, schedules cleanup or
modifies canonical records. Host policy writes and lifecycle lock metadata are
the only changes made here.
