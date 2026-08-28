from __future__ import annotations

import json
import os
import posixpath
import re
from pathlib import Path, PurePosixPath

import pytest
from fastapi.testclient import TestClient

import provelume.library_projection as library_projection
from provelume.cli import main
from provelume.library_projection import (
    LIBRARY_MANIFEST,
    LibraryProjectionError,
    LibraryProjectionManager,
)
from provelume.locks import InstanceLockManager
from provelume.service import ProvelumeInstance
from provelume.web import create_app
from provelume.web_security import CONTENT_SECURITY_POLICY


def _authoritative_snapshot(instance: ProvelumeInstance) -> dict[str, bytes]:
    selected = [
        *(
            path
            for path in instance.store.paths.knowledge.rglob("*")
            if path.is_file()
        ),
        *(path for path in instance.store.paths.originals.rglob("*") if path.is_file()),
    ]
    return {
        path.relative_to(instance.root).as_posix(): path.read_bytes()
        for path in sorted(selected)
    }


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _seed_classified_library(
    tmp_path: Path,
) -> tuple[ProvelumeInstance, dict[str, dict[str, object]], dict[str, object]]:
    source = tmp_path / "source"
    (source / "other").mkdir(parents=True)
    (source / "alpha.md").write_text(
        "# Alpha\n\nPrimary authored Markdown.\n",
        encoding="utf-8",
    )
    (source / "other" / "alpha.md").write_text(
        "# Other Alpha\n\nA colliding display filename.\n",
        encoding="utf-8",
    )
    (source / "notes.txt").write_text(
        "Unclassified text remains navigable.\n",
        encoding="utf-8",
    )
    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Library fixture")
    instance.ingest(source, source_name="Fixture Source")
    documents = {
        str(item["locator"]): item for item in instance.list_documents()
    }
    work = instance.create_hierarchy_node("area", "Work")
    research = instance.create_hierarchy_node(
        "area",
        "Research",
        parent_id=str(work["id"]),
    )
    project = instance.create_hierarchy_node(
        "project",
        "Atlas",
        parent_id=str(research["id"]),
    )
    collection = instance.create_hierarchy_node("collection", "References")
    instance.classify_document(
        str(documents["alpha.md"]["id"]),
        str(project["id"]),
        secondary_node_ids=[str(collection["id"])],
    )
    instance.classify_document(
        str(documents["other/alpha.md"]["id"]),
        str(research["id"]),
        secondary_node_ids=[str(collection["id"])],
    )
    return instance, documents, collection


def test_library_projection_is_deterministic_linked_and_canonical_safe(
    tmp_path: Path,
) -> None:
    instance, documents, collection = _seed_classified_library(tmp_path)
    canonical_before = _authoritative_snapshot(instance)

    first = instance.rebuild_library()
    first_tree = _tree_snapshot(instance.store.paths.library)
    second = instance.rebuild_library()
    second_tree = _tree_snapshot(instance.store.paths.library)

    assert first["status"] == "completed"
    assert first["canonical_before"] == first["canonical_after"]
    assert first["canonical_mutation"] == "none"
    assert first["network_used"] is False
    assert first["ai_used"] is False
    assert first["content_fingerprint"] == second["content_fingerprint"]
    assert first_tree == second_tree
    assert _authoritative_snapshot(instance) == canonical_before

    library = instance.store.paths.library
    for relative in (
        "README.md",
        "areas/README.md",
        "projects/README.md",
        "archive/README.md",
        "unclassified/README.md",
        "views/collections/README.md",
        "views/tags/README.md",
        "views/people/README.md",
        "views/sources/README.md",
        "views/dates/README.md",
        "views/types/README.md",
        LIBRARY_MANIFEST,
    ):
        assert (library / relative).is_file()

    manifest = json.loads((library / LIBRARY_MANIFEST).read_text(encoding="utf-8"))
    primary_paths = manifest["primary_paths"]
    assert len(primary_paths) == 3
    assert len(set(primary_paths.values())) == 3
    assert primary_paths[str(documents["alpha.md"]["id"])].startswith("projects/")
    assert primary_paths[str(documents["other/alpha.md"]["id"])].startswith("areas/")
    assert primary_paths[str(documents["notes.txt"]["id"])].startswith(
        "unclassified/"
    )
    assert all(re.search(r"--[0-9a-f]{32}\.md\Z", path) for path in primary_paths.values())

    document_markdown = [
        path
        for path in library.rglob("*.md")
        if path.name != "README.md"
    ]
    assert len(document_markdown) == len(primary_paths)
    projected_alpha = library / primary_paths[str(documents["alpha.md"]["id"])]
    assert "Primary authored Markdown." in projected_alpha.read_text(encoding="utf-8")
    assert "provelume_projection_is_canonical: false" in projected_alpha.read_text(
        encoding="utf-8"
    )

    collection_path = (
        library
        / "views"
        / "collections"
        / str(collection["slug"])
        / "README.md"
    )
    collection_index = collection_path.read_text(encoding="utf-8")
    for locator in ("alpha.md", "other/alpha.md"):
        target = primary_paths[str(documents[locator]["id"])]
        expected = posixpath.relpath(
            target,
            start=collection_path.parent.relative_to(library).as_posix(),
        )
        assert f"]({expected})" in collection_index
    assert "Primary authored Markdown." not in collection_index

    assert not any(path.is_symlink() for path in library.rglob("*"))
    assert instance.library_status()["status"] == "ready"

    (library / "README.md").write_text("external projection edit\n", encoding="utf-8")
    assert instance.library_status()["status"] == "modified"
    assert _authoritative_snapshot(instance) == canonical_before
    repaired = instance.rebuild_library()
    assert repaired["content_fingerprint"] == first["content_fingerprint"]
    assert _tree_snapshot(library) == first_tree


