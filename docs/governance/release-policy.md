# Release policy

This policy governs official Provelume Core and self-hosted artifacts.

- Official artifacts are produced only by workflows stored in the public `gabned/provelume` repository.
- Release tags must point to reviewed commits already present on `main`.
- The semantic version in the tag and package metadata must agree.
- CI is separate from release publication: ordinary pull requests and pushes do not create official releases.
- Every official release must publish SHA-256 checksums, a machine-readable SBOM, a release manifest and build-provenance attestations for distributable artifacts.
- License and third-party notices must remain available with the release assets.
- Signing credentials, if long-lived credentials are introduced for platform code signing, must live outside the repository and use least-privilege access.
- All core artifacts must be complete and qualified before publication. A release workflow failure must fail closed: an incomplete payload upload or incomplete publication finalization is never reported as a ready official installation kit.
- GitHub Releases may be the initial hosting provider, but release manifests and verification contracts must not require GitHub-specific identifiers to interpret artifact identity.
- Provelume must not call a build reproducible until independent rebuild equivalence is actually demonstrated.

## Actual publication and installation-kit readiness

Cura S02 adopts the two-phase PRODUCT distribution contract in
[ADR 0029](../adr/0029-offline-publication-receipt.md). Qualified core payloads are published
unchanged. Their actual public event supplies a separate receipt; an outer installation kit
contains those original bytes and the receipt. Receipt and kit receive publisher-workflow
attestations. After every public payload, receipt and kit has been read back and compared, a
separate readiness marker is published and observed. Until then finalization remains pending,
even when the public release already exists. A failed job and its pending summary remain visible.

Recovery reruns only the failed publisher with the same run's qualified bundle and exact source.
It can add missing assets, reuse identical assets and resume the receipt's original observation.
It cannot rebuild payloads, republish the release, move its tag, overwrite assets or manufacture
a successful readiness observation. A conflicting public identity or byte sequence stops recovery.
The observed release asset inventory must be complete and limited to the qualified core bundle
plus its publication receipt, exact-version installation kit and readiness marker. Unexpected
assets, duplicate names or aliases stop recovery and readiness; they are never silently ignored
or removed. Each phase requires its expected files, and existing allowed files still require
unchanged bytes. A marker uploaded before a subsequently failed observation does not grant readiness.
Raw artifacts remain independently verifiable payloads, but require the matching offline receipt
import to constitute a publication-metadata-complete installation. No source/build/install time
is substituted when that evidence is absent. The runtime receipt describes consistency and does
not establish publisher authentication. Historical releases keep their existing verification
contracts; this addition does not retroactively invent publication receipts for them.
