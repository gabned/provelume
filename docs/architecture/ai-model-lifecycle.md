# Custodia model registry and lifecycle

[S04 #318](https://github.com/gabned/provelume/issues/318) belongs to parent
[#311](https://github.com/gabned/provelume/issues/311), after completed S01 #312/#313,
S02 #314/#315 and S03 #316/#317. Application/package/public preview remains 0.11.0 — Cura.
S04 is integrated through #319 with exact-head and actual-main qualification. S05 #320/#321
adds the [one-candidate extension](ai-local-runtime.md); S06 owns dispatch enforcement; S07 owns complete
user surfaces. This internal lifecycle creates no inference, resolver, scheduler or budget engine.

## Current 0.12 recommendation

The S04 sections below retain the original synthetic-only contract and historical
scope. Provelume 0.12 ships a [bounded local recommendation](../qualification/custodia-local-profile.md)
for the exact Qwen3.5-2B Q5_K_M, runtime lock and execution configuration qualified
through S08/S09. `recommended_scope` is descriptive distribution evidence for
EN/IT extractive summary/key points, not per-device compatibility, local-network
proof or authorization to execute. Synthetic entries remain synthetic; retired
models remain blocked/removable. Every current application/model registry entry
matches the 0.12 package identity. Fresh consent/session checks remain mandatory.

## Provenance

`model_registry.json` is governed and distributed with application code. Its expected SHA-256
is pinned in `ai_models.py` under ordinary reviewed application distribution gates.
`ModelRegistry` accepts only those exact bytes. `parse_manifest` validates structure without
granting trust. A download, offline ZIP or companion checksum cannot change approved digests,
licenses, origins or compatibility. A hash supplied with an untrusted file proves consistency
at most. This is not a signing service or protection against compromised application code.

Two tiny fixtures are reproducible from `tests/ai_model_fixtures.py`. They contain inert CC0-1.0
synthetic data, not learned weights. Reserved `fixtures.invalid` URLs are not production model
sources; tests inject controlled transports. No live model/provider download, inference,
credential or existing LAN service is used or qualified.

## Closed compatibility matrix

| Dimension | Admitted S04 values and meaning |
| --- | --- |
| Application | Provelume 0.11.0, separate from runtime/model versions |
| Runtime | `provelume.synthetic-fixture`, version `1`; trusted host callback interface only |
| Payload | `synthetic-bytes-v1`; exact inert bytes, size and digest |
| Package | ZIP STORED, exactly `model.bin` and `LICENSE.txt`; no filesystem extraction |
| Model | `fixture.model-v1`/`fixture.model-v2`, versions `1`/`2`, separate archive/model digests |
| Channel | `candidate` or `stable`, metadata only; shipped fixtures are candidate |
| Qualification | `SYNTHETIC_ONLY`; never offline-qualified, Recommended or inference-authorized |
| Platform | Native Linux and Windows local filesystems, subject to exact-head qualification |
| Configuration | Exact versioned `lifecycle-self-test-only` record |
| Real GGUF | Only the exact S05 candidate tuple in ADR 0031; streamed raw import, no ZIP extraction |
| ONNX, safetensors, pickle, scripts and executable runtime packages | Unsupported |
| Advanced BYOM | `UNSUPPORTED_NO_QUALIFIED_RUNTIME`; no guessed compatibility before S05 |

Unknown/duplicate fields and unsupported combinations fail closed. Stable metadata is not
qualification. Registry presence, installation, verification, self-test and internal activation
are different states. The existing S01 `Profile` carries model/runtime fingerprints. S04 creates
no `LocalityEvidence` or inference receipt and does not alter the gateway, resolver, context,
redaction, templates, consent/binding checks or product-disabled status.

## Operations, storage and byte safety

`install`, `update` and `import_offline` require explicit requests and exact license acceptance.
The importer reads an explicitly selected absolute local file through existing pinned-parent
and file-handle primitives. Chunks are written/fsynced to staging; exact archive, members,
sizes, digests and license bytes are then verified. Only verified bytes are published under
`verified/<archive-sha256>.pkg`. Installation never moves the active selection.

Limits: 128 KiB archive, two members, 64 KiB per file, 96 KiB total member bytes, eight installed
packages and eight staging entries. The reviewed registry has a separate nine-entry
bound so retired identities remain removable without increasing installed storage.
Compression, encryption, unknown/duplicate/colliding names,
extra ZIP metadata, directories, link modes, absolute/traversal/ADS/reserved names are refused.
Source hardlinks, symlinks and Windows reparse points, including parent components, are refused.
Identities are checked around bounded reads. Members become immutable byte snapshots, never
paths reopened by runtime consumers. No pickle, executable deserialization, hook, script,
dynamic import, tokenizer or package-supplied runner exists.

One exclusive OS lock reuses the Instance lifecycle primitive across processes and covers
admission, staging, publication, self-test, selection, removal and internal-use leases.
Contention returns busy without retry. Process exit releases the OS lock; lock-file existence
is not a held-lock claim. Admission checks one MiB reserve plus two archive copies and rechecks
space during writes. This is not a reservation against unrelated filesystem writers.

The service uses the existing external control sibling
`.<instance-name>.provelume/ai-models/`. Construction is pure. No model data or installation
authority enters canonical Instance configuration, Originals, knowledge or jobs. Archives,
staging, writer temporaries and selection hints stay outside Instance backup/export and the
storage directory writes its own `*` Git exclusion on explicit use, including when an
Instance is placed inside a working tree. This cannot prevent an explicit forced Git add.
Restore on a new host requires explicit acquisition
and verification; a hint cannot recreate installed/qualified state. Reusing existing external
bytes still requires current integrity/compatibility and fresh session self-test evidence.

`ComponentInventory.model_registry` and `ProvelumeInstance.ai_model_registry` provide the
minimal internal Components, models & licenses projection, using existing category, identity,
license and unverified-state conventions. `ai_model_lifecycle` is the explicit service factory.
There is no new public API/CLI/UI install or inference bypass; complete surfaces remain S07.
Diagnostics contain closed codes/fingerprints, never contents, secrets, local paths or underlying
exception strings. No secret input is accepted by manifests, configuration or receipts.

## Acquisition network boundary

`ArtifactDownload` implements a separate one-shot artifact GET, not S03's inference protocol.
It reuses guarded-web URL/public-IP and numeric socket primitives without weakening web-intake
SSRF. Only the governed HTTPS URL/origin and port 443 are admitted, with no userinfo, query,
fragment or ambiguous escaping. Every bounded DNS answer must be public; one numeric target is
pinned. Peer address/port are checked before and after verified TLS with hostname validation.
Redirects/non-200, proxies, authentication, netrc and environment destinations are refused/unused.

Exact Content-Length and application/zip are required; transfer/content encoding is refused.
Headers are limited to 16 KiB/32 fields before accumulation, chunks to 4096 bytes and body to
the manifest size. The operation deadline is 30 seconds; socket waits are at most two seconds.
Cancellation is checked at bounded I/O checkpoints. DNS has one bounded worker slot; timed-out
OS resolution may finish later while the slot remains occupied. Constructor/start failures
release it. No retry, redirect, replay or promise to terminate OS DNS is made. Injected host
transports must honor the deadline/cancellation contract; arbitrary host callbacks are trusted
code and cannot be forcibly stopped by this interface.

Import/startup/settings/status/preflight perform no network. `discover(requested=True)` is an
opt-in local comparison against the shipped registry; there is no remote update feed. Registry
updates follow ordinary application distribution gates. Discovery never grants install consent.

## Self-test, activation and recovery

Self-test receives exact verified immutable bytes, runtime/platform/configuration and a trusted
host runner. PASSED, FAILED and UNKNOWN are explicit. Only PASSED creates an in-memory evidence
object bound to model/archive hashes, runtime/configuration, registry, current admitted IDs and
manager session; it expires 60 seconds after test start. Failure, unknown, error, forged/copied
evidence, restart, expiry, changed bytes/configuration/admission blocks activation and use.
The 30-second self-test budget is checked on return; real process isolation belongs to S05.

Activation rechecks integrity/compatibility and writes `active`/`previous` IDs only. These are
recovery hints, not durable qualification. A fresh manager needs a new self-test. The product
execution seam remains disabled until S06 regardless of installed or internally active bytes.
Failed/cancelled/incomplete/corrupt updates preserve the previous selection and valid package.
Explicit recovery removes only bounded recognized staging/writer temporary files and invalidates
ephemeral evidence; it never activates orphaned verified files. Rollback rechecks the prior
successful activation's bytes, current admission and compatibility and requires a fresh self-test.
It cannot bypass revocation. Active or leased packages cannot be removed; deactivate explicitly.
Missing/corrupt selections or packages fail closed.

Verified publication and selection use pinned-parent same-directory replacement in separate
steps. Interruption can leave a verified inactive orphan. There is no cross-filesystem
transaction or power-loss durability guarantee for directory entries. Network filesystems are
not qualified; network path syntax is refused, but POSIX mount types are not detected.
Cooperative locks do not protect against already compromised same-account host code;
every use still verifies bytes and passes immutable snapshots instead of reopened paths.

## Executable proof

```text
.venv/Scripts/python.exe -m pytest -q tests/test_ai_models.py::test_executable_s04_demonstration
```

Use `.venv/bin/python` on Linux. The demonstration performs a real tiny offline import,
verification/self-test/internal activation, rejects a hostile update, preserves valid bytes,
updates and rolls back, removes under control and proves product dispatch disabled. Native
full Ruff/pytest, diff checks, exact-head Linux/Windows CI and all ownership/policy/effects/
review/ancestry gates remain required. The owner ledger retains actual failures and post-merge
results. Fixture success does not qualify a real runtime. Live smoke is NOT_RUN; Lifecycle v2
is DEFERRED_BY_MAINTAINER. Recommended and performance remain S05/S09.
