from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import provelume.bundles as bundle_module
from provelume.bundles import BundleBuildError, DocumentBundleManager
from provelume.service import ProvelumeInstance


class _CountingImages:
    def __init__(self, total: int):
        self.total = total
        self.inspected = 0

    def __iter__(self):
        for index in range(self.total):
            self.inspected += 1
            yield SimpleNamespace(name=f"asset-{index}.bin", data=b"xx")


class _FakePage:
    def __init__(self, text: str, images=None):
        self.text = text
        self.images = images if images is not None else ()

    def extract_text(self) -> str:
        return self.text


class _FakeReader:
    is_encrypted = False

    def __init__(self, pages):
        self.pages = pages


def test_pdf_text_limit_is_aggregate_across_pages(tmp_path: Path, monkeypatch) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    pages = [_FakePage("abcdefgh"), _FakePage("ijklmnop")]
    monkeypatch.setattr(bundle_module, "PdfReader", lambda _stream: _FakeReader(pages))
    monkeypatch.setattr(bundle_module, "MAX_BUNDLE_TEXT_CHARS", 10)

    extracted, _assets, warnings = DocumentBundleManager(instance.store)._pdf_pages(b"pdf")

    assert sum(len(page["text"]) for page in extracted) == 10
    assert extracted[0]["text"] == "abcdefgh"
    assert extracted[1]["text"] == "ij"
    assert extracted[1]["extraction_status"] == "truncated"
    assert any("aggregate bundle text safety limit" in warning for warning in warnings)


def test_pdf_asset_candidates_are_inspected_lazily_and_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    images = _CountingImages(total=1000)
    pages = [_FakePage("", images=images)]
    monkeypatch.setattr(bundle_module, "PdfReader", lambda _stream: _FakeReader(pages))
    monkeypatch.setattr(bundle_module, "MAX_INSPECTED_ASSET_CANDIDATES", 3)
    monkeypatch.setattr(bundle_module, "MAX_ASSET_BYTES", 1)

    _pages, assets, warnings = DocumentBundleManager(instance.store)._pdf_pages(b"pdf")

    assert images.inspected == 3
    assert assets == []
    assert any("candidate-count safety limit" in warning for warning in warnings)


def test_bundle_verification_rejects_version_size_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("version-size assurance\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest_run(source)
    document = instance.store.list_canonical("documents")[0]
    version_id = document["current_version_id"]
    version = instance.store.read_canonical("versions", version_id)
    assert version is not None
    version["size_bytes"] = int(version["size_bytes"]) + 1
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("versions") / f"{version_id}.json",
        version,
    )

    with pytest.raises(BundleBuildError, match="Original verification failed"):
        DocumentBundleManager(instance.store).build_document(document["id"])

    assert not (instance.root / "state" / "derived" / "bundles").exists()
    operation = DocumentBundleManager(instance.store).operations.list(kind="bundle.build")[0]
    assert operation["status"] == "failed"
