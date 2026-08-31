# Local OCR execution and document bundles

Status: `0.9/S01` established the public contract through
[#5](https://github.com/gabned/provelume/issues/5) and
[PR #138](https://github.com/gabned/provelume/pull/138). `0.9/S02 — Bounded local OCR and
document bundles` implements that contract under owner
[#140](https://github.com/gabned/provelume/issues/140) and
[PR #141](https://github.com/gabned/provelume/pull/141). Lectio remains unreleased development:
the package, runtime and embedded build identity stay `0.8.0`.

The normative records are:

- [`ocr_contract.py`](../../core/provelume/ocr_contract.py) and
  [`ocr_contract.schema.json`](../../core/provelume/ocr_contract.schema.json) for settings,
  capability, request and page-result records;
- [`ocr_bundle.schema.json`](../../core/provelume/ocr_bundle.schema.json) for the successful,
  atomically promoted document-bundle manifest and page envelope;
- [ADR 0014](../adr/0014-local-ocr-contract-and-packaging.md) for the S01 engine decision and
  [ADR 0015](../adr/0015-bounded-local-ocr-execution.md) for the executable S02 path;
- [`tesseract-5.5.3.json`](../../packaging/ocr/tesseract-5.5.3.json) and the
  [qualified external-component BOM](../../packaging/ocr/qualified-local-components.cdx.json) for
  the tested component and licensing perimeter.

## Non-negotiable boundary

- OCR is optional, local and offline. The default is `disabled` and a disabled probe does not
  discover or start an engine.
- Provelume performs no runtime download, package installation, provider request or remote
  fallback. Engine, renderer, decoder and language packs are operator-installed local components.
- The exact acquired Original remains authoritative. Its SHA-256 and byte length, and the complete
  canonical knowledge fingerprint, are checked before and after planning, execution, failure,
  cancellation, removal and rebuild.
- OCR text is an unverified derived artifact. It never becomes canonical knowledge or verified
  text automatically. Confidence is engine evidence, not a truth claim.
- Layout, table, barcode and QR observations are separate from text. The baseline Tesseract
  adapter emits none, so those collections remain empty.

## Qualified components and matrix

The selected reference engine remains Tesseract CLI 5.5.3 under Apache-2.0. The adapter accepts a
reported engine version in `>=5.3,<6`, resolves the configured executable to an exact local path,
and records that version and path. It checks the installed language-pack list before accepting a
job. It never installs Tesseract or a pack.

PDF rasterisation uses pypdfium2 5.13.0 with PDFium 153.0.7999.0. TIFF, PNG, JPEG and BMP decoding
uses Pillow 12.3.0. These wheels and their native contents are external to every Provelume package.
The only S02 real-component qualification is:

| OS | Architecture | Python | Engine/packs | Renderer/decoder | Inputs |
| --- | --- | --- | --- | --- | --- |
| Ubuntu 24.04 | x86-64 | 3.12 | distribution Tesseract 5.x plus local `eng`; exact CI identity is logged | pypdfium2 5.13.0 / PDFium 153.0.7999.0 / Pillow 12.3.0 | scanned PDF, TIFF, PNG, JPEG, BMP |

Windows process cleanup is covered by the normal cross-platform test suite, but no Windows OCR
engine/renderer combination is S02-qualified. Windows x86-64 and ARM64, Linux ARM64 and macOS
x86-64/ARM64 therefore remain unqualified for OCR execution. This is not a general PDF, codec or
language support claim.

## Explicit local setup

Create the normal Provelume environment first. Then install the external components through an
operator-controlled system/environment procedure. For the qualified Ubuntu profile, the CI model
is equivalent to:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng
.venv/bin/python -m pip install 'pypdfium2==5.13.0' 'Pillow==12.3.0'
```

Those commands are setup examples, not runtime behavior. The CI workflow downloads the two exact
wheels in a separate provisioning step, verifies their recorded SHA-256 digests, installs them
offline from its wheelhouse, and only then runs the product smoke test.

Enable OCR explicitly and inspect the resulting capability before queueing work:

```bash
.venv/bin/provelume ocr-configure INSTANCE \
  --mode automatic \
  --language eng \
  --engine-executable /usr/bin/tesseract
.venv/bin/provelume ocr-capability INSTANCE
```

Use repeated `--language` options for a sorted explicit pack set. `--tessdata-path` may point to an
operator-managed local pack directory. The same configuration and lifecycle controls are
available on the loopback-only `/ocr` Browser page. Browser mutations require its per-process CSRF
token. HTTP API routes remain read-only.

The complete disabled default is:

```yaml
ocr:
  schema_version: 1
  mode: disabled
  engine: tesseract-cli
  engine_executable: tesseract
  tessdata_path: null
  renderer: pdfium-pillow
  render_dpi: 300
  languages: [eng]
  language_detection:
    mode: disabled
    candidates: []
  automatic:
    min_reliable_characters: 32
    min_printable_ratio: 0.85
  limits:
    max_input_bytes: 268435456
    max_pages: 200
    max_page_pixels: 80000000
    max_total_pixels: 500000000
    max_decompressed_page_bytes: 335544320
    max_decompression_ratio: 100
    max_temp_bytes: 1073741824
    max_seconds_per_page: 60
    max_total_seconds: 900
    max_output_chars_per_page: 500000
```

Configurations may lower these ceilings but cannot raise them. Unknown fields and invalid values
fail closed.

## Modes and deterministic automatic rule

| Mode | Execution rule |
| --- | --- |
| `disabled` | never probes, plans, queues or executes OCR |
| `automatic` | skips only when trusted embedded PDF text has at least 32 non-whitespace printable characters and a printable ratio of at least 0.85; otherwise queues OCR |
| `forced` | queues every valid page in the document |
| `selected-page` | requires a sorted, unique, nonempty, in-range list of 1-based pages |

For this input perimeter, only the `pypdf` embedded-text extractor is reliable-text evidence.
Image metadata such as format and dimensions never suppresses automatic OCR. The rule, generator,
character count and ratio are stored with the durable request. One to eight language IDs are
explicit; the baseline passes only locally installed selected packs to Tesseract.

Queue and execute an exact Version locally:

```bash
.venv/bin/provelume ocr-queue INSTANCE VERSION_ID --mode forced --language eng
.venv/bin/provelume ocr-run INSTANCE JOB_ID
.venv/bin/provelume ocr-job INSTANCE JOB_ID
```

For selected pages, add `--mode selected-page --page 1 --page 3`. An `automatic` skip returns a
durable decision response but creates no engine work.

## Process and hostile-input controls

Planning first checks media type, suffix and signature, input bytes, page count, page and total
pixels, decoded bytes and decompression ratio. PDFium never passes a PDF to Tesseract; it renders
one bounded PNG page at a time. Pillow decodes only the declared image families. Corrupt,
unsupported and over-limit input fails without another decoder/provider fallback.

Tesseract runs with `shell=False`, an allowlisted argument vector, a minimal content-free child
environment and a private per-page directory. Stdout, stderr and produced files are monitored
while the process runs. Per-page and total deadlines are enforced. Timeout or cancellation
terminates the POSIX process group or Windows process tree before temporary cleanup. Non-zero exit,
missing TSV, malformed/incomplete TSV and excessive output have distinct closed failures.

This is process containment, not a general security sandbox. S02 does not claim an OS sandbox,
container boundary, seccomp profile or independently enforced CPU/memory quota. POSIX temporary
roots are mode `0700`; Windows uses the current user's inherited ACL. Only Ubuntu x86-64 has the
real-component qualification above.

## Durable lifecycle and bundle

The scheduler idempotency key binds Original identity, Version, contract version, selected pages,
mode, languages, settings, adapter, engine, renderer and decoder identities. The journal supplies
exclusive lease, heartbeat, bounded retry and terminal receipts. Each completed page is written to
a checksum-bound work checkpoint. An expired lease or crash resumes completed pages instead of
publishing or recomputing them; a transient failure may retry the unfinished page.

Only a complete document is atomically promoted under `state/derived/ocr-bundles/`. Its manifest
contains job state, Original/Version/Document identity, settings and component provenance, stable
page result/text references and hashes, page warnings, uncertainty flags, and removal/rebuild
facts. Each page result contains text, coordinates and confidence when Tesseract produced them,
plus a source-page raster hash. No partial work directory is listed as a successful derived
artifact.

Control commands are:

```bash
.venv/bin/provelume ocr-jobs INSTANCE
.venv/bin/provelume ocr-cancel INSTANCE JOB_ID
.venv/bin/provelume ocr-bundles INSTANCE --version-id VERSION_ID
.venv/bin/provelume ocr-remove INSTANCE VERSION_ID
.venv/bin/provelume ocr-rebuild INSTANCE VERSION_ID
```

Removal deletes only the derived bundle, its derived-artifact/provenance records and resumable work.
It retains a content-free rebuild receipt. Rebuild removes the prior derivation, queues it again
with the same material derivation identity and never changes the Original or canonical knowledge.

## Capability and failures

The probe reports configured/effective limits, selected and installed languages, resolved engine
and PDFium paths, exact engine/renderer/decoder/component versions and invariant no-network facts.
It advertises `available: true` only in `ready`. Closed states distinguish `disabled`, missing
adapter, missing engine, missing renderer/decoder, incompatible version and missing language pack.
Execution further distinguishes unsupported/corrupt/oversized input, page/pixel/decompression/temp/
time/output limits, cancellation, invalid engine output, adapter failure, contract violation and
internal error. Messages are stable in English and Italian and never include source content.

Read-only status is available at `/api/v1/ocr/capability`, `/api/v1/ocr/jobs`,
`/api/v1/ocr/jobs/{job_id}` and `/api/v1/ocr/bundles`. Lease tokens are never exposed. Queue,
execute, cancel, remove and rebuild remain explicit local CLI or protected loopback Browser actions.

## Packaging, licensing and limits

The base wheel, sdist and Windows installer contain the Python seam and schemas but no Tesseract,
Leptonica, language pack, pypdfium2/PDFium or Pillow payload and no OCR runtime dependency. Python
extras do not pretend to install native components. The external-component BOM is qualification
evidence, not a Provelume release SBOM. Any future redistribution requires exact binary/codec/pack
inventory, digests, license/notice files, release manifest/SBOM entries and an offline install test.

Known S02 limits include printed-text OCR only, Tesseract page-segmentation mode 3, no semantic
verification or automatic correction, no qualified handwriting promise, no automatic deskew or
advanced preprocessing, no baseline layout/table/barcode/QR adapter, and no supported platform or
language beyond the exact matrix proved above. `0.9.0` is not published and no tag, release or
asset is created by this slice.

`0.9/S03` is implemented separately by issue #143 and its owner PR without changing the S02 OCR
contract. `0.9/S04` is only the next forecast and is not activated by this document.
