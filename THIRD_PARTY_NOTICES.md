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
| build | Python wheel/source distribution builder | MIT |
| CycloneDX Python (`cyclonedx-bom`) | release SBOM generation | Apache-2.0 |
| GitHub Actions checkout/setup/upload/attest actions | public CI and release automation | licenses published by their respective repositories |

These components have their own copyright notices and license terms. Transitive dependencies retain their own terms as well. Published release SBOMs are the machine-readable dependency inventory for the built Python environment; this file is a human-readable summary, not a substitute for that SBOM.
