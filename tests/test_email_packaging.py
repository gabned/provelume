from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_email_baseline_adds_no_distribution_dependency_or_payload() -> None:
    manifest = _json(ROOT / "packaging" / "email" / "local-email-intake.json")
    distribution = manifest["distribution"]
    assert isinstance(distribution, dict)
    assert distribution["new_python_dependencies"] == []
    assert distribution["new_native_components"] == []
    assert distribution["new_provider_payloads"] == []
    assert distribution["silent_runtime_download"] is False

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    assert all("mailbox" not in item.casefold() for item in dependencies)
    assert all("email" not in item.casefold() for item in dependencies)


def test_email_qualification_inventory_is_explicit_and_unpublished() -> None:
    manifest = _json(ROOT / "packaging" / "email" / "local-email-intake.json")
    assert manifest["slice"] == "0.9/S03"
    assert manifest["status"] == "qualified-local-baseline"
    assert manifest["release_identity"] == "0.8.0"
    baseline = manifest["baseline"]
    assert isinstance(baseline, dict)
    assert baseline["default_enabled"] is False
    assert baseline["network_required"] is False
    assert baseline["runtime_download"] is False
    assert baseline["remote_fallback"] is False
    assert baseline["container_reader"]["uses_python_mailbox_module"] is False

    matrix = baseline["qualified_matrix"]
    assert {
        (item["platform"], tuple(item["profiles"])) for item in matrix
    } == {
        ("ubuntu-24.04", ("eml-file-v1", "maildir-cur-new-v1")),
        ("windows", ("eml-file-v1",)),
    }
    assert "mbox" in baseline["unqualified"]
    assert (ROOT / "core" / "provelume" / "email_contract.schema.json").is_file()
    assert (ROOT / "core" / "provelume" / "email_bundle.schema.json").is_file()


def test_email_component_bom_records_only_runtime_stdlib() -> None:
    bom = _json(
        ROOT / "packaging" / "email" / "qualified-local-components.cdx.json"
    )
    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.6"
    assert [item["name"] for item in bom["components"]] == [
        "CPython email standard-library package"
    ]
    assert bom["components"][0]["licenses"] == [
        {"license": {"id": "PSF-2.0"}}
    ]
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "runtime standard library in 0.9/S03" in notices
    assert "not used for message reading or delimitation" in notices
