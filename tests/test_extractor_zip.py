from __future__ import annotations

import shutil
import zlib
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from provelume.extractors import ExtractionError, ZipArchiveExtractor
from provelume.service import ProvelumeInstance


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_zip_member_content_is_searchable_and_rebuildable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    archive_bytes = _zip_bytes(
        {
            "notes/readme.md": b"Archive provenance carries the topaz-marker.\n",
            "data/table.csv": b"name,status\nSynthetic,amber-marker\n",
            "binary/payload.bin": b"\x00\x01\x02",
        }
    )
    (source / "bundle.zip").write_bytes(archive_bytes)

    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Archive parity")
    acquisitions = instance.ingest(source)
    assert acquisitions[0]["outcome"] == "created"
    assert instance.search("topaz")[0]["title"] == "bundle.zip"
    assert instance.search("amber")[0]["title"] == "bundle.zip"
    assert instance.search("payload")[0]["title"] == "bundle.zip"

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
    assert instance.rebuild_index() == 1
    canonical_after = {kind: instance.store.list_canonical(kind) for kind in canonical_before}
    assert canonical_after == canonical_before
    assert instance.search("topaz")[0]["title"] == "bundle.zip"


def test_zip_traversal_fails_without_writing_member(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "unsafe.zip").write_bytes(_zip_bytes({"../escape.txt": b"do not write me"}))

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    acquisitions = instance.ingest(source)

    assert acquisitions[0]["outcome"] == "extraction_failed"
    assert "unsafe" in acquisitions[0]["error"].casefold()
    assert len(instance.store.list_canonical("originals")) == 1
    assert not (tmp_path / "escape.txt").exists()


def test_zip_drive_relative_member_fails_closed() -> None:
    archive = _zip_bytes({"C:notes.txt": b"windows-drive-relative"})
    with pytest.raises(ExtractionError, match="drive prefix"):
        ZipArchiveExtractor().extract(archive)


def test_zip_decompressor_error_becomes_extraction_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "corrupt.zip").write_bytes(_zip_bytes({"broken.txt": b"searchable before corruption"}))

    original_read = ZipFile.read

    def corrupt_read(self: ZipFile, name, pwd=None):
        filename = getattr(name, "filename", str(name))
        if filename == "broken.txt":
            raise zlib.error("synthetic corrupt DEFLATE stream")
        return original_read(self, name, pwd=pwd)

    monkeypatch.setattr(ZipFile, "read", corrupt_read)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    acquisitions = instance.ingest(source)

    assert acquisitions[0]["outcome"] == "extraction_failed"
    assert "ZIP extraction failed" in acquisitions[0]["error"]
    assert len(instance.store.list_canonical("originals")) == 1
    assert len(instance.store.list_canonical("versions")) == 1
    assert len(instance.store.list_canonical("provenance")) >= 4


def test_zip_high_compression_ratio_fails_closed() -> None:
    archive = _zip_bytes({"large.txt": b"0" * (2 * 1024 * 1024)})
    with pytest.raises(ExtractionError, match="compression ratio"):
        ZipArchiveExtractor().extract(archive)


def test_nested_zip_is_listed_but_not_recursively_expanded() -> None:
    nested = _zip_bytes({"secret.txt": b"nested-should-not-be-expanded"})
    outer = _zip_bytes({"nested.zip": nested, "visible.txt": b"visible-marker"})

    result = ZipArchiveExtractor().extract(outer)
    assert "nested.zip" in result.text
    assert "Nested ZIP content is not expanded" in result.text
    assert "nested-should-not-be-expanded" not in result.text
    assert "visible-marker" in result.text
