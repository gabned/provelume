# Custodia provider transports (0.12/S03)

Parent #311; S03 #316 follows completed S01 #312 / PR #313 and S02 #314 / PR #315.
`ai_provider.py` and `ai_provider_http.py` define internal, ephemeral adapter contracts.
There is no registry, canonical schema, model selection, persistent job, budget engine,
provider credential store or new dependency. Package/runtime remains 0.11.0 — Cura.

## Supported matrix and qualification

| Profile | Operation and input | Authentication | Qualification |
| --- | --- | --- | --- |
| `chat-json-v1` | One HTTP/1.1 `POST /v1/chat/completions`, bounded text messages, JSON object result | Explicit external `system_keyring` reference resolved by an injected vault, Bearer; or explicitly absent | Synthetic protocol conformance with owned loopback HTTP IPv4/IPv6 fixtures and injected DNS/socket/TLS failures |
| Test-only `SyntheticAdapter` | Same checked call and closed S02 candidate | None; no I/O | Deterministic substitution fixture, excluded from installed package |
| Specific provider/model/deployment | No live contact performed | No real credential accessed | **NOT_RUN**; fixture success does not qualify server behavior, model quality, billing or offline inference |

The normative wire references are the OpenAI [Chat Completions create reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
[JSON mode guide](https://developers.openai.com/api/docs/guides/structured-outputs) and
[Bearer authentication reference](https://developers.openai.com/api/reference/overview#authentication),
consulted 2026-10-03. The profile is a deliberately restricted implementation of those
operations. It is not equivalence with Responses, Ollama native, Azure-specific routes,
other compatible servers or every OpenAI model. Compatibility requires the exact request
and response subset below. No model or endpoint discovery/probe is performed.

The model is the explicit S01 `Profile.model`: lowercase identifier matching
`[a-z][a-z0-9_.-]{0,79}`. Only `(structured_output,)` is admitted. Empty/automatic names,
slash-qualified model identifiers, multiple capabilities and arbitrary extra descriptors
are refused. Names identify configured models, not availability or compatibility evidence.

Requests contain exactly `model`, two `messages` (fixed trusted `system` instructions and
S02's redacted `user` data envelope), `response_format: {type: json_object}`,
`max_completion_tokens` from the effective S01 request limit, `n: 1`, `stream: false` and
`store: false`. No sampling overrides are exposed; the configured server/model defaults
apply and are not a reproducibility claim. No tools, URLs, attachments, files, metadata,
arbitrary headers, session history, user identifiers or provider-specific parameters exist.
JSON mode is only a wire request: the closed S02 validator remains authoritative locally.
`store: false` is a request field, not a claim about a server's complete retention policy.

Responses require status 200, UTF-8 JSON, `object: chat.completion`, the exact configured
`model`, bounded string `id`, nonnegative integer `created`, and one choice at integer
index 0 with `finish_reason: stop`. Its message must have `role: assistant`, string
`content`, and absent/null refusal. Non-null logprobs, tool/function calls, extra message
or top-level authority fields, malformed/duplicate JSON and incomplete completions fail.
Optional envelope usage/service-tier/system-fingerprint metadata cannot influence routing,
limits or output. Usage is always **UNKNOWN** in this profile: unqualified server-reported
counts are not accounting evidence. Byte limits are not token or monetary cost guarantees.

Only `application/json` (optionally `charset=utf-8`), identity encoding and one positive
Content-Length are supported. Streaming/SSE, chunked framing, compression, redirects,
informational responses, tools, vision, audio, embeddings, model lists/downloads, retries,
fallback and response retrieval/cancellation APIs are unsupported. No API translation or
automatic parameter substitution is attempted after an incompatibility.

## Policy, binding and the product barrier

`CallInputs.prepare` uses S02's `prepared_request` and S01's sole `revalidate` resolver.
The transport configuration fingerprint is the S01 profile's `route_revision`; endpoint,
wire profile, destination admission, opaque secret reference and wire limits are therefore
bound into the existing plan. Every call rechecks current version, preview, policy, consent,
template, limits, profile and independent locality evidence before external lookup, after
DNS, after connection and before accepting output. The original binding/configuration must
remain equal throughout; supplying a newly allowed plan during a call cannot replace it.
Off, deny, expired/stale bindings and invalid descriptors fail before secrets, DNS or sockets.
Snapshot provenance remains the trusted host's responsibility, as in S01/S02. There is no
claim of an atomic lock over mutable external policy or a remotely revocable dispatch.

`ProviderAdapter.exchange(current, cancel=...)` is an internal contract exercised only
by test harnesses. Both adapters use `CheckedCall` and return the same `ExchangeResult`:
S02 `ValidatedCandidate` plus content-free ephemeral transport evidence. S01 `BaseReceipt`
retains its existing planned/denied/simulated meaning; S03 does not rewrite old receipts or
pretend they recorded a real transmission. Nothing writes canonical or derived data.

The service has only pure `ai_provider_configuration`, pure `ai_execution_status` and
explicit `ai_connection_diagnostic`. **There is no product inference dispatcher** or
adapter registration, UI route, API or CLI. Plans, previews, adapters and successful
diagnostics cannot enable execution; status always says `disabled_until_s06` / requires
S06. S06 must implement the existing budget/job enforcement before adding a product caller.
S07 owns user surfaces. S04–S09 are not implemented by this slice.

## Endpoint, locality and actual peer

Endpoints are exact ASCII HTTP(S) URLs with `/v1/chat/completions`. Reject whitespace,
controls, userinfo, query, fragment, escapes, backslashes, alternate paths, trailing host
dots, noncanonical numeric IPs/ports and ambiguous authorities. Ports are explicitly
1–65535, or scheme-default 80/443. The complete selected origin/port/path is in the binding.

| Destination admission | Address admission | Independent execution evidence |
| --- | --- | --- |
| `managed_loopback` | Only canonical loopback IPv4/IPv6; HTTP or HTTPS | S01 LOCAL + MANAGED_OFFLINE qualification bound to this profile, supplied independently by host |
| `explicit_lan` | HTTPS and exact explicitly configured addresses within RFC1918/IPv6 ULA, at most 16 | S01 REMOTE + REMOTE qualification; off-device network permission, never a local-only exception |
| `remote` | HTTPS and existing web-intake strict public-address predicate | S01 REMOTE + REMOTE qualification |
| `unknown` | No connection permitted | Unqualified locality cannot dispatch or diagnose |

A URL, private address, provider name or protocol compatibility never proves inference
is offline. LAN admission is a network destination category, not managed inference.
Managed evidence is represented and checked, not manufactured here; the actual managed
runtime/no-egress qualification belongs to S05. An external server can perform secondary
egress or route upstream, which this client cannot observe. No such assurance is advertised.
HTTP is limited to independently admitted managed loopback; it provides no TLS protection
against a hostile local process. Remote/LAN TLS certificate and hostname verification
remain enabled with system trust and TLS >=1.2; there is no verify-false profile option.

One DNS resolution is evaluated per explicit operation. All answers (at most 16) must be
admitted; an answer set mixing approved/public and private/unauthorized IPs is refused.
Mixed IPv4/IPv6 is allowed only when every address belongs to the admitted class. Scoped,
mapped and tunnel address forms are rejected; remote checks reuse the strict existing
public-IP predicate including translation special cases. One deterministic numeric address
is connected directly, with no second hostname resolution and no retry on another answer.
The socket's actual peer address **and port** are compared before credentials/HTTP are sent,
and again after TLS; SNI/certificate identity stays the originally configured hostname.
DNS rebinding after lookup cannot change that socket destination. A later explicit call
resolves anew and validates all answers again. This observes the OS peer, not packets past
a transparent OS/network intermediary or the server's own egress.

No redirects are followed, including same-origin redirects. Location and response bodies
are never copied into errors. No proxy, tunnel, netrc, environment provider key or ambient
authentication is inherited: direct numeric sockets and explicit headers are used. Provider
LAN/loopback admissions are confined to this profile. Existing web-intake SSRF policy and
transport are unchanged; their regression suite still rejects those destinations.

## External secrets and bounded lifetime

`CredentialReference` reuses connector `normalise_secret_reference` kind/name grammar,
but accepts only `system_keyring`, with an explicitly injected external resolver. It never
reads a real vault, provider environment variable, personal file or Instance configuration.
The resolver must return an active `SecretLease` matching the exact opaque reference,
profile fingerprint and transport fingerprint. It is rechecked immediately before sending;
observed revocation or token rotation refuses that call without authentication retry.
Missing, revoked, unrelated, control-bearing
or oversized tokens fail closed. No resolver is invoked for explicit no-auth profiles or
connection diagnostics. Only synthetic vaults/tokens are used for conformance.

Resolution is an observation, not a guarantee against revocation immediately afterward;
server authentication failures remain distinct. No token enters configuration records,
manifests, exports, backups, receipts, logs or error messages. Token values and headers are
ephemeral process memory. Python strings, buffers, exception frames and OS/runtime copies
may outlive local references: secure erasure is **not** promised. Neither credentials nor
context bodies may be logged by a future caller or injected vault. Ordinary diagnostics
report only closed codes/booleans, never endpoints, peer IPs, private response text or keys.

## Limits, failure phases and cancellation

Wire limits default to 64 KiB request / 64 KiB response, 8 KiB total headers, 32 headers,
2048 bytes per header/status line and 10 seconds. Closed maxima are 1 MiB / 256 KiB,
16 KiB headers, 64 headers, 4096-byte lines and 30 seconds. The actual request is also
capped by S01's stricter `max_input_bytes`, and time by S01's `max_seconds`. JSON is encoded
incrementally with a byte bound before lookup/send. No provider output raises any ceiling.
Status/header bytes are bounded **as received**; body Content-Length is checked before
allocation and reads are capped to remaining bytes. Premature EOF, invalid framing,
encoding or output schema cannot become a candidate. The connection is always closed.

Cancellation and one monotonic deadline govern vault/DNS waits, connect, TLS, partial sends
and reads. Socket operations are nonblocking with at most 50 ms between cancellation checks.
OS DNS and an injected vault callback cannot be forcibly stopped portably; caller waiting
ends, late results cannot start a connection, and at most one unfinished worker per lookup
kind is permitted. A blocked worker refuses later lookups until it finishes. This is a
bounded local wait, not remote cancellation or secure cleanup of worker memory.

Errors distinguish configuration/policy, credential, DNS/destination, connection/TLS,
authentication, rate limit, timeout/cancel, size/truncation, redirect and incompatibility.
Transport evidence distinguishes `not_sent`, `possibly_sent_remote_outcome_unknown`, and
`response_received` for a completely validated result. The first send attempt marks possible
transmission conservatively, including partial-header failure; every subsequent failure
retains uncertainty. Even an HTTP error does not prove no remote work or charge occurred.
No retry, replay, alternate address, alternate adapter or fallback is executed. Retry-After
is not execution authority. S06 owns durable attempts, budget reservation and recovery.
Cancellation closes local work but cannot retract sent data, remote execution or billing.

## Development evidence

Run the five-case demonstration with the native environment:

```text
.venv/Scripts/python.exe -m pytest -q tests/test_ai_provider.py::test_executable_s03_demonstration
```

Use `.venv/bin/python` on POSIX. `tests/test_ai_provider.py` covers the actual socket
implementation, substitutions, denial before effects, wire failures, DNS/peer pinning,
secret isolation, bounded cancellation and the product barrier; S01/S02 (including
self-overlapping redaction literals), guarded-web and full deterministic suites remain
required. Local fixture conformance is not a live provider qualification. Preserve the
known S02 Windows local 540-second/DPAPI/long-path failure as an actual failure if reproduced;
the accepted independent full native Linux/Windows CI path supplies platform qualification.
All exact-head CI, source pin, complete-delta effects, policy-before-binding, reviews,
findings, ancestry and expected-head merge/post-merge checks remain mandatory.
