# ADR 0029: Actual publication receipt and recoverable installation kit

Status: accepted for Cura S02 PRODUCT implementation (#258, #217).

## Context

The Preview About NEW indicator describes the first 24 hours after actual release publication.
Source, build, assembly, installation and first-visit timestamps cannot supply that fact.
Actual publication happens after qualification, so inserting its timestamp into a qualified wheel
or Setup would change the artifact being released. Runtime metadata must also work offline.

## Decision

Keep the qualified core bundle byte-for-byte unchanged. All payloads, manifests, checksums,
assurance evidence and SBOM are complete and verified before the public release event. The existing
provenance attestations still cover those original bytes. Publication then has two explicit phases:

1. Publish the qualified payloads, or resume their interrupted upload without replacing an asset.
   Observe the public release's actual `published_at`, release identity and exact resolved tag commit.
   Download and compare every public core file with the qualified original. Produce the closed
   `publication-receipt.json`, binding the event to version/tag/commit/channel, manifest and file
   hashes. `observed_at` describes the observation only.
2. Wrap the unchanged `release/` directory with `publication/publication-receipt.json` in a
   deterministic `provelume-VERSION-installation-kit.zip`. This is an installation envelope, not a
   new portable Windows distribution. Attest receipt and kit in the public publisher workflow.
   Upload them without overwrite, fetch them and every original core asset again, compare their
   bytes, then publish and re-read `publication-ready.json`. Only this completed observation
   establishes `installation_kit_ready` for that publication.

Before phase 2 completes, a public payload can exist but installation-kit readiness is pending.
Failure remains visible in the workflow result and summary. There is no fallback success marker.
Resume the failed publisher job from the same run's original qualified bundle and exact source;
do not rerun assembly or replace the release. Existing identical assets and receipt bytes are
reused. Missing assets can be uploaded. Conflicting bytes or changed publication identity stop
finalization. The receipt's first `observed_at` is preserved across retries. A readiness marker is
written only after public bytes have been independently read back. A failure after marker upload
but before its observation is retried idempotently; that run remains failed until the observation.

Every publisher observation reads all asset pages within the existing 300-asset bound. The closed
inventory permits only the qualified core file names and the receipt, this version's installation
kit and readiness marker. Extra assets, name aliases or collisions stop before recovery uploads
and before readiness is issued or reported. Missing core files are allowed only while resuming
the initial payload upload; finalization requires the complete core plus receipt and kit, and its
last observation also requires readiness. Existing permitted assets still require byte equality.
If an extra appears after the marker upload, the observation fails and recovery remains pending;
the publisher does not delete foreign assets, overwrite bytes or treat the marker alone as success.

The reusable production implementation is `scripts/publication_publish.py`, with the receipt
producer in `scripts/publication_receipt.py` and deterministic kit in `scripts/release_kit.py`.
The permanent `scripts/publication_dry_run.py` replaces only transport with an explicitly synthetic
filesystem public record. It exercises those same production functions, deliberate interruption,
fresh-stage resume, exact-byte preservation and idempotence without network or credentials.
Its output is never evidence of actual publication or release qualification.

## Installed behavior and delivery

`provelume publication import` reads a matching receipt, original release manifest and original
wheel, sdist or Windows Setup payload. It checks bounded closed metadata, version/tag/commit/channel,
payload size/hash and manifest membership before storing the unchanged receipt outside package
files. Python uses `sys.prefix/share/provelume/publication/VERSION-COMMIT/`; frozen Windows uses
`EXE_DIRECTORY/publication/VERSION-COMMIT/`. An explicit destination and the
`PROVELUME_PUBLICATION_RECEIPT` read override support a separately provisioned location. Existing
different bytes at the selected destination are never overwritten. Symlinks and Windows reparse
components are rejected. Installed wheel RECORD and frozen binaries are unchanged.

The documented official installation path verifies/extracts the outer kit, installs its payload,
then imports the receipt. Windows Setup finds the extracted kit's sibling receipt and imports it
after file installation, before initializing settings; explicit `/PUBLICATIONRECEIPT=...` supports
the updater. Import failure is visible and fails Setup. Raw wheel/sdist/Setup remain verifiable
payloads and can be used separately; by themselves they lack publication metadata. Their users
can add the matching receipt offline using the same explicit import command. Raw Setup alone
does not silently invent a timestamp or silently become a metadata-complete installation.

Windows update manifest schema 2 requires publication readiness. Selection validates the receipt,
ready marker, current public event, exact tag commit and Setup identity. Download retains the
matching raw receipt and manifest beside the verified Setup and passes their location to Setup.
The existing user check/download/apply confirmations and unsigned-preview trust boundary remain.
Historical schema-1 releases remain readable; they carry no publication metadata requirement.

`current_publication()` and About read only local bounded metadata and the current UTC clock.
They report available/missing/invalid/identity_mismatch/clock_unusable, actual publication and
expiry, remaining seconds and NEW eligibility. Eligibility is `published_at <= now < published_at
+ 24 hours`, additionally requiring the clock not precede the known observation. Missing or
unusable evidence suppresses NEW. Receipt contents are descriptive consistency evidence;
`origin_authentication` remains `not_established`. Neither importing a receipt nor comparing
hashes authenticates its publisher or verifies installed executable bytes.

## Consequences and limits

There is no runtime GitHub call, subscription, new dependency or publication-time rebuild.
The core release manifest stays provider independent; the separate event receipt deliberately
identifies its initial GitHub publication provider. The UI handles live countdown and expiry;
its Preview surface is owned by Cura S02 and the integrated native qualification remains S09.
Offline wall clocks cannot prove real time across arbitrary clock changes/restarts. A clock before
the recorded observation is unusable; live UI monotonic expiry prevents a wall-clock rollback from
extending the current page's original deadline. No first-visit timestamp is stored or treated as
publication. Independent provenance verification remains a separate explicit action.

The post-publication envelope is not a second qualification of rebuilt artifacts. It is a
deterministic container of the already qualified payload plus observed event evidence. Future
changes to those bytes require a new publication identity, never a recovery overwrite.
