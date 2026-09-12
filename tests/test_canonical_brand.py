from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
import zlib
from pathlib import Path

import pytest

from provelume import desktop

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "brand_generator", ROOT / "scripts/generate_windows_icon.py"
)
assert SPEC is not None and SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def test_single_source_binds_every_packaged_asset_and_png_pixels() -> None:
    assets = GENERATOR.generated_assets()
    for name, payload in assets.items():
        assert (ROOT / name).read_bytes() == payload, name
    manifest = json.loads(assets["assets/windows/icon-manifest.json"])
    source = (ROOT / manifest["source"]).read_bytes()
    assert hashlib.sha256(source).hexdigest() == manifest["source_sha256"]
    assert all(color in source for color in [b"#0B1F3A", b"#1769E0", b"#F6C453"])
    for name, record in manifest["outputs"].items():
        assert hashlib.sha256(assets[name]).hexdigest() == record["sha256"]
        assert len(assets[name]) == record["bytes"]
    icon = assets[manifest["output"]]
    for index, size in enumerate(manifest["sizes"]):
        png = assets[f"core/provelume/static/brand/provelume-{size}.png"]
        length, offset = struct.unpack_from("<II", icon, 6 + index * 16 + 8)
        assert icon[offset : offset + length] == png
        assert struct.unpack_from(">II", png, 16) == (size, size)
        length = struct.unpack_from(">I", png, 33)[0]
        pixels = zlib.decompress(png[41 : 41 + length])
        assert len(pixels) == size * (1 + size * 4)
        assert all(pixels[y * (1 + size * 4)] == 0 for y in range(size))
        # Independent semantic samples: transparent corner and navy background.
        assert pixels[4] == 0
        middle_top = 1 + (size // 2) * 4
        assert pixels[middle_top : middle_top + 4] == bytes.fromhex("0b1f3aff")


def test_source_change_propagates_and_missing_or_stale_derivative_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (ROOT / GENERATOR.SOURCE).read_bytes()
    (tmp_path / GENERATOR.SOURCE).parent.mkdir(parents=True)
    (tmp_path / GENERATOR.SOURCE).write_bytes(source)
    original = GENERATOR.generated_assets(tmp_path)
    monkeypatch.setattr(GENERATOR, "ROOT", tmp_path)
    monkeypatch.setattr(GENERATOR, "generated_assets", lambda: original)
    monkeypatch.setattr(sys, "argv", ["generate_windows_icon.py", "--check"])
    assert GENERATOR.main() == 1
    for name, payload in original.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    assert GENERATOR.main() == 0
    path = tmp_path / "core/provelume/static/brand/provelume-32.png"
    path.write_bytes(path.read_bytes() + b"stale")
    assert GENERATOR.main() == 1
    assert (
        GENERATOR.build_ico(source.replace(b"#F6C453", b"#FFFFFF"))
        != original["assets/windows/provelume.ico"]
    )


@pytest.mark.parametrize(
    "replacement",
    [
        b'transform="scale(2)" ',
        b'onload="alert(1)" ',
        b'opacity="0.5" ',
    ],
)
def test_unimplemented_svg_attributes_fail_instead_of_silently_changing_brand(
    replacement: bytes,
) -> None:
    source = (ROOT / GENERATOR.SOURCE).read_bytes().replace(b"<path ", b"<path " + replacement, 1)
    with pytest.raises(ValueError, match="Unsupported"):
        GENERATOR.build_ico(source)


def test_wheel_asset_is_preferred_over_cwd_and_legacy_frozen_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/provelume.ico").write_bytes(b"unrelated cwd icon")
    monkeypatch.chdir(tmp_path)
    assert desktop._versioned_icon_path() == ROOT / "core/provelume/static/brand/provelume.ico"
    assert (
        desktop._icon_identity_payload()["sha256"]
        == hashlib.sha256((ROOT / "assets/windows/provelume.ico").read_bytes()).hexdigest()
    )


def test_existing_browser_brand_keeps_text_and_local_decorative_assets() -> None:
    base = (ROOT / "core/provelume/templates/base.html").read_text()
    about = (ROOT / "core/provelume/templates/about.html").read_text()
    assert "<span>{{ t('brand') }}</span>" in base
    assert "<small>{{ t('tagline') }}</small>" in base
    for template in [base, about]:
        assert 'src="/static/brand/provelume.svg"' in template
        assert 'alt="" aria-hidden="true"' in template
    assert 'rel="icon"' in base


def test_immutable_0100_upgrade_baseline_is_bound_without_dropping_older_baselines() -> None:
    script = (ROOT / "scripts/test_windows_installer.ps1").read_text()
    for value in [
        "0.10.0",
        "72099ac35d2430c0de221fc9bfaca88942c9e883",
        "19430710",
        "785803",
        "c197f021a0c45512eb760a83e59f177ce22d946e0239ddf311296b6c7dc0e954",
        "31c10a4f0b1ab93f16321d343800f000c41163b38fa28cab15a82715058f9860",
    ]:
        assert value in script
    for version in ["0.4.0", "0.4.1", "0.5.0", "0.5.1", "0.6.0", "0.6.1", "0.7.0", "0.9.0"]:
        assert f'version = "{version}"' in script
