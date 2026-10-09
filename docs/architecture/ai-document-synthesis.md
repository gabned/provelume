# Manual document synthesis — S08 development candidate

Owner [#332](https://github.com/gabned/provelume/issues/332), parent #311.
S07 was accepted through #325 then #331 at actual main
`b4cebcfb16a67eb7375d11a9217f25818d141e3f`; its original failed post-merge
observation remains historical. This development does not publish a release or
promote the model. Package/runtime identity remains 0.11.0 — Cura.

[ADR 0033](../adr/0033-extractive-document-synthesis.md) fixes the evaluation;
[ADR 0034](../adr/0034-structured-synthesis-runtime.md) records the authorized
structured runtime revision after seven failed candidates. Its first Qwen2.5
measurement passed format/abstention but failed semantic quality on both hosts.
[ADR 0035](../adr/0035-qwen3-synthesis-candidate.md) pins the Qwen3-1.7B Q4_K_M
replacement and non-thinking chat template before separate native scoring.
Summarize and Key points select excerpts,
not model-authored facts. The task/language matrix is EN/IT, independently of the
seven interface catalogs. All real quality/performance outcomes belong to the
exact-head and actual-main owner ledgers; synthetic tests are not native proof.

## User path and authority

Document → Synthesis (`/documents/{id}/synthesis`) → select text, task and language
→ explicit private preview → consent and Generate → existing AI Operations →
result and exact evidence (`/operations/ai/{job}/synthesis`). GET never executes,
downloads, probes or looks up credentials. Existing authentication, loopback checks,
Instance identity, CSRF, one-use nonces and owned task shutdown apply to every
route. Only a supported new template can enter the document execution path;
S07's legacy document preview remains non-executable.

Every queued/active call reads fresh current Version, bounded actual Original
bytes, canonical bundle and selected output, related acquisitions/classification
ancestors, configuration and Instance network policy. Original/bundle/output hashes
and selections bind the recipe. Pure preparation reuse never caches mutable
authority. Local session/self-test evidence is still required to execute. Existing
native/provider adapters use the same closed candidate validator; the native zero
monetary quote continues to depend on the exact trusted adapter type. External
pricing and live provider qualification are not invented for this task.

Explicit HTTP execution is acknowledged only after the existing scheduler claims
the job under its lifecycle barrier and fresh admission checks. A bounded two-second
wait can absorb brief contention before any attempt starts. A persistent conflict
returns a visible error with no consumed attempt; trying again requires a fresh
explicit request. The host owns the claim/execution task before awaiting this
acknowledgement, so request cancellation cannot abandon a newly reserved job.
Inference itself stays asynchronous and is never automatically resent.

The S08 model payload contains the task ID, instructions and indexed approved
redacted paragraphs. Authority fingerprints and template revision hashes stay in
the host manifest and job binding rather than adding random non-content tokens to
the model input. Equal text payloads still have distinct consent and candidate
bindings. The legacy context-check payload remains unchanged. Negative,
conditional and masked statements are eligible document content; commands to the
AI and editorial boilerplate are not. Selection does not verify a claim's truth.
The native adapter supplies a closed task descriptor separately from the approved
JSON envelope. The worker rechecks task identity, exact trusted instructions,
segment count and contiguous indexes, then places the task in the system role and
quoted source paragraphs in the user role. A fresh grammar/greedy sampler per
request limits output to the closed JSON schema, abstention or unique source-ordered
references within the task maximum. Native prefix reuse never retains sampler state.
Practical subject-matter instructions remain eligible; commands to the assistant
and editorial notices are excluded by the semantic task, not corpus-specific filters.
Grammar proves shape, not relevance. The existing result validator remains mandatory.
The profile is bound in template and runtime configuration identities, invalidating
old consent and self-test evidence. The full native envelope keeps the approved byte
budget. Provider chat retains its existing role separation and result validation.
The candidate byte bound applies before both JSON and literal `UNKNOWN` parsing.

Optional `state/scheduler/ai-scope-policies.json` stores at most 128 deny/local-only
restrictions with Instance identity and revision. Absent rules explicitly inherit
the global AI settings. All applicable Source, category, Area/Project and ancestor
scopes go through the existing S01 resolver. No separate policy resolver is added.
The advanced document controls can only edit a currently associated scope and
cannot grant a provider, network or model permission. Changes clear consent under
the existing authority/lifecycle transaction. Scheduler validation/portability
recognizes and validates this closed bounded record.

## Result commit, read, discard and regeneration

The trusted result projector runs in the existing job completion transaction,
after usage settlement and current-authority revalidation. It rejects unsupported
references and projects literal approved redacted segments into a private bounded
file under `state/derived/ai-synthesis-job_*.json`. Up to 128 bodies of 32 KiB each
are admitted. A pinned local parent and atomic no-overwrite write avoid following
symlinks or publishing over another record. Jobs retain a closed `derived_ref`
with exact non-payload recipe, source/policy association, body digest, model and
route. Public job projections omit the entire result; receipts contain no text.

Validation/storage failure settles known usage and fails without automatic resend.
A crash between file publication and the job commit can leave an orphan file;
the HTTP path requires a successful authoritative job association, so that orphan
is not a result. Terminal replay never recreates a discarded body. Unknown remote
outcomes keep the existing conservative accounting and manual reconciliation.

Reads recheck current source/policy association, the body digest, source-derived
redacted segments and candidate references. Session disablement, self-test expiry
and restart alone do not invalidate a stored result. Changed source/configuration
or restrictions do. A private cited-evidence route shows the exact recorded
Version/anchor/offsets and approved masking; it does not claim an unmasked original
quote. Responses use no-store/no-referrer and normal template escaping.

Discard removes only the private body under the lifecycle/journal exclusion and
works even when its source association is stale. Receipt, recipe and accounting
remain. Missing bodies are reported as unavailable, not attributed to an invented
deletion event. Regeneration creates a fresh visible preview and requires new
consent. A changed source needs a newly selected current representation. There is
no automatic regeneration or bitwise result guarantee. Portable exports/backups
include the private derived body; existing backups can retain discarded copies.

## Limits and remaining qualification

The inherited Capture responsiveness gate still applies during synthesis. Windows
Capture inventory reads pin ancestor/device directory handles for one operation
and deny writers/delete on each record while reading it. This avoids repeating
full ancestor metadata walks per record without caching records or mutable
authority. Every record and the Instance identity remain freshly validated; all
handles close on success and failure. POSIX retains its existing read path.

The profile handles one text output, at most 1 MiB actual Original/output, sixteen
whole paragraphs and 2,000 selected UTF-8 bytes; the complete envelope stays below
4,096 bytes. No paragraph truncation. Coverage is relative to the selected admitted
representation, not all representations or the entire Original. Scope inventory
reads are bounded to 512 records in each relevant canonical collection.

Browser/keyboard/zoom and seven-catalog checks are separate from actual screen-reader
and human linguistic review. S07's maintainer Narrator report is not extended to
these new surfaces. No generic chat, multi-document RAG, canonical classification,
new scheduler, autonomous operation, Recommended promotion or publication.
