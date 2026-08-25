WORKSTREAM_CLASS: SELECT_ONE
PROTOCOL_ESCALATION: NONE

<!--
Replace SELECT_ONE with exactly PRODUCT or PROTOCOL.
PRODUCT covers every non-protocol change. PROTOCOL may touch only the protected
Agent Development Protocol paths. Never combine the two scopes.
-->

## Summary

Describe the public product requirement and the change.

## Change-control evidence

- [ ] The workstream class is exact and matches every changed path.
- [ ] Product and protocol changes are not mixed.
- [ ] If a protocol defect was found during product work, that work stopped and a
      separate `PROTOCOL_ESCALATION` was recorded instead of changing protocol here.
- [ ] No agent-authored emergency waiver is present.

## Boundary check

- [ ] No private Nexus data, secrets, paths, generated knowledge or Git history were copied into this PR.
- [ ] Reusable behavior is in `core/`; instance/deployment concerns are in `instance/`.
- [ ] The change is understandable and testable from this public repository alone.

## Verification

Describe tests/checks performed.
