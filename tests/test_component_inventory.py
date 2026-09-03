from __future__ import annotations

import copy
import json
import socket
from importlib.resources import files
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.component_inventory import ComponentInventory, ComponentInventoryError
from provelume.service import ProvelumeInstance
from provelume.web import create_app

VERSIONS = {
    "provelume": "0.9.0",
    "fastapi": "0.141.1",
    "jinja2": "3.1.6",
    "pypdf": "6.16.2",
    "pyyaml": "6.0.3",
    "tzdata": "2026.3",
    "uvicorn": "0.52.4",
}


def _catalogue() -> dict:
    return json.loads(files("provelume").joinpath("component_catalogue.json").read_text("utf-8"))


def _inventory(**kwargs) -> ComponentInventory:
    return ComponentInventory(
        distribution_versions=VERSIONS,
        executable_present=lambda _name: False,
        python_version="3.12.13",
        platform_name="windows",
        **kwargs,
    )


def test_inventory_covers_component_classes_and_keeps_states_distinct() -> None:
    result = _inventory().read()
    rows = {row["id"]: row for row in result["components"]}

    assert result["schema_version"] == 1
    assert result["network"] == {
        "used": False,
        "catalogue_check": "not_performed",
        "automatic_update": False,
    }
    assert result["mutated"] is False
    assert {row["category"] for row in result["class_coverage"]} == {
        "first_party",
        "python_package",
        "native_tool",
        "codec",
        "model",
        "language_pack",
        "host_prerequisite",
    }
    assert rows["provelume.core"]["status"] == "installed"
    assert rows["runtime.cpython"]["status"] == "installed"
    assert rows["ocr.tesseract"]["status"] == "missing"
    assert rows["ocr.eng-traineddata"]["status"] == "unverified"
    assert all(row["local_path_redacted"] is True for row in rows.values())
    assert all(row["license"] and row["notices"] for row in rows.values())
    assert all(row["latest_known_version"] is None for row in rows.values())
    assert all(row["security_status"] == "unverified" for row in rows.values())


def test_ahead_eol_and_present_without_version_do_not_become_approved() -> None:
    catalogue = copy.deepcopy(_catalogue())
    by_id = {row["id"]: row for row in catalogue["components"]}
    by_id["python.fastapi"]["version_constraint"] = ">=0.115,<0.140"
    by_id["python.jinja2"]["eol"] = True
    result = ComponentInventory(
        catalogue=catalogue,
        distribution_versions=VERSIONS,
        executable_present=lambda name: name == "tesseract",
        python_version="3.12.13",
        platform_name="linux",
    ).read()
    rows = {row["id"]: row for row in result["components"]}

    assert rows["python.fastapi"]["status"] == "ahead"
    assert rows["python.jinja2"]["status"] == "eol"
    assert rows["ocr.tesseract"]["status"] == "unverified"
    assert rows["ocr.tesseract"]["effective_version"] == "unknown"


def test_installed_transitive_runtime_dependency_closure_enters_inventory_and_sbom(
    tmp_path: Path,
) -> None:
    versions = {
        **VERSIONS,
        "starlette": "1.6.0",
        "anyio": "4.15.0",
        "pydantic": "2.13.5",
    }
    dependencies = {
        "provelume": ["fastapi>=0.115", "pytest>=8; extra == 'dev'"],
        "fastapi": ["starlette>=0.46", "pydantic>=2.9"],
        "starlette": ["anyio>=3.6"],
    }
    inventory = ComponentInventory(
        distribution_versions=versions,
        distribution_dependencies=dependencies,
        distribution_licenses={
            "starlette": "BSD-3-Clause",
            "anyio": "MIT",
            "pydantic": "MIT",
        },
        executable_present=lambda _name: False,
        python_version="3.12.13",
        platform_name="linux",
    )
    rows = {row["id"]: row for row in inventory.read()["components"]}
    assert set(rows).issuperset(
        {
            "python.transitive.starlette",
            "python.transitive.anyio",
            "python.transitive.pydantic",
        }
    )
    assert not any("pytest" in identifier for identifier in rows)
    assert rows["python.transitive.starlette"]["dependency_relation"] == "runtime_transitive"
    assert rows["python.transitive.starlette"]["license"] == "BSD-3-Clause"

    sbom = tmp_path / "transitive.cdx.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "components": [
                    {
                        "type": "library",
                        "name": name,
                        "version": version,
                        "purl": f"pkg:pypi/{name}@{version}",
                    }
                    for name, version in versions.items()
                ],
            }
        ),
        encoding="utf-8",
    )
    assert inventory.read(release_sbom=sbom)["release_evidence"]["status"] == "matched"


