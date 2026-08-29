from __future__ import annotations

import gzip
import http.client
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from provelume.instance_schema import build_instance_manifest
from provelume.service import ProvelumeInstance
from provelume.web_transport import (
    ConditionalMetadata,
    ConnectionParameters,
    GuardedWebLimits,
    GuardedWebRequest,
    GuardedWebTransport,
    WebTransportAuthorizationError,
    WebTransportBodyLimitError,
    WebTransportConfigurationError,
    WebTransportContentTypeError,
    WebTransportDestinationError,
    WebTransportDnsError,
    WebTransportDnsRebindingError,
    WebTransportEncodingError,
    WebTransportHeaderError,
    WebTransportPolicyError,
    WebTransportPortError,
    WebTransportRedirectError,
    WebTransportResponseError,
    WebTransportTimeoutError,
    WebTransportTruncatedError,
    WebTransportUrlError,
)

PUBLIC_IPV4 = "93.184.216.34"
PUBLIC_IPV4_TWO = "142.250.72.14"
HTTP_DATE = "Wed, 21 Oct 2015 07:28:00 GMT"


@dataclass
class SyntheticResponse:
    status: int = 200
    headers: Any = None
    body: bytes = b"synthetic public body"
    timeout_on_read: bool = False
    incomplete_after_body: bool = False
    on_first_read: Callable[[], None] | None = None
    _offset: int = 0
    _incomplete_raised: bool = False
    _read_hook_called: bool = False

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(self.body))),
            ]

    def getheaders(self) -> Any:
        return self.headers

    def read(self, amount: int) -> bytes:
        if self.on_first_read is not None and not self._read_hook_called:
            self._read_hook_called = True
            self.on_first_read()
        if self.timeout_on_read:
            raise TimeoutError
        if self._offset < len(self.body):
            end = min(len(self.body), self._offset + amount)
            selected = self.body[self._offset : end]
            self._offset = end
            return selected
        if self.incomplete_after_body and not self._incomplete_raised:
            self._incomplete_raised = True
            raise http.client.IncompleteRead(b"")
        return b""


@dataclass
class SyntheticConnection:
    network: SyntheticNetwork
    parameters: ConnectionParameters
    response: SyntheticResponse
    closed: bool = False
    read_timeout: float | None = None

    def request(self, method: str, target: str, headers: dict[str, str]) -> None:
        self.network.requests.append(
            {
                "method": method,
                "target": target,
                "headers": dict(headers),
                "parameters": self.parameters,
            }
        )

    def getresponse(self) -> SyntheticResponse:
        return self.response

    def set_read_timeout(self, seconds: float) -> None:
        self.read_timeout = seconds

    def close(self) -> None:
        self.closed = True


@dataclass
class SyntheticNetwork:
    responses: list[SyntheticResponse]
    answers: dict[str, list[list[str]]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)
    resolver_calls: list[tuple[str, int]] = field(default_factory=list)
    connections: list[SyntheticConnection] = field(default_factory=list)

    def resolver(self, host: str, port: int) -> list[str]:
        self.resolver_calls.append((host, port))
        selected = self.answers.get(host)
        if selected is None:
            return [PUBLIC_IPV4]
        if len(selected) > 1:
            return selected.pop(0)
        return list(selected[0])

    def factory(self, parameters: ConnectionParameters) -> SyntheticConnection:
        if not self.responses:
            raise AssertionError("synthetic response queue is empty")
        connection = SyntheticConnection(self, parameters, self.responses.pop(0))
        self.connections.append(connection)
        return connection


def _manifest(*, conditional: bool = True) -> dict[str, object]:
    capabilities = ["manual_read", "source_selection"]
    if conditional:
        capabilities.append("conditional_metadata")
    return {
        "adapter_key": "guarded-web-fixture",
        "adapter_version": "1.0.0",
        "display_name": "Synthetic guarded web fixture",
        "provider": "provider-independent",
        "conformance_profile": "provelume.connector.v1",
        "adapter_protocol_version": 1,
        "capabilities": capabilities,
        "authorization_modes": ["none"],
        "source_kinds": ["web"],
        "data_categories": ["source.content", "source.metadata"],
        "multi_instance": True,
        "network_access": "explicit_only",
    }


