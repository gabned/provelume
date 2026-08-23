# ADR 0007: freeze Python distribution build inputs by artifact hash

- Status: Accepted
- Date: 2026-08-23
- Deciders: Provelume maintainers

## Context

ADR 0004 requires two isolated Python distribution builds to use the same
pre-resolved wheelhouse and records the SHA-256 of every build input. That proves
same-run input equality, but a later release could resolve newer transitive
versions while the direct pins remain unchanged.

A deterministic comparison can still pass when both builds consume the same new
transitive package. The result is internally valid, but it does not freeze the
build toolchain across release runs and makes independent reconstruction harder.

The official Python wheel and source distribution are currently certified on
Linux x86-64 with CPython 3.12.14. A target-specific lock is therefore more
honest than pretending one set of binary hashes covers every platform.

## Decision

Provelume will commit `requirements-build.lock` for the certified release target.
The lock must:

1. identify its schema, Python target and platform target;
2. contain the SHA-256 of `requirements-build.txt`;
3. include every direct and transitive build package as an exact `name==version`;
4. include at least one SHA-256 artifact hash for every package;
5. be generated only from wheel METADATA and wheel bytes;
6. reject source distributions, unsafe wheel members, symlinks, duplicate
   projects and conflicting versions.

`requirements-build.txt` remains the human-reviewed list of direct build inputs.
Changing it invalidates the lock until the lock is deliberately regenerated and
reviewed.

Both normal deterministic-build CI and the official release workflow will:

- validate the committed lock against the direct requirements;
- resolve the build wheelhouse with pip `--require-hashes` and wheels only;
- install each isolated builder from that same wheelhouse with hash enforcement;
- record the lock identity and resolved wheel identities in build-comparison
  evidence;
- fail before build or publication on any missing or mismatched artifact.

The lock itself is included in official release assets, `SHA256SUMS`, the release
manifest and provenance attestations.

## Assurance statement

This decision raises the Python distribution component claim to:

> The certified Linux/CPython build uses a reviewed direct toolchain and a
> committed, exact-version, artifact-hash-locked transitive toolchain. Two
> isolated builds from the same public source and locked inputs must produce
> byte-identical wheel and source-distribution artifacts.

It still does **not** prove a complete independently reproducible release because
runner image identity, operating-system packages and an external independent
rebuilder are not yet part of the trust chain.

## Consequences

- dependency updates become explicit reviewable lock changes;
- disappearing or replaced package artifacts fail closed;
- release builds no longer silently absorb new transitive versions;
- the lock is target-specific and must not be presented as a Windows build lock;
- build tooling remains separate from the Provelume runtime dependency set;
- lock regeneration requires package-index access, while locked builds do not
  require an index after the wheelhouse has been materialized.

## Follow-up

Pin the complete hosted runner/container image by immutable identity, publish an
independent rebuild recipe and compare independently rebuilt artifacts. Separate
locks may be introduced only for additional certified build targets that are
actually tested and claimed.
