from __future__ import annotations

import shutil
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from provelume.extractors import CSV_MAX_ROWS, CsvTextExtractor, ExtractionError
from provelume.service import ProvelumeInstance


def _docx_bytes(text: str) -> bytes:
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>"
        f"{escape(text)}"
        "</w:t></w:r></w:p></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _eml_bytes() -> bytes:
    message = EmailMessage()
    message["Subject"] = "Synthetic project update"
    message["From"] = "sender@example.invalid"
    message["To"] = "reader@example.invalid"
    message.set_content("Mail provenance carries the aurora marker.")
    return message.as_bytes()


def test_docx_csv_eml_ingest_search_and_rebuild(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "brief.docx").write_bytes(
        _docx_bytes("Document provenance contains the cobalt marker.")
    )
    (source / "ledger.csv").write_text(
        "name;status\nSynthetic row;verdant-marker\n",
        encoding="utf-8",
    )
    (source / "message.eml").write_bytes(_eml_bytes())

    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Extractor parity")
    acquisitions = instance.ingest(source)
    assert {item["outcome"] for item in acquisitions} == {"created"}
    assert len(instance.list_documents()) == 3

    expected = {
        "cobalt": "brief.docx",
        "verdant": "ledger.csv",
        "aurora": "message.eml",
    }
    for query, title in expected.items():
        result = instance.search(query)
        assert result and result[0]["title"] == title

    artifact_ids_before = {
        item["version_id"]: item["id"] for item in instance.store.list_derived_artifacts()
    }
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
    assert instance.rebuild_index() == 3

    canonical_after = {kind: instance.store.list_canonical(kind) for kind in canonical_before}
    assert canonical_after == canonical_before
    artifact_ids_after = {
        item["version_id"]: item["id"] for item in instance.store.list_derived_artifacts()
    }
    assert artifact_ids_after == artifact_ids_before

    for query, title in expected.items():
        result = instance.search(query)
        assert result and result[0]["title"] == title

    docx = next(item for item in instance.list_documents() if item["title"] == "brief.docx")
    provenance = instance.provenance(docx["id"])
    assert provenance is not None
    assert any(edge["relation"] == "extracted_to" for edge in provenance["edges"])


def test_malformed_new_formats_preserve_originals(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "broken.docx").write_bytes(b"not-a-zip")
    (source / "broken.csv").write_bytes(b"\xff\xfe\x00")
    (source / "empty.eml").write_bytes(b"")

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    acquisitions = instance.ingest(source)

    assert len(acquisitions) == 3
    assert {item["outcome"] for item in acquisitions} == {"extraction_failed"}
    assert len(instance.store.list_canonical("originals")) == 3
    assert len(instance.list_documents()) == 3
    assert all(item["error"] for item in acquisitions)


def test_csv_row_limit_fails_closed() -> None:
    content = "value\n" * (CSV_MAX_ROWS + 1)
    with pytest.raises(ExtractionError, match="row safety limit"):
        CsvTextExtractor().extract(content.encode("utf-8"))
