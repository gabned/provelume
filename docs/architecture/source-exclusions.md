# Per-Source exclusions and ingestion preview

`0.10.1/S02` (#212) adds one selection policy to each managed Folder Source.
Open **Sources → Exclusions** in the local Browser or Windows-hosted application.
The EN/IT page shows every rule and its enabled state, permits editing/removing
rules, restoring defaults and disabling the whole policy. Every change is previewed
before an explicit Apply. Remote Browser clients can inspect the stored rules;
filesystem previews and mutations require the existing loopback/CSRF boundary.

## Rule contract

The visible default profile contains `.git/**`, `.github/**`, `.gitignore`,
`.gitattributes` and `.gitmodules`. New managed Sources persist that profile;
existing managed Sources without a stored profile use the same visible defaults
until their first explicit change. Unmanaged one-shot filesystem ingestion keeps
its existing contract and is not silently enrolled as a managed Source.

Policy schema 1 contains a positive `revision`, an `enabled` flag and at most 32
rules. Each rule has a stable ID, kind, pattern, `exclude` or explicit `include`
action, and its own enabled flag. Editing preserves the ID. Successful application
increments the revision exactly once; a stale revision cannot overwrite a newer
policy. This is a versioned current policy, not an append-only history of edits.

| Kind | Matching contract |
| --- | --- |
| `subfolder` | Exact Source-relative directory and descendants. |
| `file` | One exact Source-relative file, including literal brackets/punctuation. |
| `extension` | One case-insensitive suffix such as `.pdf`; a leading dot is normalized. |
| `type` | Versioned extension groups: `text`, `document`, `image`, `audio`, `video`, `email`, `archive`. These are selection groups, not content sniffing or expanded extractor support. |
| `glob` | Case-sensitive portable path components: `*` and `?` within one component, `**` for zero or more complete components. No character classes, negation or brace expansion. |

An enabled explicit include overrides matching excludes, independently of rule
ordering. Patterns normalize Unicode to NFC and separators to `/`; serialized
policies use sorted keys and rule IDs. File/path comparisons are case-sensitive
on every platform, while extension/type comparisons case-fold. Paths must be
relative, without empty, `.` or `..` components, drive prefixes or URLs. Patterns
are limited to 256 characters and 16 components, with at most two `**` components
and 12 wildcard characters. Duplicate rules, unknown fields and invalid versions
fail closed. Existing raw filesystem spelling is retained when opening a file;
names colliding after portable Unicode normalization are rejected.

## Bounded preview and apply

Preview reads directory entries and metadata, never document bytes. It reports
included/excluded files, pruned excluded directories, unsupported files, unfollowed
directory links and included byte counts, plus at most 200 explained relative-path
rows. Pruned directories are not enumerated; their unknown descendants are not
counted as individual excluded files. An explicit include retains only subtrees
that may contain a match; broad extension/type or wildcard includes may require
more traversal. Unsupported formats remain unsupported even when included.

Traversal has a 10,000-entry budget, depth 32, a ten-second cooperative scan budget
and the Source's existing included-file limit. Preview callers wait at most five
seconds; at most two read-only workers may be in flight. A blocked network filesystem
cannot cause a late rule application. Exceeded limits produce a closed diagnostic
and no applicable partial result: narrow the Source or rule. Absolute paths and
raw OS exceptions are not emitted in the preview. Links escaping the Source and
Sources retargeted into the Instance fail closed; directory links are never followed.

The preview fingerprint binds the Source identity, current policy, complete proposed
policy and inspected metadata snapshot. Apply re-runs the same preview under the
Instance mutation lock and requires an exact match. Changed metadata, rules or
revision require a new preview. The fingerprint qualifies selection/counts; it is
not a content hash of document bytes. Apply writes only the Source configuration.

## Ingestion, recovery and retained data

Initial managed scan, explicit refresh, scheduled watch and Source reconciliation
use the same selector. The policy participates in observation/configuration
fingerprints, so changing it invalidates a previous unchanged snapshot. A fresh
retry may not reacquire newly excluded items from an old failed run; use a new
refresh or an explicit previewed override. Replaying terminal receipts and repairing
interrupted canonical work retain their existing non-acquisition semantics.

Excluding an already acquired locator does not report it as missing or delete its
Source, Acquisition, Document, Version or Original. Derived FTS reindex and Markdown
rebuild continue to use retained canonical data; exclusions govern future intake,
not retroactive search visibility or deletion. The existing explicit lifecycle
operations remain the deletion boundary. Configuration backup/restore and portable
export/import carry the exact policy and revision without a separate rule store.

## Service, CLI and qualification

The service exposes `folder_source_exclusions`, `preview_folder_source_exclusions`
and `apply_folder_source_exclusions`. CLI equivalents are:

```bash
provelume folder-source-exclusions INSTANCE SOURCE_ID
provelume folder-source-exclusions-preview INSTANCE SOURCE_ID --policy-file proposed.json
provelume folder-source-exclusions-apply INSTANCE SOURCE_ID --policy-file proposed.json --preview-fingerprint SHA256
```

The policy file contains the complete proposed schema-1 policy at current revision
plus one; it is bounded to 64 KiB. Omitting it from preview inspects current rules.
The Browser provides ordinary individual-rule controls without requiring JSON editing.
See the [API contract](../api.md) for read and loopback preview endpoints.

`tests/test_source_exclusions.py` covers rule kinds, normalization and bounds,
explicit override/pruning, policy isolation, stale previews, traversal/link safety,
read-only timeout workers, actual scan/watch/reconciliation and retry behavior,
canonical/Original preservation through reindex, backup and portable round trips,
CSRF/remote restrictions and EN/IT parity. The permanent Windows matrix additionally
uses an existing localhost administrative UNC share to compare real filesystem
preview/counts with the local path, without creating a share or storing credentials.
