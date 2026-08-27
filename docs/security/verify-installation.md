# Verify installation

Provelume can inspect the installed Python package without using the network or reading
Instance knowledge, configuration or personal files. An operator may optionally provide a
local release bundle and a release-manifest SHA-256 obtained through a separate channel.

## Evidence layers

The result keeps three evidence layers distinct:

1. **Local metadata consistency** — installed package and distribution files agree with the
   installed wheel `RECORD`.
2. **Release-wheel linkage** — a self-consistent release bundle, candidate wheel and internal
   wheel `RECORD` are valid, and installed Core package files agree with the wheel bytes.
3. **Manifest-hash match** — the same verified bundle matches a manifest SHA-256 explicitly
   supplied by the operator.

Layers one and two do not authenticate the publisher. Layer three proves only that the
checked bundle matches the bytes identified by the supplied hash; its trust strength comes
from how the operator obtained that hash. No generic `official` or `safe` verdict is emitted.

## Local RECORD check

For normal wheel installations, Provelume first requires the selected distribution to resolve
to the package tree supplying the running verifier. It validates the local metadata root and
bounded UTF-8 `Name`, PEP 440 `Version` and `direct_url.json`, then streams PEP 376 `RECORD`
under fixed row and line limits. Relevant package/distribution files are checked against their
recorded size and SHA-256 under a cumulative hashing budget. The installed `provelume/`
directory is scanned incrementally for unexpected files and link-like paths.

The top-level states remain backward compatible:

- `package_integrity_verified` — relevant hashed package bytes match and no blocking finding
  exists;
- `modified_installation` — a declared or released Core file is missing, changed, unreadable,
  unsafe or unexpected;
- `verification_unavailable` — required evidence cannot be inspected completely and safely.

Calling the verifier without release options returns the original schema-1 RECORD-only shape.

## Optional release bundle

With `--release-bundle`, the same application service:

1. runs the packaged standard-library release-bundle verifier with the installed version and
   tag as external expectations;
2. selects exactly one candidate Provelume wheel from the verified package identities;
3. rechecks that wheel's size and SHA-256 before inspecting it;
4. validates wheel filename and `METADATA` identity;
5. rejects unsafe, duplicate, case-colliding, encrypted, link-like or unsupported members;
6. validates complete internal `RECORD` coverage, sizes and canonical SHA-256 values;
7. compares installed `provelume/` files directly with hashes computed from wheel members.

Archive members are read in memory and are never extracted. File count, name length, archive
size, member size, cumulative uncompressed bytes, compression ratio, metadata, RECORD line
length and installed hashing all have fixed limits. Symlinks, junctions and filesystem reparse
points fail closed.

Direct comparison with wheel members is independent from the installed `RECORD`. Rewriting a
local `RECORD` to match locally changed bytes therefore cannot conceal divergence from the
verified release wheel.

`release_linkage.status` is one of:

- `verified`;
- `installed_bytes_differ`;
- `verification_unavailable`;
- `bundle_invalid`;
- `wheel_invalid`.

The nested result includes only bundle/wheel identities and counts, not Instance data. A valid
unanchored bundle keeps `origin.status = not_established`. When the operator also supplies a
matching hash, a fully linked result uses:

```text
origin.status = trusted_manifest_sha256_matched
```

This wording records a hash match, not an independent claim about where the hash came from.

## CLI

RECORD-only verification:

```bash
provelume verify-installation
```

Release linkage:

```bash
provelume verify-installation \
  --release-bundle /path/to/provelume-release-bundle \
  --expected-manifest-sha256 <64-hex-digest>
```

The manifest hash is optional, but cannot be used without a bundle. The command prints the
same JSON contract used by the API and performs no writes.

Exit codes:

- `0` — package integrity is verified and every requested release comparison completed;
- `2` — modified installation;
- `3` — verification unavailable or supplied release evidence invalid.

## API

```http
GET /api/v1/security/installation
GET /api/v1/security/installation?release_bundle=/path/to/bundle
GET /api/v1/security/installation?release_bundle=/path/to/bundle&expected_manifest_sha256=<digest>
```

Both query parameters refer to server-local operator input. The endpoint is read-only.

Example release-linked fields:

```json
{
  "schema_version": 1,
  "status": "package_integrity_verified",
  "origin": {
    "status": "not_established",
    "detail": "..."
  },
  "release_linkage": {
    "status": "verified",
    "verified": true,
    "bundle": {
      "verification": "self_consistency_verified",
      "version": "0.3.0",
      "tag": "v0.3.0",
      "source_commit": "...",
      "release_manifest_sha256": "...",
      "externally_anchored": false
    },
    "wheel": {
      "name": "provelume-0.3.0-py3-none-any.whl",
      "sha256": "...",
      "size_bytes": 123456,
      "checked_members": 42,
      "package_files": 31
    },
    "checked_files": 31,
    "unexpected_files": 0,
    "reason": "..."
  },
  "network_used": false
}
```

## Browser

Open `/security/installation`. The EN/IT page accepts the same optional local directory and
manifest hash, presents release linkage separately from publisher authentication, and does
not render raw verifier errors supplied by backend metadata.

## Scope exclusions

The check does not verify:

- the trustworthiness of the channel that supplied a manifest hash;
- a detached signature, key lifecycle or online attestation;
- Python interpreter/base-environment files or console entrypoint scripts;
- installed runtime dependencies against the release SBOM/lock;
- local Instance data, configuration or plugins;
- container layers or Windows installer signatures;
- runtime traffic or operating-system egress.

These exclusions keep reusable Core package evidence separate from mutable local and
platform-specific state.
