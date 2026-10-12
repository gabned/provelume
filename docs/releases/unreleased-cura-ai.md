# Unreleased — Cura and local AI completion

> Historical preparation/qualification record. Its original source identities,
> failures, Unreleased statements and missing-material limits are preserved below.
> The finite follow-up was subsequently delivered in
> [0.12.1 Custodia Preview](0.12.1.md), published and ready on
> 2026-10-12 from `cd7dc64f3ffb2a17689018b3350f0e1c073abdd4`.


This finite follow-up to published **0.12.0 Custodia** includes #339/#340,
implemented in #341 and corrected/qualified in #342, plus the Windows tray and
local-panel corrections integrated through #344. It is not a release identity.
Package/runtime version and codename remain **0.12.0 / Custodia**; no new tag,
dated changelog entry or publication is assigned here. The proposed next version
is **0.12.1**, subject to a separate identity-setting preparation: the scope fixes
and completes Custodia journeys without adding a new capability or taking the
forecast 0.13.0 Iudicium classification scope. No roadmap shift is needed.

## Included changes

- Automatic model-download progress in both interfaces, cancellation during long
  transfers, fresh completion actions and distinct connection/operation errors.
  Unsaved fields and focus survive updates; observation never repeats a mutation.
- Direct Cura Management entries for AI & Privacy, AI operations, preferences and
  notifications. Document AI journeys return to their original search filters.
- Cura labelled as the standard interface; a reversible guided choice for upgrades
  without selection evidence, respecting an explicit Previous interface choice.
- Bounded local-request admission during idle cleanup and retained closed refusal
  causes; overlapping independent Capture journal I/O with all durable barriers.
- Native qualification retains all startup/warm samples and proves concurrent
  Capture/search overlaps the current request's native inference phase.
- The release pipeline qualifies ordinary AI on its own transferred installer,
  binds source/version/channel/tag and installer hash/size, and includes its report
  in the checksum-covered bundle before the publisher can run.
- Upgrade/preservation qualification also starts from the immutable public 0.12.0
  installer and matching wheel, retaining the 0.10.0/0.10.1/0.11.0 baselines.
- Windows distinguishes the browser application from the native local panel,
  explains service actions, stacks controls at high DPI and corrects Light/Dark
  channel controls and menus while respecting system high-contrast colors.

No classification, RAG, new connector/provider/model, autonomy, consent change or
new renderer enters this follow-up. All earlier failures and unobserved hardware
remain in the [functional audit](../qualification/cura-ai-completion.md) and
[release preparation record](../qualification/unreleased-cura-ai.md).

## Finding AI and choosing the interface

1. Open **Management → AI & Privacy**. Explicitly permit network access for a
   download, or use offline import. Follow progress and use Cancel when needed.
   Connection loss is an observation problem: a status refresh does not restart
   acquisition or enable AI.
2. Verify/test the acquired model, then explicitly enable local AI for the session.
   Completion alone grants no session permission; restart leaves AI off.
3. Open a document from **Knowledge** or **Search**, select **Document synthesis**,
   review the exact Version/text, scope and private preview, and explicitly consent.
   Results, references and receipts are reachable through **Management → AI operations**.
   Returning to Search preserves the original filters.
4. For an older layout, use the guided notice or **Shell settings → Interface**,
   choose **Cura · standard interface**, and save. Choose **Previous interface**
   there to roll back. The layout choice preserves Instance, knowledge, language,
   theme and AI/network permissions. Pages use the selection on navigation/reload.

The existing [local profile](../qualification/custodia-local-profile.md),
[Windows guide](../windows-preview.md) and
[publication installation guide](../publication-installation.md) still apply.
The final version's complete installation kit will be the upgrade destination;
the present development bundle is not that kit. The older 0.10.1 schema-1 updater
still needs its documented manual complete-kit transition.

## Windows application and local panel

In Italian, **Apri Provelume** opens the application in your browser;
**Pannello locale** opens the native launcher. The panel controls the local service,
Instance selection and updates. Stopping the service differs from selecting an
Instance or closing the panel according to the saved tray preference. At high DPI,
actions stack and the lower controls remain reachable by scrolling.

The automatic Windows layout probes cover seven languages, four DPI settings and
System/Light/Dark themes across four public upgrade baselines. Their results do
not attest human visual review, Narrator, a real high-contrast host or linguistic
quality. Published 0.12.0 remains unchanged; this behavior belongs to Unreleased.

## Independent release gates

The preparation owner qualifies one unchanged source head through native checks,
exact-head CI/reviews, deterministic/offline rebuild and installed observations.
After normal expected-head merge, actual main requires its own workflow inventory.

A separately authorized identity change must align package/runtime, embedded build,
Windows update metadata, versioned notes and changelog. The permanent official
workflow then binds that reviewed main/tag to freshly qualified **official**
payloads. Its installed AI job uses the same Windows installer later assembled;
development results cannot be carried over as official artifact qualification.

Publication separately requires complete checksums, SBOM, assurance and provenance,
unchanged public-byte readback, actual-publication receipt and exact-version outer
kit, their attestations, and an observed installation-readiness marker. A successful
dry run, embedded official metadata or uploaded marker alone proves none of these.
#340 remains open until its changes and #339 are delivered in that same release.
