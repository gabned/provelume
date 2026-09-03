from __future__ import annotations

import io
import json
import socket
import wave
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.file_family_profiles import CSV_PROFILE_ID
from provelume.i18n import catalog
from provelume.instance_backup import create_backup, extract_backup, verify_backup
from provelume.instance_validation import inspect_instance
from provelume.perceptio import (
    PERCEPTIO_ERROR_CODES,
    PERCEPTIO_PROFILE_IDS,
    PerceptioError,
)
from provelume.representations import canonical_json_bytes, validate_representation_bundle
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return len(payload).to_bytes(4, "big") + kind + payload + checksum.to_bytes(4, "big")


def _png() -> bytes:
    header = (4).to_bytes(4, "big") + (3).to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    pixels = (b"\x00" + b"\x10\x20\x30" * 4) * 3
    return b"\x89PNG\r\n\x1a\n" + b"".join(
        (
            _png_chunk(b"IHDR", header),
            _png_chunk(b"IDAT", zlib.compress(pixels)),
            _png_chunk(b"IEND", b""),
        )
    )


def _wav() -> bytes:
    payload = io.BytesIO()
    with wave.open(payload, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 1_600)
    return payload.getvalue()


def _mp4_atom(kind: bytes, payload: bytes = b"") -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


def _mp4() -> bytes:
    return _mp4_atom(b"ftyp", b"isom\x00\x00\x00\x00isom") + _mp4_atom(b"moov")


def _seed(tmp_path: Path) -> tuple[ProvelumeInstance, str, str]:
    source = tmp_path / "source"
    source.mkdir()
    payloads = {
        "evidence.png": _png(),
        "evidence.wav": _wav(),
        "evidence.mp4": _mp4(),
        "evidence.csv": b"name,value\n<script>alert(1)</script>,uncertain\n",
        "other.csv": b"name,value\nother,unrelated\n",
    }
    for name, payload in payloads.items():
        (source / name).write_bytes(payload)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    versions = {
        Path(str(document["locator"])).name: str(document["current_version_id"])
        for document in instance.store.list_canonical("documents")
    }
    instance.photos.create(versions["evidence.png"])
    instance.audio.create(versions["evidence.wav"])
    instance.video.create(versions["evidence.mp4"])
    version_id = versions["evidence.csv"]
    selected = instance.file_families.create(version_id, CSV_PROFILE_ID)
    representation_id = str(selected["representation_id"])
    instance.file_families.queue(version_id, CSV_PROFILE_ID)
    instance.file_families.queue(versions["other.csv"], CSV_PROFILE_ID)

    bundle_path = instance.perceptio.bundles.root / representation_id / "bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    anchor = bundle["anchors"][0]
    bundle["warnings"] = ["synthetic_uncertainty"]
    bundle["corrections"] = [
        {
            "id": "rcor_" + "3" * 64,
            "kind": "replace",
            "anchor_id": anchor["id"],
            "before_sha256": "4" * 64,
            "after_sha256": "5" * 64,
            "reversible": True,
        }
    ]
    validate_representation_bundle(bundle)
    bundle_path.write_bytes(canonical_json_bytes(bundle))
    return instance, version_id, representation_id


