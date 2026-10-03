# Custodia bounded context (0.12/S02)

Parent #311; S02 #314 follows completed S01 #312 / PR #313. `ai_context.py` adds
ephemeral schema-version-1 dataclasses and the static internal
`ProvelumeInstance.ai_context_preview` seam. No Instance is opened, no path is read,
and nothing is persisted, transmitted or executed. There is no new canonical object,
API, CLI, screen, provider transport or job. S07 owns the eventual user preview;
S08 owns synthesis. The package/runtime identity remains 0.11.0.

## Trust and explicit selection

The caller supplies an independent `SourceSnapshot`: exact Instance, Document,
Document Version and Original identity, the admitted inventory of existing representation
bundles as immutable JSON bytes, and bytes for explicitly selected outputs only.
The producer must establish Document/Instance membership and inventory completeness from
authoritative state; S02 does not invent an authoritative filesystem collector. Like S01's
governance snapshot, this internal input is trusted for provenance, never supplied by a
document, model or public API. A matching checksum proves byte integrity, not provenance.

Each `Selection` repeats the exact version, representation ID and revision (canonical
bundle digest), output ID, existing anchor ID and half-open original Unicode-code-point
range. Unknown fields, paths, URLs and arbitrary handles are not selection mechanisms.
Bundle validation reuses `validate_representation_bundle`; Version/Original membership,
output hash/size, canonical ordinal anchor identity, page and range membership are checked
again. Missing bytes, altered anchors, duplicate/overlapping ranges and cross-document
references fail closed. Storage paths and metadata are never opened, rendered as instructions,
or put into the task payload. Even bytes for an unselected output are rejected.

The bounded text profile accepts strict UTF-8 `text/plain` with existing `page` anchors:
form-feed separates pages; a document without form-feed has one page. Selection offsets
refer to the original decoded output before CRLF/CR-to-LF and NFC normalization.
A range cannot cross a page. This is a narrow representational profile, not a new parser
or a claim of support for every Perceptio/legacy extraction profile. Time/region/sheet/cell/
member/reserved anchors, binary or JSON assets, unavailable/removed bundles and bundles with
correction annotations are explicitly unsupported for payload inclusion in v1. No Original,
attachment, HTML execution, OCR, ASR, tokenizer or model is loaded. Future profile extensions
must define their own exact mapping through existing representations, under normal gates.

## Honest coverage, normalization and limits

The typed manifest records all bundle revisions, exact selections, included/excluded/
unsupported outputs, partially selected outputs, effective bounds, normalized content digest,
S01 effective policy fingerprint, independent governance revision/scopes/network state,
consent revision, template identity and redaction-profile/configuration digest. Canonical
serialization reuses sorted-key compact UTF-8 JSON, no NaN, and a trailing newline.
Selection and bundle input permutations do not change the normalized context.

`complete` means every text code point in every admitted output is covered. Page delimiters
are structural. The scope is always `admitted-representation-output-bytes`, never the entire
Original, semantic completeness, the library or unobserved representations. `partial` retains
the selected ranges and explicit exclusions/unsupported inventory. `absent`, `excessive` and
`unsupported` carry no payload. A complete-only template rejects partial coverage; the explicit
partial template accepts it. There is no silent truncation or fallback. Malformed identities
and descriptor/asset-envelope excess return closed S01 errors, not a usable context.

Absolute envelopes are 128 KiB aggregate bundle/selection descriptor material, 1 MiB supplied
source bytes, 32 assets and 256 selections. Caller limits can only narrow these; defaults are
64 KiB context, 64 segments and 16 assets. Limits are checked before JSON parsing, output
decoding, or joining a task payload as applicable. JSON has bounded depth/node traversal and
rejects duplicate keys. Manifest serialization is also capped. The complete payload includes
trusted instructions, the envelope and JSON escaping; it must fit both context limits and
S01's effective request byte ceiling. No excessive payload is returned.

