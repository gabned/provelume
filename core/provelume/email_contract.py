from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

EMAIL_CONTRACT_SCHEMA_VERSION = 1
EMAIL_ADAPTER_PROTOCOL_VERSION = 1
EMAIL_PARSER_PROTOCOL_VERSION = 1
EMAIL_ADAPTER_ID = "provelume.local-email"
EMAIL_ADAPTER_VERSION = "1.0.0"
EMAIL_PARSER_ID = "python.email"
EMAIL_PARSER_VERSION = "stdlib-3.12"

EMAIL_FORMATS = ("eml", "maildir")
EMAIL_PROFILES = ("eml-file-v1", "maildir-cur-new-v1")
EMAIL_SUPPORTED_PROFILES = EMAIL_PROFILES
EMAIL_UNSUPPORTED_PROFILES = ("mbox",)
EMAIL_PROFILE_FORMATS = MappingProxyType(
    {"eml-file-v1": "eml", "maildir-cur-new-v1": "maildir"}
)
EMAIL_SOURCE_STATES = ("enabled", "paused", "disabled")
EMAIL_CAPABILITY_STATES = (
    "ready",
    "runtime-unqualified",
    "format-unsupported",
    "profile-unsupported",
    "source-missing",
    "source-unsafe",
)
EMAIL_QUALIFIED_TARGETS = (
    "ubuntu-24.04-x86_64-cpython312",
    "windows-x86_64-cpython312",
)
EMAIL_PROFILE_QUALIFIED_TARGETS = MappingProxyType(
    {
        "eml-file-v1": EMAIL_QUALIFIED_TARGETS,
        "maildir-cur-new-v1": ("ubuntu-24.04-x86_64-cpython312",),
    }
)

EMAIL_ERROR_CODES = (
    "email_disabled",
    "email_source_disabled",
    "email_source_paused",
    "email_source_removed",
    "email_format_unsupported",
    "email_profile_unsupported",
    "email_runtime_unqualified",
    "email_source_missing",
    "email_source_unsafe",
    "email_input_non_regular",
    "email_input_changed",
    "email_message_limit_exceeded",
    "email_container_limit_exceeded",
    "email_total_read_limit_exceeded",
    "email_header_limit_exceeded",
    "email_mime_limit_exceeded",
    "email_attachment_limit_exceeded",
    "email_decoded_limit_exceeded",
    "email_message_malformed",
    "email_mime_malformed",
    "email_transfer_invalid",
    "email_timeout",
    "email_cancelled",
    "email_derived_invalid",
    "email_internal_error",
)

EMAIL_WARNING_CODES = (
    "header_repeated",
    "header_malformed",
    "encoded_word_invalid",
    "declared_date_invalid",
    "declared_message_id_absent",
    "declared_message_id_malformed",
    "declared_message_id_repeated",
    "reference_malformed",
    "reference_repeated",
    "charset_absent",
    "charset_unsupported",
    "charset_invalid",
    "html_body_unavailable",
    "body_text_unavailable",
    "mime_defect",
    "unsupported_signed_part",
    "unsupported_encrypted_part",
    "nested_message_preserved",
    "declared_message_id_collision",
    "thread_reference_missing",
    "thread_reference_ambiguous",
    "thread_reference_cycle",
    "thread_reference_cross_source",
)

MIB = 1024 * 1024
KIB = 1024

EMAIL_LIMIT_CEILINGS = {
    "max_message_bytes": 256 * MIB,
    "max_maildir_container_bytes": 8 * 1024 * MIB,
    "max_messages_per_run": 10_000,
    "max_total_read_bytes": 4 * 1024 * MIB,
    "max_headers_per_message": 4_096,
    "max_header_bytes_per_message": 4 * MIB,
    "max_header_line_bytes": 1 * MIB,
    "max_mime_parts": 4_096,
    "max_mime_depth": 64,
    "max_nested_message_depth": 16,
    "max_attachments_per_message": 1_000,
    "max_attachment_bytes": 128 * MIB,
    "max_total_attachment_bytes_per_message": 256 * MIB,
    "max_decoded_bytes_per_message": 256 * MIB,
    "max_decoded_bytes_per_run": 4 * 1024 * MIB,
    "max_body_characters": 5_000_000,
    "max_reference_tokens": 1_000,
    "max_warnings_per_message": 1_000,
    "max_errors_per_run": 10_000,
    "max_temp_bytes_per_job": 8 * 1024 * MIB,
    "max_seconds_per_message": 300,
    "max_seconds_per_job": 86_400,
}

