# Third-party notices

Provelume's public license does not replace the licenses of third-party dependencies.

Custodia 0.12 includes the reviewed optional native runtime libraries, with model
weights acquired separately. They were absent from the published 0.11.0 preview.
The local recommendation is limited to the documented EN/IT extractive profile.
llama.cpp b11379,
commit `1537a0a8b2f8711d840878b0a0677ab2213c882c`, is MIT. The selected Windows
distribution's LLVM OpenMP library is Apache-2.0 WITH LLVM-exception. Full upstream
texts are retained under `core/provelume/runtime_notices/` and accompany the
deterministic native build input. Qwen/Qwen2.5-1.5B-Instruct-GGUF revision
`91cad51170dc346986eccefdc2dd33a9da36ead9` is Apache-2.0; its full license is retained
there as `qwen-LICENSE.txt`. Weights are acquired explicitly, not shipped in wheels.
The retired Qwen3-1.7B candidate is Qwen/Qwen3-1.7B-GGUF, revision
`7fb011e9aee6e4dc7adf8430df9ea8de6a466aa3`, Apache-2.0, Copyright 2025 Alibaba Cloud.
Its complete license is retained as `qwen3-LICENSE.txt` with normalized LF line
endings. [ADR 0035](docs/adr/0035-qwen3-synthesis-candidate.md) pins the selected
quantization, origin and digest. [ADR 0039](docs/adr/0039-bounded-selection-assessment.md)
re-evaluated these same bytes under a bounded selection profile, which also failed
semantic qualification. The retired Qwen3-4B-Instruct-2507 is in
bartowski's Q2_K conversion, revision `ac104788567ef76beaf5f30b6cccb1f99a69afbe`.
This third-party quantization uses Apache-2.0, Copyright 2024 Alibaba Cloud;
the complete terms are retained in `qwen-LICENSE.txt`.
[ADR 0038](docs/adr/0038-qwen3-instruct-synthesis-candidate.md) pins its identity
before scoring. It failed latency qualification; its metadata remains RETIRED.
The earlier S08 candidates include IBM's official Granite-4.0-1B conversions,
`ibm-granite/granite-4.0-1b-GGUF` revision
`b27c2fe3f211b7f44e80fa620177aea371099aaa`, Apache-2.0. The complete unchanged
publisher license is retained as `granite-LICENSE.txt`; its immutable source and
digest, model identity and qualification conditions are recorded in
[ADR 0040](docs/adr/0040-granite-document-synthesis-candidate.md) and
[ADR 0044](docs/adr/0044-higher-precision-synthesis-candidate.md). Both
Q5_K_M and Q8_0 remain RETIRED with their identities and licenses retained.
The retired Granite-3.3-2B-Instruct Q4_K_M candidate is IBM's official artifact,
`ibm-granite/granite-3.3-2b-instruct-GGUF` revision
`7cdf86ccd1f1bb3491c9b7017b033f2e51367397`, also Apache-2.0. Its publisher's
complete license is byte-identical to `granite-LICENSE.txt`.
[ADR 0045](docs/adr/0045-granite33-capacity-candidate.md) records its immutable
artifact, license source and the official conversion's preview-workflow history.
Both native hosts reached the workflow timeout with incomplete S08 evidence.
[ADR 0046](docs/adr/0046-canonical-task-qwen25-requalification.md) requalifies the
original Qwen2.5 artifact with the current canonical task and fixed dialogue
examples. Its earlier S08 failures remain failures; no old activation or
qualification is inherited. Publisher language support, model size and
quantization precision do not establish Provelume task quality. Its new measurement
also failed; Qwen2.5 is now RETIRED with its original license retained.
[ADR 0047](docs/adr/0047-hybrid-cpu-synthesis-candidate.md) selects Qwen3.5-2B,
upstream revision `15852e8c16360a2fea060d615a32b45270f8a8fc`, Apache-2.0,
Copyright 2026 Alibaba Cloud, in the reviewed Unsloth Q5_K_M conversion
`unsloth/Qwen3.5-2B-GGUF` revision `f6d5376be1edb4d416d56da11e5397a961aca8ae`.
This is a third-party conversion, not an official Qwen GGUF. The complete upstream
license is retained byte-for-byte as `qwen35-LICENSE.txt` (including CRLF),
11,544 bytes, SHA-256 `bbedc3fda3305820b977265f01b8619d87570a6739de3a5582c3464840f1e57a`.
The immutable model SHA-256 is
`1885b3a9195f8cc09da9a7a7a75afdc1e8d5cbf9fc4a499c3961dddea37098ac`.
Neither the publisher's benchmarks nor this notice constitutes product acceptance.
The [Custodia local profile](docs/qualification/custodia-local-profile.md) records
the exact bounded recommendation. No model weights are bundled in the wheel.
See [ADR 0031](docs/adr/0031-cpu-local-runtime-candidate.md) for immutable origins,
digests, quantization and redistribution conditions. The native input's SBOM
lists each shipped native library and exact hash; host Python/C runtimes remain
host prerequisites rather than newly redistributed components.

