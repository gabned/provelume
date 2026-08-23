# ADR 0004: Deterministic Python package artifacts in a controlled build environment

- Status: Accepted
- Date: 2026-08-23

## Context

ADR 0003 established a traceable official-release chain from a reviewed public tag and commit to built artifacts, checksums, SBOM, release manifest and attestations. Traceability proves where an artifact came from, but it does not prove that rebuilding the same source produces the same bytes.

The first public Provelume deliverables are a Python wheel and source distribution. These are narrow enough to test determinism before Windows installers, container images and other platform packaging are introduced.

A full reproducible-release claim would require more evidence than one CI run: hash-locked transitive build inputs, independently provisioned builders and equivalent results across supported reconstruction environments. Those conditions are not yet satisfied.

## Decision

Provelume will add a fail-closed deterministic package gate with this contract:

`same public source commit + same exact direct build tools + same SOURCE_DATE_EPOCH -> two separate builds -> byte-identical wheel and sdist`

The gate:

1. pins Hatchling exactly in `pyproject.toml` and in the controlled build requirements;
2. uses the exact `build` frontend already selected for releases;
3. builds without an implicit isolated backend that could float independently of the declared toolchain;
4. derives `SOURCE_DATE_EPOCH` from the checked-out source commit;
5. builds wheel and source distribution twice into separate temporary directories;
6. compares filenames, sizes and SHA-256 digests;
7. refuses to continue when any output differs;
8. emits `deterministic-build-report.json` with the source identity, environment, tool versions, artifact hashes and explicit limitations;
9. includes that report in the release manifest, checksums and build-provenance attestations.

The same gate runs in ordinary pull-request CI without publishing a release. Official tag builds rerun it before any GitHub Release is created.

## Assurance language

A successful report supports this statement:

> The Provelume Python wheel and source distribution were byte-identical across two builds of the same commit in the declared controlled build environment.

It does not support these broader statements yet:

- the complete Provelume release is reproducible;
- any third party can reproduce the hashes on an arbitrary machine;
- future Windows installers or container images are deterministic;
- every transitive build dependency is hash-locked.

## Consequences

Positive consequences:

- nondeterministic package metadata or archive output blocks publication;
- package determinism becomes continuously tested rather than documented as an aspiration;
- release consumers receive machine-readable evidence tied to the attested public source chain;
- later independent rebuild work has a stable comparison contract.

Costs and limitations:

- official package builds perform two full package builds;
- direct build tools are exact, but their transitive closure remains a later hardening task;
- the first comparison uses one provisioned Ubuntu builder and Python 3.12.14;
- platform-specific packaging needs its own evidence and signing model.

## Follow-up

The next reproducibility increment should hash-lock the transitive build dependency closure and compare a release candidate against an independently provisioned rebuild. Only after that evidence exists should public documentation consider a broader reproducible-build claim.
