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

## Selected optional OCR baseline — not bundled in 0.9/S01

The `0.9/S01` contract selects the Tesseract CLI as the first replaceable local OCR engine seam,
but it adds no engine binary, language model or OCR runtime dependency to the base wheel, source
distribution or Windows installer. The following components were evaluated for a future opt-in
offline component and are **not bundled** by this slice:

| Component | Intended purpose | License | S01 distribution |
| --- | --- | --- | --- |
| Tesseract 5.5.3 | local printed-text OCR engine | Apache-2.0 | not bundled |
| Leptonica | Tesseract image decoding and processing | BSD-2-Clause | not bundled |
| `tessdata_fast` language packs | explicit local OCR language data | Apache-2.0 | not bundled |

The exact source, version, license and digest for every linked image codec remain a future
packaging gate, not an inferred Tesseract license. Before any of these components is redistributed,
the release must carry the applicable Apache-2.0 and BSD-2-Clause terms and attributions, enumerate
every binary and language pack in the release manifest and CycloneDX SBOM, publish exact checksums,
and prove an offline installation with networking denied. Provelume's public or commercial license
does not replace any third-party term.
