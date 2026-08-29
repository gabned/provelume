from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

NETWORK_STATUS_SCHEMA_VERSION = 1
_CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _boolean(value: Any, *, default: bool) -> tuple[bool, bool]:
    if value is None:
        return default, True
    if isinstance(value, bool):
        return value, True
    return default, False


def _valid_hostname(host: str) -> bool:
    try:
        ip_address(host)
        return True
    except ValueError:
        pass

    if not host.isascii() or len(host) > 253 or host.endswith("."):
        return False
    if re.fullmatch(r"[0-9.]+", host):
        return False
    labels = host.split(".")
    return all(
        1 <= len(label) <= 63
        and re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?", label)
        for label in labels
    )


def _endpoint_origin(value: Any) -> tuple[str | None, bool]:
    if value in (None, ""):
        return None, True
    if not isinstance(value, str):
        return None, False
    if value != value.strip() or "\\" in value or any(character.isspace() for character in value):
        return None, False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None, False
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or not _valid_hostname(parsed.hostname)
    ):
        return None, False
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}{f':{port}' if port is not None else ''}", True


def _data_categories(value: Any) -> tuple[list[str], bool]:
    if value is None:
        return [], True
    if not isinstance(value, list):
        return [], False
    categories: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _CATEGORY_PATTERN.fullmatch(item):
            return [], False
        if item not in categories:
            categories.append(item)
    return categories, True


def _component(
    *,
    component_id: str,
    category: str,
    component_type: str,
    enabled: bool,
    network_capability: str,
    declaration_state: str,
    endpoint: str | None,
    data_categories: list[str],
) -> dict[str, Any]:
    return {
        "id": component_id,
        "category": category,
        "type": component_type,
        "enabled": enabled,
        "network_capability": network_capability,
        "declaration_state": declaration_state,
        "endpoint": endpoint,
        "data_categories": data_categories,
        "observed_activity": "not_instrumented",
    }


