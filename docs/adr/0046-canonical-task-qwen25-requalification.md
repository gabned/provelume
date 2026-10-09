# 0046 — Requalify the lightweight Qwen2.5 artifact with the canonical task

Status: selected before scoring, 2026-10-09. Maintainer-authorized profile revision
for 0.12/S08, sole PR #333 / issue #332. Not acceptance or Recommended promotion.

## Evidence and decision

Candidate19's larger dense Granite-3.3 network reached the unchanged 20-minute
workflow timeout on both native hosts. Its partial S08 cold-first results were
22.297 seconds on Windows and 26.675 on Linux, above 20 seconds. The complete
English summary groups selected six of eight gold results on each host; remaining
Italian cases and final integrity/network evidence were not measured. Increasing
capacity did not establish an acceptable CPU-first profile. Keep that incomplete
evidence and every earlier failure.

The original Qwen2.5 artifact was last scored in candidate8 with the v1 index-list
grammar, without explicit paragraph decisions, bounded assessment or fixed trusted
dialogue demonstrations. It produced valid outputs and required abstentions, but
failed semantic quality. Those failures remain failures. Later task changes were
measured with other artifacts; they do not establish this combination's quality.

Select the existing official **Qwen2.5-1.5B-Instruct Q4_K_M** bytes from ADR 0031
for a new qualification with the complete canonical v7 selection rules, four fixed
trusted examples, bounded discarded assessment and KEEP/DROP grammar. Preserve
those semantic instructions, examples and every legal subset byte-for-byte.
Use the artifact's original ChatML roles: `<|im_start|>role`, newline, content,
`<|im_end|>`; the final assistant prefix contains no thinking-mode instruction.
Source remains only in the final quoted user turn. Continue refusing every `<|`
delimiter in source, including obsolete model delimiters.

Immutable artifact, unchanged from ADR 0031:

- Repository: `Qwen/Qwen2.5-1.5B-Instruct-GGUF`.
- Revision: `91cad51170dc346986eccefdc2dd33a9da36ead9`.
- File: `qwen2.5-1.5b-instruct-q4_k_m.gguf`.
- Size: **1,117,320,736 bytes**.
- SHA-256: `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`.
- Apache-2.0, complete retained `qwen-LICENSE.txt`, 11,343 bytes, SHA-256
  `832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e`.

The model entry is a new unqualified candidate under this ADR. Its old installed
bytes or historical S05 status cannot authorize the new runtime/template identity;
fresh explicit self-test, activation and consent remain mandatory. This is neither
a rerun of candidate8 nor automatic fallback. Both Qwen3 and all three Granite
artifacts retain their original pins/licenses as RETIRED with explicit removal.
Registry and installed-package bounds remain eight; no metadata or weights are
silently deleted and no additional artifact is introduced.

## Unchanged acceptance

Keep llama.cpp b11379, all libraries and numeric quality, cold/warm latency, CPU,
memory, cancellation, context/input/output and workflow limits. The exact file-size
pin decreases to the chosen artifact; the 2 GiB RSS and 3 GiB hard memory bounds
do not change. No semantic filter, retry, repair, second inference, corpus oracle,
new acquisition origin, benchmark substitution or hidden previous-model rescue.

ADR 0033 and both corpora/gold remain frozen. Fresh complete Windows and Linux
measurements must each pass all 26 gates, alongside exact-head application/release
CI and reviews. S08 actual-main acceptance precedes S09. Human final-artifact and
live-provider observations remain separate. No version/tag/publication authority
or mutation of published v0.11.0 is added.
