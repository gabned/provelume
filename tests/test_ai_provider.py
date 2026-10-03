"""S03 conformance uses synthetic data and owned sockets only; no live provider."""

import json
import socket
import ssl
import threading
import time
from dataclasses import replace

import pytest
from ai_context_fakes import candidate
from ai_provider_fakes import (
    SYNTHETIC_SECRET,
    SyntheticAdapter,
    SyntheticVault,
    changed_rules,
    completion,
    local_server,
    provider_case,
    response,
)

from provelume import ai_provider_http as http
from provelume.ai_contract import AiContractError, Capability, Mode, Outcome, digest
from provelume.ai_provider import (
    CredentialReference,
    Destination,
    Failure,
    ProviderConfig,
    ProviderError,
    Transmission,
    WireLimits,
    admit_address,
    endpoint,
    validate_configuration,
)
from provelume.ai_provider_http import Cancellation, ChatJsonAdapter, SecretLease
from provelume.service import ProvelumeInstance
from provelume.web_transport import WebTransportDestinationError, _public_ip


def no_effect(*args, **kwargs):
    pytest.fail("unexpected external effect")


def invoke(inputs, *, vault=None, resolver=no_effect, cancel=None):
    return ChatJsonAdapter(credentials=vault or SyntheticVault(), resolver=resolver).exchange(
        lambda: inputs, cancel=cancel or Cancellation()
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///v1/chat/completions",
        "https://user:password@example.test/v1/chat/completions",
        "https://example.test/v1/chat/completions?key=secret",
        "https://example.test/v1/chat/completions#",
        "https://example.test/v1//chat/completions",
        "https://example.test/v1/chat/../completions",
        "https://example.test:0443/v1/chat/completions",
        "https://example.test:0/v1/chat/completions",
        "https://example.test:65536/v1/chat/completions",
        "https://example.test./v1/chat/completions",
        "HTTPS://example.test/v1/chat/completions",
        "https://EXAMPLE.test/v1/chat/completions",
        "https://127.1/v1/chat/completions",
        "https://0x7f.0.0.1/v1/chat/completions",
        "https://2130706433/v1/chat/completions",
        "https://0177.0.0.1/v1/chat/completions",
        "https://[fe80::1%25eth0]/v1/chat/completions",
        "https://example.test\\other/v1/chat/completions",
        " https://example.test/v1/chat/completions",
        "https://examplé.test/v1/chat/completions",
        "https://example.test/v1/chat/completions\n",
        "https://example.test",
        "https://example.test/v1/responses",
        "https://example.test:/v1/chat/completions",
    ],
)
def test_closed_endpoint_grammar(url):
    with pytest.raises(ProviderError, match=Failure.CONFIG):
        endpoint(url)


def test_descriptor_models_capabilities_and_unknown_fields():
    inputs = provider_case()
    assert ProviderConfig.from_mapping(inputs.config.as_record()) == inputs.config
    for change in (
        {"secret": SYNTHETIC_SECRET},
        {"wire": "responses"},
        {"schema_version": 2},
        {"credential": {"kind": "environment", "name": "SECRET"}},
    ):
        with pytest.raises((ProviderError, AiContractError)):
            ProviderConfig.from_mapping({**inputs.config.as_record(), **change})
    for model in ("", "model/with-slash", "Automatic", "a" * 81, None):
        with pytest.raises(AiContractError):
            replace(inputs.profiles[0], model=model)
    for capabilities in (
        (Capability.VISION,),
        (Capability.TOOL_CALLING,),
        (Capability.STRUCTURED_OUTPUT, Capability.EMBEDDINGS),
    ):
        with pytest.raises(ProviderError):
            validate_configuration(
                replace(inputs.profiles[0], capabilities=capabilities), inputs.config
            )
    with pytest.raises(ProviderError):
        validate_configuration(inputs.profiles[0], replace(inputs.config, credential=None))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: changed_rules(c, mode=Mode.OFF, route=()),
        lambda c: changed_rules(c, deny=True),
        lambda c: replace(c, plan=replace(c.plan, binding=digest("expired"))),
        lambda c: replace(c, config=replace(c.config, credential=None)),
        lambda c: replace(
            c,
            source=replace(
                c.source, version=replace(c.source.version, version_id="changed_version")
            ),
        ),
    ],
)
def test_off_deny_stale_invalid_before_credentials_dns_transport(monkeypatch, mutation):
    monkeypatch.setattr(http, "_connect", no_effect)
    inputs = mutation(provider_case())
    with pytest.raises(ProviderError):
        invoke(inputs, vault=no_effect)


