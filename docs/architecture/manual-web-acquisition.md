# Manual safe web acquisition

Provelume `0.7/S05` acquires one URL only after an explicit application-service call or
`connector-web-acquire ... --confirm-network` command. It exclusively consumes the `0.7/S04`
guarded transport: there is no second HTTP client, proxy fallback, provider adapter, scheduler,
poller or automatic refresh path.

## Authority and commit boundary

The guarded transport first checks current Instance, connector, authorization and independently
selected Source policy, canonicalizes the exact Source URL, validates every DNS answer and redirect,
and returns one complete bounded response. Network activity finishes before the acquisition commit
guard begins.

The service then holds the Instance lifecycle lock used by ingestion, backup, restore, portable
transfer and retention work. Inside it, the service also holds the same process-local and
cross-process connector-configuration locks used by disable, removal, authorization revocation and
the desktop's global network-policy writer. It rechecks the complete current policy plus the final
redirect origin before staging any Instance write and captures the sorted canonical origin allowlist
used by that decision. A disable, Source change, revocation or global network-policy change observed
before commit therefore fails closed with no canonical or Original partial state.

## Canonical transaction and exact bytes

A successful request stages one durably journaled transaction outside the live Instance, fsyncs its
candidate bytes, exact preimages and prepared manifest, and only then replaces planned live files
while both locks remain held. The terminal operation record is part of the same transaction. An
ordinary write or replacement error restores every preimage and removes newly created files. A
process or power interruption leaves the prepared journal for lifecycle recovery during the next
Instance open; recovery is idempotent, restores the complete pre-commit state and closes the
interrupted operation as failed. A durable committed marker makes cleanup-only interruption retain
the complete success instead. Existing Original records and bytes are immutable: a mismatched
pre-existing content-addressed identity rejects the complete transaction, and no acquisition path
modifies or deletes an Original.

The retained Original contains exactly the bounded representation bytes returned by S04 after its
validated HTTP content-decoding step. Transfer framing and compressed wire form are not promoted to
canonical content; `content_encoding` is retained as acquisition evidence. The Original ID is its
SHA-256 identity and its stored bytes, declared size and hash must agree during acquisition and deep
validation.

One successful request records:

- the canonical requested URL and guarded final URL;
- retrieval instant, HTTP status, normalized media type, content encoding and exact retained size;
- the exact sorted canonical origin allowlist rechecked for the request and final redirect;
- response SHA-256, Source and ConnectorInstance identities;
- the resulting Acquisition, deterministic Document and Version, and immutable Original identities;
- canonical provenance from Source and ConnectorInstance through Acquisition, Original, Version and
  Document.

Document identity is deterministic from Source plus canonical requested URL. Version identity is
deterministic from Document plus content hash. Original identity is content-addressed globally.
These identities and their lineage survive backup, restore and portable export/import.

## Replay, duplicates and derived text

Every successful explicit request creates a distinct Acquisition, even when its bytes are unchanged.
The record points to the preceding successful request for that Source URL and reports whether its
Original already existed. Canonical content remains idempotent: unchanged bytes reuse the same
Document, Version and Original; changed bytes create one deterministic Version; bytes that return
to an earlier hash reuse that Version instead of creating a duplicate.

Readable text is a separate `DerivedArtifact`. UTF-8 text/Markdown/JSON/XML, HTML, CSV and textually
readable PDF inputs use bounded deterministic extractors. Unsupported, invalid or image-only
representations remain successfully acquired with `derived_status: unavailable`; S05 performs no
OCR and invents no substitute text. Derived text is rebuildable and never replaces or weakens the
Original.

## Read and evidence surfaces

`ProvelumeInstance.acquire_manual_web` and `connector-web-acquire` are the only S05 initiation
surfaces. The application service also supplies list/detail models used unchanged by the read-only
Knowledge API and EN/IT Browser Source/result pages. HTTP defines no acquisition `POST`, refresh,
delete or provider write-back route.

Operation evidence contains only fixed safe messages, typed codes, opaque canonical identities and
bounded numeric/status metadata. It excludes requested and final URLs, response bytes, extracted
content, tokens, credential references and physical paths. Failed transport or commit operations
report zero canonical creation; they never serialize an exception message containing private input.

## Recovery and qualification

Canonical acquisitions, provenance and Originals are included by the existing backup, restore and
portable export/import contracts. Derived text follows their declared include/rebuild policy.
Deep validation checks URL canonicality, the captured origin allowlist and final-origin membership,
connector/Source isolation, retrieval metadata, hash/size/Original/Version agreement and required
acquisition provenance.

The synthetic Linux and Windows suite injects DNS, pinned connections and response streams and
opens no real socket. It covers successful exact-byte retention, redirects, replay, duplicate,
ordinary rollback and interruption recovery; serialized global policy changes, cross-instance
disable and authorization revocation; SSRF, DNS rebinding, timeouts, malformed/truncated/oversized/
compressed responses inherited from S04; unreadable content, redacted evidence, deep validation,
backup/restore and portable transfer.
