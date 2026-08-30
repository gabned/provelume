# ADR 0014 — Local OCR contract, licensing and optional packaging

- Status: accepted for `0.9/S01`
- Decision date: 2026-08-30
- Parent tracker: [#137](https://github.com/gabned/provelume/issues/137)
- Owner issue: [#5](https://github.com/gabned/provelume/issues/5)
- Published baseline: `0.8.0`

## Context

Lectio needs a replaceable OCR boundary before any document pipeline can execute it. The boundary
must preserve the exact Original, keep recognised text derived and reviewable, reuse Vigilia's
durable job lifecycle, fail safely on hostile inputs and remain useful with no network, cloud
provider or runtime model download. S01 must also settle the licensing and distribution posture
without pretending that OCR processing already exists.

The existing extractor can read text already embedded in a PDF, but it cannot turn a scanned page
into text. An OCR engine also does not make a PDF renderer safe: Tesseract accepts raster image
formats through Leptonica, while a scanned PDF first needs a separately bounded rasterisation step.
That renderer belongs to S02 and requires its own technical and licensing decision.

## Decision

Provelume selects the **Tesseract 5.5.3 command-line interface** as the first local engine baseline
behind a replaceable `OcrEngineAdapter`. S01 ships the adapter protocol, settings, capability and
result records, limits, provenance/idempotency helpers and schema, but deliberately ships **no
Tesseract invocation or complete OCR pipeline**.

The choice is grounded in these primary sources:

- [Tesseract source and Apache-2.0 license](https://github.com/tesseract-ocr/tesseract);
- [Tesseract 5.5.3 release](https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3),
  including an official x86-64 Windows asset;
- [upstream input-format documentation](https://tesseract-ocr.github.io/tessdoc/InputFormats.html),
  which identifies Leptonica and the codec-dependent PNG, JPEG, TIFF, JPEG 2000, GIF and WebP
  perimeter plus native BMP/PNM support;
- [upstream output documentation](https://tesseract-ocr.github.io/tessdoc/FAQ.html) and
  [API reference](https://tesseract-ocr.github.io/tessapi/5.x/a02438.html), which expose text,
  TSV/hOCR, coordinates and confidence;
- the exact
  [`tessdata_fast` source commit](https://github.com/tesseract-ocr/tessdata_fast/commit/87416418657359cb625c412a48b6e1d6d41c29bd),
  whose trained data are Apache-2.0 and intended for Tesseract 4/5.

The public Provelume input contract is narrower than every format Leptonica might decode. It
declares scanned PDF, TIFF, PNG, JPEG and BMP only. PDF pages must be rasterised by a future bounded
document adapter before the Tesseract page adapter sees them. WebP, GIF, JPEG 2000 and PNM require a
later explicit contract change and codec qualification.

## Capability and execution policy

The default configuration is:

```yaml
ocr:
  schema_version: 1
  mode: disabled
  engine: tesseract-cli
  languages: [eng]
  language_detection:
    mode: disabled
    candidates: []
```

The closed modes are:

| Mode | Meaning |
| --- | --- |
| `disabled` | Never probe or invoke an adapter or engine. No download or fallback occurs. |
| `automatic` | Schedule OCR only when the deterministic reliable-text threshold is not met. |
| `forced` | Schedule every otherwise valid page explicitly submitted to the future pipeline. |
| `selected-page` | Require a nonempty, unique, sorted and in-range 1-based page selection. |

Languages are explicit Tesseract pack identifiers. Optional `bounded` detection may choose only
among at most four already selected and installed candidates; it cannot discover, install or
download a language. The orientation/script `osd` pack is not selected by default.

Capability reporting is observational and closed:

- `disabled`;
- `adapter-unavailable`;
- `engine-unavailable`;
- `language-pack-missing`;
- `ready`.

Each unavailable state has stable English and Italian messages. An absent component never causes a
package install, model fetch, provider call or remote fallback. Missing-pack reports enumerate the
exact selected IDs that are absent.

The process seam accepts only a staged raster path in the private job directory plus a request
that binds page identity, media type, settings, languages, deadline and output-character limit.
It never receives a PDF directly. Results whose page, limits or engine/adapter provenance differ
from that request are contract violations.

## Original, derived records and uncertainty

Every page identity binds the Original SHA-256, canonical Version ID, 1-based page number, exact
raster SHA-256 and source media type. Provenance additionally binds:

- engine ID and exact version;
- adapter ID and exact version;
- sorted language-pack IDs;
- a canonical settings SHA-256.

The derivation key hashes that complete input. Replaying the same page with the same engine,
adapter and settings is idempotent; any material setting, version, language or page change produces
a new identity.

Page results are explicitly `machine-unverified` or `needs-review`; there is no `verified`
OCR status. Confidence is a bounded observation, never proof. Text spans may carry source-pixel
coordinates and confidence when the adapter supplies them. Layout, table, barcode and QR-code
observations live in four separate adapter-versioned collections and cannot be smuggled into the
text claim. The first Tesseract adapter is expected to expose text, TSV-derived coordinates and
confidence. Table, barcode and QR-code capability stays false unless a separately supported adapter
actually produces it; Tesseract's own
[FAQ states that it is not a barcode recogniser](https://tesseract-ocr.github.io/tessdoc/tess3/FAQ-Old.html).

OCR records live only in derived state. Removing them, rebuilding them or failing part way through
does not modify the Original or canonical knowledge.

## Resource and hostile-input boundary

S01 sets hard ceilings that configuration may lower but never raise:

| Limit | Ceiling |
| --- | ---: |
| input bytes | 256 MiB |
| pages | 200 |
| pixels on one page | 80,000,000 |
| total pixels | 500,000,000 |
| decoded bytes on one page | 320 MiB |
| decompression ratio | 100:1 |
| temporary bytes | 1 GiB |
| time per page | 60 seconds |
| time per job | 900 seconds |
| text characters per page | 500,000 |

Media type, extension and signature must agree before a decoder is selected. A future renderer must
measure page, pixel and decoded-byte evidence before engine invocation and must map corrupt,
oversized, unsupported, deadline and adapter failures to the closed error vocabulary. Each job
uses a private mode-0700 temporary directory under an explicit local root; the directory is removed
after success, cancellation or exception.

Committed page results advance a deterministic `ocr.page.committed` checkpoint. The checkpoint
sequence and processed/skipped/error counts fit Vigilia's journal without adding a scheduler job
kind in S01. S02 will register execution only after it can honor leases, heartbeat, cancellation,
retry and immutable terminal receipts.

## Alternatives evaluated

| Candidate | Primary-source facts | Decision |
| --- | --- | --- |
| Tesseract CLI 5.5.3 | Apache-2.0; Leptonica-based local raster input; explicit language packs; text/TSV/hOCR and confidence; official x86-64 Windows asset | selected as the first replaceable baseline |
| [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) | MPL-2.0 PDF orchestrator that uses Tesseract; its [current introduction](https://ocrmypdf.readthedocs.io/en/latest/introduction.html) requires Ghostscript under AGPL-3.0 | not the engine seam; PDF reconstruction and Ghostscript licensing need a separate decision |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Apache-2.0, broad OCR/layout features and model-source/download machinery; substantially larger ML runtime and model supply chain | allowed only as a future explicit adapter with pre-staged models and per-model provenance |
| [EasyOCR](https://github.com/JaidedAI/EasyOCR) | Apache-2.0 Python/PyTorch stack; its README states that selected language weights are automatically downloaded unless installed manually | allowed only as a future explicit adapter with downloads disabled and weights independently licensed/pinned |

No alternative is a silent fallback. Adapter selection is explicit and recorded in provenance.

## Licensing and compatibility

The selected, currently unbundled component set is:

| Component | License | Compatibility result |
| --- | --- | --- |
| Tesseract 5.5.3 | Apache-2.0 | permissive aggregation with Provelume when terms/notices are preserved |
| Leptonica | BSD-2-Clause, as identified by Tesseract upstream | permissive aggregation; retain copyright and license |
| `tessdata_fast` packs | Apache-2.0 | permissive aggregation; each exact pack remains a separately inventoried component |
| image codecs | component-specific | unresolved until a pinned build chooses them; redistribution is blocked meanwhile |

Provelume's PolyForm Noncommercial/public and separate commercial terms apply to Provelume code;
they neither relicense nor suppress third-party rights. Apache-2.0 and BSD-2-Clause do not impose a
copyleft source offer on Provelume, but their license/notice preservation duties remain. No
AGPL-licensed component is selected for the baseline.

Before redistribution, a build must copy the applicable Apache-2.0 and BSD-2-Clause texts and
attributions, preserve any upstream NOTICE material, enumerate engine, Leptonica, codecs and every
language pack in the release manifest and CycloneDX SBOM, publish exact digests and pass offline
installation verification. `THIRD_PARTY_NOTICES.md` records the selection without claiming those
components are already shipped.

## Platform and packaging model

No platform has a Provelume OCR execution qualification in S01:

- the base Python wheel and sdist remain platform-independent and gain no OCR dependency;
- the current Windows installer remains x86-64 and contains zero OCR engine or language-pack
  bytes;
- Windows ARM64 OCR remains unsupported;
- upstream source/distribution paths exist for Linux x86-64/aarch64 and macOS x86-64/arm64, but
  Provelume does not turn those upstream possibilities into a support claim.

A future Windows OCR component must be opt-in and unchecked by default. Its complete payload must
be staged in the reviewed installer or an offline companion bundle; runtime downloads and execution
of a nested upstream installer are forbidden. The component is capped at 256 MiB, each language
pack at 50 MiB, and the intended initial explicit pack set is `eng` plus `ita`; `osd` remains
an additional opt-in. The exact source build, libraries, license files, notices, manifest, SBOM and
digests are release gates.

The machine-readable decision is
[`packaging/ocr/tesseract-5.5.3.json`](../../packaging/ocr/tesseract-5.5.3.json).

## Consequences

- S02 gets a small stable adapter seam without being coupled to a Python wrapper or provider.
- The baseline is fully local and can be exercised in a process sandbox with networking denied.
- Missing engines or packs are visible and actionable instead of triggering downloads.
- PDF rasterisation, actual Tesseract process isolation, language-pack installation and full
  document-bundle integration remain explicit S02 work.
- More capable layout/table or ML adapters remain possible without changing what counts as
  canonical knowledge.
