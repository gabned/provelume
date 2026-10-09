# 0044 — Higher-precision Granite synthesis candidate

Status: selected before native scoring, 2026-10-09. Maintainer-authorized S08
profile revision in PR #333 / issue #332 for 0.12 Custodia. Not qualification,
Recommended promotion or publication.

## Evidence and decision

The Q5_K_M model has not qualified under any retained synthesis profile. The
canonical-task profile completed all 32 cases per platform, selecting 19 gold
results on Windows and 20 on Linux, with seven of eight required abstentions
on each. Both passed 21/26 gates and failed abstention plus all four semantic
gates. The Linux run finished unchanged and its full result is retained.
Earlier task-wording changes produced inconsistent semantic
results. Valid grammar, exact references and acceptable latency do not prove
faithful selection.

Select one higher-precision artifact of the same official IBM model and immutable
publisher revision: **Granite-4.0-1B Q8_0**. Keep the complete v7 canonical task,
four trusted demonstration pairs, role framing, grammar, assessment, lossless
mapping and greedy sampler byte-for-byte. This isolates artifact precision from
further prompt changes. Higher precision does not establish that quantization
caused an earlier error or that the new model will meet the semantic thresholds.

Immutable origin:
`ibm-granite/granite-4.0-1b-GGUF`, revision
`b27c2fe3f211b7f44e80fa620177aea371099aaa`, file
`granite-4.0-1b-Q8_0.gguf`. The publisher's raw LFS pointer declares
**1,737,791,232 bytes**, SHA-256
`0660c20c3d3d3672b90f0468f62dc128a82a6e3ee2ec05d310d242969be06140`.
Its complete Apache-2.0 publisher license remains in `granite-LICENSE.txt`, with
the same pinned bytes and attribution as ADR 0040. The artifact is acquired only
through explicit governed paths; no weights enter source, wheels or CI artifacts.

Keep Q5_K_M's original identity/license as RETIRED and explicitly removable,
together with the three retired Qwen entries. Earlier selection, activation and
consent do not authorize Q8_0. No automatic download, migration, deletion,
fallback, install-to-enable transition or executable-code acquisition is added.

## Unchanged acceptance

The raw-file pin and Linux sealed-snapshot file-size ceiling change to the exact
artifact length. The **2 GiB peak-RSS gate and 3 GiB hard memory boundary remain
unchanged**. The 409,692,416-byte difference between file size and the RSS gate
must cover actual context, runtime and worker overhead; file arithmetic is not
memory qualification. The same llama.cpp b11379 libraries, two CPU threads,
context/input/output bounds, cold/warm latency, cancellation, inherited gates
and 20-minute workflow cap all remain unchanged.

Keep ADR 0033, both frozen corpora, every gold reference and failed observation.
Both native hosts must independently pass all 26 gates with complete evidence;
no rerun, outlier removal, semantic filter or waiver. The independent navigation
correction in the same S08 candidate only moves blocking HTTP preparation and
discard into existing owned asynchronous work; it does not change model inputs,
outputs, scoring, execution authority or resource limits. Its regression tests
and browser evidence do not qualify semantic model quality.

S08 actual-main acceptance still precedes S09 activation. Final 0.12 release
identity, artifact qualification and publication remain separate work. Published
v0.11.0 remains immutable.

## Primary sources

- [Official immutable file and license metadata](https://huggingface.co/ibm-granite/granite-4.0-1b-GGUF/blob/b27c2fe3f211b7f44e80fa620177aea371099aaa/granite-4.0-1b-Q8_0.gguf).
- [Official immutable raw LFS size and SHA-256](https://huggingface.co/ibm-granite/granite-4.0-1b-GGUF/raw/b27c2fe3f211b7f44e80fa620177aea371099aaa/granite-4.0-1b-Q8_0.gguf).
