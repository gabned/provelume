# Cura maintenance interface

`/maintenance/overview` is the shared Current and Preview entry for operations,
maintenance jobs, schedules and local admission policy. Existing scheduler,
operation and maintenance evidence routes remain available. The bounded
`OperationsMaintenance` read model supplies the same facts to this page and
`/api/v1/maintenance/overview`; unavailable or partial history remains explicit.
GET requests do not prepare an Instance, recover work or acquire writer locks.

Job detail presents the recorded checkpoint, counts, known denominator and rate,
retry eligibility, recovery state and exact terminal receipt status. Control links
come from the executor's current capabilities. A preview is a separate step;
confirmation revalidates the selected job revision and checkpoint. A queued job
is not described as completed. Unsupported running executors expose no fictitious
pause, cancellation or restart control.

## Reviewed local mutations

All new mutation forms require the local browser, the fixed selected Instance ID,
a server CSRF token and a single-use nonce. The parser accepts only URL-encoded
forms with the exact expected single-valued fields, at most 16 fields and 8 KiB.
Final confirmation additionally requires the explicit confirmation checkbox.
Server-side reviewed plans have a 128-entry, 15-minute bound and an immutable
request ID. They are not durable jobs or authority queues. Expiration requires a
new preview; refresh does not execute an action.

Heavy maintenance previews bind the action, exact Source or Instance scope,
authority, input revision, observed count and bytes, and temporary disk estimate.
Unknown estimates remain unknown. Under the lifecycle guard, the service verifies
the reviewed plan before selecting or creating a scheduler policy and before
enqueueing the job. Changed inputs do not silently replace the user's preview.
The legacy `/maintenance` page retains the same reviewed-plan requirement through
its bounded one-use form context. Normal catalogue semantics and job owners are
unchanged.

Backup verification selects one absolute local archive, registers its private
durable locator, and previews its Instance, hash, size and bounded inventory. Final
confirmation queues the existing scheduler executor with the exact target
reference, target revision and plan revision. Verification never restores files.
Local path containment, pinned directory handles, archive replacement detection
and backup limits are owned by the maintenance backup service.

Diagnostic export first records an explicit content-free snapshot and private
output selection. It displays the selected destination, allowed categories,
coverage and estimated output size before confirmation writes the archive.
No upload occurs. Delivery receipts distinguish completed export from uncertain
completion; an uncertain outcome is not reported as success. Retained selections
and diagnostic previews remain visible after server restart at
`/maintenance/selections`. Revoking a selection or forgetting a preview requires
a separate exact-revision review and confirmation. These actions remove only the
selected metadata, never an exported file or archive. The preview warns that
revocation can block future work and forgetting removes local delivery history
and the corresponding retry capability.

The capacity form changes the Instance-bound host policy after review and CAS.
The displayed wait is the **last recorded wait**, not proof of current resource
pressure. S06 owns integrating this admission check at the intake effect boundary.
Changing the policy does not stop running jobs or delete data.

## Recovery before ordinary startup

`provelume serve <selected-root> --recovery` opens the minimal recovery
interface on the existing loopback server. The root is selected by the local CLI,
never supplied by an HTTP form. `create_recovery_app` uses `InstanceStore` without
ordinary Instance preparation, migration, scheduler startup or knowledge routes.
It cannot be combined with release-bundle startup verification options; recovery
does not imply qualification of a release bundle.

The only supported repair is the separately documented maintenance atomic-file
profile. Its pure preview identifies the exact one-file change and prerequisite
evidence. The first confirmation prepares and verifies the complete repair-write
set recovery backup; a second confirmation applies the bound repair. This backup
is explicitly not a full Instance backup. Unsupported paths, different content,
other validation findings, pending recovery, active writers and missing evidence
provide closed, actionable explanations rather than an automatic fallback.
Rollback requires its own preview and confirmation and explicitly states that it
restores the known invalid state. Lifecycle, scheduler, backup, repair receipts,
compensation and the persistent invalid-state barrier remain owned by their
existing modules.

After a crash and server restart, the recovery page observes any pending repair
without changing it. A dedicated preview binds the exact pending phase, verified
capsule and current file position/context. Confirmation rechecks that revision
under the existing guards, then either finalizes the already committed operation
or compensates the uncommitted change. The interface states whether this restores
the known invalid state or the repaired state. Existing transaction and receipt
identities are preserved; an unrelated newer pending transaction cannot replace
the reviewed operation. Missing or corrupt recovery evidence remains unavailable.

Source copy is supplied in English and Italian. Catalogue completeness and
automated checks do not constitute human linguistic review; S08 owns the governed
language workflow. Browser observation, native filesystem tests and automated
integration tests remain separate evidence categories. S09 retains integrated
native and accessibility qualification.