def _set_global_network(instance: ProvelumeInstance, enabled: bool) -> None:
    config = instance.store.read_config()
    config["network"]["external_access"] = enabled
    instance.store.write_config(config)
    instance.store._atomic_json(
        instance.store.paths.manifest,
        build_instance_manifest(config),
    )


def _configured(
    tmp_path: Path,
    *,
    url: str = "https://public.example.test/article?view=full",
    allowed_origins: list[str] | None = None,
    global_network: bool = True,
    conditional: bool = True,
) -> tuple[ProvelumeInstance, dict[str, Any], dict[str, Any]]:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    _set_global_network(instance, global_network)
    definition = instance.register_connector_definition(_manifest(conditional=conditional))
    connector = instance.create_connector_instance(
        str(definition["id"]),
        name="Guarded public web",
        provider_identity="provider-independent",
        network_mode="explicit",
        allowed_origins=allowed_origins or ["https://public.example.test"],
        authorization_mode="none",
    )
    source = instance.add_connector_source(
        str(connector["id"]),
        name="Explicit article",
        source_kind="web",
        external_id=url,
    )
    return instance, connector, source


def _request(
    connector: dict[str, Any],
    source: dict[str, Any],
    *,
    url: str | None = None,
    authorization: str = "explicit",
    conditional: ConditionalMetadata | None = None,
) -> GuardedWebRequest:
    return GuardedWebRequest(
        connector_instance_id=str(connector["id"]),
        source_id=str(source["id"]),
        url=url or str(source["external_id"]),
        network_authorization=authorization,
        conditional=conditional,
    )