def test_locality_and_explicit_lan_do_not_relax_web_ssrf():
    cases = [
        (
            ProviderConfig("http://localhost/v1/chat/completions", Destination.MANAGED),
            ("127.0.0.1", "::1"),
            ("10.1.2.3", "8.8.8.8"),
        ),
        (
            ProviderConfig(
                "https://lan.example/v1/chat/completions",
                Destination.LAN,
                lan_addresses=("10.1.2.3", "fd00::1"),
            ),
            ("10.1.2.3", "fd00::1"),
            ("10.1.2.4", "127.0.0.1", "8.8.8.8"),
        ),
        (
            ProviderConfig("https://remote.example/v1/chat/completions", Destination.REMOTE),
            ("8.8.8.8", "2606:4700:4700::1111"),
            ("127.0.0.1", "::1", "169.254.169.254", "::ffff:127.0.0.1", "64:ff9b::7f00:1"),
        ),
    ]
    for config, allowed, refused in cases:
        for address in allowed:
            assert admit_address(config, address) == address
        for address in refused:
            with pytest.raises(ProviderError):
                admit_address(config, address)
        assert provider_case(config=config).prepare()
    for private in ("127.0.0.1", "::1", "10.1.2.3", "fd00::1"):
        with pytest.raises(WebTransportDestinationError):
            _public_ip(private)
    unknown = ProviderConfig("https://unknown.example/v1/chat/completions", Destination.UNKNOWN)
    inputs = provider_case(config=unknown)
    assert inputs.plan.outcome == Outcome.DENIED
    with pytest.raises(ProviderError):
        invoke(inputs, vault=no_effect)
    # LAN is off-device, never independently qualified managed/offline inference.
    lan = provider_case(config=cases[1][0])
    with pytest.raises(ProviderError):
        invoke(changed_rules(lan, local_only=True), vault=no_effect)
    with pytest.raises(ProviderError):
        invoke(
            replace(
                lan,
                current={
                    **lan.current,
                    "snapshot": replace(lan.current["snapshot"], external_access=False),
                },
            ),
            vault=no_effect,
        )


@pytest.mark.parametrize(
    "addresses",
    [
        ("8.8.8.8", "127.0.0.1"),
        ("2606:4700:4700::1111", "::1"),
        (),
        ("8.8.8.8", "fd00::1"),
        ("invalid",),
        ("8.8.8.8",) * 17,
    ],
)
def test_dns_mixed_invalid_or_excessive_refused_before_connection(monkeypatch, addresses):
    inputs = provider_case(
        config=ProviderConfig("https://remote.example/v1/chat/completions", Destination.REMOTE)
    )
    monkeypatch.setattr(http, "_connect", no_effect)
    with pytest.raises(ProviderError):
        invoke(inputs, resolver=lambda *_: addresses)


def test_rebinding_cannot_change_numeric_connection_target(monkeypatch):
    inputs = provider_case(
        config=ProviderConfig("https://remote.example/v1/chat/completions", Destination.REMOTE)
    )
    queries, targets = [], []

    def resolver(*args):
        queries.append(args)
        return ("8.8.8.8", "2606:4700:4700::1111") if len(queries) == 1 else ("127.0.0.1",)

    def connect(target, address, control):
        targets.append((target.host, address))
        raise OSError("synthetic connect failure")

    monkeypatch.setattr(http, "_connect", connect)
    with pytest.raises(ProviderError, match=Failure.CONNECTION):
        invoke(inputs, resolver=resolver)
    assert len(queries) == len(targets) == 1
    assert targets[0] == ("remote.example", "2606:4700:4700::1111")


