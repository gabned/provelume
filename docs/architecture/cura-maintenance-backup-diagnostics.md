# Cura maintenance: selected backups and reviewed diagnostics

S04 implements C15/C16 foundations through the existing Instance, lifecycle and
scheduler authorities. These modules do not create a second maintenance queue.
Repair and its recovery backup are owned by the separate repair implementation;
a valid archive alone does not authorize repair or restore.

## Explicit local targets

`LocalTargetRegistry(store)` in `maintenance_targets.py` accepts an absolute local
path only through `register_archive(path)` or `register_output(path)`. The caller
owns the explicit local selection, Instance selection, CSRF/nonce and consent.
There is no implicit latest archive, upload, download or remote provider.

The immutable public descriptor contains `target_ref`, `target_revision`,
`instance_id`, `purpose` and `created_at`; archive descriptors also contain
`archive_sha256` and `size_bytes`. Purposes are closed to `backup_read` and
`diagnostic_write`. Random references are never reused. The revision binds the
public descriptor and private locator/identity. It is a stale-input digest, not
an authentication credential or cryptographic signature.

Locators live under the lifecycle sibling control directory's
`maintenance-targets/registry.json`, outside the Instance backup payload. They
never appear in scheduler plans, public receipts or diagnostic archives. This
is host metadata, not portable authority: transferring an Instance requires
explicit selection on that host. POSIX files use mode 0600 and new directories
0700; Windows uses inherited host ACLs. This is not an encryption or universal
owner-only ACL claim.

`status()` is a pure bounded public inventory, including the capacity of 64.
`revoke(target_ref, expected_revision)` deletes only locator metadata. Existing
jobs referencing it then fail closed; no selected file is deleted. Capacity
has explicit recovery and no silent pruning.

`maintenance_local_files.py` rejects relative, URL, UNC/device, Windows alternate
stream and reserved-name selections. Windows drive classification rejects remote
and unknown drives; every parent and leaf is opened with reparse-point checks.
Directory handles deny rename/deletion, and archive handles deny writers and
deletion. Linux classifies the longest mount from local kernel mount information,
rejects remote/unknown filesystems, and uses directory descriptors with no-follow
opens. Other platforms return `target_locality_unknown`.

These checks do not claim protection against an administrator replacing kernel
mounts, equivalent privileged intervention, or every filesystem's durability
behavior. Unsupported secure file operations fail; there is no network fallback.
Registration binds the file identity and full SHA256. Verification reopens that
identity and checks the same handle before and after reading. Output selection
binds the parent identity; publication uses an exclusive hard link from an owned,
flushed temporary file, never overwriting an existing destination.

## Backup verification and scheduler contract

`BackupVerificationService(store).plan(parameters)` accepts exactly
`{target_ref, target_revision}`. The closed immutable plan contains:

```
schema_version: 1
kind: maintenance.backup_verify
instance_id, target_ref, target_revision, archive_sha256, size_bytes,
backup_id, instance_schema_version, content_fingerprint, files, plan_revision
```

Planning checks ZIP/manifest structure and exact archive identity, but does not
claim payload verification. Foreign Instance archives and absent/invalid content
fingerprints cannot satisfy this Instance-scoped action. `verify(plan)` resolves
again, hashes every payload using the existing strict archive verifier and returns
only `status: verified`, the Instance/backup identity, schema, fingerprint, file
count, archive hash/size and `verified_at`. It neither extracts nor mutates the
archive or Instance. Scheduler owns the actual job and terminal receipt.

The new `inspect_backup_stream(stream, verify_payload=False)` adapter in
`instance_backup.py` uses an already-open stream. The existing `verify_backup(path)`
facade retains its output and verification semantics. Existing archive entry,
manifest, individual-file and total-size limits remain unchanged. Normal backup
creation still requires a valid Instance; repair does not weaken this boundary.
Lock order is caller lifecycle authority, then target metadata. These services
never acquire scheduler authority from inside the target lock.

## Diagnostic review, export and recovery

`DiagnosticExportService(store).preview(categories=None)` selects only `build`,
`resources`, `scheduler`, `maintenance`, `operations_summary`. It persists the
already-redacted canonical JSON snapshot and returns its reference/revision,
Instance, selected/omitted categories, member count, exact estimated ZIP bytes,
coverage and observation time. It does not export a file.

Build projection contains only a validated version and commit. Resource counts
come from the existing validated resource-history producer and its existing
bounds; the original resource observation time and snapshot digest are retained.
The diagnostic collection time does not renew that observation. Categories are
separate observations, not an atomic cross-producer transaction.
Scheduler jobs, reindex runs and operation records use their validators;
journal projections inspect at most 100 entries and include only closed status
counts. Counts are observations, not claims about unseen entries. Absent,
unreadable, corrupt and truncated producers retain unavailable/partial coverage.
The current reindex-run producer is reused; diagnostics do not invent a generic
maintenance run authority.

No document text, Original bytes, title, path, filename, query, URL, account,
credential, arbitrary operation kind, message, error, related field or event is
serialized. Unknown states become `other`; malformed records count as invalid.
Redaction schema validation runs again before export, rejecting additional fields
even if private snapshot bytes and their digest were altered together.

`export(plan_ref, expected_revision, target_ref, expected_target_revision,
confirm=True, request_key=...)` requires literal confirmation and writes the exact
reviewed snapshot. Later producer changes never update those reviewed bytes.
The deterministic ZIP has fixed member names/timestamps and a manifest with
member hash/size, Instance, redaction schema, observation time and omissions.
The archive is explicitly not a restorable backup; maximum output is 8 MiB.

Private export metadata records a prepared intent before publication and the
receipt afterward. A completed request replay returns its original receipt.
Interrupted publication/receipt cannot be one atomic filesystem transaction:
replay of a prepared request returns `export_outcome_uncertain`, never success
or an automatic overwrite. The operator can inspect the selected destination,
select a new output and make an explicit new request. No file is automatically
deleted as recovery. Receipts record the historical export, not continuing
existence or immutability of an externally selected output file.

`status()` exposes bounded plans and receipt states without creating state, so
recovery remains reachable after restart. Eight plans and eight request records
per plan are retained. `forget(plan_ref, expected_revision, confirm=True)` removes
only valid plan/receipt metadata, never exported archives. Invalid metadata is
reported explicitly and is not silently discarded or treated as an empty store.

## Verification scope

Focused tests cover archive restart/replacement/foreign identity, payload damage,
real process lock contention, handle mutation, Windows junction/device rejection,
output-parent replacement, redaction sentinels, exact reviewed snapshot replay,
interrupted receipts, bounded metadata recovery and pure recovery status reads.
Existing lifecycle/backup tests exercise the preserved facade and strict limits.
Synthetic tests establish these boundaries; integrated FULL, packaged execution,
UI observation and release qualification remain separate evidence owned by the
campaign integrator.
