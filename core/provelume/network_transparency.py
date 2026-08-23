from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from .storage import InstanceStore

LOCAL_SOURCE_KINDS = {"filesystem"}
MAX_COMPONENTS = 500
MAX_ENDPOINTS_PER_COMPONENT = 20
MAX_DATA_CATEGORIES = 20


@dataclass(frozen=True, slots=True)
class NetworkComponent:
    id: str
    kind: str
    name: str
    configured_enabled: bool
    effective_enabled: bool
    network_capable: bool | None
    implementation_status: str
    external_endpoints: tuple[str, ...]
    data_categories: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class NetworkIssue:
    component_id: str
    issue: str
    detail: str


def _boolean(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _strings(value: Any, *, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    output: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned and cleaned not in output:
            output.append(cleaned[:200])
        if len(output) >= limit:
            break
    return tuple(output)


def _endpoint_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.casefold()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port
    authority = host if port in {None, default_port} else f"{host}:{port}"
    return f"{parsed.scheme}://{authority}"


def _endpoints(
    value: Any,
    *,
    component_id: str,
    issues: list[NetworkIssue],
) -> tuple[str, ...]:
    raw = _strings(value, limit=MAX_ENDPOINTS_PER_COMPONENT)
    output: list[str] = []
    for endpoint in raw:
        origin = _endpoint_origin(endpoint)
        if origin is None:
            issues.append(
                NetworkIssue(
                    component_id=component_id,
                    issue="invalid_endpoint",
                    detail=(
                        "A configured endpoint is invalid or uses an unsupported scheme; "
                        "its value was not exposed."
                    ),
                )
            )
            continue
        if origin not in output:
            output.append(origin)
    return tuple(output)


def _source_components(
    config: dict[str, Any],
    issues: list[NetworkIssue],
) -> list[NetworkComponent]:
    configured = config.get("sources")
    if not isinstance(configured, dict):
        return []
    components: list[NetworkComponent] = []
    for source_id, raw in sorted(configured.items(), key=lambda item: str(item[0])):
        if len(components) >= MAX_COMPONENTS:
            issues.append(
                NetworkIssue(
                    component_id="sources",
                    issue="component_limit",
                    detail=f"Source transparency stopped at the {MAX_COMPONENTS}-component limit.",
                )
            )
            break
        row = raw if isinstance(raw, dict) else {}
        source_kind = str(row.get("kind") or "unknown").casefold()
        component_id = f"source.{source_id}"
        name = str(row.get("name") or source_id)[:200]
        if source_kind in LOCAL_SOURCE_KINDS:
            components.append(
                NetworkComponent(
                    id=component_id,
                    kind=f"source:{source_kind}",
                    name=name,
                    configured_enabled=True,
                    effective_enabled=True,
                    network_capable=False,
                    implementation_status="available",
                    external_endpoints=(),
                    data_categories=(),
                    detail="Local filesystem Source; the physical path is deliberately redacted.",
                )
            )
            continue

        declared = row.get("network_capable")
        network_capable = declared if isinstance(declared, bool) else None
        if network_capable is None:
            issues.append(
                NetworkIssue(
                    component_id=component_id,
                    issue="capability_undeclared",
                    detail=(
                        f"Source kind '{source_kind}' does not declare whether it can use "
                        "external network access."
                    ),
                )
            )
        endpoints = _endpoints(
            row.get("endpoints"),
            component_id=component_id,
            issues=issues,
        )
        categories = _strings(
            row.get("data_categories"),
            limit=MAX_DATA_CATEGORIES,
        )
        components.append(
            NetworkComponent(
                id=component_id,
                kind=f"source:{source_kind}",
                name=name,
                configured_enabled=True,
                effective_enabled=True,
                network_capable=network_capable,
                implementation_status="declared" if network_capable is not None else "undeclared",
                external_endpoints=endpoints,
                data_categories=categories,
                detail="Configured Source capability declaration; no source path is exposed.",
            )
        )
    return components


def _provider_components(
    config: dict[str, Any],
    issues: list[NetworkIssue],
) -> list[NetworkComponent]:
    configured = config.get("providers")
    if configured is None:
        return []
    if not isinstance(configured, dict):
        issues.append(
            NetworkIssue(
                component_id="providers",
                issue="invalid_declaration",
                detail="Provider configuration is not an object and cannot be audited.",
            )
        )
        return []

    components: list[NetworkComponent] = []
    for provider_id, raw in sorted(configured.items(), key=lambda item: str(item[0])):
        if len(components) >= MAX_COMPONENTS:
            issues.append(
                NetworkIssue(
                    component_id="providers",
                    issue="component_limit",
                    detail=f"Provider transparency stopped at the {MAX_COMPONENTS}-component limit.",
                )
            )
            break
        row = raw if isinstance(raw, dict) else {}
        component_id = f"provider.{provider_id}"
        name = str(row.get("name") or provider_id)[:200]
        configured_enabled = _boolean(row.get("enabled"))
        declared = row.get("network_capable")
        network_capable = declared if isinstance(declared, bool) else None
        if network_capable is None:
            issues.append(
                NetworkIssue(
                    component_id=component_id,
                    issue="capability_undeclared",
                    detail="Provider does not declare whether it can use external network access.",
                )
            )
        implementation_status = str(row.get("implementation_status") or "declared")[:80]
        effective_enabled = configured_enabled and implementation_status == "available"
        if configured_enabled and implementation_status != "available":
            issues.append(
                NetworkIssue(
                    component_id=component_id,
                    issue="configured_but_unavailable",
                    detail=(
                        "Provider is configured as enabled but is not declared available in "
                        "this runtime."
                    ),
                )
            )
        endpoints = _endpoints(
            row.get("endpoints"),
            component_id=component_id,
            issues=issues,
        )
        categories = _strings(
            row.get("data_categories"),
            limit=MAX_DATA_CATEGORIES,
        )
        if configured_enabled and network_capable is True and not endpoints:
            issues.append(
                NetworkIssue(
                    component_id=component_id,
                    issue="endpoint_undeclared",
                    detail="Enabled network-capable provider has no declared external endpoint.",
                )
            )
        components.append(
            NetworkComponent(
                id=component_id,
                kind="provider",
                name=name,
                configured_enabled=configured_enabled,
                effective_enabled=effective_enabled,
                network_capable=network_capable,
                implementation_status=implementation_status,
                external_endpoints=endpoints,
                data_categories=categories,
                detail="Optional provider capability declaration from Instance configuration.",
            )
        )
    return components


def network_transparency(store: InstanceStore) -> dict[str, Any]:
    """Describe declared external-network capability without performing network I/O."""

    config = store.read_config()
    network = config.get("network") if isinstance(config.get("network"), dict) else {}
    external_access_allowed = _boolean(network.get("external_access"))
    update_requested = _boolean(network.get("update_checks"))
    issues: list[NetworkIssue] = []

    update_component_id = "core.update_checks"
    update_endpoint_value = network.get("update_endpoint")
    update_endpoints = _endpoints(
        [update_endpoint_value] if isinstance(update_endpoint_value, str) else [],
        component_id=update_component_id,
        issues=issues,
    )
    if update_requested:
        issues.append(
            NetworkIssue(
                component_id=update_component_id,
                issue="configured_but_unavailable",
                detail=(
                    "Update checks are requested in configuration, but no updater/checker "
                    "runtime is implemented in this release."
                ),
            )
        )
        if not update_endpoints:
            issues.append(
                NetworkIssue(
                    component_id=update_component_id,
                    issue="endpoint_undeclared",
                    detail="Requested update checks have no declared external endpoint.",
                )
            )

    components: list[NetworkComponent] = [
        NetworkComponent(
            id=update_component_id,
            kind="builtin",
            name="Update checks",
            configured_enabled=update_requested,
            effective_enabled=False,
            network_capable=True,
            implementation_status="not_implemented",
            external_endpoints=update_endpoints,
            data_categories=("installed_version", "release_channel") if update_requested else (),
            detail="Future optional update capability; no hidden check is performed today.",
        ),
        NetworkComponent(
            id="core.telemetry",
            kind="builtin",
            name="Analytics and telemetry",
            configured_enabled=False,
            effective_enabled=False,
            network_capable=True,
            implementation_status="absent",
            external_endpoints=(),
            data_categories=(),
            detail="The baseline Core contains no analytics or telemetry client.",
        ),
        NetworkComponent(
            id="ui.remote_assets",
            kind="builtin",
            name="Remote browser assets",
            configured_enabled=False,
            effective_enabled=False,
            network_capable=True,
            implementation_status="absent",
            external_endpoints=(),
            data_categories=(),
            detail="Knowledge Browser assets are local; no CDN or remote font is required.",
        ),
    ]
    components.extend(_source_components(config, issues))
    components.extend(_provider_components(config, issues))

    configured_external = [
        component
        for component in components
        if component.configured_enabled and component.network_capable is True
    ]
    effective_external = [
        component
        for component in components
        if component.effective_enabled and component.network_capable is True
    ]
    undeclared = [component for component in components if component.network_capable is None]
    if not external_access_allowed and effective_external:
        for component in effective_external:
            issues.append(
                NetworkIssue(
                    component_id=component.id,
                    issue="policy_conflict",
                    detail=(
                        "Component is effectively enabled for external network access while "
                        "Instance policy disables external access."
                    ),
                )
            )

    conflict_issues = {
        "policy_conflict",
        "capability_undeclared",
        "invalid_declaration",
        "invalid_endpoint",
    }
    if any(issue.issue in conflict_issues for issue in issues):
        policy = "configuration_conflict"
    elif external_access_allowed or configured_external:
        policy = "explicit_external_access"
    else:
        policy = "local_only"

    endpoint_origins = sorted(
        {
            endpoint
            for component in components
            for endpoint in component.external_endpoints
        }
    )
    return {
        "schema_version": 1,
        "policy": policy,
        "external_access_allowed": external_access_allowed,
        "network_used_by_check": False,
        "summary": {
            "components": len(components),
            "network_capable_components": sum(
                component.network_capable is True for component in components
            ),
            "configured_external_components": len(configured_external),
            "effective_external_components": len(effective_external),
            "undeclared_capability_components": len(undeclared),
            "declared_endpoint_origins": len(endpoint_origins),
            "issues": len(issues),
        },
        "declared_endpoint_origins": endpoint_origins,
        "components": [asdict(component) for component in components],
        "issues": [asdict(issue) for issue in issues],
        "observed_activity": {
            "status": "not_instrumented",
            "events_available": False,
            "detail": (
                "This release reports declared capability and configuration. It does not "
                "yet instrument or claim to observe all runtime network traffic."
            ),
        },
    }
