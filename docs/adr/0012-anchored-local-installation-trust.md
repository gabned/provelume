# ADR 0012 — Anchor installed Core bytes to a local release wheel

## Status

Accepted for release 0.3.0.

## Context

ADR 0010 deliberately limits a matching installed wheel `RECORD` to local metadata
consistency. Because that metadata is installed alongside the package, it cannot authenticate
its publisher and can be rewritten together with modified local files.

ADR 0009 defines a bounded provider-independent verifier for release bundles and an optional
operator-supplied release-manifest SHA-256. That verifier proves bundle self-consistency and,
when anchored, equality with the manifest bytes identified by the supplied hash. It did not
previously compare a bundle with a running installation.

## Decision

The shared installation-verification service accepts an optional operator-controlled local
release-bundle directory and manifest SHA-256. The CLI accepts them directly. A server accepts
them only as trusted process-start configuration, computes one verification snapshot at
startup and serves that cached result. Browser and API requests cannot select or change a
server-local path or hash. The service preserves RECORD-only behavior when neither is
supplied.

For a release-linked request, Core:

- invokes the same packaged standard-library bundle verifier that is copied verbatim into
  release bundles;
- requires the bundle version/tag to match the installed distribution;
- selects exactly one declared Provelume wheel and rechecks its identity;
- parses the wheel in memory, with no filesystem extraction;
- validates safe member names/types, bounded archive structure, exact `METADATA` identity and
  complete canonical SHA-256 `RECORD` coverage;
- computes wheel-member digests and compares installed `provelume/` files directly with those
  bytes;
- scans the installed package for files absent from the wheel;
- preserves every existing local RECORD finding rather than replacing it with bundle evidence.

CLI, read-only API and EN/IT browser routes use this one service contract. The HTTP routes
reject client-supplied release-evidence query parameters, do not disclose the configured
local path and never trigger repeated bundle processing. No route reads Instance knowledge
or configuration, and no verification path performs a network request.

## Evidence semantics

The contract exposes release linkage separately from the top-level installation state.

- A self-consistent bundle plus matching installed/wheel bytes yields
  `release_linkage.status = verified` and leaves publisher authentication
  `not_established`.
- A matching operator-supplied manifest hash additionally yields
  `origin.status = trusted_manifest_sha256_matched` only when installed package integrity and
  release linkage are both complete.
- Missing/changed/extra installed files yield `installed_bytes_differ` and a modified
  installation.
- Malformed or unsafe bundle/wheel evidence and incomplete bounded processing never produce a
  positive result.

The manifest-hash state means the checked bundle equals the bytes identified by a hash the
operator supplied independently. It does not assert how that hash was authenticated and is
not a generic `official` or `safe` verdict.

## Safety bounds

The implementation rejects symlinks, junctions, filesystem reparse points, traversal,
absolute/drive-prefixed names, duplicate or case-colliding members, non-regular and encrypted
members, unsupported compression and malformed `RECORD` rows. Fixed ceilings apply to bundle
files, wheel bytes, member count and size, compression ratio, cumulative uncompressed bytes,
metadata/RECORD bytes and lines, findings and installed hashing.

## Consequences

An installed `RECORD` rewritten to match changed local bytes cannot conceal a mismatch with a
verified release wheel. Enterprise mirrors can preserve the same provider-independent bundle
format, and the original RECORD-only check remains useful when no bundle is available.

The browser/API view remains stable for the lifetime of a server process. Operators restart
the process to verify changed release evidence. This is an intentional tradeoff that prevents
unauthenticated HTTP callers from turning local verification into filesystem path probing or
repeated bounded-but-expensive hashing.

This decision does not add signatures or key management, perform online attestation lookup,
verify runtime dependencies/plugins/containers/Windows installers, or observe/enforce network
traffic. Those require separate evidence and policy designs.