def declared_network_status(
    config: Mapping[str, Any],
    *,
    connector_definitions: Sequence[Mapping[str, Any]] = (),
    connector_instances: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Describe configured network capability without performing network activity."""

    components: list[dict[str, Any]] = []
    conflicts: list[dict[str, str]] = []

    def finding(code: str, component_id: str, message: str) -> None:
        conflicts.append({"code": code, "component_id": component_id, "message": message})

    raw_network = config.get("network")
    if raw_network is not None and not isinstance(raw_network, Mapping):
        finding(
            "invalid_component_registry",
            "registry.network",
            "The configured network policy registry is not a mapping.",
        )
        raw_network = {}
    network = _mapping(raw_network)
    external_access, external_access_valid = _boolean(
        network.get("external_access"), default=False
    )
    if not external_access_valid:
        finding(
            "invalid_external_access_flag",
            "policy.external_access",
            "network.external_access must be a boolean; the effective policy is fail-closed.",
        )

    update_enabled, update_enabled_valid = _boolean(
        network.get("update_checks"), default=False
    )
    update_endpoint, update_endpoint_valid = _endpoint_origin(
        network.get("update_endpoint")
    )
    update_categories, update_categories_valid = _data_categories(
        network.get("update_data_categories")
    )
    update_id = "builtin.update_checks"
    if not update_enabled_valid:
        finding(
            "invalid_enabled_flag",
            update_id,
            "network.update_checks must be a boolean and is treated as disabled.",
        )
    if not update_endpoint_valid:
        finding(
            "invalid_external_endpoint",
            update_id,
            "The configured update endpoint is not a safe HTTP(S) origin.",
        )
    if not update_categories_valid:
        finding(
            "invalid_data_categories",
            update_id,
            "Update data categories must use the declared identifier format.",
        )
    if update_enabled and update_endpoint is None:
        finding(
            "missing_external_endpoint",
            update_id,
            "Update checks are enabled without a declared external endpoint.",
        )
    components.append(
        _component(
            component_id=update_id,
            category="builtin",
            component_type="update_checks",
            enabled=update_enabled,
            network_capability="external",
            declaration_state="declared",
            endpoint=update_endpoint,
            data_categories=update_categories,
        )
    )

    sources = config.get("sources")
    if sources is not None and not isinstance(sources, Mapping):
        finding(
            "invalid_component_registry",
            "registry.sources",
            "The configured Sources registry is not a mapping.",
        )
        sources = {}
    for source_id, raw_item in sorted(_mapping(sources).items(), key=lambda item: str(item[0])):
        component_id = f"source.{source_id}"
        item = _mapping(raw_item)
        source_type = item.get("kind") if isinstance(item.get("kind"), str) else "unknown"
        enabled, enabled_valid = _boolean(item.get("enabled"), default=True)
        if not enabled_valid:
            finding(
                "invalid_enabled_flag",
                component_id,
                "The Source enabled flag must be a boolean and is treated as enabled.",
            )
        if source_type == "filesystem" and isinstance(raw_item, Mapping):
            endpoint = None
            categories: list[str] = []
            if item.get("endpoint") not in (None, "") or item.get("data_categories") is not None:
                finding(
                    "local_component_external_declaration",
                    component_id,
                    "A filesystem Source cannot declare an external endpoint or data categories.",
                )
            components.append(
                _component(
                    component_id=component_id,
                    category="source",
                    component_type="filesystem",
                    enabled=enabled,
                    network_capability="local_only",
                    declaration_state="declared",
                    endpoint=endpoint,
                    data_categories=categories,
                )
            )
            continue

        endpoint, endpoint_valid = _endpoint_origin(item.get("endpoint"))
        categories, categories_valid = _data_categories(item.get("data_categories"))
        if not endpoint_valid:
            finding(
                "invalid_external_endpoint",
                component_id,
                "The Source endpoint is not a safe HTTP(S) origin.",
            )
        if not categories_valid:
            finding(
                "invalid_data_categories",
                component_id,
                "Source data categories must use the declared identifier format.",
            )
        finding(
            "undeclared_component_type",
            component_id,
            f"Source type {source_type!r} has no registered network-capability declaration.",
        )
        components.append(
            _component(
                component_id=component_id,
                category="source",
                component_type=source_type,
                enabled=enabled,
                network_capability="unknown",
                declaration_state="undeclared",
                endpoint=endpoint,
                data_categories=categories,
            )
        )

    for category in ("connectors", "providers"):
        registry = config.get(category)
        if registry is not None and not isinstance(registry, Mapping):
            finding(
                "invalid_component_registry",
                f"registry.{category}",
                f"The configured {category} registry is not a mapping.",
            )
            registry = {}
        for item_id, raw_item in sorted(
            _mapping(registry).items(), key=lambda item: str(item[0])
        ):
            component_id = f"{category[:-1]}.{item_id}"
            item = _mapping(raw_item)
            component_type = (
                item.get("kind") if isinstance(item.get("kind"), str) else "unknown"
            )
            enabled, enabled_valid = _boolean(item.get("enabled"), default=False)
            endpoint, endpoint_valid = _endpoint_origin(item.get("endpoint"))
            categories, categories_valid = _data_categories(item.get("data_categories"))
            if not enabled_valid:
                finding(
                    "invalid_enabled_flag",
                    component_id,
                    "The component enabled flag must be a boolean and is treated as disabled.",
                )
            if not endpoint_valid:
                finding(
                    "invalid_external_endpoint",
                    component_id,
                    "The component endpoint is not a safe HTTP(S) origin.",
                )
            if not categories_valid:
                finding(
                    "invalid_data_categories",
                    component_id,
                    "Component data categories must use the declared identifier format.",
                )
            finding(
                "undeclared_component_type",
                component_id,
                f"{category[:-1].title()} type {component_type!r} is not registered.",
            )
            components.append(
                _component(
                    component_id=component_id,
                    category=category[:-1],
                    component_type=component_type,
                    enabled=enabled,
                    network_capability="unknown",
                    declaration_state="undeclared",
                    endpoint=endpoint,
                    data_categories=categories,
                )
            )

    definitions = {
        str(item.get("id")): item
        for item in connector_definitions
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    for raw_instance in sorted(
        connector_instances,
        key=lambda item: str(item.get("id", "")),
    ):
        instance = _mapping(raw_instance)
        instance_id = instance.get("id")
        component_id = (
            f"connector.{instance_id}"
            if isinstance(instance_id, str) and instance_id
            else "connector.invalid"
        )
        definition = definitions.get(str(instance.get("definition_id")))
        component_type = (
            str(definition.get("adapter_key"))
            if isinstance(definition, Mapping)
            and isinstance(definition.get("adapter_key"), str)
            else "unknown"
        )
        network_mode = instance.get("network_mode")
        configured_enabled, configured_enabled_valid = _boolean(
            instance.get("enabled"),
            default=True,
        )
        lifecycle_state = instance.get("lifecycle_state", "active")
        if not configured_enabled_valid:
            finding(
                "invalid_enabled_flag",
                component_id,
                "Connector enabled state is invalid and is treated as enabled.",
            )
        if lifecycle_state not in {"active", "removed"}:
            finding(
                "invalid_enabled_flag",
                component_id,
                "Connector lifecycle state is invalid and is treated as removed.",
            )
            lifecycle_state = "removed"
        enabled = (
            configured_enabled
            and lifecycle_state == "active"
            and network_mode == "explicit"
        )
        if network_mode not in {"disabled", "explicit"}:
            finding(
                "invalid_enabled_flag",
                component_id,
                "Connector network mode is invalid and is treated as disabled.",
            )
            enabled = False
        raw_origins = instance.get("allowed_origins")
        origins: list[str] = []
        origins_valid = isinstance(raw_origins, list)
        if origins_valid:
            for raw_origin in raw_origins:
                origin, valid = _endpoint_origin(raw_origin)
                if not valid or origin is None:
                    origins_valid = False
                    break
                if origin not in origins:
                    origins.append(origin)
        if not origins_valid:
            origins = []
            finding(
                "invalid_external_endpoint",
                component_id,
                "Connector allowed origins are not safe HTTP(S) origins.",
            )
        if enabled and not origins:
            finding(
                "missing_external_endpoint",
                component_id,
                "Connector network access is explicit without an allowed origin.",
            )
        declared_endpoint, endpoint_valid = _endpoint_origin(instance.get("endpoint"))
        if (
            instance.get("schema_version", 1) == 1
            and instance.get("endpoint") is None
            and origins
        ):
            declared_endpoint = origins[0]
        if not endpoint_valid or (
            declared_endpoint is not None and declared_endpoint not in origins
        ):
            declared_endpoint = None
            finding(
                "invalid_external_endpoint",
                component_id,
                "Connector endpoint is not a member of its safe origin allowlist.",
            )
        categories, categories_valid = _data_categories(
            definition.get("data_categories")
            if isinstance(definition, Mapping)
            else None
        )
        if not categories_valid:
            finding(
                "invalid_data_categories",
                component_id,
                "Connector data categories are invalid.",
            )
        if definition is None:
            finding(
                "undeclared_component_type",
                component_id,
                "Connector instance references an unavailable definition.",
            )
        component = _component(
            component_id=component_id,
            category="connector",
            component_type=component_type,
            enabled=enabled,
            network_capability="external" if definition is not None else "unknown",
            declaration_state="declared" if definition is not None else "undeclared",
            endpoint=declared_endpoint,
            data_categories=categories,
        )
        component["allowed_origins"] = origins
        component["configured_enabled"] = configured_enabled
        component["lifecycle_state"] = lifecycle_state
        component["health"] = (
            "removed"
            if lifecycle_state == "removed"
            else "disabled"
            if not configured_enabled
            else "policy_blocked"
            if network_mode == "explicit" and not external_access
            else "not_checked"
        )
        component["authorization_mode"] = (
            instance.get("authorization_mode")
            if instance.get("authorization_mode") in {"none", "external_secret", "oauth2_pkce"}
            else "unknown"
        )
        components.append(component)

    for component in components:
        if (
            component["enabled"]
            and component["network_capability"] == "external"
            and not external_access
        ):
            finding(
                "external_component_blocked_by_policy",
                str(component["id"]),
                "An enabled external component conflicts with external_access: false.",
            )

    enabled_external = sum(
        1
        for component in components
        if component["enabled"] and component["network_capability"] == "external"
    )
    enabled_unknown = sum(
        1
        for component in components
        if component["enabled"] and component["network_capability"] == "unknown"
    )
    effective_policy = (
        "attention"
        if conflicts
        else "external_access_allowed"
        if external_access
        else "local_only"
    )
    return {
        "schema_version": NETWORK_STATUS_SCHEMA_VERSION,
        "status": effective_policy,
        "policy": {
            "external_access": external_access,
            "effective": effective_policy,
        },
        "summary": {
            "configured_components": len(components),
            "enabled_external_components": enabled_external,
            "enabled_unknown_components": enabled_unknown,
            "conflicts": len(conflicts),
        },
        "components": components,
        "conflicts": conflicts,
        "observed_activity": {
            "status": "not_instrumented",
            "detail": (
                "This result describes configured capability only; runtime network traffic "
                "is not observed."
            ),
        },
        "network_used": False,
    }
