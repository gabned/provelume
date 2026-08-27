# ADR 0011 — Declared network capability transparency

## Status

Accepted for the 0.2.0 development line. No 0.2.0 release is implied by this status.

## Context

The baseline Provelume Instance is useful offline and defaults to `external_access: false` and `update_checks: false`. Future Sources, connectors and providers may be network-capable, but neither a disabled default nor the absence of telemetry proves that no runtime traffic occurred. Physical Source paths and credential-bearing endpoint details are also private operator configuration.

Provelume needs one read-only contract that can answer what the current configuration permits and declares before networked integrations become normal runtime behavior.

## Decision

Core derives a schema-versioned network-status result from `provelume.yml` and exposes it consistently through CLI, read-only API and EN/IT browser surfaces.

- The built-in update checker is a registered external-capability type.
- Filesystem Sources are registered `local_only` components; their physical paths are never returned.
- Unknown Source, connector and provider types are `undeclared` with unknown capability. They are never inferred to be local.
- Configured HTTP(S) endpoints are reduced to origins. User information, paths, queries and fragments are not returned.
- Data categories are returned only when explicit valid identifiers are configured.
- Enabled external components conflict with `external_access: false`.
- Enabled update checks without a declared endpoint conflict.
- Malformed policy and component declarations fail visibly.
- The result records `network_used: false` for the read operation and `observed_activity: not_instrumented` for runtime traffic.

The implementation performs no socket operation and no configuration, canonical or derived-state mutation.

## Consequences

The default Instance reports `local_only` with zero enabled external components. Operators can inspect configuration conflicts without granting network access, and future adapters have an explicit registration point rather than receiving an accidental local-safe classification.

This surface does not enforce operating-system egress, audit packets or prove zero traffic. A later bounded event-audit design may add observed activity to the same interface, but it must preserve the distinction between configured capability and measured events.
