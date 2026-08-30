# Third-party notices

Provelume's public license does not replace the licenses of third-party dependencies.

Direct runtime dependencies in the current Python package include:

| Component | Purpose | License |
| --- | --- | --- |
| FastAPI | Knowledge API and web routing | MIT |
| Jinja2 | server-side Knowledge Browser templates | BSD-3-Clause |
| pypdf | local PDF text extraction | BSD-3-Clause |
| PyYAML | Instance configuration | MIT |
| Uvicorn | local ASGI server | BSD-3-Clause |

Release-build tooling includes:

| Component | Purpose | License |
| --- | --- | --- |
| build | Python wheel/source distribution build frontend | MIT |
| Hatchling | pinned Python build backend and reproducible archive support | MIT |
| CycloneDX Python (`cyclonedx-bom`) | release SBOM generation | Apache-2.0 |
| GitHub Actions checkout/setup/upload/attest actions | public CI and release automation | licenses published by their respective repositories |

These components have their own copyright notices and license terms. Transitive dependencies retain their own terms as well. Published release SBOMs are the machine-readable dependency inventory for the built Python environment; this file is a human-readable summary, not a substitute for that SBOM.

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
