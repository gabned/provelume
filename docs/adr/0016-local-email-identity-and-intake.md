# ADR 0016 — Provider-neutral local email identity and bounded intake

- Status: accepted for `0.9/S03`; matrix qualification remains bound to the exact owner head
- Decision date: 2026-08-31
- Parent tracker: [#137](https://github.com/gabned/provelume/issues/137)
- Predecessors: [#5](https://github.com/gabned/provelume/issues/5) / [PR #138](https://github.com/gabned/provelume/pull/138) and [#140](https://github.com/gabned/provelume/issues/140) / [PR #141](https://github.com/gabned/provelume/pull/141)
- Owner issue: [#143](https://github.com/gabned/provelume/issues/143)
- Owner PR: `OWNER_PR_TBD`
- Published baseline: `0.8.0`; `0.9.0` remains unreleased development

## Context

Lectio needs an email Source that proves identity and provenance before a future Gmail adapter can
exist. An email is not trustworthy merely because its headers name a sender, date, `Message-ID` or
thread. MIME parameters and attachment names are likewise untrusted observations. S03 must retain
the exact local evidence, expose useful derived representations and use Vigilia's durable job
lifecycle without discovering accounts, reading credentials or contacting a provider.

Provelume already has a small generic `.eml` text extractor. That extractor is not the S03
identity, mailbox, attachment, thread or durable-intake contract. S03 keeps one replaceable parsing
boundary so generic EML extraction and email intake cannot grow into incompatible public parsers.

The Python standard library supplies `email` and `mailbox`. Evaluation found that the `mailbox`
container abstractions do not establish the exact source-byte, locator, link-policy and
pre/open/post snapshot evidence required by this contract. `mailbox.Maildir` also builds a key
table from filename conventions that are unsuitable as an authoritative cross-platform identity
and performs filesystem discovery outside Provelume's link and mutation checks. These behaviors
are acceptable for some mailbox applications but not for this exact-byte Original boundary.

## Decision

S03 implements stable seams for capability/configuration, container enumeration, bounded exact-byte
reading, header/MIME parsing, identity and deduplication planning, body selection, attachment
extraction, canonical/derived persistence, observed-thread construction and durable orchestration.
The first parser adapter uses `email.parser.BytesParser` from CPython 3.12 behind the public seam.
The parser is never the Original store and no public record depends on a concrete Python message
class.

The container reader is Provelume code built on bounded standard-library filesystem primitives. It
does **not** use `mailbox` to read message bytes or delimit messages:

- `eml-file-v1` reads one explicitly selected regular file;
- `maildir-cur-new-v1` accepts one explicit root containing `tmp/`, `new/` and `cur/`, enumerates only
  immediate regular files in `new/` and `cur/` in deterministic order, and never reads `tmp/`;
- nested Maildir folders, platform-specific filename extensions and mutable mailbox operations are
  outside the baseline;
- `mbox` is a closed unsupported format. S03 makes no byte-boundary, `From_` escaping,
  `Content-Length` or concurrent-compaction claim for it.

No Source path, account, profile or credential is autodiscovered. Creating a Source records the
explicit path and format but starts in `disabled` state with manual policy and no scan. Enable,
pause, disable, Run now and any later schedule are distinct local actions. Deleting a Source keeps
the canonical lifecycle tombstone and does not delete retained acquisitions.

## Original, identity and deduplication boundary

The complete message byte sequence is read with a fixed ceiling, hashed with SHA-256 and committed
as an immutable Original before parsing results can be promoted. The reader binds its open file
identity and pre-read snapshot, reads through that handle, then checks the handle and path snapshot
again. A disappearance, replacement, size/time change, link-policy violation or other mismatch
closes the item as mutated; no stale success is published. This detects the supported cooperative
mutation cases but is not described as a general filesystem sandbox.

The identity record separates:

- stable Source ID and adapter version;
- container profile and snapshot fingerprint;
- an opaque digest of the local locator plus the observed file identity where available;
- exact message SHA-256 and byte count;
- parser/contract version and effective limit/settings fingerprint;
- syntactically valid declared `Message-ID`, if present, as non-authoritative evidence.

Within one Source, exact content identity reuses the same message Document, Version and Original
even when a local locator changes; the new observation remains attributable. A replay with the same
observation and bytes does not duplicate an Acquisition or provenance. Equal bytes in different
Sources retain separate message, Document and Acquisition evidence and are not merged by S03, even
when the global content-addressed store safely reuses one immutable Original blob. The same
declared `Message-ID` with different bytes preserves both messages and records a collision. Missing,
malformed or repeated IDs do not prevent import of otherwise valid bounded bytes.

`References` and `In-Reply-To` produce only a Source-scoped observed thread. The derived relation
records the bounded evidence and reason; cycles, missing targets, repeated IDs and collisions stay
visible. It is neither semantic equivalence nor a cross-provider thread. Cross-Source qualification
belongs to S06.

## MIME, body and attachment boundary

Before `BytesParser` is invoked, the adapter enforces complete-message, header-block, header-count
and line-length ceilings. After parsing it walks a bounded MIME tree with cumulative part, depth,
transfer-output, body and attachment budgets. Defects, unknown/malformed charsets, repeated or
missing headers and malformed address syntax become closed warnings or failures; they are not
silently corrected into contacts or verified identities.

`text/plain` is the only readable body baseline. S03 deliberately does not perform HTML-to-text
fallback: HTML remains available only inside the preserved message Original and the representation
says that no text body is available. No email path executes or renders HTML, JavaScript or CSS,
resolves URLs, remote images, tracking pixels, forms or `cid:` references.

Strict `7bit`, `8bit`, `binary`, Base64 and quoted-printable transfer forms are accepted only
inside the cumulative budgets. The body charset profile is limited to US-ASCII/ASCII, UTF-8,
ISO-8859-1/Latin-1 and Windows-1252/CP1252. Unknown/malformed transfer encodings and invalid,
truncated or excessive decoded output fail closed; unsupported or invalid charsets produce an
unavailable body and explicit warning rather than invented text.

Each accepted attachment or inline part has a stable MIME-part identity, declared media type,
disposition, optional observed `Content-ID`, untrusted original-name observation, byte count and
SHA-256. Decoded bytes are committed as a child Original under an internal content-addressed name;
the MIME filename is never a storage path. Invalid, truncated or excessive transfer output fails
closed. `message/rfc822` is accepted only inside the nesting and cumulative budgets. Archives,
encrypted/signed parts and unsupported media are preserved but never expanded, executed,
authenticated or presented as scanned.

The parser does not claim malware scanning, legal-signature validation, DKIM/SPF/DMARC, PGP or
S/MIME verification. It never invokes a shell or external process.

## Persistence and durable execution

Canonical Source, Acquisition, Original, Document, DocumentVersion and provenance primitives
remain authoritative. Message and attachment Originals use the existing content-addressed store.
The envelope, selected body, bounded MIME tree, attachment index, observed thread and warnings form
one schema-versioned derived email representation. Its identity binds the exact message Original,
accepted attachment Originals, parser/adapter/settings identity and complete manifest checksums.

Staging is not a result. Promotion verifies the unchanged Source snapshot and atomically makes the
complete representation visible; no partial manifest, body, thread or attachment index is exposed.
Removing or rebuilding the representation changes neither Originals nor canonical knowledge.

The `email.intake` executor uses Vigilia's leases, heartbeat, bounded attempts, cancellation and
expired-lease recovery. Its idempotency binds Source, container/message observation, exact Original,
contract/adapter/parser and effective settings. A committed message checkpoint and committed
attachment checkpoints allow replay without duplicating already completed Originals, Versions,
attachments or provenance. One malformed message does not discard other valid messages; the job
closes `completed_with_errors` when appropriate. Terminal receipts contain only opaque IDs, counts,
closed codes and network/canonical-mutation facts—not subject, body, addresses, filenames or paths.

## Platform and packaging decision

The qualification target is deliberately narrow and is bound to the unchanged owner head by the
permanent real-parser smoke:

| Platform target | Architecture/runtime | EML | Maildir | Qualification boundary |
| --- | --- | --- | --- | --- |
| Ubuntu 24.04 | x86-64, CPython 3.12 | qualified | qualified | local regular files; POSIX link/mutation tests |
| GitHub-hosted Windows | x86-64, CPython 3.12 | qualified | unqualified | local regular file; hardlink/junction/reparse and mutation tests |
| Other Linux, Windows, macOS | any | unqualified | unqualified | no exact S03 smoke evidence |

Maildir is not advertised on Windows: standard Maildir `cur` naming and filesystem behavior are
not portable enough for an unqualified claim. EML and Maildir availability are reported
independently, with a closed reason for every unavailable combination.

S03 adds only Provelume Python code and schemas. `email` is part of the selected CPython runtime;
`mailbox` is evaluated but not selected for byte reading. There is no new runtime
dependency, parser wheel, native component, language pack, provider payload or runtime download.
The base wheel, sdist and Windows installer retain their existing dependency boundary; the release
CycloneDX inventory continues to be generated from the artifacts actually built.

## Alternatives considered

- Using `mailbox.Maildir` was rejected because its container abstraction does not prove the exact
  byte, link, locator and pre/open/post snapshot rules.
- Supporting mbox was rejected because S03 does not yet prove dialect, separator, escaping,
  truncation, `Content-Length` and concurrent-compaction boundaries end to end.
- An external MIME library was not selected: the bounded profile can be implemented behind the
  seam with CPython 3.12 and no new supply chain. A later replacement must preserve the contract and
  pass the same hostile corpus.
- Gmail, IMAP and POP were rejected for S03 because they add network, authorization, cursor and
  provider-specific evidence. Gmail/Drive remain S04 forecast only.

## Consequences and explicit limits

Email header identity and thread grouping remain observations, not truth. The baseline does not
resolve people, convert messages into facts/tasks/decisions, fetch content, render active HTML,
open attachments, expand archives or start OCR. Attachment OCR eligibility reuses the S01/S02
contract, but OCR remains disabled by default and requires its own explicit queue/run action.

The effective numeric limits are part of the schema, capability response and each job recipe; a
configuration may lower but never raise their hard ceilings. The EN/IT operating guides publish
the same values. A combination not positively exercised by the final exact-head smoke remains
unqualified even if the standard-library modules can be imported there.

S04 is the next forecast for Gmail/Drive adapters. This ADR does not create its issue, branch or
owner pull request and does not change the published `0.8.0` identity.
