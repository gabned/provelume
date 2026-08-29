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
performing a network request. The `0.7.0` Vinculum candidate adds validated connector definitions,
isolated instance/Source lifecycle configuration, aligned read-only health views, installed-app
OAuth/PKCE, guarded Source-bound HTTP(S) transport and one explicitly requested manual URL
acquisition; every declaration and execution remains behind the Instance-wide network gate. OAuth
state and the PKCE verifier remain short-lived process memory, canonical connector records accept
only external credential references, and provider-side deletion or movement is not implemented.
Acquired response bytes remain immutable Originals with attributable Source and Acquisition
provenance; readable text is a separate derived artifact.
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