def test_peer_mismatch_before_http_secret_send(monkeypatch):
    class WrongPeer:
        def getpeername(self):
            return ("127.0.0.2", 44859)

        def close(self):
            pass

        send = no_effect

    monkeypatch.setattr(http, "_connect", lambda *_: WrongPeer())
    with pytest.raises(ProviderError, match=Failure.DESTINATION) as error:
        invoke(provider_case())
    assert error.value.transmission == Transmission.NOT_SENT


@pytest.mark.parametrize("kind", ["missing", "revoked", "wrong_profile", "wrong_ref", "invalid"])
def test_external_secrets_fail_closed_before_dns_and_do_not_echo(monkeypatch, kind):
    monkeypatch.setattr(http, "_connect", no_effect)

    def vault(ref, profile, transport):
        if kind == "missing":
            raise RuntimeError(SYNTHETIC_SECRET)
        return SecretLease(
            CredentialReference("system_keyring", "other") if kind == "wrong_ref" else ref,
            digest("other") if kind == "wrong_profile" else profile,
            transport,
            "bad\r\nsecret" if kind == "invalid" else SYNTHETIC_SECRET,
            kind != "revoked",
        )

    with pytest.raises(ProviderError) as error:
        invoke(provider_case(), vault=vault)
    assert error.value.code == Failure.CREDENTIAL
    assert SYNTHETIC_SECRET not in str(error.value) + repr(error.value)


@pytest.mark.parametrize("ipv6", [False, True])
def test_real_http_round_trip_and_substitution_without_policy_or_task_change(ipv6):
    holder = {}
    with local_server(lambda _: response(completion(holder["inputs"])), ipv6=ipv6) as server:
        inputs = holder["inputs"] = provider_case(server["url"])
        before = (inputs.source, inputs.preview, inputs.plan, inputs.current.copy())
        real = invoke(inputs)
        fake = SyntheticAdapter().exchange(lambda: inputs, cancel=Cancellation())
        assert real.candidate == fake.candidate
        assert real.candidate.authority == "untrusted_data_only"
        assert real.receipt["transmission"] == Transmission.RESPONSE
        assert fake.receipt["transmission"] == Transmission.NOT_SENT
        assert real.receipt["usage"] == "UNKNOWN"
        assert real.receipt["binding"] == fake.receipt["binding"] == inputs.plan.binding
        assert (inputs.source, inputs.preview, inputs.plan, inputs.current) == before
        assert len(server["requests"]) == 1
        header, body = server["requests"][0]
        assert b"Authorization: Bearer " + SYNTHETIC_SECRET.encode() in header
        assert body["model"] == inputs.profiles[0].model
        assert body["max_completion_tokens"] == inputs.plan.limits.max_output_tokens
        assert body["stream"] is body["store"] is False and body["n"] == 1
        assert body["response_format"] == {"type": "json_object"}
        assert "PRIVATE" not in json.dumps(body) and "ada@example.test" not in json.dumps(body)
        assert [m["role"] for m in body["messages"]] == ["system", "user"]
        assert SYNTHETIC_SECRET not in json.dumps(real.receipt)


