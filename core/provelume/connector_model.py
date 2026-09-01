from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

CONNECTOR_DEFINITION_SCHEMA_VERSION = 1
CONNECTOR_LIFECYCLE_SCHEMA_VERSION = 2
CONNECTOR_AUTHORIZATION_SCHEMA_VERSION = 3
CONNECTOR_INVENTORY_SCHEMA_VERSION = 2
# Backward-compatible public alias retained for the S01 definition contract.
CONNECTOR_RECORD_SCHEMA_VERSION = CONNECTOR_DEFINITION_SCHEMA_VERSION
CONNECTOR_ADAPTER_PROTOCOL_VERSION = 1
CONNECTOR_CONFORMANCE_PROFILE = "provelume.connector.v1"

CONNECTOR_CAPABILITIES = (
    "conditional_metadata",
    "gmail_read",
    "google_native_export",
    "drive_read",
    "external_secret_authorization",
    "manual_read",
    "oauth2_pkce_authorization",
    "revision_read",
    "scheduled_read",
    "source_selection",
    "transcript_read",
)
CONNECTOR_AUTHORIZATION_MODES = ("none", "external_secret", "oauth2_pkce")
CONNECTOR_DEFINITION_NETWORK_ACCESS = ("none", "explicit_only")
CONNECTOR_NETWORK_MODES = ("disabled", "explicit")
CONNECTOR_SECRET_REFERENCE_KINDS = ("environment", "system_keyring")
CONNECTOR_SOURCE_KINDS = ("drive", "gmail", "transcript", "web")
CONNECTOR_LIFECYCLE_STATES = ("active", "removed")
MAX_CONNECTOR_DATA_CATEGORIES = 32
MAX_CONNECTOR_ORIGINS = 32
MAX_CONNECTOR_SCOPES = 64
MAX_OAUTH_SCOPE_CHARS = 512
MAX_OAUTH_SCOPE_TOTAL_CHARS = 8192

_ADAPTER_KEY = re.compile(r"[a-z][a-z0-9-]{0,47}\Z")
_ADAPTER_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_DEFINITION_ID = re.compile(r"connector_definition_[a-z][a-z0-9-]{0,47}\Z")
_INSTANCE_ID = re.compile(r"connector_instance_[0-9a-f]{32}\Z")
_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_ENVIRONMENT_SECRET = re.compile(r"[A-Z_][A-Z0-9_]{0,127}\Z")
_KEYRING_SECRET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

_DEFINITION_INPUT_KEYS = frozenset(
    {
        "adapter_key",
        "adapter_version",
        "display_name",
        "provider",
        "conformance_profile",
        "adapter_protocol_version",
        "capabilities",
        "authorization_modes",
        "source_kinds",
        "data_categories",
        "multi_instance",
        "network_access",
    }
)
_DEFINITION_RECORD_KEYS = _DEFINITION_INPUT_KEYS | {
    "schema_version",
    "id",
    "created_at",
}
_INSTANCE_RECORD_KEYS_V1 = frozenset(
    {
        "schema_version",
        "id",
        "definition_id",
        "name",
        "provider_identity",
        "account_identity",
        "network_mode",
        "allowed_origins",
        "authorization_mode",
        "scopes",
        "credential_reference",
        "created_at",
        "updated_at",
    }
)
_INSTANCE_RECORD_KEYS_V2 = _INSTANCE_RECORD_KEYS_V1 | {
    "endpoint",
    "enabled",
    "lifecycle_state",
    "removed_at",
    "cursors",
    "health",
}
_INSTANCE_RECORD_KEYS_V3 = _INSTANCE_RECORD_KEYS_V2 | {"authorization"}
_AUTHORIZATION_METADATA_KEYS = frozenset(
    {
        "status",
        "method",
        "authorized_at",
        "revoked_at",
        "redirect_binding",
        "consent",
    }
)
_AUTHORIZATION_STATUSES = frozenset(
    {"not_applicable", "not_authorized", "legacy_reference", "authorized", "revoked"}
)
_CONNECTOR_SOURCE_RECORD_KEYS_V1 = frozenset(
    {
        "schema_version",
        "id",
        "kind",
        "name",
        "created_at",
        "connector_instance_id",
        "source_kind",
        "external_id",
    }
)
_CONNECTOR_SOURCE_RECORD_KEYS_V2 = _CONNECTOR_SOURCE_RECORD_KEYS_V1 | {
    "enabled",
    "lifecycle_state",
    "updated_at",
    "removed_at",
}


