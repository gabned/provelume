# Custodia S05 CPU candidate: measured scope and retained findings

Sole owner: [#320](https://github.com/gabned/provelume/issues/320) /
[PR #321](https://github.com/gabned/provelume/pull/321).
The PR ledger carries final exact-head qualification, integration and actual-main
post-merge identity. This document records reproducible measurements, not product
dispatch authority or S09 Recommended promotion.

## Fixed candidate and criteria

[ADR 0031](../adr/0031-cpu-local-runtime-candidate.md) was committed at
`5e0db60e5281df5ba0d415db84fb3b84b1bad5ea` before inference. It fixes llama.cpp
b11379 / official Qwen2.5-1.5B-Instruct GGUF v3 Q4_K_M, all source revisions, bytes,
licenses, numerical thresholds and the twenty synthetic EN/IT cases. Thresholds
were not lowered after observing failures. The exact native lock SHA-256 is
`0e508965cddc60d6cfb57c42d2c4039c637e8812bb25cc21b525b6d6047a4404`;
configuration SHA-256 is
`cc30ae5fd6c331b9e713a9114768749f0428e9f12572ea4ed2bfbc11e4276cbe`.
The model SHA-256 is
`6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`.

## Real native evidence, 2026-10-03 UTC

The [native run 37157885501](https://github.com/gabned/provelume/actions/runs/37157885501)
executed source `b647fb95d4a621b2545914a46432c0947ba73422` directly, not a fixture.
Both jobs passed all seventeen measurement gates. The later bounded-pipe correction
has its own unchanged-head native run in the owner ledger; this earlier PASS is
retained with its original source identity and does not transfer qualification.

| Observed profile | Windows | Linux |
| --- | --- | --- |
| OS | Server 2025 build 26100 | Ubuntu 24.04, kernel 6.17.0-1022-azure, glibc 2.39 |
| CPU | AMD family 25 model 1 stepping 1 | AMD EPYC 7763 |
| Logical CPUs / affinity | 4 / 2 | 4 / 2 |
| Total / available RAM bytes | 17,174,360,064 / 13,903,728,640 | 16,766,414,848 / 15,638,966,272 |
| CPython | 3.12.10 | 3.12.14 |
| Native measurement job | 111305008659 | 111305008868 |

Three fresh-worker cold samples (OS cache **not flushed**), sixty warm answers
(three repetitions of ten cases per language), two cancellation phases and three
matched idle/busy capture/search probes were retained; no outliers were discarded.

| Metric | Fixed maximum | Windows observed | Linux observed |
| --- | --- | --- | --- |
| Cold load | 15 s | 1.562 s | 2.775 s |
| Cold first result | 20 s | 3.610 s | 4.848 s |
| Cold whole result | 60 s | 3.813 s | 5.179 s |
| Warm first result | 5 s | 3.609 s | 3.757 s |
| Warm whole result | 30 s | 3.750 s | 3.975 s |
| Peak worker RSS | 2 GiB | 1,145,585,664 bytes | 1,281,867,776 bytes |
| Cancel during load | 2 s | 0.109 s | 0.105 s |
| Cancel during generation | 2 s | 0.219 s | 0.335 s |
| Idle unload / zero workers | 7 s | 4.125 s | 4.328 s |
| Parent RSS change after unload | <=64 MiB | -38,535,168 bytes | +3,014,656 bytes |
| Concurrent capture | <=1 s and relative baseline threshold | 0.203 s | 0.350 s |
| Concurrent search | <=1 s and relative baseline threshold | 0.016 s | 0.027 s |
| EN exact answers | >=90%, all missing facts UNKNOWN | 30/30; abstention PASS | 30/30; abstention PASS |
| IT exact answers | >=90%, all missing facts UNKNOWN | 30/30; abstention PASS | 30/30; abstention PASS |

Each accepted answer matched the expected synthetic fact exactly after whitespace/
terminal punctuation normalization; this is bounded factual-answer evidence, not
a general summarization benchmark. Exact Original bytes and search results survived
concurrent inference; product dispatch remained disabled. Missing and one-byte-altered
installed models were refused. Explicit next callers succeeded after cancellation.

Linux strace observed all traced threads from exec through exit (96 trace files)
and no network calls after the bootstrap correction, with worker seccomp enforcement.
Windows WFP observation had a successfully calibrated denied probe, audit enabled,
and no permitted connection events for the seven supervised worker PIDs. The
temporary CI-only firewall rule and audit changes were removed/restored afterward.
This proves the observed controlled CI profiles, not network isolation of a bare
Windows worker. All load, inference, idle, error and shutdown phases are represented.

## Synthetic conformance and actual findings

The complete native Linux suite on that source passed 3,387 tests with 23 platform/
optional skips. Windows' canonical four-shard collector passed the complete disjoint
3,410-node inventory on merge candidate `e6dca695da930cb880b5eacbcccceedcb14cea62`,
whose tree `da8d287cf33fb1302baa8710486957fe95b7bd8b` equals the source tree.
Subsequent head-bound checks remain mandatory; the PR ledger names their exact runs.

Retained failures drove bounded corrections: canonical-venv acquisition; the verified
upstream CDN allowlist; efficient 1 MiB native import without changing the S04
deadline; direct Windows base-interpreter supervision; sealed Linux byte snapshots
with source ancestor descriptors closed under the unchanged 64-FD limit; synchronized
packaged credits; and containment before application imports. The first Linux
no-egress observation remains FAIL: NSS AF_UNIX socket creation preceded containment,
with connection attempts returning ENOENT. Providing a content-free HOME alone was
not accepted as evidence; the unchanged strace gate was rerun.

A separate synthetic blocked-reader probe on b647fb95 reproduced cancellation at
2.156 s, beyond the two-second requirement, despite the real benchmark PASS.
The owner correction makes pipe writes supervised and bounded too, retaining one
writer and no queue, and adds a regression with an escaped 4096-byte input and a
worker that stops reading. No gate is satisfied merely by successful ordinary input.

Local Windows remains a distinct restricted host: Python 3.12.14, Node 24.16.0,
Windows 11 build 26300, Intel family 6 model 186 stepping 3, 12 logical CPUs.
Its canonical full suites retain 540-second timeout failures and protected-parent/
DPAPI restrictions also evidenced on the S03/S04 baselines. No ACL/DPAPI weakening,
timeout increase, test removal or WSL prerequisite was introduced. The unchanged-head
native CI path supplies independent Windows/Linux coverage, not a relabeled local PASS.

## Support and remaining boundaries

S05 chooses one candidate; technical qualification is limited to the observed native
profiles and synthetic EN/IT tasks. An 8 GiB laptop, Windows 11 real inference on the
restricted local host, Arm/macOS, frozen application inference and bare-Windows
no-egress remain NOT_RUN or unsupported as stated in ADR 0031. Do not extrapolate
from the CI runners. S09 alone can promote an integrated Recommended profile.

Application/native build inputs retain ordinary lock, full notices, per-library
hashes and CycloneDX SBOM; no model weights are redistributed or released. The
[reproduction guide](../architecture/ai-local-runtime.md) performs explicit
acquisition/import, exact-byte self-test, real EN/IT inference, OS observation,
cancellation/unload, corruption refusal and deterministic-flow checks. No new
scheduler, product AI dispatch, S06–S09 feature, account, paid service, remote
inference, version/tag or publication is introduced.