_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PART_ID = re.compile(r"epart_[0-9a-f]{64}\Z")


class EmailContractError(ValueError):
    """A closed, content-free local email contract failure."""

    def __init__(self, code: str, message: str):
        if code not in EMAIL_ERROR_CODES:
            raise ValueError("email error code is outside the closed registry")
        super().__init__(message)
        self.code = code


def _bounded_integer(value: Any, name: str, *, ceiling: int) -> int:
    if type(value) is not int or value < 1 or value > ceiling:
        raise EmailContractError(
            "email_internal_error",
            f"{name} must be an integer between 1 and {ceiling}",
        )
    return value


@dataclass(frozen=True, slots=True)
class EmailLimits:
    max_message_bytes: int = 32 * MIB
    max_maildir_container_bytes: int = 512 * MIB
    max_messages_per_run: int = 500
    max_total_read_bytes: int = 256 * MIB
    max_headers_per_message: int = 512
    max_header_bytes_per_message: int = 256 * KIB
    max_header_line_bytes: int = 16 * KIB
    max_mime_parts: int = 256
    max_mime_depth: int = 16
    max_nested_message_depth: int = 4
    max_attachments_per_message: int = 100
    max_attachment_bytes: int = 20 * MIB
    max_total_attachment_bytes_per_message: int = 30 * MIB
    max_decoded_bytes_per_message: int = 32 * MIB
    max_decoded_bytes_per_run: int = 256 * MIB
    max_body_characters: int = 500_000
    max_reference_tokens: int = 100
    max_warnings_per_message: int = 200
    max_errors_per_run: int = 500
    max_temp_bytes_per_job: int = 512 * MIB
    max_seconds_per_message: int = 30
    max_seconds_per_job: int = 600

    def __post_init__(self) -> None:
        for name, ceiling in EMAIL_LIMIT_CEILINGS.items():
            _bounded_integer(getattr(self, name), name, ceiling=ceiling)
        if self.max_maildir_container_bytes < self.max_message_bytes:
            raise EmailContractError(
                "email_internal_error",
                "maildir container limit cannot be lower than the message limit",
            )
        if self.max_total_read_bytes < self.max_message_bytes:
            raise EmailContractError(
                "email_internal_error",
                "total read limit cannot be lower than the message limit",
            )
        if self.max_total_attachment_bytes_per_message < self.max_attachment_bytes:
            raise EmailContractError(
                "email_internal_error",
                "attachment total limit cannot be lower than the per-attachment limit",
            )
        if (
            self.max_decoded_bytes_per_message
            < self.max_total_attachment_bytes_per_message
        ):
            raise EmailContractError(
                "email_internal_error",
                "decoded message limit cannot be lower than the attachment total",
            )
        if self.max_decoded_bytes_per_run < self.max_decoded_bytes_per_message:
            raise EmailContractError(
                "email_internal_error",
                "decoded run limit cannot be lower than the decoded message limit",
            )
        if self.max_seconds_per_job < self.max_seconds_per_message:
            raise EmailContractError(
                "email_internal_error",
                "job deadline cannot be lower than the message deadline",
            )

    @classmethod
    def from_mapping(cls, value: Any) -> EmailLimits:
        if not isinstance(value, Mapping) or set(value) != set(EMAIL_LIMIT_CEILINGS):
            raise EmailContractError(
                "email_internal_error",
                "email limit fields are incomplete or unsupported",
            )
        return cls(**{name: value[name] for name in EMAIL_LIMIT_CEILINGS})

    def as_record(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EmailSourceConfig:
    source_id: str
    mailbox_format: Literal["eml", "maildir"]
    profile: Literal["eml-file-v1", "maildir-cur-new-v1"]
    path: Path = field(repr=False)
    state: Literal["enabled", "paused", "disabled"] = "disabled"
    adapter_id: str = EMAIL_ADAPTER_ID
    adapter_version: str = EMAIL_ADAPTER_VERSION
    schema_version: int = EMAIL_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EMAIL_CONTRACT_SCHEMA_VERSION:
            raise EmailContractError(
                "email_internal_error", "unsupported email Source schema version"
            )
        if _SOURCE_ID.fullmatch(self.source_id) is None:
            raise EmailContractError("email_internal_error", "email Source ID is invalid")
        if self.mailbox_format not in EMAIL_FORMATS:
            raise EmailContractError(
                "email_format_unsupported", "email Source format is unsupported"
            )
        expected_profile = {
            "eml": "eml-file-v1",
            "maildir": "maildir-cur-new-v1",
        }[self.mailbox_format]
        if self.profile != expected_profile:
            raise EmailContractError(
                "email_profile_unsupported",
                "email Source profile does not match its format",
            )
        if self.state not in EMAIL_SOURCE_STATES:
            raise EmailContractError("email_internal_error", "email Source state is invalid")
        selected_path = Path(self.path)
        if not selected_path.is_absolute() or "\x00" in str(selected_path):
            raise EmailContractError(
                "email_source_unsafe", "email Source path must be absolute and local"
            )
        object.__setattr__(self, "path", selected_path)
        if self.adapter_id != EMAIL_ADAPTER_ID or self.adapter_version != EMAIL_ADAPTER_VERSION:
            raise EmailContractError(
                "email_profile_unsupported", "email Source adapter identity is unsupported"
            )

    def public_record(self) -> dict[str, Any]:
        """Return the path-free configuration identity safe for retained evidence."""

        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "mailbox_format": self.mailbox_format,
            "profile": self.profile,
            "state": self.state,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "network_access": "none",
        }


