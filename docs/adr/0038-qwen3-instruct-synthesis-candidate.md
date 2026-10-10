# 0038 — Instruction-tuned four-billion-parameter synthesis candidate

Status: selected before native scoring, 2026-10-09. The maintainer-authorized AI
profile revision remains in S08 PR #333 / issue #332 for 0.12 Custodia. This is
neither Recommended promotion nor application publication.

## Evidence and selection

Eleven retained candidates failed the frozen synthesis qualification. The latest
Qwen3-1.7B Q4_K_M candidate produced 32 valid responses and all eight required
abstentions on each host, but only 18 correct selections. Every task/language
semantic gate failed: it repeatedly selected editorial or adversarial text beside
useful content. Four fixed bilingual examples did not resolve that limitation.

Select one replacement: **Qwen3-4B-Instruct-2507**, in bartowski's Q2_K GGUF
conversion. Upstream reports IFEval 83.4 for the unquantized instruction model;
this motivates evaluation but proves nothing about this quantization or task.
The 1,669,499,616-byte artifact leaves approximately 456 MiB below the unchanged
2 GiB peak-RSS gate for the context, compute buffers and worker. Whether this
margin and the two-CPU latency limits are sufficient must be measured, not
inferred. Larger Q4 weights alone exceed the RSS gate. No automatic model sweep.

Exact source: `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF`, revision
`ac104788567ef76beaf5f30b6cccb1f99a69afbe`, file
`Qwen_Qwen3-4B-Instruct-2507-Q2_K.gguf`, SHA-256
`7f9efe8a86c1d200139801642dcf8c0d9f2cf09c89ef4e8f0ea525536368c4ca`.
The publisher's immutable upload commit records the LFS size and digest. This is
a third-party quantization of Qwen's model, not an official Qwen GGUF release.
The complete Apache-2.0 license with upstream's Copyright 2024 Alibaba Cloud is
already retained as `runtime_notices/qwen-LICENSE.txt`; Qwen3-1.7B's distinct
2025 attribution remains in its separate retained license.

## Runtime and unchanged evaluation

Use the same llama.cpp b11379 binaries, greedy sampler, one inference, exact
KEEP/DROP grammar and ADR 0037 editorial instructions/examples. The instruction
model's official chat template ends at the assistant header, without a thinking
block. Bind the new template and model identities to runtime/consent evidence.
No context, output, CPU, RAM, deadline, workflow timeout or admission increase.
The raw artifact/file-size pin changes to the exact selected bytes; it is not
an increase to the accepted runtime memory or performance thresholds.

Keep both earlier model entries as RETIRED, with their original immutable
identity and license. Existing selections remain readable and explicitly
removable. Installation, self-test, activation, rollback and inference refuse
retired models; no automatic download, migration, deletion or fallback occurs.
Both reviewed GGUF formats use the same bounded streaming and verification path.

Retain every case, gold reference, sample and failed attempt in ADR 0033's frozen
32-case corpus and all 26 S05–S08 gates. Run the unchanged inherited corpus too.
The complete native Windows/Linux result decides acceptance; missing or failed
evidence blocks S08 acceptance and subsequent S09 activation. No performance or
quality claim extends to hardware, languages or providers not actually measured.

## Primary sources

- [Official model and instruction-following evaluation](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507).
- [Official chat template](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/tokenizer_config.json).
- [Official license](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/LICENSE).
- [Quantization publisher and CPU tradeoffs](https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF).
- [Immutable upload commit and LFS pointer](https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/commit/ac104788567ef76beaf5f30b6cccb1f99a69afbe).

Final 0.12 version alignment, artifact qualification and release publication
remain the separate release owner's work after accepted S01–S09 actual main.