class ConnectorError(ValueError):
    pass


class ConnectorNotFoundError(ConnectorError):
    pass


class ConnectorConflictError(ConnectorError):
    pass


class ConnectorIntegrityError(ConnectorError):
    pass


def _normalise_text(value: Any, label: str, *, max_chars: int = 200) -> str:
    if not isinstance(value, str):
        raise ConnectorError(f"{label} must be text")
    selected = unicodedata.normalize("NFC", value.strip())
    if not selected:
        raise ConnectorError(f"{label} is required")
    if len(selected) > max_chars:
        raise ConnectorError(f"{label} exceeds {max_chars} characters")
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in selected):
        raise ConnectorError(f"{label} cannot contain control characters")
    return selected


def _normalise_identifier_list(
    value: Any,
    label: str,
    *,
    allowed: Sequence[str] | None = None,
    required: bool = False,
    max_items: int = 64,
) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ConnectorError(f"{label} must be a sequence")
    if len(value) > max_items:
        raise ConnectorError(f"{label} exceeds the {max_items}-item limit")
    selected: list[str] = []
    for item in value:
        if not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None:
            raise ConnectorError(f"{label} contains an invalid identifier")
        if allowed is not None and item not in allowed:
            raise ConnectorError(f"{label} contains an unsupported value: {item}")
        selected.append(item)
    result = sorted(set(selected))
    if required and not result:
        raise ConnectorError(f"{label} must contain at least one value")
    return result


def normalise_oauth_scopes(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ConnectorError("scopes must be a sequence")
    if len(value) > MAX_CONNECTOR_SCOPES:
        raise ConnectorError(f"scopes exceeds the {MAX_CONNECTOR_SCOPES}-item limit")
    selected: list[str] = []
    total_chars = 0
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item) <= MAX_OAUTH_SCOPE_CHARS:
            raise ConnectorError("scopes contains an invalid OAuth scope token")
        if any(
            not (
                ord(character) == 0x21
                or 0x23 <= ord(character) <= 0x5B
                or 0x5D <= ord(character) <= 0x7E
            )
            for character in item
        ):
            raise ConnectorError("scopes contains an invalid OAuth scope token")
        selected.append(item)
        total_chars += len(item)
    if total_chars > MAX_OAUTH_SCOPE_TOTAL_CHARS:
        raise ConnectorError(
            f"scopes exceeds the {MAX_OAUTH_SCOPE_TOTAL_CHARS}-character total limit"
        )
    return sorted(set(selected))


def connector_definition_id(adapter_key: str) -> str:
    if _ADAPTER_KEY.fullmatch(adapter_key) is None:
        raise ConnectorError("adapter_key is invalid")
    return f"connector_definition_{adapter_key}"


def _valid_hostname(host: str) -> bool:
    try:
        ip_address(host)
        return True
    except ValueError:
        pass
    if len(host) > 253 or host.endswith(".") or re.fullmatch(r"[0-9.]+", host):
        return False
    return all(
        1 <= len(label) <= 63 and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
        for label in host.split(".")
    )


