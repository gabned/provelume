# Offline release bundle verification

Provelume release bundles can be checked locally without contacting GitHub,
Provelume Cloud or any external AI provider.

The verifier consumes the provider-independent release files produced by the
official public workflow:

- `release-manifest.json`;
- `SHA256SUMS`;
- Python wheel and source distribution;
- CycloneDX 1.6 SBOM;
- license and third-party notices;
- `build-comparison.json` and its schema when deterministic Python distribution
  evidence is included.

## Run the verifier

From a Provelume source checkout or development environment:

```bash
python scripts/verify_release_bundle.py /path/to/release-bundle
```

For machine-readable output:

```bash
python scripts/verify_release_bundle.py /path/to/release-bundle --json
```

The process makes no network request. Exit codes are stable:

| Exit code | Status | Meaning |
| --- | --- | --- |
| `0` | `verified` | Included identities and contracts are internally consistent |
| `1` | `modified` | Material exists but integrity or contract validation failed |
| `2` | `unavailable` | Required verification material is missing or unreadable |

The JSON result follows `release-verification-result.schema.json`.

## Checks performed

For manifest schema 1, verification includes:

- semantic `version` and matching `vX.Y.Z` tag;
- full 40-character source commit;
- canonical `gabned/provelume` source repository;
- supported release channel, timezone-aware build timestamp and assurance level;
- unique flat filenames safe on Windows and Linux;
- rejection of traversal, drive-relative names and symlinks;
- exact size and streaming SHA-256 verification for every declared file;
- exact checksum coverage with no missing, duplicate or unexpected entries;
- CycloneDX 1.6 SBOM JSON identity and basic structure;
- source/commit/package/artifact consistency of deterministic-build evidence;
- byte identity of both recorded wheel/source-distribution build runs.

An additional local file that is not declared by the manifest produces a
warning. It is not silently treated as official release material.

## Interpret the result

### Verified

The local files match the identities declared by the included release metadata.
When deterministic evidence is present, the result also confirms that its two
recorded build runs agree with the released wheel and source distribution.

### Modified

At least one expected file or metadata contract differs. Findings identify the
problem, such as a digest mismatch, unsafe filename, duplicate checksum entry,
invalid SBOM, source mismatch or inconsistent build comparison.

A modified result does not automatically prove malicious activity. Corruption,
partial downloads and deliberate local customization can produce the same
status.

### Unavailable

The verifier cannot make the integrity comparison because mandatory material is
missing or unreadable. It never reports this as verified.

## Current trust boundary

This first offline verifier proves **internal bundle consistency**. The release
manifest is not yet authenticated by a detached provider-independent signature,
and hosted GitHub provenance attestations are not verified offline by this
command.

Therefore a verified bundle is not yet equivalent to a cryptographically
trusted official installation. The next trust milestone is detached manifest
signing with an offline verification policy, followed by installed-file
comparison for the future **Verify installation** UX.
