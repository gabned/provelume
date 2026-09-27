# Cura Capture request foundation

Foundation history through checkpoint54: initial S06 implementation under #274, following source-exclusion correction
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

The device-scoped durable submission journal now stores immutable receipt/byte records
under `state/capture/<device>/<occurrence>.json`. `CaptureJournal` is an internal
service, not a network endpoint. Its caller supplies current authorization and actual
payload/reference validation guards; these run again on replay under the shared
lifecycle lock. Lookup/list recheck authorization, remain pure, and refuse pending
recovery. Exact bytes and metadata are compared in addition to fingerprints, so a
digest collision does not permit conflicting identity reuse. Distinct devices and
UUIDs retain distinct occurrences. A committed submission is not an Acquisition.

The bounded `capture` atomic profile commits one immutable record, with a domain
path/owner/schema allowlist checked before recovery. A prepared interruption rolls
back the unacknowledged submission; a committed interruption retains its original
receipt. Lifecycle writers and Instance preparation recover before subsequent work.
There are at most 128 records/devices and 128 MiB of serialized journal content;
individual records are bounded to 36 MiB and payloads retain the 25 MiB identity
limit. Full state fails visibly and never trims history. Base64 is storage encoding,
not protection or a malware scan. Stored submitted bytes remain untrusted.

`CaptureAdapter` now supplies the domain guards and a separate bounded atomic
acquisition profile. Its required authority callback runs before entering mutation
and again under lifecycle, including replay; the transport must still supply real
authentication and revocation. Proposal references require existing matching
Area/Project nodes and explicit callback permission. Capacity admission gates new
submissions and acquisitions; historical committed acknowledgements remain available.

The effective internal matrix admits bounded UTF-8 text, a single HTTP(S) URL without
credentials (preserved without fetching), and structurally validated unencrypted
PDFs; file mode is restricted to `.txt`, `.md` and `.pdf`. Declared MIME mismatch,
malformed bytes and unavailable modes fail before acknowledgement. The capability
description lists unsupported photo/scan/screenshot/audio/voice modes and the absent
paired transport. There is still no browser route or usable capture UI.

Each device has a deterministic Capture Source. Distinct submission occurrences
retain distinct Documents/Acquisitions even when they share one exact Original.
The acquisition receipt, canonical records, Original, derived text and provenance
commit together. The profile permits at most 20 immutable entries, 32 MiB per entry
and 40 MiB in candidates/journal. Domain receipt/path/byte bindings are checked before
recovering an interrupted transaction. Prepared writes roll back; a durable commit
retains its original acquisition receipt, so retry never duplicates acquisition.
Lookup/detail remains pure and refuses pending recovery. Extraction failure records
attention while retaining the Original; S05 routing and the search projection follow
the canonical commit and cannot roll it back. S05 retains its own authority gates.

Before external acknowledgement, the transport adapter must authenticate
and recheck current revocation, enforce reference authority and actual byte/type
validation, and commit the authoritative receipt. Processing and S05 routing follow
that commit through their existing lifecycle, without nested mutation locks or a
rollback of an acquired Original. Lookup/list/detail remain read-only.

The remaining #274 criteria include protected QR pairing and HTTPS/origin boundaries,
real capture modes, restart/replay/uncertain-acknowledgement recovery, quarantine and
retention, backup/portable preservation, the bounded offline outbox and PWA resources,
and actual browser/keyboard observations. This foundation does not satisfy or waive
those gates and does not activate S07 or a release preparation.

## Protected transport and outbox candidate

The current OWNER #289 extends that foundation with the responsive EN/IT `/capture/`
surface. The ordinary loopback server issues a ten-minute memory-only nonce after an
explicit Connect action. Exact Origin/Host and current authorization guard every
submission, reconciliation, processing and Original download. Local Inbox folder
configuration and its import journey remain available.

