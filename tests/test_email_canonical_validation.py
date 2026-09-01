from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from provelume.paths import safe_instance_path
from provelume.service import ProvelumeInstance


@pytest.fixture(autouse=True)
def qualified_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "provelume.email_contract.qualified_runtime_target",
        lambda: "ubuntu-24.04-x86_64-cpython312",
    )


def _seed(tmp_path: Path) -> tuple[ProvelumeInstance, dict[str, object]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = (
        b"Message-ID: <validation@example.invalid>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=validation\r\n\r\n"
        b"--validation\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"passive validation body\r\n"
        b"--validation\r\n"
        b"Content-Type: application/octet-stream\r\n"
        b"Content-Disposition: attachment; filename=synthetic.bin\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"c3ludGhldGlj\r\n"
        b"--validation--\r\n"
    )
    source_path = tmp_path / "validation.eml"
    source_path.write_bytes(data)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = instance.create_email_source(
        name="Validation EML",
        path=source_path,
        profile="eml-file-v1",
    )
    instance.set_email_source_state(str(source["id"]), "enabled")
    queued = instance.queue_email_intake(str(source["id"]))
    assert instance.run_email_job(str(queued["job"]["id"]))["status"] == "succeeded"
    message = instance.list_email_messages()[0]
    assert instance.validate_instance(deep=True)["status"] == "valid"
    return instance, message


def _bundle_artifact(instance: ProvelumeInstance) -> dict[str, object]:
    return next(
        item
        for item in instance.store.list_derived_artifacts()
        if item["kind"] == "email_message_bundle"
    )


def test_deep_validation_detects_tampered_manifest_and_body(tmp_path: Path) -> None:
    instance, message = _seed(tmp_path)
    artifact = _bundle_artifact(instance)
    manifest_path = safe_instance_path(instance.store.paths.root, artifact["storage_ref"])
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert "email_bundle_invalid" in {item["code"] for item in report["errors"]}
    assert instance.store.original_bytes(str(message["original_id"]))

    instance, message = _seed(tmp_path / "body-case")
    body_ref = str(message["body"]["storage_ref"])
    safe_instance_path(instance.store.paths.root, body_ref).write_text(
        "tampered passive body",
        encoding="utf-8",
    )
    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert "email_bundle_invalid" in {item["code"] for item in report["errors"]}
    assert instance.store.original_bytes(str(message["original_id"]))


def test_deep_validation_rejects_coordinated_attachment_manifest_tamper(
    tmp_path: Path,
) -> None:
    instance, message = _seed(tmp_path)
    artifact = _bundle_artifact(instance)
    manifest_path = safe_instance_path(instance.store.paths.root, artifact["storage_ref"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["attachments"][0]["size_bytes"] += 1
    encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    manifest_path.write_bytes(encoded)

    metadata_path = instance.store.paths.derived_artifacts / f"{artifact['id']}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["checksum"] = hashlib.sha256(encoded).hexdigest()
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert "email_bundle_invalid" in {item["code"] for item in report["errors"]}
    attachment = instance.store.list_canonical("email-attachments")[0]
    assert instance.store.original_bytes(str(attachment["original_id"])) == b"synthetic"
    assert instance.store.original_bytes(str(message["original_id"]))


def test_deep_validation_reports_corrupt_derived_metadata(tmp_path: Path) -> None:
    instance, _message = _seed(tmp_path)
    artifact = _bundle_artifact(instance)
    metadata_path = instance.store.paths.derived_artifacts / f"{artifact['id']}.json"
    metadata_path.write_bytes(b"not-json")

    report = instance.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert "derived_state_record_invalid" in {
        item["code"] for item in report["errors"]
    }
