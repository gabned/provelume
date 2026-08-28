# Versioned document bundles

Status: active product contract for `0.5/S03` under issue #66. The installed package and
published preview remain `0.4.1` until a separate release-preparation change.

## Purpose and authority

A document bundle gives humans and later agents a portable working representation of one exact
DocumentVersion. It is derived state. The content-addressed Original and canonical Version remain
the authority and are never overwritten, replaced or deleted by bundle construction.

Before any bundle is built, Provelume reads the Version's Original and verifies its SHA-256 and
size against both canonical records. A mismatch fails visibly and produces no new bundle.

## Portable layout

Bundles are immutable, content-addressed directories beneath:

```text
state/derived/bundles/<version_id>/<output_fingerprint>/
  manifest.json
  document.md
  page-map.json
  assets/
```

`output_fingerprint` is derived from the source Version hash, normalized Markdown checksum,
page-map checksum, selected asset checksums and bounded warnings. Rebuilding the same Version with
the same generator contract produces the same directory and manifest bytes. A single deterministic
`DerivedArtifact(kind="document_bundle")` points to the complete manifest and is linked from the
Version by derived provenance.

The manifest contains no build timestamp. Runtime timing belongs in the operation log, not in the
portable bundle identity.

## Markdown and page map

PDFs are processed page by page. `document.md` contains one document heading and one explicit page
section per source page. `page-map.json` records, for every page:

- source page number and label;
- inclusive Markdown line range;
- normalized page-text SHA-256 and character count;
- extraction status;
- referenced asset identities.

Other supported formats produce one logical page using their deterministic local extractor. Text
normalization standardizes line endings, removes trailing whitespace and collapses repeated blank
lines. Empty source pages remain visible as `_No extractable text._` rather than disappearing.

The normalized text budget is two million characters for the complete bundle, not for each page.
Each page consumes the remaining aggregate budget in source order. The page map records
`truncated` or `text_limit` when the budget is reached, and later pages remain represented rather
than silently disappearing.

The browser deliberately displays raw Markdown as escaped text in this slice. It does not execute
HTML, scripts, embedded active content or remote resources.

## Bounded assets

For PDFs, embedded images are inspected opportunistically through the packaged PDF library. Every
accepted asset has a deterministic safe filename, media type, byte count and SHA-256. Extraction is
bounded by:

- 500 PDF pages;
- 400 lazily inspected asset candidates, including rejected candidates;
- 200 accepted assets;
- 10 MiB per asset;
- 50 MiB total accepted assets;
- two million normalized text characters across the complete bundle;
- 200 retained warnings.

Asset candidates are iterated lazily. An oversized, unsupported or undecodable candidate still
consumes the inspection budget, so rejection cannot turn the scan into unbounded CPU or memory
work. An unsupported image filter, oversized asset or inspection error is recorded as a bundle
warning. The Markdown/page map still commit when safe. The operation closes as
`completed_with_errors` so the omission remains visible. No OCR, rasterization, external converter
or optimized replacement PDF is added in this slice.

## Failure isolation and operations

`bundle-build` creates one `bundle.build` operation. `bundle-build-all` creates a parent
`bundle.build_all` operation and one child operation per current DocumentVersion. A malformed PDF
or missing/corrupt Original fails only that child; valid documents continue. Child warnings are
propagated to the parent status and metrics instead of being hidden by an otherwise successful
bulk run.

Operation events record Original verification, deterministic commit, page/asset/warning counts and
bounded failure type without physical Source paths or document content.

## Local commands

```text
provelume bundle-build INSTANCE DOCUMENT_ID [--version-id VERSION_ID]
provelume bundle-build-all INSTANCE [--max-documents N]
provelume bundles INSTANCE
provelume bundle INSTANCE VERSION_ID [--include-markdown]
```

## Read-only navigation and validation

```text
GET /api/v1/bundles
GET /api/v1/bundles/{version_id}
GET /api/v1/bundles/{version_id}/markdown
GET /api/v1/bundles/{version_id}/page-map
GET /api/v1/bundles/{version_id}/assets/{asset_id}
GET /api/v1/documents/{document_id}/bundle
/bundles
/bundles/{version_id}
```

These routes do not build, rebuild, edit or delete a bundle. Before exposure, Provelume verifies
the DerivedArtifact record, manifest checksum, output fingerprint, Version/source hash, expected
bundle-relative paths and the checksum/size of Markdown, page map and every asset. A malformed or
manually altered derived bundle is omitted or reported as not found; the authoritative Original is
not changed. A read against a fresh Instance creates no bundle directory.

## Explicit exclusions

This slice does not add OCR, PDF optimization, rendered Markdown, remote assets, network access,
AI context selection, duplicate decisions, destructive Original cleanup, Instance schema
migration, package-version change, tag or release publication. Duplicate/original assurance and
rebuild/locking integration remain later `0.5` slices.