Remote Capture is a separate app, disabled by default. The local owner explicitly
configures its canonical HTTPS origin and confirms revocation when rebinding. Start
it with `provelume capture-serve INSTANCE --origin https://HOST:PORT --host BIND
--port PORT --tls-cert CERT --tls-key KEY`. TLS is mandatory, including LAN/VPN;
forwarded headers are not trusted. This command exposes only Capture, never owner
administration or the general Knowledge API. Configuration does not start a listener.

Owner-created QR contents bind destination, Instance, scope and a single-use challenge
with a 120-second lifetime. Secrets never enter URL queries. Each device credential
authorizes submission, its own receipts/Original attachments and metadata proposals.
The server retains verifiers and an audit in one atomic `device-authority` profile.
Its host key lives outside the portable Instance, protected by current-user DPAPI on
Windows and owner-only permissions on POSIX. Imported credentials remain inactive
without that host binding; explicit rebind revokes retained devices without deleting
knowledge. Corrupt state fails visibly rather than resetting pairing.

The effective matrix adds decoded PNG/JPEG for photo/scan/screenshot and validated
PCM16 WAV for audio/voice. The browser explicitly starts camera/microphone capture;
PNG/JPEG require the explicit external `capture` extra (`pip install 'provelume[capture]'`)
with the existing qualified Pillow 12.3.0 decoder. Core packages keep native decoder
payloads external; absent/incompatible decoders are declared unavailable before selection.
unavailable/denied capability remains visible and file input remains available.
Limits are declared before selection and enforced against actual bytes before server
acknowledgement: text 512 KiB, URL 8 KiB, PDF 25 MiB/500 pages, images 20 MiB/20 million
pixels/100x expansion, WAV 10 MiB/120 seconds/two channels. Files use this closed type
matrix. The one-item JSON body is capped at 36 MiB; each listener admits two concurrent
intake requests and bounded authentication attempts. Photos/audio preserve Original
with separate extraction attention; Capture does not silently start OCR/transcription.

IndexedDB retains at most 16 local entries/64 MiB. Entries preserve UUID, device,
Instance, exact-byte fingerprint and capture context across reload. A transactional
lease and cross-tab change notification coordinate duplicate tabs. Every uncertain
send looks up its authoritative receipt before retry. Receipt/device/fingerprint must
match before pending bytes and note are removed. Processing attention cannot turn an
acquired Original into a new pending occurrence. Cancellation removes the local copy
only and explicitly warns that server acceptance/knowledge may already exist.

Local nonces never persist. Paired retention requires an explicit checkbox, is bound
to the destination and expires locally after 30 days; Forget removes the credential
without deleting pending captures. No acquired knowledge is cached for mobile use.
Only seven fixed public shell assets, each bounded to 256 KiB, enter the PWA worker
cache. APIs, queries, authenticated requests, submissions and Originals are excluded.
Plain HTTP explicitly disables installation, worker and share-target paths. Native
mobile/share-target reference clients remain S07 work.

Owner rejection records bounded quarantine with explicit 1–365 day retention; undo
records compensation in an atomic `submission-quarantine` profile. Neither action
moves/purges an Original or canonical history. Action Center projects Capture intake,
quarantine and extraction attention, with inspection-only decisions and a link to the
protected Capture actions. Existing S05 routing/disposition authority still applies.

Deep Instance inspection validates Capture schemas, journal/processing/acquisition
bindings and quarantine references. Backup and portable transfer retain the journal,
receipts, Original and audit. Projection rebuild selects codecs from the accepted
Capture media type because occurrence locators intentionally have no file extension.
Backup manifests sort canonical POSIX path strings on every host.

This is a candidate, not S06 delivery. Native checks, complete exact-head CI and real
browser/PWA observations remain distinct evidence gates. Missing HTTPS/PWA evidence
must remain explicit; a simulated transport test cannot qualify real installation or
offline reload. Package 0.10.1 and the independent release gates remain unchanged.