def test_release_sbom_reconciliation_is_bounded_and_deterministic(tmp_path: Path) -> None:
    sbom = tmp_path / "bom.cdx.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "version": 1,
                "components": [
                    {"name": name, "version": version, "type": "library"}
                    for name, version in VERSIONS.items()
                ],
            }
        ),
        encoding="utf-8",
    )
    inventory = _inventory()
    first = inventory.read(release_sbom=sbom)
    second = inventory.read(release_sbom=sbom)
    assert first == second
    assert first["release_evidence"]["status"] == "matched"
    assert len(first["release_evidence"]["sbom_sha256"]) == 64

    payload = json.loads(sbom.read_text("utf-8"))
    payload["components"] = [row for row in payload["components"] if row["name"] != "fastapi"]
    sbom.write_text(json.dumps(payload), encoding="utf-8")
    mismatch = inventory.read(release_sbom=sbom)
    assert mismatch["release_evidence"]["status"] == "mismatch"
    assert mismatch["release_evidence"]["mismatched_component_ids"] == ["python.fastapi"]

    sbom.write_text('{"bomFormat":"SPDX","components":[]}', encoding="utf-8")
    with pytest.raises(ComponentInventoryError) as caught:
        inventory.read(release_sbom=sbom)
    assert caught.value.code == "component_sbom_invalid"


def test_cli_api_and_bilingual_browser_share_one_offline_read_model(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    def reject_network(*_args, **_kwargs):
        raise AssertionError("network activity is forbidden")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    root = tmp_path / "instance"
    ProvelumeInstance.initialise(root)
    config_before = (root / "provelume.yml").read_bytes()

    assert main(["component-inventory"]) == 0
    cli = json.loads(capsys.readouterr().out)

    client = TestClient(create_app(root))
    api = client.get("/api/v1/components")
    assert api.status_code == 200
    assert api.json() == cli
    assert client.post("/api/v1/components", json={}).status_code == 405

    english = client.get("/components")
    assert english.status_code == 200
    assert "Component catalogue" in english.text
    assert "No catalogue, advisory" in english.text

    italian = client.get("/components", params={"lang": "it"})
    assert italian.status_code == 200
    assert "Catalogo dei componenti" in italian.text
    assert "Non è stata eseguita" in italian.text
    for untranslated in (
        "first_party",
        "installed_version_within_declared_contract",
        "verified_release",
    ):
        assert untranslated not in italian.text
    assert str(tmp_path) not in english.text
    assert str(tmp_path) not in italian.text
    assert (root / "provelume.yml").read_bytes() == config_before


def test_component_documentation_and_schema_are_packaged() -> None:
    root = Path(__file__).parents[1]
    for path in (
        root / "docs" / "components.md",
        root / "docs" / "components.it.md",
        root / "docs" / "adr" / "0022-installed-and-release-component-inventory.md",
        root / "core" / "provelume" / "component_inventory.schema.json",
    ):
        assert path.is_file()
    english = (root / "docs" / "components.md").read_text("utf-8")
    italian = (root / "docs" / "components.it.md").read_text("utf-8")
    schema = json.loads(
        (root / "core" / "provelume" / "component_inventory.schema.json").read_text("utf-8")
    )
    assert "never installs or updates" in english
    assert "non installa né aggiorna" in italian
    assert schema["additionalProperties"] is False
    assert schema["properties"]["components"]["items"] == {"$ref": "#/$defs/component"}
    assert schema["$defs"]["component"]["additionalProperties"] is False
    assert "status" in schema["$defs"]["component"]["required"]
    assert "GITHUB_TOKEN" not in _inventory().export_bytes().decode("utf-8")
