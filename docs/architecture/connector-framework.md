# Connector framework and local lifecycle

Provelume `0.7/S01` introduces a provider-independent local configuration and conformance boundary.
`0.7/S02` adds bounded multi-instance lifecycle mutations, path-redacted evidence and aligned
service/CLI/read-only API/EN/IT Browser views. `0.7/S03` adds an installed-app OAuth 2.0/PKCE
authorization boundary with synthetic adapters only. These slices do not implement provider HTTP
transport, a callback server, background refreshes or executable adapter loading from a manifest.
Issue #105 owns the complete `0.7.0` release; guarded transport and manual web acquisition remain
later homogeneous slices.

## Identity boundary

Three identities remain separate:

- a `ConnectorDefinition` identifies one reusable adapter contract and its versioned capability
  manifest;
- a `ConnectorInstance` binds one definition to one provider identity, optional account identity,
  optional primary endpoint origin, independent endpoint allowlist, authorization mode, scope set,
  external credential reference, redacted authorization metadata, local network policy, empty
  pre-refresh cursor envelope and local health state;
- a canonical `Source` belongs to exactly one connector instance and identifies one independently
  selected provider resource.

Connector instances use `connector_instance_<uuid>` identities. Connector Sources retain the
existing `src_<uuid>` namespace and use `kind: connector`; they do not replace filesystem Sources.
Every definition requires `multi_instance: true`, so an adapter cannot rely on a process-wide
singleton account.

Definitions and instances are additive schema-2 canonical state under
`knowledge/connector-definitions/` and `knowledge/connector-instances/`. Connector Sources remain
under `knowledge/sources/`. Existing schema-2 Instances need no rewrite: missing additive connector
directories are valid and are created on first use. Deep validation, local backup/restore and
portable export/import include every connector record.

S01 connector-instance and Source records use record schema 1. S02 keeps them readable and deeply
valid without rewriting them. S02 Source mutations use lifecycle schema 2. S03 connector-instance
creates and mutations use authorization schema 3, adding only the redacted `authorization`
envelope. Schema-1 and schema-2 connector instances remain readable and deeply valid; only the
exact record first changed after S03 is upgraded. Definitions remain manifest schema 1. This lazy,
per-record transition avoids an Instance migration and preserves stable IDs.

## Versioned capability manifest

Registration accepts exactly one JSON object with the following version-1 shape:

```json
{
  "adapter_key": "example-web",
  "adapter_version": "1.0.0",
  "display_name": "Example web adapter",
  "provider": "provider-independent",
  "conformance_profile": "provelume.connector.v1",
  "adapter_protocol_version": 1,
  "capabilities": ["conditional_metadata", "manual_read", "source_selection"],
  "authorization_modes": ["none"],
  "source_kinds": ["web"],
  "data_categories": ["source.content", "source.metadata"],
  "multi_instance": true,
  "network_access": "explicit_only"
}
```

The initial closed capability vocabulary is `manual_read`, `conditional_metadata`,
`source_selection`, `external_secret_authorization` and `oauth2_pkce_authorization`. The initial
Source kind is `web`; supported authorization declarations are `none`, `external_secret` and
`oauth2_pkce`. A manifest declares and validates an adapter contract, but registration alone does
not install executable code or prove later network/OAuth conformance.

Unknown fields, capabilities, protocol versions and non-multi-instance manifests fail closed. A
definition ID is deterministic from its adapter key. Re-registering identical content is
idempotent; changing an existing definition under the same identity is rejected.

## Network and secret policy

Each connector instance declares `network_mode: disabled` or `network_mode: explicit`. Explicit
mode requires at least one canonical HTTP(S) origin and a definition with `manual_read` capability.
Origins contain only scheme, host and optional non-default port: credentials, paths, queries,
fragments, whitespace and non-HTTP schemes are rejected. This allowlist is configuration evidence,
not a claim that the later guarded transport has approved an address; SSRF, reserved-address,
DNS-rebinding and redirect enforcement belongs to `0.7/S04`.

