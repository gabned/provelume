# ADR 0001: Filesystem JSON is the first canonical metadata format

- Status: Accepted
- Date: 2026-08-23

## Decision

The first Provelume vertical slice stores canonical metadata as small UTF-8 JSON records and originals as content-addressed files in the Instance directory. SQLite is not authoritative canonical storage.

## Why

This keeps the Instance readable, inspectable, portable and independent from a database server while the public knowledge contract is still evolving. It also makes the canonical/derived boundary testable without GitHub or cloud services.

## Consequences

This is intentionally optimized for correctness and portability rather than very large collections. A future storage engine may add transactional catalogs or alternative backends, but it must preserve the logical contracts and complete export/reconstruction path.
