"""A release SBOM binds both shipped native trees, notices and installed RECORD."""

import copy
import hashlib
import shutil
from pathlib import Path

import pytest
from test_cura_icons import _augmenter, _sbom

from provelume import ai_native_inventory as native


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path / "package"
    root.mkdir()
    lock = {"version": "b11379", "source_revision": "1" * 40, "platforms": {}}
    source = Path(__file__).parents[1] / "core/provelume/runtime_notices"
    shutil.copytree(source, root / "runtime_notices")
    for platform, name in (("windows", "libomp.dll"), ("linux", "libllama.so.0")):
        raw = ("public inert " + platform).encode()
        path = root / "native-ai" / platform / name
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
        lock["platforms"][platform] = {name: {
            "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}
    monkeypatch.setattr(native, "files", lambda _: root)
    monkeypatch.setattr(native, "read_runtime_lock", lambda: lock)
    return root


def test_sbom_identifies_every_actual_native_library_with_optional_scope(package):
    components, members = native.inventory(required=True)
    assert len(components) == 2
    assert "provelume/native-ai/windows/libomp.dll" in members
    assert "provelume/native-ai/linux/libllama.so.0" in members
    assert all(row["scope"] == "optional" for row in components)
    openmp = next(row for row in components if row["name"] == "libomp.dll")
    assert openmp["licenses"] == [{"expression": "Apache-2.0 WITH LLVM-exception"}]
    augmenter = _augmenter()
    value = augmenter.augment_sbom(_sbom(), require_native=True)
    assert augmenter.augment_sbom(value, require_native=True) == value
    expected = {row["bom-ref"] for row in components}
    root = next(row for row in value["dependencies"] if row["ref"] == "application")
    assert expected <= set(root["dependsOn"])
    conflicting = copy.deepcopy(value)
    next(row for row in conflicting["components"] if row["bom-ref"] in expected)["scope"] = (
        "required")
    with pytest.raises(ValueError, match="conflicting"):
        augmenter.augment_sbom(conflicting, require_native=True)


@pytest.mark.parametrize("change", ["missing_tree", "missing_member", "altered", "model", "notice"])
def test_partial_changed_or_weight_contaminated_artifact_cannot_get_release_provenance(
    package, change,
):
    path = package / "native-ai/windows/libomp.dll"
    if change == "missing_tree":
        shutil.rmtree(path.parent)
    elif change == "missing_member":
        path.unlink()
    elif change == "altered":
        path.write_bytes(b"substitute code")
    elif change == "model":
        (path.parent / "model.gguf").write_bytes(b"GGUF model stand-in")
    else:
        (package / "runtime_notices/llama-LICENSE.txt").write_bytes(b"substituted license")
    with pytest.raises(ValueError):
        _augmenter().augment_sbom(_sbom(), require_native=True)


def test_development_without_native_payload_is_explicitly_different_from_release(
    package,
):
    shutil.rmtree(package / "native-ai")
    assert native.inventory() == ([], set())
    with pytest.raises(ValueError, match="both platform trees"):
        native.inventory(required=True)
