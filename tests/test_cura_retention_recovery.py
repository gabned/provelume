from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from provelume.bundles import BundleBuildError, BundleTextUnavailable, DocumentBundleManager
from provelume.extractors import MAX_EXTRACTED_CHARS, PlainTextExtractor, TextDecodingUnavailable
from provelume.library_projection_model import LIBRARY_MANIFEST, LibraryProjectionError
from provelume.markdown_viewer import DocumentContentError, DocumentContentReader
from provelume.retention import DocumentRetentionManager
from provelume.service import ProvelumeInstance


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _fixture(tmp_path: Path, suffix: str = ".txt"):
    instance = ProvelumeInstance.initialise(tmp_path / "i")
    good = tmp_path / "good.md"
    good.write_text("# Good\n\ncura-retention-orchid\n", encoding="utf-8")
    instance.ingest(good)
    good_document = instance.list_documents()[0]
    instance.rebuild_library()
    bad = tmp_path / ("bad" + suffix)
    bad.write_bytes(b"\xff\xfe")
    instance.ingest(bad)
    bad_document = next(d for d in instance.list_documents() if d["id"] != good_document["id"])
    return instance, str(good_document["id"]), str(bad_document["id"])


def _manifest(instance):
    return json.loads((instance.store.paths.library / LIBRARY_MANIFEST).read_bytes())


def _assert_unavailable(instance, document_id):
    content = DocumentContentReader(instance.store).get(document_id, build_missing_bundle=True)
    assert content["source"] == "unavailable"
    assert content["unavailable_reason"] == "invalid_utf8"
    assert content["markdown"] is None and content["bundle"] is None
    original = instance.root / content["original"]["storage_ref"]
    assert original.read_bytes() == b"\xff\xfe"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == content["original"]["sha256"]
    projection = instance.store.paths.library / _manifest(instance)["primary_paths"][document_id]
    text = projection.read_text(encoding="utf-8")
    assert document_id in text and content["original"]["sha256"] in text
    assert 'provelume_representation_unavailable_reason: "invalid_utf8"' in text
    assert "[Preserved Original]" in text and "not valid UTF-8" in text


@pytest.mark.parametrize("suffix", [".txt", ".md", ".csv"])
def test_verified_undecodable_original_projects_identity_and_records_failed_build(tmp_path, suffix):
    instance, good_id, bad_id = _fixture(tmp_path, suffix)
    originals = _files(instance.store.paths.originals)
    canonical = _files(instance.store.paths.knowledge)
    instance.rebuild_library()
    assert good_id in _manifest(instance)["primary_paths"]
    _assert_unavailable(instance, bad_id)
    version = instance.current_version(bad_id)
    with pytest.raises(BundleTextUnavailable):
        DocumentBundleManager(instance.store).build_version(version["id"])
    assert _files(instance.store.paths.originals) == originals
    assert _files(instance.store.paths.knowledge) == canonical
    operations = DocumentBundleManager(instance.store).operations.list(limit=100)
    assert any(r["kind"] == "bundle.build" and r["status"] == "failed" for r in operations)


@pytest.mark.parametrize(
    "action,undo,status,in_library",
    [
        ("trash", "restore_from_trash", "trashed", False),
        ("archive", "unarchive", "archived", True),
        ("remove_from_library", "restore_to_library", "active", False),
    ],
)
def test_unrelated_decode_failure_does_not_break_retention_or_undo(
    tmp_path, action, undo, status, in_library
):
    instance, good_id, bad_id = _fixture(tmp_path)
    originals = _files(instance.store.paths.originals)
    canonical = _files(instance.store.paths.knowledge)
    manager = DocumentRetentionManager(instance.store)
    result = getattr(manager, action)(good_id)
    assert result["status"] == "completed" and result["changed"]
    assert manager.get(good_id)["status"] == status
    assert (good_id in _manifest(instance)["primary_paths"]) is in_library
    _assert_unavailable(instance, bad_id)
    result = getattr(manager, undo)(good_id)
    assert result["status"] == "completed" and result["changed"]
    assert manager.get(good_id)["status"] == "active"
    assert good_id in _manifest(instance)["primary_paths"]
    assert [r["document_id"] for r in instance.search("cura-retention-orchid")] == [good_id]
    _assert_unavailable(instance, bad_id)
    assert _files(instance.store.paths.originals) == originals
    after = _files(instance.store.paths.knowledge)
    assert {k: v for k, v in after.items() if not k.startswith("dispositions/")} == canonical