def qualified_runtime_target() -> str:
    system = platform.system().casefold()
    release = platform.release().casefold().replace(" ", "-")
    if system == "linux":
        try:
            os_release = platform.freedesktop_os_release()
        except OSError:
            os_release = {}
        distribution = os_release.get("ID", "linux").casefold()
        release = os_release.get("VERSION_ID", release).casefold()
        system = distribution
    machine = platform.machine().casefold()
    architecture = (
        "x86_64" if machine in {"amd64", "x86_64"} else machine.replace("-", "_")
    )
    implementation = platform.python_implementation().casefold()
    return (
        f"{system}-{release}-{architecture}-"
        f"{implementation}{sys.version_info.major}{sys.version_info.minor}"
    )


def _runtime_is_qualified(profile: str, target: str) -> bool:
    if profile == "eml-file-v1" and target.startswith("windows-"):
        return target.endswith("-x86_64-cpython312")
    return target in EMAIL_PROFILE_QUALIFIED_TARGETS.get(profile, ())


@dataclass(frozen=True, slots=True)
class EmailAdapterCapability:
    schema_version: int
    adapter_id: str
    adapter_version: str
    adapter_protocol_version: int
    mailbox_format: str
    profile: str
    available: bool
    state: str
    reason: str | None
    current_target: str
    qualified_targets: tuple[str, ...]
    parser_id: str
    parser_version: str
    limits: EmailLimits
    network_access: Literal["none"] = "none"
    runtime_downloads: Literal[False] = False
    remote_fallback: Literal[False] = False

    def as_record(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "qualified_targets": list(self.qualified_targets),
            "limits": self.limits.as_record(),
        }


def email_adapter_capability(
    mailbox_format: str,
    profile: str,
    *,
    limits: EmailLimits | None = None,
) -> EmailAdapterCapability:
    selected_limits = limits or EmailLimits()
    expected = {
        "eml": "eml-file-v1",
        "maildir": "maildir-cur-new-v1",
    }
    target = qualified_runtime_target()
    if mailbox_format not in expected:
        state = "format-unsupported"
        reason = "email_format_unsupported"
    elif profile != expected[mailbox_format]:
        state = "profile-unsupported"
        reason = "email_profile_unsupported"
    elif not _runtime_is_qualified(profile, target):
        state = "runtime-unqualified"
        reason = "email_runtime_unqualified"
    else:
        state = "ready"
        reason = None
    return EmailAdapterCapability(
        schema_version=EMAIL_CONTRACT_SCHEMA_VERSION,
        adapter_id=EMAIL_ADAPTER_ID,
        adapter_version=EMAIL_ADAPTER_VERSION,
        adapter_protocol_version=EMAIL_ADAPTER_PROTOCOL_VERSION,
        mailbox_format=mailbox_format,
        profile=profile,
        available=state == "ready",
        state=state,
        reason=reason,
        current_target=target,
        qualified_targets=EMAIL_PROFILE_QUALIFIED_TARGETS.get(profile, ()),
        parser_id=EMAIL_PARSER_ID,
        parser_version=EMAIL_PARSER_VERSION,
        limits=selected_limits,
    )


