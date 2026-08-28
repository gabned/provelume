# Stable hierarchy and classification

The `0.6/S02` hierarchy is canonical local knowledge, not a browser-only tree or a generated
filesystem layout. It is available through the same application service used by the local CLI,
read-only Knowledge API and EN/IT Knowledge Browser.

## Canonical records

Schema-2 Instances may contain two additive canonical directories:

```text
knowledge/
  hierarchy/
    <node-id>.json
  classifications/
    <classification-id>.json
```

An older valid schema-2 Instance may not yet contain these directories. Their absence means an
empty hierarchy; it does not require another Instance migration. New Instances create both
directories, and the first hierarchy or classification write creates a missing additive directory
atomically. If records are present, deep Instance validation includes them in the canonical
fingerprint, reference checks and backups.

Every hierarchy record has record schema 1 and one stable opaque identity:

- `area_<32 hex>` for an Area or Subarea;
- `project_<32 hex>` for a Project;
- `collection_<32 hex>` for a Collection.

The record stores `kind`, normalized display `name`, deterministic portable `slug`, optional
`parent_id`, and creation/update timestamps. Renaming changes the display name and slug, while
moving changes only the parent. Neither operation changes the node identity.

The closed parent contract is:

| Child | Allowed parent |
| --- | --- |
| Area/Subarea | Area |
| Project | Area or Project |
| Collection | Collection |

Every kind may also be a root. Parent references must exist, a node cannot parent itself, parent
cycles are rejected and depth is bounded to 64 levels. Siblings and roots are ordered by
case-folded display name, kind order and stable ID, so navigation is repeatable after restart.

## Portable slugs

A slug is derived from the normalized display name plus the node's complete 32-hex identity
suffix. The readable base is ASCII lowercase, uses only letters, digits and hyphens, and is bounded
before the suffix is appended. A name that has no ASCII representation falls back to its kind.

The complete slug therefore uses only `[a-z0-9-]`, never ends in a dot or space, cannot equal a
Windows reserved device name and remains collision-safe even when two siblings have the same
display name. A rename produces a new readable base with the same identity suffix. A parent move
does not alter the node slug; descendant portable paths are recomputed from stable parent links.

## One primary path and secondary associations

A classified Document has exactly one canonical classification record. Its ID is deterministically
derived from the Document ID, so a second record cannot silently introduce another primary
classification. The record contains:

- one required `primary_node_id`;
- a sorted, unique list of zero or more `secondary_node_ids`;
- stable creation time and the most recent update time.

The primary node cannot also appear in the secondary list. Every referenced node and Document must
exist. Repeating an identical classification is idempotent. Changing classification updates this
single record; it does not copy the Document, create another Original, rewrite a Version, or touch
acquired bytes.

Each primary or secondary association also has a deterministic canonical provenance edge from the
Document to the stable hierarchy node. Repeating an association does not duplicate the edge, and
an identical classification call repairs a missing expected edge. Deep validation fails if an
active classification lacks its bound edge or if the edge does not match the association.
Historical edges remain readable after reclassification, while the classification record remains
the authority for the current primary and secondary placement. Rename and movement keep every
edge valid because the target node ID does not change.

## Application surfaces

Local operator mutation is available through the application service and CLI:

```bash
provelume hierarchy-create INSTANCE area "Work"
provelume hierarchy-create INSTANCE project "Atlas" --parent-id <area-id>
provelume hierarchy-rename INSTANCE <node-id> "Client work"
provelume hierarchy-move INSTANCE <node-id> --parent-id <new-parent-id>
provelume hierarchy-move INSTANCE <node-id>
provelume classify INSTANCE <document-id> --primary <node-id> \
  --secondary <collection-id>
```

`hierarchy-list` returns the deterministic flat navigation sequence and nested tree;
`classification` returns one Document's current classification. These commands perform no network
request.

The read-only HTTP surface adds `GET /api/v1/hierarchy`,
`GET /api/v1/hierarchy/{node-id}` and
`GET /api/v1/documents/{document-id}/classification`. Document lists accept `hierarchy_id`; by
default, a selected node includes primary or secondary associations on that node and descendants.
`include_descendants=false` selects direct associations only. No HTTP mutation route is introduced.

The Browser uses the same service results for hierarchy paths, counts, filtering, breadcrumbs and
Document classification. Source-locator `area` remains a separate backward-compatible filter; it
does not become canonical classification.

## Derived Markdown projection

`0.6/S03` now derives Area/Project primary paths, Collection association indexes and README
navigation from these canonical records. The generated `library/` stores one Markdown file per
Document; secondary associations are relative links rather than copies. Deleting, editing or
rebuilding the projection does not change hierarchy IDs, classifications, provenance, Documents,
Versions or Originals. See
[`markdown-library-viewer.md`](markdown-library-viewer.md).

`0.6/S04` now preserves these same stable classification references across archive, projection
removal, recoverable trash and restoration; only authorized permanent purge removes the selected
classification with the Document lineage. `0.6/S05` preserves hierarchy IDs, classifications and
association provenance through hash-manifested cross-platform export/import. See
[`retention-boundaries.md`](retention-boundaries.md) and
[`portable-export-import.md`](portable-export-import.md).
