# Win32 local-file API setup reuse

Corrective workstream #367, prerequisite to still-open diagnostic #365 / owner
#366, then #363 and S03 #361 / existing owner #362, under campaign #349. This
document defines scope and qualification; it does not accept a candidate.

The current diagnostic source51b605f3c5452d6a0e20f07d56d5fe4f3b75e18f retains
Installed39015123200attempt1/job117345544902FAILURE: second self-test60641ms,
self_test_final_verification, nine preceding checksPASS. Explicit parent kill is
not reached, timing is missing and its final three lifecycle gates are unqualified.
That phase does not distinguish final verification cost from budget already spent.
The different actual-main37f6ae host measured49298ms in6863livecheckpoints versus
343msACL; these measurements cannot be attributed to the newer host. Neither
observation establishes its narrower timeout cause or reopens independent #348.

The local-file helper is byte-identical between those sources. A read-only
synthetic trace of its actual open function independently demonstrates repeated
immutable setup:1000freshopens construct1000WinDLLwrappers, resolve3000symbols and
write4000function prototypes, in addition to the1000CreateFile/1000file-info calls
and1000CRTtransfers. This is a call-count proof, not measured Windows latency or
proof that this setup caused either timeout.

Two lazy process-local factories retain only the typed kernel32 API bindings,
following the existing stateless Windows API-binding pattern. The cache has no
path, instance, policy, authority, handle, locality answer, file metadata, bytes,
hash or verification result. Every original locality query, native open/info call,
CRT transfer, parent pin, file read, integrity and authority check executes afresh
at its original boundary and order. Access/share/disposition/reparse flags, close
and error mapping remain identical. A failed factory call is not memoized or
retried within that call. Cold concurrent callers may construct equivalent ABI
objects independently; hot callers reuse complete initialized bindings.

Import performs no native load or locality query. The current ctypes thread-local
Win32 error behavior remains. Both libraries and their function objects survive
only as immutable setup used by the implementation; they carry no execution or
application authority. No inference binary, model/runtime selection or profile,
polling, timeout/snapshot/threshold, permission, dependency, API or telemetry changes.
Every original hash and verification remains; this is not a hash or authority cache.

Regressions require setup reuse with every native call still fresh, changing
locality and reparse observations still refused, original failure/cleanup/CRT
ownership, inert import, and actual Windows replacement-file reads and thread-local
error controls. A structural comparison restores only the hoisted binding setup
and requires the complete original file-helper control flow to match. Linux mount
observations, native inference/containment, scheduler, configuration, cancellation,
all deadlines, qualifiers and workflows remain unchanged.

Qualification requires full unchanged native/Ruff/diff/canonical97, actual GitHub
bytes/modes/tree/parents/effects and owner binding, every applicable workflow,
attempt, job, review, finding and thread, fresh preflight, normal expected-head
merge, actual ordered parents/tree and all actual-main native/post gates. Old
failures remain retained; no CI recovery, new acquisition probe or waiver.

Only after actual acceptance may accepted main be merged through the supported
history-preserving route into the same diagnostic owner366, retaining its failed
head and fully qualifying the new candidate. Its own successful integration/post
gates must satisfy365/363 before the same route into existing S03owner362 and full
qualification, then ordered S04/S05/integratedS01+Cura/one final official0.13.0.
No result transfers to a failed host or changes the original owners. Human/label
omissions remain factual and nonblocking; classifier quality NOT_EVALUATED and
automatic application denied. Published0.12.1/0.12.0 and #348 remain immutable
and independent. Version identity belongs only to the final release workstream.
