# Provider and client boundaries

Provelume Core owns durable knowledge contracts. Providers and clients are replaceable consumers or adapters around those contracts.

## Baseline in 0.1

The first vertical slice has no external AI provider and no Git/GitHub runtime provider. Local filesystem ingestion, deterministic extraction, provenance, full-text search, Knowledge API and Knowledge Browser work without either.

The default Instance network configuration records:

```yaml
network:
  external_access: false
  update_checks: false
```

This is a declared baseline, not a claim that the operating system prevents every process from
opening a socket. `provelume network-status`, `GET /api/v1/security/network` and
`/security/network` expose the configuration-derived policy and component inventory without
performing a network request. Filesystem Sources remain the only executable intake type in the
published `0.6.1` product. Active `0.7/S01` and `0.7/S02` add validated connector definitions,
isolated instance/Source lifecycle configuration and aligned read-only health views, but no
connector transport; every such declaration remains behind the Instance-wide network gate.
Unknown Source, connector or provider types stay visibly `undeclared` until their public
capability contract is implemented.

Configured endpoints are transparency metadata, not connection instructions for this read-only surface. Only safe HTTP(S) origins are returned; credentials, paths, query strings and fragments are never surfaced. Runtime traffic observation is explicitly `not_instrumented` and remains separate from declared capability.

## Future AI Gateway boundary

Domain code must request capabilities rather than vendor APIs. Candidate capabilities include:

- `structured_output`;
- `vision`;
- `embeddings`;
- `transcription`;
- `tool_calling`;
- `local_execution`.

The disabled/no-provider state is valid. Core business logic must not call a vendor directly, and a privacy policy such as `local_only` must never silently fall back to cloud inference.

## Derived AI state

Embeddings, vector indexes and technical caches are derived state. They must record enough metadata to be rebuilt with a different model/provider without changing canonical knowledge or provenance.

AI-derived knowledge that becomes durable will require explicit receipts and source references; this is not implemented in the 0.1 vertical slice.