@dataclass(frozen=True, slots=True)
class SourceProbe:
    schema_version: int
    source_id: str
    mailbox_format: str
    profile: str
    available: bool
    state: str
    reason: str | None
    container_identity_sha256: str | None
    network_attempted: Literal[False] = False

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FilesystemIdentity:
    device: int
    inode: int
    size_bytes: int
    mtime_ns: int
    ctime_ns: int
    link_count: int
    file_attributes: int

    def as_record(self) -> dict[str, int]:
        return asdict(self)

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.as_record(), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class MessageCandidate:
    source_id: str
    mailbox_format: str
    profile: str
    container_identity_sha256: str
    snapshot_sha256: str
    locator_sha256: str
    filesystem: FilesystemIdentity


@dataclass(frozen=True, slots=True)
class ContainerSnapshot:
    schema_version: int
    source_id: str
    mailbox_format: str
    profile: str
    container_identity_sha256: str
    snapshot_sha256: str
    observed_at: str
    message_count: int
    total_bytes: int
    candidates: tuple[MessageCandidate, ...]
    network_used: Literal[False] = False

    def public_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "mailbox_format": self.mailbox_format,
            "profile": self.profile,
            "container_identity_sha256": self.container_identity_sha256,
            "snapshot_sha256": self.snapshot_sha256,
            "observed_at": self.observed_at,
            "message_count": self.message_count,
            "total_bytes": self.total_bytes,
            "candidates": [
                {
                    "locator_sha256": item.locator_sha256,
                    "filesystem_identity_sha256": item.filesystem.fingerprint(),
                    "size_bytes": item.filesystem.size_bytes,
                }
                for item in self.candidates
            ],
            "network_used": False,
        }


@dataclass(frozen=True, slots=True)
class ObservedMessageBytes:
    source_id: str
    mailbox_format: str
    profile: str
    container_identity_sha256: str
    snapshot_sha256: str
    locator_sha256: str
    filesystem: FilesystemIdentity
    observed_at: str
    acquired_at: str
    sha256: str
    size_bytes: int
    data: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class EmailWarning:
    code: str
    part_id: str | None = None
    header_name: str | None = None
    occurrence: int | None = None

    def __post_init__(self) -> None:
        if self.code not in EMAIL_WARNING_CODES:
            raise ValueError("email warning code is outside the closed registry")
        if self.part_id is not None and _PART_ID.fullmatch(self.part_id) is None:
            raise ValueError("email warning part ID is invalid")


@dataclass(frozen=True, slots=True)
class ParsedHeader:
    name: str
    occurrence: int
    raw_value: str
    raw_sha256: str
    decoded_value: str | None
    state: Literal["valid", "warning", "invalid"]
    warning_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParsedAddress:
    display_name: str
    username: str
    domain: str


@dataclass(frozen=True, slots=True)
class ParsedAddressGroup:
    header_name: str
    occurrence: int
    display_name: str | None
    addresses: tuple[ParsedAddress, ...]


@dataclass(frozen=True, slots=True)
class ParsedPart:
    part_id: str
    part_path: str
    parent_part_id: str | None
    media_type: str
    disposition: str | None
    transfer_encoding: str
    content_id: str | None
    filename: str | None
    is_multipart: bool
    child_part_ids: tuple[str, ...]
    decoded_status: Literal[
        "container", "decoded", "preserved", "nested-message"
    ]
    decoded_sha256: str | None
    decoded_size_bytes: int | None
    warning_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecodedAttachment:
    attachment_index: int
    part_id: str
    part_path: str
    media_type: str
    disposition: str | None
    transfer_encoding: str
    content_id: str | None
    filename: str | None
    sha256: str
    size_bytes: int
    data: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class BodySelection:
    status: Literal["available", "unavailable"]
    selection_rule: str
    part_id: str | None
    media_type: str | None
    charset: str | None
    sha256: str | None
    character_count: int
    text: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ParsedEmail:
    schema_version: int
    parser_id: str
    parser_version: str
    parser_protocol_version: int
    message_sha256: str
    message_size_bytes: int
    headers: tuple[ParsedHeader, ...]
    address_groups: tuple[ParsedAddressGroup, ...]
    declared_message_ids: tuple[str, ...]
    references: tuple[str, ...]
    in_reply_to: tuple[str, ...]
    declared_dates: tuple[str, ...]
    parts: tuple[ParsedPart, ...]
    body: BodySelection
    attachments: tuple[DecodedAttachment, ...]
    total_decoded_bytes: int
    warnings: tuple[EmailWarning, ...]
    limits: EmailLimits
    network_used: Literal[False] = False
    active_content_executed: Literal[False] = False
    remote_fetch: Literal[False] = False

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.message_sha256) is None:
            raise ValueError("parsed email digest is invalid")
        if (
            type(self.total_decoded_bytes) is not int
            or self.total_decoded_bytes < 0
            or self.total_decoded_bytes > self.limits.max_decoded_bytes_per_message
        ):
            raise ValueError("parsed email decoded-byte count is invalid")


