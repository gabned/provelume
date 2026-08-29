# Connector framework foundation

Provelume `0.7/S01` introduces a provider-independent local configuration and conformance boundary.
It does not yet perform HTTP requests, execute OAuth, schedule refreshes or load adapter code from a
manifest. Issue #105 owns the complete `0.7.0` release; later slices add lifecycle surfaces,
authorization, guarded transport and manual web acquisition one homogeneous pull request at a time.

## Identity boundary

Three identities remain separate:

- a `ConnectorDefinition` identifies one reusable adapter contract and its versioned capability
  manifest;
- a `ConnectorInstance` binds one definition to one provider identity, optional account identity,
  endpoint allowlist, authorization mode, scope set and local network policy;
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

## Local interfaces

The foundation exposes four local CLI commands:

```text
provelume connector-definition-register INSTANCE MANIFEST.json
provelume connector-instance-create INSTANCE DEFINITION_ID [policy options]
provelume connector-source-add INSTANCE CONNECTOR_INSTANCE_ID [Source options]
provelume connector-inventory INSTANCE
```

These commands only validate and atomically write local records. API and EN/IT Browser connector
inventory/health surfaces, mutation lifecycle evidence and disable/remove semantics belong to
`0.7/S02`. OAuth execution belongs to `0.7/S03`; guarded HTTP transport and manual acquisition
belong to `0.7/S04` and `0.7/S05` respectively.
