# Versioned local transcript profiles

`0.9/S05` adds explicit local SRT and WebVTT intake behind provider-neutral contracts. This is
unreleased `0.9.0 Lectio` development. Package, runtime, embedded identity, latest public tag and
release remain `0.8.0`; S05 creates no tag, release, asset or version change.

## Closed profile matrix

| Profile | Accepted selector | Encoding | Timestamp grammar | Speaker handling |
|---|---|---|---|---|
| `srt-v1` | one `.srt` file or one non-recursive folder containing only regular `.srt` files | strict UTF-8 or UTF-8 BOM | `HH:MM:SS,mmm --> HH:MM:SS,mmm`; hours have at least two digits | not inferred; absence is explicit |
| `webvtt-v1` | one `.vtt` file or one non-recursive folder containing only regular `.vtt` files | strict UTF-8 or UTF-8 BOM | `MM:SS.mmm` or `HH:MM:SS.mmm`, plus bounded cue settings | one leading `<v label>` is an unverified observation; class-like, repeated or malformed voice tags are ambiguous |

This matrix is closed and schema-versioned. There is no plain-text profile. SRT uses the Library of
Congress format description plus the exact grammar above; it is not treated as a fully standardized
language. WebVTT uses the public W3C WebVTT specification but intentionally accepts a bounded
subset. `STYLE` and `REGION` blocks are rejected. `NOTE` blocks are ignored with a sanitized
warning. Header metadata such as media timestamp maps is not interpreted.

A future profile needs a public stable specification, reproducible synthetic fixtures, its own
versioned contract and permanent positive smoke. Proprietary profiles, provider exports without a
public stable grammar, auto-detection and silent fallback are absent.

## Authority order and canonical boundary

The adapter first snapshots one explicit selection. It opens each candidate read-only without
following links, captures bounded exact bytes, computes SHA-256 and rechecks file identity, size and
mtime before and after reading and again after parsing. The exact-byte buffer is authoritative; a
decoded string is never used to reconstruct the Original.

Only a complete, consistent transaction promotes the following chain:

1. content-addressed exact-byte `Original`;
2. provider-neutral `Document` for Source plus opaque locator;
3. `DocumentVersion` for the exact byte digest;
4. read-only `Acquisition` with no URL, origin, credential or derived-complete assertion;
5. provider-neutral transcript revision evidence;
6. checksum-bound derived manifest, cue JSON and text representation.

The generic canonical records use `application/octet-stream`. Format and encoding interpretation
belong to the derivation boundary. A malformed file produces a closed per-item error and no partial
canonical or derived promotion. A crash or cancellation cannot expose staged output as complete.

## Provider-neutral identities

| Object | Identity input | Explicitly not authoritative |
|---|---|---|
| Transcript / Document | internal Source ID plus Source-scoped opaque locator digest | filename, absolute/relative path, title, meeting/provider ID, URL |
| Revision / Version | transcript identity plus exact Original SHA-256 | filesystem mtime, declared language, timestamp order, provider revision ID |
| Cue | revision ID, ordinal, start/end milliseconds and cue-text SHA-256 | cue identifier, speaker label, timing settings, participant name |
| Original | exact-byte SHA-256 and size | decoded text, normalized newlines, parser output |

Equal unchanged bytes replay without a new Version or Acquisition. Changed bytes create a new
Version and revision under the same Source-scoped Document. Equal bytes observed through a
different Source have different transcript and Document identities; only the global exact-byte
Original may be reused. Reverting to an already retained digest follows the existing exact-content
Version contract and does not create semantic equivalence.

Filename, path, title, meeting ID, cue ID, speaker label, declared participant, language,
timestamp, URL and provider identifier are observations only. S05 does not attest that audio,
video, a meeting or a participant exists. It does not resolve a speaker label to a person. There is
no implicit merge or association with local email, Gmail, Drive or any other Source.

## Replaceable parser and derivation provenance

The first parser is `provelume.bounded-transcript` 1.0.0 behind parser protocol 1. A parser exposes
its ID, version, protocol and supported profile IDs. Its returned provenance must exactly match the
selected implementation or intake fails closed.

Parser, profile, format, adapter and filesystem observations are excluded from the provider-neutral
revision record. They are retained in
`state/transcript-intake/recipes/<revision>/<derivation>.json`, with:

- Original, transcript, revision, Source and connector internal bindings;
- profile and interpreted format;
- adapter and parser ID/version/protocol;
- exact settings fingerprint and every effective limit;
- opaque locator and filesystem-identity checksums plus observed mtime;
- explicit no-network, no-download, no-fallback and no-active-content declarations.

The derivation key hashes Original checksum, profile, parser identity/version/protocol and settings.
A replacement parser therefore creates a new recipe and derived artifact without creating a new
canonical Version or Acquisition when bytes are unchanged. Multiple recipes may be retained; the
newest valid complete artifact is exposed. Rebuild uses the newest retained recipe and requires its
exact parser. Missing parser versions fail visibly instead of substituting the current parser.

