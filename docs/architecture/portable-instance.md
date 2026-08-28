# Portable Instance format (schema 2)

A Provelume Instance is an ordinary directory. Schema 2 uses:

```text
<instance>/
  provelume.yml
  instance-manifest.json
  originals/
    sha256/
  knowledge/
    sources/
    acquisitions/
    originals/
    documents/
    versions/
    provenance/
  state/
    lifecycle/
    migrations/
    derived/
  indexes/
```

`provelume.yml` contains stable Instance identity, the current Instance schema, local UI/network
defaults and operator Source bindings. `instance-manifest.json` repeats the stable identity and
binds it to manifest schema 1, Instance schema 2 and this closed derived-state policy:

```json
{
  "indexes": "rebuild",
  "library": "rebuild",
  "state_artifacts": "include"
}
```

Source paths are written relative to the Instance directory when the platform permits it; an
operator may explicitly configure an absolute path elsewhere on the local filesystem. Canonical
objects never require a Git remote.

`originals/` and `knowledge/` are authoritative. Retained artifacts under `state/`, including
ingestion/operation evidence, document bundles, migration receipts and recovery receipts, are
included in a local backup. `indexes/` and the future `library/` projection are excluded and rebuilt
from retained state. Secrets must not be stored in versionable configuration.

Path locators use `/` as the logical separator even on Windows. Absolute locators and `..` traversal are rejected before they are used as Instance-relative references.

## Read-only validation

`provelume validate INSTANCE` checks the configuration, manifest, canonical JSON references and
every retained Original hash/size. It performs no migration, repair, index rebuild or network
request. `--fast` validates identity and schema contracts without reading every Original byte.

Schema 1 is reported as valid but `migration_required: true` when its identity and canonical state
pass inspection. An unknown future schema or an older schema with no registered migration fails
closed before a backup or write.

## Forward-only schema migration

Opening a valid schema-1 Instance, or running `provelume migrate INSTANCE`, performs the single
registered `instance-schema-1-to-2` transition:

1. deep preflight verifies canonical references and Original bytes;
2. a same-Instance backup is built and independently re-read/hash-verified;
3. an external pending-operation marker records the rollback archive;
4. `provelume.yml`, the migration receipt and `instance-manifest.json` are installed atomically per
   file;
5. the complete schema-2 Instance is validated before the marker is removed.

The migration does not rewrite canonical JSON or acquired Original bytes. Its receipt records the
old/new schema, preflight content fingerprint and exact backup archive digest. Migrations only move
forward; there is no in-place downgrade path.

## Backup contract

`provelume backup INSTANCE [--output PATH]` writes a ZIP outside the Instance root. Its
`backup-manifest.json` binds the stable Instance ID, source schema, content fingerprint, explicit
include/rebuild policy and a sorted path/size/SHA-256 entry for every payload file. Verification
rejects undeclared/duplicate entries, encryption, symlinks, traversal, case-insensitive collisions,
hash/size mismatches and bounded expansion violations. Before success is reported, Provelume repeats
deep validation and the complete payload inventory; any retained canonical, Original, configuration
or state change during construction invalidates and removes the archive. This gives the backup a
write-consistent snapshot boundary without silently omitting a concurrently committed acquisition.

The default location is a sibling control directory:

```text
<parent>/.<instance-name>.provelume/backups/<backup-id>.zip
```

Canonical JSON, acquired Originals and retained `state/` artifacts are included. `indexes/`,
`library/` and `state/locks/` are excluded. Configured Source, Drop or managed-copy directories
outside the Instance are never copied; unacquired files waiting there are outside this backup's
claim.

## Restore, rollback and crash recovery

`provelume restore INSTANCE ARCHIVE` is a same-Instance operation, not cross-Instance import. It
fully validates the requested archive before mutation, creates and verifies a fresh backup of the
current Instance, extracts into a sibling staging directory, validates the staged Instance and
replaces the live directory on the same filesystem. Failure restores the verified pre-restore
backup. A schema-1 backup is migrated to schema 2 inside the same restore transaction.

The sibling control directory keeps the pending marker and lifecycle lock outside the directory
being replaced. The persistent lock metadata file is guarded by an OS advisory lock, so process
termination releases ownership in the kernel and contenders never delete/reclaim a pathname that a
new owner may already hold. Pending recovery acquires that same lock before changing the Instance.
After an interrupted migration or restore, the next open verifies and restores the recorded
pre-operation backup before retrying normal preparation. Recovery is persisted under
`state/lifecycle/recovery-receipts/`; it is not silently treated as an ordinary successful open.
Abandoned staging/previous directories are removed only after the rollback archive has been
verified and installed.

These local backups are not the portable cross-Instance export/import contract. Hash-manifested
cross-platform transfer, hostile-import qualification and explicit derived-state export options
remain `0.6/S05`.
