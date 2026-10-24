# Launcher-owned startup and readiness

Development contract for Concordia S01 / [#393](https://github.com/gabned/provelume/issues/393),
following the accepted [step 0](concordia-step-0.md). Qualification and acceptance belong to
the owner PR ledger. The published application remains Entitas; package identity is changed
only by the final Concordia workstream. [Italian contract](startup-readiness.it.md).

## Ownership and authority

One `ManagedStartup` owns preparation, child creation, bootstrap, serial probes, process
observation and cleanup. Tk consumes a private event queue; startup I/O and endpoint receipt
writes run in that worker. Repeated Open does not spawn another child or extend a deadline.
Callbacks require the current attempt object, owned process object, selected Instance and
port; a cancelled attempt cannot open a page. Selection/restart waits for confirmed cleanup.

The existing installation inspection and Instance opening/recovery remain required. Parent
preparation checks local-directory guards, performs the existing Instance preparation, then
pins the selected physical directory while binding and starting the child. The child opens
the same guarded directory and performs its own mandatory application initialization. A
replacement, unsupported identity, reparse chain or critical initialization error fails closed.
No additional global Instance lock, canonical state, migration or recovery bypass is introduced.
Startup guards are released after the bound observation; ordinary lifecycle/maintenance
authorities continue to govern subsequent operations.

## Private wire contract

The launcher appends a private bootstrap flag to its fixed backend command. A single stdin
frame contains a four-byte unsigned big-endian length and at most 256 UTF-8 JSON bytes with
exactly `version: 1`, `startup_id` (16 random bytes as 32 lowercase hex characters), and
`key` (32 random bytes as 64 lowercase hex characters). Duplicate/extra fields, trailing bytes,
truncation and other encodings are rejected. The parent writes once and closes its pipe.

The windowed frozen child reads the inherited OS stdin handle even when `sys.stdin` is None.
It makes bootstrap handles noninheritable and removes the consumed Windows pipe from the
standard-input slot before workers can be created. Keys never enter argv, environment, files,
URLs, diagnostics or worker parameters. Secret references are released with their attempt;
physical erasure of Python memory is not claimed.

Only this bootstrapped child registers `GET /internal/startup-readiness`. Normal `--serve`
keeps the route absent. No query parameters are accepted; exactly one
`X-Provelume-Readiness-Challenge` header carries a fresh 32-byte lowercase hex nonce.
The client connects directly to the fixed IPv4 loopback endpoint, with no DNS, proxy,
redirect, alternate port or `/health` fallback.

The response is bounded UTF-8 JSON (2,048 bytes) with exactly `contract`, `version`,
`startup_id`, `challenge`, `instance_binding`, `port`, `backend_state`, `reason`,
`diagnostics_state`, and `proof`. Booleans are not integers. Version is 1 and contract is
`provelume.startup-readiness`. `ready/operational` is HTTP 200; `starting/initializing` and
`failed/{configuration_invalid,integrity_failed,initialization_failed}` are HTTP 503.
Diagnostics independently reports `not_requested | pending | complete | failed | unavailable`.
The startup implementation reports archive diagnostics `not_requested`; it starts no scan.

Each HMAC field is UTF-8 prefixed by its four-byte unsigned big-endian byte length; integers
are unsigned decimal strings. The Instance binding fields are
`provelume.instance-binding.v1`, startup ID, canonical Instance ID, physical root binding,
`127.0.0.1`, and port. The root binding is `win32.file-id.v1:` followed by the hex encoding of
the 8-byte big-endian FileIdInfo volume serial and the 16 raw FileId bytes. Linux reference
tests use the distinct `posix.file-id.v1:` domain and 8-byte device/inode values. A pathname is
never the identity. The canonical ID is bounded to 1,024 UTF-8 bytes.

Proof fields are `provelume.startup-readiness.proof.v1`, contract, version, startup ID,
challenge, Instance binding, port, backend state, reason and diagnostics state, in that order.
Binding/proof comparisons use constant-time comparison. Stale challenges, malformed schema,
unsupported versions, wrong root/Instance/port or invalid MAC terminate the attempt.
This distinguishes the owned child from a foreign listener; it does not defend against a
compromised process with access to this user's memory or kernel handles.

READY follows installation checks, Instance/schema/recovery, service/middleware attachment
and application lifespan initialization. Modified installation evidence is terminal; missing
explicitly required release evidence cannot be promoted to success. Ordinary editable-source
inspection retains its existing unavailable status, without claiming installed integrity.
The frozen private startup requires verified package integrity. Packaging retains the wheel's
Python source payload alongside PYZ so the existing RECORD predicate can inspect every required
byte; unavailable, missing or modified package evidence never becomes READY. RECORD verifies
local package payload, not executable provenance or publisher authentication.
`/health` keeps its schema and deep checks. Readiness is a startup observation, not permanent
archive/index health or a per-document completion proof.

## Finite work and cleanup

| Limit | Value |
| --- | --- |
| Parent preparation | 10 s |
| Spawn and bootstrap | 5 s |
| Child readiness | 60 s |
| Absolute startup | 75 s |
| One complete HTTP probe | 1 s over connect, headers, body and verification |
| Probe spacing / maximum | 250 ms / 240, one in flight |
| Cleanup | 4 s cooperative/terminate, then 2 s scoped escalation |

Unused phase time does not extend another phase. Socket I/O uses an absolute monotonic
deadline and bounded reads, including slow-drip responses. Cancellation invalidates UI effects
immediately. A blocking OS operation can outlive its budget: its worker/resources remain owned,
and late results are reconciled rather than accepted or discarded.

On Windows an attempt-scoped manual-reset event requests Uvicorn's normal shutdown. Its name
is `Local\Provelume.Startup.Stop.` plus HMAC-SHA-256 over framed
`provelume.startup-stop.v1` and startup ID, using the bootstrap key. The parent creates a new
event (existing-object collision is rejected); the child opens it for synchronization only.
Neither event name nor raw handles are diagnostics. This adds no HTTP write/control endpoint.

Before delivering bootstrap the parent assigns the child to an anonymous Windows Job with
KILL_ON_JOB_CLOSE and no new CPU, memory or process-count limit. The supported `onedir`
packaging has no separate bootloader process. Application workers therefore inherit the Job;
existing component limits still apply. Escalation terminates only this Job/owned process,
then verifies both process exit and zero active Job members before releasing handles.
POSIX source reference execution retains normal SIGTERM and the owned-process escalation.

`STOP_UNCONFIRMED` preserves ownership when child, descendant or startup resources remain
active/unknown. No concurrent retry, delayed restart, Instance switch or completed Quit is
reported. The UI remains available for local details; it completes only after reconciliation.
Endpoint known-good/rollback receipts retain the existing revision checks; a later preference
edit cannot be overwritten by an old startup result.

An ambiguous directory-descriptor close is an unsupported OS condition. Its numeric descriptor
is not retried after possible reuse. The attempt remains unconfirmed and requires scoped
operator process/OS recovery; a fresh application start must revalidate/recover the Instance.
This condition is not reported as completed Quit and grants no concurrent replacement.

The local details view contains at most 32 allow-listed phase/code/timing events and optional
exit codes. No document bytes, paths, canonical IDs, keys, raw exceptions/stderr, challenges or
proofs are included. It neither uploads nor copies data automatically.

## Page projection and qualification

Empty/whitespace Search and About use only the actual configured Instance identity for their
shared page context. Missing deep counts/health are not invented. Search filters retain their
existing data sources; positive Search keeps its index/operation checks and deep context.
Other pages, `/health`, public API fields and canonical processing semantics are unchanged.

See the [qualification matrix](../qualification/concordia-startup-readiness.md). Automated
protocol, lifecycle, native Windows controls, source subprocess and frozen transport evidence
are distinct. The installed smoke keeps its existing 30-second normal readiness budget.
It does not replace normal Panel/tray/browser and Windows 11 25H2 Home/Pro observations.
