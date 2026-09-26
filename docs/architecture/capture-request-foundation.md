# Cura Capture request foundation

Status: initial S06 implementation under #274, following source-exclusion correction
#277/#278. This is not a delivered Capture API, pairing service or PWA. The package
remains 0.10.1 and the complete slice acceptance criteria remain open.

`capture_requests.py` defines the first bounded, versioned client envelope and pure
identity operations for the future append-only submission adapter. It performs no
network request, filesystem mutation, acquisition, credential issuance or acceptance.

The envelope preserves the client-generated canonical UUID4, declared capture time
with an explicit offset, selected capture mode, transport channel, optional note,
Area/Project proposals and display filename/media type. Capture time remains distinct
from a future server receipt time. Server acceptance, acquisition and credential
fields are not permitted in client metadata. Proposal shapes reuse the existing
Area/Project identity contract; existence and permission require the actual domain
guards before any submission can be committed.

The adapter must supply its independently authenticated transport channel. A client
cannot claim the local management boundary from a paired PWA. A submission occurrence
key combines the server-authenticated device identity with the client UUID. Changed
payload or metadata does not choose a new occurrence key: the durable journal must
reject conflicting reuse. Different UUIDs/devices preserve distinct occurrences of
the same bytes. The payload fingerprint binds exact bytes and declared metadata,
independently of JSON key ordering, without treating a hash as a receipt or antivirus
result. The fingerprint input retains the existing ingestion byte bound; effective
per-mode upload/type limits must be implemented and declared by the real adapter.

Next integration is the device-scoped durable submission journal, under the existing
lifecycle and recovery contracts. Before acknowledging, the adapter must authenticate
and recheck current revocation, enforce reference authority and actual byte/type
validation, and commit the authoritative receipt. Processing and S05 routing follow
that commit through their existing lifecycle, without nested mutation locks or a
rollback of an acquired Original. Lookup/list/detail remain read-only.

The remaining #274 criteria include protected QR pairing and HTTPS/origin boundaries,
real capture modes, restart/replay/uncertain-acknowledgement recovery, quarantine and
retention, backup/portable preservation, the bounded offline outbox and PWA resources,
and actual browser/keyboard observations. This foundation does not satisfy or waive
those gates and does not activate S07 or a release preparation.