The schema-1 `transcript_bundle` records the same provenance and checksums for `cues.json` and
`transcript.txt`. Cue and text bytes are verified before inspection. Removal deletes only transcript
derived files, artifact records and derived provenance edges; it retains Original bytes, canonical
records and recipes.

Schemas shipped with the package are:

- `transcript_contract.schema.json` — explicit Source configuration;
- `transcript_revision.schema.json` — parser/format-free revision evidence;
- `transcript_recipe.schema.json` — reproducible versioned derivation;
- `transcript_bundle.schema.json` — complete manifest;
- `transcript_cues.schema.json` — inert cue representation.

## Encoding and text normalization

Only strict UTF-8 and UTF-8 with one leading BOM are accepted. UTF-16, locale encodings, invalid
UTF-8 and NUL fail with `transcript_encoding_unsupported`; there is no replacement-character or
encoding-detection fallback. Original bytes and their checksum never change.

BOM removal and CRLF/CR-to-LF conversion happen only in derived parsing. The manifest records BOM
presence and source line-ending style as `none`, `lf`, `crlf`, `cr` or `mixed`. Normalization emits
closed warnings. Text output joins cue text deterministically with two LF bytes and never claims to
be an Original.

## Deterministic anomalies

Invalid or zero/negative intervals, invalid timestamp syntax, excessive cue duration/timeline,
missing cue text and malformed structure are errors. The following are deterministic warnings:

| Condition | Code | Effect |
|---|---|---|
| repeated cue identifier | `cue_identifier_duplicate` | cue retained; identifier remains observation |
| same interval and text digest | `cue_duplicate` | cue retained; no semantic deduplication |
| interval intersects any prior cue | `cue_overlap` | cue retained; overlap remains visible |
| start precedes any earlier start | `cue_out_of_order` | input order retained |
| malformed/repeated/class-like voice tag | `speaker_label_ambiguous` | no speaker label promoted |
| no accepted speaker label in the file | `speaker_label_absent` | absence remains explicit |
| UTF-8 BOM | `utf8_bom_removed` | derived decode omits BOM |
| CRLF/CR source lines | `line_endings_normalised` | derived text uses LF |
| WebVTT NOTE block | `webvtt_note_ignored` | block content is not represented |

Warnings are closed, sorted and bounded. Unsupported profile/extension, ambiguous format,
unsupported encoding and malformed input fail visibly; no input is retried under another profile.

## Explicit Source and capability lifecycle

Each path/profile/selection configuration is one ConnectorInstance and one Source. Creation is
disabled and manual by default and performs validation only: no scan, parse, job, watcher or
network request starts. The connector definition declares `network_access: none`; its instance has
`network_mode: disabled`, no allowed origins, scopes, authorization or secret reference.

The operator separately chooses:

- an exact file or folder and `srt-v1` or `webvtt-v1`;
- enable, pause or disable;
- manual or bounded interval schedule;
- refresh/import, run, retry or cancel;
- cursor reset/resync;
- disabled-only reconfiguration;
- Source tombstone removal;
- derived representation removal or rebuild.

Folders are single-level. Every observed entry counts against the enumeration limit; nested
directories, links, reparse points, hard-linked files, special files and wrong extensions fail the
snapshot. Known UNC selectors are rejected. There is no recursive discovery, global search,
watcher, hidden backfill or source-side write. The adapter never changes, renames or deletes a
source file.

## Durable bounded execution

`transcript.intake` is a Source-scoped Vigilia job. Request identity binds Source/config revision,
selection snapshot checksum, profile, parser/adapter/settings identity and limits. Durable request,
work, run and cursor records omit paths, filenames, titles, transcript text and speaker labels.
Per-item journal state contains only internal IDs/checksums, size/count values, status and closed
errors.

Snapshot, work journal and Source cursor are confined to one Source. Batch/backfill stops at the
file, enumeration, total-read, temporary-space and duration limits. Scheduler retry is capped at
three attempts with 30-to-300-second bounded backoff. Checkpoints advance after each terminal item.
Cancellation is checked between items and bounded read/parser deadlines limit the current item.
Expired leases with progress are resumable; committed items replay as skips. A cursor reset clears
only that Source and marks explicit resync required.

A changed selection after queueing or a file mutation during read or parse yields
`transcript_input_changed`, promotes no new state and follows bounded retry. Per-item format errors
remain visible in `completed_with_errors`; the Source checkpoint stays incomplete with
`resync_required=true`. Atomic transaction recovery never labels a partial manifest complete.

## Closed limits

| Limit | Default | Contract ceiling |
|---|---:|---:|
| file bytes | 32 MiB | 256 MiB |
| files per job | 500 | 10,000 |
| enumerated entries | 2,000 | 50,000 |
| total bytes read | 256 MiB | 4 GiB |
| cues per file | 10,000 | 100,000 |
| characters per line | 16 KiB | 1 MiB |
| characters per cue | 64 KiB | 5 MiB |
| decoded characters per file | 2,000,000 | 50,000,000 |
| cue duration | 24 hours | 7 days |
| timeline end | 30 days | 365 days |
| warnings per file | 500 | 10,000 |
| item errors per job | 500 | 10,000 |
| temporary bytes per job | 512 MiB | 8 GiB |
| derived bytes per file | 32 MiB | 256 MiB |
| seconds per file | 30 | 300 |
| seconds per job | 600 | 86,400 |

