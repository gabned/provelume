# ADR 0028: Cura icons and packaged-asset provenance

## Status

Accepted for PRODUCT `0.11/S02`, issue #258. Extends ADR 0022 for packaged UI assets.
This decision precedes Lucide asset inclusion and changes no Protocol requirement.

## Context

Cura needs one small, offline icon family beside visible localized labels. The earlier
MIT-only description of Lucide is inaccurate at the selected pin. The complete upstream
LICENSE starts with Lucide's ISC terms and retains MIT terms for its listed Feather-derived
icons. The mixed subset must preserve both notices; this is not a choice of license.

## Decision

Vendor exactly 18 unchanged SVG sources from `lucide-icons/lucide`, version/tag `1.45.0`,
commit `b998e2892b90b88004d62da2d0b64dab9959a520`. Preserve the entire upstream LICENSE,
including Lucide Icons and Contributors and Cole Bemis copyrights, the Feather icon list,
permissions and disclaimers. Record aggregate licensing as `ISC AND MIT`, never MIT-only
or `ISC OR MIT`. The pinned LICENSE SHA-256 is
`b495047bd93a9b06913511076f504daba17d5bbeb3e0650f3bb53a4220329c57`.

The closed set is arrow-left, chevron-down, circle-check, clock, house, inbox, info,
library, loader-circle, menu, monitor, moon, search, settings, sliders-horizontal,
sun, triangle-alert and x. Direct Feather-list matches and triangle-alert's upstream
alias `alert-triangle` retain Feather attribution; no exhaustive per-icon authorship
or blanket MIT claim is inferred from geometry or metadata.

`static/icons/lucide/subset.json` is the single asset manifest. It records the pin,
source paths, Git blob IDs, raw sizes and SHA-256 values, license identity, primary
references and reviewed-release update route. Its canonical UTF-8 JSON uses sorted
keys, compact separators and one trailing LF. The catalogue anchors the SHA-256 of
those exact bytes. No second asset registry or runtime upstream service is introduced.

The verifier reads only package resources, with a closed file set and explicit byte
limits; it rejects missing/extra files, directories, symlinks/junctions, invalid names,
manifest mismatch, source-byte mismatch and SVG active content. Geometric elements and
attributes are allowlisted. XML declarations, DTDs/entities, references, scripts,
event handlers, inline style and foreign content are excluded. Verification performs
no process, network, package-manager operation or Instance write.

`render_icon(name)` accepts only a canonical subset name and returns trusted decorative
markup after verification. Rendering adds fixed `class="cura-icon"`,
`aria-hidden="true"` and `focusable="false"` attributes; stored upstream SVG bytes stay
unchanged. Icons retain `currentColor`; callers supply visible localized text and
independent status meaning. The helper cannot accept arbitrary SVG, CSS, attributes or
paths. Brand marks remain separate. A spinner alone does not prove progress.

Each Preview response builds a renderer from one freshly verified subset snapshot.
All icons in that response share the verified immutable markup. Verification is not
cached across requests, so a later request detects subsequently altered resources.

Inventory schema/catalogue version 2 adds `ui_asset` and the closed `packaged_asset`
detector. Existing component detection and version reconciliation semantics remain
unchanged. `ui.lucide` is installed only after exact packaged-manifest and file
verification. Missing and invalid assets remain distinct from successful detection.

The shared deterministic SBOM augmenter runs against resources from the installed
release wheel, before the existing SBOM fingerprint/serial/digest steps. It adds a
Lucide source-subset component and application dependency using the same verified
manifest, with version, commit, full-license and subset digests. Same-version metadata
with different commit/bytes cannot reconcile as matched. Existing Python component
semantics and independent artifact qualification remain unchanged.

## Consequences and update route

An update is a reviewed Provelume source/release change: select an exact upstream commit,
retain complete applicable licenses, reacquire the closed source set, recompute and review
all hashes, update the catalogue anchor, regenerate the release SBOM and verify actual
wheel/sdist/frozen inclusion. Ordinary builds and runtime verification remain offline.
No npm/icon framework, CDN, font, subscription or automatic asset updater is required.

Targeted synthetic checks establish manifest/rendering/inventory/SBOM contracts. Actual
artifact inclusion, frozen Windows behavior, browser accessibility and human language
review need their own evidence and are not implied by this decision.

Primary sources: [pinned LICENSE](https://github.com/lucide-icons/lucide/blob/b998e2892b90b88004d62da2d0b64dab9959a520/LICENSE),
[release 1.45.0](https://github.com/lucide-icons/lucide/releases/tag/1.45.0), and
[triangle-alert metadata](https://github.com/lucide-icons/lucide/blob/b998e2892b90b88004d62da2d0b64dab9959a520/icons/triangle-alert.json).