def test_service_cli_api_browser_share_one_read_only_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, version_id, representation_id = _seed(tmp_path)
    before = _snapshot(instance.root)

    def blocked_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Perceptio read attempted network access")

    monkeypatch.setattr(socket, "create_connection", blocked_network)
    mixed = instance.perceptio_read_model()
    assert {item["family"] for item in mixed["items"]} == {
        "photo",
        "audio",
        "video",
        "file_family",
    }
    expected = instance.perceptio_read_model(version_id=version_id)
    assert expected["publication"] == {
        "state": "candidate",
        "availability": "unavailable_until_verified_publication",
        "current_package_version": "0.10.0",
        "official_build": False,
    }
    assert [item["family"] for item in expected["support"]] == [
        "photo",
        "audio",
        "video",
        "file_family",
    ]
    assert len(expected["items"]) == 1
    assert [job["family"] for job in expected["jobs"]] == ["file_family"]
    assert all(job["record"]["version_id"] == version_id for job in expected["jobs"])
    assert [row["job_count"] for row in expected["support"]] == [0, 0, 0, 1]
    assert all(
        row["evidence"]["capability_probe"] == "not_performed" for row in expected["support"]
    )
    item = expected["items"][0]
    assert item["representation_id"] == representation_id
    assert item["surface"] == "table_archive_metadata"
    assert item["uncertainty"] == {"count": 1, "warnings": ["synthetic_uncertainty"]}
    assert item["corrections"]["all_reversible"] is True
    assert expected["registry"]["profile_ids"] == list(PERCEPTIO_PROFILE_IDS)
    assert len(expected["registry"]["support"]["records"]) == 84
    assert expected["registry"]["support"]["network_used"] is False
    assert expected["privacy"]["network_used"] is False
    assert expected["invariants"]["mutated"] is False

    assert main(["perceptio-status", str(instance.root), "--version-id", version_id]) == 0
    assert json.loads(capsys.readouterr().out) == expected

    client = TestClient(create_app(instance.root))
    response = client.get("/api/v1/perceptio", params={"version_id": version_id})
    assert response.status_code == 200 and response.json() == expected
    detail = client.get(f"/api/v1/perceptio/representations/{representation_id}")
    assert detail.status_code == 200
    anchor_id = detail.json()["item"]["anchors"]["items"][0]["id"]
    anchor = client.get(
        f"/api/v1/perceptio/representations/{representation_id}/anchors/{anchor_id}"
    )
    assert anchor.status_code == 200
    assert anchor.json()["representation_id"] == representation_id

    browser = client.get("/perceptio?lang=it")
    assert browser.status_code == 200
    assert "Pilot multimediale Perceptio" in browser.text
    assert "<script>alert(1)</script>" not in browser.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in browser.text
    assert 'aria-labelledby="perceptio-title"' in browser.text
    assert 'scope="col"' in browser.text and 'scope="row"' in browser.text
    assert _snapshot(instance.root) == before

    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths["/api/v1/perceptio"]) == {"get"}
    assert set(paths["/api/v1/perceptio/representations/{representation_id}"]) == {"get"}
    assert client.post("/api/v1/perceptio", json={}).status_code == 405
    deleted = client.delete(f"/api/v1/perceptio/representations/{representation_id}")
    assert deleted.status_code == 405


def test_publication_state_requires_exact_official_build_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")

    def identity(*, tag: str) -> dict[str, object]:
        return {
            "version": "0.10.0",
            "tag": tag,
            "commit": "a" * 40,
            "official": True,
            "identity_status": "official_metadata_present",
        }

    monkeypatch.setattr("provelume.perceptio.current_build_info", lambda: identity(tag="v0.9.0"))
    candidate = instance.perceptio_read_model()["publication"]
    assert candidate["state"] == "candidate"
    assert candidate["availability"] == "unavailable_until_verified_publication"

    monkeypatch.setattr("provelume.perceptio.current_build_info", lambda: identity(tag="v0.10.0"))
    published = instance.perceptio_read_model()["publication"]
    assert published == {
        "state": "published",
        "availability": "available_in_verified_release",
        "current_package_version": "0.10.0",
        "official_build": True,
    }


