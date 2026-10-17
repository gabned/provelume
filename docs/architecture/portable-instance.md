# Portable Instance format (schema 3)

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
    hierarchy/
    classifications/
  state/
    lifecycle/
    migrations/
    derived/
  indexes/
  library/
```

`provelume.yml` contains stable Instance identity, the current Instance schema, local UI/network
defaults and operator Source bindings. `instance-manifest.json` repeats the stable identity and
binds it to manifest schema 1, Instance schema 3 and this closed derived-state policy:

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
included in a local backup. `indexes/` and the implemented `library/` projection are excluded and
rebuilt from canonical state, verified Originals and retained deterministic bundles. Secrets must
not be stored in versionable configuration.

`knowledge/hierarchy/` and `knowledge/classifications/` are additive schema-2 canonical
containers. An Instance created by an earlier schema-2 Core may omit them while empty; the first
hierarchy/classification mutation creates the required container without changing the Instance
schema. Present records are validated, fingerprinted and backed up like every other canonical
record. See [`hierarchical-classification.md`](hierarchical-classification.md).

`library/` has its own deterministic hash manifest, one primary Markdown path per Document and
relative README/view indexes. Its manifest binds the deep canonical/Original fingerprint but does
not promote generated files to canonical knowledge. See
[`markdown-library-viewer.md`](markdown-library-viewer.md).

Path locators use `/` as the logical separator even on Windows. Absolute locators and `..` traversal are rejected before they are used as Instance-relative references.

## Read-only validation

`provelume validate INSTANCE` checks the configuration, manifest, canonical JSON references and
every retained Original hash/size. It performs no migration, repair, index rebuild or network
request. `--fast` validates identity and schema contracts without reading every Original byte.

Every configuration access still opens and reads `provelume.yml`. An `InstanceStore` may reuse
the YAML decoding of its last successful buffer only when the newly read bytes are identical;
timestamps, file size and prior validation results never substitute for that read. The private
buffer/value pair belongs to that store, and callers receive independent deep copies. A changed,
missing, unreadable or malformed file is processed as the current input, never replaced with a
previous valid configuration. This removes repeated decoding during validation and maintenance
without caching an inspection, permission, manifest check or authority for a later operation.

Schemas 1 and 2 are reported as valid but `migration_required: true` when identity and canonical state
pass inspection. An unknown future schema or an older schema with no registered migration fails
closed before a backup or write.

## Forward-only schema migration

Ordinary open refuses schemas 1 and 2 with an explicit migration instruction. Stop every older
runtime before running `provelume migrate INSTANCE`. The operator command retains the registered
`instance-schema-1-to-2` transition and then applies `instance-schema-2-to-3`:

1. deep preflight verifies canonical references and Original bytes;
2. a same-Instance backup is built and independently re-read/hash-verified;
3. the existing external lifecycle journal binds the rollback archive and complete source-byte
   inventory; its distinct `object-migration` operation also makes older recovery code refuse it;
4. a private stage retains the original schema-1-to-2 receipt, when applicable, before promotion to
   schema 3; its independently verified publication backup is retained outside the Instance;
5. the source-byte inventory is re-read under the same lifecycle lock immediately before the
   directory replacement, and the complete installed schema-3 Instance is deeply validated.

The migration does not rewrite canonical JSON or acquired Original bytes. It adds object heads and
immutable revisions for existing Projects/Collections, preserving their exact IDs, hierarchy bytes,
names and parents. Existing hierarchy operations remain the single authority for identity/name/parent;
their object projection is committed in the same bounded transaction. A legacy identity/name/time
that cannot satisfy the closed object contract stops migration rather than being invented or repaired.
Its receipt records the
old/new schema, preflight content fingerprint and exact backup archive digest. Migrations only move
forward; there is no in-place downgrade path.

The five schema-3 canonical families are `objects`, `object-evidence`, `object-revisions`,
`object-relations` and `object-relation-revisions`. Revision files wrap a closed object/relation record
with a content-derived `objrev_`/`relrev_` identity; heads retain the S01 record shape. Deep inspection
checks complete contiguous hash-linked history, evidence identity, exact relation revision references,
typed endpoints and acyclic active dependency/containment edges (including existing hierarchy links).
Missing retained evidence is reported as unavailable, never retargeted to a newer DocumentVersion or
certified as factual truth. Writes require a matching current preimage; new evidence records require
available, matching Original bytes. The later application service also owns fresh selector resolution.
The persistence primitive has no application permission, consent or proposal approval authority.
An explicitly purged Document does not erase independent object assertions or their immutable
attribution records: the retained reference becomes unavailable. No broader erasure is claimed.

Settings, consents, permissions, language, interface selection and retained state are preserved.

The same-host operator migration also preserves filesystem access control independently of
payload byte hashes. Its bounded native profile covers POSIX modes, owner/group and extended
attributes (including filesystem ACLs), or Windows owner/group, DACL protection/inheritance and
the read-only attribute. Existing empty directories retain their access metadata; new canonical
files and directories start private. Profiles are captured from the live source, never accepted
as authority from a portable archive. Portable transfer retains application authorization records
and keeps its existing private-file extraction policy across hosts.

The lifecycle control directory outside the Instance retains three immutable permission-profile
documents for the exact source, backup reconstruction and published image. Their byte hashes and
access fingerprints are bound in the operation journal before the corresponding rename. Keep
these private documents with the recovery journal and verified backups until the operation is
settled. A permission-only concurrent change, changed profile or unknown legacy byte-only object
journal stops recovery for inspection; it cannot overwrite current permissions. The native profile
is limited to 200,000 entries, 16 MiB per profile and 256 KiB of metadata per entry. Unsupported
metadata or a host unable to reproduce it fails before publication.

Object-migration recovery records its deterministic receipt in the external lifecycle control
directory so settling an image does not require changing a read-only Instance. It recognizes only
the bound bytes and access metadata of its preimage, verified backup reconstruction or postimage.
A foreign target appearing between renames or a newer image after publication is retained with
the journal and backups. Object staging uses its own namespace; generic restore cleanup cannot
erase those retained images. Read-only preimages that cannot be removed remain explicitly reported
as inert residues for the operator, rather than causing rollback over a verified live image.
Indexes/library remain disposable rebuilds; a schema transition can invalidate their old canonical
fingerprint. Normal backup/export of an older Instance remains possible without upgrading its source.

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
backup. Older supported backups are migrated inside the private stage before publication. To roll
back the source explicitly, use `provelume restore INSTANCE PRE_MIGRATION.zip
--preserve-source-schema`. This restores the verified older schema and refuses ordinary current-Core
open until an explicit forward migration. It is a whole-snapshot restoration: later changes are not
merged, and their verified pre-restore backup is returned as `rollback_backup`. Retain that archive
before choosing which source version to reopen; there is no lossy in-place downgrade.

The frozen Windows runtime exposes these same six operator commands without an installed Python
or Git. Stop the runtime using the Instance, then use a **new** report file outside the Instance:

```powershell
Provelume.exe --instance-result-file "C:\Evidence\migration.json" --instance-command migrate "C:\My Instance"
Provelume.exe --instance-result-file "C:\Evidence\rollback.json" --instance-command restore "C:\My Instance" "C:\Backups\before.zip" --preserve-source-schema
```

`validate`, `backup`, `export` and `import` use the same native argument grammar after
`--instance-command`. The report path must precede that flag. It is created exclusively before
any action; an existing report or a path inside the Instance is refused before mutation. The
result contains the native JSON outcome; a nonzero process exit or incomplete report is not
success. This explicit mode starts neither the GUI nor a server and dispatches no other commands.
Installing, launching or selecting an Instance never grants implicit migration authority.

The sibling control directory keeps the pending marker and lifecycle lock outside the directory
being replaced. The persistent lock metadata file is guarded by an OS advisory lock, so process
termination releases ownership in the kernel and contenders never delete/reclaim a pathname that a
new owner may already hold. Pending recovery acquires that same lock before changing the Instance.
After an interrupted migration or restore, the next open verifies and restores the recorded
pre-operation backup before retrying normal preparation. Recovery is persisted under
`state/lifecycle/recovery-receipts/`; it is not silently treated as an ordinary successful open.
Object migration recovery recognizes only the bound complete preimage, verified backup image or
complete postimage. A crash between directory renames restores the verified backup; a fully installed
postimage is settled without replay. Recovery receipts are idempotent. Changed/foreign Instance bytes,
modified owned stages and conflicting receipts are retained with the pending barrier for inspection;
recovery cannot overwrite them. Only exact journal-owned, hash-matching directories are removed.
An incomplete rollback retains its previous directory. The private builder is inside the existing
control directory; an interrupted build can leave an unpublished residue there for operator inspection.
These process-crash guarantees require the existing local filesystem/OS locking profile; they do not
claim to fence an older process left running with ambient filesystem write access, or power-loss
durability beyond the platform's file/directory flush support. Stop older runtimes before migration.

These local backups are not the portable cross-Instance export/import contract. `0.6/S05` adds a
separate deterministic portable bundle, complete hostile-input validation, explicit include/rebuild
choices and replacement import with a verified target backup. Unlike restore, import intentionally
accepts a different exported Instance identity and preserves it in the target directory. See
[`portable-export-import.md`](portable-export-import.md).
