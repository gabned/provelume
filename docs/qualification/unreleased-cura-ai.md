# Unreleased Cura/AI release preparation

Owner branch: `product/cura-ai-release-preparation`, PRODUCT, PR-local legacy route.
Original accepted baseline: `854550fbddb3f0e9e2550e777e2cd708035e2498`.
Current integration baseline: `df19f7b651855546eee43ec57be26f44196907d5`.
Original binding basis: `8658d890ff36df634c2e076e2510326d49f0a73a`.
The accepted Agent Protocol pin remains 1.5.1, source
`1a11fe76712ee65ca2160d2ae3789330946a57f2`; Lifecycle v2 activation remains deferred.
The owner PR ledger records the final head, workflow/attempt/job inventories,
artifact identifiers/hashes, merge identity and actual-main observations.

## Original baseline observation — 11 October 2026

At that observation GitHub main matched the original accepted baseline. #341 and #342 are merged; #339 is
closed and #340 is open for future-release delivery. The only other open PRs are
dependency updates, outside this scope. Published v0.12.0 is a preview with 25
assets; no later publication is observed. The optional warm-resume cache is absent
in this workspace. GitHub and the source/PR ledgers remain authoritative.

Public 0.12.0 Setup and wheel were independently downloaded and matched to the
manifest and tag commit `1ed289e6cacbc08c4425d461dfce72e37fe0ca30` before adding
that upgrade baseline. Setup: 24574033 bytes, SHA-256
`e82f90cbe6d8b49255d8e5b713f855afa74de9322eb1fafaf0204c473ae8a0f1`;
wheel: 8613651 bytes, SHA-256
`9c1b21ee58e495f88d16075c918b88fedf08ca63747cd39cb6864d15725688e5`.
The unchanged hardening harness verifies these bytes before execution and retains
Instance/config/preferences/Originals fingerprints. All three older upgrade
baselines remain. The new distribution identity still requires its own observations.

