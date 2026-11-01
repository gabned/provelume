"""Synthetic supply-chain evidence: no test receipt is a real publication."""

import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from provelume.ocr_kit import (
    ENGINE,
    MANIFEST,
    PACKS,
    PDFIUM_DLL,
    PILLOW_CORE,
    PYTHON_DLL,
    TSV_CONFIG,
    WORKER,
    build_identity,
)
from provelume.publication import canonical_bytes, file_identity
from scripts.augment_ocr_sbom import PREFIX, augment


@pytest.fixture
def release(tmp_path):
    commit = "a" * 40
    payloads = {
        name: b"synthetic-never-executed"
        for name in [
            ENGINE,
            TSV_CONFIG,
            WORKER,
            PYTHON_DLL,
            PDFIUM_DLL,
            PILLOW_CORE,
            *PACKS.values(),
            "components.json",
            "native-dependencies.json",
            "licenses/component.txt",
            "ocr-components.cdx.json",
        ]
    }
    files = [
        {"path": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        for name, raw in payloads.items()
    ]
    component = {
        "name": "Synthetic component",
        "version": "1.0",
        "license": "MIT",
        "source": "synthetic-unit-fixture",
        "notices": ["licenses/component.txt"],
    }
    lock = json.loads(
        (Path(__file__).parents[1] / "packaging/ocr/windows-py312-x64.json").read_text()
    )
    manifest = {
        "schema_version": 1,
        "source_repository": "gabned/provelume",
        "version": "0.14.0",
        "commit": commit,
        "platform": "windows",
        "architecture": "x86_64",
        "python": lock["python"],
        "entrypoints": {"engine": ENGINE, "worker": WORKER, "packs": PACKS},
        "components": [component],
        "files": files,
        "trust": {"synthetic": True},
        "native_dependencies": [
            {"path": row["path"], "architecture": "AMD64", "sha256": row["sha256"], "imports": []}
            for row in files
            if Path(row["path"]).suffix in {".exe", ".dll", ".pyd"}
        ],
        "build_identity": build_identity(
            {
                "source_repository": "gabned/provelume",
                "version": "0.14.0",
                "commit": commit,
                "channel": "development",
                "official": False,
                "tag": None,
            }
        ),
    }
    raw = canonical_bytes(manifest)
    kit = tmp_path / "provelume-0.14.0-ocr-windows-x64.zip"
    with zipfile.ZipFile(kit, "w") as archive:
        for name, value in {**payloads, MANIFEST: raw}.items():
            archive.writestr(name, value)
    installer = tmp_path / "Provelume-Setup-0.14.0-x64.exe"
    installer.write_bytes(b"synthetic-never-executed-setup")
    producer = {
        "build_identity": manifest["build_identity"],
        "kit": file_identity(kit),
        "source_commit": commit,
        "components": [component],
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }
    installed = {
        "build_identity": manifest["build_identity"],
        "result": "PASS",
        "kit": file_identity(kit),
        "source_commit": commit,
        "installer": file_identity(installer),
    }
    sbom = {
        "metadata": {"component": {"bom-ref": "application", "version": "0.14.0"}},
        "components": [],
        "dependencies": [{"ref": "application", "dependsOn": []}],
    }
    return sbom, kit, producer, installed, commit, installer


def test_optional_kit_sbom_binds_exact_qualified_asset_setup_native_files_and_licenses(release):
    sbom = augment(*release)
    assert len(sbom["components"]) == 7
    assert all(row["bom-ref"].startswith(PREFIX) for row in sbom["components"])
    (component,) = [row for row in sbom["components"] if row["type"] == "library"]
    assert component["licenses"] == [{"license": {"name": "MIT"}}]
    assert len(sbom["dependencies"][0]["dependsOn"]) == 1
    assert release[0]["components"] == []
    with pytest.raises(ValueError, match="already added"):
        augment(sbom, *release[1:])


@pytest.mark.parametrize(
    "target,field,value",
    [
        (2, "source_commit", "b" * 40),
        (3, "source_commit", "b" * 40),
        (3, "result", "FAIL"),
        (2, "manifest_sha256", "0" * 64),
        (3, "installer", {"name": "different.exe", "size_bytes": 1, "sha256": "0" * 64}),
        (2, "kit", {"name": "different.zip", "size_bytes": 1, "sha256": "0" * 64}),
    ],
)
def test_cross_candidate_or_failed_evidence_never_enters_release_sbom(
    release, target, field, value
):
    args = list(deepcopy(release))
    args[target][field] = value
    with pytest.raises(ValueError):
        augment(*args)


def test_altered_nested_native_bytes_are_rejected_before_release_sbom_write(release):
    archive = release[1]
    with zipfile.ZipFile(archive) as source:
        payload = {name: source.read(name) for name in source.namelist()}
    payload[ENGINE] = b"altered"
    with zipfile.ZipFile(archive, "w") as output:
        for name, value in payload.items():
            output.writestr(name, value)
    release[2]["kit"] = release[3]["kit"] = file_identity(archive)
    with pytest.raises(ValueError, match="size differs"):
        augment(*release)


def test_missing_native_license_is_not_inferred(tmp_path):
    from scripts.compose_windows_ocr_kit import native_license

    with pytest.raises(ValueError, match="unspecified"):
        native_license("unknown", "1", {}, {}, tmp_path)


def test_native_license_evidence_cannot_transfer_to_another_version(tmp_path):
    from scripts.compose_windows_ocr_kit import native_license

    lock = {
        "native_license_evidence": {"example": {"version": "1", "expression": "MIT", "files": []}}
    }
    with pytest.raises(ValueError, match="different version"):
        native_license("example", "2", {}, lock, tmp_path)


def test_installed_scan_corpus_respects_default_expansion_budget_with_headroom(tmp_path):
    pytest.importorskip("PIL")
    from provelume.ocr_contract import OcrLimits
    from scripts.qualify_windows_ocr_installed import _corpus

    corpus = tmp_path / "corpus"
    _corpus(corpus)
    # Conservative bound above the 1800x500 raster and its PDF render guard.
    # Ordinary corpus inputs must have at least 2x headroom; malicious expansion
    # remains tested separately and the product's limit is never raised here.
    decoded_bound = 1804 * 504 * 4
    ordinary = sorted(p for p in corpus.iterdir() if p.stem in {"eng", "ita"})
    assert len(ordinary) == 10
    for path in ordinary:
        assert 2 * decoded_bound / path.stat().st_size <= OcrLimits().max_decompression_ratio, path