The Instance-wide `network.external_access` flag remains the stronger gate. A connector may be
prepared with explicit local policy while the global flag is false, but its effective network mode
is disabled and `network-status` reports the conflict. Every S01 command reports
`network_attempted: false` and no S01 path resolves DNS or opens a connection.

Credential material is never accepted in a connector record. The only supported value is an
external reference with exactly two fields:

```json
{"kind": "environment", "name": "PROVELUME_EXAMPLE_TOKEN"}
```

The alternative kind is `system_keyring`. Values, tokens, passwords, client secrets, file paths and
arbitrary reference fields are rejected. Network-status output omits the reference entirely.

## Installed-app OAuth 2.0/PKCE boundary

OAuth begins only for an active, enabled connector instance whose definition declares
`oauth2_pkce_authorization`, whose authorization mode is `oauth2_pkce`, whose least-privilege scope
set is non-empty and whose connector plus Instance-wide network policy both allow explicit access.
The adapter identity and version must exactly match the registered definition. Its declared HTTPS
authorization and token endpoint origins must both already be members of the instance allowlist.
This is an authorization-specific declaration check, not the guarded DNS/redirect/SSRF transport
implemented later in S04.

The installed app supplies an explicit consent decision and one canonical high-port loopback
callback URI. Core creates a cryptographically random, short-lived state and RFC 7636 S256 verifier,
retains both only in process memory and returns a transient authorization URI. State lives for five
minutes by default and never more than ten minutes. The URI must preserve the exact redirect, state,
challenge, `response_type=code`, exact sorted scope set and explicit consent binding. Core does not
open a browser, listen on the callback port or perform an HTTP request in this slice.

Scope values use the bounded RFC 6749 `scope-token` ASCII grammar. They remain case-sensitive and
may therefore contain provider forms such as `user:email`, `Files.Read` and URL-shaped Google
scopes; spaces, quotes, backslashes, controls, non-ASCII text and oversized tokens/sets fail closed.

Callback completion requires the same request identity, state, redirect URI, adapter identity,
adapter version and exact configured scope set. A valid-state callback is consumed before adapter
exchange, so success and every later validation/exchange failure are non-replayable. Unknown,
expired, mismatched and already-consumed state fails closed. The token-exchange extension point is
rechecked against current policy immediately before invocation; S03 ships no real provider adapter
and proves the contract only with deterministic synthetic adapters.

An adapter result has exactly three fields: an external environment/keyring reference, an optional
redacted provider account identity and the exact granted scope set. Returning an access/refresh/ID
token, authorization code, verifier, client secret, password or any extra field is rejected before
canonical mutation. Successful completion stores only the external reference and schema-3 metadata:
status, OAuth method, authorization time, loopback binding and explicit-consent marker. State,
authorization URI, code, verifier and credential material are never canonical or derived state.

Reauthorization repeats the complete boundary and may replace only the external credential
reference and redacted account/authorization metadata. Local revocation cancels pending requests,
clears the reference and records a redacted revocation timestamp; it deliberately performs no
provider-side mutation. Changing the account, mode or scopes of an authorized instance requires
revocation first. Neither operation disables/removes Sources or touches Acquisitions, Documents,
Versions, provenance or Original bytes.

Begin, callback exchange/completion and revocation share one in-process mutex per connector
instance. A callback that starts first commits before a waiting revocation, which then clears its
reference; a revocation that starts first cancels the pending callback. Successful completion also
invalidates sibling requests before releasing the mutex. Thus parallel callbacks invoke at most one
adapter exchange for one unchanged connector record, and revocation cannot be overtaken by an
already-consumed in-flight callback. Revocation before first authorization is itself recorded as a
redacted revoked state, changing the canonical fingerprint so a pending callback held by another
process-local service instance cannot later authorize against stale policy.

