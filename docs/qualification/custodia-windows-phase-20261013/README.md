# Custodia Windows phase diagnosis — retained block

Owner: `product/custodia-windows-phase-diagnosis`. This branch preserves diagnostic observers and evidence separately from documentary PR #348. It is not a Core runtime correction or a qualified runtime candidate.

The original run 38289564204 attempt 1 remains FAIL: AMD Family 25 Model 1, 26/27 gates, en04/run2 5.797 seconds above the original 5-second end-to-end limit. Both original reports, WFP, Linux success, historical audits and blocked preflight references are retained.

Two fixed diagnostic observations collect GGUF admission, runtime verification, native prefill, and request/PID-correlated IPC timings. The first observer exposed Windows monotonic clock granularity; its separate direct-child correction adds QPC and supervisor dequeue timing. Neither observation reproduces the original spike or proves its technical cause. Both remain DIAGNOSTIC_ONLY / NOT_EVALUATED. No Core correction, qualification rerun, waiver, release publication or merge follows from these outputs.

`evidence.zip` preserves original and diagnostic artifacts, logs, API inventories, reducers, validation results, and a complete source-history Git bundle. Its manifest records every included byte and the three omitted large public payloads. The complete local evidence ZIP additionally retains those payloads. Both were ZIP-tested and restored byte for byte locally; the independently downloaded durable compact copy is verified separately in the PR audit.

The official release, tag, publication receipt, installation kit and readiness are original and unchanged. The full official kit remains above 32 MiB and was not downloaded locally. Historical missing BOUND receipt and missing prior local archives are declared, not reconstructed. Human/hardware acceptance remains unattested; site work is separate; 0.12.0 is immutable and 0.13.0 remains Iudicium.

See `HANDOFF.md` for the exact owner/head/pin, unresolved cause, evidence requirements and conditional normal merge procedure. `evidence-record.json` contains archive identities and the distinction between executed diagnostic heads and archival commits. Archival commits use the supported skip-CI directive solely to prevent another diagnostic push execution; this does not waive any #348 gate or qualify this branch.