Limit records are complete and reject unknown/missing fields. Total-read cannot be below file size;
enumeration cannot be below file count; temporary space cannot be below file size; and job duration
cannot be below per-file duration. Output size is measured after JSON/text serialization, which
prevents escape amplification from bypassing the derived-output bound.

## Inert-content and privacy boundary

Transcript text, cue settings and identifiers are never executed or interpreted as HTML,
JavaScript, terminal escapes, file paths or URLs. The parser performs no link following, resource
fetch, embedded-content load, template evaluation, shell/process execution or media association.
The Browser uses server-side autoescaping and renders source text in inert `pre` blocks. Content
Security Policy and loopback controls remain unchanged.

Logs, scheduler receipts, checkpoints and operational exports contain no transcript text, speaker
name, private title, filename/path, provider identifier, URL, credential, token or resolved secret.
They expose internal IDs, SHA-256 values, counts, closed status/error/warning codes and bounded
scheduler timing. The read-only API redacts configured paths and Source names; content is returned
only from an explicit revision inspection or exact-Original read.

No credential, provider SDK, model, codec, native payload or private fixture is added. Synthetic
fixtures use invented labels and `.invalid` URLs. Local execution creates no socket, runtime
download or remote fallback. Source configuration rejects known network selectors; other
OS-mounted/network filesystem behavior is outside the qualified matrix and must not be called a
no-network-qualified local Source.

## CLI, service, API and Browser

The application service owns all mutations. The `transcript-*` CLI family exposes capability,
Source create/list/show/state/configure/schedule/remove, checkpoint/resync, queue/run/job/retry/
cancel, revision/Original inspection and derived remove/rebuild.

The API is read-only:

- `GET /api/v1/transcripts/capability`;
- `GET /api/v1/transcripts/sources` and `/sources/{source_id}`;
- `GET /api/v1/transcripts/sources/{source_id}/checkpoint`;
- `GET /api/v1/transcripts/jobs` and `/jobs/{job_id}`;
- `GET /api/v1/transcripts/revisions` and `/revisions/{revision_id}`;
- `GET /api/v1/transcripts/revisions/{revision_id}/original`.

Revision content is opt-in with `include_content=true`; lists and summaries contain no source text.
The Original endpoint verifies checksum and size and returns opaque bytes. There is no upload,
remote intake, `POST`, `PATCH` or `DELETE` endpoint.

`/transcripts` provides semantically equivalent English and Italian status and local controls.
Mutations require loopback client, form content type, bounded body/field count and per-process CSRF
token. Non-loopback views omit paths and forms. Labels, fields and controls remain keyboard- and
screen-reader-addressable.

## Backup, portable transfer and validation

Verified backup/restore includes canonical records, exact Originals, durable Source/job state,
recipes and derived state. Portable export/import preserves Source isolation and exact-byte
bindings. Deep validation checks the neutral revision chain, recipe identity/settings, manifest and
representation checksums, Source confinement, no-active/no-network flags and operational-state
privacy keys. Missing/corrupt bindings fail visibly.

## Conformance and qualification

Conformance, platform evidence and real-provider qualification are different claims:

| Tier | Evidence | Allowed claim |
|---|---|---|
| deterministic profile conformance | synthetic valid/hostile SRT/WebVTT fixtures and full unit/integration suite | parser behavior for the exact profile/contract only |
| permanent platform smoke | `.github/workflows/transcript-smoke.yml` on the unchanged candidate head | SRT/WebVTT local qualification only for the positive OS/architecture/CPython rows |
| platform preview | local Browser/CLI/API behavior outside a positive permanent row | preview, not qualification |
| real provider qualification | no permanent authenticated provider matrix exists | `false`; no cloud/provider claim |

The permanent target matrix is Ubuntu 24.04 x86-64 and Windows Server 2025 x86-64, both with
CPython 3.12, for `srt-v1` and `webvtt-v1`. The manifest defines the target; a commit becomes
qualified only after both exact-head jobs are positive. macOS, ARM, other Python versions,
non-UTF-8 encodings, plain text, proprietary profiles, cloud imports and provider exports remain
unqualified.

The smoke denies Python socket/DNS entry points and proves exact-byte Original, both parsers,
inert hostile strings, provider-neutral mapping and deep validation with synthetic data only. It is
not an authenticated provider smoke and does not qualify audio, video, meetings or people.

## Explicit exclusions

S05 adds no audio/video ingestion, speech-to-text, ASR, Whisper, diarization, model download,
automatic media association, Plaud/Zoom/Teams/Meet import, Calendar, email sending, Gmail/Drive
write-back, cross-Source qualification, human correction flow, Action Center, AI/RAG, summary,
classification, claim/decision/task extraction, cloud OCR or provider AI. S06 remains later
cross-source qualification/correction work. S07 Windows shell/installer UX and port `44851` are
unchanged.

See [ADR 0018](../adr/0018-versioned-transcript-profiles.md), the
[Italian contract](transcript-profiles.it.md) and the [API guide](../api.md).
