from __future__ import annotations

import os
import random
import socket
from pathlib import Path

import pytest

from provelume.ocr_contract import OcrContractError, OcrSettings
from provelume.service import ProvelumeInstance

pytestmark = pytest.mark.skipif(
    os.environ.get("PROVELUME_REAL_OCR") != "1",
    reason="real local OCR smoke requires explicitly provisioned components",
)


def _scanned_image():
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1600, 500
    noise = random.Random(20260830).randbytes(width * height)
    image = Image.frombytes("L", (width, height), noise).point(
        [230 + value % 26 for value in range(256)]
    )
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=72)
    except TypeError:
        font = ImageFont.load_default()
    draw.rectangle((80, 120, 1520, 320), fill=255)
    draw.text((120, 170), "PROVELUME OCR 123", fill=0, font=font)
    return image.convert("RGB")


def _write_inputs(root: Path) -> dict[str, bytes]:
    image = _scanned_image()
    paths = {
        "scan.png": {"format": "PNG"},
        "scan.jpg": {"format": "JPEG", "quality": 95},
        "scan.bmp": {"format": "BMP"},
        "scan.tiff": {"format": "TIFF", "compression": "raw"},
        "scan.pdf": {"format": "PDF", "resolution": 300},
    }
    originals = {}
    for name, options in paths.items():
        path = root / name
        image.save(path, **options)
        originals[name] = path.read_bytes()
    image.close()
    return originals


def test_real_local_ocr_engine_renderer_and_declared_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    originals = _write_inputs(source)
    (source / "corrupt.pdf").write_bytes(b"%PDF-1.7\ncorrupt")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest_run(source)
    settings = OcrSettings(
        mode="forced",
        engine_executable="tesseract",
        languages=("eng",),
        renderer="pdfium-pillow",
        render_dpi=300,
    )
    instance.configure_ocr(settings)

    def forbidden_network(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"unexpected OCR network access: {args!r} {kwargs!r}")

    monkeypatch.setattr(socket, "socket", forbidden_network)
    capability = instance.ocr_capability()
    assert capability["state"] == "ready"
    assert capability["adapter"]["engine_id"] == "tesseract-cli"
    assert capability["adapter"]["engine_version"].startswith("5.")
    assert capability["adapter"]["engine_executable"]
    assert capability["renderer"]["renderer_id"] == "pdfium-pillow"
    assert capability["renderer"]["renderer_version"] == "5.13.0"
    assert capability["renderer"]["decoder_version"] == "12.3.0"
    assert Path(capability["renderer"]["resolved_path"]).is_file()
    assert capability["network_required"] is False
    assert capability["runtime_downloads"] is False
    assert capability["remote_fallback"] is False

    documents = {
        Path(str(document["locator"])).name: document
        for document in instance.store.list_canonical("documents")
    }
    for name in ("scan.png", "scan.jpg", "scan.bmp", "scan.tiff", "scan.pdf"):
        document = documents[name]
        version_id = str(document["current_version_id"])
        queued = instance.queue_ocr(version_id)
        assert queued["scheduled"] is True
        completed = instance.run_ocr_job(queued["job"]["id"])
        assert completed is not None and completed["status"] == "succeeded"
        bundle = instance.list_ocr_bundles(version_id)[0]
        texts = [
            (instance.root / page["text_ref"]).read_text(encoding="utf-8")
            for page in bundle["manifest"]["pages"]
        ]
        assert any("PROVELUME" in text.upper() for text in texts), name
        original = instance.store.read_canonical(
            "originals", bundle["manifest"]["original"]["id"]
        )
        assert original is not None
        assert instance.store.original_bytes(original["id"]) == originals[name]
        assert bundle["manifest"]["authoritative"] is False
        assert bundle["manifest"]["text_is_verified"] is False
        assert bundle["manifest"]["observations_are_separate_from_text"] is True

    corrupt = documents["corrupt.pdf"]
    corrupt_version = instance.store.read_canonical(
        "versions", str(corrupt["current_version_id"])
    )
    assert corrupt_version is not None
    corrupt_original = instance.store.read_canonical(
        "originals", str(corrupt_version["original_id"])
    )
    assert corrupt_original is not None
    corrupt_before = instance.store.original_bytes(str(corrupt_original["id"]))
    with pytest.raises(OcrContractError) as exc_info:
        instance.queue_ocr(str(corrupt["current_version_id"]))
    assert exc_info.value.code == "ocr_corrupt_input"
    assert instance.store.original_bytes(str(corrupt_original["id"])) == corrupt_before
    assert not any(instance.ocr.temporary_root.iterdir())
