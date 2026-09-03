# ADR 0027: integrated Perceptio read model

- Status: accepted for `0.10/S07`
- Date: 2026-09-03
- Parent: #160
- Slice: #180 / owner PR #182

## Decision

Add one `provelume.perceptio-read-model.v1` projection over the already accepted photo, audio,
video and file-family managers, universal representation bundles and component inventory. The
service, CLI, GET-only API and EN/IT Browser consume that projection. It exposes support,
availability, provenance, implementation identity, warnings, reversible correction annotations,
anchors and derived outputs while keeping the candidate explicitly unpublished.

S07 adds no mutation command, worker, parser, profile, codec, model, native payload, provider,
network route or migration. Existing family surfaces remain the detailed gallery/player/table
views; Perceptio makes their evidence journey coherent and links to them. Text stays escaped and
all deep bundle validation happens before projection.

## Consequences

- The integrated surface cannot make a package or publication claim by itself.
- A malformed or non-Perceptio bundle is omitted, not reinterpreted.
- Existing remove/rebuild, backup/restore and portable-transfer paths remain authoritative.
- Version alignment, final SBOM comparison, tag creation and asset publication remain a separate
  reviewed release-boundary workstream.
