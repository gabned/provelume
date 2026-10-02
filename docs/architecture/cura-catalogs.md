# Governed offline interface catalogs — S08 development candidate

`core/provelume/i18n/registry.json` owns the language registry, message context,
plain-text rendering boundary, glossary, review requirement and compatibility
exports. Exactly one JSON catalog per language owns the strings. The remaining
`*_i18n.py` modules are compatibility readers, not string owners. Capture's
public script is rendered from the same data; its integrity and public worker
revision bind catalog bytes. Knowledge, grants and credentials never enter it.

The registered languages are en, it, de, es, fr, pt and ro. Portuguese is pt-PT.
System is a persistent choice, resolved per host without mutating the process
locale. Registered regional locales reduce to their language; unsupported host
locales resolve to English. Existing explicit en/it preferences are preserved.
Explicit choices remain independent of document language and engine capability.

The contract supports plain text and data-only plural/select variants with an
`other` case. Plain named placeholders are permitted; attribute access,
conversion, format specifiers and executable messages are rejected. Renderers
escape at their HTML/text boundary. Plurals accept bounded nonnegative integer
counts; their named categories follow the [CLDR 48 cardinal rules](https://www.unicode.org/cldr/charts/48/supplemental/language_plural_rules.html).
This is a bounded message contract, not a claim to implement arbitrary ICU syntax.

Numbers have deterministic decimal/group separators, precision and finite-value
validation. Dates require a timezone and preserve the canonical timestamp;
presentation never rewrites stored dates. Sorting uses NFC, casefold and exact
spelling as a stable tie-break. It does not promise dictionary collation.

Run `python scripts/validate_ui_catalogs.py` for the full automatic contract.
`--structural-only` supports development of incomplete packs while still reporting
every missing count; it cannot qualify a shipped catalog. Duplicate JSON keys,
key mismatches, missing translations, placeholder mismatches, malformed variants,
active markup and missing context are findings. The implementation tests are
synthetic and do not establish real browser layout, screen-reader, device or
linguistic acceptance.

Qualification has three independent results: catalog completeness, automatic
contract/tests and actual linguistic review. All seven catalogs now have complete
draft data, including Capture, retrieval, desktop and tray text. DE/ES/FR/PT/RO
were authored using Google Translate's public text interface and agent corrections
to recover malformed transfer identifiers and placeholders. PT used the explicitly
selected Portugal variant. Only public interface strings were submitted; no
Instance content, credentials or personal files were used. The product runtime
has no translation service, provider dependency or network requirement.
EN/IT strings are migrated references; migration alone does not prove historical
human approval. No generated text, successful test, internal hash or agent-written
flag can establish review. The accepted consumer has no automatic linguistic
approval delegation or exact grant recorded for this work.

The maintainer authorized ordered completion and publication of Cura on
2026-10-02. S08 is integrated only after verified S07 merge and post-merge checks;
S09 remains separate. This authorization does not establish linguistic review.
Actual review is NOT_PERFORMED and no automatic approval grant or review evidence
is inferred. The sensitive-copy review requirement under #255/#247 remains a
delivery/publication gate. Complete source-bound review evidence must identify
the exact text, language, context and dependencies. Any delegated automatic
approval additionally requires a prior adopted consumer policy and an exact
valid grant; neither exists for this candidate. Completeness and automatic
checks alone cannot close S08 or activate the new default.