Fresh GitHub inventory confirms all 14 actual-main push workflows completed
successfully on attempt 1. The
[final #342 ledger](https://github.com/gabned/provelume/pull/342#issuecomment-6108892619)
records 4048 passed / 40 skipped, 27/27 real CPU gates per recorded host and installed
Windows 12/12 checks, 32/32 syntheses at one attempt each. Its exact exercised
installer hash is `c024bfb9bd1f7a5172f71aab2eca6887711fb220f98a77e6445d7a2c2d86ffd9`.
It remains an unsigned **development** installer, with no publication receipt/tag;
that result does not attest a future distribution artifact.

The full [Cura/AI audit](cura-ai-completion.md) and #342 ledger retain the original
Linux Capture failures, first Windows refusal, both #341 Intel warm-first failures,
the floating-point test failures and missing-overlap failure. No historical FAIL
is replaced. The original 94 ms refusal lacks its provider cause; the reproduced
admission defect is compatible evidence, not retrospective proof of that event.

## Artifact gate correction

The prior official pipeline exercised its own Windows installer for install/upgrade,
but the ordinary AI workflow built a separate development installer. The new
`installed-ai` job downloads the exact `windows-package` artifact, installs it and
runs the unchanged 32-case ordinary lifecycle with independent token/parent-death
observations. It records installer name/hash/size and checks the frozen installed
version, commit, repository, channel, tag and official/development status.

Assembly depends on that job and independently rechecks its report against the
installer it will distribute, the fixed complete ordered corpus and all 12 gates.
Failures, incomplete cohorts, second attempts, missing checks and mixed development/
official identity stop assembly. The report is a manifest/checksum-covered asset;
model weights and private content never enter the bundle. Existing standalone
offline verification checks the bundle's bytes; native observations and publisher
provenance establish the report's origin separately. Hash consistency alone does
not authenticate a publisher or prove an observation occurred.

The dry run now selects the PR's actual head, rather than the synthetic merge ref.
Its channel remains development. The same permanent pipeline enforces the installed
gate for the future official identity, without rebuilding the exercised installer.
Publication permissions/readback/receipt/kit/readiness remain separate.

## Qualification and unresolved gates

Current candidate checks and artifact results are recorded in the owner PR, never
inferred from the preceding main. This preparation makes no current official-build,
publication or ready-installation-kit claim. Final artifact qualification requires
the separately authorized version-setting candidate and official pipeline.

The first local full run on `8658d890ff36df634c2e076e2510326d49f0a73a` remains
FAIL: one failed PDF 17-filter boundary, 4062 passed, 40 skipped. The recovered
environment had pypdf 6.19.0 and editable package metadata 0.11.0; canonical bootstrap
installed pypdf 6.20.0 and the current 0.12.0 package. No extraction code or test was
changed. Corrected dependencies and each subsequent source head require fresh full
qualification. The first source candidate's workflows retain their original results;
adding the 0.12.0 upgrade baseline invalidates its head-bound acceptance for the final
candidate. The rejected selector/binding inputs and corrected calls are in the PR ledger.

Windows hosted Server 2025 and the measured AMD Linux/Windows profiles do not
qualify Windows 10 22H2, Intel latency in general, minimum laptops or other hardware.
Human Narrator/linguistic/appearance observations and live external-provider quality
remain NOT_RUN/UNVERIFIED where unobserved; earlier attestations keep their scope.
Unsigned Windows previews and same-provider wheel/sdist rebuild evidence retain
their existing limits; frozen executables are not claimed reproducible.

## Resume on the current default — 12 October 2026

Fresh GitHub branch and native Git object observations agree on main `df19f7b`.
#344 is merged/closed at expected source head `d1456f6`, with tree
`7a36978342c7b5195682a2bd46f717b98e2e4197` and ordered parents `854550f`,
`d1456f6`. #343 is still the open owner, initially at `bd9eac7`; its API base
`854550f` is a retained PR coordinate, not proof of the current default.
The candidate is reconstructed by a normal merge of actual main into the same
branch, preserving both parent histories, the original baseline and binding basis.
No rebase, reset, force-push, binding replacement or v2 activation is performed.
The merge has no textual conflicts, including the shared Windows upgrade harness.
Every head-dependent result is invalidated for new acceptance, with its original
result and timestamps retained. New head qualification does not resolve old causes.

All jobs of all observed attempts were re-read through the GitHub API. Exact
inventories, including failed/cancelled jobs and steps, are retained in the ignored
resume cache and summarized in the owner PR:

| Source | Workflow runs | Terminal jobs |
| --- | ---: | --- |
| #342 `3847b0e` | 19 successful | 37 success, 41 inapplicable skips |
| #343 `8658d89` | 14 success, 1 failure, 1 cancelled | 36 success, 9 skips, 1 failure, 1 cancelled |
| #343 `bd9eac7` | 17 success, 1 failure | 39 success, 25 skips, 1 failure |
| #344 `b6f3e99` | 14 success, 1 failure, 1 cancelled | 33 success, 9 skips, 3 failures, 1 cancelled |
| #344 `d1456f6` | 18 successful | 39 success, 25 skips |
| main `df19f7b` | 15 successful | 36 success, 1 skip |

Each observed run above has attempt 1 only. #344's first-head failed Windows
aggregate is retained alongside its failed source shard and Tk job; cancellation
of the containing CI does not erase those completed failures. The corrected
probes retain all themes, DPI cases and assertions in isolated processes.

The two #343 failed report ZIPs were downloaded again and match the original
SHA-256 values: artifact `11713036725`,
`1baea2c377e57d9901a85b01ec4d21a86e678bf0412e07637341e34ec3099b01`;
artifact `11714071064`,
`e4eb88a2a54cce083b13a37230ab418fa71bb0746776ce49551b4975e9c8f456`.
Both remain 31/32, `ai_local_stopped`, LOCAL, settled/quiescent, one attempt:
`en-summary-conflict` at 45297 ms on `8658d89`, `en-key-points-injection` at
51140 ms on `bd9eac7`, AMD Family 25 Model 1. Eight preceding checks pass;
synthesis, parent-death and restart qualification do not complete. Reports retain
no native failure detail, so neither a timeout nor a hardware cause is established.
The diagnostic read does not rerun inference or modify reports.

Separate retained successes are #343's exact pipeline installer on Family 26,
#344's first source head on Family 25, final source head on Family 26, and actual
main on Family 25: each 32/32 at the first attempt. #344/main retain the 336 actual
layout observations across four upgrades, minimum contrast 7.1069. These mixed
observations neither identify a CPU-family defect nor clear the two failures.
Human appearance, Narrator, actual high-contrast-host and linguistic review remain
unverified. The #344 PR bundle belongs to synthetic merge `c11bcd1`; main's bundle
belongs to `df19f7b`. Neither can become this candidate's distribution identity.

The optional `/workspace/provelume-cura-ai/.agent/warm-qualification-resume.json`
and original `.agent/release-preparation/` cache are unavailable in this workspace.
The user confirmed no recovery location/export is available. The GitHub owner
ledger, original source history and failed reports survive; the original BOUND
receipt bytes do not. At `c406d70` the prior audit treated that gap as blocking
every new binding and preflight. That historical BLOCKED observation remains in
the PR ledger; no original receipt is reconstructed or relabelled.

The resumed contract inspection distinguishes the PR/branch authoritative state
from ignored stateless receipts. The accepted v1.2 contract's "Exact effect report
and binding" requires a new report and binding after material head movement;
1.4.9 forbids rewriting coherent existing bindings, not an additional current
attestation for the materially changed candidate under the same owner. The current
candidate therefore uses that ordinary path, with independently selected current
policy context and the original validators. The original baseline `854550f`,
binding basis `8658d89`, missing original receipt and failed preflight are retained
separately from the current integration base/default `df19f7b`. There is no policy
compensation, recovery of PRODUCTION material, second lifecycle or v2 activation.

Required integration checks are selected by the accepted repository policy:
complete exact-head PR and trusted-base CI, current findings/review/thread
inventory, known review requirement, scope/effect binding, ownership, ancestry,
native product/artifact checks and normal expected-head merge. The policy requires
no unconditional Codex review, host enrollment, ruleset read or retrospective
diagnosis of all historical failures. Actual-main push CI and merge parent/tree
reconciliation remain required after integration. Future official publication
identity and human/unobserved hardware acceptance remain separate and unqualified.

## Native diagnostic follow-up

The historical two 31/32 FAILs and all independent Family 25/26 and Intel results
above keep their original scope. Their unavailable native cause cannot be inferred
from elapsed time. The verified diagnostic defect is loss between runtime,
`NativeJobAdapter`, `LocalFailure` and durable job/report: the latter retained only
`ai_local_stopped`; reader cleanup could also erase the pre-termination exit code.
No runtime root-cause fix follows from this observation.

The new instrumentation projects only closed cause/model-code/request-phase,
worker phase, native startup stage, numeric native/exit codes, observed parent
termination and actual cancellation/deadline/authority reason. Unknown remains
null; a cleanup exit code never becomes the worker's native failure. An optional
strictly validated diagnostic in the existing atomic attempt journal survives
settlement/restart and reaches the installed report. No exception text, stderr,
prompt, output, private path or identity is retained. Accounting, reserves, limits,
consent, isolation, integrity, durability and retry policy remain unchanged.

Five deterministic diagnostic regressions fail on `c406d70` and pass with the
instrumentation. The ordinary installed workflow still exercises the unchanged
ordered 32 cases and 12 distribution checks. It separately observes one explicit
synthetic request cancellation after child CPU activity through the real forms,
scheduler and frozen worker, with no adapter substitution or repeated experiment.
Its OBSERVED/NOT_OBSERVED result is diagnostic evidence, not an added distribution
gate or historical diagnosis. Exact new-head native and same-bundle-Setup results,
checksums, receipt validation/preflight and any merge are recorded in the owner
ledger only after their real observations.

The recovered local environment again contained pypdf 6.19.0 and editable
metadata 0.11.0. This was identified before running the new full suite; canonical
bootstrap is required. The new unchanged-head outcomes belong in the owner PR.
The existing >32 MiB local complete-bundle transport limitation is retained;
individual downloaded artifacts and remote full-bundle verification have distinct
scopes. No actual publication receipt, kit or readiness exists for this Unreleased
candidate. Future official identity/artifacts still require separately authorized
fresh qualification and publication settlement.

Package/runtime/codename remain 0.12.0/Custodia; all changes remain Unreleased.
**Proposed version: 0.12.1**, a bounded Custodia correction, without assigning it,
renumbering forecasts, creating a tag or publishing. #340's release-delivery criterion
remains open until public payload/receipt/kit/readiness have actually been verified.