def test_failed_staged_replacement_restores_the_previous_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _documents, _collection = _seed_classified_library(tmp_path)
    manager = LibraryProjectionManager(instance.store)
    manager.rebuild()
    expected = _tree_snapshot(manager.root)
    canonical_before = _authoritative_snapshot(instance)
    real_replace = os.replace

    def fail_staging_commit(source: str | Path, target: str | Path) -> None:
        source_path = Path(source)
        target_path = Path(target)
        if source_path.name.startswith(".library-building-") and target_path == manager.root:
            raise OSError("synthetic staged commit failure")
        real_replace(source, target)

    monkeypatch.setattr(library_projection.os, "replace", fail_staging_commit)

    with pytest.raises(LibraryProjectionError, match="staged replacement failed"):
        manager.rebuild()

    assert _tree_snapshot(manager.root) == expected
    assert manager.status()["status"] == "ready"
    assert _authoritative_snapshot(instance) == canonical_before
    lock_root = instance.store.paths.state / "locks"
    assert not list(lock_root.glob(".library-building-*"))
    assert not list(lock_root.glob(".library-previous-*"))


def test_staging_creation_failure_releases_the_library_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _documents, _collection = _seed_classified_library(tmp_path)
    manager = LibraryProjectionManager(instance.store)

    def fail_staging(*_args: object, **_kwargs: object) -> str:
        raise OSError("synthetic staging allocation failure")

    monkeypatch.setattr(library_projection.tempfile, "mkdtemp", fail_staging)

    with pytest.raises(LibraryProjectionError, match="staging allocation failure"):
        manager.rebuild()

    assert InstanceLockManager(instance.store).inspect("derived-rebuild") is None
    assert not manager.root.exists()


def test_staged_validation_and_unsafe_target_preserve_previous_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _documents, _collection = _seed_classified_library(tmp_path)
    manager = LibraryProjectionManager(instance.store)
    manager.rebuild()
    expected = _tree_snapshot(manager.root)
    real_write_staging = manager._write_staging

    def corrupt_staging(
        staging: Path,
        files: dict[PurePosixPath, bytes],
        manifest: dict[str, object],
    ) -> None:
        real_write_staging(staging, files, manifest)
        (staging / "README.md").write_text("incomplete staged tree\n", encoding="utf-8")

    monkeypatch.setattr(manager, "_write_staging", corrupt_staging)
    with pytest.raises(LibraryProjectionError, match="before commit"):
        manager.rebuild()

    assert _tree_snapshot(manager.root) == expected
    assert manager.status()["status"] == "ready"
    assert not list(
        (instance.store.paths.state / "locks").glob(".library-building-*")
    )

    blocked = ProvelumeInstance.initialise(tmp_path / "blocked")
    blocked.store.paths.library.write_bytes(b"operator-owned regular file\n")
    with pytest.raises(LibraryProjectionError, match="not a safe directory"):
        blocked.rebuild_library()
    assert blocked.store.paths.library.read_bytes() == b"operator-owned regular file\n"
    assert InstanceLockManager(blocked.store).inspect("derived-rebuild") is None


def test_empty_projection_and_symlink_status_are_bounded(tmp_path: Path) -> None:
    empty = ProvelumeInstance.initialise(tmp_path / "empty", name="Empty library")
    result = empty.rebuild_library()

    assert result["documents"] == 0
    assert empty.library_status()["status"] == "ready"
    assert (empty.store.paths.library / "archive" / "README.md").is_file()

    linked = ProvelumeInstance.initialise(tmp_path / "linked")
    linked.store.paths.library.symlink_to(
        tmp_path / "missing-library-target",
        target_is_directory=True,
    )
    assert linked.library_status()["status"] == "invalid"
    assert linked.library_status()["reason"] == "library_path_invalid"