Direct runtime dependencies in the current Python package include:

| Component | Purpose | License |
| --- | --- | --- |
| FastAPI | Knowledge API and web routing | MIT |
| Jinja2 | server-side Knowledge Browser templates | BSD-3-Clause |
| pypdf | local PDF text extraction | BSD-3-Clause |
| PyYAML | Instance configuration | MIT |
| Uvicorn | local ASGI server | BSD-3-Clause |
| qrcode 8.2 | local single-use pairing QR encoding | BSD-3-Clause AND inherited MIT notice |

Capture uses qrcode's pure SVG encoder; it does not bundle an image decoder or invoke
an external QR service. The complete unchanged upstream license, including Lincoln
Loop (2011) and Kazuhiko Arase (2009) notices, is packaged at
`provelume/notices/qrcode-LICENSE.txt`. Pillow remains an explicitly installed external
component for the optional Capture PNG/JPEG decoder; its existing notices below apply.

Release-build tooling includes:

| Component | Purpose | License |
| --- | --- | --- |
| build | Python wheel/source distribution build frontend | MIT |
| Hatchling | pinned Python build backend and reproducible archive support | MIT |
| CycloneDX Python (`cyclonedx-bom`) | release SBOM generation | Apache-2.0 |
| GitHub Actions checkout/setup/upload/attest actions | public CI and release automation | licenses published by their respective repositories |

These components have their own copyright notices and license terms. Transitive dependencies retain their own terms as well. Published release SBOMs are the machine-readable dependency inventory for the built Python environment; this file is a human-readable summary, not a substitute for that SBOM.

## Cura UI icons — vendored Lucide subset in 0.11/S02

