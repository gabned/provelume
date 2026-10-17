# ADR 0059 — Evidence-linked objects and an explicit migration boundary

Status: S01 contract/design candidate, #376, parent #375. Not delivery evidence.

Implement Knowledge Objects as closed provider-independent records with immutable
revision chains, exact Version/Original evidence and stable path-independent IDs.
Project and Collection promotion preserves existing IDs. Alias equality never
grants identity-merge permission. Claims remain attributed assertions; evidence
syntax and hashes do not prove factual truth, source availability or review.

Keep S01 validation pure and bounded. Resolve source bytes, relation endpoints,
time-zone rules and current preimages at the later service boundary. Separate
explicit manual canonical writes from removable receipt-bound AI proposals. The
existing Action Center and review authority govern acceptance; no confidence,
model output or record origin grants automatic application.

Introduce the object store only through a separately implemented forward Instance
schema transition. Existing schema-2 binaries do not understand the new canonical
containers; an invisible additive change could produce lossy validation/export.
An explicit boundary makes them fail closed. Require deep preflight, complete
verified backup, staged commit/recovery, preserved hierarchy/Original/Knowledge and
settings/consent/permission bytes, migration receipts and export/import/restore
qualification before acceptance. Downgrade is restoration of the verified old
backup with explicit handling of later changes, never in-place data removal.

Reuse existing lifecycle locks, atomic writer, portability and review contracts;
do not introduce another database, queue, migration journal or runtime provider.
Cura remains primary and Current an explicit reversible backup. No application
identity change occurs until the final Entitas workstream. Published releases,
independent #348 and later release scopes remain unchanged. The complete design
and required later-slice evidence are in
[the Knowledge Objects contract](../architecture/knowledge-objects.md).
