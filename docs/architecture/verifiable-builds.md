# Verifiable builds

Provelume official Core and self-hosted artifacts must be traceable to public source and a public build workflow.

## Assurance levels

Provelume uses precise terminology:

1. **Traceable build** — an artifact is tied to a public repository, tag/commit and reviewed build workflow; checksums, an SBOM and build provenance are published.
2. **Deterministic build components** — selected build inputs are pinned and can be recreated predictably.
3. **Reproducible release** — an independent rebuild produces equivalent release artifacts where the platform permits it.

The current target is level 1. The project does not claim reproducible releases yet.

## Official source rule

Official Provelume Core and self-hosted artifacts are built only from `gabned/provelume`, from reviewed commits on `main` referenced by public release tags. Private repositories may consume those versioned artifacts but must not build an official hidden Core variant.

## Release chain

The intended chain is:

`public tag -> public commit -> release workflow -> artifact -> SHA-256 -> SBOM -> provenance attestation`

A release manifest records the semantic version, tag, commit SHA, canonical source repository, release channel, build timestamp and artifact/SBOM checksums. The manifest format is provider-independent even when GitHub Releases is the initial distribution channel.

## Artifact attestations

Artifact attestations establish where and how an artifact was built. They do not certify that the artifact is secure. The public GitHub release workflow uses short-lived OIDC identity to create signed provenance and an SBOM attestation for the Python wheel.

Platform-specific code signing, including Windows Authenticode for a future installer or launcher, is a separate later requirement. Long-lived signing keys must not be stored in this repository.

## Verification

For GitHub-hosted public artifacts, users can verify provenance with GitHub CLI artifact-attestation verification. A future Provelume `Verify installation` flow must also support provider-independent and offline verification against downloaded manifests, checksums and attestations where practical.

## Reproducibility status

The Python package currently has version ranges and build tooling whose transitive dependency graph is not fully pinned. Therefore release artifacts are traceable, but the project does not claim byte-for-byte reproducibility. Pinning, independent rebuild comparison and platform signing are later hardening steps.
