# ADR 0017: replaceable Google read-only adapters

- Status: accepted for unreleased `0.9/S04`
- Date: 2026-09-01
- Owner issue: [#149](https://github.com/gabned/provelume/issues/149)
- Public identity: `0.8.0`

## Context

Lectio needs Gmail and Drive intake without allowing a provider identifier, OAuth credential or
remote mutation to become canonical authority. The provider-neutral connector framework already
defines separate ConnectorInstance and Source identities, explicit network policy, external secret
references and canonical Original/Document/Version/Acquisition records. S03 separately defines
exact-byte email Originals and non-authoritative message observations.

Google accounts combine capabilities that have different scopes, selections and revocation
lifecycles. Treating an account as one indivisible grant would make disabling Drive also affect
Gmail, encourage over-broad consent and obscure which Source owns a cursor. Persisting an access or
refresh token would also leak credentials through backup, portable export, fixtures or logs.

## Decision

Each authorized Google identity is one provider-neutral ConnectorInstance. Gmail and Drive are
independent capability records under that instance, each with its exact read-only OAuth scope,
explicit consent, enable/disable state, authorization lifecycle and external credential reference.
Only the reference kind/name is durable; the adapter resolves a credential value transiently.

Every mailbox/label or file/folder selection is a separate provider-neutral Source. Raw provider
identifiers remain adapter-local configuration. Canonical and operational evidence retains only
Source-scoped SHA-256 references. Provider Message-ID, thread ID, addresses, dates, labels, file ID
and revision ID never become global identity and never cause an implicit cross-Source merge.

The adapter protocol is replaceable. The built-in REST preview uses only bounded GET requests to
the closed HTTPS allowlist. Public CI uses `SyntheticGoogleAdapter`, which performs no credential
resolution or socket operation. Without a permanent authorized exact-head smoke, the published
claim remains `local-conformance-preview`; `real_google_qualified` is false.

Gmail reuses the S03 exact-byte message/attachment commit and removable representation pipeline.
Drive commits binary bytes, or the exact bytes of a bounded supported Google-native export, as an
Original. Revision evidence records source format, export format, provider-neutral revision
reference, checksum, size, accepted time and provenance.

Jobs reuse Vigilia leases, heartbeat, checkpoints, bounded retry and crash recovery. Provider
cursors live only under their Source adapter state. Revocation and expired authorization disable
only the affected capability; cursor invalidation requires a visible manual resync; remote mutation
during a Drive read aborts before canonical promotion.

## Consequences

- Gmail and Drive can be authorized, enabled, disabled, revoked and reauthorized independently.
- Disabling the global network policy, connector, capability or Source prevents any adapter call.
- Provider writes, Gmail sending/label mutation and Drive write/delete/share are structurally
  absent.
- Backups and portable bundles preserve connector state and canonical evidence without credential
  values.
- Binary Drive content without a safe text extractor remains a verified Original and receives an
  explicit unavailable Markdown projection; no implicit OCR or remote conversion starts.
- Calendar, IMAP/POP/SMTP, transcript, cross-source qualification and Windows endpoint work remain
  later slices.

## Rejected alternatives

- One OAuth grant and cursor for the whole Google account: rejects independent consent and failure
  isolation.
- Provider IDs as Document identity: rejects provider neutrality and Source isolation.
- SDK-specific canonical records: rejects adapter replacement.
- Durable token storage in connector JSON: rejects backup/export and logging safety.
- Silent Google-native fallback formats or OCR: rejects bounded reproducibility and explicit user
  control.
