# Concordia S02: saved language readback

Issue [#377](https://github.com/gabned/provelume/issues/377) reported that saving
Italian left the selector displaying System while preference export contained
`"language": "it"`. The observed installation identified source
`4b3b6c8d85769b8726355e69415071397b6eee47`; its installed integrity was not
independently attested by that report.

## Existing correction

Accepted commit `b796a9826597653cee0011b0a480d4065d71a997` already adds the saved
language to `LauncherSettings.public_view()["shell"]`. It is an ancestor of the
S02 starting main, `99e49ad5d58f8162c3b4395c9c002ac99bcfa473`. The shared settings
template reads that value for both its language selector and the hidden field
used when changing the theme. Persistence and export already had the value.

Without this projection, no explicit language option is selected and an HTML
single-select defaults to its first option, System. S02 retains the existing
runtime correction and extends its regression coverage; it does not add another
preference writer or change language resolution.

## Source regression matrix

`tests/test_custodia_language_preferences.py` exercises all eight choices in both
Current and Cura (`preview`): System, English, Italian, German, Spanish, French,
Portuguese and Romanian. For each combination it verifies:

- Exactly one selected option in the actual `shell-language` control, with all
  eight choices present. A selected option elsewhere in the page is insufficient.
- A language-only POST followed by the actual redirect and readback. Other saved
  settings change only by the expected revision increment; Instance configuration
  remains unchanged. Endpoint, login-startup and network-related writers are fenced.
- Agreement between the saved value, public shell view and official preference
  export, including every other exported preference.
- A different URL language changes the rendered page language without changing
  the saved selector value. System remains System when its effective locale is
  Italian, rather than being rewritten to `it`.
- Returning through preferences, reopening without a URL override and recreating
  the application against the same settings retain the selected value. These reads
  do not rewrite the settings file. A consumed save nonce remains rejected.

The System case uses an explicitly controlled synthetic Italian host locale;
it does not attest the locale of a Windows installation. Existing invalid-field,
authority, CSRF, nonce and theme-form controls remain in place.

## Execution and limits

Run the focused source controls with the canonical environment:

```text
python -m pytest -q tests/test_custodia_language_preferences.py tests/test_shell_settings.py tests/test_cura_s09_preferences.py tests/test_cura_preferences.py
```

The S02 PR ledger records the exact committed source, full native suite, CI,
reviews and integration results. Source tests are not native Windows/browser or
human qualification, linguistic review, installer-upgrade proof or evidence for
the final 0.15 artifact.

The maintainer's [1 November decision](https://github.com/gabned/provelume/issues/383#issuecomment-6555381204)
allows S02 to start without the S01 manual qualification. S01 remains suspended
and not accepted, its missing observations remain NOT_RUN and its CPU findings
remain CURRENT. No publication or application-version change follows from S02.
