from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from .connector_model import normalise_secret_reference

GOOGLE_CONTRACT_SCHEMA_VERSION = 1
GOOGLE_ADAPTER_ID = "provelume.google"
GOOGLE_ADAPTER_VERSION = "1.0.0"
GOOGLE_ADAPTER_PROTOCOL_VERSION = 1
GOOGLE_CONFORMANCE_PROFILE = "provelume.google.readonly.v1"
GOOGLE_DEFINITION_KEY = "google-readonly"
GOOGLE_DEFINITION_ID = f"connector_definition_{GOOGLE_DEFINITION_KEY}"

GOOGLE_CAPABILITIES = ("drive", "gmail")
GOOGLE_CAPABILITY_SCOPES = {
    "gmail": ("https://www.googleapis.com/auth/gmail.readonly",),
    "drive": ("https://www.googleapis.com/auth/drive.readonly",),
}
GOOGLE_ALLOWED_ORIGINS = (
    "https://accounts.google.com",
    "https://gmail.googleapis.com",
    "https://oauth2.googleapis.com",
    "https://www.googleapis.com",
)
GOOGLE_SELECTION_KINDS = {
    "gmail": ("label", "mailbox"),
    "drive": ("file", "folder"),
}
GOOGLE_CAPABILITY_STATES = ("disabled", "enabled")
GOOGLE_AUTHORIZATION_STATES = (
    "not_authorized",
    "authorized",
    "revoked",
    "reauthorization_required",
)
GOOGLE_SOURCE_STATES = ("disabled", "enabled", "paused")
GOOGLE_SOURCE_LIFECYCLE_STATES = ("active", "removed")
GOOGLE_JOB_KIND = "google.intake"

GOOGLE_ERROR_CODES = (
    "google_adapter_unavailable",
    "google_authorization_expired",
    "google_authorization_required",
    "google_backfill_limit_exceeded",
    "google_cancelled",
    "google_capability_disabled",
    "google_cursor_invalidated",
    "google_input_changed",
    "google_internal_error",
    "google_network_disabled",
    "google_payload_invalid",
    "google_payload_limit_exceeded",
    "google_rate_limited",
    "google_remote_mutation",
    "google_retryable_failure",
    "google_source_disabled",
    "google_source_paused",
    "google_source_removed",
)

GOOGLE_NATIVE_EXPORTS = {
    "application/vnd.google-apps.document": "application/pdf",
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    "application/vnd.google-apps.presentation": "application/pdf",
}

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_INSTANCE_ID = re.compile(r"connector_instance_[0-9a-f]{32}\Z")
_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")
_JOB_ID = re.compile(r"job_[0-9a-f]{32}\Z")
_SAFE_MEDIA_TYPE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}\Z"
)


class GoogleContractError(ValueError):
    def __init__(self, code: str, message: str):
        if code not in GOOGLE_ERROR_CODES:
            raise ValueError("Google error code is outside the closed registry")
        self.code = code
        super().__init__(message)


class GoogleAdapterError(GoogleContractError):
    pass


