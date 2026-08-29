from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import uuid4

from .connector_model import (
    CONNECTOR_DEFINITION_SCHEMA_VERSION,
    CONNECTOR_INVENTORY_SCHEMA_VERSION,
    CONNECTOR_LIFECYCLE_SCHEMA_VERSION,
    ConnectorConflictError,
    ConnectorError,
    ConnectorIntegrityError,
    ConnectorNotFoundError,
    canonical_connector_errors,
    connector_definition_id,
    connector_instance_lifecycle,
    connector_source_lifecycle,
    normalise_connector_definition_manifest,
    normalise_connector_instance_configuration,
    normalise_connector_source_configuration,
)
from .domain import ConnectorDefinition, ConnectorInstance, ConnectorSource
from .locks import InstanceLockManager
from .operations import OperationLedger
from .storage import InstanceStore, utc_now

CONNECTOR_CONFIGURATION_LOCK = "connector-configuration"
_INSTANCE_UPDATE_FIELDS = frozenset(
    {
        "name",
        "provider_identity",
        "account_identity",
        "endpoint",
        "network_mode",
        "allowed_origins",
        "authorization_mode",
        "scopes",
        "credential_reference",
    }
)
_SOURCE_UPDATE_FIELDS = frozenset({"name"})
MutationResult = tuple[dict[str, Any], tuple[str, ...], dict[str, int]]