def test_viewer_blocks_active_html_links_and_resource_loading(tmp_path: Path) -> None:
    source = tmp_path / "hostile.md"
    original = (
        "# Safe heading\n\n"
        "<script>alert('active')</script>\n\n"
        "<iframe src=\"file:///etc/passwd\"></iframe>\n\n"
        "![remote](https://example.invalid/tracker.png)\n\n"
        "[local](file:///etc/passwd) [run](javascript:alert(1))\n"
    )
    source.write_text(original, encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    document = instance.list_documents()[0]
    client = TestClient(create_app(instance.root))

    rendered = client.get(f"/documents/{document['id']}")

    assert rendered.status_code == 200
    assert rendered.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "<h1>Safe heading</h1>" in rendered.text
    assert "&lt;script&gt;alert" in rendered.text
    assert "<script" not in rendered.text.casefold()
    assert "<iframe" not in rendered.text.casefold()
    assert "javascript:" not in rendered.text.casefold()
    assert 'src="file:///' not in rendered.text.casefold()
    assert 'href="file:///' not in rendered.text.casefold()
    assert 'src="https://' not in rendered.text.casefold()
    assert "blocked-resource" in rendered.text
    assert "blocked-link" in rendered.text

    raw = client.get(
        f"/documents/{document['id']}",
        params={"mode": "raw"},
    )
    assert raw.status_code == 200
    assert "&lt;script&gt;alert" in raw.text
    original_page = client.get(
        f"/documents/{document['id']}",
        params={"mode": "original"},
    )
    assert original_page.status_code == 200
    assert "&lt;script&gt;alert" in original_page.text
    assert client.get(
        f"/documents/{document['id']}",
        params={"mode": "unsupported"},
    ).status_code == 400

    raw_api = client.get(f"/api/v1/documents/{document['id']}/content")
    assert raw_api.status_code == 200
    assert raw_api.text == original
    assert raw_api.headers["content-type"].startswith("text/plain")
    exact_original = client.get(f"/api/v1/documents/{document['id']}/original")
    assert exact_original.content == original.encode("utf-8")
    assert "attachment" in exact_original.headers["content-disposition"]
    assert exact_original.headers["x-provelume-original-sha256"] == document[
        "current_version"
    ]["content_hash"]
    assert not instance.store.paths.library.exists()
    assert not (instance.root / "state" / "derived" / "bundles").exists()

    original_record = instance.store.read_canonical(
        "originals",
        str(document["current_version"]["original_id"]),
    )
    assert original_record is not None
    original_path = instance.store.paths.root / str(original_record["storage_ref"])
    original_path.write_bytes(b"tampered")
    assert client.get(f"/api/v1/documents/{document['id']}/original").status_code == 409


def test_viewer_preserves_a_utf8_bom_in_raw_and_original_text(tmp_path: Path) -> None:
    source = tmp_path / "bom.md"
    authored = b"\xef\xbb\xbf# Authored with BOM\n"
    source.write_bytes(authored)
    instance = ProvelumeInstance.initialise(tmp_path / "instance-bom")
    instance.ingest(source)
    document = instance.list_documents()[0]
    client = TestClient(create_app(instance.root))

    assert client.get(
        f"/api/v1/documents/{document['id']}/content",
        params={"mode": "raw"},
    ).content == authored
    assert client.get(
        f"/api/v1/documents/{document['id']}/content",
        params={"mode": "original"},
    ).content == authored
    assert client.get(f"/api/v1/documents/{document['id']}/original").content == authored


def test_library_cli_api_and_coordinated_rebuild_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "note.txt"
    source.write_text("Coordinated library evidence.\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    root = str(instance.root)

    assert main(["library-rebuild", root]) == 0
    rebuilt = json.loads(capsys.readouterr().out)
    assert rebuilt["status"] == "completed"
    assert main(["library-status", root]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"

    client = TestClient(create_app(instance.root))
    library = client.get("/api/v1/library")
    assert library.status_code == 200
    assert library.json()["status"] == "ready"
    assert client.post("/api/v1/library").status_code == 405

    report = instance.store.knowledge_fingerprint()
    from provelume.rebuild import DerivedRebuildManager

    coordinated = DerivedRebuildManager(instance.store).run("agreement")
    assert coordinated["status"] == "completed"
    assert coordinated["agreement"] is True
    assert coordinated["final_snapshot"]["counts"]["library_ready"] is True
    assert coordinated["metrics"]["library_rebuilds"] == 2
    assert instance.store.knowledge_fingerprint() == report


def test_projection_manifest_paths_are_portable(tmp_path: Path) -> None:
    instance, _documents, _collection = _seed_classified_library(tmp_path)
    instance.rebuild_library()
    manifest = json.loads(
        (instance.store.paths.library / LIBRARY_MANIFEST).read_text(encoding="utf-8")
    )

    for item in manifest["files"]:
        path = item["path"]
        pure = PurePosixPath(path)
        assert not pure.is_absolute()
        assert ".." not in pure.parts
        assert "\\" not in path
        assert all(
            not set('<>:"/\\|?*').intersection(part)
            for part in pure.parts
        )

    first_document_id = next(iter(manifest["primary_paths"]))
    manifest["primary_paths"][first_document_id] = "README.md"
    (instance.store.paths.library / LIBRARY_MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert instance.library_status()["status"] == "invalid"
