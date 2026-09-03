from __future__ import annotations

import copy
import json
import socket
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.extractors import CsvTextExtractor, XlsxTextExtractor, ZipArchiveExtractor
from provelume.file_family_profiles import (
    CSV_PROFILE_ID,
    FILE_FAMILY_PROFILE_IDS,
    XLSX_PROFILE_ID,
    ZIP_PROFILE_ID,
    FileFamilyContractError,
    FileFamilyProfileManager,
    _parse_csv,
    _parse_xlsx,
    _parse_xml,
    _parse_zip,
    validate_file_family_record,
)
from provelume.instance_backup import create_backup, extract_backup, verify_backup
from provelume.instance_validation import inspect_instance
from provelume.service import ProvelumeInstance
from provelume.storage import CANONICAL_KINDS, InstanceStore
from provelume.web import create_app


def _zip(entries: dict[str, bytes | str | ZipInfo]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            if isinstance(value, ZipInfo):
                archive.writestr(value, b"target")
            else:
                archive.writestr(name, value)
    return output.getvalue()


def _mark_zip_encrypted(payload: bytes) -> bytes:
    selected = bytearray(payload)
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = selected.find(signature)
        assert position >= 0
        current = int.from_bytes(
            selected[position + flag_offset : position + flag_offset + 2], "little"
        )
        selected[position + flag_offset : position + flag_offset + 2] = (current | 1).to_bytes(
            2, "little"
        )
    return bytes(selected)


def _xlsx(
    *,
    formula: str = 'WEBSERVICE("https://invalid.example")',
    cached_value: str | None = "2",
    external: bool = False,
    macro: bool = False,
) -> bytes:
    value = "" if cached_value is None else f"<v>{cached_value}</v>"
    relationship_mode = ' TargetMode="External"' if external else ""
    relationship_target = (
        "https://invalid.example/sheet.xml" if external else "worksheets/sheet1.xml"
    )
    workbook_type = (
        "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
        if macro
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    )
    worksheet_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    relationship_type = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    )
    entries = {
        "[Content_Types].xml": f"""<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="{workbook_type}"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="{worksheet_type}"/>
</Types>""",
        "xl/workbook.xml": """<?xml version="1.0"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Evidence" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": f"""<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="{relationship_type}"
    Target="{relationship_target}"{relationship_mode}/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": f"""<?xml version="1.0"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData><row r="1">
    <c r="A1" t="inlineStr"><is><t>&lt;script&gt;alert(1)&lt;/script&gt;</t></is></c>
    <c r="B1"><f>{formula}</f>{value}</c>
    <c r="C1" t="b"><v>1</v></c>
  </row></sheetData>
</worksheet>""",
    }
    if macro:
        entries["xl/vbaProject.bin"] = b"never execute"
    return _zip(entries)


def _seed(tmp_path: Path) -> tuple[ProvelumeInstance, dict[str, str], dict[str, bytes]]:
    source = tmp_path / "source"
    source.mkdir()
    payloads = {
        "evidence.csv": b"name,value\n<script>alert(1)</script>,=2+2\n",
        "evidence.xlsx": _xlsx(),
        "evidence.zip": _zip(
            {
                "notes/evidence.txt": b"hello",
                "payload.html": b"<script>alert('never')</script>",
                "nested.zip": _zip({"hidden.txt": b"do not expand"}),
            }
        ),
    }
    for name, payload in payloads.items():
        (source / name).write_bytes(payload)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    versions = {
        Path(str(document["locator"])).name: str(document["current_version_id"])
        for document in instance.store.list_canonical("documents")
    }
    return instance, versions, payloads


def _canonical_snapshot(store: InstanceStore) -> dict[str, list[dict[str, object]]]:
    return {kind: store.list_canonical(kind) for kind in CANONICAL_KINDS}


def test_exact_three_profiles_create_typed_anchors_without_mutating_authority(
    tmp_path: Path,
) -> None:
    instance, versions, payloads = _seed(tmp_path)
    manager = FileFamilyProfileManager(instance.store)
    canonical_before = _canonical_snapshot(instance.store)
    originals_before = {
        item["id"]: instance.store.original_bytes(str(item["id"]))
        for item in instance.store.list_canonical("originals")
    }
    requested = (
        (CSV_PROFILE_ID, "evidence.csv", "cell"),
        (XLSX_PROFILE_ID, "evidence.xlsx", "cell"),
        (ZIP_PROFILE_ID, "evidence.zip", "member"),
    )
    selected = []
    for profile_id, name, required_anchor in requested:
        queued = manager.queue(versions[name], profile_id)
        assert queued["scheduled"] is True
        job = manager.run(str(queued["job"]["id"]))
        assert job["status"] == "succeeded"
        representation = manager.get(str(job["representation_id"]))
        assert representation is not None
        assert representation["record"]["profile_id"] == profile_id
        assert required_anchor in {item["kind"] for item in representation["anchors"]}
        assert (
            manager.create(versions[name], profile_id)["representation_id"]
            == job["representation_id"]
        )
        selected.append(representation)

    assert tuple(manager.capability()["profile_ids"]) == FILE_FAMILY_PROFILE_IDS
    assert _canonical_snapshot(instance.store) == canonical_before
    assert {
        item["id"]: instance.store.original_bytes(str(item["id"]))
        for item in instance.store.list_canonical("originals")
    } == originals_before
    assert originals_before and len(payloads) == 3

    csv_profile = selected[0]
    csv_targets = [item["target"] for item in csv_profile["anchors"]]
    assert csv_targets[0] == {
        "schema_version": 1,
        "profile": "csv",
        "row": 1,
        "column": 1,
        "coordinate": "A1",
    }
    xlsx_profile = selected[1]
    assert any(item["kind"] == "sheet" for item in xlsx_profile["anchors"])
    cell = xlsx_profile["record"]["profile"]["sheets"][0]["rows"][0]["cells"][1]
    assert cell["display_value"] == "2" and cell["formula_present"] is True
    record_text = json.dumps(xlsx_profile["record"])
    assert "WEBSERVICE" not in record_text and "invalid.example" not in record_text
    zip_profile = selected[2]
    members = zip_profile["record"]["profile"]["members"]
    assert [item["path"] for item in members] == sorted(item["path"] for item in members)
    assert next(item for item in members if item["path"] == "nested.zip")["nested_archive"] is True
    assert all("payload" not in item for item in members)


def test_jobs_cancel_retry_failure_and_cleanup(tmp_path: Path) -> None:
    instance, versions, _payloads = _seed(tmp_path)
    manager = FileFamilyProfileManager(instance.store)
    queued = manager.queue(versions["evidence.zip"], ZIP_PROFILE_ID)
    job_id = str(queued["job"]["id"])
    assert manager.cancel(job_id)["status"] == "cancelled"
    assert manager.retry(job_id)["status"] == "queued"
    assert manager.run(job_id)["status"] == "succeeded"

    source = tmp_path / "bad"
    source.mkdir()
    (source / "legacy.csv").write_bytes(b"\xff\xfelegacy")
    instance.ingest(source)
    version_id = next(
        str(document["current_version_id"])
        for document in instance.store.list_canonical("documents")
        if str(document["locator"]).endswith("legacy.csv")
    )
    failed_id = str(manager.queue(version_id, CSV_PROFILE_ID)["job"]["id"])
    failed = manager.run(failed_id)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "file_family_encoding_unsupported"
    assert manager.retry(failed_id)["status"] == "queued"
    assert not list((manager.root).glob(".file-family-*"))


@pytest.mark.parametrize(
    ("payload", "profile_id", "code"),
    [
        (b"\xff\xfeinvalid", CSV_PROFILE_ID, "file_family_encoding_unsupported"),
        (_xlsx(cached_value=None), XLSX_PROFILE_ID, "file_family_formula_value_unavailable"),
        (_xlsx(external=True), XLSX_PROFILE_ID, "file_family_external_relationship"),
        (_xlsx(macro=True), XLSX_PROFILE_ID, "file_family_active_content"),
        (_zip({"../escape.txt": b"no"}), ZIP_PROFILE_ID, "file_family_path_unsafe"),
        (
            _zip({"A.txt": b"one", "a.TXT": b"two"}),
            ZIP_PROFILE_ID,
            "file_family_collision",
        ),
        (
            _zip({"bomb.txt": b"0" * (2 * 1024 * 1024)}),
            ZIP_PROFILE_ID,
            "file_family_compression_unsafe",
        ),
        (
            _mark_zip_encrypted(_zip({"secret.txt": b"never read"})),
            ZIP_PROFILE_ID,
            "file_family_encrypted",
        ),
    ],
)
def test_hostile_inputs_fail_closed(payload: bytes, profile_id: str, code: str) -> None:
    parser = {
        CSV_PROFILE_ID: _parse_csv,
        XLSX_PROFILE_ID: _parse_xlsx,
        ZIP_PROFILE_ID: _parse_zip,
    }[profile_id]
    with pytest.raises(FileFamilyContractError) as caught:
        parser(payload, cancelled=None)
    assert caught.value.code == code


def test_zip_symlink_nested_and_cancellation_never_extract_to_host(tmp_path: Path) -> None:
    symlink = ZipInfo("link.txt")
    symlink.create_system = 3
    symlink.external_attr = 0o120777 << 16
    with pytest.raises(FileFamilyContractError) as caught:
        _parse_zip(_zip({"ignored": symlink}), cancelled=None)
    assert caught.value.code == "file_family_path_unsafe"

    before = set(tmp_path.rglob("*"))
    record, anchors, _preview = _parse_zip(
        _zip({"nested.zip": _zip({"secret.txt": b"secret"})}), cancelled=None
    )
    assert record["members"][0]["nested_archive"] is True and len(anchors) == 1
    assert set(tmp_path.rglob("*")) == before
    with pytest.raises(FileFamilyContractError) as cancelled:
        _parse_zip(_zip({"a.txt": b"a"}), cancelled=lambda: True)
    assert cancelled.value.code == "file_family_cancelled"


def test_xml_active_declaration_is_rejected_beyond_the_prefix() -> None:
    payload = b"<?xml version='1.0'?>" + b" " * 5000 + b"<!DOCTYPE x><x/>"
    with pytest.raises(FileFamilyContractError) as caught:
        _parse_xml(payload, label="late-doctype.xml")
    assert caught.value.code == "file_family_active_content"


def test_persisted_profile_validation_rejects_inconsistent_nested_evidence(
    tmp_path: Path,
) -> None:
    instance, versions, _payloads = _seed(tmp_path)
    manager = FileFamilyProfileManager(instance.store)
    bundle = manager.create(versions["evidence.csv"], CSV_PROFILE_ID)
    selected = manager.get(str(bundle["representation_id"]))
    assert selected is not None
    tampered = copy.deepcopy(selected["record"])
    tampered["profile"]["rows"][0]["cells"][0]["coordinate"] = "B1"
    with pytest.raises(FileFamilyContractError) as coordinate:
        validate_file_family_record(tampered)
    assert coordinate.value.code == "file_family_contract_violation"

    tampered = copy.deepcopy(selected["record"])
    tampered["profile"]["cell_count"] += 1
    with pytest.raises(FileFamilyContractError) as count:
        validate_file_family_record(tampered)
    assert count.value.code == "file_family_contract_violation"


def test_no_network_and_existing_extractors_keep_their_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_data = b"a,b\n1,2\n"
    xlsx_data = _xlsx(formula="1+1")
    zip_data = _zip({"a.csv": csv_data})
    before = (
        CsvTextExtractor().extract(csv_data),
        XlsxTextExtractor().extract(xlsx_data),
        ZipArchiveExtractor().extract(zip_data),
    )

    def denied(*_args: object, **_kwargs: object) -> socket.socket:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "socket", denied)
    _parse_csv(csv_data, cancelled=None)
    _parse_xlsx(xlsx_data, cancelled=None)
    _parse_zip(zip_data, cancelled=None)
    after = (
        CsvTextExtractor().extract(csv_data),
        XlsxTextExtractor().extract(xlsx_data),
        ZipArchiveExtractor().extract(zip_data),
    )
    assert after == before


def test_remove_rebuild_backup_and_portable_transfer(tmp_path: Path) -> None:
    instance, versions, _payloads = _seed(tmp_path)
    manager = FileFamilyProfileManager(instance.store)
    bundle = manager.create(versions["evidence.csv"], CSV_PROFILE_ID)
    selected_id = str(bundle["representation_id"])
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    receipt = manager.remove(selected_id)
    assert receipt["representation_id"] == selected_id
    assert manager.get(selected_id) is None
    rebuilt = manager.rebuild(selected_id)
    assert rebuilt["representation_id"] == selected_id

    backup = create_backup(instance.store, destination=tmp_path / "backups", reason="file-family")
    assert verify_backup(backup["archive"])["status"] == "valid"
    restored_root = tmp_path / "restored"
    extract_backup(backup["archive"], restored_root)
    assert FileFamilyProfileManager(InstanceStore(restored_root)).get(selected_id) is not None

    portable = tmp_path / "portable.zip"
    instance.export_portable(portable)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    target.import_portable(portable)
    assert target.get_file_family(selected_id) is not None


def test_service_cli_api_and_inert_accessible_browser(tmp_path: Path, capsys) -> None:
    instance, versions, _payloads = _seed(tmp_path)
    selected = instance.file_families.create(versions["evidence.csv"], CSV_PROFILE_ID)
    instance.file_families.create(versions["evidence.xlsx"], XLSX_PROFILE_ID)
    instance.file_families.create(versions["evidence.zip"], ZIP_PROFILE_ID)
    selected_id = str(selected["representation_id"])
    expected = instance.file_family_read_model()

    assert main(["file-family-support", str(instance.root)]) == 0
    support_cli = json.loads(capsys.readouterr().out)
    assert tuple(support_cli["profile_ids"]) == FILE_FAMILY_PROFILE_IDS
    assert main(["file-family-profiles", str(instance.root)]) == 0
    assert json.loads(capsys.readouterr().out) == expected

    client = TestClient(create_app(instance.root))
    assert client.get("/api/v1/file-families/support").status_code == 200
    assert client.get("/api/v1/file-families").json() == expected
    browser = client.get("/file-families?lang=it")
    assert browser.status_code == 200
    assert "Profili di tabelle e archivi" in browser.text
    assert "<script>alert(1)</script>" not in browser.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in browser.text
    assert 'scope="col"' in browser.text and 'scope="row"' in browser.text
    assert "/anchors/None" not in browser.text

    detail = client.get(f"/api/v1/file-families/{selected_id}")
    assert detail.status_code == 200
    anchor_id = detail.json()["anchors"][0]["id"]
    anchor = client.get(f"/api/v1/file-families/{selected_id}/anchors/{anchor_id}")
    assert anchor.status_code == 200 and anchor.json()["target"]["coordinate"] == "A1"
    output = client.get(f"/api/v1/file-families/{selected_id}/outputs/profile.json")
    assert output.status_code == 200
    assert output.headers["cache-control"] == "no-store"
    assert "script-src 'none'" in output.headers["content-security-policy"]
    assert "object-src 'none'" in output.headers["content-security-policy"]
    assert client.get(f"/api/v1/file-families/{selected_id}/outputs/source.csv").status_code == 404
    assert client.post("/api/v1/file-families", json={}).status_code == 405
    assert client.delete(f"/api/v1/file-families/{selected_id}").status_code == 405
    assert client.get("/api/v1/file-families?profile_id=unknown").status_code == 400
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths["/api/v1/file-families/{representation_id}"]) == {"get"}


def test_registry_schema_docs_and_packaging_agree() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = json.loads(
        (root / "core/provelume/representation-support-registry.json").read_text(encoding="utf-8")
    )
    profiles = {item["id"]: item for item in registry["profiles"]}
    assert set(FILE_FAMILY_PROFILE_IDS).issubset(profiles)
    for profile_id in FILE_FAMILY_PROFILE_IDS:
        operations = profiles[profile_id]["operations"]
        assert set(operations) == {
            "preserve",
            "inspect",
            "extract",
            "preview",
            "local_enrich",
            "ai_enrich",
        }
        assert operations["preserve"]["effective"] == "available"
        assert operations["preview"]["effective"] == "available"
        assert operations["ai_enrich"]["reason"] == "not_implemented"
    schema = json.loads(
        (root / "core/provelume/file_family_profile.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["schema_version"]["const"] == 1
    assert tuple(schema["properties"]["profile_id"]["enum"]) == FILE_FAMILY_PROFILE_IDS
    assert {"csvProfile", "xlsxProfile", "zipProfile"}.issubset(schema["$defs"])
    manifest = json.loads(
        (root / "packaging/file-families/python-stdlib-3.12.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "3.12"
    assert manifest["component"] == "runtime.cpython"
    assert manifest["license"] == "PSF-2.0"
    assert manifest["runtime_downloads"] is False and manifest["network_required"] is False
    for path in (
        root / "docs/file-families.md",
        root / "docs/file-families.it.md",
        root / "docs/adr/0026-bounded-csv-xlsx-zip-profiles.md",
    ):
        assert path.is_file() and "perceptio-csv-cell-v1" in path.read_text(encoding="utf-8")
