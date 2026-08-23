# ADR 0007: Reviewed target-specific build-input lock

- Status: Accepted
- Date: 2026-08-23

## Context

ADR 0006 makes the transitive Python package-build wheel closure immutable within one workflow run. Candidate and rebuild jobs consume identical SHA-256-identified wheel bytes, but the bundle expires with workflow retention and is not itself a durable reviewed repository policy.

The current official package builder is intentionally narrow: GitHub-hosted Ubuntu x86_64 with CPython 3.12.14 produces the platform-independent Provelume Python wheel and source distribution. A target-specific lock can therefore be introduced before broader Windows/container package targets exist.

A durable lock must record artifact bytes rather than only package versions. Exact versions alone do not identify which wheel was installed, and a generic transitive resolver may select newer dependencies without a reviewed source change.

## Decision

Provelume will maintain two synchronized target-lock files under `build-lock/`:

- `ubuntu-py312-x86_64.lock.json` — machine-readable policy and audit metadata;
- `ubuntu-py312-x86_64.requirements.txt` — exact pip-compatible pins with one reviewed SHA-256 per target wheel.

The JSON lock records:

- schema and assurance level;
- canonical public source repository;
- public commit from which the lock was generated;
- target implementation, Python version, operating-system family and machine family;
- SHA-256 of the direct build requirements;
- each resolved distribution name/version;
- exact wheel filename, size and SHA-256;
- wheel `Requires-Dist` metadata;
- a content-derived lock ID.

Creation and verification use `scripts/build_input_lock.py`. The verifier rejects:

- non-exact direct requirements;
- target-environment mismatch;
- empty wheelhouses, symlinks or non-wheel files;
- missing or mismatched direct inputs;
- duplicate distributions;
- changed requirements or wheel bytes;
- extra/missing wheel identities;
- forged lock IDs;
- divergence between JSON and pip-compatible lock files.

Ordinary CI downloads only the exact locked wheel identities with `--require-hashes --no-deps`, recomputes the JSON lock and installs the complete build toolchain with package-index access disabled. It then runs the deterministic package gate.

## Refresh workflow

Lock refresh is a maintainer operation:

1. create or select a repository branch named `lock/**`;
2. update `requirements-build.txt` or explicitly dispatch the refresh workflow on that branch;
3. the workflow resolves one binary target wheelhouse;
4. it generates both lock files and independently redownloads/verifies them;
5. it commits only lock-file changes to the selected `lock/**` branch;
6. normal pull-request review and read-only CI validate the resulting policy before merge.

The refresh workflow has scoped `contents: write` solely because it must update the selected repository lock branch. Its job guard refuses non-`lock/**` refs. Lock-only bot commits do not match the push path filter, preventing recursive refresh.

## Assurance language

A green lock gate supports:

> The declared Ubuntu x86_64 / CPython 3.12.14 Provelume package builder installed the reviewed SHA-256-identified build-input wheels without package-index access and produced deterministic Python package artifacts.

It does not yet support:

- all-platform or all-Python build reproducibility;
- identity of the base runner image, Python distribution or bundled pip beyond their declared workflow versions;
- independence from GitHub-hosted infrastructure;
- reproducibility of future Windows installers, containers or managed-cloud packaging.

## Consequences

Positive consequences:

- changes to the transitive build closure become visible source-review events;
- official package inputs remain reconstructable after a workflow artifact expires, subject to artifact availability or mirroring;
- pip resolution cannot silently float during package builds;
- lock identity can be carried into release manifests and installation verification later.

Costs and limitations:

- lock refresh is target-specific and requires deliberate review;
- package artifacts may later disappear from their original index and therefore need retained mirrors;
- target expansion requires separate locks and CI coverage;
- the lock does not replace code signing or release provenance.

## Follow-up

The official tag workflow should be changed to consume this reviewed lock, require offline independent rebuild evidence before publication, and include the lock ID plus lock files in the release manifest. A subsequent milestone should establish retained/mirrored build-input artifacts and an off-provider verification path.
