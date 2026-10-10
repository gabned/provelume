"""A small adversarial PDF exercises the updated decoder and preservation boundary."""

import zlib
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, EncodedStreamObject, NameObject

from provelume.bundles import DocumentBundleManager
from provelume.extractors import ExtractionError, PdfTextExtractor
from provelume.service import ProvelumeInstance


def filtered_pdf(filters):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
        DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    raw = b"BT /F1 12 Tf 72 720 Td (Public bounded PDF fixture.) Tj ET"
    for _ in range(filters):
        raw = zlib.compress(raw)
    stream = EncodedStreamObject()
    stream._data = raw
    stream[NameObject("/Filter")] = ArrayObject([NameObject("/FlateDecode")] * filters)
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    assert len(output.getvalue()) < 2048
    return output.getvalue()


@pytest.mark.parametrize("filters", [1, 16, 17])
def test_pdf_decoder_limit_preserves_original_and_reports_failed_extraction(tmp_path, filters):
    raw = filtered_pdf(filters)
    if filters <= 16:
        assert PdfTextExtractor().extract(raw).text.strip() == "Public bounded PDF fixture."
    else:
        with pytest.raises(ExtractionError):
            PdfTextExtractor().extract(raw)
    source = tmp_path / "public.pdf"
    source.write_bytes(raw)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    ingestion = instance.ingest(source)
    original, = instance.store.list_canonical("originals")
    assert instance.store.original_bytes(original["id"]) == raw
    document, = instance.store.list_canonical("documents")
    bundles = DocumentBundleManager(instance.store)
    result = bundles.build_document(document["id"])
    pages = bundles.read_page_map(document["current_version_id"])["pages"]
    if filters > 16:
        assert [row["outcome"] for row in ingestion] == ["extraction_failed"]
        assert result["operation"]["status"] == "completed_with_errors"
        assert all(p["extraction_status"] == "error" for p in pages)
    else:
        assert result["operation"]["status"] == "completed"
