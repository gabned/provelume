from __future__ import annotations

import http.client
import re
import socket
import ssl
import zlib
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

from . import __version__
from .connector_model import ConnectorError
from .connectors import ConnectorManager
from .storage import InstanceStore

DEFAULT_ALLOWED_CONTENT_TYPES = (
    "application/json",
    "application/ld+json",
    "application/pdf",
    "application/xhtml+xml",
    "application/xml",
    "text/csv",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/xml",
)

# WHATWG Fetch bad-port list. An explicit origin allowlist cannot make one of these service
# ports a web-retrieval target.
BLOCKED_WEB_PORTS = frozenset(
    {
        1,
        7,
        9,
        11,
        13,
        15,
        17,
        19,
        20,
        21,
        22,
        23,
        25,
        37,
        42,
        43,
        53,
        69,
        77,
        79,
        87,
        95,
        101,
        102,
        103,
        104,
        109,
        110,
        111,
        113,
        115,
        117,
        119,
        123,
        135,
        137,
        139,
        143,
        161,
        179,
        389,
        427,
        465,
        512,
        513,
        514,
        515,
        526,
        530,
        531,
        532,
        540,
        548,
        554,
        556,
        563,
        587,
        601,
        636,
        989,
        990,
        993,
        995,
        1719,
        1720,
        1723,
        2049,
        3659,
        4045,
        4190,
        5060,
        5061,
        6000,
        6566,
        6665,
        6666,
        6667,
        6668,
        6669,
        6697,
        10080,
    }
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_NO_BODY_STATUSES = frozenset({204, 205, 304})
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_MEDIA_TYPE = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+/[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_ETAG = re.compile(r'(?:W/)?"[\x21\x23-\x7e]*"\Z')
_NAT64_WELL_KNOWN = ip_network("64:ff9b::/96")
_NAT64_LOCAL_USE = ip_network("64:ff9b:1::/48")


class WebTransportError(RuntimeError):
    """A typed, safe-to-log guarded-transport failure."""

    code = "web_transport_failed"
    safe_message = "Guarded web retrieval failed closed."
    retryable = False

    def __init__(self) -> None:
        super().__init__(self.safe_message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.safe_message,
            "retryable": self.retryable,
        }


class WebTransportConfigurationError(WebTransportError):
    code = "web_transport_configuration_invalid"
    safe_message = "Guarded web transport configuration is invalid."


class WebTransportAuthorizationError(WebTransportError):
    code = "web_transport_authorization_required"
    safe_message = "An explicit guarded web request is required."


class WebTransportPolicyError(WebTransportError):
    code = "web_transport_policy_blocked"
    safe_message = "Instance, connector, or Source policy blocked guarded web retrieval."


class WebTransportUrlError(WebTransportError):
    code = "web_transport_url_rejected"
    safe_message = "The requested web URL is not an unambiguous HTTP(S) URL."


class WebTransportPortError(WebTransportError):
    code = "web_transport_port_rejected"
    safe_message = "The requested port is not authorized for guarded web retrieval."


class WebTransportDestinationError(WebTransportError):
    code = "web_transport_destination_rejected"
    safe_message = "The requested destination is not a public network destination."


class WebTransportDnsError(WebTransportError):
    code = "web_transport_dns_failed"
    safe_message = "Public DNS resolution failed closed."
    retryable = True


class WebTransportDnsRebindingError(WebTransportError):
    code = "web_transport_dns_rebinding_rejected"
    safe_message = "DNS revalidation rejected the connection target."


class WebTransportConnectionError(WebTransportError):
    code = "web_transport_connection_failed"
    safe_message = "The guarded connection failed without fallback."
    retryable = True


class WebTransportTimeoutError(WebTransportError):
    code = "web_transport_timeout"
    safe_message = "The guarded request exceeded an explicit time limit."
    retryable = True


class WebTransportRedirectError(WebTransportError):
    code = "web_transport_redirect_rejected"
    safe_message = "The guarded redirect chain was rejected."


class WebTransportHeaderError(WebTransportError):
    code = "web_transport_headers_rejected"
    safe_message = "The response headers were malformed or exceeded an explicit limit."


class WebTransportResponseError(WebTransportError):
    code = "web_transport_response_rejected"
    safe_message = "The HTTP response was not accepted by guarded retrieval."


class WebTransportContentTypeError(WebTransportError):
    code = "web_transport_content_type_rejected"
    safe_message = "The response content type is not authorized."


class WebTransportEncodingError(WebTransportError):
    code = "web_transport_encoding_rejected"
    safe_message = "The response content encoding is unsupported or malformed."


class WebTransportBodyLimitError(WebTransportError):
    code = "web_transport_body_limit_exceeded"
    safe_message = "The response body exceeded an explicit guarded limit."


class WebTransportTruncatedError(WebTransportError):
    code = "web_transport_response_truncated"
    safe_message = "The response body was truncated or incompletely encoded."


@dataclass(frozen=True, slots=True)
class ConditionalMetadata:
    etag: str | None = None
    last_modified: str | None = None

    def __post_init__(self) -> None:
        if self.etag is not None and not _valid_etag(self.etag):
            raise WebTransportConfigurationError
        if self.last_modified is not None and not _valid_http_date(self.last_modified):
            raise WebTransportConfigurationError
        if self.etag is None and self.last_modified is None:
            raise WebTransportConfigurationError


@dataclass(frozen=True, slots=True)
class GuardedWebRequest:
    connector_instance_id: str
    source_id: str
    url: str
    network_authorization: str
    conditional: ConditionalMetadata | None = None


@dataclass(frozen=True, slots=True)
class GuardedWebLimits:
    max_redirects: int = 5
    max_resources: int = 6
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 15.0
    total_timeout_seconds: float = 30.0
    max_url_chars: int = 4096
    max_resolved_addresses: int = 16
    max_header_count: int = 100
    max_header_bytes: int = 64 * 1024
    max_header_name_bytes: int = 128
    max_header_value_bytes: int = 8 * 1024
    max_compressed_bytes: int = 20 * 1024 * 1024
    max_decompressed_bytes: int = 50 * 1024 * 1024
    max_decompression_ratio: int = 100
    decompression_ratio_floor_bytes: int = 1024
    read_chunk_bytes: int = 64 * 1024
    allowed_content_types: tuple[str, ...] = DEFAULT_ALLOWED_CONTENT_TYPES

    def __post_init__(self) -> None:
        integer_limits = {
            "max_redirects": (self.max_redirects, 0, 10),
            "max_resources": (self.max_resources, 1, 11),
            "max_url_chars": (self.max_url_chars, 256, 16384),
            "max_resolved_addresses": (self.max_resolved_addresses, 1, 64),
            "max_header_count": (self.max_header_count, 1, 256),
            "max_header_bytes": (self.max_header_bytes, 1024, 1024 * 1024),
            "max_header_name_bytes": (self.max_header_name_bytes, 16, 256),
            "max_header_value_bytes": (self.max_header_value_bytes, 128, 64 * 1024),
            "max_compressed_bytes": (self.max_compressed_bytes, 1, 100 * 1024 * 1024),
            "max_decompressed_bytes": (
                self.max_decompressed_bytes,
                1,
                250 * 1024 * 1024,
            ),
            "max_decompression_ratio": (self.max_decompression_ratio, 1, 1000),
            "decompression_ratio_floor_bytes": (
                self.decompression_ratio_floor_bytes,
                1,
                1024 * 1024,
            ),
            "read_chunk_bytes": (self.read_chunk_bytes, 256, 1024 * 1024),
        }
        if any(
            type(value) is not int or not minimum <= value <= maximum
            for value, minimum, maximum in integer_limits.values()
        ):
            raise WebTransportConfigurationError
        if self.max_resources < self.max_redirects + 1:
            raise WebTransportConfigurationError
        for value in (
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
            self.total_timeout_seconds,
        ):
            if type(value) not in {int, float} or not 0 < value <= 120:
                raise WebTransportConfigurationError
        if self.total_timeout_seconds < min(
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
        ):
            raise WebTransportConfigurationError
        if (
            not isinstance(self.allowed_content_types, tuple)
            or not 1 <= len(self.allowed_content_types) <= 32
        ):
            raise WebTransportConfigurationError
        selected: list[str] = []
        for item in self.allowed_content_types:
            if (
                not isinstance(item, str)
                or item != item.lower()
                or "*" in item
                or _MEDIA_TYPE.fullmatch(item) is None
            ):
                raise WebTransportConfigurationError
            if item not in selected:
                selected.append(item)
        object.__setattr__(self, "allowed_content_types", tuple(selected))


@dataclass(frozen=True, slots=True)
class GuardedWebResponse:
    status: int
    body: bytes
    content_type: str | None
    content_encoding: str
    etag: str | None
    last_modified: str | None
    final_url: str
    redirects: int
    resources: int
    compressed_bytes: int
    decompressed_bytes: int
    not_modified: bool


@dataclass(frozen=True, slots=True)
class _Target:
    url: str
    scheme: str
    host: str
    port: int
    origin: str
    request_target: str


@dataclass(frozen=True, slots=True)
class ConnectionParameters:
    scheme: str
    host: str
    port: int
    address: str
    connect_timeout_seconds: float


class ResponseStream(Protocol):
    status: int

    def getheaders(self) -> list[tuple[str, str]]: ...

    def read(self, amount: int) -> bytes: ...


class WebConnection(Protocol):
    def request(self, method: str, target: str, headers: Mapping[str, str]) -> None: ...

    def getresponse(self) -> ResponseStream: ...

    def set_read_timeout(self, seconds: float) -> None: ...

    def close(self) -> None: ...


Resolver = Callable[[str, int], Sequence[str]]
ConnectionFactory = Callable[[ConnectionParameters], WebConnection]


def _valid_etag(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 1024 and _ETAG.fullmatch(value) is not None


def _valid_http_date(value: Any) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.isascii():
        return False
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return parsed is not None and parsed.tzinfo is not None


def _has_valid_percent_escapes(value: str) -> bool:
    cursor = 0
    while True:
        cursor = value.find("%", cursor)
        if cursor < 0:
            return True
        if _PERCENT_ESCAPE.match(value, cursor) is None:
            return False
        cursor += 3


def _normalise_host(host: str) -> str:
    if "%" in host:
        raise WebTransportUrlError
    try:
        address = ip_address(host)
    except ValueError:
        try:
            canonical = host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise WebTransportUrlError from None
        if (
            len(canonical) > 253
            or canonical.endswith(".")
            or "." not in canonical
            or re.fullmatch(r"[0-9.]+", canonical)
            or any(label.startswith("0x") for label in canonical.split("."))
            or not all(
                1 <= len(label) <= 63 and _HOST_LABEL.fullmatch(label) is not None
                for label in canonical.split(".")
            )
        ):
            raise WebTransportUrlError from None
        return canonical
    return str(address)


def _explicit_port_text(netloc: str) -> str | None:
    if netloc.startswith("["):
        closing = netloc.find("]")
        if closing < 0:
            raise WebTransportUrlError
        suffix = netloc[closing + 1 :]
        if not suffix:
            return None
        if not suffix.startswith(":"):
            raise WebTransportUrlError
        return suffix[1:]
    if ":" not in netloc:
        return None
    return netloc.rsplit(":", 1)[1]


def _normalise_url(value: Any, limits: GuardedWebLimits) -> _Target:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= limits.max_url_chars
        or value != value.strip()
        or not value.isascii()
        or "\\" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
        or not _has_valid_percent_escapes(value)
    ):
        raise WebTransportUrlError
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (UnicodeError, ValueError):
        raise WebTransportUrlError from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise WebTransportUrlError
    explicit_port = _explicit_port_text(parsed.netloc)
    if explicit_port is not None and (
        not explicit_port.isascii()
        or not explicit_port.isdecimal()
        or port is None
        or explicit_port != str(port)
    ):
        raise WebTransportUrlError
    host = _normalise_host(parsed.hostname)
    selected_port = port if port is not None else 80 if parsed.scheme == "http" else 443
    if selected_port in BLOCKED_WEB_PORTS:
        raise WebTransportPortError
    display_host = f"[{host}]" if ":" in host else host
    default_port = 80 if parsed.scheme == "http" else 443
    origin = (
        f"{parsed.scheme}://{display_host}"
        f"{f':{selected_port}' if selected_port != default_port else ''}"
    )
    path = parsed.path or "/"
    if not path.startswith("/"):
        raise WebTransportUrlError
    request_target = f"{path}{f'?{parsed.query}' if parsed.query else ''}"
    canonical = f"{origin}{request_target}"
    if len(canonical) > limits.max_url_chars:
        raise WebTransportUrlError
    return _Target(
        url=canonical,
        scheme=parsed.scheme,
        host=host,
        port=selected_port,
        origin=origin,
        request_target=request_target,
    )


def _public_ip(value: str) -> str:
    if not isinstance(value, str) or "%" in value:
        raise WebTransportDestinationError
    try:
        address = ip_address(value)
    except ValueError:
        raise WebTransportDestinationError from None
    candidates: list[IPv4Address | IPv6Address] = [address]
    if isinstance(address, IPv6Address):
        if address.ipv4_mapped is not None:
            candidates.append(address.ipv4_mapped)
        if address.sixtofour is not None:
            candidates.append(address.sixtofour)
        if address.teredo is not None:
            candidates.extend(address.teredo)
        if address in _NAT64_LOCAL_USE:
            raise WebTransportDestinationError
        if address in _NAT64_WELL_KNOWN:
            candidates.append(IPv4Address(int(address) & 0xFFFFFFFF))
        interface_prefix = address.packed[-8:-4]
        if interface_prefix in {b"\x00\x00\x5e\xfe", b"\x02\x00\x5e\xfe"}:
            candidates.append(IPv4Address(address.packed[-4:]))
    if any(
        not candidate.is_global
        or candidate.is_private
        or candidate.is_loopback
        or candidate.is_link_local
        or candidate.is_multicast
        or candidate.is_reserved
        or candidate.is_unspecified
        or isinstance(candidate, IPv6Address)
        and candidate.is_site_local
        for candidate in candidates
    ):
        raise WebTransportDestinationError
    return str(address)


def _default_resolver(host: str, port: int) -> Sequence[str]:
    results = socket.getaddrinfo(
        host,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return [str(item[4][0]) for item in results]


def _open_pinned_socket(address: str, port: int, timeout: float) -> socket.socket:
    parsed = ip_address(address)
    family = socket.AF_INET6 if isinstance(parsed, IPv6Address) else socket.AF_INET
    endpoint: tuple[Any, ...] = (
        (str(parsed), port, 0, 0) if family == socket.AF_INET6 else (str(parsed), port)
    )
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(endpoint)
        return sock
    except Exception:
        sock.close()
        raise


class _PinnedHttpConnection(http.client.HTTPConnection):
    def __init__(self, parameters: ConnectionParameters):
        super().__init__(
            parameters.host,
            parameters.port,
            timeout=parameters.connect_timeout_seconds,
        )
        self._pinned_address = parameters.address

    def connect(self) -> None:
        if self._tunnel_host is not None:
            raise OSError("proxy tunnelling is disabled")
        self.sock = _open_pinned_socket(self._pinned_address, self.port, self.timeout)


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(self, parameters: ConnectionParameters):
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        super().__init__(
            parameters.host,
            parameters.port,
            timeout=parameters.connect_timeout_seconds,
            context=context,
        )
        self._pinned_address = parameters.address

    def connect(self) -> None:
        if self._tunnel_host is not None:
            raise OSError("proxy tunnelling is disabled")
        plain = _open_pinned_socket(self._pinned_address, self.port, self.timeout)
        try:
            self.sock = self._context.wrap_socket(plain, server_hostname=self.host)
        except Exception:
            plain.close()
            raise


class _StdlibConnection:
    def __init__(self, parameters: ConnectionParameters):
        self._connection: http.client.HTTPConnection = (
            _PinnedHttpsConnection(parameters)
            if parameters.scheme == "https"
            else _PinnedHttpConnection(parameters)
        )

    def request(self, method: str, target: str, headers: Mapping[str, str]) -> None:
        self._connection.request(method, target, body=None, headers=dict(headers))

    def getresponse(self) -> ResponseStream:
        return self._connection.getresponse()

    def set_read_timeout(self, seconds: float) -> None:
        if self._connection.sock is None:
            raise OSError("connection socket is unavailable")
        self._connection.sock.settimeout(seconds)

    def close(self) -> None:
        self._connection.close()


def _default_connection_factory(parameters: ConnectionParameters) -> WebConnection:
    return _StdlibConnection(parameters)


@dataclass(frozen=True, slots=True)
class _Headers:
    values: dict[str, tuple[str, ...]]

    def one(self, name: str, *, required: bool = False) -> str | None:
        selected = self.values.get(name, ())
        if len(selected) > 1 or (required and not selected):
            raise WebTransportHeaderError
        return selected[0] if selected else None


def _validate_headers(raw: Any, limits: GuardedWebLimits) -> _Headers:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise WebTransportHeaderError
    if len(raw) > limits.max_header_count:
        raise WebTransportHeaderError
    values: dict[str, list[str]] = {}
    total = 0
    for item in raw:
        if (
            not isinstance(item, Sequence)
            or isinstance(item, (str, bytes, bytearray))
            or len(item) != 2
        ):
            raise WebTransportHeaderError
        name, value = item
        if not isinstance(name, str) or not isinstance(value, str):
            raise WebTransportHeaderError
        if (
            not name.isascii()
            or _HEADER_NAME.fullmatch(name) is None
            or len(name.encode("ascii")) > limits.max_header_name_bytes
            or not value.isascii()
            or len(value.encode("ascii")) > limits.max_header_value_bytes
            or any(
                ord(character) < 0x20 and character != "\t" or ord(character) == 0x7F
                for character in value
            )
        ):
            raise WebTransportHeaderError
        total += len(name) + len(value) + 4
        if total > limits.max_header_bytes:
            raise WebTransportHeaderError
        values.setdefault(name.lower(), []).append(value.strip())
    return _Headers({name: tuple(items) for name, items in values.items()})


def _framing(headers: _Headers, limits: GuardedWebLimits) -> tuple[int | None, bool]:
    content_length = headers.one("content-length")
    transfer_encoding = headers.one("transfer-encoding")
    if content_length is not None and transfer_encoding is not None:
        raise WebTransportHeaderError
    expected: int | None = None
    if content_length is not None:
        if not content_length.isascii() or not content_length.isdecimal():
            raise WebTransportHeaderError
        expected = int(content_length)
        if expected > limits.max_compressed_bytes:
            raise WebTransportBodyLimitError
    chunked = False
    if transfer_encoding is not None:
        if transfer_encoding.lower() != "chunked":
            raise WebTransportHeaderError
        chunked = True
    return expected, chunked


def _valid_content_type_parameter(value: str) -> bool:
    if _HEADER_NAME.fullmatch(value) is not None:
        return True
    if len(value) < 2 or value[0] != '"' or value[-1] != '"':
        return False
    escaped = False
    for character in value[1:-1]:
        if escaped:
            if not 0x20 <= ord(character) <= 0x7E:
                return False
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"' or not 0x20 <= ord(character) <= 0x7E:
            return False
    return not escaped


def _content_type(headers: _Headers, limits: GuardedWebLimits) -> str:
    raw = headers.one("content-type", required=True)
    assert raw is not None
    if len(raw) > 256:
        raise WebTransportContentTypeError
    parts = raw.split(";")
    media_type = parts[0].strip().lower()
    if _MEDIA_TYPE.fullmatch(media_type) is None or media_type not in limits.allowed_content_types:
        raise WebTransportContentTypeError
    for parameter in parts[1:]:
        name, separator, value = parameter.partition("=")
        if (
            separator != "="
            or _HEADER_NAME.fullmatch(name.strip()) is None
            or not _valid_content_type_parameter(value.strip())
        ):
            raise WebTransportContentTypeError
    return media_type


def _content_encoding(headers: _Headers) -> str:
    raw = headers.one("content-encoding")
    selected = "identity" if raw is None else raw.strip().lower()
    if selected not in {"identity", "gzip", "deflate"}:
        raise WebTransportEncodingError
    return selected


class GuardedWebTransport:
    """Perform one explicit, policy-bound HTTP(S) retrieval without canonical mutation."""

    def __init__(
        self,
        store: InstanceStore,
        connectors: ConnectorManager | None = None,
        *,
        limits: GuardedWebLimits | None = None,
        resolver: Resolver = _default_resolver,
        connection_factory: ConnectionFactory = _default_connection_factory,
        clock: Callable[[], float] = monotonic,
    ):
        self.store = store
        self.connectors = connectors or ConnectorManager(store)
        self.limits = limits or GuardedWebLimits()
        self.resolver = resolver
        self.connection_factory = connection_factory
        self.clock = clock

    def _deadline_timeout(self, deadline: float, stage_limit: float) -> float:
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise WebTransportTimeoutError
        return min(remaining, stage_limit)

    def _policy(self, request: GuardedWebRequest) -> tuple[dict[str, Any], _Target]:
        if request.network_authorization != "explicit":
            raise WebTransportAuthorizationError
        if (
            not isinstance(request.connector_instance_id, str)
            or not request.connector_instance_id
            or not isinstance(request.source_id, str)
            or not request.source_id
        ):
            raise WebTransportPolicyError
        try:
            config = self.store.read_config()
            connector = self.connectors.get_instance(request.connector_instance_id)
            source = self.connectors.get_source(
                request.connector_instance_id,
                request.source_id,
            )
        except (ConnectorError, OSError, ValueError):
            raise WebTransportPolicyError from None
        if connector is None or source is None:
            raise WebTransportPolicyError
        raw_network = config.get("network")
        global_network_allowed = (
            isinstance(raw_network, Mapping) and raw_network.get("external_access") is True
        )
        definition = connector.get("definition")
        if not isinstance(definition, Mapping):
            raise WebTransportPolicyError
        authorization_mode = connector.get("authorization_mode")
        authorization = connector.get("authorization")
        authorization_ready = (
            authorization_mode == "none"
            or authorization_mode == "external_secret"
            and connector.get("credential_reference_configured") is True
            or authorization_mode == "oauth2_pkce"
            and isinstance(authorization, Mapping)
            and authorization.get("status") == "authorized"
        )
        if (
            not global_network_allowed
            or connector.get("effective_network") != "explicit"
            or connector.get("lifecycle_state") != "active"
            or connector.get("configured_enabled") is not True
            or definition.get("network_access") != "explicit_only"
            or "manual_read" not in definition.get("capabilities", ())
            or not authorization_ready
            or source.get("source_kind") != "web"
            or source.get("lifecycle_state") != "active"
            or source.get("effective_enabled") is not True
        ):
            raise WebTransportPolicyError
        if request.conditional is not None and "conditional_metadata" not in definition.get(
            "capabilities", ()
        ):
            raise WebTransportPolicyError
        target = _normalise_url(request.url, self.limits)
        source_target = _normalise_url(source.get("external_id"), self.limits)
        allowed_origins = connector.get("allowed_origins")
        if (
            target.url != source_target.url
            or not isinstance(allowed_origins, Sequence)
            or isinstance(allowed_origins, (str, bytes, bytearray))
        ):
            raise WebTransportPolicyError
        if target.origin not in allowed_origins:
            for origin in allowed_origins:
                parsed_origin = urlsplit(str(origin))
                if parsed_origin.scheme == target.scheme and parsed_origin.hostname == target.host:
                    raise WebTransportPortError
            raise WebTransportPolicyError
        return dict(connector), target

    def _assert_current_authority(
        self,
        request: GuardedWebRequest,
        target: _Target,
    ) -> frozenset[str]:
        connector, _initial_target = self._policy(request)
        allowed_origins = frozenset(str(item) for item in connector["allowed_origins"])
        if target.origin not in allowed_origins:
            raise WebTransportPolicyError
        return allowed_origins

    def _resolve(self, target: _Target, *, connection_recheck: bool) -> tuple[str, ...]:
        try:
            literal = ip_address(target.host)
        except ValueError:
            literal = None
        if literal is not None:
            return (_public_ip(str(literal)),)
        try:
            raw = self.resolver(target.host, target.port)
        except Exception:
            raise WebTransportDnsError from None
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, (str, bytes, bytearray))
            or not raw
            or len(raw) > self.limits.max_resolved_addresses
        ):
            raise WebTransportDnsError
        selected: list[str] = []
        try:
            for value in raw:
                address = _public_ip(value)
                if address not in selected:
                    selected.append(address)
        except WebTransportDestinationError:
            if connection_recheck:
                raise WebTransportDnsRebindingError from None
            raise
        if not selected:
            raise WebTransportDnsError
        return tuple(selected)

    def _request_headers(
        self,
        request: GuardedWebRequest,
        *,
        send_conditionals: bool,
    ) -> dict[str, str]:
        headers = {
            "Accept": ", ".join(self.limits.allowed_content_types),
            "Accept-Encoding": "gzip, deflate, identity",
            "Connection": "close",
            "User-Agent": f"Provelume/{__version__} guarded-web-transport",
        }
        if send_conditionals and request.conditional is not None:
            if request.conditional.etag is not None:
                headers["If-None-Match"] = request.conditional.etag
            if request.conditional.last_modified is not None:
                headers["If-Modified-Since"] = request.conditional.last_modified
        return headers

    def _read_body(
        self,
        response: ResponseStream,
        *,
        expected_length: int | None,
        chunked: bool,
        encoding: str,
        deadline: float,
    ) -> tuple[bytes, int]:
        if expected_length is None and not chunked:
            raise WebTransportTruncatedError
        decompressor = (
            zlib.decompressobj(16 + zlib.MAX_WBITS)
            if encoding == "gzip"
            else zlib.decompressobj(zlib.MAX_WBITS)
            if encoding == "deflate"
            else None
        )
        body = bytearray()
        compressed = 0
        while True:
            self._deadline_timeout(deadline, self.limits.read_timeout_seconds)
            try:
                block = response.read(self.limits.read_chunk_bytes)
            except TimeoutError:
                raise WebTransportTimeoutError from None
            except (http.client.IncompleteRead, http.client.HTTPException, OSError):
                raise WebTransportTruncatedError from None
            if not isinstance(block, bytes):
                raise WebTransportResponseError
            if not block:
                break
            compressed += len(block)
            if compressed > self.limits.max_compressed_bytes:
                raise WebTransportBodyLimitError
            if decompressor is None:
                body.extend(block)
                if len(body) > self.limits.max_decompressed_bytes:
                    raise WebTransportBodyLimitError
            else:
                pending = block
                try:
                    while pending:
                        remaining = self.limits.max_decompressed_bytes - len(body)
                        expanded = decompressor.decompress(pending, remaining + 1)
                        body.extend(expanded)
                        if len(body) > self.limits.max_decompressed_bytes:
                            raise WebTransportBodyLimitError
                        pending = decompressor.unconsumed_tail
                except zlib.error:
                    raise WebTransportEncodingError from None
            if (
                compressed >= self.limits.decompression_ratio_floor_bytes
                and len(body) > compressed * self.limits.max_decompression_ratio
            ):
                raise WebTransportBodyLimitError
        if expected_length is not None and compressed != expected_length:
            raise WebTransportTruncatedError
        if decompressor is not None:
            try:
                remaining = self.limits.max_decompressed_bytes - len(body)
                body.extend(decompressor.flush(remaining + 1))
            except zlib.error:
                raise WebTransportEncodingError from None
            if len(body) > self.limits.max_decompressed_bytes:
                raise WebTransportBodyLimitError
            if not decompressor.eof:
                raise WebTransportTruncatedError
            if decompressor.unused_data or decompressor.unconsumed_tail:
                raise WebTransportEncodingError
            if (
                compressed >= self.limits.decompression_ratio_floor_bytes
                and len(body) > compressed * self.limits.max_decompression_ratio
            ):
                raise WebTransportBodyLimitError
        return bytes(body), compressed

    def fetch(self, request: GuardedWebRequest) -> GuardedWebResponse:
        _, target = self._policy(request)
        initial_origin = target.origin
        visited = {target.url}
        deadline = self.clock() + self.limits.total_timeout_seconds
        redirects = 0
        resources = 0

        while True:
            if resources >= self.limits.max_resources:
                raise WebTransportRedirectError
            allowed_origins = self._assert_current_authority(request, target)
            self._deadline_timeout(deadline, self.limits.total_timeout_seconds)
            self._resolve(target, connection_recheck=False)
            self._deadline_timeout(deadline, self.limits.total_timeout_seconds)
            addresses = self._resolve(target, connection_recheck=True)
            allowed_origins = self._assert_current_authority(request, target)
            parameters = ConnectionParameters(
                scheme=target.scheme,
                host=target.host,
                port=target.port,
                address=addresses[0],
                connect_timeout_seconds=self._deadline_timeout(
                    deadline,
                    self.limits.connect_timeout_seconds,
                ),
            )
            try:
                connection = self.connection_factory(parameters)
            except TimeoutError:
                raise WebTransportTimeoutError from None
            except Exception:
                raise WebTransportConnectionError from None
            try:
                try:
                    connection.request(
                        "GET",
                        target.request_target,
                        self._request_headers(
                            request,
                            send_conditionals=target.origin == initial_origin,
                        ),
                    )
                    response = connection.getresponse()
                    connection.set_read_timeout(
                        self._deadline_timeout(deadline, self.limits.read_timeout_seconds)
                    )
                except TimeoutError:
                    raise WebTransportTimeoutError from None
                except WebTransportError:
                    raise
                except Exception:
                    raise WebTransportConnectionError from None
                resources += 1
                status = getattr(response, "status", None)
                if type(status) is not int or not 100 <= status <= 599:
                    raise WebTransportResponseError
                try:
                    headers = _validate_headers(response.getheaders(), self.limits)
                except WebTransportError:
                    raise
                except Exception:
                    raise WebTransportHeaderError from None
                expected_length, chunked = _framing(headers, self.limits)

                if status in _REDIRECT_STATUSES:
                    location = headers.one("location", required=True)
                    if redirects >= self.limits.max_redirects or location is None:
                        raise WebTransportRedirectError
                    try:
                        next_target = _normalise_url(
                            urljoin(target.url, location),
                            self.limits,
                        )
                    except WebTransportError:
                        raise WebTransportRedirectError from None
                    if target.scheme == "https" and next_target.scheme != "https":
                        raise WebTransportRedirectError
                    if next_target.origin not in allowed_origins or next_target.url in visited:
                        raise WebTransportRedirectError
                    visited.add(next_target.url)
                    redirects += 1
                    target = next_target
                    continue

                if status not in {200, 204, 205, 304}:
                    raise WebTransportResponseError
                etag = headers.one("etag")
                last_modified = headers.one("last-modified")
                if etag is not None and not _valid_etag(etag):
                    raise WebTransportHeaderError
                if last_modified is not None and not _valid_http_date(last_modified):
                    raise WebTransportHeaderError

                if status == 304 and request.conditional is None:
                    raise WebTransportResponseError
                if status in _NO_BODY_STATUSES:
                    if (expected_length not in {None, 0}) or chunked:
                        raise WebTransportResponseError
                    self._deadline_timeout(deadline, self.limits.read_timeout_seconds)
                    try:
                        unexpected = response.read(1)
                    except TimeoutError:
                        raise WebTransportTimeoutError from None
                    except (http.client.IncompleteRead, http.client.HTTPException, OSError):
                        raise WebTransportResponseError from None
                    if unexpected != b"":
                        raise WebTransportResponseError
                    self._assert_current_authority(request, target)
                    return GuardedWebResponse(
                        status=status,
                        body=b"",
                        content_type=None,
                        content_encoding="identity",
                        etag=etag,
                        last_modified=last_modified,
                        final_url=target.url,
                        redirects=redirects,
                        resources=resources,
                        compressed_bytes=0,
                        decompressed_bytes=0,
                        not_modified=status == 304,
                    )

                content_type = _content_type(headers, self.limits)
                encoding = _content_encoding(headers)
                body, compressed = self._read_body(
                    response,
                    expected_length=expected_length,
                    chunked=chunked,
                    encoding=encoding,
                    deadline=deadline,
                )
                self._assert_current_authority(request, target)
                return GuardedWebResponse(
                    status=status,
                    body=body,
                    content_type=content_type,
                    content_encoding=encoding,
                    etag=etag,
                    last_modified=last_modified,
                    final_url=target.url,
                    redirects=redirects,
                    resources=resources,
                    compressed_bytes=compressed,
                    decompressed_bytes=len(body),
                    not_modified=False,
                )
            finally:
                with suppress(Exception):
                    connection.close()


__all__ = [
    "BLOCKED_WEB_PORTS",
    "ConditionalMetadata",
    "ConnectionParameters",
    "DEFAULT_ALLOWED_CONTENT_TYPES",
    "GuardedWebLimits",
    "GuardedWebRequest",
    "GuardedWebResponse",
    "GuardedWebTransport",
    "WebTransportAuthorizationError",
    "WebTransportBodyLimitError",
    "WebTransportConfigurationError",
    "WebTransportConnectionError",
    "WebTransportContentTypeError",
    "WebTransportDestinationError",
    "WebTransportDnsError",
    "WebTransportDnsRebindingError",
    "WebTransportEncodingError",
    "WebTransportError",
    "WebTransportHeaderError",
    "WebTransportPolicyError",
    "WebTransportPortError",
    "WebTransportRedirectError",
    "WebTransportResponseError",
    "WebTransportTimeoutError",
    "WebTransportTruncatedError",
    "WebTransportUrlError",
]
