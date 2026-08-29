from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

CONNECTOR_RECORD_SCHEMA_VERSION = 1
CONNECTOR_ADAPTER_PROTOCOL_VERSION = 1
CONNECTOR_CONFORMANCE_PROFILE = "provelume.connector.v1"

CONNECTOR_CAPABILITIES = (
    "conditional_metadata",
    "external_secret_authorization",
    "manual_read",
    "oauth2_pkce_authorization",
    "source_selection",
)
CONNECTOR_AUTHORIZATION_MODES = ("none", "external_secret", "oauth2_pkce")
CONNECTOR_NETWORK_MODES = ("disabled", "explicit")
CONNECTOR_SECRET_REFERENCE_KINDS = ("environment", "system_keyring")
CONNECTOR_SOURCE_KINDS = ("web",)
MAX_CONNECTOR_DATA_CATEGORIES = 32
MAX_CONNECTOR_ORIGINS = 32
MAX_CONNECTOR_SCOPES = 64

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
_INSTANCE_RECORD_KEYS = frozenset(
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
_CONNECTOR_SOURCE_RECORD_KEYS = frozenset(
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
    if value.get("network_access") != "explicit_only":
        raise ConnectorError("connector network access must be explicit_only")

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
        "network_access": "explicit_only",
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
    if network_mode == "explicit" and not origins:
        raise ConnectorError("explicit network mode requires at least one allowed origin")
    selected_scopes = _normalise_identifier_list(
        scopes,
        "scopes",
        max_items=MAX_CONNECTOR_SCOPES,
    )
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
        "network_mode": str(network_mode),
        "allowed_origins": origins,
        "authorization_mode": str(authorization_mode),
        "scopes": selected_scopes,
        "credential_reference": selected_reference,
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
            )
            valid = (
                set(value) == _INSTANCE_RECORD_KEYS
                and type(value.get("schema_version")) is int
                and value.get("schema_version") == CONNECTOR_RECORD_SCHEMA_VERSION
                and _INSTANCE_ID.fullmatch(record_id) is not None
                and value.get("id") == record_id
                and isinstance(definition_id, str)
                and all(value.get(key) == selected for key, selected in config.items())
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
            valid = (
                set(value) == _CONNECTOR_SOURCE_RECORD_KEYS
                and type(value.get("schema_version")) is int
                and value.get("schema_version") == CONNECTOR_RECORD_SCHEMA_VERSION
                and _SOURCE_ID.fullmatch(record_id) is not None
                and value.get("id") == record_id
                and isinstance(connector_instance_id, str)
                and all(value.get(key) == selected for key, selected in config.items())
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
