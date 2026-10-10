# ADR 0052 — Custodia integrated installation and lifecycle

Status: accepted design for [S09 #335](https://github.com/gabned/provelume/issues/335),
2026-10-10. S08 was accepted at actual main
`8b2403a091f927debd3718ba3ae0ea90ece657ee` in its
[final ledger](https://github.com/gabned/provelume/pull/334#issuecomment-6097065742).
This decision is fixed before integrated candidate scoring. It grants no waiver,
model promotion or release-publication authority.

The selected source-reporting v11 profile, model bytes, runtime lock, frozen
corpora/gold and all 26 S08 native criteria remain unchanged. S09 qualifies their
ordinary installed path and complete user lifecycle. Keep every failed observation.

Freeze a new execution-configuration identity for parent-process lifetime, ordinary
Windows AppContainer containment and effective resource admission before integrated
scoring. The semantic profile, model/runtime bytes, corpus/gold and numeric gates
above stay fixed; prior configuration-bound consent and self-test evidence cannot
qualify the changed execution boundary.

The S09 canonical execution-configuration SHA-256 is
`3fc42d6c5e1e6e565e9888acc4fceb163d0fe751b7b4a4199f339a94d77bc808`,
fixed before the first S09 native scoring. Its four explicit lifecycle properties
record the frozen Windows AppContainer/creation-time Job/model-handle worker,
Linux pidfd lifetime guard after seccomp, and host/visible-cgroup-ancestor
admission. This supersedes S08 configuration evidence; no result threshold or
task framing changes. Unobserved cgroup ancestors remain explicitly unobserved.

The initial installed observations (runs 38051898250, 38052240494 and 38052818420)
failed before worker entry; retain them. The last two report Win32 203 at
CreateProcessW. Resolve the required LOCALAPPDATA from SHGetKnownFolderPath for
the current user and add only that field to the minimal child environment. Do
not inherit the ambient environment or grant the private profile directory an
ACL. Freeze this explicit environment property before its next native run:
configuration SHA-256
`9b8c5e44224fdaf34f947eb969ce53dce3c3398b6068eed854bc0979ade09b9c`.
It replaces the initial configuration above without changing gates or model bytes.
The independent [Windows launcher experiment](https://github.com/Convira/convira-sandbox/issues/1#issuecomment-5225682721)
supports the diagnosis; only this product's installed run can establish the fix.

Installed run 38053390090 passed the AppContainer, ordinary import/self-test/
activation and parent-death observations on that configuration. Native run
38053390064 retained a distinct performance failure: full document authority was
reconstructed about 2,800 times per model hash, costing up to 17 seconds before
inference. Poll that expensive authority after at most 20 ms of file reading
between completed checks **only inside the
regular-file hash loop**. Retain per-MiB deadline/immediate-cancel checkpoints,
full authority at both hash boundaries and every publication/dispatch boundary;
inference polling is unchanged. Freeze the explicit polling property before the
next measurement as configuration
`af9bfc85f5b1968f74a65f5a3207614a6bc059b8306a7ed751c047c3c206fdd5`.
No threshold, model, corpus or task framing changes. Prior results remain scoped
to their original configuration.

Retain 9056b2c Linux run 38055192811: governed-job warm first response fell to
3.69–3.88 seconds and S06 passed, but S07 warm first response remained 6.23 seconds
and the first S08 job failed before inference. The initial implementation scheduled
the next hash-loop audit from the previous audit's **start**, so a document audit
longer than 20 ms left its own timer already expired and ran again immediately.
Schedule the unchanged interval from audit **completion**. Immediate cancellation,
per-read deadlines and complete publication/dispatch revalidation remain unchanged.
This is an implementation correction, not a larger interval or acceptance waiver.

The next Linux observation, run 38056161108 on ff562b2, passes 25/26 gates,
including every gold reference and abstention, but S08 warm first response is
6.096 seconds against the unchanged five-second bound. Retain that failure.
A public 32-document profile identifies repeated construction of every path
ancestor for every Linux mount as the main cost of local-file authority reads.
Compare normalized path components against mount components once instead. Read
the complete kernel mount observation afresh for each call, retain nearest-mount
selection and remote/unknown refusals, and decode all four kernel escapes,
including newline. Keep descriptor-pinned, no-follow file access and every
authority/read/dispatch checkpoint unchanged. This neither caches locality nor
changes the execution configuration, selected model, task framing or numeric gates.
Native measurements also retain model-admission and revalidation phase durations.

A successful native self-test records a measurement, not network authority. Only
actual seccomp or the parent's verified AppContainer proof grants product-local
activation. The legacy source-only Windows CI observer may add its independently
measured WFP evidence after the test; that does not qualify the installed worker.

## Installed resources and reconstruction

Use one portable Core distribution containing both optional, independently pinned
Windows and Linux x64 library resource trees, 19,333,560 uncompressed bytes across
12 closed inventory members. No model weights. Select only the supported host tree
after hardware/ABI admission; portable Core availability does not imply portable AI.
The source distribution includes the same verified inputs, preserving offline
sdist-to-wheel reconstruction. The ignored packaging study already demonstrates
byte-identical two-build and sdist rebuild results; it is not installed qualification.

Keep original reviewed source identity and verified native input composition
distinct in build evidence. Release packaging must require both closed inputs and
their lock, notices and SBOM; a missing/substituted member blocks packaging. The
independent runner rebuilds with the same transferred, byte-verified inputs, with
network disabled. Frozen inventory checks include the selected libraries and
private worker entry. Never download executable code through model acquisition.
Source-only development without supplied inputs remains explicitly unavailable.

Linux static requirements observed in the exact libraries are GLIBC >=2.34,
GLIBCXX >=3.4.29, libgomp and x64 loader/CPU support. Container builds must supply
the required system dependencies, recorded base digest and governed native inputs.
Run as UID 10001, retain the read-only root/no-new-privileges/capability-drop
boundary, and mount a separate model-store volume outside portable Instance data.
Effective admission uses inherited cgroup/ancestor memory and CPU limits as well
as physical hardware; unknown limits fail closed.

## Installation ownership and budgets

Keep synthetic ZIP acquisition at its existing 30-second envelope. Select a
separate **900-second total native installation/import budget**, including transfer,
hashing and atomic publication, before measurement. This accommodates a 1.44 GB
explicit download without changing any inference, self-test or cancellation cap.
Do not reset the deadline at redirects, retries, verification or publication.
There is no automatic retry or activation. Cancellation stays required within
the existing two-second bound on measured hosts. Buffered headers remain bounded
at 16 KiB/32 fields; native body reads stay bounded at 64 KiB and hash/copy reads
at 1 MiB with pre/post checkpoints. Retain a finite short socket wait so a stalled
peer cannot suppress cancellation. At most three redirects, only the reviewed
HTTPS origin/CDN set, with every DNS answer and numeric TLS peer validated.

Exact size, magic, complete hash and license acceptance gate atomic publication.
Global network denial is checked before DNS and throughout transfer; install
never broadens global consent. Newer global revocation survives launcher restart
and Instance selection even when the saved update-check preference remains on.
Verification/admission/self-test use the owning cancellation/deadline before the
first read and between chunks, while preserving complete verification before use.

## Ordinary worker containment

The installed Windows windowed executable dispatches its private worker role
before desktop/Tk imports. Explicit binary GetStdHandle pipes avoid absent default
Python stdio. Create the worker suspended with a capability-free AppContainer,
verify the real token and absence of loopback exemptions. A parent-owned,
noninherited kill-on-close Job is supplied through PROC_THREAD_ATTRIBUTE_JOB_LIST
at process creation; verify membership before resume. Creating a suspended child
and only then assigning its Job leaves an unacceptable parent-crash gap. Do not
fall back to that sequence if creation-time Job assignment is unsupported. Inherit only explicit
stdio and the read-only pinned model handle. Public installed code gets only the
necessary AppContainer read/execute access; private Instance/model-store/ancestor
permissions are never broadened. Preserve the locked same-UCRT FILE-pointer
lifetime contract through model_free. No administrator/firewall prerequisite and
no arbitrary executable path from documents, models or environment variables.

Linux retains seccomp/rlimits and a parent-process lifetime guard using pidfd.
Creator-thread exit must not terminate a valid warm worker; actual parent death
must terminate it promptly. The parent opens its own pidfd before spawning and passes
that exact descriptor. Start the child watchdog only after containment so its
thread inherits the seccomp filter; check parent death before further native work.
Native proof observes cleanup independently and
retains uncertain accounting after interrupted dispatch without automatic replay.

## User actions and recovery

Use the existing setup/background-operation and durable job owners. Present one
current model and action appropriate to its state, with size/license/destination
visible. Put retired inventory, hashes and manual runtime configuration in
technical detail; actual retired installations retain explicit removal controls.
Preserve Off initially and after restart. An explicit Generate action may own a
fresh synthetic self-test when evidence expires, then must revalidate all original
preview/source/policy/configuration/route bindings. Never recreate consent.

One header disclosure is open at a time. Toggle, Escape, outside click and focus
leaving the header dismiss correctly without stealing the destination. Use the
same compact labelled globe/native-language selector in both layouts. GET changes
only the current request; saving preference uses a narrow revision/nonce/CSRF
action, preserving unrelated shell and network state. Keep System and seven
catalogs. Perceptio uses four task cards and collapses diagnostics; synthesis
retains route, coverage, cost/limits and consent without making internal identifiers
primary navigation. Input-limit errors retain document context and fresh selection.

Backup/restore/portable transfer preserve canonical records and included private
bodies/recipes while excluding external weights and credentials. Explicit bounded
orphan cleanup must protect active/uncertain jobs, maintain receipts/accounting
and require fresh ownership; missing job authority is not permission to delete.
No automatic regeneration or retry during recovery.

## Observations required before acceptance

Keep the 26 original native gates on both recorded Windows/Linux profiles, plus
actual installed Windows and non-root container lifecycle/network/resource
evidence. Record observed hardware rather than claiming an unmeasured laptop.
Exercise provider substitution/policy adversaries; specific live providers remain
unqualified without separately authorized credentials and bounded cost.

Retain immutable 0.10.1/0.11 upgrade inputs and the existing baseline, same AppId,
preserved Instance, correct update/About identity and restart Off. The old schema1
client requires one manual complete-kit upgrade; never mutate published 0.11.
Resolve the narrow PDF dependency correction on a genuine Windows resolver and
preserve extraction-failure evidence without claiming every advisory is covered.

Browser proof covers both layouts/seven catalogs, light/dark/System, keyboard and
pointer/touch, 390px reflow, real 200% zoom, forced colors and reduced motion.
Human screen-reader/linguistic evidence is bound to the final concrete artifact;
prior S07 attestations are not extended. Full unchanged-source checks, complete
exact-head CI/reviews, expected-head merge and actual-main acceptance precede S09
closure or promotion of the exact observed model/task/language profile. Version
alignment and official preview publication remain a separate release workstream.
