# 0047 — Hybrid CPU candidate with a bounded sequence checkpoint

Status: selected before scoring, 2026-10-09. Authorized profile revision for
0.12/S08, sole PR #333 / issue #332. Not acceptance or Recommended promotion.

## Evidence and selection

Candidate20 completed all 32 native cases on each host, but selected only 24 gold
results on Windows and 22 on Linux, with five/four required abstentions of eight.
Both failed semantic qualification; Linux also failed inherited Capture latency.
All twenty preceding unsuccessful candidates and their complete/partial evidence
remain retained. Another prompt wording change has no demonstrated justification.

Select **Qwen3.5-2B Q5_K_M**, a different multilingual hybrid architecture already
implemented by the locked llama.cpp revision. The hypothesis is better extraction
quality within the existing CPU/memory budget, not a claim of improvement. Keep
the entire canonical v7 task, four trusted examples, grammar and lossless mapping
unchanged. The official non-thinking ChatML template ends the generation prompt
with an empty `<think>\n\n</think>\n\n` block. Earlier demonstration responses have
ordinary assistant framing. No vision encoder, tools or thinking mode is enabled.

Separate upstream and conversion provenance:

- Upstream `Qwen/Qwen3.5-2B`, revision
  `15852e8c16360a2fea060d615a32b45270f8a8fc`, Apache-2.0.
- Reviewed conversion publisher `unsloth/Qwen3.5-2B-GGUF`, revision
  `f6d5376be1edb4d416d56da11e5397a961aca8ae`. This is **not** an official Qwen GGUF.
- File `Qwen3.5-2B-Q5_K_M.gguf`, **1,435,238,656 bytes**, SHA-256
  `1885b3a9195f8cc09da9a7a7a75afdc1e8d5cbf9fc4a499c3961dddea37098ac`.
- Full upstream license, **11,544 bytes**, SHA-256
  `bbedc3fda3305820b977265f01b8619d87570a6739de3a5582c3464840f1e57a`;
  exact Git blob `f938136e3adacfd92be087f6e113b5d6d97f678f` independently matches
  publisher metadata. Preserve its original CRLF bytes in distribution.

Public metadata and the exact license are inspected before selection. Explicit CI
acquisition must verify the immutable conversion's full size/hash; metadata alone
does not authenticate downloaded bytes or grant inference authority. No new
acquisition origin, ambient credential, model resolver or automatic fallback.
The six preceding native artifacts remain RETIRED with exact pins and licenses.
Separate the bounded nine-entry registry from the unchanged eight-package installed
limit; retaining failed identities must not silently delete installed packages.

## Recurrent state and request isolation

Arbitrary suffix removal is not supported by this hybrid's recurrent state without
per-token snapshots. Do not enable an unbounded rollback history. Use one complete
sequence checkpoint from the existing locked `llama_state_seq_*` ABI, bounded to
64 MiB and held only in the worker's memory. Set recurrent rollback history to zero.

For governed calls, checkpoint after the exact tokenized trusted prefix, or at 128
input tokens when that prefix is shorter, always before the final input token.
This is a computation boundary, not a content classification. It may include an
initial private prefix; reuse requires every saved token to equal the current
prefix and the same non-null Instance scope. Shorter/divergent inputs, scope changes
and unscoped calls clear all state. Never restore a previous response or a partial
recurrent suffix. Decode the entire remaining current input for fresh logits.

Validate checkpoint size, complete write/read and native position before reuse.
Zero and release its buffer on replacement/close. One checkpoint, one sequence,
one inference, no inference retry. All checkpoint/tokenization/copy costs remain
inside the existing wall-time/RSS/deadline accounting; every logical input token
remains charged. This creates no cached consent, policy, output or self-test grant.
Fresh runtime/template identities invalidate all preceding authority.

## Lifecycle correction and acceptance

The separately reproduced scheduler gap can reject a claimed job before dispatch,
or lose settlement while another short lifecycle owner runs. Wait up to two seconds
at initial execution and completion, then validate the current lease and authority
under the lock. Retain an observed outcome during that wait; never repeat inference.
Cancellation during either wait must prevent result publication, retaining actual
known usage if a response was already received. Persistent contention remains a
visible failure/owned recovery state, not an automatic resend.

Candidate20's Linux Capture diagnostic observed repeated ancestor walks for each
receipt (over a thousand `lstat` calls per probe), alongside variable `fsync`
latency. Its post-scoring busy samples did not prove concurrent generation, so
they are attribution only, not substitute passing measurements. POSIX inventory
now traverses once through no-follow directory descriptors, reads each current
record relative to its pinned device, and rechecks every directory binding before
returning. Two regressions first reproduced stale results when the Capture or
device directory was replaced after the last record read. The new path rejects
both, closes all descriptors on failure, and rejects symlinks/FIFOs without following
or blocking on them. Size, fingerprint, per-record identity, fresh Instance identity
and every durable write/fsync remain mandatory. No cached inventory or weakened
durability gate is introduced; fresh native responsiveness still must pass.

ADR 0033 and both frozen corpora/gold remain byte-identical. Keep all 26 quality,
abstention, native latency, Capture/search, CPU, context, input/output, RSS, hard
memory, cancellation and twenty-minute workflow gates. The exact artifact-size
pin changes; no numeric acceptance limit increases. Fresh complete Windows/Linux
and application/release checks must pass independently. Actual-main S08 acceptance
precedes S09; human final-artifact and live-provider evidence remain separate.
No version, tag, publication or mutation of published v0.11.0 is authorized.

Sources:

- https://huggingface.co/Qwen/Qwen3.5-2B
- https://huggingface.co/Qwen/Qwen3.5-2B/blob/15852e8c16360a2fea060d615a32b45270f8a8fc/chat_template.jinja
- https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/tree/f6d5376be1edb4d416d56da11e5397a961aca8ae
- https://github.com/ggml-org/llama.cpp/blob/1537a0a8b2f8711d840878b0a0677ab2213c882c/include/llama.h
- https://github.com/ggml-org/llama.cpp/blob/1537a0a8b2f8711d840878b0a0677ab2213c882c/src/llama-memory-recurrent.cpp
