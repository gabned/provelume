# Historical compatibility and active owners

Historical receipts retain their schema, validator, meaning and result. The pinned
canonical distribution includes the unchanged compatibility corpus and licenses.
Original consumer-specific validators and accepted Git revisions remain available
where their local policy or existing workstreams still depend on them.

Distinguish three steps: installing the canonical engine, migrating authoritative
state, and removing compatibility. A new source pin alone completes none of the
state or cleanup obligations. Preserve AGENT_STATUS release/epic/slice information
when it is only a cache; do not promote it into a new authority. An authoritative
legacy checkpoint remains under its original validator until a supported migration.

A workstream with an existing owner must keep that identity and supported route.
Do not create a second journal for it, manually rewrite its checkpoint, close its
PR, or infer ownership from an idle cache. An explicit handoff must verify the
current owner, grant, exact PR and head, allowed delta, durable source material and
new observable event, and must be idempotent.

The provenance record describes canonical source to vendor mapping. Local cleanup
decisions require evidence of import, CLI, link/anchor, packaging, CI, synchronization,
recovery and indirect uses; a version in a filename does not prove obsolescence.
Preserve unique evidence and unresolved work. Retained shims need a demonstrated
caller, conformance coverage and a removal criterion. No historical tag, release,
failed run or someone else's branch is deleted.