Token accounting is explicitly **`utf8-bytes-v1-proxy`**: one unit per UTF-8 byte, with
`exact_tokens: null`. Manifest units describe normalized selected source text; preview
diagnostics and `RequestDescriptor.input_bytes` describe the complete redacted envelope.
These are exact byte counts and a conservative planning proxy, **not an exact tokenizer
count or a universal upper bound for arbitrary models/chat protocols**. The synthetic
candidate output is bounded to the smaller of 16 KiB and the S01 output-token ceiling
interpreted as byte proxy units. No real inference or monetary billing guarantee is made.
A later transport/runtime must qualify its tokenizer/framing and actual context capacity;
S02 cannot qualify a model from this estimate. No tokenizer/model download is needed.

## Local redaction and invalidation

The immutable `literal-email-v1` profile recognizes the documented ASCII email pattern and
up to 32 exact, case-sensitive NFC literal strings (at most 256 characters each). Matches
are replaced with `[REDACTED]`; overlapping matches are merged to avoid retaining an
overlapping sensitive suffix. Events retain segment indexes, original normalized offsets
and closed rule IDs, never matched private strings. Match count is bounded. Preview text
is local private data, separate from its content-free diagnostic record.

This does not recognize all sensitive information: names, addresses, telephone numbers,
obfuscated/international email, variants/case differences, omitted content and patterns
split across selected segments may remain. It is not anonymization. The preview states
these limitations even when it finds no matches. It does not edit Original bytes,
representations, annotations or canonical knowledge, and never grants consent or inference.

Preview identity covers the complete manifest, redacted segments, events and limitations.
Every consuming operation regenerates the preview from current inputs and compares the
complete value. Changes to Version/Original, inventory or representation bytes/metadata,
selection, policy, governance, consent, template, request/context limits or redaction
invalidate retained previews and results. Versioned profiles must not change semantics
in place. Fingerprints bind data and are not signatures or execution tokens.

`prepared_request` is the explicit bridge: it rebuilds the preview, creates an S01 request
using its fingerprint and measured envelope bytes, and projects that binding into the
independent current governance snapshot. `explain_prepared` then invokes S01 unchanged.
S01 alone resolves policy; monotone ceilings, local-only, ordered routes, independent
locality evidence and request limits remain in force. The test harness regenerates and
revalidates both context and plan **before invoking even the fake** for off/deny/stale.

## Trusted template and untrusted result

Two repository-owned versioned `context-check` templates differ only in whether explicit
partial coverage is acceptable. Their identity hashes the closed result contract and fixed
instructions. The JSON task envelope separates `trusted` instructions/template from
`untrusted` segments. Quoting, role-like JSON, URLs and commands inside text remain inert
strings. Metadata is absent from that instruction channel. There is no tool registry,
credential lookup, route field, dynamic schema, link opener or execution hook.

The minimal synthetic result schema is exactly `schema_version`, `preview_fingerprint`,
`status` (`checked` or `abstained`) and unique integer `references` into current segments.
Each reference resolves through the freshly validated exact anchor and selected range.
`checked` requires a reference; `abstained` requires none. Unknown fields, actions, free
text, malformed/duplicate JSON, wrong versions, stale bindings, out-of-range references
and excess bytes are rejected. A valid result remains `untrusted_data_only`: it is neither
semantic truth nor execution/application authority. No synthesis or canonical write exists.

## Executable evidence

Run `python -m pytest -q tests/test_ai_context.py::test_executable_s02_demonstration` using
the repository's native environment. It exercises valid redaction and synthetic planning,
partial/excessive context, stale preview refusal and hostile-result rejection. The broader
S02 suite covers exact identities, malicious content, limits, redaction, invalidation,
forged previews, content-free diagnostics and no socket/DNS/filesystem/environment/credential/
subprocess access. Fixtures and adapters live only in `tests/`. Native full pytest and
Ruff, exact-head CI and the existing Protocol/review/ancestry gates remain mandatory.
