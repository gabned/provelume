# S02 Windows mutable JSON snapshot qualification

Corrective scope #359, parent #352/#349. The original owner #358 was normally
merged at `462adce92f0cc48cdb8c113c7d96ff1d07a97480`, but its actual-main Windows
HTTP synthesis test failed reading a scheduler job JSON with `PermissionError`.
The failure and aggregate remain retained; the slice is not accepted.

Mutable JSON readers open one read-only, non-inheritable Windows handle sharing
read, write and delete, so an existing DELETE-access handle does not exclude the
reader. The handle closes before UTF-8 decode and JSON parsing. Sharing alone does
not let the unchanged MoveFileEx writer replace an open destination: its bounded
denial remains visible, with complete publication after the reader closes.
Existing caller path/type/schema checks and genuine access,
missing-file and malformed-data errors remain; no stale cache, fallback, retry,
ACL change, mutation lock or timeout increase is introduced. Immutable model and
archive readers and the writer's existing rename budget remain unchanged.

Qualification must include real Windows negative controls: a held DELETE-access
handle conflicts with the preceding CRT reader, while the snapshot reader still
reads the complete JSON; the existing writer's denial during an open snapshot
preserves both files, and publication after close produces complete new bytes.
Mocked handle/descriptor failures must
propagate once and release ownership. Existing scheduler and HTTP idempotence,
preservation and lifecycle tests remain unchanged and mandatory.

These controls demonstrate a sharing-protocol defect and its correction; they do
not prove the exact historical host's denial cause. Full unchanged-candidate
native, every workflow/attempt/job/review, effect binding, fresh preflight, normal
expected-head merge and actual-main checks remain required. No old PASS transfers,
CI retry, native inference correction or release is authorized by this document.

The first corrective candidate's forced replacement-while-open test failed on
Windows with WinError 5. That failure is retained in #360. Its stronger expectation
was incorrect for the unchanged writer; it is now a fail-closed native control,
not a reason to change the writer API, access or deadline. The CRT/delete-sharing
negative control, concurrent complete-publication check and original HTTP test
remain. Microsoft documents the separate POSIX rename flag and existing-handle
restriction in [FILE_RENAME_INFORMATION](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information).