def _transport(
    instance: ProvelumeInstance,
    network: SyntheticNetwork,
    *,
    limits: GuardedWebLimits | None = None,
) -> GuardedWebTransport:
    return GuardedWebTransport(
        instance.store,
        instance.connectors,
        limits=limits,
        resolver=network.resolver,
        connection_factory=network.factory,
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_explicit_happy_path_pins_revalidated_public_address(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork(
        [SyntheticResponse()],
        answers={"public.example.test": [[PUBLIC_IPV4], [PUBLIC_IPV4]]},
    )

    result = _transport(instance, network).fetch(_request(connector, source))

    assert result.status == 200
    assert result.body == b"synthetic public body"
    assert result.final_url == "https://public.example.test/article?view=full"
    assert result.redirects == 0
    assert result.resources == 1
    assert result.compressed_bytes == result.decompressed_bytes == len(result.body)
    assert network.resolver_calls == [
        ("public.example.test", 443),
        ("public.example.test", 443),
    ]
    assert len(network.connections) == 1
    assert network.connections[0].parameters.address == PUBLIC_IPV4
    assert network.connections[0].parameters.host == "public.example.test"
    assert network.connections[0].closed is True
    assert network.requests[0]["method"] == "GET"
    assert network.requests[0]["target"] == "/article?view=full"
    assert "Authorization" not in network.requests[0]["headers"]
    assert "Cookie" not in network.requests[0]["headers"]


@pytest.mark.parametrize(
    ("url", "origin", "scheme", "port"),
    [
        (
            "http://public.example.test/article",
            "http://public.example.test",
            "http",
            80,
        ),
        (
            "https://public.example.test:8443/article",
            "https://public.example.test:8443",
            "https",
            8443,
        ),
    ],
)
def test_http_and_explicit_safe_non_default_https_port_are_supported(
    tmp_path: Path,
    url: str,
    origin: str,
    scheme: str,
    port: int,
) -> None:
    instance, connector, source = _configured(
        tmp_path,
        url=url,
        allowed_origins=[origin],
    )
    network = SyntheticNetwork([SyntheticResponse()])

    result = _transport(instance, network).fetch(_request(connector, source))

    assert result.status == 200
    assert network.connections[0].parameters.scheme == scheme
    assert network.connections[0].parameters.port == port


def test_public_ipv6_literal_is_pinned_without_dns(tmp_path: Path) -> None:
    address = "2606:2800:220:1:248:1893:25c8:1946"
    url = f"https://[{address}]/article"
    instance, connector, source = _configured(
        tmp_path,
        url=url,
        allowed_origins=[f"https://[{address}]"],
    )
    network = SyntheticNetwork([SyntheticResponse()])

    result = _transport(instance, network).fetch(_request(connector, source))

    assert result.status == 200
    assert network.resolver_calls == []
    assert network.connections[0].parameters.address == address


def test_request_requires_an_explicit_network_authorization_marker(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork([SyntheticResponse()])

    with pytest.raises(WebTransportAuthorizationError) as captured:
        _transport(instance, network).fetch(_request(connector, source, authorization="ambient"))

    assert captured.value.as_dict() == {
        "code": "web_transport_authorization_required",
        "message": "An explicit guarded web request is required.",
        "retryable": False,
    }
    assert network.resolver_calls == []
    assert network.connections == []


@pytest.mark.parametrize("blocked_gate", ["global", "connector", "source"])
def test_instance_connector_and_source_policy_each_fail_closed(
    tmp_path: Path,
    blocked_gate: str,
) -> None:
    instance, connector, source = _configured(tmp_path / blocked_gate)
    if blocked_gate == "global":
        _set_global_network(instance, False)
    elif blocked_gate == "connector":
        instance.disable_connector_instance(str(connector["id"]))
    else:
        instance.disable_connector_source(str(connector["id"]), str(source["id"]))
    network = SyntheticNetwork([SyntheticResponse()])

    with pytest.raises(WebTransportPolicyError):
        _transport(instance, network).fetch(_request(connector, source))

    assert network.resolver_calls == []
    assert network.connections == []


def test_truthy_malformed_global_policy_does_not_enable_network(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    config = instance.store.read_config()
    config["network"]["external_access"] = "true"
    instance.store.write_config(config)
    instance.store._atomic_json(
        instance.store.paths.manifest,
        build_instance_manifest(config),
    )
    network = SyntheticNetwork([SyntheticResponse()])

    with pytest.raises(WebTransportPolicyError):
        _transport(instance, network).fetch(_request(connector, source))

    assert network.resolver_calls == []
    assert network.connections == []


def test_authority_is_rechecked_after_dns_and_before_return(tmp_path: Path) -> None:
    first, connector, source = _configured(tmp_path / "before-connect")
    calls = 0

    def disabling_resolver(_host: str, _port: int) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            first.disable_connector_source(str(connector["id"]), str(source["id"]))
        return [PUBLIC_IPV4]

    before_connect = SyntheticNetwork([SyntheticResponse()])
    transport = GuardedWebTransport(
        first.store,
        first.connectors,
        resolver=disabling_resolver,
        connection_factory=before_connect.factory,
    )
    with pytest.raises(WebTransportPolicyError):
        transport.fetch(_request(connector, source))
    assert before_connect.connections == []

    second, connector, source = _configured(tmp_path / "before-return")

    def disable_during_read() -> None:
        second.disable_connector_source(str(connector["id"]), str(source["id"]))

    during_read = SyntheticNetwork([SyntheticResponse(on_first_read=disable_during_read)])
    with pytest.raises(WebTransportPolicyError):
        _transport(second, during_read).fetch(_request(connector, source))
    assert during_read.connections[0].closed is True


def test_source_url_is_an_exact_initial_request_boundary(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork([SyntheticResponse()])

    with pytest.raises(WebTransportPolicyError):
        _transport(instance, network).fetch(
            _request(
                connector,
                source,
                url="https://public.example.test/other?token=sensitive",
            )
        )

    assert network.resolver_calls == []


@pytest.mark.parametrize(
    "url",
    [
        "file:///private/local/path",
        "ftp://public.example.test/article",
        "https://user:sensitive-token@public.example.test/article",
        "https:///missing-host",
        "https://public.example.test\\@127.0.0.1/article",
        "https://public.example.test:0443/article",
        "https://public.example.test/article#fragment",
        "https://2130706433/article",
        "https://127.1/article",
        "https://public.example.test/%zz",
        " https://public.example.test/article",
    ],
)
def test_non_http_userinfo_and_ambiguous_urls_are_rejected_before_dns(
    tmp_path: Path,
    url: str,
) -> None:
    instance, connector, source = _configured(
        tmp_path,
        url=url,
        allowed_origins=["https://public.example.test"],
    )
    network = SyntheticNetwork([SyntheticResponse()])

    with pytest.raises(WebTransportUrlError) as captured:
        _transport(instance, network).fetch(_request(connector, source, url=url))

    rendered = str(captured.value)
    assert "sensitive-token" not in rendered
    assert "private/local/path" not in rendered
    assert network.resolver_calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/article",
        "https://10.0.0.1/article",
        "https://169.254.169.254/latest/meta-data",
        "https://224.0.0.1/article",
        "https://0.0.0.0/article",
        "https://192.0.2.1/article",
        "https://100.64.0.1/article",
        "https://[::1]/article",
        "https://[fe80::1]/article",
        "https://[fc00::1]/article",
        "https://[ff02::1]/article",
        "https://[::]/article",
        "https://[::ffff:127.0.0.1]/article",
        "https://[64:ff9b::7f00:1]/article",
        "https://[2002:7f00:1::]/article",
    ],
)
def test_direct_non_public_ipv4_ipv6_and_mapped_forms_are_blocked(
    tmp_path: Path,
    url: str,
) -> None:
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    instance, connector, source = _configured(
        tmp_path,
        url=url,
        allowed_origins=[origin],
    )
    network = SyntheticNetwork([SyntheticResponse()])

    with pytest.raises(WebTransportDestinationError):
        _transport(instance, network).fetch(_request(connector, source))

    assert network.resolver_calls == []
    assert network.connections == []


def test_blocked_service_port_is_rejected_even_when_allowlisted(tmp_path: Path) -> None:
    url = "https://public.example.test:22/article"
    instance, connector, source = _configured(
        tmp_path,
        url=url,
        allowed_origins=["https://public.example.test:22"],
    )
    network = SyntheticNetwork([SyntheticResponse()])

    with pytest.raises(WebTransportPortError):
        _transport(instance, network).fetch(_request(connector, source))

    assert network.resolver_calls == []


def test_unlisted_non_default_port_is_rejected_before_dns(tmp_path: Path) -> None:
    url = "https://public.example.test:8443/article"
    instance, connector, source = _configured(
        tmp_path,
        url=url,
        allowed_origins=["https://public.example.test"],
    )
    network = SyntheticNetwork([SyntheticResponse()])

    with pytest.raises(WebTransportPortError):
        _transport(instance, network).fetch(_request(connector, source))

    assert network.resolver_calls == []


def test_mixed_public_and_private_dns_answer_fails_closed(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork(
        [SyntheticResponse()],
        answers={"public.example.test": [[PUBLIC_IPV4, "10.1.2.3"]]},
    )

    with pytest.raises(WebTransportDestinationError):
        _transport(instance, network).fetch(_request(connector, source))

    assert len(network.resolver_calls) == 1
    assert network.connections == []


def test_dns_is_revalidated_at_connect_and_rebinding_is_rejected(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork(
        [SyntheticResponse()],
        answers={"public.example.test": [[PUBLIC_IPV4], ["127.0.0.1"]]},
    )

    with pytest.raises(WebTransportDnsRebindingError):
        _transport(instance, network).fetch(_request(connector, source))

    assert len(network.resolver_calls) == 2
    assert network.connections == []


def test_dns_failures_and_address_count_are_typed_and_redacted(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork(
        [SyntheticResponse()],
        answers={"public.example.test": [[f"8.8.8.{index}" for index in range(1, 18)]]},
    )

    with pytest.raises(WebTransportDnsError) as captured:
        _transport(instance, network).fetch(_request(connector, source))

    assert "public.example.test" not in str(captured.value)
    assert network.connections == []


def test_redirects_revalidate_each_origin_and_strip_cross_origin_conditionals(
    tmp_path: Path,
) -> None:
    instance, connector, source = _configured(
        tmp_path,
        allowed_origins=[
            "https://public.example.test",
            "https://cdn.example.test",
        ],
    )
    final = b"redirected public content"
    network = SyntheticNetwork(
        [
            SyntheticResponse(
                status=302,
                headers=[("Location", "https://cdn.example.test/final")],
                body=b"ignored",
            ),
            SyntheticResponse(body=final),
        ],
        answers={
            "public.example.test": [[PUBLIC_IPV4], [PUBLIC_IPV4]],
            "cdn.example.test": [[PUBLIC_IPV4_TWO], [PUBLIC_IPV4_TWO]],
        },
    )
    conditional = ConditionalMetadata(etag='"bounded-etag"', last_modified=HTTP_DATE)

    result = _transport(instance, network).fetch(
        _request(connector, source, conditional=conditional)
    )

    assert result.body == final
    assert result.final_url == "https://cdn.example.test/final"
    assert result.redirects == 1
    assert result.resources == 2
    assert len(network.resolver_calls) == 4
    assert network.requests[0]["headers"]["If-None-Match"] == '"bounded-etag"'
    assert network.requests[0]["headers"]["If-Modified-Since"] == HTTP_DATE
    assert "If-None-Match" not in network.requests[1]["headers"]
    assert "If-Modified-Since" not in network.requests[1]["headers"]


def test_redirect_dns_pivot_to_private_network_is_blocked(tmp_path: Path) -> None:
    instance, connector, source = _configured(
        tmp_path,
        allowed_origins=[
            "https://public.example.test",
            "https://pivot.example.test",
        ],
    )
    network = SyntheticNetwork(
        [
            SyntheticResponse(
                status=302,
                headers=[("Location", "https://pivot.example.test/private")],
            ),
            SyntheticResponse(),
        ],
        answers={
            "public.example.test": [[PUBLIC_IPV4], [PUBLIC_IPV4]],
            "pivot.example.test": [["192.168.1.10"]],
        },
    )

    with pytest.raises(WebTransportDestinationError):
        _transport(instance, network).fetch(_request(connector, source))

    assert len(network.connections) == 1
    assert network.connections[0].closed is True


@pytest.mark.parametrize(
    "location",
    [
        "http://public.example.test/downgrade",
        "https://unlisted.example.test/pivot",
        "https://user:token@public.example.test/pivot",
        "/article?view=full",
    ],
)
def test_downgrade_unlisted_userinfo_and_redirect_loops_are_rejected(
    tmp_path: Path,
    location: str,
) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork([SyntheticResponse(status=302, headers=[("Location", location)])])

    with pytest.raises(WebTransportRedirectError) as captured:
        _transport(instance, network).fetch(_request(connector, source))

    assert "token" not in str(captured.value)


def test_redirect_resource_limit_is_explicit(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork(
        [
            SyntheticResponse(status=302, headers=[("Location", "/second")]),
            SyntheticResponse(status=302, headers=[("Location", "/third")]),
        ]
    )
    limits = replace(GuardedWebLimits(), max_redirects=1, max_resources=2)

    with pytest.raises(WebTransportRedirectError):
        _transport(instance, network, limits=limits).fetch(_request(connector, source))


def test_conditional_metadata_is_bounded_and_304_is_bodyless(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork(
        [
            SyntheticResponse(
                status=304,
                headers=[
                    ("ETag", 'W/"next"'),
                    ("Last-Modified", HTTP_DATE),
                    ("Content-Length", "0"),
                ],
                body=b"",
            )
        ]
    )
    before = _snapshot(instance.root)

    result = _transport(instance, network).fetch(
        _request(
            connector,
            source,
            conditional=ConditionalMetadata(etag='"previous"'),
        )
    )

    assert result.not_modified is True
    assert result.body == b""
    assert result.etag == 'W/"next"'
    assert result.last_modified == HTTP_DATE
    assert _snapshot(instance.root) == before


@pytest.mark.parametrize(
    "conditional",
    [
        {"etag": "unquoted"},
        {"etag": '"bad\nvalue"'},
        {"last_modified": "not-a-date"},
        {},
    ],
)
def test_invalid_conditional_metadata_is_rejected(conditional: dict[str, str]) -> None:
    with pytest.raises(WebTransportConfigurationError):
        ConditionalMetadata(**conditional)


def test_conditional_request_requires_declared_capability(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path, conditional=False)
    network = SyntheticNetwork([SyntheticResponse()])

    with pytest.raises(WebTransportPolicyError):
        _transport(instance, network).fetch(
            _request(
                connector,
                source,
                conditional=ConditionalMetadata(etag='"known"'),
            )
        )

    assert network.resolver_calls == []


@pytest.mark.parametrize(
    ("headers", "expected_error"),
    [
        (
            [
                ("Content-Type", "text/plain"),
                ("Content-Length", "1"),
                ("Content-Length", "1"),
            ],
            WebTransportHeaderError,
        ),
        (
            [
                ("Content-Type", "text/plain"),
                ("Content-Length", "1"),
                ("Transfer-Encoding", "chunked"),
            ],
            WebTransportHeaderError,
        ),
        (
            [("Content-Type", "text/plain"), ("Content-Length", "-1")],
            WebTransportHeaderError,
        ),
        (
            [("Content-Type", "text/plain"), ("Transfer-Encoding", "compress")],
            WebTransportHeaderError,
        ),
        (
            [("Bad Header", "value"), ("Content-Length", "1")],
            WebTransportHeaderError,
        ),
        (
            [("X-Fixture", "bad\nvalue"), ("Content-Length", "1")],
            WebTransportHeaderError,
        ),
        (
            [("Content-Type", "application/x-private"), ("Content-Length", "1")],
            WebTransportContentTypeError,
        ),
        (
            [("Content-Type", "text/plain; broken"), ("Content-Length", "1")],
            WebTransportContentTypeError,
        ),
        (
            [("Content-Type", "text/plain"), ("Content-Encoding", "br"), ("Content-Length", "1")],
            WebTransportEncodingError,
        ),
    ],
)
def test_malformed_headers_content_types_and_encodings_fail_closed(
    tmp_path: Path,
    headers: list[tuple[str, str]],
    expected_error: type[Exception],
) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork([SyntheticResponse(headers=headers, body=b"x")])

    with pytest.raises(expected_error):
        _transport(instance, network).fetch(_request(connector, source))


def test_header_count_and_value_size_are_bounded(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    too_many = [(f"X-{index}", "v") for index in range(101)]
    network = SyntheticNetwork([SyntheticResponse(headers=too_many, body=b"")])

    with pytest.raises(WebTransportHeaderError):
        _transport(instance, network).fetch(_request(connector, source))

    network = SyntheticNetwork(
        [
            SyntheticResponse(
                headers=[("X-Large", "a" * (8 * 1024 + 1))],
                body=b"",
            )
        ]
    )
    with pytest.raises(WebTransportHeaderError):
        _transport(instance, network).fetch(_request(connector, source))


def test_bodyful_not_modified_response_is_rejected(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork(
        [
            SyntheticResponse(
                status=304,
                headers=[("Content-Length", "0")],
                body=b"unexpected private body",
            )
        ]
    )

    with pytest.raises(WebTransportResponseError):
        _transport(instance, network).fetch(
            _request(
                connector,
                source,
                conditional=ConditionalMetadata(etag='"known"'),
            )
        )


def test_declared_oversize_and_actual_oversize_bodies_are_rejected(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    limits = replace(
        GuardedWebLimits(),
        max_compressed_bytes=1024,
        max_decompressed_bytes=2048,
    )
    declared = SyntheticNetwork(
        [
            SyntheticResponse(
                headers=[
                    ("Content-Type", "text/plain"),
                    ("Content-Length", "1025"),
                ],
                body=b"",
            )
        ]
    )
    with pytest.raises(WebTransportBodyLimitError):
        _transport(instance, declared, limits=limits).fetch(_request(connector, source))

    actual_body = b"x" * 1025
    actual = SyntheticNetwork(
        [
            SyntheticResponse(
                headers=[
                    ("Content-Type", "text/plain"),
                    ("Transfer-Encoding", "chunked"),
                ],
                body=actual_body,
            )
        ]
    )
    with pytest.raises(WebTransportBodyLimitError):
        _transport(instance, actual, limits=limits).fetch(_request(connector, source))


def test_missing_framing_short_content_length_and_chunk_truncation_fail_closed(
    tmp_path: Path,
) -> None:
    instance, connector, source = _configured(tmp_path)
    fixtures = [
        SyntheticResponse(
            headers=[("Content-Type", "text/plain")],
            body=b"unframed",
        ),
        SyntheticResponse(
            headers=[("Content-Type", "text/plain"), ("Content-Length", "20")],
            body=b"short",
        ),
        SyntheticResponse(
            headers=[("Content-Type", "text/plain"), ("Transfer-Encoding", "chunked")],
            body=b"partial",
            incomplete_after_body=True,
        ),
    ]
    for index, response in enumerate(fixtures):
        network = SyntheticNetwork([response])
        with pytest.raises(WebTransportTruncatedError), pytest.MonkeyPatch.context():
            _transport(instance, network).fetch(_request(connector, source))
        assert network.connections[0].closed is True, index


def test_gzip_is_streamed_with_compressed_decompressed_and_ratio_limits(
    tmp_path: Path,
) -> None:
    instance, connector, source = _configured(tmp_path)
    body = b"bounded compressed response " * 100
    compressed = gzip.compress(body, mtime=0)
    response = SyntheticResponse(
        headers=[
            ("Content-Type", "text/plain"),
            ("Content-Encoding", "gzip"),
            ("Content-Length", str(len(compressed))),
        ],
        body=compressed,
    )
    result = _transport(instance, SyntheticNetwork([response])).fetch(_request(connector, source))
    assert result.body == body
    assert result.compressed_bytes == len(compressed)
    assert result.decompressed_bytes == len(body)

    bomb_body = b"a" * 200_000
    bomb = gzip.compress(bomb_body, mtime=0)
    limits = replace(
        GuardedWebLimits(),
        max_compressed_bytes=1024 * 1024,
        max_decompressed_bytes=250_000,
        max_decompression_ratio=10,
        decompression_ratio_floor_bytes=100,
    )
    network = SyntheticNetwork(
        [
            SyntheticResponse(
                headers=[
                    ("Content-Type", "text/plain"),
                    ("Content-Encoding", "gzip"),
                    ("Content-Length", str(len(bomb))),
                ],
                body=bomb,
            )
        ]
    )
    with pytest.raises(WebTransportBodyLimitError):
        _transport(instance, network, limits=limits).fetch(_request(connector, source))


@pytest.mark.parametrize(
    ("body", "expected_error"),
    [
        (b"not-gzip", WebTransportEncodingError),
        (gzip.compress(b"truncated", mtime=0)[:-5], WebTransportTruncatedError),
    ],
)
def test_malformed_and_truncated_compressed_bodies_fail_closed(
    tmp_path: Path,
    body: bytes,
    expected_error: type[Exception],
) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork(
        [
            SyntheticResponse(
                headers=[
                    ("Content-Type", "text/plain"),
                    ("Content-Encoding", "gzip"),
                    ("Content-Length", str(len(body))),
                ],
                body=body,
            )
        ]
    )

    with pytest.raises(expected_error):
        _transport(instance, network).fetch(_request(connector, source))


def test_timeout_and_error_response_do_not_disclose_url_or_body(tmp_path: Path) -> None:
    sensitive_url = "https://public.example.test/article?token=private-token"
    instance, connector, source = _configured(tmp_path, url=sensitive_url)
    timeout_network = SyntheticNetwork([SyntheticResponse(timeout_on_read=True)])
    with pytest.raises(WebTransportTimeoutError) as timeout:
        _transport(instance, timeout_network).fetch(_request(connector, source))
    assert "private-token" not in str(timeout.value)

    private_body = b"private provider error contents"
    error_network = SyntheticNetwork(
        [
            SyntheticResponse(
                status=500,
                headers=[
                    ("Content-Type", "text/plain"),
                    ("Content-Length", str(len(private_body))),
                ],
                body=private_body,
            )
        ]
    )
    with pytest.raises(WebTransportResponseError) as response_error:
        _transport(instance, error_network).fetch(_request(connector, source))
    assert "private-token" not in str(response_error.value)
    assert "private provider" not in str(response_error.value)
    assert error_network.responses == []

    partial_network = SyntheticNetwork(
        [
            SyntheticResponse(
                status=206,
                headers=[
                    ("Content-Type", "text/plain"),
                    ("Content-Length", "1"),
                ],
                body=b"x",
            )
        ]
    )
    with pytest.raises(WebTransportResponseError):
        _transport(instance, partial_network).fetch(_request(connector, source))


def test_transport_success_and_failure_do_not_mutate_instance_or_canonical_knowledge(
    tmp_path: Path,
) -> None:
    instance, connector, source = _configured(tmp_path)
    before = _snapshot(instance.root)
    success = SyntheticNetwork([SyntheticResponse(body=b"transient only")])

    result = _transport(instance, success).fetch(_request(connector, source))

    assert result.body == b"transient only"
    assert _snapshot(instance.root) == before
    assert instance.store.list_canonical("documents") == []
    assert instance.store.list_canonical("acquisitions") == []
    assert instance.store.list_canonical("versions") == []
    assert instance.store.list_canonical("originals") == []
    assert instance.store.list_derived_artifacts() == []

    failure = SyntheticNetwork(
        [
            SyntheticResponse(
                headers=[("Content-Type", "text/plain"), ("Content-Length", "999")],
                body=b"short",
            )
        ]
    )
    with pytest.raises(WebTransportTruncatedError):
        _transport(instance, failure).fetch(_request(connector, source))
    assert _snapshot(instance.root) == before


def test_instance_service_exposes_only_the_transient_transport_result(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path)
    network = SyntheticNetwork([SyntheticResponse(body=b"service boundary")])
    instance.web_transport = _transport(instance, network)
    before = _snapshot(instance.root)

    result = instance.guarded_web_fetch(_request(connector, source))

    assert result.body == b"service boundary"
    assert _snapshot(instance.root) == before
    assert instance.store.list_canonical("documents") == []
    assert instance.store.list_canonical("acquisitions") == []


def test_limit_contract_rejects_unbounded_or_inconsistent_values() -> None:
    with pytest.raises(WebTransportConfigurationError):
        GuardedWebLimits(max_redirects=5, max_resources=5)
    with pytest.raises(WebTransportConfigurationError):
        GuardedWebLimits(total_timeout_seconds=1, connect_timeout_seconds=2)
    with pytest.raises(WebTransportConfigurationError):
        GuardedWebLimits(allowed_content_types=("*/*",))
