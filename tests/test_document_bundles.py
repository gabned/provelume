from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from provelume.bundles import DocumentBundleManager
from provelume.cli import main
from provelume.operations import OperationLedger
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _pdf_bytes(*texts: str) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_ref}
                )
            }
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(
            f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_bundle_preserves_original_and_page_map(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    pdf = source / "pages.pdf"
    original_bytes = _pdf_bytes("First bundle page", "Second bundle page")
    pdf.write_bytes(original_bytes)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest_run(source)
    document = instance.store.list_canonical("documents")[0]
    version_id = document["current_version_id"]

    result = DocumentBundleManager(instance.store).build_document(document["id"])

    manifest = result["manifest"]
    markdown = DocumentBundleManager(instance.store).read_markdown(version_id)
    page_map = DocumentBundleManager(instance.store).read_page_map(version_id)
    assert result["operation"]["status"] == "completed"
    assert manifest["page_map"]["pages"] == 2
    assert manifest["assets"] == []
    assert markdown is not None
    assert "## Page 1" in markdown
    assert "First bundle page" in markdown
    assert "## Page 2" in markdown
    assert "Second bundle page" in markdown
    assert page_map is not None
    assert [page["number"] for page in page_map["pages"]] == [1, 2]
    assert page_map["pages"][0]["markdown_start_line"] < page_map["pages"][1][
        "markdown_start_line"
    ]
    original = instance.store.list_canonical("originals")[0]
    assert instance.store.original_bytes(original["id"]) == original_bytes
    assert instance.store.read_canonical("versions", version_id)["content_hash"] == original[
        "sha256"
    ]
    operation = OperationLedger(instance.store).get(result["operation"]["id"])
    assert operation is not None
    assert [event["code"] for event in operation["events"]] == [
        "bundle.original_verified",
        "bundle.committed",
    ]


def test_bundle_rebuild_is_content_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "note.md"
    source.write_text("# Deterministic\n\nPortable bundle.\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest_run(source)
    document = instance.store.list_canonical("documents")[0]
    manager = DocumentBundleManager(instance.store)

    first = manager.build_document(document["id"])
    second = manager.build_document(document["id"])

    assert first["manifest"] == second["manifest"]
    assert first["artifact"]["id"] == second["artifact"]["id"]
    assert first["artifact"]["storage_ref"] == second["artifact"]["storage_ref"]
    assert first["artifact"]["checksum"] == second["artifact"]["checksum"]
    bundle_directories = list(
        (instance.root / "state" / "derived" / "bundles").glob("*/*")
    )
    assert len(bundle_directories) == 1
    operations = OperationLedger(instance.store).list(kind="bundle.build")
    assert len(operations) == 2
    assert all(item["status"] == "completed" for item in operations)


def test_bundle_build_all_isolates_document_failure(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "valid.txt").write_text("valid bundle content\n", encoding="utf-8")
    (source / "broken.pdf").write_bytes(b"%PDF-1.7\nbroken")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    ingestion = instance.ingest_run(source)
    assert ingestion["run"]["status"] == "completed_with_errors"

    result = DocumentBundleManager(instance.store).build_all()

    assert result["operation"]["status"] == "completed_with_errors"
    assert len(result["completed"]) == 1
    assert len(result["failed"]) == 1
    assert len(DocumentBundleManager(instance.store).list()) == 1
    parent = OperationLedger(instance.store).get(result["operation"]["id"])
    assert parent is not None
    assert parent["metrics"] == {
        "documents_total": 2,
        "bundles_completed": 1,
        "bundles_failed": 1,
    }
    assert {event["code"] for event in parent["events"]} == {
        "bundle.child_completed",
        "bundle.child_failed",
    }


def test_bundle_read_surfaces_do_not_build_or_mutate(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("read-only bundle surface\n", encoding="utf-8")
    instance_root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(instance_root)
    instance.ingest_run(source)
    document = instance.store.list_canonical("documents")[0]
    version_id = document["current_version_id"]
    bundle_root = instance_root / "state" / "derived" / "bundles"
    assert not bundle_root.exists()
    client = TestClient(create_app(instance_root))

    assert client.get("/api/v1/bundles").json() == []
    assert client.get("/bundles").status_code == 200
    assert client.get(f"/api/v1/bundles/{version_id}").status_code == 404
    assert client.get(f"/api/v1/documents/{document['id']}/bundle").status_code == 404
    assert client.post("/api/v1/bundles").status_code == 405
    assert not bundle_root.exists()


def test_bundle_cli_and_read_only_http_navigation(tmp_path: Path, capsys) -> None:
    source = tmp_path / "note.txt"
    source.write_text("CLI bundle navigation\n", encoding="utf-8")
    instance_root = tmp_path / "instance"
    assert main(["init", str(instance_root)]) == 0
    capsys.readouterr()
    assert main(["ingest", str(instance_root), str(source)]) == 0
    capsys.readouterr()
    instance = ProvelumeInstance(instance_root)
    document = instance.store.list_canonical("documents")[0]
    version_id = document["current_version_id"]

    assert main(["bundle-build", str(instance_root), document["id"]]) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["manifest"]["version_id"] == version_id
    assert main(["bundles", str(instance_root)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["manifest"]["version_id"] == version_id
    assert main(
        ["bundle", str(instance_root), version_id, "--include-markdown"]
    ) == 0
    detail = json.loads(capsys.readouterr().out)
    assert "CLI bundle navigation" in detail["markdown"]

    client = TestClient(create_app(instance_root))
    assert client.get("/bundles").status_code == 200
    page = client.get(f"/bundles/{version_id}")
    assert page.status_code == 200
    assert "CLI bundle navigation" in page.text
    assert client.get(f"/api/v1/bundles/{version_id}").status_code == 200
    assert "CLI bundle navigation" in client.get(
        f"/api/v1/bundles/{version_id}/markdown"
    ).text
    page_map = client.get(f"/api/v1/bundles/{version_id}/page-map")
    assert page_map.status_code == 200
    assert page_map.json()["pages"][0]["number"] == 1
