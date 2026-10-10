# 0045 — Higher-capacity Granite instruction candidate

Status: selected before native scoring, 2026-10-09. Maintainer-authorized S08
profile revision, PR #333 / issue #332, for 0.12 Custodia. Not qualification,
Recommended promotion or publication.

## Evidence and decision

Increasing Granite-4.0-1B precision to Q8_0 did not establish useful selection.
Linux completed 32 valid outputs but only 19 gold selections and five of eight
required abstentions, failing five semantic/abstention gates. Windows reached
the unchanged 20-minute timeout: its partial report retains 20 S08 cases and
already fails inherited latency and S08 cold-first timing. Its missing final
cases, network observation and integrity remain incomplete. All eighteen
preceding candidates and their failed/partial observations remain retained.

Select one larger instruction-model candidate: the official IBM
**Granite-3.3-2B-Instruct Q4_K_M** distribution. The publisher explicitly lists
English and Italian, extraction, classification and summarization. Its dense
Granite architecture uses 40 attention layers and a 49,159-token vocabulary;
the GGUF metadata declares 2,533,539,840 parameters. Its custom-system template
uses the existing Granite role delimiters, without injecting the optional
thinking instruction. These are compatibility facts, not task-quality evidence.
Keep the complete v7 canonical task, four fixed trusted dialogue examples,
grammar, discarded assessment and lossless index mapping byte-for-byte.

Immutable artifact:

- Repository: `ibm-granite/granite-3.3-2b-instruct-GGUF`.
- Revision: `7cdf86ccd1f1bb3491c9b7017b033f2e51367397`.
- File: `granite-3.3-2b-instruct-Q4_K_M.gguf`.
- Exact size: **1,545,303,328 bytes**.
- SHA-256: `ac71e9e32c0bea919b409c5918f69ca74339854b0319c5065e4e9fb6d95c4852`.

The public repository history names IBM/gguf's
`granite-3.3-release-preview-ibm-granite.yml` workflow at
`preview-v3.3-rc.0`, run 14406385444, for its April 11, 2025 conversion.
The April 16 model card links the public instruct model. This decision pins
the actual official converted bytes; it does not claim a reproduced conversion
or silently equate that preview history with a later source-weight revision.
Publisher benchmarks cannot substitute for this artifact's native qualification.

Both immutable cards declare Apache-2.0. The instruct card at
`707f574c62054322f6b5b04b6d075f0a8f05e0f0` links the publisher's
`ibm-granite/granite-3.3-language-models` repository. Its complete LICENSE at
`cdb168187905dd4d6965d4070551dfeb8887bb36` is byte-identical to the retained
`granite-LICENSE.txt`: 11,357 bytes, SHA-256
`c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`.
Keep attribution and the complete terms in both notice inventories.

## Unchanged boundaries

The file ceiling changes to the exact artifact size. Keep the same llama.cpp
b11379 libraries, two CPU threads, 2 GiB peak-RSS gate, 3 GiB hard boundary,
context/input/output limits, cold/warm timing, cancellation and 20-minute
workflow timeout. A smaller file than Q8_0 does not qualify either memory or
latency for the larger network. No model sweep, semantic post-filter, repair,
retry, second inference, source-dependent grammar or corpus oracle is added.

Retain both Granite-4 artifacts and all three Qwen artifacts as RETIRED with
their original pins/licenses and explicit removal. No automatic download,
migration, deletion, fallback, activation or executable-code acquisition.
Earlier model/configuration/self-test/consent cannot authorize this identity.
Weights stay outside source, wheels and CI artifacts.

An independent pre-consent correction validates the complete local native
frame, including quotation expansion and trusted dialogue, during preparation.
Unsupported role delimiters and oversized frames are refused before a preview
can be approved, without probing model files, network or credentials. Fitting
source remains unchanged, and the external-only contract keeps its own bounds.
This does not change the frozen corpus, prompts, inference or scoring.

Preserve ADR 0033, both corpora, gold references and every numeric gate. Both
native hosts must independently pass all 26 gates with complete evidence.
S08 actual-main acceptance precedes S09 activation. Final 0.12 artifact
qualification and publication remain separate; v0.11.0 remains immutable.

## Primary sources

- [Official immutable GGUF pointer](https://huggingface.co/ibm-granite/granite-3.3-2b-instruct-GGUF/raw/7cdf86ccd1f1bb3491c9b7017b033f2e51367397/granite-3.3-2b-instruct-Q4_K_M.gguf).
- [Official immutable conversion card](https://huggingface.co/ibm-granite/granite-3.3-2b-instruct-GGUF/blob/7cdf86ccd1f1bb3491c9b7017b033f2e51367397/README.md).
- [Official immutable instruct card](https://huggingface.co/ibm-granite/granite-3.3-2b-instruct/blob/707f574c62054322f6b5b04b6d075f0a8f05e0f0/README.md).
- [Publisher license](https://github.com/ibm-granite/granite-3.3-language-models/blob/cdb168187905dd4d6965d4070551dfeb8887bb36/LICENSE).
- [Named publisher conversion workflow](https://github.com/IBM/gguf/blob/preview-v3.3-rc.0/.github/workflows/granite-3.3-release-preview-ibm-granite.yml).
