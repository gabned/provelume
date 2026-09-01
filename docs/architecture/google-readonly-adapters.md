# Google Gmail and Drive read-only adapters

`0.9/S04` adds a replaceable Google adapter behind the provider-neutral connector, Source, email
and document contracts. It is unreleased development and keeps package, runtime and embedded
identity at `0.8.0`.

## Authority and isolation

One Google identity maps to one `ConnectorInstance`. Gmail and Drive are independent capabilities;
each requires explicit consent and exactly one scope:

| Capability | Scope | Provider mutations |
|---|---|---|
| Gmail | `https://www.googleapis.com/auth/gmail.readonly` | none |
| Drive | `https://www.googleapis.com/auth/drive.readonly` | none |

Authorization persists only `{kind, name}` for an environment or system-keyring reference. Access
tokens, refresh tokens, client secrets and authorization headers are never serialized. Revocation
clears the reference and disables only that capability. Reauthorization creates a new capability
revision and does not silently re-enable it.

Each mailbox/label or file/folder selection is a separate connector Source. The Source owns its
schedule, lifecycle, cursor, page fingerprints and health. There is no cross-Source merge. API and
Browser views redact selectors and raw cursors to their count/hash or presence state.

## Network disclosure

The effective gate requires all of the following:

1. Instance `network.external_access` is enabled;
2. the ConnectorInstance is enabled in explicit network mode;
3. the exact Gmail or Drive capability is authorized and enabled;
4. the exact Source is enabled;
5. the connector allowlist equals the closed Google origin set.

The REST preview accepts HTTPS only and disables redirects. Its allowlist is
`accounts.google.com`, `oauth2.googleapis.com`, `gmail.googleapis.com` and
`www.googleapis.com`. Intake uses bounded GET requests only. Disabled paths fail before credential
resolution and before a socket can be opened. Errors contain closed codes, not URLs, query values,
headers or content.

## Gmail acquisition

Gmail selection is explicit: the authorized `me` mailbox or one or more label identifiers. Each
page is bounded, and every selected message is fetched as Gmail `format=raw`. The decoded RFC 822
bytes enter the S03 pipeline unchanged:

- exact message Original and exact accepted-attachment child Originals;
- provider-neutral Document/Version/Acquisition and S03 email evidence;
- removable, inert email representation;
- attachment OCR eligibility only, with `execution_requested=false` and
  `execution_started=false`.

Gmail message ID, history/revision ID, thread ID and labels are salted-by-namespace SHA-256
observations scoped to the Source. Declared Message-ID, addresses and dates remain the S03
non-authoritative observations. Equal bytes can deduplicate cryptographically, but separate Sources
and provider observations remain separate.

Sending, draft creation, deletion, label changes and write-back have no command, API method or
adapter operation.

## Drive acquisition

Drive selection is an explicit set of file or folder identifiers. Binary files use `alt=media` and
their response bytes become the exact Original. Supported Google-native formats use one bounded
export:

| Source format | Export format |
|---|---|
| Google Docs | PDF |
| Google Sheets | XLSX |
| Google Slides | PDF |

After the content read, metadata is fetched again. A changed revision or MIME type raises
`google_remote_mutation` and nothing is promoted. Revision evidence records the hashed provider
file/revision references, provider-neutral Document/Version, acquisition, source/export formats,
checksum, size, observed/accepted times and exact-byte Original. Unsupported Google-native formats
fail visibly instead of selecting an implicit export.

Drive update, delete, share, permission and write-back operations are absent. A binary without a
local text extractor remains a verified Original with an unavailable readable representation; it
does not trigger OCR or a remote fallback.

## Durable execution

`google.intake` is a Source-scoped Vigilia job. Requests bind Source/capability fingerprints,
capability and cursor revisions, exact scope, allowlist, selection hash and closed limits. They do
not contain credential reference names, raw selectors, provider cursors or private content.

The default limits are 32 pages, 100 items per page, 500 items, 32 MiB per item, 256 MiB per run,
4 MiB metadata JSON, 100 item errors, 256 page fingerprints and a 30-second request timeout. All
ceilings are closed and validated.

The work journal contains only item identity/checksum, size, canonical ID, status and closed error.
Raw cursors remain in `state/google-adapters/sources/<source>.json`; public surfaces expose only
presence. A page fingerprint mismatch produces visible cursor invalidation and `resync_required`.
Rate limit and transient provider failures use bounded scheduler retry. OAuth expiry changes only
the affected capability to `reauthorization_required`. Atomic item promotion and transaction
recovery make lease replay idempotent.

## Surfaces and qualification

The service and `google-*` CLI commands provide identity, capability, Source, schedule, cursor,
job, revocation and evidence controls. `/google` supplies CSRF-protected loopback controls in
English and Italian. `/api/v1/google/*` is read-only; mutations return 405.

Public CI uses deterministic synthetic pages and credentials are never required. The built-in REST
implementation is a preview seam, not real-provider qualification. Until a permanent authorized
smoke proves an exact head against Google, packaging evidence reports
`local-conformance-preview` and `real_google_qualified=false`.

See [ADR 0017](../adr/0017-google-readonly-adapters.md), the
[Italian guide](google-readonly-adapters.it.md) and the [API guide](../api.md).
