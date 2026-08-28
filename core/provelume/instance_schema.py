from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CURRENT_INSTANCE_SCHEMA_VERSION = 2
LEGACY_INSTANCE_SCHEMA_VERSION = 1
INSTANCE_MANIFEST_SCHEMA_VERSION = 1
MIGRATION_RECEIPT_SCHEMA_VERSION = 1

DERIVED_STATE_POLICY = {
    "indexes": "rebuild",
    "library": "rebuild",
    "state_artifacts": "include",
}

MIGRATION_1_TO_2 = "instance-schema-1-to-2"


def build_instance_manifest(
    config: Mapping[str, Any],
    *,
    migrations: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    instance = config.get("instance")
    if not isinstance(instance, Mapping):
        raise ValueError("Instance configuration has no valid identity")
    instance_id = instance.get("id")
    created_at = instance.get("created_at")
    if not isinstance(instance_id, str) or not instance_id:
        raise ValueError("Instance configuration has no valid ID")
    if not isinstance(created_at, str) or not created_at:
        raise ValueError("Instance configuration has no valid creation time")
    return {
        "schema_version": INSTANCE_MANIFEST_SCHEMA_VERSION,
        "instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
        "instance": {
            "id": instance_id,
            "created_at": created_at,
        },
        "derived_state": dict(DERIVED_STATE_POLICY),
        "migrations": list(migrations or []),
    }


def manifest_validation_errors(
    value: Any,
    *,
    config: Mapping[str, Any],
) -> list[str]:
    if not isinstance(value, Mapping):
        return ["Instance manifest must be a JSON object"]
    errors: list[str] = []
    if value.get("schema_version") != INSTANCE_MANIFEST_SCHEMA_VERSION:
        errors.append("unsupported Instance manifest schema version")
    if value.get("instance_schema_version") != CURRENT_INSTANCE_SCHEMA_VERSION:
        errors.append("Instance manifest schema identity does not match this Core")

    config_instance = config.get("instance")
    manifest_instance = value.get("instance")
    if not isinstance(config_instance, Mapping) or not isinstance(
        manifest_instance, Mapping
    ):
        errors.append("Instance manifest identity is invalid")
    else:
        for key in ("id", "created_at"):
            if manifest_instance.get(key) != config_instance.get(key):
                errors.append(f"Instance manifest {key} does not match provelume.yml")

    if value.get("derived_state") != DERIVED_STATE_POLICY:
        errors.append("Instance manifest derived-state policy is unsupported")
    migrations = value.get("migrations")
    if not isinstance(migrations, list):
        errors.append("Instance manifest migrations must be a list")
    else:
        for migration in migrations:
            if not isinstance(migration, Mapping) or not all(
                isinstance(migration.get(key), str) and migration.get(key)
                for key in ("id", "applied_at", "receipt")
            ):
                errors.append("Instance manifest contains an invalid migration entry")
                break
    return errors
