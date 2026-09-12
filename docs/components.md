# Component catalogue

The local **Components** page and `GET /api/v1/components` explain which parts of the effective
Provelume runtime are installed, missing or still unverified. The same JSON is available with:

```bash
provelume component-inventory
```

Every record states its category, purpose, dependency relationship, delivery and update route,
license/notices, declared version contract, effective version and evidence state. The installed
Python inventory follows the runtime dependency closure from Provelume, including present
transitive distributions and excluding development extras. `installed`
means only that local distribution/runtime metadata agrees with the declared contract. It is not a
security endorsement. `ahead`, `incompatible`, `eol`, `missing` and `unverified` remain distinct.

The inventory does not execute optional tools or search model directories. Executable detection
reports presence without returning its path; model and language-pack claims require explicit
evidence. No credential, private filesystem path or Instance content is included.

Schema 2 adds the `ui_asset` category to the existing seven categories. The `ui.lucide`
entry describes the 18-icon subset packaged with Provelume, version 1.45.0, with the
complete upstream `ISC AND MIT` license. Its installed state requires exact manifest,
SVG and license hashes from package resources. A missing or altered file remains
missing or unverified. No icon service, executable or remote registry is consulted.
See [ADR 0028](adr/0028-cura-icons-and-provenance.md) for the pin and update procedure.

## Release SBOM comparison

A local operator can compare a downloaded or assembled CycloneDX release SBOM:

```bash
provelume component-inventory --release-sbom /trusted/local/bom.cdx.json
```

The file is read locally with byte and component limits. The command never contacts a registry,
advisory service, provider or model host, and it never installs or updates anything. Without this
explicit evidence the release comparison is truthfully `unavailable`. Latest-known and security
states remain `not_checked` and `unverified` until a separate explicit network capability is
qualified.

The release SBOM includes this same installed subset before its fingerprint is generated.
Matching the version alone is insufficient: the commit, subset and license digests must
also agree. A same-version altered subset is reported as a mismatch.
