from __future__ import annotations

import shutil
import zlib
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from provelume.service import ProvelumeInstance


def _xlsx_bytes() -> bytes:
    shared_strings = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'count="1" uniqueCount="1"><si><t>celadon-marker</t></si></sst>'
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
        '<c r="B1"><v>42</v></c></row></sheetData></worksheet>'
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", shared_strings)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return buffer.getvalue()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return (
        len(payload).to_bytes(4, "big")
        + kind
        + payload
        + checksum.to_bytes(4, "big")
    )


def _png_bytes(width: int, height: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes([8, 2, 0, 0, 0])
    )
    scanline = b"\x00" + (b"\x00\x00\x00" * width)
    raw = scanline * height
    return (
        signature
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def _jpeg_bytes(width: int, height: int) -> bytes:
    sof_payload = (
        bytes([8])
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + bytes([3, 1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0])
    )
    sof_segment = b"\xff\xc0" + (len(sof_payload) + 2).to_bytes(2, "big") + sof_payload
    return b"\xff\xd8" + sof_segment + b"\xff\xd9"


def _tiff_bytes(width: int, height: int) -> bytes:
    entries = b"".join(
        (
            (256).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + (1).to_bytes(4, "little")
            + width.to_bytes(4, "little"),
            (257).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + (1).to_bytes(4, "little")
            + height.to_bytes(4, "little"),
        )
    )
    return b"II*\x00" + (8).to_bytes(4, "little") + (2).to_bytes(2, "little") + entries


def _bmp_bytes(width: int, height: int) -> bytes:
    return (
        b"BM"
        + (54).to_bytes(4, "little")
        + b"\x00" * 8
        + (40).to_bytes(4, "little")
        + width.to_bytes(4, "little", signed=True)
        + height.to_bytes(4, "little", signed=True)
        + b"\x00" * 28
    )


def test_xlsx_and_image_metadata_survive_derived_rebuild(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "workbook.xlsx").write_bytes(_xlsx_bytes())
    (source / "diagram.png").write_bytes(_png_bytes(321, 7))
    (source / "photo.jpg").write_bytes(_jpeg_bytes(123, 45))
    (source / "scan.tiff").write_bytes(_tiff_bytes(234, 56))
    (source / "bitmap.bmp").write_bytes(_bmp_bytes(345, 67))

    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="XLSX images")
    acquisitions = instance.ingest(source)
    assert {item["outcome"] for item in acquisitions} == {"created"}
    assert len(instance.list_documents()) == 5

    expected = {
        "celadon": "workbook.xlsx",
        "321": "diagram.png",
        "123": "photo.jpg",
        "234": "scan.tiff",
        "345": "bitmap.bmp",
    }
    for query, title in expected.items():
        result = instance.search(query)
        assert result and result[0]["title"] == title

    canonical_before = {
        kind: instance.store.list_canonical(kind)
        for kind in (
            "sources",
            "acquisitions",
            "originals",
            "documents",
            "versions",
            "provenance",
        )
    }
    shutil.rmtree(instance.store.paths.derived_text)
    shutil.rmtree(instance.store.paths.indexes)
    assert instance.rebuild_index() == 5
    canonical_after = {kind: instance.store.list_canonical(kind) for kind in canonical_before}
    assert canonical_after == canonical_before

    for query, title in expected.items():
        result = instance.search(query)
        assert result and result[0]["title"] == title


def test_malformed_xlsx_and_image_preserve_originals(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "broken.xlsx").write_bytes(b"not-an-ooxml-package")
    (source / "broken.png").write_bytes(b"not-a-png")
    (source / "broken.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (source / "broken.tiff").write_bytes(b"II*\x00bad")
    (source / "broken.bmp").write_bytes(b"BMbad")

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    acquisitions = instance.ingest(source)

    assert len(acquisitions) == 5
    assert {item["outcome"] for item in acquisitions} == {"extraction_failed"}
    assert len(instance.store.list_canonical("originals")) == 5
    assert len(instance.list_documents()) == 5
    assert all(item["error"] for item in acquisitions)
