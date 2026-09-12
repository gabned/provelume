from __future__ import annotations

import json
import zipfile

import pytest

from provelume.publication import (
    READY_NAME,
    RECEIPT_NAME,
    PublicationError,
    canonical_bytes,
    read_metadata,
)
from scripts.publication_dry_run import OfflinePublicRecord, exercise, synthetic_bundle
from scripts.publication_publish import finalize, prepare
from scripts.publication_receipt import create_receipt
from scripts.release_kit import verify_kit


def test_same_production_path_recovers_interruption_without_republish_or_rebuild(tmp_path):
    bundle, _manifest = synthetic_bundle(tmp_path)
    result = exercise(bundle, tmp_path)
    assert result["status"] == "offline_dry_run_pass"
    assert result["publication_event"] == "explicitly_synthetic"
    assert result["actual_release_publication"] is False


def test_receipt_uses_actual_event_and_rejects_conflicting_reobservation(tmp_path):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public")
    event = client.release(manifest["tag"])
    raw = create_receipt(
        event, bundle=bundle, resolved_commit=manifest["commit"], observed_at="2026-01-01T12:01:00Z"
    )
    assert json.loads(raw)["published_at"] != manifest["built_at"]
    assert (
        create_receipt(
            event,
            bundle=bundle,
            resolved_commit=manifest["commit"],
            observed_at="2026-01-02T12:00:00Z",
            existing=raw,
        )
        == raw
    )
    event["published_at"] = "2026-01-01T12:00:01Z"
    with pytest.raises(PublicationError, match="conflicts"):
        create_receipt(
            event,
            bundle=bundle,
            resolved_commit=manifest["commit"],
            observed_at="2026-01-02T12:00:00Z",
            existing=raw,
        )


def test_existing_partial_core_upload_recovers_and_changed_asset_fails(tmp_path):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public")
    missing = next(client.root.glob("*.whl"))
    missing.unlink()
    prepare(bundle, tmp_path / "stage", commit=manifest["commit"], client=client)
    assert missing.read_bytes() == (bundle / missing.name).read_bytes()
    assert client.create_count == 0
    missing.write_bytes(b"unexpected existing asset")
    with pytest.raises(PublicationError, match="overwrite is forbidden"):
        prepare(bundle, tmp_path / "stage2", commit=manifest["commit"], client=client)
    assert not (client.root / READY_NAME).exists()


def test_changed_public_payload_during_finalization_never_creates_readiness(tmp_path):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public")
    stage = tmp_path / "stage"
    prepare(bundle, stage, commit=manifest["commit"], client=client)
    next(client.root.glob("*.exe")).write_bytes(b"changed after prepare")
    with pytest.raises(PublicationError, match="changed during finalization"):
        finalize(bundle, stage, client=client)
    assert not (client.root / READY_NAME).exists()


def test_kit_rejects_added_member_before_trusting_archive(tmp_path):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public")
    stage = tmp_path / "stage"
    prepare(bundle, stage, commit=manifest["commit"], client=client)
    kit = next(stage.glob("*.zip"))
    with zipfile.ZipFile(kit, "a") as archive:
        archive.writestr("../escape", b"unqualified")
    with pytest.raises(PublicationError, match="members differ"):
        verify_kit(kit, bundle=bundle, receipt=read_metadata(stage / RECEIPT_NAME))


def test_wrong_public_tag_stops_before_any_release_creation_or_upload(tmp_path):
    bundle, manifest = synthetic_bundle(tmp_path)

    class MovedTag(OfflinePublicRecord):
        def run(self, arguments, *, destination=None):
            assert arguments[0] == "api", "No mutation may follow a mismatched tag"
            return canonical_bytes({"sha": "b" * 40})

    client = MovedTag(bundle, tmp_path / "public", published=False)
    with pytest.raises(PublicationError, match="tag moved"):
        prepare(bundle, tmp_path / "stage", commit=manifest["commit"], client=client)
    assert client.create_count == 0
    assert list(client.root.iterdir()) == []


@pytest.mark.parametrize("invalid", ["development", "extra_file", "changed_payload"])
def test_invalid_qualified_input_stops_before_any_transport(tmp_path, invalid):
    bundle, manifest = synthetic_bundle(tmp_path)
    if invalid == "development":
        manifest["channel"] = "development"
        (bundle / "release-manifest.json").write_bytes(canonical_bytes(manifest))
    elif invalid == "extra_file":
        (bundle / "unqualified.txt").write_bytes(b"extra")
    else:
        next(bundle.glob("*.whl")).write_bytes(b"changed")

    class NoTransport:
        def __getattr__(self, name):
            pytest.fail(f"Invalid input reached transport method {name}")

    with pytest.raises(PublicationError):
        prepare(bundle, tmp_path / "stage", commit=manifest["commit"], client=NoTransport())