class GoogleRateLimitError(GoogleAdapterError):
    def __init__(self, *, retry_after_seconds: int | None = None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("google_rate_limited", "Google adapter rate limit was reached")


class GoogleAuthorizationError(GoogleAdapterError):
    def __init__(self, *, expired: bool = False):
        super().__init__(
            "google_authorization_expired" if expired else "google_authorization_required",
            "Google capability authorization is unavailable",
        )


class GoogleCursorInvalidated(GoogleAdapterError):
    def __init__(self):
        super().__init__(
            "google_cursor_invalidated",
            "Google Source cursor no longer matches the remote observation",
        )


def _text(value: Any, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise GoogleContractError("google_payload_invalid", f"{label} must be text")
    selected = unicodedata.normalize("NFC", value.strip())
    if not selected or len(selected) > maximum:
        raise GoogleContractError("google_payload_invalid", f"{label} is invalid")
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in selected):
        raise GoogleContractError(
            "google_payload_invalid", f"{label} contains unsupported characters"
        )
    return selected


def _instant(value: Any, label: str) -> str:
    from datetime import datetime

    selected = _text(value, label, maximum=80)
    try:
        parsed = datetime.fromisoformat(selected.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoogleContractError(
            "google_payload_invalid", f"{label} must be an offset-aware timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoogleContractError(
            "google_payload_invalid", f"{label} must be an offset-aware timestamp"
        )
    return selected


def opaque_reference(value: str, *, namespace: str) -> str:
    selected = _text(value, "provider reference", maximum=2048)
    return hashlib.sha256(f"{namespace}\0{selected}".encode()).hexdigest()


def normalise_capability(value: Any) -> str:
    if value not in GOOGLE_CAPABILITIES:
        raise GoogleContractError("google_payload_invalid", "Google capability is unsupported")
    return str(value)


def normalise_media_type(value: Any, label: str = "media type") -> str:
    if not isinstance(value, str):
        raise GoogleContractError("google_payload_invalid", f"{label} is invalid")
    selected = value.strip().casefold()
    if _SAFE_MEDIA_TYPE.fullmatch(selected) is None:
        raise GoogleContractError("google_payload_invalid", f"{label} is invalid")
    return selected


def normalise_selectors(
    capability: str,
    selection_kind: Any,
    selectors: Any,
) -> tuple[str, tuple[str, ...]]:
    selected_capability = normalise_capability(capability)
    if selection_kind not in GOOGLE_SELECTION_KINDS[selected_capability]:
        raise GoogleContractError(
            "google_payload_invalid", "Google Source selection kind is unsupported"
        )
    if not isinstance(selectors, Sequence) or isinstance(selectors, (str, bytes, bytearray)):
        raise GoogleContractError(
            "google_payload_invalid", "Google Source selectors must be a sequence"
        )
    if not 1 <= len(selectors) <= 100:
        raise GoogleContractError(
            "google_payload_invalid", "Google Source selector count is invalid"
        )
    selected = tuple(sorted({_text(item, "Google Source selector") for item in selectors}))
    if selected_capability == "gmail" and selection_kind == "mailbox" and selected != ("me",):
        raise GoogleContractError(
            "google_payload_invalid",
            "Gmail mailbox selection is limited to the authorized identity",
        )
    return str(selection_kind), selected


@dataclass(frozen=True, slots=True)
class GoogleLimits:
    max_pages_per_run: int = 32
    max_items_per_page: int = 100
    max_items_per_run: int = 500
    max_item_bytes: int = 32 * 1024 * 1024
    max_total_bytes_per_run: int = 256 * 1024 * 1024
    max_json_bytes: int = 4 * 1024 * 1024
    max_error_count: int = 100
    max_page_fingerprints: int = 256
    request_timeout_seconds: int = 30

    def __post_init__(self) -> None:
        ceilings = {
            "max_pages_per_run": 128,
            "max_items_per_page": 1000,
            "max_items_per_run": 10_000,
            "max_item_bytes": 256 * 1024 * 1024,
            "max_total_bytes_per_run": 4 * 1024 * 1024 * 1024,
            "max_json_bytes": 32 * 1024 * 1024,
            "max_error_count": 1000,
            "max_page_fingerprints": 1024,
            "request_timeout_seconds": 300,
        }
        for name, maximum in ceilings.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise GoogleContractError(
                    "google_payload_limit_exceeded", f"{name} is outside the closed limit"
                )
        if self.max_items_per_page > self.max_items_per_run:
            raise GoogleContractError(
                "google_payload_limit_exceeded",
                "page item limit cannot exceed the run item limit",
            )
        if self.max_item_bytes > self.max_total_bytes_per_run:
            raise GoogleContractError(
                "google_payload_limit_exceeded",
                "item byte limit cannot exceed the run byte limit",
            )

    def as_record(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> GoogleLimits:
        if value is None:
            return cls()
        if not isinstance(value, Mapping) or set(value) != set(cls().as_record()):
            raise GoogleContractError(
                "google_payload_invalid", "Google limits have missing or unsupported fields"
            )
        return cls(**{key: value[key] for key in cls().as_record()})


@dataclass(frozen=True, slots=True)
class GoogleItem:
    capability: Literal["gmail", "drive"]
    provider_item_id: str
    provider_revision_id: str
    payload: bytes = field(repr=False)
    media_type: str = "application/octet-stream"
    provider_thread_id: str | None = None
    provider_labels: tuple[str, ...] = ()
    provider_observed_at: str | None = None
    source_format: str | None = None
    export_format: str | None = None
    google_native: bool = False

    def __post_init__(self) -> None:
        normalise_capability(self.capability)
        _text(self.provider_item_id, "provider item reference", maximum=2048)
        _text(self.provider_revision_id, "provider revision reference", maximum=2048)
        if not isinstance(self.payload, bytes) or not self.payload:
            raise GoogleContractError(
                "google_payload_invalid", "Google item payload must contain bytes"
            )
        normalise_media_type(self.media_type)
        if self.provider_thread_id is not None:
            _text(self.provider_thread_id, "provider thread reference", maximum=2048)
        if len(self.provider_labels) > 100:
            raise GoogleContractError(
                "google_payload_limit_exceeded", "Gmail label observation limit was exceeded"
            )
        for label in self.provider_labels:
            _text(label, "provider label reference", maximum=512)
        if self.provider_observed_at is not None:
            _instant(self.provider_observed_at, "provider observation time")
        if self.google_native:
            source_format = normalise_media_type(self.source_format, "source format")
            export_format = normalise_media_type(self.export_format, "export format")
            if GOOGLE_NATIVE_EXPORTS.get(source_format) != export_format:
                raise GoogleContractError(
                    "google_payload_invalid", "Google-native export format is unsupported"
                )
        elif self.export_format is not None:
            raise GoogleContractError(
                "google_payload_invalid", "binary Drive items cannot claim an export format"
            )

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    def identity_record(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "provider_item_ref_sha256": opaque_reference(
                self.provider_item_id, namespace=f"google-{self.capability}-item"
            ),
            "provider_revision_ref_sha256": opaque_reference(
                self.provider_revision_id, namespace=f"google-{self.capability}-revision"
            ),
            "payload_sha256": self.payload_sha256,
            "size_bytes": len(self.payload),
            "media_type": normalise_media_type(self.media_type),
            "provider_thread_ref_sha256": (
                opaque_reference(self.provider_thread_id, namespace="google-gmail-thread")
                if self.provider_thread_id is not None
                else None
            ),
            "provider_label_ref_sha256": sorted(
                opaque_reference(label, namespace="google-gmail-label")
                for label in self.provider_labels
            ),
            "provider_observed_at": self.provider_observed_at,
            "source_format": self.source_format,
            "export_format": self.export_format,
            "google_native": self.google_native,
        }


@dataclass(frozen=True, slots=True)
class GooglePage:
    capability: Literal["gmail", "drive"]
    items: tuple[GoogleItem, ...]
    next_cursor: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        normalise_capability(self.capability)
        if any(item.capability != self.capability for item in self.items):
            raise GoogleContractError(
                "google_payload_invalid", "Google page mixes capability item types"
            )
        if self.next_cursor is not None:
            _text(self.next_cursor, "provider page cursor", maximum=4096)

    def fingerprint(self) -> str:
        payload = [item.identity_record() for item in self.items]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


class GoogleProviderAdapter(Protocol):
    adapter_id: str
    adapter_version: str
    adapter_protocol_version: int

    def fetch_page(
        self,
        *,
        instance: Mapping[str, Any],
        capability: Mapping[str, Any],
        source: Mapping[str, Any],
        cursor: str | None,
        limits: GoogleLimits,
    ) -> GooglePage: ...


def google_definition_manifest() -> dict[str, Any]:
    return {
        "adapter_key": GOOGLE_DEFINITION_KEY,
        "adapter_version": GOOGLE_ADAPTER_VERSION,
        "display_name": "Google read-only adapter",
        "provider": "google",
        "conformance_profile": "provelume.connector.v1",
        "adapter_protocol_version": 1,
        "capabilities": [
            "drive_read",
            "gmail_read",
            "google_native_export",
            "manual_read",
            "revision_read",
            "scheduled_read",
            "source_selection",
        ],
        "authorization_modes": ["none"],
        "source_kinds": ["drive", "gmail"],
        "data_categories": [
            "drive.file",
            "drive.metadata",
            "email.attachment",
            "email.message",
            "email.metadata",
        ],
        "multi_instance": True,
        "network_access": "explicit_only",
    }


def capability_fingerprint(value: Mapping[str, Any]) -> str:
    safe = {
        key: item
        for key, item in value.items()
        if key not in {"credential_reference", "updated_at", "health"}
    }
    reference = normalise_secret_reference(value.get("credential_reference"))
    safe["credential_reference_present"] = reference is not None
    return hashlib.sha256(
        json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def source_fingerprint(value: Mapping[str, Any]) -> str:
    safe = {key: item for key, item in value.items() if key not in {"updated_at", "cursor"}}
    return hashlib.sha256(
        json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def public_credential_reference(value: Any) -> dict[str, Any]:
    reference = normalise_secret_reference(value)
    return {
        "present": reference is not None,
        "kind": reference["kind"] if reference is not None else None,
    }


def require_identifier(value: Any, kind: str) -> str:
    pattern = {
        "instance": _INSTANCE_ID,
        "source": _SOURCE_ID,
        "job": _JOB_ID,
        "sha256": _SHA256,
    }[kind]
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise GoogleContractError("google_payload_invalid", f"Google {kind} identity is invalid")
    return value


__all__ = [
    "GOOGLE_ADAPTER_ID",
    "GOOGLE_ADAPTER_PROTOCOL_VERSION",
    "GOOGLE_ADAPTER_VERSION",
    "GOOGLE_ALLOWED_ORIGINS",
    "GOOGLE_AUTHORIZATION_STATES",
    "GOOGLE_CAPABILITIES",
    "GOOGLE_CAPABILITY_SCOPES",
    "GOOGLE_CAPABILITY_STATES",
    "GOOGLE_CONFORMANCE_PROFILE",
    "GOOGLE_DEFINITION_ID",
    "GOOGLE_ERROR_CODES",
    "GOOGLE_JOB_KIND",
    "GOOGLE_NATIVE_EXPORTS",
    "GOOGLE_SELECTION_KINDS",
    "GOOGLE_SOURCE_LIFECYCLE_STATES",
    "GOOGLE_SOURCE_STATES",
    "GoogleAdapterError",
    "GoogleAuthorizationError",
    "GoogleContractError",
    "GoogleCursorInvalidated",
    "GoogleItem",
    "GoogleLimits",
    "GooglePage",
    "GoogleProviderAdapter",
    "GoogleRateLimitError",
    "capability_fingerprint",
    "google_definition_manifest",
    "normalise_capability",
    "normalise_media_type",
    "normalise_selectors",
    "opaque_reference",
    "public_credential_reference",
    "require_identifier",
    "source_fingerprint",
]
