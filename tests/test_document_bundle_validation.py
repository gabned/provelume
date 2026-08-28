from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from provelume.bundle_reader import DocumentBundleReader
from provelume.bundles import DocumentBundleManager
from provelume.paths import safe_instance_path
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def test_tampered_bundle_is_not_exposed_and_original_remains_intact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "note.txt"
    source_bytes = b"validated derived bundle\n"
    source.write_bytes(source_bytes)
    instance_root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(instance_root)
    instance.ingest_run(source)
    document = instance.store.list_canonical("documents")[0]
    version_id = document["current_version_id"]
    built = DocumentBundleManager(instance.store).build_document(document["id"])
    markdown_path = safe_instance_path(
        instance_root,
        built["manifest"]["markdown"]["storage_ref"],
    )
    markdown_path.write_text("tampered derived state\n", encoding="utf-8")

    reader = DocumentBundleReader(instance.store)

    assert reader.get(version_id) is None
    assert reader.read_markdown(version_id) is None
    assert reader.list() == []
    original = instance.store.list_canonical("originals")[0]
    assert instance.store.original_bytes(original["id"]) == source_bytes
    client = TestClient(create_app(instance_root))
    assert client.get(f"/api/v1/bundles/{version_id}").status_code == 404
    assert client.get(f"/bundles/{version_id}").status_code == 404


def test_invalid_bundle_artifact_is_skipped_without_mutation(tmp_path: Path) -> None:
    instance_root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(instance_root)
    invalid = instance.store.paths.derived_artifacts / f"derived_{'0' * 32}.json"
    invalid.write_text(json.dumps({"kind": "document_bundle"}), encoding="utf-8")
    before = invalid.read_bytes()

    reader = DocumentBundleReader(instance.store)

    assert reader.list() == []
    assert invalid.read_bytes() == before
    client = TestClient(create_app(instance_root))
    assert client.get("/api/v1/bundles").json() == []
    assert invalid.read_bytes() == before
