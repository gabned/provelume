from __future__ import annotations

import io
import os
import random
import socket
from pathlib import Path

import pytest

from provelume.photo_profiles import PhotoContractError, PhotoProfileManager, inspect_photo_bytes
from provelume.service import ProvelumeInstance

pytestmark = pytest.mark.skipif(
    os.environ.get("PROVELUME_REAL_PHOTO") != "1",
    reason="real photo smoke requires the explicitly provisioned Pillow component",
)


def test_real_pillow_baseline_sanitized_preview_and_unsupported_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PIL import Image

    width, height = 128, 96
    pixels = random.Random(20260903).randbytes(width * height * 3)
    image = Image.frombytes("RGB", (width, height), pixels)
    exif = Image.Exif()
    exif[274] = 6
    exif[306] = "2026:09:03 07:00:00"
    source = tmp_path / "source"
    source.mkdir()
    formats = {
        "photo.jpg": {"format": "JPEG", "quality": 95, "exif": exif},
        "photo.png": {"format": "PNG"},
        "photo.tiff": {"format": "TIFF", "compression": "raw", "exif": exif},
        "photo.bmp": {"format": "BMP"},
    }
    originals = {}
    for name, options in formats.items():
        target = source / name
        image.save(target, **options)
        originals[name] = target.read_bytes()
    unsupported = io.BytesIO()
    image.save(unsupported, format="WEBP")
    image.close()

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    manager = PhotoProfileManager(instance.store)
    assert manager.capability()["decoder"] == {
        "state": "ready",
        "component": "codec.pillow",
        "version": "12.3.0",
        "qualified": True,
    }

    def reject_network(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"unexpected photo network access: {args!r} {kwargs!r}")

    monkeypatch.setattr(socket, "socket", reject_network)
    documents = {
        Path(str(item["locator"])).name: item for item in instance.store.list_canonical("documents")
    }
    for name in sorted(formats):
        version_id = str(documents[name]["current_version_id"])
        bundle = manager.create(version_id)
        selected = manager.get(bundle["representation_id"])
        assert selected is not None
        record = selected["record"]
        assert record["preview"]["state"] == "available"
        assert record["preview"]["active_content"] is False
        assert record["metadata"]["device_fields_redacted"] is True
        assert record["gps"]["coordinates"] is None
        output = next(item for item in selected["outputs"] if item["media_type"] == "image/png")
        preview = instance.root / output["storage_ref"]
        with Image.open(preview) as decoded:
            assert decoded.format == "PNG"
            assert decoded.width <= 1600 and decoded.height <= 1600
            assert not decoded.getexif()
            assert "icc_profile" not in decoded.info
        version = instance.store.read_canonical("versions", version_id)
        assert version is not None
        original = instance.store.read_canonical("originals", str(version["original_id"]))
        assert original is not None
        assert instance.store.original_bytes(str(original["id"])) == originals[name]

    with pytest.raises(PhotoContractError) as caught:
        inspect_photo_bytes(unsupported.getvalue())
    assert caught.value.code == "photo_unsupported_format"
