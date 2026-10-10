# 0040 — Granite candidate for bounded document selection

Status: selected before native scoring, 2026-10-09. Maintainer-authorized model
profile revision within S08 PR #333 / issue #332 for 0.12 Custodia. No Recommended
promotion, S09 acceptance or publication authority.

## Evidence and choice

All thirteen prior candidates remain failed in the owner ledger. The latest
Qwen3-1.7B assessment profile completed all 32 cases on each native host, with
valid references and all eight required abstentions, but only 19 gold selections.
All four semantic gates failed; the other 22 gates passed. It still confused
subject matter and assistant instructions or abstained despite useful content.
The previously evaluated 4B Q2_K profile exceeded the fixed latency limits.

Evaluate IBM's official Granite-4.0-1B dense instruct model in Q5_K_M. The name
contains 1B; the publisher describes approximately 1.6B actual parameters, forty
attention layers and explicit EN/IT support. Its instruction/structured-output
training and comparable file size make it a plausible alternative, not proof of
Provelume accuracy, latency or laptop support. Q5_K_M preserves more precision
than the earlier four-bit candidate within the same resource ceilings.

Keep the exact `extractive-assessed-decisions-v4` method, two fixed editorial
examples, grammar, assessment bound and lossless position mapping from ADR 0039.
Only the model and its canonical role framing change. No new task examples,
source-dependent selection rule, semantic post-filter, retry or corpus oracle.

## Immutable candidate and provenance

- Model ID: `granite-4.0-1b-q5-k-m`; format: `gguf-v3-q5_k_m`.
- Official conversion repository: `ibm-granite/granite-4.0-1b-GGUF`.
- Revision: `b27c2fe3f211b7f44e80fa620177aea371099aaa`.
- File: `granite-4.0-1b-Q5_K_M.gguf`, exactly 1,178,310,400 bytes.
- SHA-256: `3d977db90ec00a2152cc3cdb788f7273c6258f49394a914046cc90c266831598`.
- Acquisition URL:
  `https://huggingface.co/ibm-granite/granite-4.0-1b-GGUF/resolve/b27c2fe3f211b7f44e80fa620177aea371099aaa/granite-4.0-1b-Q5_K_M.gguf`.
- The publisher's pinned Git LFS pointer independently supplies size/digest:
  [pointer](https://huggingface.co/ibm-granite/granite-4.0-1b-GGUF/raw/b27c2fe3f211b7f44e80fa620177aea371099aaa/granite-4.0-1b-Q5_K_M.gguf).
  The repository history identifies IBM/gguf's release workflow, run 24843593968,
  tag `v4.0-language-refresh-20260423-01`. A workflow reference is provenance,
  not a substitute for independently checking the complete acquired bytes.
- Apache-2.0. The complete unchanged publisher license is retained as
  `runtime_notices/granite-LICENSE.txt`, from
  [IBM's model repository at de23701](https://github.com/ibm-granite/granite-4.0-language-models/blob/de23701d1627c767cfc91a0ccfa360a5b247dde2/LICENSE).
  License: 11,357 bytes, SHA-256
  `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`.

Primary design references: [publisher model card](https://huggingface.co/ibm-granite/granite-4.0-1b)
and [Granite prompt guide](https://github.com/ibm-granite/granite-4.0-language-models/blob/de23701d1627c767cfc91a0ccfa360a5b247dde2/Granite%204.0%20Prompt%20engineering%20guide%20v2.md).
Other publishers' generic benchmark comparisons are not qualification evidence.

## Runtime and authority

Keep the exact pinned llama.cpp b11379 libraries, ABI and greedy sampler. Use
Granite's explicit system/user/assistant role delimiters, without thinking,
tools, RAG injection, auxiliary models or an external service. Source control-token
prefixes are refused before native framing, including after decoding the host
JSON envelope; escaped document bytes cannot create an additional role.

The locked runtime supports Granite's dense configuration. Although upstream
configuration names its shared hybrid model class, this variant has no recurrent
layers. The pinned native recurrent-memory implementation permits suffix removal
when its layer filter is empty; the existing checked prefix-reuse invariant is
retained. Actual loading, reuse, isolation and all resource limits still require
native evidence; source inspection does not constitute an execution result.

Keep all three failed Qwen artifact/license pins as RETIRED and readable/removable;
refuse installation, activation and rollback into them. The changed registry,
model and framing identities require fresh technical evidence and explicit
consent, with no automatic download, switch, removal or fallback. Developer
qualification uses the neutral `model.gguf` cache filename; weights are never
committed or uploaded as CI artifacts.

## Unchanged acceptance

ADR 0033, S05/S08 corpora, gold selections, all 26 gates, CPU/context/memory/input/
output limits, cancellation, Capture/search bounds and twenty-minute workflow
limit remain byte-identical or numerically unchanged as applicable. Every case
runs once on each native host; retain every failure. Neither a publisher's
language claim nor local synthetic/browser success can promote this candidate.
Normal exact-head and actual-main acceptance must precede S09 activation.
