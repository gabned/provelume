from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.connectors import ConnectorConflictError
from provelume.domain import Acquisition, Document, DocumentVersion
from provelume.instance_validation import inspect_instance
from provelume.service import ProvelumeInstance
from provelume.storage import utc_now
from provelume.web import create_app


def _manifest() -> dict[str, object]:
    return {
        "adapter_key": "fixture-web",
        "adapter_version": "1.0.0",
        "display_name": "Synthetic web fixture",
        "provider": "provider-independent",
        "conformance_profile": "provelume.connector.v1",
        "adapter_protocol_version": 1,
        "capabilities": [
            "conditional_metadata",
            "external_secret_authorization",
            "manual_read",
            "source_selection",
        ],
        "authorization_modes": ["external_secret", "none"],
        "source_kinds": ["web"],
        "data_categories": ["source.content", "source.metadata"],
        "multi_instance": True,
        "network_access": "explicit_only",
    }


def _configured(tmp_path: Path) -> tuple[ProvelumeInstance, dict[str, object]]:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    definition = instance.register_connector_definition(_manifest())
    return instance, definition


def _attach_original(
    instance: ProvelumeInstance,
    source_id: str,
) -> tuple[str, str, str, bytes]:
    data = b"exact connector Original bytes"
    original = instance.store.store_original_bytes(data)
    suffix = uuid4().hex
    document_id = f"doc_{suffix}"
    version_id = f"ver_{suffix}"
    acquisition_id = f"acq_{suffix}"
    now = utc_now()
    instance.store.write_version(
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            sequence=1,
            content_hash=original.sha256,
            original_id=original.id,
            media_type="text/plain",
            size_bytes=len(data),
            acquired_at=now,
        )
    )
    instance.store.write_document(
        Document(
            id=document_id,
            source_id=source_id,
            locator="https://example.test/article",
            title="Preserved article",
            media_type="text/plain",
            created_at=now,
            current_version_id=version_id,
        )
    )
    instance.store.write_acquisition(
        Acquisition(
            id=acquisition_id,
            source_id=source_id,
            locator="https://example.test/article",
            observed_at=now,
            content_hash=original.sha256,
            outcome="created",
            document_id=document_id,
            version_id=version_id,
        )
    )
    return original.id, document_id, acquisition_id, data


