# Local OCR capability contract

Status: delivered as `0.9/S01` under
[#137](https://github.com/gabned/provelume/issues/137) and
[#5](https://github.com/gabned/provelume/issues/5) by owner
[PR #138](https://github.com/gabned/provelume/pull/138).

S01 defines a stable local OCR boundary. It does **not** implement the complete renderer, Tesseract
process adapter, document-bundle integration or user execution flow. OCR is therefore not an
available Provelume processing feature yet.

The normative code contract is
[`ocr_contract.py`](../../core/provelume/ocr_contract.py), the machine-readable schema is
[`ocr_contract.schema.json`](../../core/provelume/ocr_contract.schema.json), and the technology
and licensing decision is [ADR 0014](../adr/0014-local-ocr-contract-and-packaging.md).

## Baseline rules

- OCR is local and offline. No cloud endpoint or remote provider is part of the baseline.
- The default mode is `disabled`; disabled reporting does not probe an adapter or engine.
- Provelume never downloads an engine or language pack at runtime and has no implicit fallback.
- The exact acquired Original remains authoritative and unchanged.
- OCR text and observations are derived, removable and rebuildable.
- An OCR failure cannot authorize a canonical mutation, Original deletion or automatic cleanup of
  user knowledge.
- The first engine seam is Tesseract CLI 5.5.3, but adapters remain replaceable and explicit.

## Configuration

New Instances receive the full disabled default. Existing Instances without an `ocr` section
behave identically and resolve to the same default without a migration:

```yaml
ocr:
  schema_version: 1
  mode: disabled
  engine: tesseract-cli
  languages:
    - eng
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

Configurations may lower those ceilings but cannot raise them. Unknown fields, modes and limits
fail closed.

## Modes and language policy

| Mode | Contract |
| --- | --- |
| `disabled` | never schedules OCR and never discovers an engine |
| `automatic` | schedules only when existing reliable text is below the explicit character or printable-ratio threshold |
| `forced` | requests OCR for every otherwise valid page in the explicit job |
| `selected-page` | requires a sorted, unique, nonempty and in-range 1-based page list |

One to eight sorted language-pack IDs must be selected explicitly. Optional `bounded` detection
may choose only among at most four of those already installed packs. It cannot broaden the set or
download a model. Orientation/script data such as `osd` is a separate opt-in pack.

## Supported input perimeter

The contract accepts scanned PDF, TIFF, PNG, JPEG and BMP. Media type, extension and leading file
signature must agree. WebP, GIF, JPEG 2000 and PNM remain unsupported even if a particular
Leptonica build could decode them.

Tesseract consumes raster images, not a general PDF object model. S02 must choose and qualify a
bounded PDF rasteriser, measure page and decoded-image evidence before engine invocation and retain
the exact page raster hash in provenance.

Oversized input bytes, page counts, per-page/total pixels, decoded bytes, decompression ratio,
temporary storage and deadlines have separate closed errors. Corrupt and unsupported inputs fail
without invoking another provider.

## Capability and absence reporting

The closed states are `disabled`, `adapter-unavailable`, `engine-unavailable`,
`language-pack-missing` and `ready`. Each unavailable report contains stable English and Italian
messages; a language-pack failure also names the exact missing pack IDs. Every report includes
these invariant facts:

```json
{
  "network_required": false,
  "runtime_downloads": false,
  "remote_fallback": false,
  "original_mutation": false,
  "canonical_mutation": false
}
```

S01 ships no built-in execution adapter, so enabling OCR in configuration produces
`adapter-unavailable`, not a download or a false ready state.

The adapter seam receives an exact request record plus a staged raster path inside the private
job directory. The request binds page identity, staged media type, settings fingerprint,
languages, deadline and the configured output-character limit. PDF is never passed directly to
the engine seam; S02 must stage and hash one bounded raster per page. Adapter output is rejected if
its provenance, page or configured output limit does not match that request.

## Derived page record and provenance

Every page is identified by Original SHA-256, canonical Version ID, 1-based page number, raster
SHA-256 and source media type. Every result also records the engine and adapter IDs/versions,
language packs and settings fingerprint. Together these fields form a deterministic derivation key
for replay and idempotency.

Text and spans can only be `machine-unverified` or `needs-review`; there is no verified OCR
status. Confidence is an engine observation between 0 and 1. Coordinates use source-page pixels
and include page dimensions. Layout, table, barcode and QR-code observations are four separate
adapter-versioned collections; absent adapter support leaves them empty.

Committed pages produce an `ocr.page.committed` checkpoint with sequence, completed pages and the
next page. This record is compatible with Vigilia's content-free processed/skipped/error progress,
lease and recovery lifecycle. S01 does not register an executable scheduler job.

## Temporary files and deletion

The seam creates one unshared temporary directory per job under an explicit local root and removes
it after success or exception. POSIX directories are forced to mode 0700. Windows uses a per-user
root and inherited ACLs; S02 must qualify that DACL as well as OS process, CPU/memory and deadline
isolation around the engine.

OCR artifacts belong under derived state. Removing them does not remove an Original or canonical
record. A rebuild creates the same derivation identity only when page bytes, engine, adapter,
languages and settings are unchanged.

## Packaging status

The base wheel, sdist and Windows installer contain no Tesseract binary or language pack and add no
OCR runtime dependency. A future Windows component may be delivered only as a default-off, fully
pre-staged offline payload with exact source/version/digests, license files, notices, release
manifest entries, SBOM and offline verification. Silent runtime download remains forbidden.

See the
[`tesseract-5.5.3.json` packaging record](../../packaging/ocr/tesseract-5.5.3.json) for the
platform matrix, reference language-pack provenance, size budgets and redistribution gates.

## Next slice

`0.9/S02` may implement bounded PDF/image page preparation, Tesseract process isolation, derived
artifact persistence and document-bundle integration against this exact contract. It is not active
and has no issue, branch or owner PR yet.
