# Custodia local recommendation

The recommendation covers one exact local profile for **extractive summary and
key points in English and Italian**. It is a distribution decision after S08/S09
qualification, not a grant of inference authority, a language-general quality
claim or proof that an unmeasured computer meets the observed timings.

S08 was accepted at `8b2403a091f927debd3718ba3ae0ea90ece657ee`.
S09 integration and actual-main evidence: [the S09 integration ledger](https://github.com/gabned/provelume/pull/336).
The [S09 candidate ledger](https://github.com/gabned/provelume/pull/336#issuecomment-6099065777)
retains the original failures, exact artifacts and historical 8329330 results.
The later 57544c4 native Linux capture-latency failures and Windows CI attempts
remain separate observations; subsequent acceptance requires a complete new result.
The release-preparation owner is #337; its exact-head and actual-main
checks must qualify the changed application identity before official publication.

| Coordinate | Promoted scope |
| --- | --- |
| Model | Qwen3.5-2B, Unsloth Q5_K_M GGUF, 1,435,238,656 bytes |
| Model SHA-256 | `1885b3a9195f8cc09da9a7a7a75afdc1e8d5cbf9fc4a499c3961dddea37098ac` |
| Runtime | llama.cpp b11379; Windows/Linux x86-64 AVX2 |
| Runtime lock SHA-256 | `0e508965cddc60d6cfb57c42d2c4039c637e8812bb25cc21b525b6d6047a4404` |
| Execution configuration SHA-256 | `51c7539e89a4a29c6bc3ad04fb7b1e2b1cf8afdf33ed2f23261a47c6ccc56640` |
| Task | `extractive-source-reporting-v11`; exact source excerpts and references |
| Language/task quality | EN/IT × summary/key points; 32 public cases, eight required abstentions |
| Evaluated hardware | Recorded hosted Windows/Linux CPU profiles; 4 logical CPUs, approximately 16 GiB host RAM; non-root container with 12 GiB limit |
| Native limits | 2 selected physical CPU cores; 2 GiB observed peak-RSS cap, 3 GiB hard limit; 5 s warm first response; 2 s cancellation |
| Local admission | AVX2 x86-64, 4 logical CPUs, 8 GiB total and 4 GiB available RAM; compatibility admission is not a performance certification of an 8 GiB laptop |
| Outside the recommendation | Other tasks/languages, autonomous filing, arbitrary BYOM, GPU, macOS/ARM and unmeasured hardware performance |

`qualified_local_profile()` matches the independently frozen model, runtime-lock
and execution-configuration hashes. A changed coordinate removes the recommendation;
the shipped registry cannot silently promote a new configuration. Synthetic entries
remain `SYNTHETIC_ONLY`; six retired models remain blocked and explicitly removable.
The registry's `recommended_scope` records the bounded tasks/languages and evidence.

Model installation, current-file verification, per-device compatibility, OS isolation,
session enablement, preview, document consent and durable job authority remain separate.
The inventory keeps `offline_qualified` and `inference_authorized` false for an
unobserved installation. Importing recommendation metadata acquires nothing and does
not start a worker. AI remains off initially and after restart; uncertain work is
never automatically replayed. A version upgrade invalidates old runtime-selection
fingerprints while retaining identical verified model bytes for fresh explicit checks.

Windows containment is exercised through the ordinary installed AppContainer/Job
path. Linux native seccomp and parent-lifetime checks, plus the non-root read-only
offline container, have separate recorded observations. A compatibility self-test
does not replace the quality corpus or establish qualification of a remote provider.
Specific live external providers remain unqualified.

The maintainer explicitly requested proceeding without Narrator on 2026-10-10;
[the original instruction is recorded](https://github.com/gabned/provelume/pull/336#issuecomment-6099628733).
Screen-reader evidence remains **NOT_RUN** and newly unreviewed human linguistic,
contrast/DPI observations remain **UNVERIFIED**. Automated catalog/browser checks
are recorded separately. Earlier S07 or Cura human attestations are not extended.
