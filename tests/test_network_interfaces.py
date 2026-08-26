from __future__ import annotations

import json
import socket
from pathlib import Path

from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def test_network_status_cli_api_and_browser_are_read_only_and_local(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    root = tmp_path / "instance"
    source = tmp_path / "sensitive-source"
    source.mkdir()
    instance = ProvelumeInstance.initialise(root, name="Network transparency")
    instance.store.register_source_path("local", source, name="Local files")
    config_before = instance.store.paths.config.read_bytes()

    def reject_network(*_args, **_kwargs):
        raise AssertionError("network activity is forbidden")

    monkeypatch.setattr(socket, "create_connection", reject_network)

    assert main(["network-status", str(root)]) == 0
    cli_result = json.loads(capsys.readouterr().out)
    assert cli_result["status"] == "local_only"
    assert cli_result["network_used"] is False

    client = TestClient(create_app(root))
    api = client.get("/api/v1/security/network")
    assert api.status_code == 200
    assert api.json() == cli_result
    assert client.post("/api/v1/security/network", json={}).status_code == 405

    english = client.get("/security/network")
    assert english.status_code == 200
    assert "Privacy &amp; Network Activity" in english.text
    assert "Local only" in english.text
    assert "Not instrumented" in english.text
    assert str(source) not in english.text
    assert 'href="http' not in english.text.lower()
    assert 'src="http' not in english.text.lower()

    italian = client.get("/security/network", params={"lang": "it"})
    assert italian.status_code == 200
    assert "Privacy e attività di rete" in italian.text
    assert "Solo locale" in italian.text
    assert "Non strumentata" in italian.text

    assert instance.store.paths.config.read_bytes() == config_before


def test_network_status_interfaces_expose_conflicts_without_false_traffic_claims(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root)
    config = instance.store.read_config()
    config["network"]["update_checks"] = True
    instance.store.write_config(config)

    assert main(["network-status", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "attention"
    assert payload["observed_activity"]["status"] == "not_instrumented"
    assert {item["code"] for item in payload["conflicts"]} == {
        "missing_external_endpoint",
        "external_component_blocked_by_policy",
    }

    page = TestClient(create_app(root)).get("/security/network")
    assert "Configuration needs attention" in page.text
    assert "missing_external_endpoint" in page.text
    assert "not_instrumented" not in page.text


def test_malformed_network_registry_remains_visible_across_interfaces(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root)
    config = instance.store.read_config()
    config["network"] = []
    instance.store.write_config(config)
    config_before = instance.store.paths.config.read_bytes()

    assert main(["network-status", str(root)]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["status"] == "attention"
    assert cli_payload["conflicts"][0]["component_id"] == "registry.network"

    client = TestClient(create_app(root))
    api = client.get("/api/v1/security/network")
    assert api.status_code == 200
    assert api.json() == cli_payload

    page = client.get("/security/network")
    assert page.status_code == 200
    assert "invalid_component_registry" in page.text
    assert instance.store.paths.config.read_bytes() == config_before