def test_multi_instance_updates_and_health_remain_isolated(tmp_path: Path) -> None:
    instance, definition = _configured(tmp_path)
    first = instance.create_connector_instance(
        str(definition["id"]),
        name="First account",
        provider_identity="provider-one",
        account_identity="account-one",
        endpoint="https://one.example.test",
        network_mode="explicit",
        allowed_origins=["https://one.example.test"],
        authorization_mode="external_secret",
        scopes=["content.read"],
        credential_reference={"kind": "environment", "name": "FIRST_TOKEN"},
    )
    second = instance.create_connector_instance(
        str(definition["id"]),
        name="Second account",
        provider_identity="provider-two",
        account_identity="account-two",
        endpoint="https://two.example.test",
        allowed_origins=["https://two.example.test"],
        authorization_mode="external_secret",
        scopes=["metadata.read"],
        credential_reference={"kind": "system_keyring", "name": "provelume:second"},
    )
    second_before = instance.get_connector_instance(str(second["id"]))

    updated = instance.update_connector_instance(
        str(first["id"]),
        name="First account updated",
        provider_identity="provider-one-next",
        account_identity=None,
        endpoint="https://next.example.test",
        allowed_origins=["https://next.example.test"],
        scopes=["content.read", "metadata.read"],
        credential_reference={"kind": "environment", "name": "FIRST_TOKEN_NEXT"},
    )
    disabled = instance.disable_connector_instance(str(first["id"]))

    assert updated["endpoint"] == "https://next.example.test"
    assert updated["account_identity"] is None
    assert updated["scopes"] == ["content.read", "metadata.read"]
    assert updated["cursors"] == {}
    assert disabled["health"]["status"] == "disabled"
    assert disabled["effective_network"] == "disabled"
    assert instance.get_connector_instance(str(second["id"])) == second_before
    assert second_before is not None
    assert second_before["credential_reference"] == {
        "kind": "system_keyring",
        "name": "provelume:second",
    }
    assert second_before["health"]["status"] == "not_checked"
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_selected_source_lifecycle_changes_are_isolated(tmp_path: Path) -> None:
    instance, definition = _configured(tmp_path)
    connector = instance.create_connector_instance(
        str(definition["id"]),
        name="Source isolation",
        provider_identity="fixture-provider",
    )
    first = instance.add_connector_source(
        str(connector["id"]),
        name="First Source",
        source_kind="web",
        external_id="fixture:first",
    )
    second = instance.add_connector_source(
        str(connector["id"]),
        name="Second Source",
        source_kind="web",
        external_id="fixture:second",
    )

    instance.update_connector_source(
        str(connector["id"]),
        str(first["id"]),
        name="First Source updated",
    )
    disabled = instance.disable_connector_source(
        str(connector["id"]),
        str(first["id"]),
    )
    second_after = instance.get_connector_source(
        str(connector["id"]),
        str(second["id"]),
    )

    assert disabled["name"] == "First Source updated"
    assert disabled["effective_enabled"] is False
    assert second_after is not None
    assert second_after["name"] == "Second Source"
    assert second_after["effective_enabled"] is True

    instance.remove_connector_source(str(connector["id"]), str(first["id"]))
    assert (
        instance.get_connector_source(str(connector["id"]), str(second["id"]))
        == second_after
    )
    with pytest.raises(ConnectorConflictError, match="removed independently"):
        instance.remove_connector_instance(str(connector["id"]))
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_source_and_instance_removal_preserve_acquired_originals_and_evidence(
    tmp_path: Path,
) -> None:
    instance, definition = _configured(tmp_path)
    connector = instance.create_connector_instance(
        str(definition["id"]),
        name="Private fixture",
        provider_identity="private-provider",
        account_identity="private-account",
        endpoint="https://private.example.test",
        allowed_origins=["https://private.example.test"],
        authorization_mode="external_secret",
        scopes=["content.read"],
        credential_reference={"kind": "environment", "name": "PRIVATE_TOKEN_REF"},
    )
    source = instance.add_connector_source(
        str(connector["id"]),
        name="Selected articles",
        source_kind="web",
        external_id="workspace:private",
    )
    original_id, document_id, acquisition_id, original_bytes = _attach_original(
        instance,
        str(source["id"]),
    )

    instance.disable_connector_source(str(connector["id"]), str(source["id"]))
    instance.disable_connector_instance(str(connector["id"]))
    with pytest.raises(ConnectorConflictError, match="removed independently"):
        instance.remove_connector_instance(str(connector["id"]))
    removed_source = instance.remove_connector_source(
        str(connector["id"]),
        str(source["id"]),
    )
    removed_instance = instance.remove_connector_instance(str(connector["id"]))

    assert removed_source["lifecycle_state"] == "removed"
    assert removed_instance["lifecycle_state"] == "removed"
    assert instance.store.original_bytes(original_id) == original_bytes
    assert instance.store.read_canonical("documents", document_id) is not None
    assert instance.store.read_canonical("acquisitions", acquisition_id) is not None
    assert instance.store.read_canonical("sources", str(source["id"])) is not None
    assert (
        instance.store.read_canonical("connector-instances", str(connector["id"]))
        is not None
    )
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    operations = instance.connectors.operations.list(limit=100)
    rendered = json.dumps(operations)
    assert "PRIVATE_TOKEN_REF" not in rendered
    assert "private-account" not in rendered
    assert "private.example.test" not in rendered
    assert str(tmp_path) not in rendered
    removals = [
        item
        for item in operations
        if item["kind"] in {"connector.source.remove", "connector.instance.remove"}
        and item["status"] == "completed"
    ]
    assert len(removals) == 2
    assert all(item["metrics"]["originals_deleted"] == 0 for item in removals)
    assert all(item["metrics"]["originals_overwritten"] == 0 for item in removals)