@pytest.mark.parametrize("after_publication", [False, True])
def test_faulted_retention_restores_disposition_and_views_with_unavailable_document(
    tmp_path, monkeypatch, after_publication
):
    instance, good_id, bad_id = _fixture(tmp_path)
    instance.rebuild_library()
    canonical = _files(instance.store.paths.knowledge)
    originals = _files(instance.store.paths.originals)
    library = _files(instance.store.paths.library)
    manager = DocumentRetentionManager(instance.store)
    sync = manager._sync_document_derived
    calls = []

    def fault_once(document_id):
        calls.append(document_id)
        if len(calls) == 1:
            if after_publication:
                sync(document_id)
            raise OSError("synthetic projection failure")
        return sync(document_id)

    monkeypatch.setattr(manager, "_sync_document_derived", fault_once)
    with pytest.raises(OSError, match="synthetic projection failure"):
        manager.trash(good_id)
    assert calls == [good_id, good_id]
    assert manager.get(good_id)["status"] == "active"
    assert _files(instance.store.paths.knowledge) == canonical
    assert _files(instance.store.paths.originals) == originals
    assert _files(instance.store.paths.library) == library
    assert [r["document_id"] for r in instance.search("cura-retention-orchid")] == [good_id]
    _assert_unavailable(instance, bad_id)


def test_corrupt_original_still_blocks_projection_before_publication(tmp_path):
    instance, _, bad_id = _fixture(tmp_path)
    before = _files(instance.store.paths.library)
    verified = DocumentContentReader(instance.store).verified_original(bad_id)
    original = instance.root / verified["original"]["storage_ref"]
    original.write_bytes(b"replaced bytes")
    with pytest.raises(DocumentContentError, match="hash or size"):
        DocumentContentReader(instance.store).get(bad_id, build_missing_bundle=True)
    with pytest.raises(LibraryProjectionError, match="deep validation"):
        instance.rebuild_library()
    assert _files(instance.store.paths.library) == before


def test_only_decode_unavailability_is_typed_and_container_limits_still_fail(tmp_path, monkeypatch):
    with pytest.raises(TextDecodingUnavailable):
        PlainTextExtractor().extract(b"\xff")
    instance, _, bad_id = _fixture(tmp_path)
    before = _files(instance.store.paths.library)

    def failed_build(*args, **kwargs):
        raise BundleBuildError("synthetic safety bound")

    monkeypatch.setattr(DocumentBundleManager, "build_version", failed_build)
    with pytest.raises(BundleBuildError, match="safety bound"):
        instance.rebuild_library()
    assert _files(instance.store.paths.library) == before
    with pytest.raises(BundleBuildError, match="safety bound"):
        DocumentContentReader(instance.store).get(bad_id, build_missing_bundle=True)


def test_actual_unsafe_archive_is_not_downgraded_to_missing_representation(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "i")
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "synthetic")
    instance.ingest(archive)
    document = instance.list_documents()[0]
    with pytest.raises(BundleBuildError, match="unsafe") as failure:
        DocumentContentReader(instance.store).get(document["id"], build_missing_bundle=True)
    assert not isinstance(failure.value, BundleTextUnavailable)
    assert not (tmp_path / "escape.txt").exists()


def test_actual_text_safety_limit_still_blocks_library_publication(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "i")
    text = tmp_path / "large.txt"
    text.write_bytes(b"a" * (MAX_EXTRACTED_CHARS + 1))
    instance.ingest(text)
    before = _files(instance.store.paths.library)
    with pytest.raises(BundleBuildError, match="safety limit") as failure:
        instance.rebuild_library()
    assert not isinstance(failure.value, BundleTextUnavailable)
    assert _files(instance.store.paths.library) == before
