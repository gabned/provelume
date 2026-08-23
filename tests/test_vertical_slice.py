from __future__ import annotations

import shutil
from pathlib import Path

from pypdf import PdfWriter

from provelume.service import ProvelumeInstance

CANONICAL_KINDS = (
    "sources",
    "acquisitions",
    "originals",
    "documents",
    "versions",
    "provenance",
)


def test_init_ingest_duplicate_version_restart_and_rebuild(tmp_path: Path) -> None:
    instance_dir = tmp_path / "instance"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    note = source_dir / "note.md"
    note.write_text("# Alpha\n\nDurable provenance matters.\n", encoding="utf-8")

    instance = ProvelumeInstance.initialise(instance_dir, name="Synthetic Demo")
    assert (instance_dir / "provelume.yml").is_file()
    assert (instance_dir / "knowledge").is_dir()
    assert (instance_dir / "originals").is_dir()
    assert (instance_dir / "indexes").is_dir()

    first = instance.ingest(source_dir)
    assert first[0]["outcome"] == "created"
    document_id = first[0]["document_id"]
    version_id = first[0]["version_id"]
    assert instance.search("provenance")[0]["document_id"] == document_id

    second = instance.ingest(source_dir)
    assert second[0]["outcome"] == "unchanged"
    assert second[0]["version_id"] == version_id
    assert len(instance.store.versions_for_document(document_id)) == 1

    note.write_text(
        "# Alpha\n\nDurable provenance and versions matter.\n",
        encoding="utf-8",
    )
    third = instance.ingest(source_dir)
    assert third[0]["outcome"] == "version_created"
    assert third[0]["version_id"] != version_id
    assert len(instance.store.versions_for_document(document_id)) == 2

    canonical_before = {
        kind: instance.store.list_canonical(kind) for kind in CANONICAL_KINDS
    }
    shutil.rmtree(instance_dir / "indexes")
    restarted = ProvelumeInstance(instance_dir)
    assert restarted.rebuild_index() == 1
    assert restarted.search("versions")[0]["document_id"] == document_id
    canonical_after = {
        kind: restarted.store.list_canonical(kind) for kind in CANONICAL_KINDS
    }
    assert canonical_after == canonical_before


def test_originals_are_content_addressed_and_deduplicated(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    content = "same bytes\n"
    (source_dir / "a.txt").write_text(content, encoding="utf-8")
    (source_dir / "b.txt").write_text(content, encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source_dir)

    originals = instance.store.list_canonical("originals")
    documents = instance.store.list_canonical("documents")
    assert len(originals) == 1
    assert len(documents) == 2
    assert any(
        problem["code"] == "duplicate_content"
        for problem in instance.knowledge_health()["problems"]
    )


def test_extraction_failure_preserves_original(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "bad.txt").write_bytes(b"\xff\xfe\x00")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    acquisitions = instance.ingest(source_dir)
    assert acquisitions[0]["outcome"] == "extraction_failed"
    assert len(instance.store.list_canonical("originals")) == 1
    assert len(instance.store.list_canonical("documents")) == 1


def test_pdf_ingestion_is_supported(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf_path = source_dir / "blank.pdf"
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    acquisitions = instance.ingest(source_dir)
    assert acquisitions[0]["outcome"] == "created"
    document = instance.store.list_canonical("documents")[0]
    assert document["media_type"] == "application/pdf"
