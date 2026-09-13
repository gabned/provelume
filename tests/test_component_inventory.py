from __future__ import annotations

import copy
import json
import shutil
import socket
from importlib.resources import files
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume import cura_icons
from provelume.cli import main
from provelume.component_inventory import ComponentInventory, ComponentInventoryError
from provelume.cura_icons import asset_sbom_component
from provelume.service import ProvelumeInstance
from provelume.web import create_app

VERSIONS = {
    "provelume": "0.10.1",
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

    assert result["schema_version"] == 2
    assert result["catalogue_version"] == 2
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
        "ui_asset",
    }
    assert rows["provelume.core"]["status"] == "installed"
    assert rows["provelume.core"]["pinned"] is True
    assert rows["python.fastapi"]["pinned"] is False
    assert rows["runtime.cpython"]["status"] == "installed"
    assert rows["ui.lucide"]["status"] == "installed"
    assert rows["ui.lucide"]["effective_version"] == "1.45.0"
    assert rows["ui.lucide"]["license"] == "ISC AND MIT"
    assert rows["ui.lucide"]["evidence"] == "packaged_asset_sha256_verified"
    assert rows["ocr.tesseract"]["status"] == "missing"
    assert rows["ocr.eng-traineddata"]["status"] == "unverified"
    assert rows["asr.whisper-cpp"]["approved_version"] == "1.9.2"
    assert rows["asr.whisper-cpp"]["status"] == "unverified"
    assert rows["model.whisper-tiny-q5-1"]["expected_sha256"] == (
        "818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7"
    )
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


def test_dated_latest_and_security_evidence_can_be_current_or_stale() -> None:
    result = _inventory(
        upstream_evidence={
            "python.fastapi": {
                "latest_known_version": "0.142.0",
                "status": "stale",
                "checked_at": "2026-08-01T00:00:00+00:00",
                "source": "allowlisted-catalogue-fixture",
                "security_status": "action_required",
            }
        }
    ).read()
    row = next(item for item in result["components"] if item["id"] == "python.fastapi")
    assert row["latest_known_version"] == "0.142.0"
    assert row["latest_check"]["status"] == "stale"
    assert row["security_status"] == "action_required"

    with pytest.raises(ComponentInventoryError, match="cannot make claims"):
        _inventory(
            upstream_evidence={
                "python.fastapi": {
                    "latest_known_version": "0.142.0",
                    "status": "not_checked",
                    "checked_at": None,
                    "source": None,
                    "security_status": "unverified",
                }
            }
        ).read()


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
                ]
                + [asset_sbom_component()],
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
                ]
                + [asset_sbom_component()],
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

    client = TestClient(create_app(root, shell_settings_file=tmp_path / "shell-settings.json"))
    api = client.get("/api/v1/components")
    assert api.status_code == 200
    assert api.json() == cli
    assert client.post("/api/v1/components", json={}).status_code == 405

    english = client.get("/components", params={"lang": "en"})
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
    assert "pinned" in schema["$defs"]["component"]["required"]
    assert "GITHUB_TOKEN" not in _inventory().export_bytes().decode("utf-8")


@pytest.mark.parametrize("field", ["hash", "commit", "asset_bytes", "license", "duplicate"])
def test_packaged_asset_sbom_rejects_same_version_different_provenance(
    tmp_path: Path,
    field: str,
) -> None:
    asset = asset_sbom_component()
    rows = [
        {"name": name, "version": version, "type": "library"} for name, version in VERSIONS.items()
    ] + [asset]
    if field == "hash":
        asset["hashes"][0]["content"] = "0" * 64
    elif field in {"commit", "asset_bytes"}:
        key = "provelume:source-commit" if field == "commit" else "provelume:asset-sha256:house.svg"
        next(row for row in asset["properties"] if row["name"] == key)["value"] = "different"
    elif field == "license":
        asset["licenses"] = [{"expression": "MIT"}]
    else:
        rows.append(copy.deepcopy(asset))
    sbom = tmp_path / "asset-mismatch.cdx.json"
    sbom.write_text(json.dumps({"bomFormat": "CycloneDX", "components": rows}), "utf-8")
    result = _inventory().read(release_sbom=sbom)
    assert result["release_evidence"]["mismatched_component_ids"] == ["ui.lucide"]
    row = next(row for row in result["components"] if row["id"] == "ui.lucide")
    assert row["effective_version"] == "1.45.0"
    assert row["release_evidence"] == "mismatch"


@pytest.mark.parametrize(
    "change,state,reason",
    [
        ("missing", "missing", "packaged_asset_missing"),
        ("tampered", "unverified", "packaged_asset_invalid"),
    ],
)
def test_packaged_detection_requires_actual_intact_resources(
    tmp_path: Path,
    monkeypatch,
    change: str,
    state: str,
    reason: str,
) -> None:
    root = tmp_path / "assets"
    shutil.copytree(Path(str(files("provelume").joinpath(cura_icons.RESOURCE_PATH))), root)
    notice = tmp_path / "lucide-LICENSE.txt"
    shutil.copyfile(
        Path(str(files("provelume").joinpath(cura_icons.LICENSE_RESOURCE_PATH))), notice
    )
    if change == "missing":
        notice.unlink()
    else:
        (root / "house.svg").write_bytes(b"tampered")
    monkeypatch.setattr(cura_icons, "_resource_root", lambda: root)
    monkeypatch.setattr(cura_icons, "_license_resource", lambda: notice)
    result = _inventory().read()
    row = next(row for row in result["components"] if row["id"] == "ui.lucide")
    assert (row["status"], row["status_reason"]) == (state, reason)
    assert row["effective_version"] is None
    assert str(tmp_path) not in json.dumps(result)


def test_packaged_asset_detector_does_not_accept_arbitrary_paths() -> None:
    catalogue = copy.deepcopy(_catalogue())
    row = next(row for row in catalogue["components"] if row["id"] == "ui.lucide")
    row["detection"]["value"] = "../../private"
    with pytest.raises(ComponentInventoryError, match="not allowlisted"):
        _inventory(catalogue=catalogue)