def normalise_connector_origin(value: str) -> str:
    if not isinstance(value, str):
        raise ConnectorError("allowed origin must be text")
    if value != value.strip() or "\\" in value or any(character.isspace() for character in value):
        raise ConnectorError("allowed origin is not a safe HTTP(S) origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
    except (UnicodeError, ValueError) as exc:
        raise ConnectorError("allowed origin is not a safe HTTP(S) origin") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ConnectorError("allowed origin is not a safe HTTP(S) origin")
    try:
        canonical_host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ConnectorError("allowed origin hostname is invalid") from exc
    if not _valid_hostname(canonical_host):
        raise ConnectorError("allowed origin hostname is invalid")
    if port is not None and not 1 <= port <= 65535:
        raise ConnectorError("allowed origin port is invalid")
    if (parsed.scheme, port) in {("http", 80), ("https", 443)}:
        port = None
    display_host = f"[{canonical_host}]" if ":" in canonical_host else canonical_host
    return f"{parsed.scheme}://{display_host}{f':{port}' if port is not None else ''}"


def normalise_secret_reference(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"kind", "name"}:
        raise ConnectorError("credential_reference must contain only external kind and name fields")
    kind = value.get("kind")
    name = value.get("name")
    if kind not in CONNECTOR_SECRET_REFERENCE_KINDS or not isinstance(name, str):
        raise ConnectorError("credential_reference is invalid")
    pattern = _ENVIRONMENT_SECRET if kind == "environment" else _KEYRING_SECRET
    if pattern.fullmatch(name) is None:
        raise ConnectorError("credential_reference name is invalid")
    return {"kind": str(kind), "name": name}


def _normalise_authorization_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ConnectorError(f"{label} must be an offset-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ConnectorError(f"{label} must be an offset-aware timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConnectorError(f"{label} must be an offset-aware timestamp")
    return value


def default_connector_authorization(
    authorization_mode: Any,
    credential_reference: Any,
) -> dict[str, Any]:
    reference = normalise_secret_reference(credential_reference)
    if authorization_mode != "oauth2_pkce":
        return {
            "status": "not_applicable",
            "method": None,
            "authorized_at": None,
            "revoked_at": None,
            "redirect_binding": None,
            "consent": None,
        }
    return {
        "status": "legacy_reference" if reference is not None else "not_authorized",
        "method": "oauth2_pkce",
        "authorized_at": None,
        "revoked_at": None,
        "redirect_binding": None,
        "consent": None,
    }


def normalise_connector_authorization(
    value: Any,
    *,
    authorization_mode: Any,
    credential_reference: Any,
) -> dict[str, Any]:
    reference = normalise_secret_reference(credential_reference)
    if not isinstance(value, Mapping) or set(value) != _AUTHORIZATION_METADATA_KEYS:
        raise ConnectorError("connector authorization metadata has missing or unsupported fields")
    status = value.get("status")
    if status not in _AUTHORIZATION_STATUSES:
        raise ConnectorError("connector authorization status is unsupported")
    selected = {
        "status": str(status),
        "method": value.get("method"),
        "authorized_at": value.get("authorized_at"),
        "revoked_at": value.get("revoked_at"),
        "redirect_binding": value.get("redirect_binding"),
        "consent": value.get("consent"),
    }
    if authorization_mode != "oauth2_pkce":
        expected = default_connector_authorization(authorization_mode, reference)
        if selected != expected:
            raise ConnectorError("non-OAuth connector cannot retain OAuth authorization metadata")
        return expected
    if selected["method"] != "oauth2_pkce":
        raise ConnectorError("OAuth connector authorization method must be oauth2_pkce")
    if status == "not_authorized":
        expected = default_connector_authorization("oauth2_pkce", None)
        if reference is not None or selected != expected:
            raise ConnectorError("not-authorized OAuth metadata cannot retain credentials")
        return expected
    if status == "legacy_reference":
        expected = default_connector_authorization("oauth2_pkce", reference)
        if reference is None or selected != expected:
            raise ConnectorError("legacy OAuth metadata requires only an external reference")
        return expected
    if status == "authorized":
        authorized_at = _normalise_authorization_timestamp(
            selected["authorized_at"],
            "authorized_at",
        )
        if selected["redirect_binding"] != "loopback" or selected["consent"] != "explicit":
            raise ConnectorError(
                "OAuth authorization metadata must record loopback binding and consent"
            )
        if reference is None or selected["revoked_at"] is not None:
            raise ConnectorError("authorized OAuth metadata requires an external reference")
        return {**selected, "authorized_at": authorized_at}
    if status == "revoked":
        if reference is not None:
            raise ConnectorError("revoked OAuth metadata cannot retain credentials")
        revoked_at = _normalise_authorization_timestamp(selected["revoked_at"], "revoked_at")
        authorized_at = selected["authorized_at"]
        if authorized_at is None:
            if selected["redirect_binding"] is not None or selected["consent"] is not None:
                raise ConnectorError("legacy OAuth revocation metadata cannot claim consent")
        else:
            authorized_at = _normalise_authorization_timestamp(authorized_at, "authorized_at")
            if selected["redirect_binding"] != "loopback" or selected["consent"] != "explicit":
                raise ConnectorError(
                    "OAuth authorization metadata must record loopback binding and consent"
                )
        return {
            **selected,
            "authorized_at": authorized_at,
            "revoked_at": revoked_at,
        }
    raise ConnectorError("connector authorization metadata is invalid")


def connector_instance_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != CONNECTOR_AUTHORIZATION_SCHEMA_VERSION:
        return default_connector_authorization(
            value.get("authorization_mode"),
            value.get("credential_reference"),
        )
    return normalise_connector_authorization(
        value.get("authorization"),
        authorization_mode=value.get("authorization_mode"),
        credential_reference=value.get("credential_reference"),
    )


def normalise_connector_definition_manifest(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _DEFINITION_INPUT_KEYS:
        raise ConnectorError("connector definition manifest has missing or unsupported fields")
    adapter_key = value.get("adapter_key")
    adapter_version = value.get("adapter_version")
    provider = value.get("provider")
    if not isinstance(adapter_key, str) or _ADAPTER_KEY.fullmatch(adapter_key) is None:
        raise ConnectorError("adapter_key is invalid")
    if not isinstance(adapter_version, str) or _ADAPTER_VERSION.fullmatch(adapter_version) is None:
        raise ConnectorError("adapter_version must be a three-part numeric version")
    if not isinstance(provider, str) or _IDENTIFIER.fullmatch(provider) is None:
        raise ConnectorError("provider is invalid")
    if value.get("conformance_profile") != CONNECTOR_CONFORMANCE_PROFILE:
        raise ConnectorError("connector conformance profile is unsupported")
    if (
        type(value.get("adapter_protocol_version")) is not int
        or value.get("adapter_protocol_version") != CONNECTOR_ADAPTER_PROTOCOL_VERSION
    ):
        raise ConnectorError("connector adapter protocol version is unsupported")
    if value.get("multi_instance") is not True:
        raise ConnectorError("connector definitions must require multi-instance operation")
    network_access = value.get("network_access")
    if network_access not in CONNECTOR_DEFINITION_NETWORK_ACCESS:
        raise ConnectorError("connector definition network access is unsupported")

    capabilities = _normalise_identifier_list(
        value.get("capabilities"),
        "capabilities",
        allowed=CONNECTOR_CAPABILITIES,
        required=True,
    )
    authorization_modes = _normalise_identifier_list(
        value.get("authorization_modes"),
        "authorization_modes",
        allowed=CONNECTOR_AUTHORIZATION_MODES,
        required=True,
    )
    source_kinds = _normalise_identifier_list(
        value.get("source_kinds"),
        "source_kinds",
        allowed=CONNECTOR_SOURCE_KINDS,
        required=True,
    )
    data_categories = _normalise_identifier_list(
        value.get("data_categories"),
        "data_categories",
        required=True,
        max_items=MAX_CONNECTOR_DATA_CATEGORIES,
    )
    if (
        "external_secret" in authorization_modes
        and "external_secret_authorization" not in capabilities
    ):
        raise ConnectorError("external_secret authorization requires its declared capability")
    if "oauth2_pkce" in authorization_modes and "oauth2_pkce_authorization" not in capabilities:
        raise ConnectorError("oauth2_pkce authorization requires its declared capability")
    if "web" in source_kinds and "manual_read" not in capabilities:
        raise ConnectorError("web Sources require the manual_read capability")

    return {
        "adapter_key": adapter_key,
        "adapter_version": adapter_version,
        "display_name": _normalise_text(value.get("display_name"), "display_name"),
        "provider": provider,
        "conformance_profile": CONNECTOR_CONFORMANCE_PROFILE,
        "adapter_protocol_version": CONNECTOR_ADAPTER_PROTOCOL_VERSION,
        "capabilities": capabilities,
        "authorization_modes": authorization_modes,
        "source_kinds": source_kinds,
        "data_categories": data_categories,
        "multi_instance": True,
        "network_access": network_access,
    }


def normalise_connector_instance_configuration(
    *,
    name: Any,
    provider_identity: Any,
    account_identity: Any,
    network_mode: Any,
    allowed_origins: Any,
    authorization_mode: Any,
    scopes: Any,
    credential_reference: Any,
    endpoint: Any = None,
    derive_endpoint: bool = False,
) -> dict[str, Any]:
    if network_mode not in CONNECTOR_NETWORK_MODES:
        raise ConnectorError("network_mode is unsupported")
    if authorization_mode not in CONNECTOR_AUTHORIZATION_MODES:
        raise ConnectorError("authorization_mode is unsupported")
    if not isinstance(allowed_origins, Sequence) or isinstance(
        allowed_origins, (str, bytes, bytearray)
    ):
        raise ConnectorError("allowed_origins must be a sequence")
    if len(allowed_origins) > MAX_CONNECTOR_ORIGINS:
        raise ConnectorError(f"allowed_origins exceeds the {MAX_CONNECTOR_ORIGINS}-item limit")
    origins = sorted({normalise_connector_origin(item) for item in allowed_origins})
    selected_endpoint = (
        origins[0]
        if derive_endpoint and endpoint is None and origins
        else None
        if endpoint is None
        else normalise_connector_origin(endpoint)
    )
    if selected_endpoint is not None and selected_endpoint not in origins:
        raise ConnectorError("endpoint must be included in allowed_origins")
    if network_mode == "explicit" and not origins:
        raise ConnectorError("explicit network mode requires at least one allowed origin")
    selected_scopes = normalise_oauth_scopes(scopes)
    selected_reference = normalise_secret_reference(credential_reference)
    if authorization_mode == "none" and (selected_scopes or selected_reference is not None):
        raise ConnectorError("authorization mode none cannot declare scopes or credentials")
    if authorization_mode == "external_secret" and selected_reference is None:
        raise ConnectorError("external_secret authorization requires a credential reference")
    selected_account = (
        None
        if account_identity is None
        else _normalise_text(account_identity, "account_identity", max_chars=256)
    )
    return {
        "name": _normalise_text(name, "connector instance name"),
        "provider_identity": _normalise_text(
            provider_identity,
            "provider_identity",
            max_chars=256,
        ),
        "account_identity": selected_account,
        "endpoint": selected_endpoint,
        "network_mode": str(network_mode),
        "allowed_origins": origins,
        "authorization_mode": str(authorization_mode),
        "scopes": selected_scopes,
        "credential_reference": selected_reference,
    }


def connector_instance_lifecycle(value: Mapping[str, Any]) -> dict[str, Any]:
    schema_version = value.get("schema_version")
    if schema_version == CONNECTOR_DEFINITION_SCHEMA_VERSION:
        return {
            "enabled": True,
            "lifecycle_state": "active",
            "removed_at": None,
            "cursors": {},
            "health": {
                "status": "not_checked",
                "checked_at": None,
                "code": "network_not_attempted",
            },
        }
    if schema_version not in {
        CONNECTOR_LIFECYCLE_SCHEMA_VERSION,
        CONNECTOR_AUTHORIZATION_SCHEMA_VERSION,
    }:
        raise ConnectorError("connector instance schema version is unsupported")

    enabled = value.get("enabled")
    lifecycle_state = value.get("lifecycle_state")
    removed_at = value.get("removed_at")
    cursors = value.get("cursors")
    health = value.get("health")
    if type(enabled) is not bool:
        raise ConnectorError("connector instance enabled state must be boolean")
    if lifecycle_state not in CONNECTOR_LIFECYCLE_STATES:
        raise ConnectorError("connector instance lifecycle state is unsupported")
    if lifecycle_state == "removed":
        if enabled or not isinstance(removed_at, str) or not removed_at.strip():
            raise ConnectorError("removed connector instance lifecycle is invalid")
        expected_health = {
            "status": "removed",
            "checked_at": None,
            "code": "connector_removed",
        }
    else:
        if removed_at is not None:
            raise ConnectorError("active connector instance cannot have removed_at")
        expected_health = {
            "status": "not_checked" if enabled else "disabled",
            "checked_at": None,
            "code": "network_not_attempted" if enabled else "connector_disabled",
        }
    if cursors != {}:
        raise ConnectorError("connector cursors must remain empty before refresh is implemented")
    if health != expected_health:
        raise ConnectorError("connector health state is invalid")
    return {
        "enabled": enabled,
        "lifecycle_state": str(lifecycle_state),
        "removed_at": removed_at,
        "cursors": {},
        "health": expected_health,
    }


def connector_source_lifecycle(value: Mapping[str, Any]) -> dict[str, Any]:
    schema_version = value.get("schema_version")
    if schema_version == CONNECTOR_DEFINITION_SCHEMA_VERSION:
        return {
            "enabled": True,
            "lifecycle_state": "active",
            "updated_at": value.get("created_at"),
            "removed_at": None,
        }
    if schema_version != CONNECTOR_LIFECYCLE_SCHEMA_VERSION:
        raise ConnectorError("connector Source schema version is unsupported")
    enabled = value.get("enabled")
    lifecycle_state = value.get("lifecycle_state")
    updated_at = value.get("updated_at")
    removed_at = value.get("removed_at")
    if type(enabled) is not bool:
        raise ConnectorError("connector Source enabled state must be boolean")
    if lifecycle_state not in CONNECTOR_LIFECYCLE_STATES:
        raise ConnectorError("connector Source lifecycle state is unsupported")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ConnectorError("connector Source updated_at is invalid")
    if lifecycle_state == "removed":
        if enabled or not isinstance(removed_at, str) or not removed_at.strip():
            raise ConnectorError("removed connector Source lifecycle is invalid")
    elif removed_at is not None:
        raise ConnectorError("active connector Source cannot have removed_at")
    return {
        "enabled": enabled,
        "lifecycle_state": str(lifecycle_state),
        "updated_at": updated_at,
        "removed_at": removed_at,
    }


def normalise_connector_source_configuration(
    *,
    name: Any,
    source_kind: Any,
    external_id: Any,
) -> dict[str, str]:
    if source_kind not in CONNECTOR_SOURCE_KINDS:
        raise ConnectorError("source_kind is unsupported")
    return {
        "name": _normalise_text(name, "Source name"),
        "source_kind": str(source_kind),
        "external_id": _normalise_text(external_id, "external_id", max_chars=512),
    }


def canonical_connector_errors(
    definitions: Mapping[str, Mapping[str, Any]],
    instances: Mapping[str, Mapping[str, Any]],
    sources: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    valid_definitions: dict[str, Mapping[str, Any]] = {}
    valid_instances: dict[str, Mapping[str, Any]] = {}

    for record_id, value in definitions.items():
        path = f"knowledge/connector-definitions/{record_id}.json"
        try:
            manifest = normalise_connector_definition_manifest(
                {key: value.get(key) for key in _DEFINITION_INPUT_KEYS}
            )
            valid = (
                set(value) == _DEFINITION_RECORD_KEYS
                and type(value.get("schema_version")) is int
                and value.get("schema_version") == CONNECTOR_RECORD_SCHEMA_VERSION
                and _DEFINITION_ID.fullmatch(record_id) is not None
                and value.get("id") == record_id
                and record_id == connector_definition_id(manifest["adapter_key"])
                and all(value.get(key) == selected for key, selected in manifest.items())
                and isinstance(value.get("created_at"), str)
                and bool(str(value["created_at"]).strip())
            )
        except ConnectorError:
            valid = False
        if not valid:
            errors.append(
                (
                    "connector_definition_invalid",
                    "Connector definition identity or conformance manifest is invalid",
                    path,
                )
            )
        else:
            valid_definitions[record_id] = value

    for record_id, value in instances.items():
        path = f"knowledge/connector-instances/{record_id}.json"
        definition_id = value.get("definition_id")
        try:
            config = normalise_connector_instance_configuration(
                name=value.get("name"),
                provider_identity=value.get("provider_identity"),
                account_identity=value.get("account_identity"),
                network_mode=value.get("network_mode"),
                allowed_origins=value.get("allowed_origins"),
                authorization_mode=value.get("authorization_mode"),
                scopes=value.get("scopes"),
                credential_reference=value.get("credential_reference"),
                endpoint=value.get("endpoint"),
                derive_endpoint=(
                    value.get("schema_version") == CONNECTOR_DEFINITION_SCHEMA_VERSION
                ),
            )
            lifecycle = connector_instance_lifecycle(value)
            authorization = connector_instance_authorization(value)
            schema_version = value.get("schema_version")
            expected_keys = (
                _INSTANCE_RECORD_KEYS_V1
                if schema_version == CONNECTOR_DEFINITION_SCHEMA_VERSION
                else _INSTANCE_RECORD_KEYS_V2
                if schema_version == CONNECTOR_LIFECYCLE_SCHEMA_VERSION
                else _INSTANCE_RECORD_KEYS_V3
            )
            comparable_config = (
                {key: selected for key, selected in config.items() if key != "endpoint"}
                if schema_version == CONNECTOR_DEFINITION_SCHEMA_VERSION
                else config
            )
            valid = (
                set(value) == expected_keys
                and type(value.get("schema_version")) is int
                and schema_version
                in {
                    CONNECTOR_DEFINITION_SCHEMA_VERSION,
                    CONNECTOR_LIFECYCLE_SCHEMA_VERSION,
                    CONNECTOR_AUTHORIZATION_SCHEMA_VERSION,
                }
                and _INSTANCE_ID.fullmatch(record_id) is not None
                and value.get("id") == record_id
                and isinstance(definition_id, str)
                and all(
                    value.get(key) == selected
                    for key, selected in comparable_config.items()
                )
                and (
                    schema_version == CONNECTOR_DEFINITION_SCHEMA_VERSION
                    or all(value.get(key) == selected for key, selected in lifecycle.items())
                )
                and (
                    schema_version != CONNECTOR_AUTHORIZATION_SCHEMA_VERSION
                    or value.get("authorization") == authorization
                )
                and all(
                    isinstance(value.get(field), str) and bool(str(value[field]).strip())
                    for field in ("created_at", "updated_at")
                )
            )
        except ConnectorError:
            valid = False
        if not valid:
            errors.append(
                (
                    "connector_instance_invalid",
                    "Connector instance identity or local policy is invalid",
                    path,
                )
            )
            continue
        definition = valid_definitions.get(str(definition_id))
        if definition is None:
            errors.append(
                (
                    "connector_definition_missing",
                    "Connector instance references a missing definition",
                    path,
                )
            )
            continue
        if value.get("authorization_mode") not in definition["authorization_modes"]:
            errors.append(
                (
                    "connector_authorization_unsupported",
                    "Connector instance authorization is not declared by its definition",
                    path,
                )
            )
            continue
        if (
            value.get("network_mode") == "explicit"
            and "manual_read" not in definition["capabilities"]
        ):
            errors.append(
                (
                    "connector_network_capability_missing",
                    "Explicit network mode requires a declared read capability",
                    path,
                )
            )
            continue
        valid_instances[record_id] = value

    seen_sources: set[tuple[str, str, str]] = set()
    for record_id, value in sources.items():
        if value.get("kind") != "connector":
            continue
        path = f"knowledge/sources/{record_id}.json"
        connector_instance_id = value.get("connector_instance_id")
        try:
            config = normalise_connector_source_configuration(
                name=value.get("name"),
                source_kind=value.get("source_kind"),
                external_id=value.get("external_id"),
            )
            lifecycle = connector_source_lifecycle(value)
            schema_version = value.get("schema_version")
            expected_keys = (
                _CONNECTOR_SOURCE_RECORD_KEYS_V1
                if schema_version == CONNECTOR_DEFINITION_SCHEMA_VERSION
                else _CONNECTOR_SOURCE_RECORD_KEYS_V2
            )
            valid = (
                set(value) == expected_keys
                and type(value.get("schema_version")) is int
                and schema_version
                in {
                    CONNECTOR_DEFINITION_SCHEMA_VERSION,
                    CONNECTOR_LIFECYCLE_SCHEMA_VERSION,
                }
                and _SOURCE_ID.fullmatch(record_id) is not None
                and value.get("id") == record_id
                and isinstance(connector_instance_id, str)
                and all(value.get(key) == selected for key, selected in config.items())
                and (
                    schema_version == CONNECTOR_DEFINITION_SCHEMA_VERSION
                    or all(value.get(key) == selected for key, selected in lifecycle.items())
                )
                and isinstance(value.get("created_at"), str)
                and bool(str(value["created_at"]).strip())
            )
        except ConnectorError:
            valid = False
        if not valid:
            errors.append(
                (
                    "connector_source_invalid",
                    "Connector Source identity or configuration is invalid",
                    path,
                )
            )
            continue
        instance = valid_instances.get(str(connector_instance_id))
        if instance is None:
            errors.append(
                (
                    "connector_source_instance_missing",
                    "Connector Source references a missing connector instance",
                    path,
                )
            )
            continue
        definition = valid_definitions[str(instance["definition_id"])]
        if value.get("source_kind") not in definition["source_kinds"]:
            errors.append(
                (
                    "connector_source_kind_unsupported",
                    "Connector Source kind is not declared by its definition",
                    path,
                )
            )
        if (
            connector_instance_lifecycle(instance)["lifecycle_state"] == "removed"
            and lifecycle["lifecycle_state"] != "removed"
        ):
            errors.append(
                (
                    "connector_source_parent_removed",
                    "Active connector Source references a removed connector instance",
                    path,
                )
            )
        identity = (
            str(connector_instance_id),
            str(value.get("source_kind")),
            str(value.get("external_id")),
        )
        if identity in seen_sources:
            errors.append(
                (
                    "connector_source_duplicate",
                    "Connector Source external identity is duplicated within one instance",
                    path,
                )
            )
        seen_sources.add(identity)

    return errors
