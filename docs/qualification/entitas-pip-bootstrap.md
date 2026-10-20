# Entitas online installer toolchain

This PRODUCT workstream is coordinated under
[#402](https://github.com/gabned/provelume/issues/402). It extends the existing
0.14 dependency inventory only for an observed bootstrap gap.

The Windows CPU job `118314278564` on source
`c7868cbf50eeecc7e813c2e81475c33dcc4fe4c1` reported pip 25.0.1 while installing
development dependencies. The version used by a different job is not inferred
from that observation. `scripts/bootstrap.py` previously retained the version
seeded by `venv`; direct workflow installs and the private Windows builder also
did not establish a corrected installer before installing dependencies.

All online installs used by this campaign now first install the already reviewed
pip 26.2 wheel from `build-lock/sbom-runtime-pip.requirements.txt`, with SHA256
`931c303696af6fa3417112103b1cad26890e5a07eccb5b99783700e33f2b8aad`.
Only a wheel is accepted, its hash is required, and failure stops before the
subsequent dependency install. The existing container and SBOM runtime already
used this pin. No package resolution, Windows dependency lock, native component,
historical pytest compatibility input or canonical Protocol vendor is updated.

| Component and manifest/scope | Official advisory | Affected / corrected | Observed applicability and action |
| --- | --- | --- | --- |
| pip 25.0.1, Windows development bootstrap; unpinned online installers in workflow/build scripts | [GHSA-6vgw-5pg2-w6jp](https://github.com/advisories/GHSA-6vgw-5pg2-w6jp), CVE-2026-1703 | <26.0 / 26.0 | APPLICABILE: affected installer consumes online wheels; no exploitation observed. Establish reviewed 26.2 before dependency installation. |
| Same installer and online package inputs | [GHSA-58qw-9mgm-455v](https://github.com/advisories/GHSA-58qw-9mgm-455v), CVE-2026-3219 | <=26.0.1 / 26.1 | APPLICABILE: affected version accepts archive inputs. Same correction. |
| Same installer and post-install version checks | [GHSA-jp4c-xjxw-mgf9](https://github.com/advisories/GHSA-jp4c-xjxw-mgf9), CVE-2026-6357 | <26.1 / 26.1 | APPLICABILE: existing online install did not disable the version check. Same correction and explicit version-check suppression. |
| Same installer and wheel entry points | [GHSA-wf93-45jw-7689](https://github.com/advisories/GHSA-wf93-45jw-7689), CVE-2026-8643 | <26.1.2 / 26.1.2 | APPLICABILE: online wheels may contain entry-point metadata. Same correction. |
| pip URL handling in online acquisition | [GHSA-qwm4-qh6w-59xr](https://github.com/advisories/GHSA-qwm4-qh6w-59xr), CVE-2026-13346 | <26.2 / 26.2 | DA_VERIFICARE for the malicious-index precondition; it was not observed. Establish 26.2 before the existing online download/install operations. |
| pip tar extraction fallback on the observed Python 3.12 hosts | [GHSA-4xh5-x5gv-qwph](https://github.com/advisories/GHSA-4xh5-x5gv-qwph), CVE-2025-8869 | <=25.2 / 25.3 | NON_APPLICABILE to the reported fallback because Python 3.12 provides the PEP 706 API. This does not establish the security of every CPython tar filter. |
| pip 26.2, existing pinned runtime/container and corrected online bootstrap | Same six advisories | 26.2 is outside the six affected ranges | NON_APPLICABILE by version for these advisories only. Actual remote installation and the final distributed SBOM still require fresh observation. |
| Seed pip in isolated release offline build/rebuild environments | Same advisories where their versions are affected | Actual seed version must be read from its original evidence | NON_APPLICABILE to malicious package/index preconditions in the observed operation: only the complete reviewed local wheelhouse is installed with `--no-index` and required hashes. The pin change does not expand those offline inputs or claim a corrected seed version. |

The one pinned bootstrap wheel is an independently reviewed byte input; the seed
installer is not asked to resolve arbitrary packages during its own correction.
The dedicated future lock-refresh workflow is outside this release's execution
and is not run or broadened here.

Protected advisory API accessibility and scanner closure remain UNOBSERVED.
This bounded assessment is not a general security verdict. Fresh native checks,
the exact-head workflow results and the read-only release chain remain required
before acceptance.
