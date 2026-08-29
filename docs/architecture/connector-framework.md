# Connector framework and local lifecycle

Provelume `0.7/S01` introduces a provider-independent local configuration and conformance boundary.
`0.7/S02` adds bounded multi-instance lifecycle mutations, path-redacted evidence and aligned
service/CLI/read-only API/EN/IT Browser views. Neither slice performs HTTP requests, executes OAuth,
schedules refreshes or loads adapter code from a manifest. Issue #105 owns the complete `0.7.0`
release; later slices add authorization, guarded transport and manual web acquisition one
homogeneous pull request at a time.

## Identity boundary

Three identities remain separate:

- a `ConnectorDefinition` identifies one reusable adapter contract and its versioned capability
  manifest;
- a `ConnectorInstance` binds one definition to one provider identity, optional account identity,
  primary endpoint origin, endpoint allowlist, authorization mode, scope set, external credential
  reference, local network policy, empty pre-refresh cursor envelope and local health state;
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
valid without rewriting them. A create uses lifecycle schema 2; an update, enable, disable or remove
upgrades only the exact legacy record being changed. Definitions remain manifest schema 1. This
lazy, per-record transition avoids a second Instance migration and preserves stable IDs.

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

## Lifecycle and preservation boundary

Connector instances and each selected Source have independent `enabled` state. Disabling a parent
fails its effective network policy closed but does not rewrite child configuration. Disabling a
Source affects only that selection. Re-enabling retains the same stable identity and policy.

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

## Cursor and health boundary

Each lifecycle-schema-2 instance owns a separate `cursors: {}` envelope. S02 requires that it stay
empty: it does not invent cursor tokens, conditional checkpoints, jobs, retries or refresh state
before the later transport/refresh contracts exist. This reserves an isolated per-instance
boundary without anticipating `0.8.0`.

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
contain no exclusive business logic and never change Instance state.

OAuth execution belongs to `0.7/S03`; guarded HTTP transport and manual acquisition belong to
`0.7/S04` and `0.7/S05` respectively. Background scheduling and refresh remain excluded.
