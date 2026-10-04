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

## Custodia internal AI Gateway boundary

S05's [CPU candidate runtime](ai-local-runtime.md) uses the existing S01–S04
profile, compatibility and lifecycle boundaries. Internal synthetic qualification
is the only real inference caller. It adds no provider resolver, public dispatch
route or cloud rescue; product execution remains disabled until S06. Linux seccomp
and Windows Job controls have different guarantees. Network qualification needs
external native observations, including the additional CI WFP control on Windows;
a process boundary alone is not an offline claim.

The `0.12/S01` [preflight contract](ai-gateway-preflight.md) now supplies versioned internal
descriptors, independent locality evidence and a pure scope-policy resolver through
`ProvelumeInstance.ai_explain`. It returns only a plan; it opens no Instance, contacts no
provider and grants no execution or canonical-write authority. Its deterministic fake adapter
lives only in synthetic tests, outside the product package. Real inference now requires
the separate [S06 governed-job contract](ai-durable-jobs.md); a preflight plan remains insufficient.

S02 (#314) adds the [bounded context boundary](ai-bounded-context.md): explicitly supplied
exact-Version representation selections, local redaction with disclosed limits, immutable
task templates and closed untrusted-result validation. It does not retrieve more content,
invoke providers or give a manifest/preview/result execution authority. S01 (#312/#313)
remains the only policy resolver. S03 (#316) supplies the internal
[transport and diagnostic boundary](ai-provider-transports.md): one restricted Chat
Completions JSON profile, pinned actual peer, external-secret references and bounded I/O,
exercised with synthetic fixtures. S06 alone binds these adapters to durable jobs; S07 owns
user previews. Configuration/state reads are local; explicit diagnostics establish only
a connection, never model compatibility, authentication, inference or offline assurance.

S04 (#318) supplies the [governed model lifecycle](ai-model-lifecycle.md), including explicit
artifact acquisition/import, byte verification, self-test/internal activation, recovery and
rollback. App/runtime/model identity and candidate/stable/qualification stay separate.
Artifact GET is distinct from inference and preserves web-intake SSRF. Synthetic fixtures
cannot establish managed offline locality or enable product dispatch; S05 chooses the real
runtime and S06 gates execution. S01–S03 are completed through #313/#315/#317.

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

Custodia's base receipt distinguishes plans, denials and synthetic simulations without claiming
transmission. Later Custodia slices extend it for actual bounded derived work; Iudicium (0.13)
adds classification, calibrated confidence and controlled application. No durable AI output is
created by S01.
