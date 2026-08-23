# Verifiable builds

Provelume official Core and self-hosted artifacts must be traceable to public source and a public build workflow.

## Assurance levels

Provelume uses precise terminology:

1. **Traceable build** — an artifact is tied to a public repository, tag/commit and reviewed build workflow; checksums, an SBOM and build provenance are published.
2. **Deterministic build components** — selected build inputs are pinned and repeated same-input builds produce output equivalent under a documented criterion.
3. **Reproducible release** — an independent rebuild produces equivalent release artifacts where the platform permits it.

The Python wheel and source distribution have reached a measured level-2 component guarantee on the certified Linux build path. The complete release is not claimed to be reproducible.

## Official source rule

Official Provelume Core and self-hosted artifacts are built only from `gabned/provelume`, from reviewed commits on `main` referenced by public release tags. Private repositories may consume those versioned artifacts but must not build an official hidden Core variant.

## Release chain

The intended chain is:

`public tag -> public commit -> deterministic build check -> artifact -> SHA-256 -> SBOM -> provenance attestation`

A release manifest records the semantic version, tag, commit SHA, canonical source repository, release channel, build timestamp and artifact/SBOM checksums. The manifest format is provider-independent even when GitHub Releases is the initial distribution channel.

## Deterministic Python distribution check

The release pipeline pins Hatchling exactly and enables its reproducible mode explicitly. `SOURCE_DATE_EPOCH` is derived from the tagged public commit. The repository is copied into two independent clean workspaces and each copy produces one wheel and one source distribution with the same normalized environment.

Release assembly continues only when the two wheel hashes and the two source-distribution hashes are byte-identical. The result is recorded in `build-determinism.json`, whose schema is published in `docs/build-determinism.schema.json`.

The evidence contains:

- source repository and optional public commit;
- a source-tree SHA-256 fingerprint;
- `SOURCE_DATE_EPOCH` and its UTC representation;
- Python/platform and exact build frontend/backend versions;
- filename, size and both SHA-256 values for wheel and source distribution;
- an explicit `full_release_reproducibility_claimed: false` boundary.

The normal CI performs this comparison without publishing. The tag release workflow repeats the same check and includes the evidence in release checksums, manifest assets and provenance attestations.

## Artifact attestations

Artifact attestations establish where and how an artifact was built. They do not certify that the artifact is secure. The public GitHub release workflow uses short-lived OIDC identity to create signed provenance for the Python distributions, release manifest and deterministic-build evidence, plus an SBOM attestation for the wheel.

Platform-specific code signing, including Windows Authenticode for a future installer or launcher, is a separate later requirement. Long-lived signing keys must not be stored in this repository.

## Verification

For GitHub-hosted public artifacts, users can verify provenance with GitHub CLI artifact-attestation verification. `SHA256SUMS`, `release-manifest.json`, the CycloneDX SBOM and `build-determinism.json` remain ordinary portable files.

A future Provelume `Verify installation` flow must support provider-independent and offline verification against downloaded manifests, checksums and attestations where practical.

## Remaining reproducibility gaps

The measured check proves byte identity for two builds performed on the same certified Linux runner/toolchain and source/timestamp input. It does not yet prove an independent third-party rebuild.

Remaining work includes:

- locking or otherwise recording the complete transitive build environment;
- comparing builds performed in independently provisioned jobs or environments;
- defining equivalence for container and future Windows artifacts;
- eliminating or documenting nondeterminism outside the Python wheel/source distribution;
- adding offline manifest signing and verification;
- publishing a third-party rebuild procedure.

Claims of a **reproducible release** remain prohibited until those broader criteria are demonstrated.
