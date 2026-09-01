from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .connector_model import normalise_secret_reference
from .connectors import ConnectorManager
from .google_contract import (
    GOOGLE_ADAPTER_ID,
    GOOGLE_ADAPTER_PROTOCOL_VERSION,
    GOOGLE_ADAPTER_VERSION,
    GOOGLE_ALLOWED_ORIGINS,
    GOOGLE_CAPABILITIES,
    GOOGLE_CAPABILITY_SCOPES,
    GOOGLE_CONFORMANCE_PROFILE,
    GOOGLE_DEFINITION_ID,
    GOOGLE_SOURCE_STATES,
    GoogleContractError,
    capability_fingerprint,
    google_definition_manifest,
    normalise_capability,
    normalise_selectors,
    public_credential_reference,
    require_identifier,
    source_fingerprint,
)
from .operations import OperationLedger
from .scheduler_model import schedule_payload
from .storage import InstanceStore, utc_now

GOOGLE_STATE_SCHEMA_VERSION = 1
GOOGLE_SCHEDULE_MODES = ("manual", "interval")


def _json_fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class GoogleSourceManager:
    """Google-specific configuration outside provider-neutral canonical identities."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.connectors = ConnectorManager(store)
        self.root = store.paths.state / "google-adapters"
        self.instances = self.root / "instances"
        self.sources = self.root / "sources"
        self.operations = OperationLedger(store)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise GoogleContractError(
                "google_payload_invalid", "Google adapter state is not a regular file"
            )
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GoogleContractError(
                "google_payload_invalid", "Google adapter state is unreadable"
            ) from exc
        if not isinstance(value, dict):
            raise GoogleContractError(
                "google_payload_invalid", "Google adapter state must be an object"
            )
        return value

    def _write_json(self, path: Path, value: Mapping[str, Any]) -> None:
        self.store._atomic_json(path, dict(value))

    def ensure_definition(self) -> dict[str, Any]:
        return self.connectors.register_definition(google_definition_manifest())

    @staticmethod
    def _capability_seed(capability: str) -> dict[str, Any]:
        return {
            "capability": capability,
            "scope": list(GOOGLE_CAPABILITY_SCOPES[capability]),
            "state": "disabled",
            "authorization_status": "not_authorized",
            "credential_reference": None,
            "consent": None,
            "authorized_at": None,
            "revoked_at": None,
            "revision": 1,
            "health": {
                "status": "not_authorized",
                "code": "google_authorization_required",
                "checked_at": None,
            },
        }

    def create_instance(self, *, name: str, account_identity: str) -> dict[str, Any]:
        self.ensure_definition()
        connector = self.connectors.create_instance(
            GOOGLE_DEFINITION_ID,
            name=name,
            provider_identity="google",
            account_identity=account_identity,
            endpoint="https://www.googleapis.com",
            network_mode="explicit",
            allowed_origins=GOOGLE_ALLOWED_ORIGINS,
            authorization_mode="none",
            scopes=(),
            credential_reference=None,
        )
        instance_id = str(connector["id"])
        now = utc_now()
        record = {
            "schema_version": GOOGLE_STATE_SCHEMA_VERSION,
            "connector_instance_id": instance_id,
            "adapter_id": GOOGLE_ADAPTER_ID,
            "adapter_version": GOOGLE_ADAPTER_VERSION,
            "adapter_protocol_version": GOOGLE_ADAPTER_PROTOCOL_VERSION,
            "conformance_profile": GOOGLE_CONFORMANCE_PROFILE,
            "qualification": "local-conformance-preview",
            "real_google_qualified": False,
            "allowed_origins": list(GOOGLE_ALLOWED_ORIGINS),
            "capabilities": {
                capability: self._capability_seed(capability) for capability in GOOGLE_CAPABILITIES
            },
            "created_at": now,
            "updated_at": now,
        }
        self._write_json(self.instances / f"{instance_id}.json", record)
        return self.instance_view(instance_id, local=True)

    def _instance_record(self, connector_instance_id: str) -> dict[str, Any]:
        instance_id = require_identifier(connector_instance_id, "instance")
        path = self.instances / f"{instance_id}.json"
        if not path.is_file():
            raise GoogleContractError(
                "google_payload_invalid", "Google connector instance was not found"
            )
        record = self._read_json(path)
        connector = self.connectors.get_instance(instance_id)
        if connector is None or connector.get("definition_id") != GOOGLE_DEFINITION_ID:
            raise GoogleContractError(
                "google_payload_invalid", "Google connector binding is invalid"
            )
        if record.get("connector_instance_id") != instance_id:
            raise GoogleContractError(
                "google_payload_invalid", "Google connector state identity is invalid"
            )
        return record

    def _write_instance_record(self, record: Mapping[str, Any]) -> None:
        instance_id = require_identifier(record.get("connector_instance_id"), "instance")
        self._write_json(self.instances / f"{instance_id}.json", record)

    def instance_view(self, connector_instance_id: str, *, local: bool = False) -> dict[str, Any]:
        record = self._instance_record(connector_instance_id)
        connector = self.connectors.get_instance(connector_instance_id)
        assert connector is not None
        external_access = bool(
            self.store.read_config().get("network", {}).get("external_access", False)
        )
        capabilities: dict[str, Any] = {}
        for name, raw in record["capabilities"].items():
            item = dict(raw)
            reference = normalise_secret_reference(item.pop("credential_reference"))
            item["credential_reference"] = (
                reference if local else public_credential_reference(reference)
            )
            item["effective_network"] = bool(
                external_access
                and connector.get("effective_network") == "explicit"
                and connector.get("enabled")
                and item.get("state") == "enabled"
                and item.get("authorization_status") == "authorized"
            )
            capabilities[name] = item
        return {
            "schema_version": GOOGLE_STATE_SCHEMA_VERSION,
            "connector": connector,
            "adapter": {
                "id": record["adapter_id"],
                "version": record["adapter_version"],
                "protocol_version": record["adapter_protocol_version"],
                "conformance_profile": record["conformance_profile"],
                "qualification": record["qualification"],
                "real_google_qualified": False,
            },
            "capabilities": capabilities,
            "allowed_origins": list(record["allowed_origins"]),
            "network_external_access": external_access,
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }

    def list_instances(self, *, local: bool = False) -> list[dict[str, Any]]:
        if not self.instances.exists():
            return []
        return [
            self.instance_view(path.stem, local=local)
            for path in sorted(self.instances.glob("connector_instance_*.json"))
        ]

    def authorize_capability(
        self,
        connector_instance_id: str,
        capability: str,
        *,
        credential_reference: Mapping[str, str],
        consent: bool,
    ) -> dict[str, Any]:
        selected = normalise_capability(capability)
        reference = normalise_secret_reference(credential_reference)
        if reference is None or consent is not True:
            raise GoogleContractError(
                "google_authorization_required",
                "Google capability requires explicit consent and an external credential reference",
            )
        record = self._instance_record(connector_instance_id)
        item = dict(record["capabilities"][selected])
        now = utc_now()
        item.update(
            {
                "state": "disabled",
                "authorization_status": "authorized",
                "credential_reference": reference,
                "consent": "explicit",
                "authorized_at": now,
                "revoked_at": None,
                "revision": int(item["revision"]) + 1,
                "health": {
                    "status": "ready",
                    "code": "network_not_attempted",
                    "checked_at": None,
                },
            }
        )
        capabilities = {**record["capabilities"], selected: item}
        self._write_instance_record({**record, "capabilities": capabilities, "updated_at": now})
        return self.instance_view(connector_instance_id, local=True)["capabilities"][selected]

    def set_capability_state(
        self,
        connector_instance_id: str,
        capability: str,
        state: str,
    ) -> dict[str, Any]:
        selected = normalise_capability(capability)
        if state not in {"enabled", "disabled"}:
            raise GoogleContractError(
                "google_payload_invalid", "Google capability state is unsupported"
            )
        record = self._instance_record(connector_instance_id)
        item = dict(record["capabilities"][selected])
        if state == "enabled" and item["authorization_status"] != "authorized":
            raise GoogleContractError(
                "google_authorization_required", "Google capability must be authorized first"
            )
        now = utc_now()
        item.update(
            {
                "state": state,
                "revision": int(item["revision"]) + 1,
                "health": {
                    "status": "ready" if state == "enabled" else "disabled",
                    "code": "network_not_attempted"
                    if state == "enabled"
                    else "google_capability_disabled",
                    "checked_at": None,
                },
            }
        )
        self._write_instance_record(
            {
                **record,
                "capabilities": {**record["capabilities"], selected: item},
                "updated_at": now,
            }
        )
        return self.instance_view(connector_instance_id)["capabilities"][selected]

    def revoke_capability(self, connector_instance_id: str, capability: str) -> dict[str, Any]:
        selected = normalise_capability(capability)
        record = self._instance_record(connector_instance_id)
        item = dict(record["capabilities"][selected])
        now = utc_now()
        item.update(
            {
                "state": "disabled",
                "authorization_status": "revoked",
                "credential_reference": None,
                "revoked_at": now,
                "revision": int(item["revision"]) + 1,
                "health": {
                    "status": "revoked",
                    "code": "google_authorization_required",
                    "checked_at": now,
                },
            }
        )
        self._write_instance_record(
            {
                **record,
                "capabilities": {**record["capabilities"], selected: item},
                "updated_at": now,
            }
        )
        return self.instance_view(connector_instance_id)["capabilities"][selected]

    def mark_reauthorization_required(
        self, connector_instance_id: str, capability: str, *, code: str
    ) -> None:
        selected = normalise_capability(capability)
        record = self._instance_record(connector_instance_id)
        item = dict(record["capabilities"][selected])
        now = utc_now()
        item.update(
            {
                "state": "disabled",
                "authorization_status": "reauthorization_required",
                "credential_reference": None,
                "revision": int(item["revision"]) + 1,
                "health": {
                    "status": "reauthorization_required",
                    "code": code,
                    "checked_at": now,
                },
            }
        )
        self._write_instance_record(
            {
                **record,
                "capabilities": {**record["capabilities"], selected: item},
                "updated_at": now,
            }
        )

    def capability_record(
        self,
        connector_instance_id: str,
        capability: str,
        *,
        require_enabled: bool = False,
    ) -> dict[str, Any]:
        selected = normalise_capability(capability)
        record = self._instance_record(connector_instance_id)
        item = dict(record["capabilities"][selected])
        if item.get("authorization_status") != "authorized":
            raise GoogleContractError(
                "google_authorization_required", "Google capability is not authorized"
            )
        if require_enabled and item.get("state") != "enabled":
            raise GoogleContractError("google_capability_disabled", "Google capability is disabled")
        return item

    def create_source(
        self,
        connector_instance_id: str,
        *,
        name: str,
        capability: str,
        selection_kind: str,
        selectors: Sequence[str],
    ) -> dict[str, Any]:
        selected = normalise_capability(capability)
        self._instance_record(connector_instance_id)
        normalised_kind, normalised_selectors = normalise_selectors(
            selected, selection_kind, selectors
        )
        selection_sha256 = _json_fingerprint(
            {
                "capability": selected,
                "selection_kind": normalised_kind,
                "selectors": normalised_selectors,
            }
        )
        connector_source = self.connectors.add_source(
            connector_instance_id,
            name=name,
            source_kind=selected,
            external_id=f"google:{selected}:{normalised_kind}:sha256:{selection_sha256}",
        )
        source_id = str(connector_source["id"])
        self.connectors.disable_source(connector_instance_id, source_id)
        now = utc_now()
        record = {
            "schema_version": GOOGLE_STATE_SCHEMA_VERSION,
            "source_id": source_id,
            "connector_instance_id": connector_instance_id,
            "capability": selected,
            "selection_kind": normalised_kind,
            "selectors": list(normalised_selectors),
            "selection_sha256": selection_sha256,
            "state": "disabled",
            "lifecycle_state": "active",
            "schedule": schedule_payload(mode="manual", timezone="UTC"),
            "cursor": {
                "revision": 1,
                "provider_cursor": None,
                "page_ordinal": 0,
                "page_fingerprints": [],
                "resync_required": False,
                "last_attempt_at": None,
                "last_success_at": None,
                "last_status": "not_run",
            },
            "health": {
                "status": "disabled",
                "code": "google_source_disabled",
                "checked_at": None,
            },
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._write_json(self.sources / f"{source_id}.json", record)
        return self.source_view(source_id, local=True)

    def _source_record(self, source_id: str) -> dict[str, Any]:
        selected = require_identifier(source_id, "source")
        path = self.sources / f"{selected}.json"
        if not path.is_file():
            raise GoogleContractError("google_payload_invalid", "Google Source was not found")
        value = self._read_json(path)
        if value.get("source_id") != selected:
            raise GoogleContractError(
                "google_payload_invalid", "Google Source state identity is invalid"
            )
        connector = self.connectors.get_source(str(value.get("connector_instance_id")), selected)
        if connector is None:
            raise GoogleContractError(
                "google_payload_invalid", "Google Source connector binding is missing"
            )
        return value

    def _write_source_record(self, value: Mapping[str, Any]) -> None:
        source_id = require_identifier(value.get("source_id"), "source")
        self._write_json(self.sources / f"{source_id}.json", value)

    def source_record(self, source_id: str, *, require_enabled: bool = False) -> dict[str, Any]:
        record = self._source_record(source_id)
        if record.get("lifecycle_state") == "removed":
            raise GoogleContractError("google_source_removed", "Google Source is removed")
        if require_enabled:
            if record.get("state") == "paused":
                raise GoogleContractError("google_source_paused", "Google Source is paused")
            if record.get("state") != "enabled":
                raise GoogleContractError("google_source_disabled", "Google Source is disabled")
        return record

    def source_view(self, source_id: str, *, local: bool = False) -> dict[str, Any]:
        record = self._source_record(source_id)
        connector = self.connectors.get_source(str(record["connector_instance_id"]), source_id)
        assert connector is not None
        selection = (
            {"kind": record["selection_kind"], "selectors": list(record["selectors"])}
            if local
            else {
                "kind": record["selection_kind"],
                "count": len(record["selectors"]),
                "sha256": record["selection_sha256"],
            }
        )
        return {
            "schema_version": GOOGLE_STATE_SCHEMA_VERSION,
            "id": source_id,
            "connector_instance_id": record["connector_instance_id"],
            "name": connector["name"],
            "capability": record["capability"],
            "selection": selection,
            "state": record["state"],
            "lifecycle_state": record["lifecycle_state"],
            "schedule": dict(record["schedule"]),
            "cursor": {
                key: value for key, value in record["cursor"].items() if key != "provider_cursor"
            }
            | {"provider_cursor_present": record["cursor"].get("provider_cursor") is not None},
            "health": dict(record["health"]),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "removed_at": record["removed_at"],
        }

    def list_sources(
        self,
        *,
        connector_instance_id: str | None = None,
        capability: str | None = None,
        local: bool = False,
        include_removed: bool = True,
    ) -> list[dict[str, Any]]:
        selected_capability = normalise_capability(capability) if capability else None
        if not self.sources.exists():
            return []
        result: list[dict[str, Any]] = []
        for path in sorted(self.sources.glob("src_*.json")):
            value = self.source_view(path.stem, local=local)
            if connector_instance_id and value["connector_instance_id"] != connector_instance_id:
                continue
            if selected_capability and value["capability"] != selected_capability:
                continue
            if not include_removed and value["lifecycle_state"] == "removed":
                continue
            result.append(value)
        return result

    def set_source_state(self, source_id: str, state: str) -> dict[str, Any]:
        if state not in GOOGLE_SOURCE_STATES:
            raise GoogleContractError(
                "google_payload_invalid", "Google Source state is unsupported"
            )
        record = self.source_record(source_id)
        if state == "enabled":
            self.capability_record(
                str(record["connector_instance_id"]),
                str(record["capability"]),
                require_enabled=True,
            )
            self.connectors.enable_source(str(record["connector_instance_id"]), source_id)
        else:
            self.connectors.disable_source(str(record["connector_instance_id"]), source_id)
        now = utc_now()
        updated = {
            **record,
            "state": state,
            "health": {
                "status": "ready" if state == "enabled" else state,
                "code": "network_not_attempted" if state == "enabled" else f"google_source_{state}",
                "checked_at": None,
            },
            "updated_at": now,
        }
        self._write_source_record(updated)
        return self.source_view(source_id, local=True)

    def configure_schedule(
        self,
        source_id: str,
        *,
        mode: str,
        interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        record = self.source_record(source_id)
        if mode not in GOOGLE_SCHEDULE_MODES:
            raise GoogleContractError(
                "google_payload_invalid", "Google Source schedule mode is unsupported"
            )
        if mode == "manual":
            selected_interval = None
        elif type(interval_seconds) is not int or not 60 <= interval_seconds <= 31_536_000:
            raise GoogleContractError(
                "google_payload_invalid", "Google Source interval is outside the closed range"
            )
        else:
            selected_interval = interval_seconds
        schedule = schedule_payload(
            mode=mode,
            timezone="UTC",
            interval_seconds=selected_interval,
        )
        updated = {
            **record,
            "schedule": schedule,
            "updated_at": utc_now(),
        }
        self._write_source_record(updated)
        return self.source_view(source_id, local=True)

    def update_cursor(
        self,
        source_id: str,
        *,
        cursor: Mapping[str, Any],
        health: Mapping[str, Any],
    ) -> None:
        record = self.source_record(source_id)
        self._write_source_record(
            {
                **record,
                "cursor": dict(cursor),
                "health": dict(health),
                "updated_at": utc_now(),
            }
        )

    def reset_cursor(self, source_id: str) -> dict[str, Any]:
        record = self.source_record(source_id)
        now = utc_now()
        cursor = {
            "revision": int(record["cursor"]["revision"]) + 1,
            "provider_cursor": None,
            "page_ordinal": 0,
            "page_fingerprints": [],
            "resync_required": True,
            "last_attempt_at": now,
            "last_success_at": record["cursor"].get("last_success_at"),
            "last_status": "reset",
        }
        self.update_cursor(
            source_id,
            cursor=cursor,
            health={
                "status": "resync_required",
                "code": "google_cursor_invalidated",
                "checked_at": now,
            },
        )
        return self.source_view(source_id, local=True)

    def remove_source(self, source_id: str) -> dict[str, Any]:
        record = self.source_record(source_id)
        self.connectors.remove_source(str(record["connector_instance_id"]), source_id)
        now = utc_now()
        self._write_source_record(
            {
                **record,
                "state": "disabled",
                "lifecycle_state": "removed",
                "health": {
                    "status": "removed",
                    "code": "google_source_removed",
                    "checked_at": now,
                },
                "removed_at": now,
                "updated_at": now,
            }
        )
        return self.source_view(source_id, local=True)

    def effective_execution_context(
        self, source_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        source = self.source_record(source_id, require_enabled=True)
        instance_id = str(source["connector_instance_id"])
        instance_record = self._instance_record(instance_id)
        capability = self.capability_record(
            instance_id, str(source["capability"]), require_enabled=True
        )
        connector = self.connectors.get_instance(instance_id)
        if connector is None or connector.get("lifecycle_state") == "removed":
            raise GoogleContractError(
                "google_source_removed", "Google connector instance is unavailable"
            )
        if not connector.get("enabled"):
            raise GoogleContractError(
                "google_network_disabled", "Google connector instance is disabled"
            )
        external_access = bool(
            self.store.read_config().get("network", {}).get("external_access", False)
        )
        if not external_access or connector.get("effective_network") != "explicit":
            raise GoogleContractError(
                "google_network_disabled", "Google network access is disabled"
            )
        if sorted(connector.get("allowed_origins", [])) != sorted(GOOGLE_ALLOWED_ORIGINS):
            raise GoogleContractError(
                "google_network_disabled", "Google endpoint allowlist is incomplete"
            )
        return instance_record, capability, source

    def configuration_fingerprints(self, source_id: str) -> dict[str, str | int]:
        source = self.source_record(source_id)
        instance = self._instance_record(str(source["connector_instance_id"]))
        capability = instance["capabilities"][source["capability"]]
        return {
            "source": source_fingerprint(source),
            "capability": capability_fingerprint(capability),
            "capability_revision": int(capability["revision"]),
            "cursor_revision": int(source["cursor"]["revision"]),
        }


__all__ = ["GOOGLE_SCHEDULE_MODES", "GoogleSourceManager"]
