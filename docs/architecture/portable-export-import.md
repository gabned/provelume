# Portable export/import and cross-platform transfer

Status: active product contract for `0.6/S05` under issue #95. Package and embedded release
identity remain `0.5.1` until the separate `0.6.0` release-preparation change.

## Portable bundle

`provelume export INSTANCE --output PATH` creates a ZIP outside the Instance root:

```text
portable-manifest.json
instance/
  provelume.yml
  instance-manifest.json
  originals/...
  knowledge/...
  state/...
  inbox/submissions/...
  indexes/...                 # only with --derived-state include
  library/...                 # only with --derived-state include
```

The manifest is canonical readable JSON. It binds the stable Instance ID, Instance schema,
canonical/Original content fingerprint, exact derived-state policy, payload totals and a sorted
category/path/size/SHA-256 row for every file. The `export_id` is the SHA-256 identity of those
stable fields. ZIP member order, timestamps, modes and compression settings are fixed; there is no
wall-clock field inside the bundle. Two exports of unchanged Instance bytes under the same policy
are therefore byte-identical. The completion time is returned to the caller but is not embedded in
the portable artifact.

The default `--derived-state rebuild` mode follows the Instance manifest: retained state artifacts
are included, while `indexes/` and `library/` are declared for rebuild after import. The explicit
`include` mode carries their current verified bytes instead. Transient `state/locks/` content is
never transferable. `include` requires both the current index and library manifests to be ready;
import validates those included views again in staging before the swap.

The allowlist prevents an export from sweeping arbitrary files merely because they are below the
Instance directory. Canonical JSON, acquired Originals, retained `state/` evidence and retained
Inbox submission evidence are portable. Configured Source, Drop and managed-copy content is not
copied unless already acquired into the authoritative Original store. Absolute external path
configuration may remain descriptive configuration, but the referenced external bytes remain a
machine-local dependency and are outside the bundle claim.

## Validation before import

`verify_portable_bundle` and import complete all structural and byte verification before changing
the target Instance. Validation rejects:

- missing, duplicate, non-canonical or unsupported manifest fields and ZIP members;
- undeclared, unordered, encrypted, directory, symlink or other special members;
- traversal, absolute POSIX paths, drive-qualified paths and backslash aliases;
- non-NFC Unicode, control characters, Windows-forbidden characters, trailing dot/space segments
  and reserved device names such as `CON`, `NUL`, `COM1` or `LPT1`;
- exact, case-insensitive, Unicode-normalized and file/directory path collisions;
- missing payloads, size/hash mismatches, archive changes during validation/extraction and bounded
  entry/file/total expansion violations;
- a staged Instance whose ID, schema, canonical references, Original bytes or deep content
  fingerprint do not match the manifest.

Paths are logical POSIX-relative names in the artifact and are materialized beneath a newly created
sibling staging directory. No archive-provided path is passed directly to the host filesystem.

## Transactional cross-Instance import

`provelume import TARGET BUNDLE` replaces an existing valid target Instance. Requiring an existing
target gives every import a concrete rollback identity; initialize a new empty target first when
moving to a new directory.

The transaction:

1. prepares and deeply validates the target, then validates the complete portable bundle;
2. acquires the cross-platform lifecycle OS lock;
3. creates and independently verifies a full pre-import target backup;
4. records external pending-operation evidence bound to the bundle SHA-256;
5. extracts and deeply validates off to the side, applying the registered N-1 to N migration when
   required;
6. rebuilds the search index and Markdown library in staging for `rebuild`, or retains their
   manifested bytes for `include`;
7. writes a privacy-bounded import receipt and atomically swaps the staged directory on the same
   filesystem;
8. deeply validates the installed ID, Originals and content fingerprint before clearing pending
   evidence.

An ordinary failure restores the exact previous directory or its verified backup. If the process
ends while an import is pending, the next open acquires the same lifecycle lock and restores the
verified pre-import backup before normal preparation. Recovery is explicit under
`state/lifecycle/recovery-receipts/`; successful import evidence is under
`state/lifecycle/import-receipts/`. The retained rollback archive remains in the sibling lifecycle
control directory.

Import intentionally preserves the exported Instance identity, acquired Original bytes, Versions,
provenance, hierarchy IDs, classifications, dispositions and associations. It replaces rather than
merges the target; multi-master synchronization and conflict resolution are outside this contract.

## Local authority and qualification

The same application-service authority is exposed by `export_portable()` and `import_portable()`.
There is no HTTP upload, export or import mutation route. Export, verification, import, migration
and derived rebuild use local files only and report `network_used: false` and `ai_used: false`.

Regression qualification covers deterministic repeated export, schema N-1 preparation,
Windows/Linux-safe path rules, include/rebuild modes, complete authoritative round trips, CLI and
service parity, hostile/partial bundles, injected commit failure, verified rollback and interrupted
import recovery. This is format and behavior qualification, not a claim that configured external
Sources, backups, replicas or unacquired working-folder files moved with the Instance.
