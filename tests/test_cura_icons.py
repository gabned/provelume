from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import socket
from importlib.resources import files
from pathlib import Path

import pytest
from markupsafe import Markup

from provelume import cura_icons
from provelume.cura_icons import IconAssetError, render_icon, verify_icon_subset

ASSETS = Path(str(files("provelume").joinpath(cura_icons.RESOURCE_PATH)))


@pytest.fixture
def isolated_assets(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "lucide"
    shutil.copytree(ASSETS, root)
    monkeypatch.setattr(cura_icons, "_resource_root", lambda: root)
    return root


def _reseal_svg(root: Path, content: bytes, *, name: str = "house") -> str:
    """A deliberately re-anchored synthetic manifest exercises structural checks after hashes."""
    manifest = json.loads((root / "subset.json").read_bytes())
    row = next(item for item in manifest["icons"] if item["name"] == name)
    (root / row["file"]).write_bytes(content)
    row["bytes"] = len(content)
    row["sha256"] = hashlib.sha256(content).hexdigest()
    row["git_blob"] = hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content
    ).hexdigest()
    raw = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()
    (root / "subset.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_pinned_subset_preserves_exact_upstream_sources_and_both_licenses(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("icon verification must remain offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    subset = verify_icon_subset()
    assert len(subset.svgs) == 18
    assert sum(map(len, subset.svgs.values())) == 5999
    assert subset.manifest["source"]["commit"] == "b998e2892b90b88004d62da2d0b64dab9959a520"
    assert subset.manifest["version"] == "1.45.0"
    assert subset.manifest["license_expression"] == "ISC AND MIT"
    license_bytes = (ASSETS / "LICENSE").read_bytes()
    assert hashlib.sha256(license_bytes).hexdigest() == (
        "b495047bd93a9b06913511076f504daba17d5bbeb3e0650f3bb53a4220329c57"
    )
    assert b"Copyright (c) 2026 Lucide Icons and Contributors" in license_bytes
    assert b"Copyright (c) 2013-present Cole Bemis" in license_bytes
    assert b"The MIT License (MIT) (for the icons listed above)" in license_bytes
    for name, original in subset.svgs.items():
        rendered = render_icon(name)
        assert isinstance(rendered, Markup)
        assert str(rendered).startswith(
            '<svg class="cura-icon" aria-hidden="true" focusable="false"'
        )
        assert 'stroke="currentColor"' in rendered
        assert (ASSETS / (name + ".svg")).read_bytes() == original


@pytest.mark.parametrize("name", ["../house", "/house", "<svg>", "unknown", "", None])
def test_unknown_names_cannot_select_paths_or_markup(name) -> None:
    with pytest.raises(ValueError, match="unknown Cura icon"):
        render_icon(name)


def test_response_snapshot_keeps_verified_bytes_and_next_response_detects_tampering(
    isolated_assets: Path,
) -> None:
    renderer = cura_icons.icon_renderer()
    original = renderer("house")
    (isolated_assets / "house.svg").write_bytes(b"<svg onload='unexpected()'/>")
    assert renderer("house") == original
    assert "unexpected" not in renderer("house")
    assert isinstance(renderer("search"), Markup)
    with pytest.raises(ValueError, match="unknown Cura icon"):
        renderer("../house")
    with pytest.raises(IconAssetError, match="packaged_asset_invalid"):
        cura_icons.icon_renderer()


@pytest.mark.parametrize(
    "change,code",
    [
        ("missing", "packaged_asset_missing"),
        ("changed", "packaged_asset_invalid"),
        ("extra", "packaged_asset_invalid"),
        ("oversized", "packaged_asset_invalid"),
    ],
)
def test_missing_changed_extra_and_oversized_files_fail_closed(
    isolated_assets: Path,
    change: str,
    code: str,
) -> None:
    if change == "missing":
        (isolated_assets / "house.svg").unlink()
    elif change == "changed":
        (isolated_assets / "house.svg").write_bytes(b"<svg/>")
    elif change == "extra":
        (isolated_assets / "unexpected.svg").write_bytes(b"<svg/>")
    else:
        (isolated_assets / "house.svg").write_bytes(b" " * (cura_icons.MAX_FILE_BYTES + 1))
    with pytest.raises(IconAssetError) as error:
        verify_icon_subset()
    assert error.value.code == code
    with pytest.raises(IconAssetError):
        render_icon("house")


def test_link_like_resource_is_rejected_without_opening_it(
    isolated_assets: Path,
    monkeypatch,
) -> None:
    target = isolated_assets / "house.svg"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(IconAssetError, match="packaged_asset_invalid"):
        verify_icon_subset()


@pytest.mark.parametrize(
    "replacement",
    [
        b"<script>alert(1)</script>",
        b'<path onload="alert(1)" d="M0 0" />',
        b'<path href="https://example.test/active" d="M0 0" />',
        b"<foreignObject><div>active</div></foreignObject>",
        b'<path style="stroke:red" d="M0 0" />',
        b'<!DOCTYPE svg [<!ENTITY external SYSTEM "file:///private">]>',
        b'<path d="M0 0">&external;</path>',
    ],
)
def test_active_or_referenced_content_fails_even_with_recomputed_hashes(
    isolated_assets: Path,
    replacement: bytes,
) -> None:
    original = (isolated_assets / "house.svg").read_bytes()
    modified = original.replace(b"</svg>", replacement + b"</svg>")
    digest = _reseal_svg(isolated_assets, modified)
    with pytest.raises(IconAssetError, match="packaged_asset_invalid"):
        verify_icon_subset(digest)


def test_manifest_cannot_expand_into_paths(isolated_assets: Path) -> None:
    manifest = json.loads((isolated_assets / "subset.json").read_bytes())
    manifest["icons"][0]["name"] = "../outside"
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (isolated_assets / "subset.json").write_bytes(raw)
    with pytest.raises(IconAssetError, match="packaged_asset_invalid"):
        verify_icon_subset(hashlib.sha256(raw).hexdigest())


def test_alternate_xml_encoding_cannot_bypass_the_rendering_contract(
    isolated_assets: Path,
) -> None:
    alternate = (isolated_assets / "house.svg").read_text("utf-8").encode("utf-16")
    digest = _reseal_svg(isolated_assets, alternate)
    with pytest.raises(IconAssetError, match="packaged_asset_invalid"):
        verify_icon_subset(digest)


def _augmenter():
    script = Path(__file__).parents[1] / "scripts/augment_asset_sbom.py"
    spec = importlib.util.spec_from_file_location("asset_sbom_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sbom() -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "provelume",
                "version": "0.10.1",
                "bom-ref": "application",
            }
        },
        "components": [
            {"type": "library", "name": "existing", "version": "1", "bom-ref": "existing"}
        ],
        "dependencies": [{"ref": "application", "dependsOn": ["existing"]}],
    }