@pytest.mark.parametrize(
    "status,code",
    [
        (301, Failure.REDIRECT),
        (307, Failure.REDIRECT),
        (308, Failure.REDIRECT),
        (401, Failure.AUTH),
        (403, Failure.AUTH),
        (429, Failure.RATE_LIMIT),
        (500, Failure.REMOTE),
        (404, Failure.INCOMPATIBLE),
    ],
)
def test_status_errors_never_follow_redirect_retry_fallback_or_retain_body(status, code):
    with (
        local_server(no_effect) as sink,
        local_server(
            lambda _: response(
                SYNTHETIC_SECRET.encode(),
                status=status,
                headers=(("Location", sink["url"]), ("Retry-After", "0")),
            )
        ) as server,
    ):
        with pytest.raises(ProviderError) as error:
            invoke(provider_case(server["url"]))
        assert error.value.code == code
        assert error.value.transmission == Transmission.POSSIBLE
        assert SYNTHETIC_SECRET not in str(error.value)
        assert len(server["requests"]) == 1 and not sink["connections"]


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"HTTP/1.1 200 OK\r\nX: " + b"a" * 4096, Failure.LIMIT),
        (b"HTTP/1.1 200 OK\r\n" + b"X: y\r\n" * 33 + b"\r\n", Failure.INCOMPATIBLE),
        (b"HTTP/1.1 200 OK\n\n", Failure.INCOMPATIBLE),
        (response(b"{}", headers=(("Content-Encoding", "gzip"),)), Failure.INCOMPATIBLE),
        (response(b"{}", headers=(("Transfer-Encoding", "chunked"),)), Failure.INCOMPATIBLE),
        (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 999999\r\n\r\n",
            Failure.LIMIT,
        ),
        (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 30\r\n\r\n{}",
            Failure.TRUNCATED,
        ),
        (response(b"\xff"), Failure.INCOMPATIBLE),
        (response(b'{"broken":'), Failure.INCOMPATIBLE),
        (response(b'{"a":1,"a":2}'), Failure.INCOMPATIBLE),
    ],
)
def test_bounded_headers_body_encoding_json_and_truncation(raw, code):
    with local_server(lambda _: raw) as server:
        with pytest.raises(ProviderError) as error:
            invoke(provider_case(server["url"]))
        assert error.value.code == code
        assert error.value.transmission == Transmission.POSSIBLE


def test_request_limits_before_credentials():
    inputs = provider_case()
    config = replace(inputs.config, limits=replace(inputs.config.limits, request_bytes=1))
    inputs = provider_case(config=config)
    with pytest.raises(ProviderError, match=Failure.LIMIT):
        invoke(inputs, vault=no_effect)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda i: candidate(i.preview, tools=["read_file"]),
        lambda i: candidate(i.preview, references=[999]),
        lambda i: candidate(i.preview, schema_version=2),
        lambda i: candidate(i.preview, preview_fingerprint=digest("old")),
        lambda i: candidate(i.preview, policy="allow", route="https://evil.example"),
    ],
)
def test_hostile_candidates_never_gain_authority(mutation):
    holder = {}
    with local_server(
        lambda _: response(completion(holder["i"], content=mutation(holder["i"])))
    ) as server:
        holder["i"] = provider_case(server["url"])
        with pytest.raises(ProviderError, match=Failure.INCOMPATIBLE):
            invoke(holder["i"])
        assert len(server["requests"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"model": "different"},
        {"object": "response"},
        {"choices": []},
        {"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {}}]},
        {"choices": [{"index": 0, "finish_reason": "length", "message": {}}]},
        {
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "{}", "tool_calls": []},
                }
            ]
        },
    ],
)
def test_incompatible_wire_envelopes(change):
    holder = {}
    with local_server(lambda _: response(completion(holder["i"], **change))) as server:
        holder["i"] = provider_case(server["url"])
        with pytest.raises(ProviderError, match=Failure.INCOMPATIBLE):
            invoke(holder["i"])


def test_post_send_policy_change_refuses_result_without_replay():
    holder = {}

    def handler(_):
        initial = holder["i"]
        holder["i"] = changed_rules(initial, deny=True)
        return response(completion(initial))

    with local_server(handler) as server:
        holder["i"] = provider_case(server["url"])
        with pytest.raises(ProviderError, match=Failure.POLICY) as error:
            ChatJsonAdapter(credentials=SyntheticVault()).exchange(
                lambda: holder["i"], cancel=Cancellation()
            )
        assert error.value.transmission == Transmission.POSSIBLE
        assert len(server["requests"]) == 1


