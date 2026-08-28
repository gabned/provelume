# Configurable local folder settings

Status: `0.5.0` release-blocking compatibility contract under issue #72.

## Scope

An Instance owns one logical Inbox identity but users may choose its display name and the physical
locations of two local folders:

- **Drop folder** — files explicitly placed here can be processed with move-after-verified-commit
  semantics;
- **managed-copy folder** — Provelume keeps hash-verified working copies here before and after the
  canonical Acquisition is committed.

Both paths may be relative to the Instance or absolute paths elsewhere on the local filesystem.
Relative paths are resolved from the Instance root and are stored portably. A location outside the
Instance is stored as an absolute path because a parent-traversal relative path would obscure the
portability boundary.

Canonical Originals, readable knowledge JSON, derived state, indexes, operation records, assurance
reports and submission evidence remain inside the Instance in `0.5.0`. External Drop or managed
folders are local filesystem dependencies, not alternate canonical stores.

## Default and compatibility behavior

An Instance without a `folders` section retains the original behavior:

```yaml
folders:
  inbox:
    schema_version: 1
    name: Local Inbox
    drop_path: inbox/drop
    managed_path: inbox/items
```

The section is optional and does not change Instance schema version 1. Existing legacy submission
summaries below `inbox/submissions/` remain readable; new summaries are stored under
`state/inbox/submissions/` independently from the selected working folders.

## Validation

An explicit local settings action validates both selected directories before committing config:

- the directories are created when missing and a bounded temporary write proves local write access;
- Drop and managed folders must be distinct and neither may contain the other;
- neither folder may be the Instance root or an ancestor that contains the Instance;
- neither may overlap canonical Originals, knowledge, state or index storage;
- null, empty, overlong and non-directory paths fail visibly;
- paths are canonicalized before overlap checks so existing symlinks cannot bypass the boundary.

Changing the display name or Drop folder remains available after use. Moving the managed-copy
folder after the Inbox Source has Documents or Acquisitions is blocked. A future relocation feature
must verify every managed copy, update the Source binding and preserve crash recovery before that
movement can be automated.

## Interfaces and path disclosure

Local controls are:

```text
provelume folder-settings INSTANCE
provelume configure-inbox INSTANCE --name NAME --drop PATH --managed PATH
/settings
```

The browser form accepts mutations only from a loopback client and requires a process-local CSRF
token. The corresponding API remains read-only:

```text
GET /api/v1/settings/folders
```

CLI and the loopback settings page show full physical paths because they are local operator
surfaces. The read-only API and non-local browser view expose only `instance`/`external` scope,
a relative internal locator or external basename, and availability/writeability state. They do not
return external absolute paths.

## Operation evidence

A successful change creates a `settings.folders` operation with changed-field flags, internal or
external scope and integer metrics. It deliberately omits folder names and physical paths. A failed
committed attempt records only the bounded error type. Inbox submissions continue to link to the
stable Inbox Source identity even when its display name or Drop location changes.

## External-folder consequences

External folders are technically supported anywhere on a mounted local filesystem for which the
Provelume process has access. They may become unavailable when a removable disk, network mount or
user profile is missing. The Instance remains valid and its canonical knowledge stays portable,
but new Drop processing or managed-copy access fails visibly until the configured location returns.
Backing up only the Instance does not back up unacquired files waiting in an external Drop folder.
