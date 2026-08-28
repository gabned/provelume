# Security policy

Provelume handles private knowledge and source material, so security and provenance failures are
treated as product-critical issues.

## Supported preview policy

Provelume is pre-1.0. Security corrections are considered for the latest published preview line.
Older previews, forecasts and unreleased branches are not supported security targets; reporters
should reproduce a finding against the latest public preview when that can be done safely. A fix
may ship as a patch preview or in the next preview, according to severity, compatibility and the
verified release gate. This policy does not promise a response or publication deadline.

Preview Windows installers are currently unsigned. Release checksums, manifests, attestations and
offline verification evidence strengthen integrity and traceability but do not substitute for
independent publisher authentication. Authenticode and the safe updater remain forecast work.

## Local serving boundary

The packaged Knowledge Browser is a single-user, local application. `provelume serve` accepts only
explicit loopback bind targets and rejects non-local Host values. It does not provide account,
multi-user authorization, LAN or Internet exposure. Publishing it through a reverse proxy,
container port mapping, tunnel or firewall exception is outside the supported preview boundary.

Core knowledge processing remains useful offline. A user-invoked update check is a separate,
visible network action; installation and release verification can be performed from local
evidence. See `docs/privacy-network.md` for the declared network contract.

## Reporting a vulnerability

Do not publish exploitable vulnerabilities, credentials, private source content, local paths or
personal knowledge in a public issue, pull request, test fixture or log.

When GitHub reports private vulnerability reporting as enabled for this repository, use the
repository Security tab. Until then, use the private security/contact channel published on
https://provelume.com. Repository setting work, including private vulnerability reporting, is
tracked by issue #1 and must not be claimed complete from repository code alone.

Include, when safe:

- affected Provelume version, platform and installation type;
- a minimal synthetic reproduction and expected impact;
- whether loopback-only serving, update checks or release verification are involved;
- installer or release-asset SHA-256 when the finding concerns distribution;
- confirmation that the report contains no private Instance material.

The stable support and disclosure policy will be finalized before `1.0.0`.
