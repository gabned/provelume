from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from provelume.cli import main
from provelume.connector_model import ConnectorConflictError, ConnectorError
from provelume.instance_validation import inspect_instance
from provelume.service import ProvelumeInstance


def _manifest(adapter_key: str = "fixture-web") -> dict[str, object]:
    return {
        "adapter_key": adapter_key,
        "adapter_version": "1.0.0",
        "display_name": "Synthetic safe web fixture",
        "provider": "provider-independent",
        "conformance_profile": "provelume.connector.v1",
        "adapter_protocol_version": 1,
        "capabilities": [
            "source_selection",
            "oauth2_pkce_authorization",
            "manual_read",
            "external_secret_authorization",
            "conditional_metadata",
        ],
        "authorization_modes": ["oauth2_pkce", "none", "external_secret"],
        "source_kinds": ["web"],
        "data_categories": ["source.metadata", "source.content"],
        "multi_instance": True,
        "network_access": "explicit_only",
    }


def _configured_instance(tmp_path: Path) -> tuple[ProvelumeInstance, dict[str, object]]:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    definition = instance.register_connector_definition(_manifest())
    return instance, definition


def test_multi_instance_connector_identity_and_sources_are_portable(
    tmp_path: Path,
) -> None:
    instance, definition = _configured_instance(tmp_path)
    first = instance.create_connector_instance(
        str(definition["id"]),
        name="Public research",
        provider_identity="public-web",
        network_mode="disabled",
        allowed_origins=["https://EXAMPLE.test:443/"],
    )
    second = instance.create_connector_instance(
        str(definition["id"]),
        name="Authenticated research",
        provider_identity="example-provider",
        account_identity="account-02",
        network_mode="explicit",
        allowed_origins=["https://api.example.test", "https://api.example.test/"],
        authorization_mode="external_secret",
        scopes=["content.read", "content.read"],
        credential_reference={
            "kind": "environment",
            "name": "PROVELUME_FIXTURE_TOKEN",
        },
    )
    first_source = instance.add_connector_source(
        str(first["id"]),
        name="Documentation",
        source_kind="web",
        external_id="https://example.test/docs",
    )
    second_source = instance.add_connector_source(
        str(second["id"]),
        name="Account knowledge",
        source_kind="web",
        external_id="workspace:knowledge",
    )

    assert first["id"] != second["id"]
    assert first_source["id"] != second_source["id"]
    assert first["allowed_origins"] == ["https://example.test"]
    assert second["allowed_origins"] == ["https://api.example.test"]
    assert second["scopes"] == ["content.read"]
    assert second["effective_network"] == "disabled"
    assert (
        instance.add_connector_source(
            str(second["id"]),
            name="Ignored rename",
            source_kind="web",
            external_id="workspace:knowledge",
        )["id"]
        == second_source["id"]
    )

    inventory = instance.connector_inventory()
    assert inventory["summary"] == {
        "definitions": 1,
        "instances": 2,
        "sources": 2,
        "network_attempted": False,
    }
    assert instance.instance_summary()["network"]["configured_external_providers"] == 2
    assert {item["provider_identity"] for item in inventory["instances"]} == {
        "public-web",
        "example-provider",
    }
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    assert ProvelumeInstance(instance.root).connector_inventory() == inventory

    bundle = instance.export_portable(tmp_path / "connector-instance.zip")
    assert bundle["status"] == "completed"
    target = ProvelumeInstance.initialise(tmp_path / "target")
    imported = target.import_portable(tmp_path / "connector-instance.zip")
    assert imported["status"] == "imported"
    assert target.connector_inventory() == inventory


def test_connector_declarations_are_network_transparent_and_secret_free(
    tmp_path: Path,
) -> None:
    instance, definition = _configured_instance(tmp_path)
    created = instance.create_connector_instance(
        str(definition["id"]),
        name="External fixture",
        provider_identity="fixture-provider",
        network_mode="explicit",
        allowed_origins=["https://service.example.test"],
        authorization_mode="external_secret",
        scopes=["content.read"],
        credential_reference={
            "kind": "system_keyring",
            "name": "provelume:fixture",
        },
    )

    status = instance.network_status()
    connector = next(
        item for item in status["components"] if item["id"] == f"connector.{created['id']}"
    )
    assert status["network_used"] is False
    assert status["status"] == "attention"
    assert connector == {
        "id": f"connector.{created['id']}",
        "category": "connector",
        "type": "fixture-web",
        "enabled": True,
        "network_capability": "external",
        "declaration_state": "declared",
        "endpoint": "https://service.example.test",
        "data_categories": ["source.content", "source.metadata"],
        "observed_activity": "not_instrumented",
        "allowed_origins": ["https://service.example.test"],
        "authorization_mode": "external_secret",
        "configured_enabled": True,
        "lifecycle_state": "active",
        "health": "policy_blocked",
    }
    assert "external_component_blocked_by_policy" in {item["code"] for item in status["conflicts"]}
    rendered = json.dumps(status)
    assert "provelume:fixture" not in rendered
    assert "credential" not in rendered


