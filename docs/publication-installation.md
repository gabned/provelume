# Installing actual publication metadata offline

Cura's publication receipt reports the release's actual public timestamp. It is optional
descriptive evidence at runtime: missing, mismatched or malformed evidence hides NEW and never
substitutes installation, build or first-visit time. The complete official installation path
below supplies it explicitly. This contract applies to future releases produced by the Cura
publisher; historical releases are not claimed to have these new assets.

## Obtain and verify a ready installation kit

From the matching official release, obtain `provelume-VERSION-installation-kit.zip`,
`publication-ready.json` and `publication-receipt.json`. A raw Setup or Python distribution
alone remains a verifiable payload; it does not include actual-publication metadata.
An absent readiness marker means the publisher has not completed finalization.

Check the kit and receipt size/SHA-256 against the readiness marker. For publisher authentication,
verify their public-workflow attestations using the existing
[release provenance procedure](release-verification.md#verify-github-build-provenance) before
disconnecting. Comparing a marker's hashes alone does not authenticate its publisher. Keep any
independently verified evidence needed by your deployment's offline trust procedure.

Extract the kit into a new directory, preserving this layout:

```text
kit/
  publication/publication-receipt.json
  release/release-manifest.json
  release/SHA256SUMS
  release/verify-provelume-release.py
  release/<the unchanged qualified release files>
```

Run the existing standalone verifier against `kit/release` with the expected version, tag and
commit. The inner bundle file set and all original hashes remain exactly the qualified bundle;
the outer receipt is not inserted into the old manifest or checksums. The kit adds no portable
Windows distribution. Installer and Python payloads remain the supported distribution paths.

## Wheel or source distribution

Install the extracted wheel into the intended Python environment using your normal package
procedure, then run that environment's `provelume`:

```bash
python -m pip install --no-index --find-links /path/to/prepared-dependencies \
  kit/release/provelume-VERSION-py3-none-any.whl
provelume publication import \
  --receipt kit/publication/publication-receipt.json \
  --manifest kit/release/release-manifest.json \
  --payload kit/release/provelume-VERSION-py3-none-any.whl
provelume publication show
```

Substitute the real release version. Offline installation still requires your environment's
ordinary runtime dependencies; the kit is not an offline dependency repository. For an sdist,
install `provelume-VERSION.tar.gz` with its prepared build/runtime dependencies, then pass that
original sdist to `--payload`. The installed embedded source identity must match the receipt.
Import verifies the original distribution; it does not turn a locally rebuilt wheel into an
independently authenticated official wheel.

Import stores unchanged receipt bytes under
`sys.prefix/share/provelume/publication/VERSION-COMMIT/publication-receipt.json`, outside package
files and RECORD. If that location is read-only, use `--destination /managed/path/receipt.json`
and configure `PROVELUME_PUBLICATION_RECEIPT` to that same file for subsequent processes. An
existing different receipt is rejected rather than overwritten. Normal environment permissions
apply; no elevated install is introduced.

## Windows Setup and updater

Run the original `kit/release/Provelume-Setup-VERSION-x64.exe` in place. Setup finds the sibling
`kit/publication/publication-receipt.json`, verifies it against its own original EXE and adjacent
release manifest using the installed runtime, and imports it under
`INSTALL_DIRECTORY/publication/VERSION-COMMIT/`. A failed import produces a visible installation
error. Existing instance preservation and normal installation confirmations still apply.

For future schema-2 updates the updater waits for the ready marker, checks the event/receipt
against the resolved tag, then downloads the verified Setup, receipt and release manifest into
the same update directory. Only after all downloads pass does it offer the existing apply
confirmation and pass `/PUBLICATIONRECEIPT=...` to Setup. It performs no automatic apply and
does not infer publisher authentication or Windows signing from hashes. Historical schema-1
updates keep their existing compatibility path and supply no invented publication metadata.

## Add metadata to an existing raw installation

A user who installed a raw wheel or sdist can later obtain the matching receipt, original release
manifest and exact original payload, transfer them offline, and use the same import command above.
No reinstall or first-visit timestamp is needed. For raw Windows Setup users:

```powershell
& "$env:LOCALAPPDATA\Programs\Provelume\Provelume.exe" `
  --import-publication "D:\release\publication-receipt.json" `
  --publication-manifest "D:\release\release-manifest.json" `
  --publication-payload "D:\release\Provelume-Setup-VERSION-x64.exe"
```

Alternatively run the original Setup with `/PUBLICATIONRECEIPT="D:\release\publication-receipt.json"`
while its matching `release-manifest.json` is beside the Setup. Raw Setup without a receipt
continues to report missing publication metadata. The receipt import never changes installed
package/executable bytes, claims actual publication without event evidence, or establishes
publisher authentication. Local About/CLI reads do not contact GitHub.

## Publisher recovery

If publication or finalization fails, inspect the failed step and job summary. Rerun the failed
publisher job in the same workflow run, retaining its original qualified artifact download and
exact source commit. Do not rerun assembly, recreate the release, move the tag or overwrite an
asset. The permanent prepare/finalize commands compare existing bytes and add only missing
assets. A conflicting public receipt, payload or event requires investigation; it cannot be
repaired by silently replacing the evidence. Only an observed matching ready marker ends the
pending state. See [ADR 0029](adr/0029-offline-publication-receipt.md).
