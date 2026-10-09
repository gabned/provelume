# Custodia S05 local CPU candidate

Issue #320, sole owner PR #321, after integrated and qualified S01–S04. The selection
and frozen thresholds are [ADR 0031](../adr/0031-cpu-local-runtime-candidate.md).
Candidate selection, S05 technical qualification and S09 Recommended promotion are
three separate decisions. S05 is integrated at main
`d7f33d908912b7644cc074354ec68a8552c081fb`; the final integration ledger is linked in
the qualification record. None of these decisions authorizes dispatch: the separate
[S06 durable-job boundary](ai-durable-jobs.md) requires current policy, explicit
session/job authority and an atomic reservation.
Actual profiles, numerical results and retained failures are in the
[S05 qualification record](../qualification/custodia-s05-cpu-runtime.md); final
exact-head and actual-main qualification are linked from the sole owner ledger.

## Boundary and compatibility

The historical S05 tuple was llama.cpp b11379 / Qwen2.5-1.5B-Instruct / GGUF v3 Q4_K_M.
The S08 development candidate is the reviewed Qwen3.5-2B Q5_K_M conversion in
[ADR 0047](../adr/0047-hybrid-cpu-synthesis-candidate.md), using the same locked libraries on
native Linux x86-64 or Windows x64 with AVX2, CPython 3.12, four logical CPUs,
8 GiB RAM and 4 GiB available. Arm, macOS, GPU paths, ONNX, arbitrary GGUF/BYOM,
frozen-launcher inference and unknown configurations fail closed. The ordinary
0.11.0 application remains AI off; this is an internal qualification seam.

`ai_models.RuntimeSelection`, the S01 Profile and S04 ModelRegistry/ModelStore remain
the identity/admission owners. No second resolver, canonical object, scheduler or
budget engine exists. S01/S02 context, redaction, template, receipt and gateway
rules remain unchanged; the benchmark uses synthetic strings internally, never
accepts a product dispatch permit and cannot create product inference authority.
Service `ai_local_runtime_status` and the existing Components model projection are
pure metadata. Complete activation surfaces belong to S07.

Construction, import, status and preflight do not load native libraries, spawn
workers, fetch weights or send network requests. Only an explicit lifecycle self-test
or qualification call, or an admitted S06 job, lazily starts one worker; after five idle seconds it exits.
One process slot per Core interpreter, one active request, zero queue. Multiple
independent Core processes are constrained by S06's Instance-wide durable reservations
and existing cross-process scheduler lock before product dispatch.
The worker uses fixed two-thread CPU inference, 2048 context tokens, 1536 input
tokens, 4096 input bytes, 128 output tokens and 4096 output bytes. Greedy sampling
is fixed. StdIO messages, the reader queue and the single supervised writer are
bounded; a worker that stops consuming input cannot block cancellation in a pipe
write. Errors, crash, malformed
output, cancellation and timeout close the operation without retry or fallback.

## OS controls, byte integrity and limits

Linux applies a two-CPU affinity and a 3 GiB RLIMIT_AS ceiling. Seccomp checks the
x86-64 audit architecture, rejects x32, networking and io_uring syscalls, fork,
non-thread clone and exec; thread clone remains available to inference. It is not
a filesystem sandbox. File/core/descriptor limits are also imposed. Model and
small native libraries are copied in bounded chunks to sealed memfd snapshots;
no whole-weight Python bytes object or unbounded copies exist. One model snapshot
per worker can consume about 1.34 GiB of additional file-backed system memory for
the current artifact. This is separate from the unchanged 2 GiB qualification RSS
gate and 3 GiB worker virtual-memory ceiling.

Windows uses a Job Object with two-CPU affinity, one active process, 3 GiB committed
process/job memory and kill-on-close. It launches the base Python interpreter
directly, avoiding the virtualenv redirector, and verifies reported PID equals
the supervised PID. Verified files retain deny-write/delete handles until exit.
Job memory is not the same measure as Linux virtual address space or peak RSS.
The Job Object alone **does not block networking**. Native CI adds a temporary,
exact-interpreter WFP outbound deny rule and Security event observation; that rule
is removed and previous audit policy restored. This control is not installed on
users' computers. A bare Windows worker is not claimed network-isolated.

Both platforms keep ownership and the global slot if termination cannot be proved.
The fixed 60-second operation limit includes load/generation; cancellation polls
at bounded supervisor waits and termination has a two-second deadline. Python
thread count is configurable, not a hard OS thread ceiling. Parent verification
streams weights through existing S04 admission; OS controls start before native
library load and application dependency imports. A content-free child HOME prevents
implicit NSS account-home discovery, but is never treated as network evidence.
The interpreter and application code are trusted application inputs.

