# Duplicate and Original assurance

Status: active product contract for `0.5/S04` under issue #66. The installed package and
published preview remain `0.4.1` until a separate release-preparation change.

## Purpose

Duplicate detection must explain evidence without silently collapsing knowledge. Original
assurance must verify exact retained bytes and canonical references without repairing, replacing or
deleting anything. Both activities are explicit local operations and are recorded in the navigable
operation log introduced in `0.5/S02`.

## Exact duplicates

An exact case exists when two or more current DocumentVersions have the same SHA-256 content hash.
The content-addressed Original is stored once, while every Document, Source locator and Acquisition
remains separate. A case records the current Documents, Versions, Source identities, normalized
locators, Acquisition counts and one confidence value of `1.0`.

Exact detection does not merge Documents, rewrite a current Version, remove an Inbox item or delete
an external or retained file. The only offered review choices are descriptive future actions such
as keeping occurrences separate, linking occurrences or reviewing whether one should become a new
version.

## Probable duplicates

Probable cases are conservative, explainable pairs with different content hashes. The detector uses
bounded normalized title tokens and bounded extracted-text token overlap. A pair must satisfy one of
two published rules:

- the normalized titles are equal and extracted-text overlap is at least 0.50; or
- title overlap is at least 0.60 and extracted-text overlap is at least 0.75.

The case stores the rule, component similarities, confidence and compared-token counts. No semantic
model, cloud provider or hidden embedding is used. Missing or unreadable derived text prevents a
probable match and produces a bounded scan warning instead of a guessed result.

Cases use deterministic identities. A later scan marks a no-longer-matching case `not_current`
rather than deleting its history. The automatic action is always `none`.

## Bounded scan

The local command is:

```text
provelume duplicate-scan INSTANCE
```

The scan bounds Document count, candidate pairs, retained cases, text characters, tokens and
warnings. Exceeding a structural limit fails visibly and closes the corresponding operation as
failed. Canonical knowledge and Original bytes are read-only inputs.

Read surfaces are:

```text
provelume duplicates INSTANCE
provelume duplicate INSTANCE DUPLICATE_ID
GET /api/v1/duplicates
GET /api/v1/duplicates/{duplicate_id}
/duplicates
/duplicates/{duplicate_id}
```

## Original assurance

`provelume assurance-check INSTANCE` verifies:

- every content-addressed Original ID, declared SHA-256, size and storage reference;
- the bytes stored at that reference against both hash and size;
- DocumentVersion links to existing Documents and Originals;
- agreement between Version content hash/size and Original identity;
- Document links to existing Sources and a current Version that belongs to the Document;
- Acquisition links to existing Sources, Documents and Versions plus hash agreement;
- unreferenced Originals and Versions without Acquisition evidence.

The report is schema-versioned under `state/assurance/reports/`, has a stable operation link,
bounded findings and integer metrics. Shared Originals are counted as assurance evidence, not as an
error. An unhealthy report never repairs records or rewrites bytes.

Read surfaces are:

```text
provelume assurance-reports INSTANCE
provelume assurance-report INSTANCE ASSURANCE_ID
GET /api/v1/assurance
GET /api/v1/assurance/reports
GET /api/v1/assurance/reports/{assurance_id}
/assurance
/assurance/{assurance_id}
```

## Privacy and lifecycle

The public records contain canonical IDs, normalized Source-relative locators, hashes, bounded
messages and metrics. They contain no configured absolute Source path, credential or private
network endpoint. Browser and API reads create no duplicate or assurance directory.

This slice adds no automatic deduplication, destructive cleanup, repair, AI classification,
network Source, schema migration, package-version change, tag or release publication. A later
Action Center may add explicit reviewed decisions without changing the assurance rule that an
acquired Original is never removed implicitly.