Provelume includes 23 unchanged SVG sources from [Lucide 1.45.0](https://github.com/lucide-icons/lucide/releases/tag/1.45.0),
commit `b998e2892b90b88004d62da2d0b64dab9959a520`, for decorative icons beside visible
navigation and status labels. Lucide's ISC license and the applicable MIT notices for its
Feather-derived icons are both retained: the aggregate subset is **ISC AND MIT**, not MIT-only
and not a choice between ISC and MIT. Copyright holders are Lucide Icons and Contributors
(2026) and Cole Bemis (2013-present, Feather-derived list).

The complete, unchanged upstream [LICENSE](core/provelume/notices/lucide-LICENSE.txt),
including both permission/disclaimer blocks and the Feather icon list, is packaged at
`provelume/notices/lucide-LICENSE.txt`. Its SHA-256 is
`b495047bd93a9b06913511076f504daba17d5bbeb3e0650f3bb53a4220329c57`.
The [subset manifest](core/provelume/static/icons/lucide/subset.json) records every
source byte identity and upstream reference. `triangle-alert` retains its upstream
`alert-triangle` alias reference for the Feather-list attribution. No exhaustive individual
copyright history is inferred from icon names or geometry.

The installed component catalogue and release SBOM consume that same verified manifest.
Updates require a reviewed Provelume source/release change with license, hash and artifact
verification. No icon framework, npm runtime, CDN or runtime network service is required.
Provelume's own license does not replace these third-party terms. See [ADR 0028](docs/adr/0028-cura-icons-and-provenance.md).

## Qualified optional OCR baseline — external in 0.9/S02

The `0.9/S02` implementation can execute the Tesseract CLI through a replaceable local process
adapter and uses PDFium/Pillow through a separate renderer/decoder process. It adds adapter code,
not native payloads: the base wheel, source distribution and Windows installer still contain no OCR
engine, language model, PDF renderer, image decoder or optional Python wheel. These components are
installed and configured separately by the operator and are **not bundled by Provelume**:

| Component | Intended purpose | License | S02 distribution |
| --- | --- | --- | --- |
| Tesseract 5.5.3 | local printed-text OCR engine | Apache-2.0 | not bundled |
| Leptonica | Tesseract image decoding and processing | BSD-2-Clause | not bundled |
| `tessdata_fast` language packs | explicit local OCR language data | Apache-2.0 | not bundled |
| pypdfium2 5.13.0 | Python binding and external-wheel delivery of PDFium | Apache-2.0 OR BSD-3-Clause, plus dependency licenses | not bundled |
| PDFium 153.0.7999.0 | PDF rasterization in the qualified Linux wheel | BSD-3-Clause and dependency licenses | not bundled |
| Pillow 12.3.0 | TIFF, PNG, JPEG and BMP decode/render boundary | MIT-CMU and applicable wheel dependency terms | not bundled |

The qualified Ubuntu x86_64 CI job provisions the two Python wheels by exact version and SHA-256,
records the distribution-provided Tesseract, Leptonica and `eng` pack identities, then runs with no
runtime installer or fallback. The pypdfium2 wheel carries `LICENSES` and platform-specific
`BUILD_LICENSES` for PDFium and its native dependencies; those files remain authoritative for that
external wheel. [`packaging/ocr/qualified-local-components.cdx.json`](packaging/ocr/qualified-local-components.cdx.json)
is a machine-readable inventory of the qualified external path, not the SBOM of a Provelume release
artifact.

Before Provelume redistributes any of these components, the release must carry every applicable
license and attribution, enumerate every binary, codec and language pack in the release manifest
and release CycloneDX SBOM, publish exact checksums, and prove an offline installation with
networking denied. The S02 Windows model therefore remains explicit external local installation;
there is no offline installer component yet. Provelume's public or commercial license does not
replace any third-party term.

## Qualified local email baseline — runtime standard library in 0.9/S03

The `0.9/S03` EML and Maildir baseline adds no Python dependency, native parser, provider SDK,
language pack or remote service. MIME parsing uses the `email` package supplied by the qualified
CPython 3.12 runtime, under the Python Software Foundation License, behind a replaceable Provelume
parser interface. Exact message bytes are read by Provelume's bounded local adapters before parsing;
the Python `mailbox` package was evaluated but is not used for message reading or delimitation.

The wheel and source distribution do not copy the CPython standard library. The Windows frozen
application continues to carry its existing Python runtime; S03 adds no separate email component or
payload. [`packaging/email/qualified-local-components.cdx.json`](packaging/email/qualified-local-components.cdx.json)
is the machine-readable inventory for this development qualification, not the SBOM of a published
Provelume release. No `0.9.0` release artifact is created by S03.

## Local transcript profiles — first-party parser in 0.9/S05

The `0.9/S05` SRT and WebVTT baseline adds no Python dependency, native parser,
provider SDK, media codec, model or remote service. Parsing is implemented by
first-party bounded code behind a replaceable provider-neutral contract and uses only
the CPython 3.12 standard library, under the Python Software Foundation License.
The wheel and source distribution contain no transcript payload or private fixture.

[`packaging/transcript/qualified-local-components.cdx.json`](packaging/transcript/qualified-local-components.cdx.json)
records the runtime-provided standard-library boundary for permanent synthetic local
conformance. It is not the aggregate release SBOM and makes no cloud-provider, audio,
video, speech-to-text or real-data qualification claim. S05 itself created no release artifact;
the baseline is included in the later `0.9.0` release boundary.

## Qualified optional local audio baseline — external in 0.10/S04

The `0.10/S04` profile can invoke one explicitly configured local path: `whisper.cpp` 1.9.2 at
source commit `306c88f4d1286aec1bf96e544632897886af5501` with the multilingual Whisper tiny `q5_1`
GGML model. Both are licensed under MIT terms and remain **not bundled by Provelume**. The operator
supplies absolute paths and exact binary/model identity; the installer and runtime never discover,
download, update or remotely replace either component.

[`packaging/audio/qualified-local-components.cdx.json`](packaging/audio/qualified-local-components.cdx.json)
records this qualified optional path and its model checksum. It is not the aggregate release SBOM.
The Python wheel, source distribution and Windows installer include only Provelume's bounded
adapter, schema and manifest; they contain no speech engine, model, codec or private audio fixture.

## Qualified optional local video baseline — external in 0.10/S05

The `0.10/S05` profile can invoke one explicitly configured FFmpeg/ffprobe 9.0.1 pair built from
the official source archive. The pair is governed by FFmpeg's LGPL 2.1-or-later baseline when built
without optional GPL or nonfree components and remains **not bundled by Provelume**. The operator
supplies absolute paths, the declared version and exact hashes for both binaries; Provelume never
discovers, downloads, updates or remotely replaces them.

[`packaging/video/qualified-local-components.cdx.json`](packaging/video/qualified-local-components.cdx.json)
records the qualified optional Ubuntu path and source checksum. It is not the aggregate release
SBOM. The Python wheel, source distribution and Windows installer contain no FFmpeg binary, codec,
model, media payload or private fixture. Any future redistribution must inventory the exact build
configuration and all applicable component licenses first.
