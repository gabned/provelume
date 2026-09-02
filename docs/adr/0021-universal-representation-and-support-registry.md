# ADR 0021 — Universal representation and support-registry contract

Status: accepted for `0.10/S01`

## Context

Lectio publishes document, OCR, email, Google-read-only, transcript and cross-source-finding
contracts. They preserve the same authority boundary but describe support and derived outputs with
profile-specific vocabulary. Adding media parsers directly to those contracts would make
Preserve look equivalent to Inspect, Extract, Preview or enrichment and would make rebuild and
portable-transfer behavior difficult to verify.

## Decision

Provelume defines `provelume.representation-bundle` schema version 1 and
`provelume.representation-support.v1` as additive, first-party contracts. A bundle identity binds
one exact DocumentVersion and Original checksum to one recipe fingerprint and one output
fingerprint. Component/adapter identity, settings, warning codes, lifecycle, availability with a
closed degraded/unavailable reason, parent and previous representations, reversible corrections,
exact anchors and closed limits travel with the bundle. Public domain enums and separate JSON
Schemas cover both the bundle and support registry.

Preserve, Inspect, Extract, Preview, Local enrich and AI enrich are independent registry rows for
every profile. Declared support, effective support and a missing component are separate fields.
Unavailable and degraded states use a closed reason. `AI enrich` is always unavailable with
`not_implemented`; S01 contains no AI execution path.

Page, time and region anchors are validated now. Slide, sheet, cell, member and symbol are
reserved anchors only: their target must say `reserved: true`, which does not claim support for an
office, archive or programming format.

Native bundles live only under `state/derived/representations/<representation-id>/`. Existing
Lectio bundles and schema-2 Instance records are projected through a compatibility view and remain
byte-unchanged. A new recipe creates a different representation. Removal retains a derived
history receipt; an equivalent rebuild must reproduce the same identity and bytes.

The service, CLI, API and Browser call one `RepresentationReadModel`. Reads are offline and do not
create, repair or migrate state.

## Consequences

- Originals, canonical records and provider data remain authoritative and immutable.
- Native bundles are included in backup and in the portable `state_artifacts: include` boundary;
  restore/import deep-validation rejects invalid or missing output bytes.
- Path, case, file/directory collision, count, byte, total-size and expansion limits fail closed.
- No Instance schema migration or Original-adjacent Markdown sidecar is introduced.
- Photo, audio, video, AI and additional-format implementation remains outside S01.
