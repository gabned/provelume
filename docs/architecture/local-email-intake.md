# Local email identity and intake

Status: implemented for active, unreleased `0.9/S03` under
[#143](https://github.com/gabned/provelume/issues/143) and
[PR #144](https://github.com/gabned/provelume/pull/144).
Published package, embedded identity, tag and release remain `0.8.0 — Vigilia`.

Qualification is bound to the unchanged owner head by the permanent EML/Maildir smoke and required
repository workflows. It is a local development qualification, not a published `0.9.0` support
claim.

## What this slice does

S03 imports email evidence from an explicitly selected local EML file or bounded Maildir profile. It is
provider-neutral, offline and disabled by default. It does not discover mail applications,
accounts, folders or credentials, and it does not contact Gmail, an IMAP/POP server or any other
provider.

The public seams keep Source configuration, container enumeration, bounded byte reading, MIME
parsing, identity/deduplication, body selection, attachment extraction, persistence, observed
threading and durable job orchestration replaceable. The first parser is
`email.parser.BytesParser(policy=policy.default)` from CPython 3.12, exposed as
`python.email` / `stdlib-3.12` behind parser protocol 1. The Source adapter is
`provelume.local-email` 1.0.0 behind adapter protocol 1.

The parser is deliberately narrower than everything MIME can express. Exact raw bytes are hashed
and preserved before a parser result is trusted. Python's `email` objects are never canonical
records and serializing one is never used to reconstruct the Original.

Primary references are the Python 3.12
[`email.parser`](https://docs.python.org/3.12/library/email.parser.html),
[`email.policy`](https://docs.python.org/3.12/library/email.policy.html) and
[`mailbox`](https://docs.python.org/3.12/library/mailbox.html) documentation, plus
[RFC 5322](https://www.rfc-editor.org/rfc/rfc5322),
[RFC 2045](https://www.rfc-editor.org/rfc/rfc2045),
[RFC 2046](https://www.rfc-editor.org/rfc/rfc2046),
[RFC 2047](https://www.rfc-editor.org/rfc/rfc2047) and
[RFC 2231](https://www.rfc-editor.org/rfc/rfc2231), plus
[RFC 6532](https://www.rfc-editor.org/rfc/rfc6532) for internationalized headers. These standards
describe syntax; they do not make a declared identity, timestamp, media type or filename
trustworthy.

## Explicit Source lifecycle

An email Source always requires an operator-selected path and one explicit profile:

- `eml-file-v1` — exactly one local regular file;
- `maildir-cur-new-v1` — exactly one local Maildir root with `tmp/`, `new/` and `cur/`;
- `mbox` — unsupported and rejected with a closed reason.

Creation performs no intake and stores the Source as `disabled` with manual execution policy.
`enabled`, `paused` and `disabled` are distinct states. Enable, Run now, pause, disable, cancel,
remove and any scheduled policy are explicit local actions. A path that merely exists cannot start
a job. There is no watcher, daemon, startup task or background agent.

The local service, CLI and CSRF-protected loopback Browser own mutations. The versioned HTTP API is
read-only and cannot upload EML bytes, configure a path or start intake. The local CLI and Browser
configuration view may show the escaped operator-selected path; the API, job receipts and operation
records never expose it.

Removing a Source retains its tombstone and every prior Source, Acquisition, Document, Version,
Original and provenance relationship. It does not delete or rewrite acquired knowledge.

## Format and platform matrix

The permanent smoke runs the real selected parser and generated synthetic messages on these exact
qualified targets:

| Profile | Ubuntu 24.04 x86-64 / CPython 3.12 | Windows Server 2025 x86-64 / CPython 3.12 | Other targets |
| --- | --- | --- | --- |
| `eml-file-v1` | qualified | qualified | unqualified |
| `maildir-cur-new-v1` | qualified | unqualified | unqualified |
| `mbox` | unsupported | unsupported | unsupported |

The Maildir profile enumerates only immediate regular files in `new/` and `cur/`, in deterministic
order. It never reads `tmp/`, changes flags, moves messages, cleans temporary files or traverses
nested folders. On Windows, standard Maildir `cur` naming and filesystem behavior are not claimed
portable, so the capability is unavailable even though CPython exposes a `mailbox` module.

`mailbox` was evaluated but is not selected for reading or delimitation. Its mailbox abstractions
do not establish Provelume's exact source-byte, snapshot, link and locator evidence. Provelume
instead opens the selected regular file in binary mode, bounds the read, hashes the bytes, and
compares handle/path evidence before and after the read. Original CRLF, LF or mixed line endings
remain exact Original bytes; only a derived body may have normalized text line endings.

The Source root, required directories and message candidates must satisfy the platform's no-link
policy. POSIX symlinks and hardlinks, and Windows symlinks, hardlinks, junctions or other reparse
points, are rejected. Non-regular files are rejected. A file that vanishes, is renamed, replaced or
changes relevant size/time/file-identity evidence during the bounded read is not promoted as a
success. This is a fail-closed cooperative mutation boundary, not an operating-system sandbox.

## Effective hard ceilings

Configuration may lower these schema-1 ceilings but cannot raise them. Counters are cumulative
where shown, and the capability response plus every job recipe records the effective values.

| Limit | Hard ceiling |
| --- | ---: |
| one EML/message file | 32 MiB |
| one mailbox container snapshot | 512 MiB |
| messages in one run | 500 |
| source bytes read in one run | 256 MiB |
| header fields in one message | 512 |
| complete header block | 256 KiB |
| one header/source line | 16 KiB |
| MIME parts in one message | 256 |
| MIME nesting depth | 16 |
| nested `message/rfc822` depth | 4 |
| accepted attachments in one message | 100 |
| one accepted attachment | 20 MiB |
| accepted attachment bytes in one message | 30 MiB |
| transfer-decoded output in one message | 32 MiB |
| transfer-decoded output in one run | 256 MiB |
| derived body characters | 500,000 |
| retained thread references | 100 |
| retained warnings in one message | 200 |
| retained errors in one job | 500 |
| temporary space in one job | 512 MiB |
| time for one message | 30 seconds |
| time for one job | 600 seconds |

The 512 MiB container ceiling and 256 MiB run-read ceiling are independent checks. The lower
effective check wins for a single run: exceeding either fails closed, and S03 does not advertise a
partial snapshot or silent continuation as a complete mailbox result.

## Message identity and deduplication

S03 keeps independent values for:

- Source ID and adapter/protocol version;
- container profile and observed snapshot fingerprint;
- opaque locator digest and local file identity when available;
- exact message SHA-256 and byte count;
- contract, parser, effective settings and limits;
- declared `Message-ID`, `References` and `In-Reply-To` observations.

Within one Source, the exact content identity owns the stable message Document/Version. Reimporting
the same observation and bytes is a replay and creates no duplicate Acquisition, Document,
Version, Original, attachment or provenance. Equal bytes under another locator reuse the same
message evidence within that Source while retaining the new observation. Equal bytes in another
Source remain another Source-scoped message, Document and acquisition; S03 does not merge Sources.
The global content-addressed store may safely reuse the same immutable Original blob by digest,
which is storage deduplication rather than cross-Source identity equivalence.

A valid-looking `Message-ID` is not an identity key by itself. Two different byte sequences with
the same ID are both retained and carry an explicit collision warning. A missing, malformed or
repeated ID does not make valid bounded bytes unimportable.

Thread identity is likewise an observed Source-scoped grouping. The representation records which
bounded `References`/`In-Reply-To` evidence produced it. Missing targets, duplicate IDs, cycles,
oversized reference chains and cross-Source references do not create equivalence. S06 owns any
later cross-source qualification.

The header-declared date, filesystem/container observation time and acquisition time remain three
different fields. None is silently substituted for another.

## Originals, attachments and derived representation

The exact message is an immutable content-addressed Original. Each accepted attachment or inline
part is separately decoded under the transfer budget and committed as an immutable child Original
with a provenance edge to the message and exact MIME-part identity. Its declared filename is an
observation only. Storage uses an internal deterministic identifier, never the MIME name, so
absolute paths, traversal, Windows device names, ambiguous Unicode and collisions cannot select a
storage location.

The schema-1 `email_message_bundle` is a removable and rebuildable derived representation. It
contains or binds:

- Source/container/message identity and exact Original digest;
- selected raw/parsed envelope fields, defect state and warnings;
- declared, observed and acquisition timestamps as separate values;
- selected text body, selection rule, character count and digest;
- the bounded MIME tree;
- accepted attachment identities, digests, declared media/disposition/`Content-ID` and relation;
- declared reply/reference evidence and observed thread/reason;
- parser, adapter, platform, settings and effective limits;
- the job ID and immutable `message-complete` unit state (the durable journal remains authoritative
  for the overall multi-message job status);
- checksums needed to verify complete removal or reconstruction.

The bundle is promoted atomically only after the message Original, every accepted attachment
Original, canonical records and complete derived manifest agree. A staged or partial body, MIME
tree, thread or attachment index is not readable as a successful result. Removing or rebuilding
the bundle never mutates an Original or canonical knowledge.

## MIME and active-content safety

Header count/bytes and line length are checked before the MIME parser receives the message. The
bounded walk then handles missing, repeated, malformed and encoded-word headers; address lists and
groups remain syntax observations and never become resolved contacts.

`multipart/mixed`, `multipart/alternative` and `multipart/related` are walked only inside the
closed part/depth budgets. An acceptable `text/plain` part is preferred. The S03 baseline has no
HTML-to-text fallback: HTML remains only in the exact message Original and the derived body is
explicitly unavailable. No email path renders HTML, runs script, applies remote CSS, submits forms,
follows URLs, loads remote images or tracking pixels, or resolves a `cid:` reference.

Strict `7bit`, `8bit`, `binary`, Base64 and quoted-printable transfer forms are accepted only after
syntax/output checks and inside cumulative budgets. Unknown encodings and invalid, truncated or
excessive output fail closed. Body decoding is qualified only for US-ASCII/ASCII, UTF-8,
ISO-8859-1/Latin-1 and Windows-1252/CP1252 declarations. An unknown or invalid charset retains an
explicit warning and an unavailable-body state instead of an invented semantic correction.
`message/rfc822` is bounded separately. Archives are retained as attachments but never expanded.
Signed, encrypted or unsupported parts are preserved without claiming signature, sender or
encryption verification.

No email operation executes an attachment, macro, JavaScript or shell command. It performs no
malware scan and makes no DKIM, SPF, DMARC, PGP, S/MIME or legal-authenticity claim.

## Durable job, retry and recovery

Email intake uses Vigilia's durable scheduler journal with an idempotency key bound to Source,
container/message observation, exact message hash, contract/adapter/parser and effective settings.
It retains message-level and accepted-attachment checkpoints, an exclusive lease, heartbeat,
bounded attempts and cooperative cancellation between bounded units.

An expired lease or process crash resumes only from a verified committed checkpoint. A replay
cannot overwrite an Original or duplicate a Version, attachment or provenance edge. One bad message
is isolated; valid messages continue and the overall state becomes `completed_with_errors` when
needed. Before promotion the adapter rechecks the Source snapshot so a changed mailbox cannot
publish a stale success.

Warnings, errors and receipts use opaque IDs, counts and closed codes. They do not contain subject,
body, addresses, filenames, physical paths or caller text.

Deep validation verifies Source/config bindings, canonical message/attachment evidence, exact
Original references and complete bundle checksums without rereading the mailbox. Backup/restore
retains local configuration, tombstones, canonical evidence and durable job state. Portable export
always retains canonical email evidence and follows the selected derived-state policy; an import
without bundles can rebuild them from retained message Originals. A restored path that is absent or
unqualified leaves the Source visibly unavailable and does not rewrite earlier acquisitions.

## Local controls and read-only views

The local CLI groups the boundary into explicit commands:

- `email-capability` reports adapter/parser identity, profiles, target availability and limits;
- `email-source-create`, `email-source-list`, `email-source-show`, `email-source-state`,
  `email-source-schedule` and `email-source-remove` manage the explicit configuration/tombstone;
- `email-intake-queue`, `email-intake-run`, `email-intake-jobs`, `email-intake-job` and
  `email-intake-cancel` manage durable work;
- `email-messages`, `email-message`, `email-threads`, `email-thread`, `email-attachments` and
  `email-attachment` inspect bounded local representations;
- `email-derived-remove` and `email-derived-rebuild` change only derived email state.

The minimum operator sequence is: create a Source with its exact local path and profile, change its
state to `enabled`, queue intake for that Source, then explicitly run the returned job. Creation and
enablement are deliberately separate; a queue request does not bypass capability, Source-state or
snapshot gates.

```bash
provelume email-source-create INSTANCE --name "Local message" \
  --path /path/to/message.eml --profile eml-file-v1
provelume email-source-state INSTANCE SOURCE_ID enabled
provelume email-intake-queue INSTANCE SOURCE_ID
provelume email-intake-run INSTANCE JOB_ID
```

Use `maildir-cur-new-v1` with the explicit Maildir root for the targeted Ubuntu profile. The create
and queue results return the opaque Source and job IDs used by the next command.

The supported surface covers these operations:

- create one explicit local email Source and inspect its capability/profile/limits;
- enable, pause or disable it and request Run now;
- inspect or cancel durable work;
- list and safely inspect messages, observed threads and attachments;
- remove or rebuild an email derived representation;
- see attachment OCR eligibility without starting OCR;
- tombstone-remove the Source without deleting previous acquisitions.

The read-only API exposes the same sanitized read models below `/api/v1/email/capability`,
`/sources`, `/jobs`, `/messages`, `/threads` and `/attachments`, with item routes for each retained
identity; mutation attempts return `405`. Browser mutations exist only on `/email`, a loopback
surface protected by the current per-process CSRF contract. S03 adds no HTTP upload or remote
intake endpoint.

Closed failures distinguish disabled Source/capability, unsupported profile/platform, missing or
unsafe path, mutation during read, exceeded limit, malformed message/MIME, invalid transfer
encoding, declared-identity collision, timeout, cancellation, expired/recovered lease, invalid
derived artifact and internal error.

## OCR and network separation

The capability may report whether an attachment's exact bytes and media type are eligible for the
S01/S02 OCR contract. That is information only. Email intake never enables, queues or executes OCR;
the operator must separately enable and explicitly run OCR. The email capability envelope reports
the independently probed OCR state, reason and supported media types under `attachment_ocr`;
`intake_dependency: false` means email availability never implies or requires OCR availability.

Capability discovery, Source reads, MIME parsing, derived rebuild and read-only inspection require
no network. They do not open a socket, resolve DNS, fetch avatars, follow links, load remote images,
download a parser or fall back to a provider. Enabling a local email Source does not enable
`network.external_access` or add an origin.

Gmail, Google Drive, IMAP, POP, SMTP, sending, account discovery and provider cursor/refresh are
absent. Gmail/Drive remain the unactivated `0.9/S04` forecast.

## Packaging and known limitations

S03 adds no runtime dependency. The wheel and sdist contain Provelume adapter/parser-seam code and
schemas; they add no external MIME parser, provider SDK, native library or mailbox payload. The
Windows installer uses the CPython standard library already present in its frozen runtime. No
component is downloaded at runtime. The release SBOM continues to describe the packages actually
built rather than inventing a separately versioned `email` component.

The baseline does not support mbox, nested Maildir folders, Windows Maildir, remote or removable
mailboxes, PST/OST, archive expansion, active HTML, contacts/calendar/tasks, message sending,
semantic classification, AI/RAG, authenticity verification or cross-Source merge. `0.9.0` is not
published, and no S03 change creates a tag, release or asset.