The provider adapter exchange remains outside the Instance-wide connector-configuration lock.
Independent connector exchanges may therefore overlap; only their short canonical commits are
serialized by a process-local Instance mutex and the existing cross-process configuration lease.
The per-connector callback mutex remains held through exchange and commit, so this does not permit
sibling callbacks or a same-process revocation to overtake completion.

## Lifecycle and preservation boundary

Connector instances and each selected Source have independent `enabled` state. Disabling a parent
fails its effective network policy closed but does not rewrite child configuration. Disabling a
Source affects only that selection. Re-enabling retains the same stable identity and policy.
The optional primary endpoint can likewise be cleared without clearing or implicitly reselecting
the separate origin allowlist; legacy S01 records retain their first-origin derived view until that
exact instance is upgraded.

Removal is a terminal canonical tombstone, not a filesystem delete. A Source tombstone remains
under `knowledge/sources/`, so existing Documents and Acquisitions retain a valid Source reference.
An instance may be removed only after every child Source has been removed independently; both the
instance and Source tombstones then remain available for provenance and portable transfer. No
lifecycle method calls Original storage, Document retention or purge. Permanent erasure remains the
separate preview-bound retention contract.

Every mutation is serialized by the Instance-local `connector-configuration` lock and uses atomic
canonical JSON replacement for the one selected record. A path-redacted operation record reports
the mutation kind, stable related IDs, changed field names and zero Original deletions/overwrites.
It never records provider/account values, endpoint origins, external credential-reference names,
physical paths or secret material.

Authorization-boundary evidence additionally records only PKCE method, redirect-binding kind,
consent marker, scope count, state lifetime, external-reference storage and zero Original mutation.
It never records the authorization URI, state, code, verifier, callback payload, credential
reference name or adapter grant. Failure evidence contains only a closed exception class and the
same zero-Original metrics.

## Cursor and health boundary

Each lifecycle-schema-2 or authorization-schema-3 instance owns a separate `cursors: {}` envelope.
S02 requires that it stay empty: it does not invent cursor tokens, conditional checkpoints, jobs,
retries or refresh state before the later transport/refresh contracts exist. This reserves an
isolated per-instance boundary without anticipating `0.8.0`.

Canonical local health is limited to `not_checked`, `disabled` or `removed`, with no check
timestamp. The shared service view may additionally report `policy_blocked` when the instance asks
for explicit access while the stronger Instance-wide policy disables external access. All health
views report `network_attempted: false`; they are configuration health, not observed provider or
traffic health.

## Local interfaces

The local CLI exposes the foundation and lifecycle commands:

```text
provelume connector-definition-register INSTANCE MANIFEST.json
provelume connector-instance-create INSTANCE DEFINITION_ID [policy options]
provelume connector-instance-show INSTANCE CONNECTOR_INSTANCE_ID
provelume connector-instance-update INSTANCE CONNECTOR_INSTANCE_ID [policy options]
provelume connector-instance-enable|disable|remove INSTANCE CONNECTOR_INSTANCE_ID
provelume connector-source-add INSTANCE CONNECTOR_INSTANCE_ID [Source options]
provelume connector-source-show INSTANCE CONNECTOR_INSTANCE_ID SOURCE_ID
provelume connector-source-update INSTANCE CONNECTOR_INSTANCE_ID SOURCE_ID --name NAME
provelume connector-source-enable|disable|remove INSTANCE CONNECTOR_INSTANCE_ID SOURCE_ID
provelume connector-inventory INSTANCE
```

Mutation commands only validate and atomically write local records. The same application-service
read models back `GET /api/v1/connectors`, instance/Source detail endpoints and the EN/IT
`/connectors` Browser inventory/detail pages; HTTP exposes no connector mutation route. Views
contain no exclusive business logic and never change Instance state. S03 exposes begin, complete
and local revoke contracts through the in-process application service so the same installed-app
process retains its short-lived state; it adds no unauthenticated HTTP or split-process CLI mutation
surface.

Guarded HTTP transport and manual acquisition belong to `0.7/S04` and `0.7/S05` respectively.
Background scheduling, polling, token refresh and renewal remain excluded.
