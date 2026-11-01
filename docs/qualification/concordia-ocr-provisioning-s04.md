# Concordia S04: optional offline Windows OCR provisioning

This candidate is the provisioning part of [#381](https://github.com/gabned/provelume/issues/381),
under #383. Source consent, ingestion triggers, historical backlog, common text
selection, Inbox and the setup wizard remain later slices. The base package still
works with OCR disabled and no kit. Importing a kit changes no OCR mode, Source,
Instance configuration, canonical knowledge or Original.

S03 acceptance is a dependency. Its [current automatic CPU finding](https://github.com/gabned/provelume/pull/429#issuecomment-6556735101)
blocks integration; preparing this candidate does not accept either stage.
The maintainer [deferred manual S03/S04 observations to integrated qualification](https://github.com/gabned/provelume/pull/429#issuecomment-6556457115).
They remain NOT_RUN. A Windows CI runner does not attest Windows11 Home/Pro25H2.

## Closed build and delivery

`packaging/ocr/windows-py312-x64.json` selects CPython3.12.10 x64, the exact
Windows Pillow13.0.0 and pypdfium2 5.13.0 wheels, PDFium153.0.7999.0, the accepted
eng/ita traineddata bytes and the exact vcpkg source revision. Tesseract5.5.3 and
its dependencies build from hash-checked source with static libraries/runtime;
no nested upstream installer, training tools, osd/detection or binary cache is used.
The upstream installer acquired during research is not redistributed by this kit.

An isolated build environment freezes a dedicated console `ProvelumeOcrWorker.exe`.
It retains distribution metadata, renderer DLLs, the Python patch and licenses.
It executes the existing bounded renderer protocol directly. The GUI executable
is never used as a generic Python interpreter. The base installer environment
does not acquire Pillow, PDFium, Tesseract or traineddata through this build.

The composer verifies actual frozen worker/build identity, exact component probes,
all AMD64 native files and imported/delay-imported DLL resolution. System API
imports are classified separately and resolved only through Windows' system
directories, with the actual system-file identity and OS build recorded; an
unresolved application DLL fails the build. [Microsoft documents XmlLite as part
of Windows and forbids redistributing its DLL](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ee388577(v=vs.85)).
Every distributed file has a package-relative path, length and SHA256. Native
source package versions, patches/source archives, notices and vcpkg SPDX records
remain attached; Python/wheel/license files and a kit CycloneDX inventory are retained.
The pinned vcpkg manifests omit a license expression for Leptonica/libarchive;
version-bound upstream evidence supplies those fields. Its exact copyright files
and libarchive's file-specific BSD notices are fetched by immutable commit and
byte digest, retained beside the original vcpkg copyright, and listed in the kit.

The release pipeline builds the optional asset from its own exact candidate wheel,
tests it against its own unchanged Setup, then includes the ZIP, producer/installed
reports and OCR component/native inventory in the same release manifest/checksums
and SBOM. The outer installation kit carries those unchanged release bytes. This
adds no second publisher, runtime download or release event. Nothing is published
by PR/main CI; the application version remains0.14.0 during this campaign.

## Explicit offline lifecycle

The engine payload includes the exact upstream `tessdata/configs/tsv` bytes.
The existing adapter selects that named output configuration. A zero exit code
without this file can leave only plain text and no TSV; the kit requires the
configuration before activation and treats its loss as an unavailable engine.

The frozen operator interface writes a new JSON result outside the Instance/kit:

```text
Provelume.exe --ocr-result-file RESULT.json --ocr-command kit-import KIT.zip --receipt publication-receipt.json
Provelume.exe --ocr-result-file STATUS.json --ocr-command kit-status
Provelume.exe --ocr-result-file REMOVE.json --ocr-command kit-remove
```

The receipt route requires the matching official embedded build and exact asset
identity. An advanced operator or isolated qualification harness can instead
provide `--expected-sha256` obtained independently from the trusted producer/release
record. Never derive that authority from the incoming archive's own manifest.
`--development` additionally refuses an official build; it cannot override that
boundary. A checksum proves selected bytes, not publisher authentication. Import
does not confer publication readiness or create a publication receipt.

The content-addressed host location is `%LOCALAPPDATA%/Provelume/ocr/kits/SHA256`,
outside program files, preferences and Instances. Safe relative ZIP names, duplicate
keys/names, Windows device/ADS names, symlinks/reparse ancestors, file counts and
byte limits are checked before activation. Extraction goes to private staging;
the full exact inventory is verified before replacing the active pointer atomically.
Required Python/PDFium/Pillow native payloads, SBOM and component notices must be
present even when an incoming manifest is self-consistently incomplete. Embedded
app source/version/channel/tag/official identity must match, as must the actual
Python DLL bytes in the frozen program and kit, not just the Python version string.
Updates retain prior kit directories. Explicit reimport of independently selected
bytes quarantines a damaged owned tree and restores it; the damaged bytes are kept
for diagnosis. Removal verifies ownership/integrity and deletes only the active
kit tree. It never removes shared engines, prior kits or Instance data.

Frozen Windows OCR uses only that verified kit, with absolute engine/pack/worker
paths. There is no PATH/system-Python fallback. Disabled mode never probes it.
Missing engine, packs, renderer or runtime yields an unavailable capability without
executing unverified bytes. The complete material digest enters the renderer
adapter version, binding page/document derivations and queued capability snapshots.
Existing stale-material checks remain authoritative. Source/Linux external-component
behavior remains available through its existing explicit settings.

## Qualification and limits

Local tests cover trusted-identity selection, unsafe archives, missing/altered
components, failed imports preserving the active pointer, repair/removal, disabled
no-probe behavior and direct frozen dispatch. Full native/release checks and exact
candidate CI remain mandatory; results belong in the owner PR, not this procedure.

The permanent Windows workflow installs an actual unsigned development package,
imports the exact producer-identified kit, leaves OCR disabled until the synthetic
fixture explicitly enables it, and executes eng/ita PNG/JPEG/BMP/TIFF/scanned-PDF
jobs through the installed executable with an empty PATH. It checks reliable-native
PDF skip, corrupt input, missing engine/pack/worker/Python/PDFium, untouched Originals
and canonical knowledge, temporary cleanup and explicit kit removal. Outbound
Windows Firewall rules apply to the three exact executables during qualification.
The disposable runner's profile states are recorded, temporarily enabled and
restored afterward; active rule direction/action/program bindings are checked
before disabled/import/OCR commands. The report records the actual admin context.
It does not claim packet-observation evidence or a general-purpose security sandbox.

Cancellation/deadline cases suspend only a newly owned frozen worker through
NtSuspendProcess, then exercise the real bounded parent termination/cleanup path.
The report distinguishes those injected faults from ordinary OCR and records
owned process IDs and absence after cleanup. No personal process is a fixture.

Manual Home/Pro25H2, human accessibility and integrated setup/upgrade cases stay
NOT_RUN until performed on their exact integrated candidate. Linguistic/semantic
OCR quality beyond this synthetic printed corpus remains UNVERIFIED. #381 stays
open; no trigger/backlog acceptance follows from provisioning.
