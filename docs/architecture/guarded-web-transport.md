# Guarded web transport

Provelume `0.7/S04` adds one provider-independent HTTP(S) retrieval boundary for connector web
Sources. It returns a transient response to the invoking application service. It does not acquire
the response, create or change canonical knowledge, persist a cache, schedule work, refresh a
Source or load a real provider adapter. Manual URL acquisition remains `0.7/S05`.

## Explicit authority chain

A request reaches DNS only when every one of these conditions is true at invocation time:

1. the caller supplies `network_authorization: explicit`;
2. the Instance has `network.external_access: true`;
3. the connector is active and enabled, declares `network_access: explicit_only` and
   `manual_read`, and has effective network mode `explicit`;
4. authorization state matches the connector mode: none, a configured external-secret reference,
   or a completed OAuth grant;
5. the selected Source is an active, enabled `web` Source under that connector;
6. the initial request URL is exactly the Source external identity after safe canonicalization;
7. the request origin, including every non-default port, is in that connector's origin allowlist.

Missing, malformed, disabled, removed or internally inconsistent state fails closed. There is no
environment proxy, cookie jar, netrc lookup, ambient credential, alternate endpoint or implicit
network fallback. The transport never dereferences an external credential reference; later
provider-specific adapters may build on this boundary through their own separately qualified
contract.

## URL, origin and port boundary

Only unambiguous ASCII HTTP and HTTPS URLs are accepted. The parser rejects userinfo, fragments,
backslashes, whitespace and controls, invalid percent escapes, missing or single-label hosts,
legacy numeric host forms, scoped IPv6 literals, leading-zero ports and every non-HTTP scheme.
IDNs must be supplied in their ASCII IDNA form. The canonical request target retains the exact
path and query, while error output never includes them.

Default HTTP port 80 and HTTPS port 443 are implicit. Every non-default port must occur in the
connector's exact allowed origin. The WHATWG Fetch bad-port set remains blocked even when an
origin tries to allowlist one of those service ports; this prevents the web transport from being
repurposed against mail, DNS, file-transfer, directory, remote-login and similar services.

An HTTPS redirect may not downgrade to HTTP. A redirect may change origin only when the new origin
was already explicitly allowlisted. Conditional request metadata is sent only on the initial hop
and is stripped after every redirect.
Redirect loops, missing or duplicate `Location` headers and chains beyond the configured limits
are rejected.

## DNS and connection pinning

Every hostname is resolved and validated once before connection preparation and again immediately
before the socket is opened. Every returned address must be public; a mixed public/private answer
rejects the whole request. Resolution has an explicit address-count limit.

Validation rejects IPv4 and IPv6 loopback, link-local, private, shared, multicast, reserved,
unspecified and all other non-global destinations. It also inspects IPv4-mapped IPv6, 6to4,
Teredo and well-known NAT64 embedded addresses, and rejects the local-use NAT64 prefix. The same
checks run for every redirect hop.

The connection uses the public IP from the second validation directly, so the HTTP backend cannot
resolve the hostname a third time. HTTPS keeps the separately validated hostname for SNI and
certificate verification, requires the platform trust store and TLS 1.2 or newer, and never falls
back to an unverified connection. A changed DNS answer may proceed only when every newly returned
address is still public; a public-to-non-public change is a typed DNS-rebinding rejection. Each
platform resolver call runs behind both a five-second DNS-stage deadline and the request's shorter
remaining total deadline. A process-wide four-slot cap prevents an unresponsive platform resolver
from causing unbounded worker accumulation; a timed-out call causes no retry or refresh.

## Bounded request and response contract

The default immutable limit contract is:

| Limit | Default | Hard constructor ceiling |
| --- | ---: | ---: |
| Redirects | 5 | 10 |
| HTTP resources in one chain | 6 | 11 |
| Total time | 30 s | 120 s |
| DNS/connect/read stage time | 5 s / 10 s / 15 s | 120 s each |
| URL length | 4,096 characters | 16,384 |
| Resolved addresses per check | 16 | 64 |
| Header count/aggregate bytes | 100 / 64 KiB | 256 / 1 MiB |
| One header name/value | 128 B / 8 KiB | 256 B / 64 KiB |
| Compressed response body | 20 MiB | 100 MiB |
| Decompressed response body | 50 MiB | 250 MiB |
| Decompression ratio | 100:1 after 1 KiB | 1,000:1 |
| Streaming read chunk | 64 KiB | 1 MiB |

The caller may choose stricter validated limits. Wildcard media types are not accepted. The
default closed set covers bounded text, HTML, CSV, Markdown, JSON, XML and PDF retrieval; a future
consumer can supply another explicit closed set without changing transport policy.

Response header names, values, count and aggregate size are validated before body processing.
Duplicate singleton headers, conflicting `Content-Length`/`Transfer-Encoding`, invalid length,
unsupported transfer coding and malformed content type fail closed. A body-bearing response must
be framed by an exact content length or valid chunked coding. Short content, incomplete chunks and
body-bearing no-content/not-modified responses are rejected.

Identity, gzip and zlib-wrapped deflate are the only accepted content encodings. Decompression is
streamed with simultaneous compressed-byte, decompressed-byte and ratio enforcement. Invalid,
truncated, concatenated or trailing compressed streams and every unsupported encoding fail
closed. Error-status bodies are neither consumed into application state nor exposed in an error.

## Conditional metadata and state boundary

`ETag` and `Last-Modified` inputs and outputs use bounded validated syntax. A valid `304 Not
Modified` is accepted only on the initial hop that actually carried a validator and is returned as
a transient bodyless result; the transport does not persist validators, create a cursor, schedule
a retry or infer a refresh cadence.

Every failure is a typed `WebTransportError` with a closed code, fixed safe message and explicit
retryability marker. Errors contain no URL, host, query, credential name, token, local path,
response body or private provider content. The transport itself emits no log or operation record,
so a caller can record only the safe code and message without accidentally serializing sensitive
inputs.

Success and failure leave the complete Instance byte-identical. In particular, S04 creates or
modifies no Source, Document, Acquisition, Version, Original, DerivedArtifact, cursor, health
record or operation evidence. S05 must separately authorize and implement any canonical
acquisition transaction.

## Synthetic and cross-platform qualification

The hostile-network suite injects a resolver, pinned connection factory and response stream. It
opens no socket and exercises direct and DNS-based SSRF, mixed answers, DNS rebinding, redirect
pivots and loops, disallowed ports, malformed headers and framing, status/body conflicts,
timeouts, truncation, oversize bodies, unsupported encoding, malformed compression and
decompression bombs. The same suite runs in the repository's Ubuntu and Windows CI jobs; the real
backend uses only Python cross-platform socket, TLS and HTTP primitives.
