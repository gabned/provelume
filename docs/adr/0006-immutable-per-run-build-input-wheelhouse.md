# ADR 0006: Immutable per-run build-input wheelhouse for offline rebuilds

- Status: Accepted
- Date: 2026-08-23

## Context

ADR 0005 compares package artifacts produced by separately provisioned jobs. Both jobs install exact direct build tools, but their transitive dependencies are still independently resolved from the package index. Matching outputs are useful evidence, yet the jobs could theoretically receive different transitive input bytes or become unreconstructable after an index change.

A maintained repository lock with reviewed hashes is the desired long-term policy. Before introducing that operational process, Provelume can make the dependency bytes immutable within each workflow run: resolve the transitive wheel closure once, identify every wheel by SHA-256, and require both builders to install from that exact bundle without package-index access.

## Decision

A dedicated workflow will create an **immutable per-run build-input bundle**:

1. the candidate job resolves `requirements-build.txt` once using binary wheels only;
2. every wheel filename, size and SHA-256 is recorded in `build-input-manifest.json`;
3. the direct requirements file hash, public source commit and target Python/platform identity are recorded;
4. the candidate build environment is created with `pip --no-index --find-links` from that wheelhouse;
5. candidate wheel/sdist artifacts are built through the deterministic double-build gate;
6. wheelhouse, manifest, package candidate and deterministic report are transferred through the current workflow run;
7. a separately provisioned job recomputes and verifies every wheel identity before installation;
8. the rebuild environment is installed from the verified wheelhouse with package-index access disabled;
9. the package is rebuilt and compared with the candidate;
10. `offline-rebuild-evidence.json` combines the verified input-bundle identity and matching package artifact hashes.

Unexpected non-wheel files, missing direct inputs, symlinks, changed requirements, extra/missing wheels, hash mismatches or source-commit mismatches fail closed.

## Network boundary

Network access is intentionally split:

- candidate dependency resolution may contact the configured Python package index;
- candidate build-tool installation uses only the resolved wheelhouse;
- the second job downloads the candidate bundle from the current GitHub Actions run;
- second-job build-tool installation uses `PIP_NO_INDEX=1` and the verified wheelhouse;
- package builds use `python -m build --no-isolation`, so they do not create a hidden online backend environment.

The workflow does not imply that the Provelume runtime requires network access. This is build infrastructure only.

## Assurance language

A successful workflow supports:

> Candidate and separately provisioned rebuild jobs used the same SHA-256-identified transitive build-input wheel bytes, installed without package-index access, and produced matching Provelume Python package artifacts.

It does not yet support:

- a durable repository-reviewed dependency lock;
- reconstruction after the workflow artifact expires;
- independence from GitHub-hosted infrastructure;
- reproducibility of complete platform releases or future installers.

## Consequences

Positive consequences:

- candidate and rebuild package bytes are no longer compared across independently floating transitive resolutions;
- every transitive build-input wheel is explicit and machine-verifiable;
- offline installation proves the bundle is sufficient for the selected Python/platform target;
- the evidence format can be promoted into official release manifests later.

Costs and limitations:

- the wheelhouse increases workflow transfer/storage size;
- only binary-compatible wheels for the selected environment are accepted;
- the closure is immutable per run, not yet maintained as source-controlled policy;
- pip itself and the base Python distribution remain part of the declared builder environment rather than the wheelhouse.

## Follow-up

The next milestone is to turn successful bundle identities into a reviewed lock/update process with retained hashes and immutable source references. The official tag workflow should then require the offline independent rebuild report before publication and preserve the build-input manifest with the release.