def test_ambient_proxy_auth_and_credentials_are_not_read(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NETRC", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, "http://synthetic-secret@127.0.0.2:1")
    holder = {}
    with local_server(lambda _: response(completion(holder["i"]))) as server:
        holder["i"] = provider_case(server["url"])
        invoke(holder["i"])
        header = server["requests"][0][0]
        assert b"synthetic-secret" not in header and b"Proxy-Authorization" not in header


def test_cancellation_before_lookup_and_during_response_stops_without_replay():
    cancel = Cancellation()
    cancel.cancel()
    with pytest.raises(ProviderError, match=Failure.CANCELLED) as error:
        invoke(provider_case(), cancel=cancel, vault=no_effect)
    assert error.value.transmission == Transmission.NOT_SENT
    cancel = Cancellation()

    def handler(_):
        cancel.cancel()
        return b""

    with local_server(handler) as server:
        with pytest.raises(ProviderError) as error:
            invoke(provider_case(server["url"]), cancel=cancel)
        assert error.value.code == Failure.CANCELLED
        assert error.value.transmission == Transmission.POSSIBLE
        assert len(server["requests"]) == 1


def test_timeout_and_dns_cancellation_bound_local_wait(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def resolver(*_):
        started.set()
        release.wait(2)
        return ("127.0.0.1",)

    inputs = provider_case(
        config=ProviderConfig(
            "http://localhost/v1/chat/completions",
            Destination.MANAGED,
            limits=WireLimits(seconds=1),
        )
    )
    monkeypatch.setattr(http, "_connect", no_effect)
    try:
        begin = time.monotonic()
        with pytest.raises(ProviderError, match=Failure.TIMEOUT) as error:
            invoke(inputs, resolver=resolver)
        assert time.monotonic() - begin < 1.8
        assert error.value.transmission == Transmission.NOT_SENT
    finally:
        release.set()


def test_connection_tls_failures_before_transmission(monkeypatch):
    for exception, code in (
        (OSError("private"), Failure.CONNECTION),
        (ssl.SSLError("private"), Failure.TLS),
    ):

        def fail(*_, exception=exception):
            raise exception

        monkeypatch.setattr(http, "_connect", fail)
        with pytest.raises(ProviderError) as error:
            invoke(provider_case())
        assert error.value.code == code
        assert error.value.transmission == Transmission.NOT_SENT
        assert "private" not in str(error.value)
    context = http._tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_configuration_status_and_diagnostics_do_not_dispatch(monkeypatch):
    inputs = provider_case()
    monkeypatch.setattr(socket, "getaddrinfo", no_effect)
    assert (
        ProvelumeInstance.ai_provider_configuration(inputs.profiles[0], inputs.config)[
            "product_execution"
        ]
        == "disabled_until_s06"
    )
    assert ProvelumeInstance.ai_execution_status() == {
        "enabled": False,
        "reason": Failure.DISABLED.value,
    }
    with pytest.raises(ProviderError, match=Failure.DISABLED):
        ProvelumeInstance.ai_connection_diagnostic(lambda: inputs, cancel=Cancellation())
    with local_server(no_effect) as server:
        inputs = provider_case(server["url"])
        result = ProvelumeInstance.ai_connection_diagnostic(
            lambda: inputs, cancel=Cancellation(), requested=True
        )
        assert result["connection"] == "connected" and result["peer_verified"]
        assert result["authentication"] == result["inference"] == "NOT_RUN"
        assert not server["requests"]
        assert not ProvelumeInstance.ai_execution_status()["enabled"]


def test_executable_s03_demonstration():
    """Five required cases through one contract and an actual owned HTTP server."""
    holder = {}
    with local_server(lambda _: response(completion(holder["i"]))) as server:
        inputs = holder["i"] = provider_case(server["url"])
        real = invoke(inputs)
        fake = SyntheticAdapter().exchange(lambda: inputs, cancel=Cancellation())
        assert real.candidate == fake.candidate
        assert inputs.plan.execution_authorized is False
        vault = SyntheticVault()
        vault.active = False
        with pytest.raises(ProviderError, match=Failure.CREDENTIAL):
            invoke(inputs, vault=vault)
        assert len(server["requests"]) == 1
    with local_server(lambda _: b"") as uncertain:
        with pytest.raises(ProviderError) as error:
            invoke(provider_case(uncertain["url"]))
        assert error.value.transmission == Transmission.POSSIBLE
        assert len(uncertain["requests"]) == 1
    assert not ProvelumeInstance.ai_execution_status()["enabled"]


def test_dns_change_on_later_explicit_call_is_revalidated(monkeypatch):
    inputs = provider_case(
        config=ProviderConfig("https://remote.example/v1/chat/completions", Destination.REMOTE)
    )
    addresses = ["8.8.8.8"]
    connections = []

    def fail(target, address, control):
        connections.append(address)
        raise OSError("fixture")

    monkeypatch.setattr(http, "_connect", fail)
    adapter = ChatJsonAdapter(credentials=None, resolver=lambda *_: tuple(addresses))
    with pytest.raises(ProviderError, match=Failure.CONNECTION):
        adapter.exchange(lambda: inputs, cancel=Cancellation())
    addresses[:] = ["127.0.0.1"]
    with pytest.raises(ProviderError, match=Failure.DESTINATION):
        adapter.exchange(lambda: inputs, cancel=Cancellation())
    assert connections == ["8.8.8.8"]


def test_policy_mutation_during_dns_stops_before_connect(monkeypatch):
    holder = {
        "i": provider_case(
            config=ProviderConfig("https://remote.example/v1/chat/completions", Destination.REMOTE)
        )
    }

    def resolver(*_):
        holder["i"] = changed_rules(holder["i"], deny=True)
        return ("8.8.8.8",)

    monkeypatch.setattr(http, "_connect", no_effect)
    with pytest.raises(ProviderError, match=Failure.POLICY):
        ChatJsonAdapter(credentials=None, resolver=resolver).exchange(
            lambda: holder["i"], cancel=Cancellation()
        )


def test_replacement_allowed_plan_cannot_rebind_inflight_call():
    holder = {}

    def handler(_):
        original = holder["i"]
        config = replace(original.config, limits=replace(original.config.limits, seconds=9))
        holder["i"] = provider_case(config=config)
        assert holder["i"].plan.outcome == Outcome.PLANNED
        return response(completion(original))

    with local_server(handler) as server:
        holder["i"] = provider_case(server["url"])
        with pytest.raises(ProviderError, match=Failure.POLICY):
            ChatJsonAdapter(credentials=SyntheticVault()).exchange(
                lambda: holder["i"], cancel=Cancellation()
            )
        assert len(server["requests"]) == 1


@pytest.mark.parametrize(
    "limit",
    [
        {"header_bytes": 50},
        {"header_count": 1},
        {"line_bytes": 10},
    ],
)
def test_request_headers_bounded_before_dns(monkeypatch, limit):
    config = ProviderConfig(
        "http://localhost/v1/chat/completions", Destination.MANAGED, limits=WireLimits(**limit)
    )
    monkeypatch.setattr(http, "_connect", no_effect)
    with pytest.raises(ProviderError, match=Failure.LIMIT):
        invoke(provider_case(config=config))


@pytest.mark.parametrize("which", ["count", "total"])
def test_distinct_header_count_and_aggregate_limit(which):
    raw = (
        b"HTTP/1.1 200 OK\r\n"
        + b"".join(
            f"X-{i}: {'a' * (400 if which == 'total' else 1)}\r\n".encode() for i in range(33)
        )
        + b"\r\n"
    )
    with local_server(lambda _: raw) as server, pytest.raises(ProviderError, match=Failure.LIMIT):
        invoke(provider_case(server["url"]))


def test_payload_timeout_after_transmission_has_no_replay():
    release = threading.Event()

    def handler(_):
        release.wait(2)
        return b""

    with local_server(handler) as server:
        config = ProviderConfig(server["url"], Destination.MANAGED, limits=WireLimits(seconds=1))
        try:
            with pytest.raises(ProviderError, match=Failure.TIMEOUT) as error:
                invoke(provider_case(config=config))
            assert error.value.transmission == Transmission.POSSIBLE
            assert len(server["requests"]) == 1
        finally:
            release.set()


def test_cancellation_during_secret_lookup_cannot_trigger_future_dns(monkeypatch):
    cancel, release, started = Cancellation(), threading.Event(), threading.Event()

    def vault(ref, profile, transport):
        started.set()
        cancel.cancel()
        release.wait(2)
        return SecretLease(ref, profile, transport, SYNTHETIC_SECRET, True)

    monkeypatch.setattr(http, "_connect", no_effect)
    try:
        with pytest.raises(ProviderError, match=Failure.CANCELLED) as error:
            invoke(provider_case(), vault=vault, cancel=cancel)
        assert started.is_set()
        assert error.value.transmission == Transmission.NOT_SENT
    finally:
        release.set()
        # Ensure the deliberately surviving worker settles before the next test.
        assert http._SECRET_SLOT.acquire(timeout=1)
        http._SECRET_SLOT.release()


def test_partial_send_failure_is_uncertain_and_never_retried(monkeypatch):
    class BrokenSocket:
        calls = 0
        closed = False

        def getpeername(self):
            return ("127.0.0.1", 44859)

        def send(self, data):
            self.calls += 1
            if self.calls == 1:
                return 3
            raise OSError("synthetic private server text")

        def close(self):
            self.closed = True

    sock = BrokenSocket()
    connections = []

    def connect(*_):
        connections.append(1)
        return sock

    monkeypatch.setattr(http, "_connect", connect)
    with pytest.raises(ProviderError, match=Failure.CONNECTION) as error:
        invoke(provider_case())
    assert error.value.transmission == Transmission.POSSIBLE
    assert sock.calls == 2 and sock.closed and len(connections) == 1


def test_real_connect_uses_numeric_ipv6_and_tls_hostname_with_peer_checks(monkeypatch):
    calls = []

    class Socket:
        def setblocking(self, flag):
            assert flag is False

        def connect_ex(self, target):
            calls.append(target)
            return 0

        def getsockopt(self, *_):
            return 0

        def getpeername(self):
            return ("2606:4700:4700::1111", 443, 0, 0)

        def do_handshake(self):
            calls.append("handshake")

        def close(self):
            calls.append("closed")

    class Context:
        def wrap_socket(self, plain, *, server_hostname, do_handshake_on_connect):
            assert server_hostname == "remote.example"
            assert do_handshake_on_connect is False
            calls.append("tls")
            return plain

    sock = Socket()
    monkeypatch.setattr(socket, "socket", lambda *args: sock)
    monkeypatch.setattr(http, "_wait", lambda *args, **kwargs: None)
    monkeypatch.setattr(http, "_tls_context", Context)
    target = endpoint("https://remote.example/v1/chat/completions")
    assert http._connect(target, "2606:4700:4700::1111", http._Control(Cancellation(), 1)) is sock
    assert calls == [("2606:4700:4700::1111", 443, 0, 0), "tls", "handshake"]


def test_product_has_no_exchange_caller_or_public_dispatch_route():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "core" / "provelume"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Guard the new seam: only tests may invoke the provider's exchange method.
        if path.name in {"service.py", "api.py", "cli.py", "ai_gateway.py", "ai_context.py"}:
            assert not any(
                isinstance(node, ast.Attribute) and node.attr == "exchange"
                for node in ast.walk(tree)
            )


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {"total_tokens": -1},
        {"cost": "0.00"},
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    ],
)
def test_unqualified_reported_usage_stays_unknown(usage):
    holder = {}
    with local_server(lambda _: response(completion(holder["i"], usage=usage))) as server:
        holder["i"] = provider_case(server["url"])
        assert invoke(holder["i"]).receipt["usage"] == "UNKNOWN"


def test_secret_revocation_after_connection_prevents_http_send():
    vault = SyntheticVault()

    def revoke_on_second(ref, profile, transport):
        if vault.calls:
            vault.active = False
        return vault(ref, profile, transport)

    with local_server(no_effect) as server:
        with pytest.raises(ProviderError, match=Failure.CREDENTIAL) as error:
            invoke(provider_case(server["url"]), vault=revoke_on_second)
        assert error.value.transmission == Transmission.NOT_SENT
        assert not server["requests"] and vault.calls == 2
