# ADR 0015 — Bounded local OCR execution and document bundles

- Status: accepted for `0.9/S02`
- Decision date: 2026-08-30
- Parent tracker: [#137](https://github.com/gabned/provelume/issues/137)
- Predecessor: [#5](https://github.com/gabned/provelume/issues/5) / [PR #138](https://github.com/gabned/provelume/pull/138)
- Owner issue: [#140](https://github.com/gabned/provelume/issues/140)
- Owner PR: [#141](https://github.com/gabned/provelume/pull/141)
- Published baseline: `0.8.0`; `0.9.0` remains unreleased development

## Context

ADR 0014 selected the replaceable Tesseract CLI boundary and public OCR records without invoking
an engine. S02 must make that boundary executable while preserving Originals, keeping OCR derived
and uncertain, using Vigilia's durable scheduler, and avoiding any hidden network, download or
native-payload promise.

Tesseract does not rasterise PDF. A scanned PDF therefore requires a separately selected renderer;
TIFF page selection and all image families also need a bounded decoder boundary. These native
components expand the parsing and supply-chain perimeter even when Provelume does not redistribute
them.

## Decision

Provelume implements seven replaceable seams: capability discovery, document/page planning,
rendering/decoding, engine execution, TSV parsing, bundle persistence and durable job orchestration.
The first executable path is entirely local:

| Seam | S02 selection | Accepted version | Distribution |
| --- | --- | --- | --- |
| OCR engine | Tesseract CLI; reference release 5.5.3 | `>=5.3,<6` with exact runtime version recorded | external |
| PDF renderer | pypdfium2 5.13.0 / PDFium 153.0.7999.0 | pypdfium2 major 5, exact component versions recorded | external |
| image/TIFF decoder | Pillow 12.3.0 | Pillow major 12, exact codec versions where exposed | external |
| language data | explicit installed Tesseract packs; S02 smoke uses `eng` | exact installed IDs; reference digest retained | external |

The primary upstream records are the
[Tesseract repository and license](https://github.com/tesseract-ocr/tesseract),
[5.5.3 release](https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3),
[input-format guidance](https://tesseract-ocr.github.io/tessdoc/InputFormats.html),
[TSV/output documentation](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html),
[`tessdata_fast` source](https://github.com/tesseract-ocr/tessdata_fast),
[pypdfium2 5.13.0 source](https://github.com/pypdfium2-team/pypdfium2/tree/5.13.0),
[PDFium source and licensing tree](https://pdfium.googlesource.com/pdfium/), and
[Pillow 12.3.0 source](https://github.com/python-pillow/Pillow/tree/12.3.0).

### Discovery and explicit control

OCR remains disabled by default. A disabled report does not probe components. Once enabled, the
probe resolves the configured executable, runs bounded `--version` and `--list-langs` checks, and
probes the renderer in an isolated Python process. `ready` requires compatible engine, renderer and
decoder plus every explicitly selected local pack. No probe installs, downloads or falls back.

The loopback Browser and CLI expose configure, queue, execute, observe, cancel, remove and rebuild.
The versioned HTTP API is read-only. It exposes no lease token and advertises capability only after
a positive probe.

### Planning and execution

Media type, suffix and signature must agree. The supported input contract is scanned PDF, TIFF,
PNG, JPEG and BMP. Planning measures bytes, page count, per-page/total pixels, decoded bytes and
decompression ratio before engine invocation. The renderer stages one checksum-bound PNG per page.

Tesseract receives only an allowlisted argument vector with `shell=False`; the path, output base,
sorted languages, fixed page-segmentation mode and `tsv` output are separate arguments. It runs in
a private directory with a minimal environment. Stdout, stderr and output files are monitored
during execution. Per-page and whole-job deadlines are bounded. Cancellation and timeout terminate
the POSIX process group or Windows process tree before cleanup. Exit failure, missing or malformed
TSV and excessive output are closed errors.

This boundary is not described as a security sandbox. It has private directories, process-tree
termination and byte/time limits, but no container, seccomp profile or independently enforced CPU/
memory quota.

### Automatic mode and uncertainty

`automatic` skips only when existing `pypdf` embedded text reaches both contract thresholds: at
least 32 printable non-whitespace characters and printable ratio at least 0.85. Image metadata is
not text evidence. The generator and metrics are persisted with the request. Other modes are
`disabled`, `forced` and explicit `selected-page`.

Tesseract TSV becomes page text and word spans with source-pixel coordinates and confidence.
Confidence below 0.5 marks the span/page `needs-review`; all other OCR text remains
`machine-unverified`. Neither status is verified. Layout, table, barcode and QR collections remain
separate and empty because this adapter does not qualify such output.

### Durable state and atomic publication

The derivation/idempotency identity binds Original SHA-256, Version, contract version, pages, mode,
languages, all settings, and exact adapter/engine/renderer/decoder capability records. The existing
scheduler owns lease, heartbeat, retry/backoff, cancellation and terminal receipt behavior.
Checksum-bound page checkpoints survive a crash or expired lease, and completed pages are not
recomputed on resume.

Work is not a result. Only after every selected page succeeds does Provelume atomically promote a
bundle manifest and page text/result files, then register the derived artifact and provenance.
Original identity and the canonical tree are checked throughout. Removal affects only derived OCR
state; rebuild uses the retained content-free request material and preserves canonical state.

## Qualification and distribution

The real-component workflow qualifies only Ubuntu 24.04 x86-64 with Python 3.12, distribution
Tesseract 5.x and `eng`, pypdfium2 5.13.0/PDFium 153.0.7999.0 and Pillow 12.3.0 across PDF, TIFF,
PNG, JPEG and BMP generated fixtures. It logs exact system package, executable, pack and Python
component identity. All other platform/architecture combinations remain unqualified.

Base wheel, sdist and Windows installer contain no engine, language data, renderer, decoder or
optional wheel. There is no OCR Python extra. The two CI wheels are downloaded in an explicit
provisioning step, checked against recorded SHA-256 values and installed offline before runtime
smoke. The qualified-component CycloneDX file inventories this external path; it is not a release
SBOM and does not claim those components are bundled.

The pypdfium2 wheel's own `LICENSES`/`BUILD_LICENSES` inventory remains authoritative for its
native PDFium payload and dependencies. Tesseract, Leptonica, language packs and Pillow retain
their own terms. Redistribution is blocked until every actual binary, codec and pack has exact
source/version/digest, applicable license/notice material, release manifest/SBOM entries and an
offline installation test.

## Alternatives considered

- Passing PDF to Tesseract is invalid because Tesseract is a raster OCR engine, not a PDF renderer.
- `pypdf` remains the embedded-text extractor but cannot rasterise scanned pages.
- Poppler and Ghostscript were not selected for this baseline. They introduce a different native
  tool/process and redistribution-license perimeter, and Ghostscript would also recreate the
  OCRmyPDF orchestration choice rejected by ADR 0014.
- In-process rendering was rejected. The separate renderer worker makes imports optional and
  contains decoder crashes/output, though it is not a security sandbox.
- Bundling Windows binaries was rejected because S02 has no complete Windows component, codec,
  pack, notice and clean offline-install qualification.

## Consequences and explicit limits

Operators control every local dependency and pack. Missing or incompatible components produce
unambiguous capability errors. Results are reproducible only when exact source, settings and
component identities remain available. Printed text is the only qualified content; there is no
handwriting, semantic correction, automatic verification, advanced preprocessing, layout/table/
barcode/QR claim or remote fallback. `0.9/S03` remains a forecast only and is not activated by
this decision.
