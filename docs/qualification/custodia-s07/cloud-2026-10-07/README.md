# S07 cloud browser qualification, 2026-10-07

Continuation of owner PR #325 from `ae94b34e4f562233a1be22b5222d168c023e900b`,
with the original binding, base and Protocol pin unchanged. This record is not an
integration receipt. S08 remains dependent on verified S07 integration.

The new Linux execution environment provides CPython 3.12.14 and Chromium
151.0.7922.173. Playwright 1.63.0 was installed only in an ignored tooling directory;
no product dependency, browser framework, model or runtime was changed. Each preview
uses an owned loopback server and newly initialized, public synthetic Instance.
Browser requests are restricted to that preview by the harness. No real provider,
credential, model acquisition or inference is involved.

## Observations and correction

The Components catalogue overflowed the entire mobile page: measured document
widths ranged from 812 to 1066 CSS pixels at a 390-pixel viewport, depending on
language. Its existing table wrapper had no overflow rule. The correction gives
only that wrapper horizontal scrolling, a localized accessible region name,
keyboard focus and explicit column-header scope. Other tables are unchanged.
Keyboard ArrowRight reaches the off-screen columns without widening the page.

The resumed sensitive-copy review also found three Italian strings needing
correction: the malformed article/agreement in the public synthetic test description,
and the false-friend use of “redazione” in the payload label and redaction explanation.
They now use “mascheramento”; consent and privacy limitations are unchanged.
This is an AI review, not an independent human linguistic attestation.

| Evidence | Result and exact scope |
| --- | --- |
| `matrix.json` | 252 rendered checks: six views × seven catalogs × Light/Dark/System × desktop 1280×900/mobile 390×844. All have translated headings, labeled visible fields and no document-level horizontal overflow. System uses a dark OS preference. |
| `zoom.json` | 126 checks: the same six views × seven catalogs × three themes at native Chromium 200% zoom. Outer width 1280, inner width 640, devicePixelRatio 2 and visualViewport.scale 1 distinguish browser zoom from CSS/pinch scaling. No horizontal page overflow. |
| `accessibility.json` | 42 keyboard journeys across the six views and seven catalogs. All visible focusable controls were reached and had a visible outline; form fields had names. Advanced disclosure works by Enter, mobile navigation closes with Escape and returns focus, back/refresh preserves configuration revision, and the Components table scrolls by keyboard. |
| `receipts.json` | 42 rendered checks for populated Operations, explicit synthetic consent and enqueue confirmation in seven catalogs, Light desktop/Dark mobile. The completed and queued jobs use the existing governed scheduler with a test-owned transport and explicit zero-cost synthetic quote. No private result body appears in these pages. |
| Browser accessibility tree | Components exposes its localized region name, table and seven column headers. This is browser accessibility-tree evidence, not screen-reader operation. |
| Native full suite on original candidate | 3521 passed, 23 skipped, 10 warnings, 305.27 seconds. Full Ruff and whitespace passed. Final follow-up native/CI observations belong in the same owner PR ledger. |
| Manual screen reader | NOT_RUN by the agent. A maintainer's affirmative statement that details can be supplied is not yet a test attestation; tool/OS, surfaces, language, outcome and source/date remain required. |
| Human linguistic review | NOT_RUN. |

The six views are AI & Privacy, blocked synthetic-test preview, document selection,
private exact-Version document preview, empty AI Operations, and Components.
Coverage is synthetic fixture coverage, not a claim to have exercised every model,
error or assistive-technology combination. HTTP/CSRF/race/recovery tests remain
separate native evidence. The two Italian description corrections followed the
252-check run; they were present during zoom/receipt checks. The final payload-label
correction receives an additional Italian rendered check, recorded separately.

Representative screenshots are retained alongside the structured observations.
The full transient screenshot set is not presented as a retained artifact. Native
zoom full-page captures from Playwright were clipped by its capture dimensions;
they are excluded from retained visual proof. Direct browser viewport captures
are labeled separately and preserve the measured native zoom.

## Preserved unsuccessful attempts

- The initial shell network sandbox prevented Chromium socket setup and the first
  preview bind. The first full pytest attempt stalled after 80 observed passing
  nodes and was interrupted, not passed. The supported command-scoped network
  permission allowed the owned loopback fixtures and the successful new run.
- The first browser fixture attempted a document preview while AI was Off and
  correctly received a blocked page. The corrected fixture explicitly saves Local
  configuration without enabling a session or obtaining execution authority.
- Early measurements immediately after form navigation ran before CSS load. Those
  preview dimensions are invalid observations, not product regressions. The
  confirmed Components overflow is kept separately in `initial-observations.json`.
  Final measurements wait for page load, network idle and fonts.
- The first keyboard inventory counted descendants of closed `details` elements.
  Its observed tab sequence omitted those hidden controls correctly. The corrected
  expected inventory excludes closed disclosure contents, without changing page
  behavior or tab order. `keyboard-initial.json` retains the first counts.
- The first receipt fixture invoked the pre-app Instance rather than the app-owned
  Instance with the test adapter. It failed its success assertion. The correction
  invokes the actual host Instance; no production validation was weakened.

Earlier Windows, browser-policy and runtime failures remain in the original
qualification record and owner ledger. This Linux environment's success does not
retroactively qualify the previous environment or any Windows desktop.

## Reproduction

The retained scripts are inspection fixtures, not shipped commands. From a clean
repository copy, copy `s07-*.py` into ignored `.agent/`, install Playwright 1.63.0
into `.agent/browser-tools`, and supply Chromium at `/usr/bin/chromium`. Start
`s07-preview-server.py` on loopback port 8047, then run `s07-browser-matrix.py` and
`s07-browser-accessibility.py` sequentially with the repository virtualenv and
`PYTHONPATH=.agent/browser-tools`. Use fresh fixture/profile directories per run;
the scripts deliberately do not erase an existing Instance. The accessibility
script accepts `--keyboard-only` for the corrected inventory check.

Separately start `s07-receipts-server.py` on port 8048 and run
`s07-browser-receipts.py`. This server alone injects fixture-owned locality evidence,
a synthetic adapter and a zero-cost quote; none of those controls is exposed by
the product HTTP interface. Stop the owned servers after inspection. Results go
to `.agent/s07-browser-evidence/`. Production acceptance still uses the repository's
native checks and owner PR's exact-head CI/review/integration gates.
