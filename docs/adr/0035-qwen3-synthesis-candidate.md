# 0035 — Qwen3 candidate for bounded document synthesis

Status: candidate selected before scoring, 2026-10-09. Maintainer-authorized AI
profile revision for 0.12 Custodia; sole S08 owner PR #333 / issue #332. This is
not Recommended promotion or release authority.

## Evidence and choice

The eight retained Qwen2.5 candidates did not qualify S08. ADR 0034's structured
decoder produced 32/32 valid responses and 8/8 required abstentions on each native
host, but only 18/32 correct selections on Windows and 17/32 on Linux. All four
task/language semantic gates failed. Format enforcement alone is insufficient.

Select one replacement: official **Qwen/Qwen3-1.7B-GGUF**, revision
`7fb011e9aee6e4dc7adf8430df9ea8de6a466aa3`, file
`Qwen3-1.7B-Q4_K_M.gguf`, **1,107,408,544 bytes**, SHA-256
`228fb5627f7510b8b3516cdb6435e4b0d2a2bf330fe5b0ab19284a3570a8bb1f`.
The official immutable LFS pointer supplies the size/digest before acquisition.
Use Apache-2.0 with Copyright 2025 Alibaba Cloud; retain the complete license in
`runtime_notices/qwen3-LICENSE.txt` with normalized LF line endings. The previous
Qwen2.5 license and historical qualification records remain retained.

This small dense transformer provides a native non-thinking mode and multilingual
instruction following without adding another inference framework. It is a
bounded extension of the original small-model direction, not a claim that its
parameter count or upstream benchmarks establish Provelume quality. No automatic
model sweep or fallback to the previous unqualified synthesis model.

## Runtime and unchanged acceptance

Keep the exact llama.cpp b11379 libraries, CPU/RAM/input/output/deadline bounds,
greedy decoding, source isolation and fresh per-request GBNF sampler. Use the
official ChatML non-thinking assistant prefix, including an empty
`<think>\n\n</think>\n\n` block. It selects the supported non-thinking mode without
asking the user document to control runtime behavior. No hidden reasoning output,
new network call, tool, sampling sweep or extra inference attempt is introduced.
The upstream warning against greedy decoding concerns thinking mode; non-thinking
sampling suggestions are not a substitute for this task's actual qualification.

New model and chat-template identities invalidate prior runtime/self-test/consent
bindings. Registry/runtime code continues to arrive through ordinary application
distribution; model acquisition never installs executable code.
Keep the old governed entry as RETIRED so an existing installation's selection
remains readable and the old bytes can be explicitly deactivated/removed. Exclude
it from discovery and reject installation, self-test, activation, use and rollback;
retained metadata grants no runtime authority. Never silently delete old weights.

Preserve ADR 0033's exact 32-case corpus, gold and all 26 S05–S08 quality,
abstention, latency, memory, cancellation, responsiveness and no-egress gates.
The original S05 corpus also runs unchanged against the replacement. Every failed
case, sample and candidate stays recorded. Missing evidence is NOT_RUN; model
replacement does not establish acceptance or qualify an unobserved machine.

The separately diagnosed Capture correction sizes a fresh read from its observed
file length plus one byte rather than allocating the 36 MiB maximum per small
record. It retains the hard size cap, pinned Windows handles, complete record
validation and before/after file identity checks. No durability or authority
check is cached or removed, and diagnostic timings never replace scored samples.

## Primary sources

- [Official immutable model files](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/tree/7fb011e9aee6e4dc7adf8430df9ea8de6a466aa3).
- [Immutable GGUF pointer](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/raw/7fb011e9aee6e4dc7adf8430df9ea8de6a466aa3/Qwen3-1.7B-Q4_K_M.gguf).
- [License and attribution](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/blob/7fb011e9aee6e4dc7adf8430df9ea8de6a466aa3/LICENSE).
- [Official non-thinking mode](https://huggingface.co/Qwen/Qwen3-1.7B#switching-between-thinking-and-non-thinking-mode).

S09 activation/promotion still follows accepted S08 actual main. Application
version/tag/publication remain in the independent final release workstream.
