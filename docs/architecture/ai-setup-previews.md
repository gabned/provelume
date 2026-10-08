# AI setup, private previews and receipts

S07 (#324), under parent #311, composes the S01–S06 contracts in the existing
Browser. This is an implementation contract, not an integration or qualification
receipt. Package/runtime/public preview remains 0.11.0 — Cura. S08 document
synthesis and S09 Recommended promotion are outside this change.

| Existing surface | Route | Authority and effects |
| --- | --- | --- |
| Settings → AI & Privacy | `/settings/ai` | Read configuration, registry metadata and durable controls. No DNS, credential lookup, model loading or download on GET. |
| Document Viewer → AI preview | `/documents/{document_id}/ai` | Select an existing bounded text representation/page and character interval for the current exact Version. Private POST preview only. |
| Action Center → Operations → AI | `/operations/ai` | Privacy-safe S06 job state, attempt accounting, controls and terminal receipts. |
| Components, models & licenses | `/components` | Existing inventory and a link to the same registry-backed setup. No alternate catalogue. |

## Separate grants

`AiSetup` belongs to one selected Instance. The default is Off. Saving Off, Local,
External or explicitly ordered Hybrid persists an Instance-bound configuration
revision in `state/scheduler/ai-setup.json`; it disables execution and invalidates
the session's previews. Saving does not acquire weights, unlock a vault, test an
endpoint, create a job or dispatch work. Monetary hard caps remain zero; unknown
external pricing cannot pass admission. Resource units use S06's byte/token proxy,
not a promise of exact tokenizer counts or financial estimates.

Model actions are explicit bounded background calls to ModelStore and LocalRuntime.
Selecting a runtime directory verifies the exact installed locked library inventory;
the private path is session-only. Model acquisition/import, byte verification,
self-test and activation are separate actions. Installation uses the existing
download cancellation callback and reports bytes actually received. Import has no
invented percentage. Cancellation intent remains visible until the operation exits.
The server validates available actions again, regardless of browser controls.

Self-test is the native 60-second contract. A passed process is not locality proof.
The product host grants local evidence only from the observed managed Linux seccomp
control. Bare Windows remains unqualified for local dispatch. The independent
disposable Windows CI observer can establish its existing WFP proof in the test
harness; there is no product URL, form field or environment switch granting that
authority. No PC security change is part of setup. S04 synthetic self-test retains
its separate 30-second limit. The Recommended choice remains a candidate, with no
S09 promotion badge. Arbitrary BYOM is not advertised as compatible.

External configuration uses S03's closed compatible HTTPS profile and credential
reference, without live discovery. This revision does not manufacture remote
qualification or a defensible quote from a URL. An unqualified provider, missing
credential or unknown price fails closed. External and Hybrid demonstrations use
test-owned transports and evidence; they do not qualify a real provider.

## Preview and consent

The private preview includes S02's payload/redaction, exact Version, selection,
coverage within the admitted representation, limits and fingerprints, followed by
the S01 route plan. It does not claim coverage of the Original or representations
outside that inventory. Document previews never yield an executable reference.
Only the fixed public synthetic connection fixture can receive S07 consent.

Synthetic consent is short-lived (600 seconds), bounded to 32 private previews per
Instance host, and bound to configuration, generation, context, redaction, template,
profiles, evidence, route and limits. Consent is checked inside the S06 authority
transaction. Enqueue is separately explicit and idempotent for that preview;
dispatch is another explicit Operations action. The ordinary scheduler cycle does
not admit AI implicitly. Current authority is checked again during S06 polling.
Disabling, changing configuration or losing evidence invalidates old authorization.
Refresh, back navigation and duplicate forms cannot create another grant: forms
reuse the existing bounded nonce mechanism, CSRF and local Browser access policy.

## Receipts and persistence

Normal lists expose references, bindings, routes, attempts, reservations, known
usage and uncertainty. They omit private payloads/results, filesystem paths and
credentials. Template autoescaping treats provider names and other text as data.
Private preview responses use `Cache-Control: no-store` and `Referrer-Policy:
no-referrer`. Error responses use closed diagnostics rather than exception details.

UNKNOWN retains liability. An uncertain possible send has no automatic retry or
fallback. Reconciliation records separately retained stop evidence and explicit
duplicate-risk acknowledgement through S06; it neither refunds unknown usage nor
requeues a job. External cancellation cannot retract already transmitted content.
The lifecycle cancellation callback and S06 worker cleanup remain authoritative.

Portable scheduler validation recognizes the closed configuration schema. Runtime
paths, model bytes, secret values, private previews and self-test evidence are not
part of this file. Reopening creates no consent and does not authorize a session;
S06 restore forces execution off and preserves uncertainty and accounting.

After ASGI request draining, shutdown stops new scheduler cycles and joins the
running cycle before revoking the in-memory session and previews and requesting
AI cancellation. This lets a stopped AI task settle its attempt without competing
with the scheduler's lifecycle barrier. The Browser joins its AI tasks before
persisting Off. The existing lifecycle barrier remains nonblocking;
an unrelated owner can still refuse the persistent write. Runtime cleanup runs even
if that write fails, and reopening still cannot restore session authorization.

While the native worker is silent, authority polling uses a 100 ms wait. A worker
message wakes that wait immediately; current authority is still read on every poll
and before accepting completion. This reduces metadata contention with Capture
without caching mutable policy or changing the two-second cancellation/cleanup gate,
model configuration, CPU budget or ADR measurement thresholds.

On Windows the inference worker yields scheduling priority to ordinary foreground
work through Job Object below-normal priority. Only the disposable Windows worker
is changed; the application process and Linux retain their inherited priority.
Windows observations include the effective worker priority.
The same two-CPU affinity, model, thread count, containment and fixed ADR latency
and capture/search thresholds still apply to fresh native qualification.

## Reproduction and qualification

Run `python scripts/demonstrate_ai_setup.py` in the bootstrapped environment. It
uses public synthetic fixtures, the real HTTP controls and existing S06 process
contention/crash tests. For this targeted Windows demonstration, supply fresh
`--basetemp` and pytest cache directories when process identities differ. For the
full suite, let the canonical supervisor allocate separate shard temporaries;
never share a `--basetemp` through `PYTEST_ADDOPTS` across its child processes.

The existing `ai-runtime-candidate.yml` observer additionally invokes
`qualify_ai_setup.measure_setup`: real locked model/runtime, S07 configuration,
self-test/activation, private preview, consent, S06 job execution and receipts on
native Windows/Linux. Its separate `s07_setup` gate retains source/runtime/model
identities and the same ADR 0031 latency/memory limits; network observation covers
the additional workers. A prior S06 PASS is not substituted for this measurement.

Full native pytest, Ruff, exact-head CI, complete review/finding inventories,
rendered UI observations and actual-main checks still gate integration. See the
[S07 qualification record](../qualification/custodia-s07-setup.md) for actual results.
