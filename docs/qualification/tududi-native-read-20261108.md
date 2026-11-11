# Tududi native read observation — 8 November 2026

Owner: integrated S23 [#460](https://github.com/gabned/provelume/pull/460).
This supplements the closed synthetic mapping matrix. It does not accept S14,
S23, a real account or the complete provider matrix. Decision L still defers
public write-back from 0.15.0; no provider write-back capability is qualified.

## Inputs and observed scope

The upstream stable 2.1.0 source is
`chrisvel/tududi@e03bc361bc7fa49a475fca9952b345822d1d5f11`.
The independently selected Linux amd64 image manifest is
`chrisvel/tududi@sha256:0787ac438d460d89e669cdae5ab2b205c7a6424c98fba50bf1209623c50cf3ee`,
local image ID
`sha256:6ebc9f0750e99916f1c604126cb66ceadb37f66d4272d8f94ac27a9c385787a1`.
PostgreSQL is a fresh synthetic fixture database, pinned to
`postgres@sha256:ac838714b7d794185a866e5a6b479b954e7d8a070568aa0acac6fe07c3070bf5`.
Neither image is an application distribution component.

An original complete tracked-file comparison failed: 327 upstream docs/tests are
absent from the image and package-lock root version fields changed from 2.0.0 to
2.1.0. That FAIL remains. A separately declared runtime scope found 837 runtime
files byte-identical to Git blobs. Structural lock comparison found only the two
root version changes, with the dependency graph/integrities unchanged. Image
signature verification and dependency-binary reproducibility remain NOT_VERIFIED.
Do not call the entire image/source identical or reproducible.

On exact Core `afda36c9c0ba5a5e9ee4ecc1c44d5c34b4c70f3e`, an external prototype
passed two actual isolated endpoints/accounts, project catalogue and selection,
native HTTPS acquisition and replay, one Version per task, upstream synthetic
token revocation yielding HTTP401, local revocation retaining imported records,
Instance token scans and offline portable import. Its real `ProductivityHttp`
workers used verified TLS and private test certificates; native SecretService
stored grants outside the Instance. This is actual local upstream API execution,
separate from synthetic wire responses and from a hosted personal account.

The first fixture preparation failed after temporary PostgreSQL socket readiness;
the next preparation required TCP readiness. Subsequent preparations failed before
tokens during migration. Keeping pids32/memory256MiB, Node's private fixture
environment reduced its internal thread pools; two servers then prepared and the
product journey passed. Earlier incomplete observations remain FAIL/UNKNOWN;
they are not provider or Core successes. No native or Public CI limits increased.

## Reproduction and limits

`scripts/qualify_tududi_native.py --directory <fresh-ignored-directory>
--allow-synthetic-fixtures` contains the reviewable local driver. Run with the
checkout's own declared Python and an unlocked native OS vault in a private
session. Both pinned images must already exist locally. The final receipt binds
the clean Git commit/tree; changed driver/source needs new execution.

The driver creates an internal Docker network, two fresh apps/databases, private
synthetic accounts and tokens. No Docker port is published. Loopback TLS proxies
only connect each app to its own actual read APIs. App containers are read-only,
non-root, cap-drop ALL, pids32 and memory256MiB; the database has separate bounded
tmpfs storage. Node thread pools are fixture preparation settings, not Core
performance measurements. Credentials are never printed or archived. Cleanup
checks the unique owner label before removing its own containers/network.

Only GET requests cross the product-facing proxy. Creating fixture data/tokens and
revoking those tokens occur through an explicit driver inside the fresh upstream
server; these are not public task write-back tests. Real accounts, native Windows
vault/transport, full pagination/date/subtask/comment fault matrices and actual
server signature/dependency attestations are not established by this small native
journey. Their other evidence and unresolved gates remain separate. All human
checks remain DEFERRED_BY_MAINTAINER / NOT_RUN.

Retain only receipts, source-input observations, driver and closed logs. Exclude
Instance directories, keyrings, private TLS keys, browser profiles and containers
from evidence archives. Receipt export does not grant account or server authority.