class ConnectorManager:
    """Manage isolated connector configuration without performing network access."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.operations = OperationLedger(store)
        self.locks = InstanceLockManager(store)

    def _state(
        self,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        definitions = {
            str(item.get("id", "")): item
            for item in self.store.list_canonical("connector-definitions")
        }
        instances = {
            str(item.get("id", "")): item
            for item in self.store.list_canonical("connector-instances")
        }
        sources = {
            str(item.get("id", "")): item
            for item in self.store.list_canonical("sources")
            if item.get("kind") == "connector"
        }
        errors = canonical_connector_errors(definitions, instances, sources)
        if errors:
            raise ConnectorIntegrityError(errors[0][1])
        return definitions, instances, sources

    @staticmethod
    def _operation_view(record: Any) -> dict[str, Any]:
        return {
            "id": record.id,
            "status": record.status,
            "completed_at": record.completed_at,
        }

    def _mutate(
        self,
        *,
        kind: str,
        title: str,
        related: dict[str, str],
        apply: Callable[[], MutationResult],
    ) -> dict[str, Any]:
        with self.locks.hold(CONNECTOR_CONFIGURATION_LOCK, purpose=kind):
            operation = self.operations.start(
                kind,
                title,
                summary="Validate and atomically persist local connector configuration.",
                related=related,
            )
            try:
                result, changed_fields, metrics = apply()
                self.operations.append(
                    operation.id,
                    f"{kind}.saved",
                    "Connector configuration was validated and saved locally.",
                    details={
                        "changed_fields": ",".join(changed_fields) or "none",
                        "network_attempted": False,
                        "original_action": "none",
                    },
                )
                closed = self.operations.close(
                    operation.id,
                    status="completed",
                    summary=(
                        "Connector configuration completed without network access or Original "
                        "mutation."
                    ),
                    metrics={
                        "changed_fields": len(changed_fields),
                        "originals_deleted": 0,
                        "originals_overwritten": 0,
                        **metrics,
                    },
                )
                return {
                    **result,
                    "operation": self._operation_view(closed),
                    "network_attempted": False,
                }
            except Exception as exc:
                current = self.operations.get_record(operation.id)
                if current is not None and current.status == "running":
                    self.operations.append(
                        operation.id,
                        f"{kind}.failed",
                        "Connector configuration was not changed.",
                        level="error",
                        details={
                            "error_type": exc.__class__.__name__,
                            "network_attempted": False,
                            "original_action": "none",
                        },
                    )
                    self.operations.close(
                        operation.id,
                        status="failed",
                        summary="Connector configuration was not changed.",
                        error_code="connector_configuration_failed",
                        error=exc.__class__.__name__,
                    )
                raise

    @staticmethod
    def _configuration(instance: Mapping[str, Any]) -> dict[str, Any]:
        return normalise_connector_instance_configuration(
            name=instance.get("name"),
            provider_identity=instance.get("provider_identity"),
            account_identity=instance.get("account_identity"),
            endpoint=instance.get("endpoint"),
            network_mode=instance.get("network_mode"),
            allowed_origins=instance.get("allowed_origins"),
            authorization_mode=instance.get("authorization_mode"),
            scopes=instance.get("scopes"),
            credential_reference=instance.get("credential_reference"),
            derive_endpoint=(
                instance.get("schema_version") == CONNECTOR_DEFINITION_SCHEMA_VERSION
            ),
        )

    @staticmethod
    def _health(*, enabled: bool, lifecycle_state: str) -> dict[str, Any]:
        if lifecycle_state == "removed":
            return {
                "status": "removed",
                "checked_at": None,
                "code": "connector_removed",
            }
        return {
            "status": "not_checked" if enabled else "disabled",
            "checked_at": None,
            "code": "network_not_attempted" if enabled else "connector_disabled",
        }

    def _write_instance(
        self,
        existing: Mapping[str, Any],
        config: Mapping[str, Any],
        *,
        enabled: bool,
        lifecycle_state: str,
        removed_at: str | None,
        updated_at: str,
    ) -> None:
        self.store.write_connector_instance(
            ConnectorInstance(
                schema_version=CONNECTOR_LIFECYCLE_SCHEMA_VERSION,
                id=str(existing["id"]),
                definition_id=str(existing["definition_id"]),
                name=str(config["name"]),
                provider_identity=str(config["provider_identity"]),
                account_identity=(
                    str(config["account_identity"])
                    if config["account_identity"] is not None
                    else None
                ),
                endpoint=str(config["endpoint"]) if config["endpoint"] is not None else None,
                network_mode=str(config["network_mode"]),
                allowed_origins=tuple(config["allowed_origins"]),
                authorization_mode=str(config["authorization_mode"]),
                scopes=tuple(config["scopes"]),
                credential_reference=config["credential_reference"],
                enabled=enabled,
                lifecycle_state=lifecycle_state,
                removed_at=removed_at,
                cursors={},
                health=self._health(enabled=enabled, lifecycle_state=lifecycle_state),
                created_at=str(existing["created_at"]),
                updated_at=updated_at,
            )
        )

    def _write_source(
        self,
        existing: Mapping[str, Any],
        config: Mapping[str, str],
        *,
        enabled: bool,
        lifecycle_state: str,
        removed_at: str | None,
        updated_at: str,
    ) -> None:
        self.store.write_connector_source(
            ConnectorSource(
                schema_version=CONNECTOR_LIFECYCLE_SCHEMA_VERSION,
                id=str(existing["id"]),
                kind="connector",
                name=str(config["name"]),
                created_at=str(existing["created_at"]),
                connector_instance_id=str(existing["connector_instance_id"]),
                source_kind=str(config["source_kind"]),
                external_id=str(config["external_id"]),
                enabled=enabled,
                lifecycle_state=lifecycle_state,
                updated_at=updated_at,
                removed_at=removed_at,
            )
        )

    @staticmethod
    def _assert_definition_supports(
        definition: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> None:
        if config["authorization_mode"] not in definition["authorization_modes"]:
            raise ConnectorConflictError(
                "authorization mode is not declared by the connector definition"
            )
        if config["network_mode"] == "explicit" and "manual_read" not in definition["capabilities"]:
            raise ConnectorConflictError(
                "explicit network mode requires the manual_read capability"
            )

    def register_definition(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        normalised = normalise_connector_definition_manifest(manifest)
        definition_id = connector_definition_id(normalised["adapter_key"])

        def apply() -> MutationResult:
            definitions, _instances, _sources = self._state()
            existing = definitions.get(definition_id)
            if existing is not None:
                comparable = {
                    key: value
                    for key, value in existing.items()
                    if key not in {"schema_version", "id", "created_at"}
                }
                if comparable != normalised:
                    raise ConnectorConflictError(
                        "connector definition already exists with different content: "
                        f"{definition_id}"
                    )
                return dict(existing), (), {"configuration_records": 0}

            definition = ConnectorDefinition(
                schema_version=CONNECTOR_DEFINITION_SCHEMA_VERSION,
                id=definition_id,
                adapter_key=str(normalised["adapter_key"]),
                adapter_version=str(normalised["adapter_version"]),
                display_name=str(normalised["display_name"]),
                provider=str(normalised["provider"]),
                conformance_profile=str(normalised["conformance_profile"]),
                adapter_protocol_version=int(normalised["adapter_protocol_version"]),
                capabilities=tuple(normalised["capabilities"]),
                authorization_modes=tuple(normalised["authorization_modes"]),
                source_kinds=tuple(normalised["source_kinds"]),
                data_categories=tuple(normalised["data_categories"]),
                multi_instance=True,
                network_access="explicit_only",
                created_at=utc_now(),
            )
            self.store.write_connector_definition(definition)
            return (
                dict(self.store.read_canonical("connector-definitions", definition_id) or {}),
                ("definition",),
                {"configuration_records": 1},
            )

        return self._mutate(
            kind="connector.definition.register",
            title="Register connector definition",
            related={"connector_definition_id": definition_id},
            apply=apply,
        )

    def list_definitions(self) -> list[dict[str, Any]]:
        definitions, _instances, _sources = self._state()
        return [dict(definitions[key]) for key in sorted(definitions)]

    def get_definition(self, definition_id: str) -> dict[str, Any] | None:
        definitions, _instances, _sources = self._state()
        selected = definitions.get(definition_id)
        return dict(selected) if selected is not None else None

    def create_instance(
        self,
        definition_id: str,
        *,
        name: str,
        provider_identity: str,
        account_identity: str | None = None,
        endpoint: str | None = None,
        network_mode: str = "disabled",
        allowed_origins: Sequence[str] = (),
        authorization_mode: str = "none",
        scopes: Sequence[str] = (),
        credential_reference: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        instance_id = f"connector_instance_{uuid4().hex}"

        def apply() -> MutationResult:
            definitions, _instances, _sources = self._state()
            definition = definitions.get(definition_id)
            if definition is None:
                raise ConnectorNotFoundError(
                    f"connector definition not found: {definition_id}"
                )
            config = normalise_connector_instance_configuration(
                name=name,
                provider_identity=provider_identity,
                account_identity=account_identity,
                endpoint=endpoint,
                network_mode=network_mode,
                allowed_origins=allowed_origins,
                authorization_mode=authorization_mode,
                scopes=scopes,
                credential_reference=credential_reference,
                derive_endpoint=True,
            )
            self._assert_definition_supports(definition, config)
            now = utc_now()
            seed = {
                "id": instance_id,
                "definition_id": definition_id,
                "created_at": now,
            }
            self._write_instance(
                seed,
                config,
                enabled=True,
                lifecycle_state="active",
                removed_at=None,
                updated_at=now,
            )
            return (
                self.get_instance(instance_id) or {},
                tuple(sorted(config)),
                {"configuration_records": 1},
            )

        return self._mutate(
            kind="connector.instance.create",
            title="Create connector instance",
            related={"connector_instance_id": instance_id},
            apply=apply,
        )

    def update_instance(self, instance_id: str, **changes: Any) -> dict[str, Any]:
        unknown = set(changes) - _INSTANCE_UPDATE_FIELDS
        if unknown:
            raise ConnectorError(
                "unsupported connector instance update fields: " + ", ".join(sorted(unknown))
            )
        if not changes:
            raise ConnectorError("at least one connector instance update field is required")

        def apply() -> MutationResult:
            definitions, instances, _sources = self._state()
            existing = instances.get(instance_id)
            if existing is None:
                raise ConnectorNotFoundError(f"connector instance not found: {instance_id}")
            lifecycle = connector_instance_lifecycle(existing)
            if lifecycle["lifecycle_state"] == "removed":
                raise ConnectorConflictError("removed connector instance cannot be updated")
            current = self._configuration(existing)
            selected = {**current, **changes}
            config = normalise_connector_instance_configuration(
                **selected,
                derive_endpoint=False,
            )
            definition = definitions[str(existing["definition_id"])]
            self._assert_definition_supports(definition, config)
            changed_fields = tuple(
                sorted(key for key in config if config[key] != current[key])
            )
            if changed_fields:
                self._write_instance(
                    existing,
                    config,
                    enabled=bool(lifecycle["enabled"]),
                    lifecycle_state="active",
                    removed_at=None,
                    updated_at=utc_now(),
                )
            return (
                self.get_instance(instance_id) or {},
                changed_fields,
                {"configuration_records": int(bool(changed_fields))},
            )

        return self._mutate(
            kind="connector.instance.update",
            title="Update connector instance",
            related={"connector_instance_id": instance_id},
            apply=apply,
        )

    def _set_instance_enabled(self, instance_id: str, *, enabled: bool) -> dict[str, Any]:
        action = "enable" if enabled else "disable"

        def apply() -> MutationResult:
            _definitions, instances, _sources = self._state()
            existing = instances.get(instance_id)
            if existing is None:
                raise ConnectorNotFoundError(f"connector instance not found: {instance_id}")
            lifecycle = connector_instance_lifecycle(existing)
            if lifecycle["lifecycle_state"] == "removed":
                raise ConnectorConflictError("removed connector instance cannot change state")
            changed = bool(lifecycle["enabled"]) != enabled
            if changed:
                self._write_instance(
                    existing,
                    self._configuration(existing),
                    enabled=enabled,
                    lifecycle_state="active",
                    removed_at=None,
                    updated_at=utc_now(),
                )
            return (
                self.get_instance(instance_id) or {},
                ("enabled",) if changed else (),
                {"configuration_records": int(changed)},
            )

        return self._mutate(
            kind=f"connector.instance.{action}",
            title=f"{action.capitalize()} connector instance",
            related={"connector_instance_id": instance_id},
            apply=apply,
        )

    def enable_instance(self, instance_id: str) -> dict[str, Any]:
        return self._set_instance_enabled(instance_id, enabled=True)

    def disable_instance(self, instance_id: str) -> dict[str, Any]:
        return self._set_instance_enabled(instance_id, enabled=False)

    def remove_instance(self, instance_id: str) -> dict[str, Any]:
        def apply() -> MutationResult:
            _definitions, instances, sources = self._state()
            existing = instances.get(instance_id)
            if existing is None:
                raise ConnectorNotFoundError(f"connector instance not found: {instance_id}")
            lifecycle = connector_instance_lifecycle(existing)
            attached = [
                source
                for source in sources.values()
                if source["connector_instance_id"] == instance_id
            ]
            retained = [
                source
                for source in attached
                if connector_source_lifecycle(source)["lifecycle_state"] != "removed"
            ]
            if retained:
                raise ConnectorConflictError(
                    "connector Sources must be removed independently before the instance"
                )
            changed = lifecycle["lifecycle_state"] != "removed"
            if changed:
                now = utc_now()
                self._write_instance(
                    existing,
                    self._configuration(existing),
                    enabled=False,
                    lifecycle_state="removed",
                    removed_at=now,
                    updated_at=now,
                )
            source_ids = {str(source["id"]) for source in attached}
            acquisitions = sum(
                item.get("source_id") in source_ids
                for item in self.store.list_canonical("acquisitions")
            )
            documents = sum(
                item.get("source_id") in source_ids
                for item in self.store.list_canonical("documents")
            )
            return (
                self.get_instance(instance_id) or {},
                ("lifecycle_state", "enabled") if changed else (),
                {
                    "configuration_records": int(changed),
                    "sources_retained": len(attached),
                    "acquisitions_preserved": acquisitions,
                    "documents_preserved": documents,
                },
            )

        return self._mutate(
            kind="connector.instance.remove",
            title="Remove connector instance configuration",
            related={"connector_instance_id": instance_id},
            apply=apply,
        )

    def _source_counts(self) -> tuple[Counter[str], Counter[str]]:
        document_counts = Counter(
            str(item.get("source_id", ""))
            for item in self.store.list_canonical("documents")
        )
        acquisition_counts = Counter(
            str(item.get("source_id", ""))
            for item in self.store.list_canonical("acquisitions")
        )
        return document_counts, acquisition_counts

    def _source_view(
        self,
        source: Mapping[str, Any],
        parent: Mapping[str, Any],
        *,
        document_counts: Mapping[str, int],
        acquisition_counts: Mapping[str, int],
    ) -> dict[str, Any]:
        lifecycle = connector_source_lifecycle(source)
        parent_lifecycle = connector_instance_lifecycle(parent)
        source_active = lifecycle["lifecycle_state"] == "active"
        parent_active = parent_lifecycle["lifecycle_state"] == "active"
        effective_enabled = bool(
            source_active
            and parent_active
            and lifecycle["enabled"]
            and parent_lifecycle["enabled"]
        )
        if not source_active:
            health_status = "removed"
        elif not lifecycle["enabled"]:
            health_status = "disabled"
        elif not parent_active or not parent_lifecycle["enabled"]:
            health_status = "parent_disabled"
        else:
            health_status = "not_checked"
        source_id = str(source["id"])
        return {
            **dict(source),
            **lifecycle,
            "configured_enabled": bool(lifecycle["enabled"]),
            "effective_enabled": effective_enabled,
            "health": {
                "status": health_status,
                "checked_at": None,
                "network_attempted": False,
            },
            "document_count": int(document_counts.get(source_id, 0)),
            "acquisition_count": int(acquisition_counts.get(source_id, 0)),
            "original_policy": "preserved",
            "network_attempted": False,
        }

    def _instance_view(
        self,
        instance: Mapping[str, Any],
        definitions: Mapping[str, Mapping[str, Any]],
        sources: Mapping[str, Mapping[str, Any]],
        *,
        document_counts: Mapping[str, int],
        acquisition_counts: Mapping[str, int],
    ) -> dict[str, Any]:
        raw_network = self.store.read_config().get("network")
        network = raw_network if isinstance(raw_network, Mapping) else {}
        global_network = bool(network.get("external_access", False))
        instance_id = str(instance["id"])
        lifecycle = connector_instance_lifecycle(instance)
        config = self._configuration(instance)
        selected_sources = [
            self._source_view(
                source,
                instance,
                document_counts=document_counts,
                acquisition_counts=acquisition_counts,
            )
            for source in sources.values()
            if source["connector_instance_id"] == instance_id
        ]
        selected_sources.sort(
            key=lambda item: (str(item["name"]).casefold(), str(item["id"]))
        )
        active = lifecycle["lifecycle_state"] == "active"
        configured_enabled = bool(lifecycle["enabled"] and active)
        effective_network = (
            "explicit"
            if configured_enabled
            and global_network
            and config["network_mode"] == "explicit"
            else "disabled"
        )
        if not active:
            health_status = "removed"
            health_code = "connector_removed"
        elif not lifecycle["enabled"]:
            health_status = "disabled"
            health_code = "connector_disabled"
        elif config["network_mode"] == "explicit" and not global_network:
            health_status = "policy_blocked"
            health_code = "global_network_disabled"
        else:
            health_status = "not_checked"
            health_code = "network_not_attempted"
        active_sources = sum(
            item["lifecycle_state"] == "active" for item in selected_sources
        )
        enabled_sources = sum(bool(item["effective_enabled"]) for item in selected_sources)
        return {
            **dict(instance),
            **config,
            **lifecycle,
            "definition": dict(definitions[str(instance["definition_id"])]),
            "sources": selected_sources,
            "source_count": len(selected_sources),
            "active_source_count": active_sources,
            "enabled_source_count": enabled_sources,
            "removed_source_count": len(selected_sources) - active_sources,
            "configured_enabled": configured_enabled,
            "effective_network": effective_network,
            "policy": {
                "enabled": configured_enabled,
                "endpoint": config["endpoint"],
                "network_mode": str(config["network_mode"]),
                "allowed_origins": list(config["allowed_origins"]),
                "authorization_mode": str(config["authorization_mode"]),
                "scopes": list(config["scopes"]),
                "global_external_access": global_network,
                "effective_network": effective_network,
            },
            "cursors": {},
            "health": {
                "status": health_status,
                "checked_at": None,
                "code": health_code,
                "network_attempted": False,
            },
            "credential_reference_configured": config["credential_reference"] is not None,
            "network_attempted": False,
        }

    def _views(
        self,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        definitions, instances, sources = self._state()
        document_counts, acquisition_counts = self._source_counts()
        views = {
            instance_id: self._instance_view(
                instance,
                definitions,
                sources,
                document_counts=document_counts,
                acquisition_counts=acquisition_counts,
            )
            for instance_id, instance in instances.items()
        }
        return definitions, views, sources

    def list_instances(self) -> list[dict[str, Any]]:
        _definitions, views, _sources = self._views()
        return sorted(
            views.values(),
            key=lambda item: (str(item["name"]).casefold(), str(item["id"])),
        )

    def get_instance(self, instance_id: str) -> dict[str, Any] | None:
        _definitions, views, _sources = self._views()
        return views.get(instance_id)

    def list_sources(self, instance_id: str | None = None) -> list[dict[str, Any]]:
        _definitions, views, _sources = self._views()
        selected: list[dict[str, Any]] = []
        for connector in views.values():
            if instance_id is None or connector["id"] == instance_id:
                selected.extend(connector["sources"])
        return sorted(
            selected,
            key=lambda item: (str(item["name"]).casefold(), str(item["id"])),
        )

    def get_source(self, instance_id: str, source_id: str) -> dict[str, Any] | None:
        connector = self.get_instance(instance_id)
        if connector is None:
            return None
        return next(
            (source for source in connector["sources"] if source["id"] == source_id),
            None,
        )

    def add_source(
        self,
        connector_instance_id: str,
        *,
        name: str,
        source_kind: str,
        external_id: str,
    ) -> dict[str, Any]:
        source_id = f"src_{uuid4().hex}"

        def apply() -> MutationResult:
            definitions, instances, sources = self._state()
            instance = instances.get(connector_instance_id)
            if instance is None:
                raise ConnectorNotFoundError(
                    f"connector instance not found: {connector_instance_id}"
                )
            if connector_instance_lifecycle(instance)["lifecycle_state"] == "removed":
                raise ConnectorConflictError(
                    "cannot add a Source to a removed connector instance"
                )
            definition = definitions[str(instance["definition_id"])]
            config = normalise_connector_source_configuration(
                name=name,
                source_kind=source_kind,
                external_id=external_id,
            )
            if config["source_kind"] not in definition["source_kinds"]:
                raise ConnectorConflictError(
                    "Source kind is not declared by the connector definition"
                )
            for source in sources.values():
                if (
                    source["connector_instance_id"] == connector_instance_id
                    and source["source_kind"] == config["source_kind"]
                    and source["external_id"] == config["external_id"]
                ):
                    if connector_source_lifecycle(source)["lifecycle_state"] == "removed":
                        raise ConnectorConflictError(
                            "removed connector Source identity is retained and cannot be recreated"
                        )
                    return (
                        self.get_source(connector_instance_id, str(source["id"])) or {},
                        (),
                        {"configuration_records": 0},
                    )
            now = utc_now()
            seed = {
                "id": source_id,
                "created_at": now,
                "connector_instance_id": connector_instance_id,
            }
            self._write_source(
                seed,
                config,
                enabled=True,
                lifecycle_state="active",
                removed_at=None,
                updated_at=now,
            )
            return (
                self.get_source(connector_instance_id, source_id) or {},
                tuple(sorted(config)),
                {"configuration_records": 1},
            )

        return self._mutate(
            kind="connector.source.create",
            title="Create connector Source",
            related={
                "connector_instance_id": connector_instance_id,
                "source_id": source_id,
            },
            apply=apply,
        )

    def update_source(
        self,
        connector_instance_id: str,
        source_id: str,
        **changes: Any,
    ) -> dict[str, Any]:
        unknown = set(changes) - _SOURCE_UPDATE_FIELDS
        if unknown:
            raise ConnectorError(
                "unsupported connector Source update fields: " + ", ".join(sorted(unknown))
            )
        if not changes:
            raise ConnectorError("at least one connector Source update field is required")

        def apply() -> MutationResult:
            _definitions, instances, sources = self._state()
            parent = instances.get(connector_instance_id)
            source = sources.get(source_id)
            if parent is None:
                raise ConnectorNotFoundError(
                    f"connector instance not found: {connector_instance_id}"
                )
            if source is None or source["connector_instance_id"] != connector_instance_id:
                raise ConnectorNotFoundError(f"connector Source not found: {source_id}")
            lifecycle = connector_source_lifecycle(source)
            if lifecycle["lifecycle_state"] == "removed":
                raise ConnectorConflictError("removed connector Source cannot be updated")
            current = normalise_connector_source_configuration(
                name=source.get("name"),
                source_kind=source.get("source_kind"),
                external_id=source.get("external_id"),
            )
            config = normalise_connector_source_configuration(**{**current, **changes})
            changed_fields = tuple(
                sorted(key for key in config if config[key] != current[key])
            )
            if changed_fields:
                self._write_source(
                    source,
                    config,
                    enabled=bool(lifecycle["enabled"]),
                    lifecycle_state="active",
                    removed_at=None,
                    updated_at=utc_now(),
                )
            return (
                self.get_source(connector_instance_id, source_id) or {},
                changed_fields,
                {"configuration_records": int(bool(changed_fields))},
            )

        return self._mutate(
            kind="connector.source.update",
            title="Update connector Source",
            related={
                "connector_instance_id": connector_instance_id,
                "source_id": source_id,
            },
            apply=apply,
        )

    def _set_source_enabled(
        self,
        connector_instance_id: str,
        source_id: str,
        *,
        enabled: bool,
    ) -> dict[str, Any]:
        action = "enable" if enabled else "disable"

        def apply() -> MutationResult:
            _definitions, instances, sources = self._state()
            parent = instances.get(connector_instance_id)
            source = sources.get(source_id)
            if parent is None:
                raise ConnectorNotFoundError(
                    f"connector instance not found: {connector_instance_id}"
                )
            if source is None or source["connector_instance_id"] != connector_instance_id:
                raise ConnectorNotFoundError(f"connector Source not found: {source_id}")
            if connector_instance_lifecycle(parent)["lifecycle_state"] == "removed":
                raise ConnectorConflictError(
                    "Source state cannot change under a removed instance"
                )
            lifecycle = connector_source_lifecycle(source)
            if lifecycle["lifecycle_state"] == "removed":
                raise ConnectorConflictError("removed connector Source cannot change state")
            changed = bool(lifecycle["enabled"]) != enabled
            if changed:
                config = normalise_connector_source_configuration(
                    name=source.get("name"),
                    source_kind=source.get("source_kind"),
                    external_id=source.get("external_id"),
                )
                self._write_source(
                    source,
                    config,
                    enabled=enabled,
                    lifecycle_state="active",
                    removed_at=None,
                    updated_at=utc_now(),
                )
            return (
                self.get_source(connector_instance_id, source_id) or {},
                ("enabled",) if changed else (),
                {"configuration_records": int(changed)},
            )

        return self._mutate(
            kind=f"connector.source.{action}",
            title=f"{action.capitalize()} connector Source",
            related={
                "connector_instance_id": connector_instance_id,
                "source_id": source_id,
            },
            apply=apply,
        )

    def enable_source(self, connector_instance_id: str, source_id: str) -> dict[str, Any]:
        return self._set_source_enabled(connector_instance_id, source_id, enabled=True)

    def disable_source(self, connector_instance_id: str, source_id: str) -> dict[str, Any]:
        return self._set_source_enabled(connector_instance_id, source_id, enabled=False)

    def remove_source(self, connector_instance_id: str, source_id: str) -> dict[str, Any]:
        def apply() -> MutationResult:
            _definitions, instances, sources = self._state()
            parent = instances.get(connector_instance_id)
            source = sources.get(source_id)
            if parent is None:
                raise ConnectorNotFoundError(
                    f"connector instance not found: {connector_instance_id}"
                )
            if source is None or source["connector_instance_id"] != connector_instance_id:
                raise ConnectorNotFoundError(f"connector Source not found: {source_id}")
            lifecycle = connector_source_lifecycle(source)
            changed = lifecycle["lifecycle_state"] != "removed"
            if changed:
                now = utc_now()
                config = normalise_connector_source_configuration(
                    name=source.get("name"),
                    source_kind=source.get("source_kind"),
                    external_id=source.get("external_id"),
                )
                self._write_source(
                    source,
                    config,
                    enabled=False,
                    lifecycle_state="removed",
                    removed_at=now,
                    updated_at=now,
                )
            documents = sum(
                item.get("source_id") == source_id
                for item in self.store.list_canonical("documents")
            )
            acquisitions = sum(
                item.get("source_id") == source_id
                for item in self.store.list_canonical("acquisitions")
            )
            return (
                self.get_source(connector_instance_id, source_id) or {},
                ("lifecycle_state", "enabled") if changed else (),
                {
                    "configuration_records": int(changed),
                    "documents_preserved": documents,
                    "acquisitions_preserved": acquisitions,
                },
            )

        return self._mutate(
            kind="connector.source.remove",
            title="Remove connector Source configuration",
            related={
                "connector_instance_id": connector_instance_id,
                "source_id": source_id,
            },
            apply=apply,
        )

    def inventory(self) -> dict[str, Any]:
        definitions = self.list_definitions()
        instances = self.list_instances()
        sources = [source for instance in instances for source in instance["sources"]]
        active_instances = [
            item for item in instances if item["lifecycle_state"] == "active"
        ]
        active_sources = [
            item for item in sources if item["lifecycle_state"] == "active"
        ]
        return {
            "schema_version": CONNECTOR_INVENTORY_SCHEMA_VERSION,
            "status": "configured" if instances else "empty",
            "definitions": definitions,
            "instances": instances,
            "summary": {
                "definitions": len(definitions),
                "instances": len(instances),
                "sources": len(sources),
                "network_attempted": False,
            },
            "lifecycle": {
                "active_instances": len(active_instances),
                "enabled_instances": sum(
                    bool(item["configured_enabled"]) for item in active_instances
                ),
                "disabled_instances": sum(
                    not bool(item["configured_enabled"]) for item in active_instances
                ),
                "removed_instances": len(instances) - len(active_instances),
                "active_sources": len(active_sources),
                "enabled_sources": sum(
                    bool(item["effective_enabled"]) for item in active_sources
                ),
                "disabled_sources": sum(
                    not bool(item["effective_enabled"]) for item in active_sources
                ),
                "removed_sources": len(sources) - len(active_sources),
            },
            "authority": {
                "configuration": "canonical_json",
                "acquired_originals": "authoritative",
                "removal_action": "configuration_tombstone_only",
            },
            "network_attempted": False,
        }


__all__ = [
    "ConnectorConflictError",
    "ConnectorError",
    "ConnectorIntegrityError",
    "ConnectorManager",
    "ConnectorNotFoundError",
]
