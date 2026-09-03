# ADR 0023: Bounded photo profiles and optional decoder

## Status

Accepted for 0.10/S03.

## Context

Exact image Originals can already be preserved and sent through the document-oriented OCR path,
but that path does not define photo privacy, previews or the difference between exact and visual
similarity. Serving an Original directly would also expose active or private metadata.

## Decision

Core identifies and bounds JPEG, PNG, TIFF and BMP by signature, dimensions, pixels, expansion
ratio, metadata records and metadata bytes. It emits only family presence/digests plus safe
orientation, color and unverified capture-time evidence. EXIF/IPTC/XMP device values are not
exported; coordinates are always absent and GPS defaults to excluded.

Pillow 12.3.0 is the only selected optional decoder. The exact Ubuntu wheel hash is retained in
packaging/photo/pillow-12.3.0.json; it is never bundled or downloaded at runtime. When present,
it produces an orientation-normalized first-frame RGB PNG with source metadata stripped and a
review-only dHash. When absent or incompatible, core inspection remains available while preview
and perceptual evidence are visibly unavailable. Windows proves that degraded base-install path.

SHA-256 exact matches and bounded perceptual proposals remain separate evidence classes and never
authorize merge or deletion. Lectio OCR page evidence is reused through universal anchors. No
QR/barcode implementation is selected; the closed seam emits typed, payload-redacted observations
only for an explicitly injected adapter reporting qualified identity.

WebP, HEIC/HEIF, AVIF and RAW/DNG remain Preserve-only in this slice. No face, identity, emotion,
sensitive-trait, source edit, metadata write-back, ambient scan, provider, AI or update path exists.

## Consequences

- Derived profiles are attributable, removable, equivalently rebuildable and portable.
- The Browser can request only a generated PNG, with no Original-photo endpoint added.
- Reprocessing under another recipe creates another representation and keeps prior evidence.
- Supporting another decoder, format or barcode adapter requires a later explicit decision.
