from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from provelume.publication import READY_NAME, RECEIPT_NAME, file_identity
from provelume.updates import UpdateError, download_update, select_update_candidate
from scripts.publication_dry_run import OfflinePublicRecord, synthetic_bundle
from scripts.publication_publish import finalize, prepare


@pytest.fixture
def delivery(tmp_path):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public")
    stage = tmp_path / "stage"
    prepare(bundle, stage, commit=manifest["commit"], client=client)
    finalize(bundle, stage, client=client)
    installer = next(bundle.glob("*.exe"))
    update = {
        "schema_version": 2,
        "publication_required": True,
        **{
            key: manifest[key]
            for key in ("source_repository", "version", "tag", "commit", "channel")
        },
        "artifact": {
            **file_identity(installer),
            "platform": "windows",
            "architecture": "x86_64",
            "installer_type": "inno_setup",
            "minimum_windows_build": 19045,
            "automatic_apply": False,
        },
        "trust": {
            "publisher_authentication": "not_established",
            "platform_signature": "unsigned_preview",
        },
    }
    (client.root / "provelume-windows-update.json").write_text(json.dumps(update))
    return client, manifest


def select(client, manifest):
    return select_update_candidate(
        [client.release(manifest["tag"])],
        current_version="0.0.0",
        channel="preview",
        fetch_manifest=lambda url: json.loads((client.root / url.rsplit("/", 1)[-1]).read_bytes()),
        resolve_tag_commit=lambda _tag: manifest["commit"],
    )


@pytest.mark.parametrize("missing", [READY_NAME, RECEIPT_NAME, "release-manifest.json"])
def test_metadata_required_update_waits_for_complete_finalization(delivery, missing):
    client, manifest = delivery
    (client.root / missing).unlink()
    with pytest.raises(UpdateError) as failure:
        select(client, manifest)
    assert failure.value.code == "publication_pending"
    assert failure.value.stage == "release_manifest"


def test_update_checks_actual_publication_event_and_downloads_matching_sidecars(delivery, tmp_path):
    client, manifest = delivery
    candidate = select(client, manifest)
    assert candidate.publication_required is True
    calls = []

    class Downloader:
        def download(self, url, *, destination, expected_size, expected_sha256, progress=None):
            source = client.root / url.rsplit("/", 1)[-1]
            identity = file_identity(source)
            assert (identity["size_bytes"], identity["sha256"]) == (expected_size, expected_sha256)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            calls.append(source.name)
            return destination

    target = download_update(candidate, tmp_path / "download", client=Downloader())
    assert target.name.endswith(".exe")
    assert calls == [target.name, RECEIPT_NAME, "release-manifest.json"]
    client.event["published_at"] = "2026-01-01T12:00:01Z"
    with pytest.raises(UpdateError) as failure:
        select(client, manifest)
    assert failure.value.code == "publication_pending"


def test_download_failure_never_returns_an_installable_candidate(delivery, tmp_path):
    client, manifest = delivery
    candidate = select(client, manifest)

    class InterruptedDownloader:
        def download(self, url, *, destination, **kwargs):
            if url.endswith(RECEIPT_NAME):
                raise UpdateError("synthetic interrupted download")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(client.root / Path(url).name, destination)
            return destination

    with pytest.raises(UpdateError) as failure:
        download_update(candidate, tmp_path / "download", client=InterruptedDownloader())
    assert failure.value.stage == "installer_download"