def test_reads_do_not_probe_family_or_registry_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, version_id, _representation_id = _seed(tmp_path)

    def forbidden_probe(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Perceptio read performed an optional capability probe")

    for manager in (
        instance.photos,
        instance.audio,
        instance.video,
        instance.file_families,
    ):
        monkeypatch.setattr(manager, "capability", forbidden_probe)
        monkeypatch.setattr(manager, "read_model", forbidden_probe)
    for name in ("_ocr_state", "_photo_state", "_audio_state", "_video_state"):
        monkeypatch.setattr(instance.representations.support, name, forbidden_probe)

    selected = instance.perceptio_read_model(version_id=version_id)
    assert len(selected["items"]) == 1
    assert selected["jobs"][0]["record"]["version_id"] == version_id


def test_empty_degraded_unavailable_recovery_contract_and_closed_limits(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    model = instance.perceptio_read_model()
    assert model["items"] == [] and model["jobs"] == []
    assert model["journey"]["states"] == [
        "happy",
        "empty",
        "loading",
        "degraded",
        "unavailable",
        "interrupted",
        "recovery",
    ]
    assert model["qualification"]["recovery"]["remove_rebuild"] == "required"
    assert model["qualification"]["recovery"]["backup_restore"] == "required"
    assert model["qualification"]["recovery"]["portable_transfer"] == "required"
    assert model["qualification"]["recovery"]["n_minus_one"] == "0.9.0"
    assert model["qualification"]["recovery"]["rollback"] == ("explicit_no_silent_schema_downgrade")
    for invalid in (0, 501, True):
        with pytest.raises(PerceptioError) as caught:
            instance.perceptio_read_model(limit=invalid)
        assert caught.value.code == "perceptio_limit_invalid"
    assert {
        "perceptio_limit_invalid",
        "perceptio_qualification_invalid",
    } == PERCEPTIO_ERROR_CODES


def test_mixed_archive_backup_restore_and_portable_transfer_preserve_evidence(
    tmp_path: Path,
) -> None:
    instance, _version_id, corrected_id = _seed(tmp_path)
    before = inspect_instance(instance.root, deep=True)
    assert before["status"] == "valid"

    backup = create_backup(instance.store, destination=tmp_path / "backups", reason="perceptio")
    assert verify_backup(backup["archive"])["status"] == "valid"
    restored_root = tmp_path / "restored"
    extract_backup(backup["archive"], restored_root)
    restored = ProvelumeInstance(restored_root)
    assert (
        inspect_instance(restored_root, deep=True)["content_fingerprint"]
        == before["content_fingerprint"]
    )
    assert {item["family"] for item in restored.perceptio_read_model()["items"]} == {
        "photo",
        "audio",
        "video",
        "file_family",
    }
    corrected = restored.get_perceptio_representation(corrected_id)
    assert corrected is not None and corrected["item"]["corrections"]["count"] == 1

    portable = tmp_path / "perceptio-portable.zip"
    instance.export_portable(portable)
    target = ProvelumeInstance.initialise(tmp_path / "portable-target")
    assert target.import_portable(portable)["status"] == "imported"
    assert (
        inspect_instance(target.root, deep=True)["content_fingerprint"]
        == before["content_fingerprint"]
    )
    transferred = target.get_perceptio_representation(corrected_id)
    assert transferred is not None and transferred["item"]["corrections"]["count"] == 1


def test_english_italian_and_packaged_qualification_remain_exact() -> None:
    english = catalog("en")
    italian = catalog("it")
    perceptio_keys = {key for key in english if key.startswith("perceptio.")}
    assert perceptio_keys == {key for key in italian if key.startswith("perceptio.")}
    assert all(english[key] != key and italian[key] != key for key in perceptio_keys)

    root = Path(__file__).resolve().parents[1]
    qualification = json.loads(
        (root / "core/provelume/perceptio_qualification.json").read_text(encoding="utf-8")
    )
    assert qualification["target_version"] == "0.10.0"
    assert qualification["publication_state"] == "candidate"
    assert qualification["registry_profile_ids"] == list(PERCEPTIO_PROFILE_IDS)
    assert [item["id"] for item in qualification["exit_gates"]] == [
        f"release-exit-{index:02d}" for index in range(1, 11)
    ]
    assert qualification["privacy"]["active_content"] == "inert"
    assert qualification["resource_policy"]["bounded_profiles_only"] is True
    schema = json.loads(
        (root / "core/provelume/perceptio_qualification.schema.json").read_text(encoding="utf-8")
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["publication_state"] == {"const": "candidate"}
    wheel_config = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'packages = ["core/provelume"]' in wheel_config
    workflow = (root / ".github/workflows/perceptio-final-qualification.yml").read_text(
        encoding="utf-8"
    )
    assert "ubuntu-24.04" in workflow and "windows-2025" in workflow
    assert "tests/test_perceptio_integration.py" in workflow
    for path in (
        root / "docs/perceptio.md",
        root / "docs/perceptio.it.md",
        root / "docs/api.md",
        root / "docs/qualification/perceptio-s07.md",
        root / "docs/adr/0027-integrated-perceptio-read-model.md",
    ):
        assert path.is_file() and "0.10" in path.read_text(encoding="utf-8")
    api = (root / "docs/api.md").read_text(encoding="utf-8")
    assert "development builds report `candidate`" in api
    assert "`v0.10.0` reports `published`" in api
