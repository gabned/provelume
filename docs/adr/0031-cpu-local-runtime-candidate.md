# ADR 0031: one CPU runtime candidate for Custodia S05

Status: candidate selected; technical qualification pending; Recommended promotion
requires S09. Parent #311, slice #320. Decision and thresholds fixed before any
candidate inference or scoring on 2026-10-03. Failures do not change these thresholds.

## Choice and provenance

Use **llama.cpp b11379**, source commit
`1537a0a8b2f8711d840878b0a0677ab2213c882c`, MIT, with the official CPU-only
Windows x64 and Ubuntu x64 distributions. Use only the shared inference libraries,
in a disposable Python worker; no server, HTTP endpoint, tool calling or executable
model code. Runtime code is an application build input, never a registry update.

One model: **Qwen/Qwen2.5-1.5B-Instruct-GGUF**, official upstream revision
`91cad51170dc346986eccefdc2dd33a9da36ead9`, GGUF v3, Q4_K_M,
`qwen2.5-1.5b-instruct-q4_k_m.gguf`, 1,117,320,736 bytes, SHA-256
`6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`.
The model is Apache-2.0; retain its full license and attribution on redistribution.
MIT runtime notices must accompany native libraries. No account or acceptance portal
is needed. The registry pins reviewed application metadata, not companion checksums.
The upstream immutable repository and release API independently supply identities;
byte hashes establish integrity, not independent publisher authentication.

Sources consulted before acquisition:

- [Official model card and files](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/tree/91cad51170dc346986eccefdc2dd33a9da36ead9).
- [Model license](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/blob/91cad51170dc346986eccefdc2dd33a9da36ead9/LICENSE).
- [Official runtime release](https://github.com/ggml-org/llama.cpp/releases/tag/b11379)
  and [MIT license](https://github.com/ggml-org/llama.cpp/blob/1537a0a8b2f8711d840878b0a0677ab2213c882c/LICENSE).

Windows archive: 19,352,297 bytes, SHA-256
`ec014c2c2a27b18786d24eba3e8650d4e68b9003ca6cf91714125b71975eb7ea`.
Linux archive: 17,658,949 bytes, SHA-256
`8ab0e8588e2b282ed4882a47a26dbf1a2ae920578deb24a8dfe390110c1bb924`.
The application lock records individual library/license digests before measurements.
The GGUF includes vocabulary/tokenizer metadata; no external tokenizer is fetched.

This is a bounded evaluation of #224's small-model direction, not evidence that
parameter count establishes quality. The official quantization and small native
CPU distribution avoid a second tensor runtime, Python ML dependency tree or GPU.
ONNX is not implemented. EN/IT adequacy is decided by the corpus below, not upstream
general benchmarks. A failed candidate remains failed; no automatic model sweep.

## Reference profiles and fixed configuration

Targets: native Ubuntu 24.04 x86-64 and Windows 11 / Server 2025 x64, CPython 3.12,
at least four logical CPU cores with AVX2, 8 GiB installed RAM, 4 GiB currently
available, and 5 GiB free local disk for bounded acquisition/staging. Two inference
threads, one process, one sequence, 2048-token context, at most 1536 input tokens,
4096 UTF-8 input bytes and 128 output tokens / 4096 output bytes; greedy decoding.
No GPU layers. Idle unload after five seconds. One active operation; no waiting
queue. Maximum load/generation operation 60 seconds; cancellation/termination two
seconds. Runtime limits are distinct from the future S06 job/budget engine.

Linux address-space hard ceiling 3 GiB; Windows Job committed-memory hard ceiling
3 GiB. These are different OS resources; record RSS/private working set separately.
CPU affinity restricts the worker to two available logical CPUs; thread count is
a runtime setting, not a hard count of OS housekeeping threads. Unsupported OS,
architecture, insufficient resources or failed OS containment fails closed.

## Thresholds frozen before evaluation

Every mandatory dimension must pass on each claimed profile:

| Dimension | PASS threshold |
| --- | --- |
| EN and IT bounded factual answers / key facts | >=90% exact expected facts per language, no unsupported fact in any accepted answer |
| Missing fact / abstention | 100% expected UNKNOWN on missing-fact cases per language |
| Cold model load | maximum <=15 s |
| Cold first output / whole 128-token result | maximum <=20 s / <=60 s |
| Warm first output / whole result | maximum <=5 s / <=30 s |
| Peak worker RSS | <=2 GiB |
| After unload | zero worker processes; parent RSS increase <=64 MiB from pre-load baseline |
| Cancellation during load and generation | <=2 s until worker/descendants absent, next explicit caller succeeds |
| Idle unload | <=7 s from last result, no live worker/descendants |
| Capture/search under inference | each <=1 s and <=2x matched idle median +100 ms; exact Original/search result preserved |
| Network | no successful runtime egress in load, generation, idle, error, shutdown, with OS-appropriate control and observation |
| Absence/tampering/unsupported configuration | closed failure; no implicit acquisition/retry/cloud; deterministic flows remain available |

## Measurement protocol and scope

Use only committed synthetic EN/IT fixtures: ten questions per language including
two missing-fact cases. No product synthesis feature is introduced. Greedy output
is scored against explicit facts/abstention; retain public synthetic outputs with
scores. Three fresh-worker cold runs (OS file cache is not flushed and must be
reported), three warm runs per case in the same loaded worker, plus load/generation
cancellation and unload. Report every sample, maxima and medians; no dropped outlier.
Measure monotonic wall time, first token, OS peak/current memory and child liveness.
Measure existing deterministic capture/search on identical synthetic inputs both
idle and concurrently. Record OS/build, CPU, RAM, affinity, runtime/library/model/
configuration digests and exact source commit.

Separate synthetic contract tests, real execution, semantic quality, hardware
profile and offline/no-egress results. A strong CI runner qualifies only its
observed profile; it does not qualify an 8 GiB laptop by extrapolation. Unsupported
or unavailable observation is NOT_RUN; failed thresholds are FAIL; either prevents
S05 qualification and Recommended claims. Successful offline inference alone is not
complete no-egress proof. Do not disable security controls on the user's PC.

Acquisition is explicit and bounded (one model plus two small platform runtime
archives), outside Git and portable Instance storage. Installation, self-test and
internal activation never open product dispatch; S06 remains required. S09 alone
can promote an integrated task/language/hardware profile to Recommended.
