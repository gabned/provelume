from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from .connector_model import (
    CONNECTOR_RECORD_SCHEMA_VERSION,
    ConnectorConflictError,
    ConnectorError,
    ConnectorIntegrityError,
    ConnectorNotFoundError,
    canonical_connector_errors,
    connector_definition_id,
    normalise_connector_definition_manifest,
    normalise_connector_instance_configuration,
    normalise_connector_source_configuration,
)
from .domain import ConnectorDefinition, ConnectorInstance, ConnectorSource
from .storage import InstanceStore, utc_now


class ConnectorManager:
    """Manage connector declarations without performing network access."""

    def __init__(self, store: InstanceStore):
        self.store = store

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

    def register_definition(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        normalised = normalise_connector_definition_manifest(manifest)
        definition_id = connector_definition_id(normalised["adapter_key"])
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
                    f"connector definition already exists with different content: {definition_id}"
                )
            return {**dict(existing), "network_attempted": False}

        definition = ConnectorDefinition(
            schema_version=CONNECTOR_RECORD_SCHEMA_VERSION,
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
        return {
            **(self.get_definition(definition_id) or {}),
            "network_attempted": False,
        }

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
        network_mode: str = "disabled",
        allowed_origins: Sequence[str] = (),
        authorization_mode: str = "none",
        scopes: Sequence[str] = (),
        credential_reference: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        definitions, _instances, _sources = self._state()
        definition = definitions.get(definition_id)
        if definition is None:
            raise ConnectorNotFoundError(f"connector definition not found: {definition_id}")
        config = normalise_connector_instance_configuration(
            name=name,
            provider_identity=provider_identity,
            account_identity=account_identity,
            network_mode=network_mode,
            allowed_origins=allowed_origins,
            authorization_mode=authorization_mode,
            scopes=scopes,
            credential_reference=credential_reference,
        )
        if config["authorization_mode"] not in definition["authorization_modes"]:
            raise ConnectorConflictError(
                "authorization mode is not declared by the connector definition"
            )
        if config["network_mode"] == "explicit" and "manual_read" not in definition["capabilities"]:
            raise ConnectorConflictError(
                "explicit network mode requires the manual_read capability"
            )
        now = utc_now()
        instance_id = f"connector_instance_{uuid4().hex}"
        instance = ConnectorInstance(
            schema_version=CONNECTOR_RECORD_SCHEMA_VERSION,
            id=instance_id,
            definition_id=definition_id,
            name=str(config["name"]),
            provider_identity=str(config["provider_identity"]),
            account_identity=(
                str(config["account_identity"]) if config["account_identity"] is not None else None
            ),
            network_mode=str(config["network_mode"]),
            allowed_origins=tuple(config["allowed_origins"]),
            authorization_mode=str(config["authorization_mode"]),
            scopes=tuple(config["scopes"]),
            credential_reference=config["credential_reference"],
            created_at=now,
            updated_at=now,
        )
        self.store.write_connector_instance(instance)
        return self.get_instance(instance_id) or {}

    def _instance_view(
        self,
        instance: Mapping[str, Any],
        definitions: Mapping[str, Mapping[str, Any]],
        sources: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        raw_network = self.store.read_config().get("network")
        network = raw_network if isinstance(raw_network, Mapping) else {}
        global_network = bool(network.get("external_access", False))
        instance_id = str(instance["id"])
        selected_sources = [
            dict(source)
            for source in sources.values()
            if source["connector_instance_id"] == instance_id
        ]
        selected_sources.sort(key=lambda item: (str(item["name"]).casefold(), str(item["id"])))
        return {
            **dict(instance),
            "definition": dict(definitions[str(instance["definition_id"])]),
            "sources": selected_sources,
            "source_count": len(selected_sources),
            "effective_network": (
                "explicit"
                if global_network and instance["network_mode"] == "explicit"
                else "disabled"
            ),
            "network_attempted": False,
        }

    def list_instances(self) -> list[dict[str, Any]]:
        definitions, instances, sources = self._state()
        result = [
            self._instance_view(instance, definitions, sources) for instance in instances.values()
        ]
        return sorted(
            result,
            key=lambda item: (str(item["name"]).casefold(), str(item["id"])),
        )

    def get_instance(self, instance_id: str) -> dict[str, Any] | None:
        definitions, instances, sources = self._state()
        instance = instances.get(instance_id)
        return self._instance_view(instance, definitions, sources) if instance is not None else None

    def add_source(
        self,
        connector_instance_id: str,
        *,
        name: str,
        source_kind: str,
        external_id: str,
    ) -> dict[str, Any]:
        definitions, instances, sources = self._state()
        instance = instances.get(connector_instance_id)
        if instance is None:
            raise ConnectorNotFoundError(f"connector instance not found: {connector_instance_id}")
        definition = definitions[str(instance["definition_id"])]
        config = normalise_connector_source_configuration(
            name=name,
            source_kind=source_kind,
            external_id=external_id,
        )
        if config["source_kind"] not in definition["source_kinds"]:
            raise ConnectorConflictError("Source kind is not declared by the connector definition")
        for source in sources.values():
            if (
                source["connector_instance_id"] == connector_instance_id
                and source["source_kind"] == config["source_kind"]
                and source["external_id"] == config["external_id"]
            ):
                return {**dict(source), "network_attempted": False}
        source = ConnectorSource(
            schema_version=CONNECTOR_RECORD_SCHEMA_VERSION,
            id=f"src_{uuid4().hex}",
            kind="connector",
            name=config["name"],
            created_at=utc_now(),
            connector_instance_id=connector_instance_id,
            source_kind=config["source_kind"],
            external_id=config["external_id"],
        )
        self.store.write_connector_source(source)
        return {
            **(self.store.read_canonical("sources", source.id) or {}),
            "network_attempted": False,
        }

    def inventory(self) -> dict[str, Any]:
        definitions = self.list_definitions()
        instances = self.list_instances()
        return {
            "schema_version": CONNECTOR_RECORD_SCHEMA_VERSION,
            "status": "configured" if instances else "empty",
            "definitions": definitions,
            "instances": instances,
            "summary": {
                "definitions": len(definitions),
                "instances": len(instances),
                "sources": sum(int(item["source_count"]) for item in instances),
                "network_attempted": False,
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