def test_shared_sbom_augmentation_is_deterministic_and_binds_application_and_source() -> None:
    augmenter = _augmenter()
    original = _sbom()
    before = copy.deepcopy(original)
    result = augmenter.augment_sbom(original)
    assert original == before
    assert augmenter.augment_sbom(result) == result
    assert (
        next(row for row in result["components"] if row["name"] == "existing")
        == (before["components"][0])
    )
    asset = next(row for row in result["components"] if row["bom-ref"] == cura_icons.BOM_REF)
    assert asset == cura_icons.asset_sbom_component()
    properties = {row["name"]: row["value"] for row in asset["properties"]}
    assert (
        properties["provelume:source-commit"] == verify_icon_subset().manifest["source"]["commit"]
    )
    assert properties["provelume:subset-sha256"] == verify_icon_subset().manifest_sha256
    assert "purl" not in asset
    root = next(row for row in result["dependencies"] if row["ref"] == "application")
    assert root["dependsOn"] == ["existing", cura_icons.BOM_REF]


def test_sbom_augmenter_does_not_replace_same_version_conflicting_or_duplicate_assets() -> None:
    augmenter = _augmenter()
    result = augmenter.augment_sbom(_sbom())
    asset = next(row for row in result["components"] if row["bom-ref"] == cura_icons.BOM_REF)
    asset["hashes"][0]["content"] = "0" * 64
    with pytest.raises(ValueError, match="conflicting"):
        augmenter.augment_sbom(result)
    duplicate = augmenter.augment_sbom(_sbom())
    duplicate["components"].append(copy.deepcopy(cura_icons.asset_sbom_component()))
    with pytest.raises(ValueError, match="duplicate"):
        augmenter.augment_sbom(duplicate)
    conflict = augmenter.augment_sbom(_sbom())
    next(row for row in conflict["dependencies"] if row["ref"] == cura_icons.BOM_REF)[
        "dependsOn"
    ] = ["application"]
    with pytest.raises(ValueError, match="dependency relationship"):
        augmenter.augment_sbom(conflict)


@pytest.mark.parametrize("change", ["format", "application", "dependencies"])
def test_sbom_augmenter_rejects_missing_identity_or_malformed_graph(change: str) -> None:
    payload = _sbom()
    if change == "format":
        payload["specVersion"] = "1.5"
    elif change == "application":
        payload["metadata"]["component"]["name"] = "another-product"
    else:
        payload["dependencies"] = [{"ref": "application", "dependsOn": [None]}]
    with pytest.raises(ValueError):
        _augmenter().augment_sbom(payload)
