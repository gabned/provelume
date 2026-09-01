# ADR 0018: provider-neutral versioned transcript profiles

- Status: accepted for unreleased `0.9/S05`
- Date: 2026-09-01
- Owner issue: [#151](https://github.com/gabned/provelume/issues/151)
- Owner PR: [#152](https://github.com/gabned/provelume/pull/152)
- Parent tracker: [#137](https://github.com/gabned/provelume/issues/137)
- Public identity: `0.8.0`

## Context

Lectio needs to ingest existing transcript files without making a subtitle syntax, parser,
filename, meeting identifier, speaker label or cloud provider part of canonical knowledge. The
connector framework already supplies isolated ConnectorInstance and Source identities, explicit
lifecycle controls, Source-scoped scheduler state and immutable Original/Document/Version/
Acquisition bindings. S02 supplies the removable document-bundle pattern; S03 and S04 establish
exact-byte, non-authoritative observation and read-only provider boundaries.

Transcript inputs are unusually easy to over-interpret. Cue order and timestamps do not prove that
audio, video or a meeting exists. A voice tag does not verify a person. Markup, links and embedded
references may be hostile. Permissive parser fallback can also turn malformed or incorrectly
encoded bytes into apparently trustworthy text.

## Decision

S05 defines a closed profile matrix containing only `srt-v1` and `webvtt-v1`. Each profile has a
strict UTF-8/UTF-8-BOM grammar, explicit extension, closed limits and deterministic warning/error
behavior. The first implementation is the first-party `provelume.bounded-transcript` parser 1.0.0
behind parser protocol 1. Parser implementations are replaceable; a parser change creates a new
derivation recipe and artifact identity, not a new canonical Version when Original bytes are
unchanged.

Every explicit file or non-recursive folder configuration creates its own disabled
ConnectorInstance and Source. The definition declares `network_access: none`; the instance has a
disabled network mode, no origins, no authorization and no credentials. Enable, pause, disable,
reconfigure, remove, refresh, retry, cancel and resync are separate local actions. Known UNC
selectors, links, reparse points, hard-linked files, recursive entries and unsupported extensions
fail closed.

Exact bytes are bounded, snapshotted, read without following links, hashed and rechecked before a
parser result is accepted. Canonical transcript and revision identities use only internal Source,
opaque locator and exact-byte identities. Core Document/Version/Acquisition records use a neutral
octet-stream media type. Profile, format, parser, settings and filesystem observations live outside
the canonical record in a durable derivation recipe and checksum-bound derived manifest.

Cues are derived, provider-neutral observations identified from the revision, ordinal, interval
and text checksum. Cue identifiers, timing settings and speaker labels remain non-authoritative.
Invalid intervals fail; duplicate identifiers/cues, overlaps, out-of-order cues and ambiguous or
absent speaker labels produce closed deterministic warnings. No cross-Source merge, semantic
deduplication, participant resolution or association with email, Drive, audio or video occurs.

Derived cue JSON and plain text are inert, removable and rebuildable from the Original plus exact
recipe. Removal retains canonical records, Original bytes and recipes. A rebuild requires the
recorded parser identity/version; it never silently substitutes another parser. Atomic promotion
and transaction recovery prevent a partial bundle from being declared complete.

## Consequences

- SRT and WebVTT can evolve through new explicit profile/parser versions without changing the
  provider-neutral canonical model.
- Equal bytes replay idempotently; changed bytes create a new DocumentVersion; equal bytes in
  different Sources retain separate transcript/Document identity while sharing only the
  content-addressed Original.
- Malformed, ambiguous, unsupported or non-UTF-8 files fail visibly without a fallback profile or
  encoding guess.
- Operational state contains internal IDs, checksums, counts, closed status/error/warning codes
  and scheduler timing only; transcript text, filenames, paths, titles and speaker labels are not
  journaled.
- The local parser performs no socket operation, runtime download, remote lookup, active rendering
  or source mutation.
- Public conformance uses only synthetic fixtures. Ubuntu 24.04 and Windows Server 2025 x86-64 on
  CPython 3.12 become qualified for these exact profiles only after the permanent transcript smoke
  succeeds on the unchanged candidate head. No provider or cloud matrix is claimed.

## Rejected alternatives

- One global transcript folder or watcher: rejected because selection and activity must be
  explicit and Source-confined.
- A permissive auto-detect/fallback parser: rejected because malformed and ambiguous inputs must
  fail visibly.
- Plain text with inferred timestamps, speakers or meeting structure: rejected because missing
  structure cannot be promoted as certainty.
- Provider-specific canonical records: rejected because provider replacement must not migrate
  canonical knowledge.
- Browser upload or authenticated provider intake: rejected because the S05 API is read-only and
  cloud qualification belongs to later explicitly scoped work.
- Audio/video ingestion, ASR, diarization, AI summaries or cross-source linking: rejected as S05
  scope expansion.

See the [English architecture contract](../architecture/transcript-profiles.md) and its
[Italian counterpart](../architecture/transcript-profiles.it.md).
