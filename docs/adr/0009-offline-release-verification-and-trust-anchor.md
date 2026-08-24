# ADR 0009: Offline release verification and explicit external trust anchor

- Status: Accepted
- Date: 2026-08-23

## Context

The release pipeline now emits a provider-independent manifest, checksums, reviewed build lock and deterministic/independent/offline rebuild evidence. Those files are useful outside GitHub, but a user still needs a simple way to validate a downloaded bundle without installing Provelume or contacting a network service.

A verifier shipped inside the same bundle can detect accidental corruption and internal inconsistency. It cannot, by itself, authenticate that the bundle is genuinely official: an attacker able to replace all files can also replace the verifier, manifest and checksums. Treating self-consistency as authenticated origin would create a false green state.

GitHub artifact attestations provide an initial provider-specific origin check. The architecture also requires a provider-independent path so releases can later move to another host or be mirrored without changing the trust model.

## Decision

Every official release bundle will include a self-contained Python standard-library verifier named `verify-provelume-release.py`.

The tool performs no network requests and verifies:

- a flat regular-file bundle with bounded file count and metadata/artifact sizes;
- no symlinks, path traversal names or duplicate checksum entries;
- every `SHA256SUMS` identity;
- release-manifest artifact and SBOM identities;
- source repository, semantic version, tag, channel and full public commit consistency;
- a passed `release-assurance.json` publication gate;
- package artifact identities across deterministic, rebuild, independent and offline reports;
- the content-derived reviewed build-lock ID and JSON/requirements lock equivalence;
- per-run build-input manifest and offline wheel identity consistency;
- candidate identity and source epoch;
- an exact bundle file set with no untracked additions.

The verifier supports optional external expectations for version, tag and commit plus an optional trusted SHA-256 of `release-manifest.json`.

## Result states

Without an external cryptographic anchor, a green result is:

`self_consistency_verified`

and explicitly reports:

`origin_authentication: not_established_by_bundle_alone`

When the caller supplies a matching manifest SHA-256 obtained independently from the bundle, the result is:

`externally_anchored_bundle_verified`

with:

`origin_authentication: trusted_release_manifest_sha256`

This confirms that the bundle matches the externally trusted manifest bytes. It does not imply a signature/key policy unless the source of that hash is itself authenticated.

## Distribution

The verifier is copied into the final release bundle and is itself included in the release manifest and `SHA256SUMS`. This protects it from accidental or partial modification once the manifest is trusted, but does not create circular self-authentication.

The repository continues to provide GitHub/Sigstore attestation verification as an additional online provider-specific check. The offline tool deliberately does not implement network access or a GitHub client.

## Consequences

Positive consequences:

- users can validate bundle integrity with only Python and local files;
- internal evidence inconsistencies fail closed and are explained;
- the UX language distinguishes corruption detection from origin authentication;
- enterprise mirrors can preserve the same bundle format;
- a future signed manifest can reuse the verifier's existing external-anchor boundary.

Costs and limitations:

- Python must be available to run the standalone verifier;
- origin authentication still requires an independently trusted hash or provider-specific attestation;
- the verifier currently validates release bundles, not an installed Core file inventory;
- the current build evidence covers the declared Python package target.

## Follow-up

Define a provider-independent signing key, rotation/revocation policy and detached signature format for `release-manifest.json`. Then extend the verifier to validate that signature offline and reuse the same library for `Settings -> Security -> Verify installation` once installed Core manifests are available.