Model integrity, governed metadata and origin authenticity remain distinct. The
application-pinned registry and native lock are reviewed source artifacts; a
download's companion hash cannot replace them. Every self-test binds model bytes,
native library lock, configuration, current registry/admission and manager session.
Actual native files are rechecked at activation and warm use; substitutions
invalidate evidence. UNKNOWN, failed/expired evidence, revoked IDs and changed
configuration fail closed. Rollback follows S04's fresh verification/self-test.
Restore hints never recreate installation or qualification. Installed weights,
staging and snapshots remain outside portable Instance backup/export and Git.

Governed requests may reuse one exact input-prefix sequence checkpoint in the same
loaded worker and Instance. The hybrid recurrent state cannot support arbitrary
suffix removal. Its 64 MiB checkpoint is captured before the final input token,
after the trusted prefix or at 128 tokens if that prefix is shorter. Every saved
token must match the new full current input; otherwise all state is cleared. A
matching restore is checked for complete byte count and native position, then all
remaining current tokens are decoded for fresh logits. No previous response or
sampler state enters the checkpoint. Unscoped calls and Instance changes clear it.
Buffers are zeroed on replacement/close, never persisted. All copy costs remain
in the existing time/memory bounds and every logical input token remains charged.
This computation reuses no permission, output or accounting. Cancellation, errors
and idle unload destroy it. ADR 0032's isolation contract remains mandatory;
ADR 0047 specifies the changed mechanism requiring fresh native qualification.

## Reproduction and build inputs

Check Python 3.12 and Node first. Reuse a valid environment or run canonical
`python scripts/bootstrap.py`. On Linux use `.venv/bin/python`; on Windows use
`.venv/Scripts/python.exe` for the commands below. Use a fresh, short, external
directory with at least 5 GiB free; do not put it inside portable Instance data.

```text
python scripts/ai_runtime_acquire.py --directory ABSOLUTE_SCRATCH --accept-licenses --include-model
python scripts/build_ai_runtime_input.py --directory ABSOLUTE_SCRATCH/windows --platform windows --output .agent/s05-native-input.zip
python scripts/qualify_ai_runtime.py --artifacts ABSOLUTE_SCRATCH --output .agent/s05-real.json
```

Use `linux` for both build arguments on Linux. The first command downloads only
the locked current-platform CPU archive and the one locked model. It requires
explicit license acceptance, checks space, caps bytes/time and permits only
reviewed HTTPS upstream/CDN hosts; no ambient proxies, cookies or credentials.
The official [Hugging Face download documentation](https://huggingface.co/docs/hub/models-downloading)
identifies `us.aws.cdn.hf.co`, observed as the immutable model URL's redirect.
This developer/build acquisition tool is separate from the unchanged guarded S04
product downloader: it cannot update executable runtime components through a
model registry. It imports the resulting model through the real S04 lifecycle.

The second command builds a deterministic, offline native application input with
full notices, exact per-library hashes and a CycloneDX SBOM. It excludes weights.
Application wheels carry the lock, notices and Python boundary; the native input
is not a released or installed runtime update. Ordinary deterministic wheel,
Windows installer and release SBOM gates still run in repository CI. Final native
distribution/Recommended promotion remains blocked until its qualification gates
and S09; there is no invasive global installation or new Python ML dependency.
System C/Python runtime dependencies remain prerequisites of the declared host,
not files redistributed in this optional native input.

The third command produces real synthetic EN/IT answers, all cold/warm samples,
self-test bindings, capture/search comparisons, tamper rejection, cancellation
and unload observations. It exits nonzero for FAIL or BLOCKED. Its standalone
network gate is NOT_RUN; only external native observations can complete it.
The CI workflow uses strace from process creation through exit on Linux and
`qualify_ai_runtime_windows.ps1` on disposable Windows runners. That PowerShell
script deliberately refuses ordinary local execution. Logs contain closed worker
diagnostics and public synthetic corpus output, no user documents or credentials.

Keep separate the synthetic supervisor suite, native execution, model quality and
covered hardware profiles. No successful CI run qualifies an unmeasured laptop.
The owner ledger retains failed runs and residual host restrictions. The local
Windows sandbox's protected-parent/DPAPI restrictions and unavailable WSL are
already evidenced on S03/S04; do not loosen ACLs or retry identical failing paths.
