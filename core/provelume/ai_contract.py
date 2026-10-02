"""Custodia v1 internal descriptors. No payload, endpoint or secret is accepted here."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from typing import Any, Self

from .representations import canonical_json_bytes

AI_SCHEMA_VERSION = 1
MAX_ASSOCIATIONS = 128
MAX_PROFILES = 16
MAX_DESCRIPTOR_BYTES = 128 * 1024
LIMIT_CEILINGS = (1024 * 1024, 8192, 4, 300)
_ID = re.compile(r"[a-z][a-z0-9_.-]{0,79}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class Capability(StrEnum):
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    TRANSCRIPTION = "transcription"
    TOOL_CALLING = "tool_calling"


class Mode(StrEnum):
    OFF = "off"
    LOCAL_ONLY = "local_only"
    REMOTE = "selected_remote"
    FALLBACK = "ordered_fallback"


class Scope(StrEnum):
    INSTANCE = "instance"
    SOURCE = "source"
    CATEGORY = "category"
    AREA = "area"
    PROJECT = "project"


class Locality(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class Assurance(StrEnum):
    MANAGED_OFFLINE = "managed_offline_qualified"
    REMOTE = "remote_qualified"
    UNQUALIFIED = "unqualified"


class Outcome(StrEnum):
    PLANNED = "planned"
    DENIED = "denied"
    SIMULATED = "simulated"
    EXECUTED = "executed"  # Reserved: no S01 producer may emit this outcome.


class Reason(StrEnum):
    INVALID = "ai_invalid_descriptor"
    SCHEMA = "ai_unknown_schema"
    OFF = "ai_off"
    DENY = "ai_explicit_deny"
    MISSING = "ai_missing_policy"
    CONFLICT = "ai_conflicting_policy"
    CAPABILITY = "ai_unsupported_capability"
    PROFILE = "ai_profile_not_allowed"
    LOCALITY = "ai_locality_unqualified"
    LOCAL_ONLY = "ai_local_only"
    NETWORK = "ai_network_disabled"
    LIMIT = "ai_limit_exceeded"
    ROUTE = "ai_route_not_configured"
    CONTEXT = "ai_context_mismatch"
    CONSENT = "ai_consent_missing"
    STALE = "ai_stale_plan"


class AiContractError(ValueError):
    """Closed error: never interpolate input or retain validation payloads."""

    def __init__(self, code: Reason = Reason.INVALID):
        self.code = Reason(code)
        super().__init__(self.code.value)


def require(condition: bool, reason: Reason = Reason.INVALID) -> None:
    if not condition:
        raise AiContractError(reason)


def identifier(value: Any) -> None:
    require(type(value) is str and _ID.fullmatch(value) is not None)


def fingerprint(value: Any) -> None:
    require(type(value) is str and _HASH.fullmatch(value) is not None)


def choice(value: Any, enum: type[StrEnum]) -> None:
    require(isinstance(value, (str, enum)) and value in tuple(enum))


def sequence(value: Any, maximum: int, *, empty: bool = True) -> None:
    require(type(value) is tuple and len(value) <= maximum and (empty or bool(value)))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class Contract:
    schema_version: int = AI_SCHEMA_VERSION

    def __post_init__(self) -> None:
        require(
            type(self.schema_version) is int and self.schema_version == AI_SCHEMA_VERSION,
            Reason.SCHEMA,
        )

    def as_record(self) -> dict[str, Any]:
        return asdict(self)

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_record())

    @property
    def fingerprint(self) -> str:
        return digest(self.as_record())


def closed(value: Any, cls: type[Contract]) -> dict:
    require(type(value) is dict and set(value) == {f.name for f in fields(cls)})
    require(type(value["schema_version"]) is int and value["schema_version"] == 1, Reason.SCHEMA)
    return dict(value)


@dataclass(frozen=True, slots=True, repr=False)
class Limits(Contract):
    max_input_bytes: int
    max_output_tokens: int
    max_attempts: int
    max_seconds: int

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        for value, ceiling in zip(self.values(), LIMIT_CEILINGS, strict=True):
            require(type(value) is int and 1 <= value <= ceiling)

    def values(self) -> tuple[int, ...]:
        return (self.max_input_bytes, self.max_output_tokens, self.max_attempts, self.max_seconds)

    @classmethod
    def from_mapping(cls, value: Any) -> Self:
        return cls(**closed(value, cls))


@dataclass(frozen=True, slots=True, repr=False)
class ScopeRef(Contract):
    kind: Scope
    id: str

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        choice(self.kind, Scope)
        identifier(self.id)


@dataclass(frozen=True, slots=True, repr=False)
class ContextBinding(Contract):
    instance_id: str
    document_id: str
    version_id: str
    context_fingerprint: str
    consent_revision: str

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        for item in (self.instance_id, self.document_id, self.version_id):
            identifier(item)
        fingerprint(self.context_fingerprint)
        fingerprint(self.consent_revision)


@dataclass(frozen=True, slots=True, repr=False)
class TemplateIdentity(Contract):
    id: str
    revision: str

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        identifier(self.id)
        fingerprint(self.revision)


@dataclass(frozen=True, slots=True, repr=False)
class RequestDescriptor(Contract):
    capability: Capability
    context: ContextBinding
    template: TemplateIdentity
    input_bytes: int
    limits: Limits

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        choice(self.capability, Capability)
        require(type(self.context) is ContextBinding and type(self.template) is TemplateIdentity)
        require(type(self.limits) is Limits)
        require(type(self.input_bytes) is int and 1 <= self.input_bytes <= LIMIT_CEILINGS[0])

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        row = closed(value, cls)
        row["context"] = ContextBinding(**closed(row["context"], ContextBinding))
        row["template"] = TemplateIdentity(**closed(row["template"], TemplateIdentity))
        row["limits"] = Limits.from_mapping(row["limits"])
        return cls(**row)


@dataclass(frozen=True, slots=True, repr=False)
class Profile(Contract):
    id: str
    provider: str
    model: str
    revision: str
    route_revision: str
    capabilities: tuple[Capability, ...]
    limits: Limits

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        for item in (self.id, self.provider, self.model):
            identifier(item)
        fingerprint(self.revision)
        fingerprint(self.route_revision)
        sequence(self.capabilities, len(Capability), empty=False)
        for item in self.capabilities:
            choice(item, Capability)
        require(len(set(self.capabilities)) == len(self.capabilities))
        object.__setattr__(self, "capabilities", tuple(sorted(self.capabilities)))
        require(type(self.limits) is Limits)


@dataclass(frozen=True, slots=True, repr=False)
class LocalityEvidence(Contract):
    """Host-supplied qualification, outside the candidate descriptor/profile.

    Digests bind independently accepted evidence; they do not authenticate it.
    The S01 planner neither acquires nor certifies qualification.
    """

    profile_fingerprint: str
    locality: Locality
    assurance: Assurance
    qualification_revision: str

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        fingerprint(self.profile_fingerprint)
        fingerprint(self.qualification_revision)
        choice(self.locality, Locality)
        choice(self.assurance, Assurance)


@dataclass(frozen=True, slots=True, repr=False)
class PolicyRule(Contract):
    scope: ScopeRef
    revision: str
    deny: bool = False
    local_only: bool = False
    allowed_profiles: tuple[str, ...] | None = None
    allowed_capabilities: tuple[Capability, ...] | None = None
    limits: Limits | None = None
    mode: Mode | None = None
    route: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        require(type(self.scope) is ScopeRef)
        fingerprint(self.revision)
        require(type(self.deny) is bool and type(self.local_only) is bool)
        if self.allowed_profiles is not None:
            sequence(self.allowed_profiles, MAX_PROFILES)
            for item in self.allowed_profiles:
                identifier(item)
            require(len(set(self.allowed_profiles)) == len(self.allowed_profiles))
            object.__setattr__(self, "allowed_profiles", tuple(sorted(self.allowed_profiles)))
        if self.allowed_capabilities is not None:
            sequence(self.allowed_capabilities, len(Capability))
            for item in self.allowed_capabilities:
                choice(item, Capability)
            require(len(set(self.allowed_capabilities)) == len(self.allowed_capabilities))
            object.__setattr__(
                self, "allowed_capabilities", tuple(sorted(self.allowed_capabilities))
            )
        require(self.limits is None or type(self.limits) is Limits)
        if self.mode is not None:
            choice(self.mode, Mode)
        sequence(self.route, LIMIT_CEILINGS[2])
        for item in self.route:
            identifier(item)
        require(len(set(self.route)) == len(self.route))
        require(not self.route if self.mode in (None, Mode.OFF) else bool(self.route))
        require(self.mode == Mode.FALLBACK or len(self.route) <= 1)


@dataclass(frozen=True, slots=True, repr=False)
class GovernanceSnapshot(Contract):
    """Independent complete scope inventory, including all acquisitions/ancestors.

    No caller-selectable subset lives in RequestDescriptor. A future host must
    collect this from authoritative current state; S01 only consumes snapshots.
    """

    context: ContextBinding
    scopes: tuple[ScopeRef, ...]
    revision: str
    external_access: bool
    consent_granted: bool

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        require(type(self.context) is ContextBinding)
        sequence(self.scopes, MAX_ASSOCIATIONS, empty=False)
        require(all(type(item) is ScopeRef for item in self.scopes))
        keys = [(item.kind, item.id) for item in self.scopes]
        require(len(set(keys)) == len(keys))
        require(
            [item.id for item in self.scopes if item.kind == Scope.INSTANCE]
            == [self.context.instance_id]
        )
        require({Scope.SOURCE, Scope.CATEGORY} <= {item.kind for item in self.scopes})
        fingerprint(self.revision)
        require(type(self.external_access) is bool and type(self.consent_granted) is bool)


@dataclass(frozen=True, slots=True, repr=False)
class EffectivePolicy(Contract):
    mode: Mode
    local_only: bool
    allowed_profiles: tuple[str, ...]
    allowed_capabilities: tuple[Capability, ...]
    limits: Limits
    route: tuple[str, ...]
    policy_fingerprint: str

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        choice(self.mode, Mode)
        require(type(self.local_only) is bool and type(self.limits) is Limits)
        fingerprint(self.policy_fingerprint)
        sequence(self.allowed_profiles, MAX_PROFILES)
        sequence(self.allowed_capabilities, len(Capability))
        sequence(self.route, LIMIT_CEILINGS[2], empty=False)
        for item in (*self.allowed_profiles, *self.route):
            identifier(item)
        for item in self.allowed_capabilities:
            choice(item, Capability)


@dataclass(frozen=True, slots=True, repr=False)
class RouteDecision(Contract):
    position: int
    profile_fingerprint: str
    eligible: bool
    reasons: tuple[Reason, ...]

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        require(type(self.position) is int and 0 <= self.position < LIMIT_CEILINGS[2])
        fingerprint(self.profile_fingerprint)
        require(type(self.eligible) is bool and self.eligible == (not self.reasons))
        sequence(self.reasons, len(Reason))
        for item in self.reasons:
            choice(item, Reason)


@dataclass(frozen=True, slots=True, repr=False)
class Plan(Contract):
    outcome: Outcome
    reasons: tuple[Reason, ...]
    binding: str | None
    policy_fingerprint: str | None
    limits: Limits | None
    routes: tuple[RouteDecision, ...]
    execution_authorized: bool = False
    canonical_mutation: bool = False
    network_used: bool = False

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        require(self.outcome in (Outcome.PLANNED, Outcome.DENIED))
        require(
            self.execution_authorized is False
            and self.canonical_mutation is False
            and self.network_used is False
        )
        sequence(self.reasons, len(Reason))
        for item in self.reasons:
            choice(item, Reason)
        sequence(self.routes, LIMIT_CEILINGS[2])
        require(all(type(item) is RouteDecision for item in self.routes))
        require(tuple(item.position for item in self.routes) == tuple(range(len(self.routes))))
        require(self.limits is None or type(self.limits) is Limits)
        for item in (self.binding, self.policy_fingerprint):
            if item is not None:
                fingerprint(item)
        require((self.binding is None) == (self.policy_fingerprint is None))
        if self.outcome == Outcome.PLANNED:
            require(
                not self.reasons
                and self.binding is not None
                and bool(self.routes)
                and self.routes[0].eligible
                and self.limits is not None
            )
        else:
            require(bool(self.reasons))


@dataclass(frozen=True, slots=True, repr=False)
class BaseReceipt(Contract):
    outcome: Outcome
    binding: str | None
    reasons: tuple[Reason, ...]
    attempted_routes: tuple[str, ...] = ()
    transmitted: bool = False
    usage: None = None  # Unknown/not applicable, never a fabricated zero bill.
    canonical_mutation: bool = False

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        require(self.outcome in (Outcome.PLANNED, Outcome.DENIED, Outcome.SIMULATED))
        require(self.transmitted is False and self.canonical_mutation is False)
        require(self.usage is None and self.attempted_routes == ())
        if self.binding is not None:
            fingerprint(self.binding)
        sequence(self.reasons, len(Reason))
        for reason in self.reasons:
            choice(reason, Reason)
        require(
            bool(self.reasons)
            if self.outcome == Outcome.DENIED
            else self.binding is not None and not self.reasons
        )


@dataclass(frozen=True, slots=True, repr=False)
class SimulatedResult(Contract):
    fixture: str
    output_fingerprint: str
    receipt: BaseReceipt

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        require(self.fixture == "synthetic_contract_v1")
        fingerprint(self.output_fingerprint)
        require(type(self.receipt) is BaseReceipt and self.receipt.outcome == Outcome.SIMULATED)
