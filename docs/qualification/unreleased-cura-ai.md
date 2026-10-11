# Unreleased Cura/AI release preparation

Owner branch: `product/cura-ai-release-preparation`, PRODUCT, PR-local legacy route.
Accepted base: `854550fbddb3f0e9e2550e777e2cd708035e2498`.
The accepted Agent Protocol pin remains 1.5.1, source
`1a11fe76712ee65ca2160d2ae3789330946a57f2`; Lifecycle v2 activation remains deferred.
The owner PR ledger records the final head, workflow/attempt/job inventories,
artifact identifiers/hashes, merge identity and actual-main observations.

## Reconciled baseline — 11 October 2026

GitHub main matches the accepted base above. #341 and #342 are merged; #339 is
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

Package/runtime/codename remain 0.12.0/Custodia; all changes remain Unreleased.
**Proposed version: 0.12.1**, a bounded Custodia correction, without assigning it,
renumbering forecasts, creating a tag or publishing. #340's release-delivery criterion
remains open until public payload/receipt/kit/readiness have actually been verified.
