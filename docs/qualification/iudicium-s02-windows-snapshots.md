# S02 Windows mutable JSON snapshot qualification

Corrective scope #359, parent #352/#349. The original owner #358 was normally
merged at `462adce92f0cc48cdb8c113c7d96ff1d07a97480`, but its actual-main Windows
HTTP synthesis test failed reading a scheduler job JSON with `PermissionError`.
The failure and aggregate remain retained; the slice is not accepted.

Mutable JSON readers open one read-only, non-inheritable Windows handle sharing
read, write and delete. Atomic publication may replace the directory entry while
the reader finishes the complete old file. The handle closes before UTF-8 decode
and JSON parsing. Existing caller path/type/schema checks and genuine access,
missing-file and malformed-data errors remain; no stale cache, fallback, retry,
ACL change, mutation lock or timeout increase is introduced. Immutable model and
archive readers and the writer's existing rename budget remain unchanged.

Qualification must include real Windows negative controls: a held DELETE-access
handle conflicts with the preceding CRT reader, while the snapshot reader still
reads the complete JSON; replacement during an open snapshot retains complete
old bytes and publishes complete new bytes. Mocked handle/descriptor failures must
propagate once and release ownership. Existing scheduler and HTTP idempotence,
preservation and lifecycle tests remain unchanged and mandatory.

These controls demonstrate a sharing-protocol defect and its correction; they do
not prove the exact historical host's denial cause. Full unchanged-candidate
native, every workflow/attempt/job/review, effect binding, fresh preflight, normal
expected-head merge and actual-main checks remain required. No old PASS transfers,
CI retry, native inference correction or release is authorized by this document.
