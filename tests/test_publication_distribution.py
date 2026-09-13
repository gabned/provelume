from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

import pytest

from provelume.publication import (
    READY_NAME,
    RECEIPT_NAME,
    PublicationError,
    canonical_bytes,
    read_metadata,
)
from scripts.publication_dry_run import OfflinePublicRecord, exercise, synthetic_bundle
from scripts.publication_publish import GitHub, finalize, prepare
from scripts.publication_receipt import create_receipt, validate_asset_inventory
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


@pytest.mark.parametrize(
    "extra", ["unreviewed.exe", "publication-ready.json.sig", "PUBLICATION-READY.JSON"]
)
def test_receipt_rejects_unqualified_extra_or_alias_asset(tmp_path, extra):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public")
    (client.root / extra).write_bytes(b"unqualified")
    with pytest.raises(PublicationError, match="unexpected asset"):
        create_receipt(
            client.release(manifest["tag"]),
            bundle=bundle,
            resolved_commit=manifest["commit"],
            observed_at="2026-01-01T12:01:00Z",
        )


@pytest.mark.parametrize("phase", ["partial_payloads", "finalize", "completed_resume"])
def test_extra_public_asset_stops_recovery_before_any_upload(tmp_path, monkeypatch, phase):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public")
    stage = tmp_path / "stage"
    if phase == "partial_payloads":
        next(client.root.glob("*.whl")).unlink()
    else:
        prepare(bundle, stage, commit=manifest["commit"], client=client)
        if phase == "completed_resume":
            finalize(bundle, stage, client=client)
    (client.root / "unqualified.exe").write_bytes(b"outside qualified inventory")
    before = {p.name: p.read_bytes() for p in client.root.iterdir()}
    original_run = client.run

    def no_mutation(arguments, *, destination=None):
        assert arguments[0] == "api", "Unexpected inventory must stop before any upload"
        return original_run(arguments, destination=destination)

    monkeypatch.setattr(client, "run", no_mutation)
    with pytest.raises(PublicationError, match="unexpected asset"):
        if phase == "finalize":
            finalize(bundle, stage, client=client)
        else:
            prepare(bundle, tmp_path / "fresh-stage", commit=manifest["commit"], client=client)
    assert before == {p.name: p.read_bytes() for p in client.root.iterdir()}
    assert client.create_count == 0
    assert not (tmp_path / "fresh-stage" / READY_NAME).exists()


@pytest.mark.parametrize("insertion", ["kit_upload", "ready_upload"])
def test_asset_inserted_during_finalization_never_returns_ready(tmp_path, insertion):
    bundle, manifest = synthetic_bundle(tmp_path)
    kit_name = f"provelume-{manifest['version']}-installation-kit.zip"

    class ChangedInventory(OfflinePublicRecord):
        def run(self, arguments, *, destination=None):
            result = super().run(arguments, destination=destination)
            target = kit_name if insertion == "kit_upload" else READY_NAME
            if arguments[:2] == ["release", "upload"] and arguments[3].endswith(target):
                (self.root / "unreviewed.exe").write_bytes(b"concurrent extra")
            return result

    client = ChangedInventory(bundle, tmp_path / "public")
    stage = tmp_path / "stage"
    prepare(bundle, stage, commit=manifest["commit"], client=client)
    with pytest.raises(PublicationError, match="unexpected asset"):
        finalize(bundle, stage, client=client)
    assert (client.root / READY_NAME).exists() is (insertion == "ready_upload")
    before = {p.name: p.read_bytes() for p in client.root.iterdir()}
    # A marker already uploaded before the conflicting observation is not success.
    with pytest.raises(PublicationError, match="unexpected asset"):
        prepare(bundle, tmp_path / "resumed", commit=manifest["commit"], client=client)
    assert before == {p.name: p.read_bytes() for p in client.root.iterdir()}


@pytest.mark.parametrize("interrupted_asset", [RECEIPT_NAME, "kit", READY_NAME])
def test_all_generated_asset_interruptions_resume_exactly_without_overwrite(
    tmp_path, interrupted_asset
):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public", published=False)
    stage = tmp_path / "stage"
    prepare(bundle, stage, commit=manifest["commit"], client=client)
    original_receipt = read_metadata(stage / RECEIPT_NAME)
    client.fail_upload = (
        f"provelume-{manifest['version']}-installation-kit.zip"
        if interrupted_asset == "kit"
        else interrupted_asset
    )
    with pytest.raises(PublicationError, match="synthetic interrupted upload"):
        finalize(bundle, stage, client=client)
    assert not (client.root / READY_NAME).exists()
    partial = {p.name: p.read_bytes() for p in client.root.iterdir()}
    client.fail_upload = None
    resumed = tmp_path / "resumed"
    prepare(bundle, resumed, commit=manifest["commit"], client=client)
    result = finalize(bundle, resumed, client=client)
    assert result["status"] == "installation_kit_ready"
    assert partial.items() <= {p.name: p.read_bytes() for p in client.root.iterdir()}.items()
    if interrupted_asset != RECEIPT_NAME:
        assert read_metadata(client.root / RECEIPT_NAME) == original_receipt
    complete = {p.name: p.read_bytes() for p in client.root.iterdir()}
    prepare(bundle, tmp_path / "repeat", commit=manifest["commit"], client=client)
    finalize(bundle, tmp_path / "repeat", client=client)
    assert complete == {p.name: p.read_bytes() for p in client.root.iterdir()}
    assert set(complete) == {p.name for p in bundle.iterdir()} | {
        RECEIPT_NAME,
        READY_NAME,
        f"provelume-{manifest['version']}-installation-kit.zip",
    }
    assert client.create_count == 1


def test_inventory_requires_each_phase_payload_and_rejects_duplicate_names(tmp_path):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public")
    event = client.release(manifest["tag"])
    with pytest.raises(PublicationError, match="required asset is missing"):
        validate_asset_inventory(event, manifest, phase="finalization")
    event["assets"].append(dict(event["assets"][0]))
    with pytest.raises(PublicationError, match="assets collide"):
        validate_asset_inventory(event, manifest, phase="payloads")


@pytest.mark.parametrize("count", [101, 300])
def test_publisher_reads_complete_asset_pages_even_when_embedded_inventory_is_partial(
    monkeypatch, count
):
    monkeypatch.setattr(
        "scripts.publication_publish.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=canonical_bytes({"id": 42, "assets": []}), stderr=b""
        ),
    )
    expected = [{"id": index, "name": f"asset-{index}"} for index in range(count)]
    pages = []

    class PagedGitHub(GitHub):
        def run(self, arguments, *, destination=None):
            page = int(arguments[1].rsplit("=", 1)[1])
            pages.append(page)
            return canonical_bytes(expected[(page - 1) * 100 : page * 100])

    assert PagedGitHub().release("v0.11.0")["assets"] == expected
    assert pages == list(range(1, count // 100 + 2))


def test_publisher_cannot_silently_truncate_inventory_at_existing_bound(monkeypatch):
    monkeypatch.setattr(
        "scripts.publication_publish.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=canonical_bytes({"id": 42}), stderr=b""
        ),
    )

    class TooManyAssets(GitHub):
        def run(self, arguments, *, destination=None):
            return canonical_bytes([{"name": str(index)} for index in range(100)])

    with pytest.raises(PublicationError, match="inventory is invalid or incomplete"):
        TooManyAssets().release("v0.11.0")
