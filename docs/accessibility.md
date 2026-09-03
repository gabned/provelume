# Browser and Windows shell accessibility baseline

Unreleased S07 applies one EN/IT accessibility baseline to the Knowledge Browser and installed
Windows shell. It does not change public version identity.

- Keyboard: skip link, native links/buttons/selects/details and tray menu; logical DOM/focus order;
  no focus trap outside a true modal native dialog.
- Structure: one useful page heading, header/navigation/main/footer landmarks, grouped primary
  navigation and explicit content/status/configuration/maintenance/support labels.
- Names: icons are supplementary; every control/action/status has visible text and an accessible
  name in EN and IT. Help text is associated with endpoint validation.
- Feedback: successful changes use a polite atomic live region; errors use `role=alert`; service,
  warning, error, setting, destructive action and diagnostics remain textually distinct.
- Vision: visible focus, light/dark contrast variables, system theme, Windows forced colors,
  200% zoom/reflow and no color-only state.
- Motion: `prefers-reduced-motion` collapses animations/transitions and disables smooth scrolling.
- Content safety: autoescape plus script-free CSP makes markup, URLs, formulas, terminal escapes and
  script-like payloads inert. There is no CDN, remote font, analytics or remote theme asset.

Permanent regressions inspect semantic EN/IT parity, skip/navigation landmarks, form labels,
live/error regions, explicit themes, forced-colors and reduced-motion CSS, native tray label parity
and inert hostile names. A manual release candidate still needs keyboard, Narrator/screen-reader,
high-contrast, zoom/reflow and DPI evidence on the exact artifact; source tests alone are not a
claim that such an artifact has passed.

The `0.10/S07` Perceptio page applies the same baseline to its mixed-media journey. Family support
uses a native table with row and column headers; exact identities and states remain textual;
metadata, uncertainty, corrections and anchors use keyboard-operable native disclosure controls.
The empty state remains a paragraph in the page structure. Malicious or prompt-like profile text
is escaped rather than interpreted. EN and IT add the same semantic catalog keys, and the permanent
Ubuntu/Windows Perceptio smoke checks those invariants. Final screen-reader, forced-colour,
200% reflow and DPI observations remain exact-artifact release gates.
