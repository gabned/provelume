# ADR 0008: Release publication only after offline independent rebuild evidence

- Status: Accepted
- Date: 2026-08-23

## Context

The first official release workflow established traceability from a reviewed public tag to package artifacts, checksums, SBOM and attestations. Subsequent ADRs added same-run deterministic package builds, a separately provisioned rebuild, an immutable per-run wheelhouse and a durable reviewed Ubuntu/CPython build-input lock.

Those controls existed as independent workflows. A tag publication could still execute the original single-job release workflow without making the newer offline independent rebuild a hard predecessor. The privilege boundary was also broader than necessary because artifact construction, attestation and GitHub Release publication occurred inside one job.

The publication path must be structurally incapable of using release privileges before the complete evidence chain is green.

## Decision

Provelume will use one reusable multi-job release assurance pipeline for both read-only pull-request validation and official tag releases.

The pipeline has four stages.

### 1. Locked candidate

A read-only job:

- verifies tag/package identity for official invocations;
- verifies that an official tag commit is already on public `main`;
- reruns lint and tests;
- downloads only the committed reviewed build-wheel hashes;
- verifies the JSON/pip lock pair;
- installs build tooling without package-index access;
- builds wheel and sdist twice and requires byte identity;
- emits candidate, deterministic and build-input evidence.

### 2. Offline second-runner rebuild

A separately provisioned read-only job:

- checks out the same public commit;
- downloads the candidate through the current workflow run;
- verifies the reviewed lock and transferred wheelhouse;
- installs build tooling offline from those exact bytes;
- rebuilds twice;
- recomputes candidate/rebuild identities;
- emits independent and offline rebuild evidence.

### 3. Read-only assembly

A third read-only job:

- downloads both evidence sets;
- runs `release_assurance.py` to validate the complete source/lock/wheelhouse/package chain;
- installs the candidate wheel in a clean runtime environment and generates a CycloneDX SBOM;
- assembles all package, license, lock and evidence assets;
- creates the provider-independent release manifest and SHA-256 file;
- reverifies every declared bundle identity;
- uploads a verified release bundle.

This stage runs in pull-request dry runs and official releases. It cannot publish.

### 4. Privileged publication

A final job exists only when the reusable workflow is invoked with `publish: true`. It alone receives:

- `contents: write`;
- OIDC `id-token: write`;
- `attestations: write`;
- `actions: read` for the verified bundle.

It downloads the already assembled bundle, reverifies it, creates provenance/SBOM attestations and publishes a non-overwriting GitHub Release. No build or dependency-resolution step occurs after the privilege boundary.

## Reusable validation

A path-filtered pull-request workflow invokes the same pipeline with `publish: false`. It exercises candidate, second-runner rebuild and final assembly without any release/attestation permissions. The old standalone rebuild workflows are removed to avoid divergent controls and repeated CI work.

## Evidence contract

`release-assurance.json` is the final publication decision record. It links:

- version, tag, channel and public commit;
- reviewed build lock ID and target;
- committed lock files and per-run input manifest identities;
- candidate package hashes;
- deterministic, independent and offline evidence hashes;
- an explicit `publication_gate: passed` result;
- current limitations.

`verify_release_bundle.py` then verifies the release manifest, assurance identity, SHA256SUMS and required evidence files before privilege use.

## Assurance language

A successful official workflow supports:

> The published Provelume Python package artifacts were built from the reviewed public tag using the reviewed target build-input lock, matched an offline rebuild on a separately provisioned runner, and were attested only after the complete evidence bundle passed read-only verification.

It does not yet prove:

- reconstruction outside the GitHub-hosted CI provider;
- reproducibility of runtime dependency resolution;
- reproducibility or code signing of future Windows installers and launchers;
- reproducibility of container or managed-cloud deployment images.

## Consequences

Positive consequences:

- official publication cannot bypass the independent rebuild gate;
- privileged steps consume artifacts rather than execute untrusted build logic;
- dry-run and official paths share one implementation;
- the release bundle carries the evidence needed for later offline verification;
- duplicate standalone workflows can be retired.

Costs and limitations:

- an official release uses several jobs and transfers package/evidence artifacts between them;
- runtime dependency installation for SBOM generation remains separately declared rather than covered by the package build lock;
- GitHub Actions remains the first attestation/publication provider;
- future platform packages require analogous gates.

## Follow-up

The next trust milestone is retained/mirrored build-input artifacts plus an off-provider verifier capable of reconstructing or validating the release bundle without relying on GitHub-hosted runners. Windows lifecycle work must add platform code signing and package-specific rollback evidence without weakening this Core release chain.