def test_connector_sources_do_not_create_false_filesystem_health_findings(
    tmp_path: Path,
) -> None:
    instance, definition = _configured_instance(tmp_path)
    connector = instance.create_connector_instance(
        str(definition["id"]),
        name="Configuration-only fixture",
        provider_identity="fixture-provider",
    )
    source = instance.add_connector_source(
        str(connector["id"]),
        name="Configured web Source",
        source_kind="web",
        external_id="fixture:configured",
    )
    instance.rebuild_index()

    health = instance.knowledge_health()
    source_view = instance.get_source(str(source["id"]))
    assert health["status"] == "healthy"
    assert "source_missing" not in {item["code"] for item in health["problems"]}
    assert source_view is not None
    assert source_view["available"] is False
    assert source_view["availability_status"] == "configuration_only"
    assert instance.instance_summary()["knowledge_status"] == "healthy"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"token": "secret"}), "unsupported fields"),
        (lambda value: value.update({"multi_instance": False}), "multi-instance"),
        (
            lambda value: value.update({"capabilities": ["provider_write"]}),
            "unsupported value",
        ),
        (
            lambda value: value.update({"adapter_protocol_version": 99}),
            "protocol version",
        ),
        (
            lambda value: value.update({"adapter_protocol_version": True}),
            "protocol version",
        ),
    ],
)
def test_manifest_validation_fails_closed(
    tmp_path: Path,
    mutate: object,
    message: str,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manifest = _manifest()
    mutate(manifest)  # type: ignore[operator]
    with pytest.raises(ConnectorError, match=message):
        instance.register_connector_definition(manifest)
    assert instance.connector_inventory()["status"] == "empty"


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:secret@example.test",
        "https://example.test/private",
        "file:///tmp/private",
        "https://example.test?token=secret",
        "https://updates_example.test",
    ],
)
def test_connector_origin_policy_accepts_only_canonical_http_origins(
    tmp_path: Path,
    origin: str,
) -> None:
    instance, definition = _configured_instance(tmp_path)
    with pytest.raises(ConnectorError, match="origin"):
        instance.create_connector_instance(
            str(definition["id"]),
            name="Unsafe",
            provider_identity="fixture",
            network_mode="explicit",
            allowed_origins=[origin],
        )


def test_external_secret_references_never_accept_inline_secret_material(
    tmp_path: Path,
) -> None:
    instance, definition = _configured_instance(tmp_path)
    with pytest.raises(ConnectorError, match="only external kind and name"):
        instance.create_connector_instance(
            str(definition["id"]),
            name="Unsafe secret",
            provider_identity="fixture",
            authorization_mode="external_secret",
            credential_reference={
                "kind": "environment",
                "name": "PROVELUME_TOKEN",
                "value": "never-store-this",
            },
        )
    assert "never-store-this" not in json.dumps(instance.connector_inventory())


def test_definition_conflict_and_deep_reference_tampering_are_visible(
    tmp_path: Path,
) -> None:
    instance, definition = _configured_instance(tmp_path)
    changed = _manifest()
    changed["adapter_version"] = "1.0.1"
    with pytest.raises(ConnectorConflictError, match="different content"):
        instance.register_connector_definition(changed)

    connector = instance.create_connector_instance(
        str(definition["id"]),
        name="Fixture",
        provider_identity="fixture",
    )
    instance.add_connector_source(
        str(connector["id"]),
        name="Fixture Source",
        source_kind="web",
        external_id="fixture:source",
    )
    definition_path = (
        instance.store.paths.canonical_dir("connector-definitions") / f"{definition['id']}.json"
    )
    definition_path.unlink()

    report = inspect_instance(instance.root, deep=True)
    assert report["status"] == "invalid"
    assert "connector_definition_missing" in {item["code"] for item in report["errors"]}


def test_connector_directories_are_additive_for_existing_schema_two_instances(
    tmp_path: Path,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    shutil.rmtree(instance.store.paths.canonical_dir("connector-definitions"))
    shutil.rmtree(instance.store.paths.canonical_dir("connector-instances"))
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    definition = instance.register_connector_definition(_manifest())
    assert definition["id"] == "connector_definition_fixture-web"
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_connector_cli_is_local_deterministic_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manifest_path = tmp_path / "connector.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    root = str(instance.root)

    assert main(["connector-definition-register", root, str(manifest_path)]) == 0
    definition = json.loads(capsys.readouterr().out)
    assert definition["id"] == "connector_definition_fixture-web"
    assert definition["network_attempted"] is False

    assert (
        main(
            [
                "connector-instance-create",
                root,
                definition["id"],
                "--name",
                "CLI connector",
                "--provider-identity",
                "fixture-provider",
                "--network-mode",
                "explicit",
                "--origin",
                "https://example.test",
                "--authorization-mode",
                "external_secret",
                "--scope",
                "content.read",
                "--secret-ref-kind",
                "environment",
                "--secret-ref-name",
                "PROVELUME_CLI_TOKEN",
            ]
        )
        == 0
    )
    connector = json.loads(capsys.readouterr().out)
    assert connector["network_attempted"] is False

    assert (
        main(
            [
                "connector-source-add",
                root,
                connector["id"],
                "--name",
                "CLI Source",
                "--source-kind",
                "web",
                "--external-id",
                "https://example.test/article",
            ]
        )
        == 0
    )
    source = json.loads(capsys.readouterr().out)
    assert source["connector_instance_id"] == connector["id"]
    assert source["network_attempted"] is False

    assert main(["connector-inventory", root]) == 0
    inventory = json.loads(capsys.readouterr().out)
    assert inventory["network_attempted"] is False
    assert inventory["summary"]["instances"] == 1
    assert inventory["summary"]["sources"] == 1
    assert inventory["summary"]["network_attempted"] is False

    assert (
        main(
            [
                "connector-instance-create",
                root,
                definition["id"],
                "--name",
                "Broken",
                "--provider-identity",
                "fixture",
                "--authorization-mode",
                "external_secret",
                "--secret-ref-kind",
                "environment",
            ]
        )
        == 2
    )
    error = json.loads(capsys.readouterr().out)
    assert error["network_attempted"] is False
