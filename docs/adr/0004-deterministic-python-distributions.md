# ADR 0004 — deterministic Python distributions

- Status: Accepted
- Date: 2026-08-23

## Context

ADR 0003 established traceable public releases: a semantic tag identifies a reviewed `main` commit and the public release workflow emits checksums, a CycloneDX SBOM, a provider-independent manifest and provenance attestations.

Traceability does not establish that running the same build twice produces the same bytes. The Python build backend was specified with a version range, and normal CI built only one wheel/source distribution pair. Provelume must improve this assurance without overstating the result as an independently reproducible release.

## Decision

For the Python wheel and source distribution:

1. Hatchling is pinned to an exact version in both `pyproject.toml` and release tooling.
2. Hatch reproducible mode is explicit.
3. `SOURCE_DATE_EPOCH` is derived from the public source commit timestamp.
4. The same public source tree is copied into two independent clean workspaces.
5. Both workspaces are built with the same pinned frontend/backend and normalized build environment.
6. Wheel and source distribution filenames, sizes and SHA-256 values must match exactly.
7. CI and the official release workflow fail closed on any mismatch.
8. A versioned `build-determinism.json` evidence file records the source fingerprint, commit, timestamp input, toolchain, platform and both artifact hashes.
9. The evidence file is included in release checksums, manifest assets and provenance attestations.

The first verified artifact pair is copied to the release assembly only after the comparison succeeds.

## Assurance language

A successful check supports this statement:

> The Provelume Python wheel and source distribution were byte-identical across two clean builds of the same public source on the same certified runner/toolchain with the same declared timestamp input.

It does **not** yet support these broader statements:

- the complete release is reproducible on every platform;
- a third party using an independently provisioned environment will necessarily obtain the same bytes;
- transitive runtime or build dependencies are fully locked;
- the future Windows installer/container is reproducible;
- artifact signatures or local installation integrity have been verified by the runtime.

## Consequences

- accidental timestamp/order/toolchain drift becomes a release-blocking failure;
- build evidence is portable and readable without Provelume Cloud;
- official builds remain tied only to `gabned/provelume`;
- builds take longer because distributions are produced twice;
- exact backend updates require an explicit reviewed change;
- independent rebuild comparison, complete dependency locking and platform-specific reproducibility remain later milestones.
