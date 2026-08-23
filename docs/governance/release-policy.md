# Release policy

This policy governs official Provelume Core and self-hosted artifacts.

- Official artifacts are produced only by workflows stored in the public `gabned/provelume` repository.
- Release tags must point to reviewed commits already present on `main`.
- The semantic version in the tag and package metadata must agree.
- CI is separate from release publication: ordinary pull requests and pushes do not create official releases.
- Every official release must publish SHA-256 checksums, a machine-readable SBOM, a release manifest and build-provenance attestations for distributable artifacts.
- License and third-party notices must remain available with the release assets.
- Signing credentials, if long-lived credentials are introduced for platform code signing, must live outside the repository and use least-privilege access.
- A release workflow failure must fail closed: incomplete artifacts are not published as an official release.
- GitHub Releases may be the initial hosting provider, but release manifests and verification contracts must not require GitHub-specific identifiers to interpret artifact identity.
- Provelume must not call a build reproducible until independent rebuild equivalence is actually demonstrated.
