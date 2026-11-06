# Concordia S08: understandable search types and recovery

This is the B slice of [#391](https://github.com/gabned/provelume/issues/391), after
the integrated S03/A behavior. The maintainer's
[6 November sequencing decision](https://github.com/gabned/provelume/pull/439#issuecomment-6680960524)
authorizes its development before S07's automatic acceptance. The original CPU
owner/finding stays draft/CURRENT; this slice does not accept S07 or qualify the
release. Its own homogeneous PR-local owner records actual source, evidence and
qualification results. Protocol 1.5.2 and the accepted legacy route remain in use;
Lifecycle v2 is deferred.

## Behavior contract

Both Current and Cura search forms present understandable file-type labels while
submitting the exact original MIME value. Active search chips use the same labels;
technical MIME remains available as detail. Unknown types have a readable fallback
with their escaped technical value, preserving distinct unknown choices. Labels
describe type, not extraction, indexing, OCR readiness or search coverage.

A genuine successful search with no matches retains its words and active filters.
It offers an ordinary keyboard-accessible edit action targeting the existing query
field. When non-word filters are present, it also offers removal of Source/type/
acquisition-date filters while retaining the effective words, resolved language
and validated search context. Query normalization, return-target allowlists and
duplicate/bounds checks keep the S03 contract. Error, initial and index-pending
states must not acquire a false zero-result or text-availability claim.

The slice introduces no implicit OCR/AI, ingestion, data mutation, new shortcut,
global focus policy, result redesign, pagination, engine or date semantics. Source
names/identities, Originals, canonical records and preferences remain unchanged.
All seven offline catalogs contain complete copy/context; new linguistic review
is UNVERIFIED, separate from automatic completeness.

## Evidence required on the actual candidate

- Both layouts: known/unknown/hostile MIME choices, matching labels/chips and exact
  submitted values; removal of one chip and all non-word filters.
- Empty search: query/filter summary, edit focus and keyboard correction, filter
  removal with exact words/language retained, return from a matching document.
- S03 initial/error/pending behavior, valid dates and compatible API/browse/mobile
  callers; no false extraction/OCR inference or work admission.
- Synthetic Original/canonical/preference byte conservation and inert escaping.
- Complete catalog validator, focused regressions, full native suite, current Ruff
  with an external cache, diff check, exact-head all-attempt CI and reviews.
- Applicable automatic real-browser interaction, keyboard/focus, themes and
  viewport checks, reported with its actual browser/host and source identity.

The PR ledger records results and limitations, including interrupted/failed
attempts. HTTP/markup checks are not browser evidence. An available automated
Chromium check does not establish the historical internal-browser or human
Windows11/screen-reader/real-zoom rows. Those manual methods remain
DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official 0.15 on the
maintainer's production Windows11Pro25H2 account. No intermediate installation or
manual candidate test is requested. Ordinary merge and actual-main checks still
require valid applicable qualification; every release gate remains separate.
