# Verify a Provelume release bundle offline

Every future official release bundle includes `verify-provelume-release.py`. The tool uses only the Python standard library and performs no network requests.

## Basic integrity check

Download all release assets into one clean directory and run:

```bash
python verify-provelume-release.py --root .
```

A successful unanchored result says:

```text
Result: self_consistency_verified
Origin authentication: not_established_by_bundle_alone
Network used: no
```

This is meaningful: the tool has recomputed checksums, manifest identities, package/build evidence, lock identities and the exact bundle file set. It is not an origin signature. A completely replaced bundle could contain a matching replacement verifier and manifest.

## Verify against a trusted manifest hash

Obtain the SHA-256 of `release-manifest.json` through a channel you trust independently from the downloaded bundle. Then run:

```bash
python verify-provelume-release.py \
  --root . \
  --expected-manifest-sha256 <64-hex-digest>
```

You may also pin the expected public identity:

```bash
python verify-provelume-release.py \
  --root . \
  --expected-manifest-sha256 <digest> \
  --expected-version 0.1.0 \
  --expected-tag v0.1.0 \
  --expected-commit <full-public-commit-sha>
```

A matching cryptographic anchor produces:

```text
Result: externally_anchored_bundle_verified
Origin authentication: trusted_release_manifest_sha256
```

The trust strength is inherited from the channel that supplied the expected hash. A future provider-independent manifest signature will provide a stronger standardized anchor.

## JSON output

For audit tooling:

```bash
python verify-provelume-release.py --root . --json
```

The JSON result includes:

- result and origin-authentication state;
- version, tag, channel and public commit;
- release-manifest SHA-256;
- reviewed build-lock ID;
- package identities;
- checksummed file count;
- explicit limitations;
- `network_used: false`.

Failures return exit code 1. With `--json`, failures are emitted as a JSON object instead of human-readable stderr.

## What is checked

The verifier rejects:

- missing required assurance files;
- nested directories, symlinks, junctions, reparse points or unsafe filenames;
- oversized metadata/artifacts or excessive bundle cardinality;
- malformed or duplicate checksum entries;
- checksum, manifest or SBOM mismatches;
- source/version/tag/commit divergence;
- a failed or unsupported release-assurance record;
- package hashes that differ among candidate, rebuild and offline evidence;
- forged build-lock IDs or JSON/requirements lock divergence;
- per-run wheel identities that differ from the reviewed lock;
- offline evidence without `--no-index` installation proof;
- candidate identity or source-epoch mismatch;
- extra untracked files.

## Additional online verification

GitHub/Sigstore attestations remain an additional origin/provenance check for the initial distribution provider. Use them when network access and the GitHub CLI are acceptable. The offline verifier intentionally contains no GitHub-specific business logic and remains usable with release mirrors or another future hosting provider.

## Link the bundle to an installed Core package

The standalone tool verifies a downloaded release bundle but does not inspect an installation.
The installed `provelume verify-installation --release-bundle <directory>` service reuses the
same verifier contract, validates the candidate wheel and internal `RECORD` in memory, and
compares installed Core package files with wheel bytes. An optional independently obtained
manifest SHA-256 can anchor that comparison. A server operator may configure the same evidence
through `provelume serve --release-bundle`; the server computes it once at startup. Remote API
or browser clients cannot submit server-local paths.

Neither path verifies runtime dependencies, local configuration/plugins, containers or future
Windows code signing.
