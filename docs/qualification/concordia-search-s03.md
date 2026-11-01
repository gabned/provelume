# Concordia S03: recoverable search input

This is the A part of [#391](https://github.com/gabned/provelume/issues/391).
Part B, shortcuts, result redesign, pagination, engine changes, OCR and Inbox
remain separate. The maintainer [authorized S03 followed by S04](https://github.com/gabned/provelume/issues/383#issuecomment-6556143706)
after S02's actual-main acceptance. S01 remains suspended and not accepted.

## Boundary and behavior

The HTML `/search` controller derives one trimmed query. Execution, the form,
filter chips, result links, language links and return context use that value.
It passes explicit presentation query pairs to the existing context helpers;
the Request is not mutated. Existing return-target whitelist, bounds and duplicate
checks remain unchanged. Other pages use their original request values.

Absent, empty and whitespace-only queries do not execute search and do not show
an empty-result claim. Existing Source/type/valid date choices remain selected.
The HTML page validates nonempty dates as ISO calendar days, including leap-year
rules, and rejects inverted ranges before invoking search, even with an empty
query. Invalid input returns the same HTML page with HTTP400, an error summary,
linked field diagnostics, `aria-invalid`/`aria-describedby` and autofocus on the
first invalid date. The advanced disclosure is open when needed. Rejected date
text is escaped; valid dates and all other inputs remain available for correction.

Both layouts distinguish invalid input from a genuine successful search with no
matches. Current search result/Document/Provenance links now retain the same
validated search-return context; Current browse presentation remains unchanged.
No global keyboard shortcut or new focus policy is introduced.

The date help names **acquisition days in UTC**. Domain/API `_date_floor` and
`_date_ceiling`, API search, browse/mobile callers, canonical data, Originals,
preferences and index-integrity controls are unchanged.

## Qualification

The owner PR records exact candidate/base/tree, complete native checks, original
CI histories, reviews and actual-main integration. Source tests cover initial
states with retained filters; positive/title/content/uppercase/trimmed queries;
valid, empty, open and equal dates; leap-day UTC boundaries; malformed/calendar
errors; inverted ranges and repair; inert hostile text; context round trips,
Original bytes, preferences and compatible API timestamp inputs.

All seven catalogs include the validation copy. Run the complete catalog gate:

```text
python scripts/validate_ui_catalogs.py
python -m pytest -q tests/test_concordia_search_inputs.py tests/test_cura_shell.py tests/test_api_browser.py tests/test_mobile_retrieval.py
```

Catalog completeness is distinct from linguistic review, which remains UNVERIFIED.
Markup/HTTP checks establish source contracts, not observed keyboard focus, real
browser zoom, screen-reader behavior or an internal-browser qualification.

The [A handoff](https://github.com/gabned/provelume/issues/391#issuecomment-6246563151)
requires a real internal-browser run. That capability is not exposed in this
execution environment; its interactive rows remain **NOT_RUN**. An external
Chrome/HTTP run does not replace it. Record any maintainer decision about
deferring that gate explicitly in the owner/campaign ledger before acceptance.
The maintainer explicitly [deferred the S03/S04 manual rows to integrated qualification](https://github.com/gabned/provelume/pull/429#issuecomment-6556457115).
They remain NOT_RUN; the normal automatic/review/integration gates still apply.
No missing human or Windows11 observation is converted to PASS, and no S01
finding is cleared by this source work.