def test_service_cli_api_and_browser_share_read_contracts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance, definition = _configured(tmp_path)
    connector = instance.create_connector_instance(
        str(definition["id"]),
        name="Aligned account",
        provider_identity="fixture-provider",
        endpoint="https://aligned.example.test",
        allowed_origins=["https://aligned.example.test"],
    )
    source = instance.add_connector_source(
        str(connector["id"]),
        name="Aligned Source",
        source_kind="web",
        external_id="fixture:aligned",
    )
    expected_connector = instance.get_connector_instance(str(connector["id"]))
    expected_source = instance.get_connector_source(
        str(connector["id"]),
        str(source["id"]),
    )

    assert (
        main(
            [
                "connector-instance-show",
                str(instance.root),
                str(connector["id"]),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == expected_connector
    assert (
        main(
            [
                "connector-source-show",
                str(instance.root),
                str(connector["id"]),
                str(source["id"]),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == expected_source

    client = TestClient(create_app(instance.root))
    assert client.get("/api/v1/connectors").json() == instance.connector_inventory()
    assert (
        client.get(f"/api/v1/connectors/{connector['id']}").json()
        == expected_connector
    )
    assert (
        client.get(
            f"/api/v1/connectors/{connector['id']}/sources/{source['id']}"
        ).json()
        == expected_source
    )
    assert client.post("/api/v1/connectors", json={}).status_code == 405

    english = client.get(f"/connectors/{connector['id']}")
    italian = client.get("/connectors", params={"lang": "it"})
    source_page = client.get(
        f"/connectors/{connector['id']}/sources/{source['id']}",
        params={"lang": "it"},
    )
    assert english.status_code == italian.status_code == source_page.status_code == 200
    assert "Aligned account" in english.text
    assert "No cursor has been created" in english.text
    assert "Istanze dei connettori" in italian.text
    assert "Original acquisito" in source_page.text
    assert 'href="https://aligned.example.test"' not in english.text
    assert 'src="https://aligned.example.test"' not in english.text


def test_legacy_s01_records_remain_valid_and_upgrade_on_mutation(
    tmp_path: Path,
) -> None:
    instance, definition = _configured(tmp_path)
    now = utc_now()
    instance_id = f"connector_instance_{uuid4().hex}"
    source_id = f"src_{uuid4().hex}"
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("connector-instances")
        / f"{instance_id}.json",
        {
            "schema_version": 1,
            "id": instance_id,
            "definition_id": definition["id"],
            "name": "Legacy account",
            "provider_identity": "legacy-provider",
            "account_identity": None,
            "network_mode": "disabled",
            "allowed_origins": ["https://legacy.example.test"],
            "authorization_mode": "none",
            "scopes": [],
            "credential_reference": None,
            "created_at": now,
            "updated_at": now,
        },
    )
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("sources") / f"{source_id}.json",
        {
            "schema_version": 1,
            "id": source_id,
            "kind": "connector",
            "name": "Legacy Source",
            "created_at": now,
            "connector_instance_id": instance_id,
            "source_kind": "web",
            "external_id": "legacy:source",
        },
    )

    legacy = instance.get_connector_instance(instance_id)
    assert legacy is not None
    assert legacy["endpoint"] == "https://legacy.example.test"
    assert legacy["lifecycle_state"] == "active"
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    instance.update_connector_instance(instance_id, name="Upgraded account")
    instance.update_connector_source(instance_id, source_id, name="Upgraded Source")
    upgraded_instance = instance.store.read_canonical(
        "connector-instances",
        instance_id,
    )
    upgraded_source = instance.store.read_canonical("sources", source_id)
    assert upgraded_instance is not None and upgraded_instance["schema_version"] == 2
    assert upgraded_source is not None and upgraded_source["schema_version"] == 2
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
