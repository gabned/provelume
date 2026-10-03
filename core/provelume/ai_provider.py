"""Internal S03 transport contract. No registry, product dispatcher or persistence.

Only the synthetic harness invokes adapters. The service exposes validation and
explicit connection-only diagnostics; S06 must establish execution authority.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import IPv6Address, ip_address, ip_network
from typing import Protocol
from urllib.parse import urlsplit

from .ai_context import (
    RedactionPreview,
    ValidatedCandidate,
    prepared_request,
    task_payload,
    validate_candidate,
)
from .ai_contract import (
    AiContractError,
    Assurance,
    Capability,
    Contract,
    Locality,
    Outcome,
    Plan,
    Profile,
    Reason,
    closed,
    require,
)
from .ai_gateway import receipt, revalidate
from .connector_model import ConnectorError, normalise_secret_reference
from .web_transport import WebTransportError, _public_ip

WIRE_PROFILE = "chat-json-v1"
_LAN = tuple(ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))


class Destination(StrEnum):
    MANAGED = "managed_loopback"
    LAN = "explicit_lan"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class Failure(StrEnum):
    CONFIG = "ai_transport_configuration"
    DISABLED = "ai_execution_requires_s06"
    POLICY = "ai_transport_policy_or_stale"
    CREDENTIAL = "ai_credential_unavailable"
    DESTINATION = "ai_destination_refused"
    DNS = "ai_dns_failed"
    CONNECTION = "ai_connection_failed"
    TLS = "ai_tls_failed"
    AUTH = "ai_authentication_failed"
    RATE_LIMIT = "ai_rate_limited"
    TIMEOUT = "ai_transport_timeout"
    CANCELLED = "ai_transport_cancelled"
    LIMIT = "ai_transport_limit"
    TRUNCATED = "ai_response_truncated"
    INCOMPATIBLE = "ai_protocol_incompatible"
    REDIRECT = "ai_redirect_refused"
    REMOTE = "ai_remote_failure"


class Transmission(StrEnum):
    NOT_SENT = "not_sent"
    POSSIBLE = "possibly_sent_remote_outcome_unknown"
    RESPONSE = "response_received"


class ProviderError(ValueError):
    """Closed code only; never retain an endpoint, credential or provider body."""

    def __init__(self, code: Failure, transmission=Transmission.NOT_SENT):
        self.code = Failure(code)
        self.transmission = Transmission(transmission)
        super().__init__(self.code.value)


def check(condition, code=Failure.CONFIG):
    if not condition:
        raise ProviderError(code)


@dataclass(frozen=True, slots=True, repr=False)
class WireLimits(Contract):
    request_bytes: int = 64 * 1024
    response_bytes: int = 64 * 1024
    header_bytes: int = 8192
    header_count: int = 32
    line_bytes: int = 2048
    seconds: int = 10

    def __post_init__(self):
        Contract.__post_init__(self)
        for name, ceiling in (
            ("request_bytes", 1024 * 1024),
            ("response_bytes", 256 * 1024),
            ("header_bytes", 16384),
            ("header_count", 64),
            ("line_bytes", 4096),
            ("seconds", 30),
        ):
            value = getattr(self, name)
            check(type(value) is int and 1 <= value <= ceiling)


@dataclass(frozen=True, slots=True, repr=False)
class CredentialReference(Contract):
    kind: str
    name: str

    def __post_init__(self):
        Contract.__post_init__(self)
        try:
            normalise_secret_reference({"kind": self.kind, "name": self.name})
        except ConnectorError:
            raise ProviderError(Failure.CONFIG) from None
        # Only explicitly injected vaults. No environment lookup implementation.
        check(self.kind == "system_keyring")


@dataclass(frozen=True, slots=True, repr=False)
class Endpoint:
    scheme: str
    host: str
    port: int
    authority: str


def endpoint(value: str) -> Endpoint:
    check(type(value) is str and 1 <= len(value) <= 512 and value.isascii())
    check(not any(ord(c) <= 32 or ord(c) == 127 for c in value))
    check(not any(c in value for c in ("@", "%", "\\", "?", "#")))
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        check(parsed.scheme in ("https", "http") and bool(host))
        check(parsed.path == "/v1/chat/completions" and not parsed.query and not parsed.fragment)
        check(host == host.lower() and not host.endswith("."))
        try:
            address = ip_address(host)
        except ValueError:
            check(
                not all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", part) for part in host.split("."))
            )
            check(host == "localhost" or ("." in host and len(host) <= 253))
            check(
                all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p)
                    for p in host.split(".")
                )
            )
            display = host
        else:
            check(str(address) == host)
            display = f"[{host}]" if isinstance(address, IPv6Address) else host
        check(port is None or 1 <= port <= 65535)
        authority = display + (f":{port}" if port is not None else "")
        check(value == f"{parsed.scheme}://{authority}/v1/chat/completions")
        return Endpoint(
            parsed.scheme, host, port or (443 if parsed.scheme == "https" else 80), authority
        )
    except (ValueError, TypeError):
        raise ProviderError(Failure.CONFIG) from None


def _address(raw):
    check(type(raw) is str and len(raw) <= 45 and "%" not in raw, Failure.DESTINATION)
    try:
        value = ip_address(raw)
    except ValueError:
        raise ProviderError(Failure.DESTINATION) from None
    # No scoped, translated, tunnel or mapped spellings in this initial profile.
    if isinstance(value, IPv6Address):
        check(
            value.ipv4_mapped is None and value.sixtofour is None and value.teredo is None,
            Failure.DESTINATION,
        )
    check(str(value) == raw, Failure.DESTINATION)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class ProviderConfig(Contract):
    endpoint_url: str
    destination: Destination
    credential: CredentialReference | None = None
    lan_addresses: tuple[str, ...] = ()
    wire: str = WIRE_PROFILE
    limits: WireLimits = field(default_factory=WireLimits)

    def __post_init__(self):
        Contract.__post_init__(self)
        target = endpoint(self.endpoint_url)
        check(self.wire == WIRE_PROFILE and self.destination in tuple(Destination))
        object.__setattr__(self, "destination", Destination(self.destination))
        check(type(self.limits) is WireLimits)
        check(self.credential is None or type(self.credential) is CredentialReference)
        check(type(self.lan_addresses) is tuple and len(self.lan_addresses) <= 16)
        check(len(set(self.lan_addresses)) == len(self.lan_addresses))
        if self.destination == Destination.LAN:
            check(bool(self.lan_addresses) and target.scheme == "https")
            for raw in self.lan_addresses:
                address = _address(raw)
                check(any(address in network for network in _LAN), Failure.DESTINATION)
        else:
            check(not self.lan_addresses)
        check(target.scheme == "https" or self.destination == Destination.MANAGED)
        # Literal addresses can be refused without DNS or secrets.
        try:
            ip_address(target.host)
        except ValueError:
            pass
        else:
            admit_address(self, target.host)

    @classmethod
    def from_mapping(cls, value):
        try:
            row = closed(value, cls)
            row["limits"] = WireLimits(**closed(row["limits"], WireLimits))
            if row["credential"] is not None:
                row["credential"] = CredentialReference(
                    **closed(row["credential"], CredentialReference)
                )
            check(type(row["lan_addresses"]) in (list, tuple))
            row["lan_addresses"] = tuple(row["lan_addresses"])
            return cls(**row)
        except (AiContractError, TypeError, KeyError):
            raise ProviderError(Failure.CONFIG) from None


def admit_address(config, raw):
    value = _address(raw)
    if config.destination == Destination.MANAGED:
        check(value.is_loopback, Failure.DESTINATION)
    elif config.destination == Destination.LAN:
        check(raw in config.lan_addresses, Failure.DESTINATION)
    elif config.destination == Destination.REMOTE:
        try:
            _public_ip(raw)  # Reuse the existing strict public-IP predicate unchanged.
        except WebTransportError:
            raise ProviderError(Failure.DESTINATION) from None
    else:
        raise ProviderError(Failure.DESTINATION)
    return str(value)


def validate_configuration(profile, config):
    """Pure local validation; availability is not provider/model qualification."""
    check(type(profile) is Profile and type(config) is ProviderConfig)
    check(profile.capabilities == (Capability.STRUCTURED_OUTPUT,))
    check(profile.route_revision == config.fingerprint)
    check(config.destination != Destination.UNKNOWN)
    return {
        "configuration": "valid",
        "wire": WIRE_PROFILE,
        "destination": config.destination.value,
        "live_verification": "NOT_RUN",
        "product_execution": "disabled_until_s06",
    }


@dataclass(frozen=True, slots=True, repr=False)
class CallInputs:
    """Host-owned current snapshots, never a document/provider-supplied authority."""

    plan: Plan
    preview: RedactionPreview
    source: object
    selections: tuple
    current: dict
    profiles: tuple
    evidence: tuple
    config: ProviderConfig

    def prepare(self):
        try:
            request, snapshot = prepared_request(
                self.preview, self.source, self.selections, **self.current
            )
            fresh = revalidate(
                self.plan,
                request,
                snapshot=snapshot,
                rules=self.current["rules"],
                profiles=self.profiles,
                evidence=self.evidence,
            )
            require(fresh.outcome == Outcome.PLANNED, Reason.STALE)
            profile = next(
                p for p in self.profiles if p.fingerprint == fresh.routes[0].profile_fingerprint
            )
            validate_configuration(profile, self.config)
            qualification = next(
                e for e in self.evidence if e.profile_fingerprint == profile.fingerprint
            )
            expected = (
                (Locality.LOCAL, Assurance.MANAGED_OFFLINE)
                if self.config.destination == Destination.MANAGED
                else (Locality.REMOTE, Assurance.REMOTE)
            )
            require((qualification.locality, qualification.assurance) == expected, Reason.LOCALITY)
            return request, profile
        except (AiContractError, StopIteration):
            raise ProviderError(Failure.POLICY) from None


def encode_bounded(value, maximum):
    parts, size = [], 0
    for part in json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).iterencode(value):
        raw = part.encode("utf-8", errors="strict")
        size += len(raw)
        check(size <= maximum, Failure.LIMIT)
        parts.append(raw)
    return b"".join(parts)


def wire_request(inputs):
    request, profile = inputs.prepare()
    envelope = json.loads(task_payload(inputs.preview, inputs.current["template"]))
    maximum = min(request.limits.max_input_bytes, inputs.config.limits.request_bytes)
    return encode_bounded(
        {
            "model": profile.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return JSON. " + envelope["trusted"]["instructions"],
                },
                {
                    "role": "user",
                    "content": encode_bounded(envelope["untrusted"], maximum).decode(),
                },
            ],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": request.limits.max_output_tokens,
            "n": 1,
            "stream": False,
            "store": False,
        },
        maximum,
    )


@dataclass(frozen=True, slots=True, repr=False)
class ExchangeResult:
    candidate: ValidatedCandidate
    receipt: dict


class ProviderAdapter(Protocol):
    def exchange(self, current: Callable[[], CallInputs], *, cancel) -> ExchangeResult: ...


def accept_candidate(raw, inputs, *, transmission):
    inputs.prepare()  # Recheck source/governance/consent/profile before accepting output.
    try:
        candidate = validate_candidate(
            raw, inputs.preview, inputs.source, inputs.selections, **inputs.current
        )
    except AiContractError:
        raise ProviderError(Failure.INCOMPATIBLE, transmission) from None
    # Ephemeral transport evidence; the S01 BaseReceipt remains a non-execution receipt.
    return ExchangeResult(
        candidate,
        {
            "schema_version": 1,
            "plan_receipt": receipt(inputs.plan).as_record(),
            "binding": inputs.plan.binding,
            "profile_fingerprint": inputs.plan.routes[0].profile_fingerprint,
            "transport_fingerprint": inputs.config.fingerprint,
            "transmission": transmission.value,
            "usage": "UNKNOWN",
            "attempts": 1,
            "canonical_mutation": False,
            "product_execution": False,
        },
    )


def product_execution_status():
    return {"enabled": False, "reason": Failure.DISABLED.value}