class EmailContainerAdapter(Protocol):
    config: EmailSourceConfig

    def capability(self, *, limits: EmailLimits | None = None) -> EmailAdapterCapability: ...

    def probe(self) -> SourceProbe: ...

    def snapshot(self, *, limits: EmailLimits | None = None) -> ContainerSnapshot: ...

    def read_exact(
        self,
        candidate: MessageCandidate,
        *,
        limits: EmailLimits | None = None,
    ) -> ObservedMessageBytes: ...

    def recheck(
        self,
        snapshot: ContainerSnapshot,
        *,
        limits: EmailLimits | None = None,
    ) -> ContainerSnapshot: ...


class EmailParser(Protocol):
    parser_id: str
    parser_version: str

    def parse(
        self,
        data: bytes,
        *,
        limits: EmailLimits | None = None,
        deadline: float | None = None,
    ) -> ParsedEmail: ...


def settings_fingerprint(
    limits: EmailLimits,
    *,
    parser_id: str = EMAIL_PARSER_ID,
    parser_version: str = EMAIL_PARSER_VERSION,
) -> str:
    payload = {
        "schema_version": EMAIL_CONTRACT_SCHEMA_VERSION,
        "parser_id": parser_id,
        "parser_version": parser_version,
        "limits": limits.as_record(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def mailbox_format_for_profile(profile: str) -> str:
    try:
        return EMAIL_PROFILE_FORMATS[profile]
    except KeyError as exc:
        raise EmailContractError(
            "email_profile_unsupported", "email Source profile is unsupported"
        ) from exc


capability_report = email_adapter_capability


def ensure_unique_warnings(
    warnings: Sequence[EmailWarning], limits: EmailLimits
) -> tuple[EmailWarning, ...]:
    selected: list[EmailWarning] = []
    seen: set[tuple[Any, ...]] = set()
    for warning in warnings:
        identity = (
            warning.code,
            warning.part_id,
            warning.header_name,
            warning.occurrence,
        )
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(warning)
        if len(selected) > limits.max_warnings_per_message:
            raise EmailContractError(
                "email_mime_limit_exceeded", "email warning limit was exceeded"
            )
    return tuple(selected)


__all__ = [
    "EMAIL_ADAPTER_ID",
    "EMAIL_ADAPTER_PROTOCOL_VERSION",
    "EMAIL_ADAPTER_VERSION",
    "EMAIL_CAPABILITY_STATES",
    "EMAIL_CONTRACT_SCHEMA_VERSION",
    "EMAIL_ERROR_CODES",
    "EMAIL_FORMATS",
    "EMAIL_LIMIT_CEILINGS",
    "EMAIL_PARSER_ID",
    "EMAIL_PARSER_PROTOCOL_VERSION",
    "EMAIL_PARSER_VERSION",
    "EMAIL_PROFILES",
    "EMAIL_PROFILE_FORMATS",
    "EMAIL_PROFILE_QUALIFIED_TARGETS",
    "EMAIL_QUALIFIED_TARGETS",
    "EMAIL_SOURCE_STATES",
    "EMAIL_SUPPORTED_PROFILES",
    "EMAIL_UNSUPPORTED_PROFILES",
    "EMAIL_WARNING_CODES",
    "BodySelection",
    "ContainerSnapshot",
    "DecodedAttachment",
    "EmailAdapterCapability",
    "EmailContainerAdapter",
    "EmailContractError",
    "EmailLimits",
    "EmailParser",
    "EmailSourceConfig",
    "EmailWarning",
    "FilesystemIdentity",
    "MessageCandidate",
    "ObservedMessageBytes",
    "ParsedAddress",
    "ParsedAddressGroup",
    "ParsedEmail",
    "ParsedHeader",
    "ParsedPart",
    "SourceProbe",
    "email_adapter_capability",
    "capability_report",
    "ensure_unique_warnings",
    "qualified_runtime_target",
    "mailbox_format_for_profile",
    "settings_fingerprint",
]
