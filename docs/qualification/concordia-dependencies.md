# Concordia dependency maintenance

Owner: `product/0.15-dependency-security`, PRODUCT / REPOSITORY_POLICY,
PR-local legacy. Baseline: main `674d292428f5f116ef32499f84fb7fcc872e9339`.
The accepted Protocol source remains `02317e02767958faa3de5bb6d245ca3440360d9e`;
Lifecycle v2 remains deferred. Application identity remains 0.14.0 / Entitas
until the separately qualified Concordia release preparation.

Dependabot proposals #434, #425 and #346 supply the upstream dependency changes.
Their protected `ci.yml` portion requires its own PROTOCOL workstream; this
PRODUCT workstream covers the other workflows and the application dependency.
No release, tag, publication, installation or deployment is part of this change.

## PDF security correction

The [pypdf 6.21.4 release](https://github.com/py-pdf/pypdf/releases/tag/6.21.4)
corrects copied-page-attribute limits, EOF handling in cross-reference trailers
and clone-loop detection. Its preceding 6.21.3 release also limits cross-reference
stream entries and validates decrypted page counts. These concern the maintained
PDF reader, which processes supplied documents; Dependabot #434 reports high
severity. This is scoped dependency remediation, not a general security verdict.

The runtime requirement, component catalogue, Windows input, pinned wheel and
maintained Windows resolver all select at least 6.21.4 within the existing major.
The universal wheel was downloaded from PyPI and SHA-256 verified as
`33e4fb41ca352810eb4e9838aa0d82d6888a5f8bf682f43e99cce5faa666255c`.
The resolver's existing replacement routine preserves every other pin and hash.
The permanent native Windows workflow resolves the complete selected environment
and now compares its proposal with the committed lock. Its actual exact-head run
is required evidence; a local Linux wheel check does not establish Windows PASS.
The component inventory regression rejects 6.21.2 and 6.21.3 while keeping the
security-status field unverified and making no network request or automatic update.

## CI dependencies

Official immutable pins select setup-python 7.1.0
(`6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`) and upload-artifact 7.0.2
(`cf430e030ddbb5b0abf93d22962f4752f3646cd9`). Both old and new action versions
use Node 24. No workflow uses setup-python's removed `pip-install` input.
Upload retains its default ZIP archive behavior, names, retention, hidden-file
choices and permissions, preserving existing download-artifact/CLI consumers.
The Windows shell assurance assertion follows the reviewed upload pin.

## Qualification boundaries

Run the existing PDF hostile-input/extraction tests, component inventory,
Windows lock and shell assertions, then complete native Ruff and pytest and
`git diff --check` on unchanged source. The permanent release dry run and offline
verifier remain required for this release-chain change. Retain complete remote
run/attempt/job histories and current reviews/threads in the owner PR, then verify
actual-main post-merge checks. No candidate or post-merge PASS is asserted here
before those observations. Historical release evidence remains at its original
revision and scope.
