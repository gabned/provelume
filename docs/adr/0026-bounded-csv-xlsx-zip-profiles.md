# ADR 0026: bounded CSV, XLSX and ZIP profiles

- Status: accepted for `0.10/S06`
- Date: 2026-09-03
- Parent: #160
- Slice: #177

## Decision

Admit exactly `perceptio-csv-cell-v1`, `perceptio-xlsx-sheet-cell-v1` and
`perceptio-zip-member-v1`. They use only Python 3.12 standard-library `csv`, `zipfile` and
`xml.etree.ElementTree` under PSF-2.0. No dependency or native/runtime payload is added.

S01 bundle schema v1 remains current. Its reserved `sheet`, `cell` and `member` kinds gain closed,
discriminated target-v1 shapes while legacy `{reserved: true}` targets remain valid. This is an
additive activation, not a migration or reinterpretation of existing extraction.

CSV is limited to bounded UTF-8 input and inert displayed strings. XLSX reads workbook
relationships and cached/displayed cell values, records only whether a formula is present, and
rejects formula-only values, external relationships, macros and embedded active content. ZIP
records bounded member metadata and hashes in memory without writing or recursively opening any
member.

## Rejected alternatives

- Adding a fourth family: violates the activation gate.
- Reusing or changing canonical text extraction: would silently redefine existing evidence.
- `openpyxl`, archive binaries or plugin discovery: adds dependencies and a wider execution/
  packaging surface without necessity.
- Rendering spreadsheet HTML from source content: risks active content. Browser tables are
  first-party, escaped and read-only.

All other forecast families remain deferred at their existing truthful support level or later
roadmap boundary.
