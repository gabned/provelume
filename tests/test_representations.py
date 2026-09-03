from __future__ import annotations

import copy
import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.instance_backup import create_backup, extract_backup, verify_backup
from provelume.instance_validation import inspect_instance
from provelume.representations import (
    ANCHOR_KINDS,
    RESERVED_ANCHOR_KINDS,
    SUPPORT_OPERATIONS,
    SUPPORT_REASON_CODES,
    RepresentationBundleManager,
    RepresentationContractError,
    RepresentationReadModel,
    build_representation_bundle,
    canonical_json_bytes,
    output_fingerprint,
    representation_id,
    validate_representation_bundle,
)
from provelume.service import ProvelumeInstance
from provelume.storage import CANONICAL_KINDS, InstanceStore
from provelume.web import create_app


def _seed(tmp_path: Path) -> tuple[ProvelumeInstance, str]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text(
        "Universal derived evidence remains attributable.\n", encoding="utf-8"
    )
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    version_id = str(instance.store.list_canonical("versions")[0]["id"])
    return instance, version_id


def _snapshots(store: InstanceStore) -> tuple[dict[str, list[dict]], dict[str, bytes]]:
    canonical = {kind: store.list_canonical(kind) for kind in CANONICAL_KINDS}
    originals = {
        str(record["id"]): store.original_bytes(str(record["id"]))
        for record in store.list_canonical("originals")
    }
    return canonical, originals


def _implementation() -> dict[str, object]:
    return {
        "component": "provelume.core",
        "component_version": "0.9.0",
        "adapter": "synthetic-conformance",
        "adapter_version": "1",
        "settings": {"mode": "offline"},
    }


def _materialize(
    instance: ProvelumeInstance,
    version_id: str,
    *,
    recipe_version: str = "1",
    previous: tuple[str, ...] = (),
) -> dict:
    return RepresentationBundleManager(instance.store).materialize(
        version_id,
        recipe_id="provelume.synthetic-conformance",
        recipe_version=recipe_version,
        recipe_settings={"normalization": "none"},
        output_payloads={"summary.txt": ("text/plain", b"derived fixture\n")},
        implementation=_implementation(),
        warnings=("synthetic_fixture",),
        anchor_targets=(
            {"kind": "page", "page": 1},
            {"kind": "time", "start_ms": 0, "end_ms": 1000},
            {"kind": "region", "page": 1, "x": 0, "y": 0, "width": 10, "height": 10},
            {"kind": "slide", "reserved": True},
            {"kind": "sheet", "reserved": True},
            {"kind": "cell", "reserved": True},
            {"kind": "member", "reserved": True},
            {"kind": "symbol", "reserved": True},
        ),
        previous_representation_ids=previous,
        created_at="2026-09-02T00:00:00+00:00",
    )


def test_schema_round_trip_identity_anchors_and_reversible_corrections(
    tmp_path: Path,
) -> None:
    instance, version_id = _seed(tmp_path)
    version = instance.store.read_canonical("versions", version_id)
    assert version is not None
    original = instance.store.read_canonical("originals", str(version["original_id"]))
    assert original is not None
    output = {
        "id": "rout_" + "1" * 64,
        "media_type": "text/plain",
        "storage_ref": "state/derived/fixtures/output.txt",
        "sha256": "2" * 64,
        "size_bytes": 10,
    }
    bundle = build_representation_bundle(
        version={
            "id": version_id,
            "original_id": original["id"],
            "original_sha256": original["sha256"],
            "original_size_bytes": original["size_bytes"],
        },
        recipe_id="provelume.synthetic-conformance",
        recipe_version="1",
        recipe_settings={"mode": "fixture"},
        outputs=(output,),
        implementation=_implementation(),
        anchor_targets=(
            {"kind": "page", "page": 1},
            {"kind": "time", "start_ms": 10, "end_ms": 20},
            {"kind": "region", "page": 1, "x": 1, "y": 2, "width": 3, "height": 4},
            {"kind": "slide", "reserved": True},
            {"kind": "sheet", "reserved": True},
            {"kind": "cell", "reserved": True},
            {"kind": "member", "reserved": True},
            {"kind": "symbol", "reserved": True},
        ),
        created_at="2026-09-02T00:00:00+00:00",
    )
    anchor = bundle["anchors"][0]
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

    encoded = canonical_json_bytes(validate_representation_bundle(bundle))
    decoded = json.loads(encoded)

    assert validate_representation_bundle(decoded) == bundle
    assert {item["kind"] for item in bundle["anchors"]} == set(ANCHOR_KINDS)
    assert all(
        item["target"]["reserved"] is True
        for item in bundle["anchors"]
        if item["kind"] in RESERVED_ANCHOR_KINDS
    )
    assert bundle["corrections"][0]["reversible"] is True
    assert bundle["representation_id"] == representation_id(
        version_id=version_id,
        original_sha256=str(original["sha256"]),
        recipe_sha256=str(bundle["recipe"]["fingerprint"]),
        output_sha256=output_fingerprint(bundle["outputs"]),
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (
            lambda bundle: bundle.update({"representation_id": "repr_" + "0" * 64}),
            "representation_identity_mismatch",
        ),
        (
            lambda bundle: bundle["outputs"][0].update({"storage_ref": "../../Original"}),
            "representation_path_unsafe",
        ),
        (
            lambda bundle: bundle["outputs"][0].update(
                {"storage_ref": "state/derived/representations/e\u0301.txt"}
            ),
            "representation_path_unsafe",
        ),
        (
            lambda bundle: bundle["outputs"][0].update({"size_bytes": "10"}),
            "representation_limit_exceeded",
        ),
        (
            lambda bundle: bundle["anchors"][0].update({"version_id": "ver_other"}),
            "representation_invalid",
        ),
        (
            lambda bundle: bundle.update(
                {
                    "availability": {
                        "state": "degraded",
                        "reason": None,
                        "missing_component": None,
                    }
                }
            ),
            "representation_invalid",
        ),
        (
            lambda bundle: bundle["limits"].update({"max_path_chars": 1}),
            "representation_path_unsafe",
        ),
        (
            lambda bundle: bundle["limits"].update({"max_segment_chars": 1}),
            "representation_path_unsafe",
        ),
        (
            lambda bundle: bundle["lifecycle"].update({"created_at": "2026-09-02T00:00:00"}),
            "representation_invalid",
        ),
        (lambda bundle: bundle["invariants"].update({"ai_used": True}), "representation_invalid"),
    ),
)
def test_negative_contract_fixtures_fail_closed(tmp_path: Path, mutation, code: str) -> None:
    instance, version_id = _seed(tmp_path)
    bundle = _materialize(instance, version_id)
    invalid = copy.deepcopy(bundle)
    mutation(invalid)

    with pytest.raises(RepresentationContractError) as caught:
        validate_representation_bundle(invalid)

    assert caught.value.code == code


def test_collision_and_reserved_anchor_claims_are_rejected(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    bundle = _materialize(instance, version_id)
    duplicate = copy.deepcopy(bundle)
    duplicate["outputs"].append(copy.deepcopy(duplicate["outputs"][0]))

    with pytest.raises(RepresentationContractError, match="paths must be unique"):
        validate_representation_bundle(duplicate)

    reserved = copy.deepcopy(bundle)
    selected = next(item for item in reserved["anchors"] if item["kind"] == "slide")
    selected["target"] = {"reserved": True, "slide": 1}
    with pytest.raises(RepresentationContractError, match="explicitly reserved"):
        validate_representation_bundle(reserved)


def test_remove_equivalent_rebuild_and_new_recipe_preserve_history(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    canonical_before, originals_before = _snapshots(instance.store)
    first = _materialize(instance, version_id)
    manager = RepresentationBundleManager(instance.store)
    first_id = str(first["representation_id"])

    receipt = manager.remove(first_id, removed_at="2026-09-02T00:01:00+00:00")
    assert manager.get(first_id) is None
    assert receipt["bundle"]["lifecycle"]["state"] == "removed"
    rebuilt = manager.rebuild(first_id, {"summary.txt": b"derived fixture\n"})
    assert rebuilt == first

    second = _materialize(
        instance,
        version_id,
        recipe_version="2",
        previous=(first_id,),
    )
    assert second["representation_id"] != first_id
    assert second["provenance"]["previous_representation_ids"] == [first_id]
    assert manager.get(first_id) == first
    assert _snapshots(instance.store) == (canonical_before, originals_before)


def test_anchor_resolution_is_exact_to_version_and_representation(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    bundle = _materialize(instance, version_id)
    other = copy.deepcopy(bundle)
    other["anchors"][0]["representation_id"] = "repr_" + "9" * 64
    with pytest.raises(RepresentationContractError, match="anchor is invalid"):
        validate_representation_bundle(other)


def test_bundle_availability_uses_closed_reason_and_missing_component(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    first = _materialize(instance, version_id)
    unavailable = build_representation_bundle(
        version=first["version"],
        recipe_id="provelume.unavailable-conformance",
        recipe_version="1",
        recipe_settings={},
        outputs=first["outputs"],
        implementation=_implementation(),
        availability_state="unavailable",
        availability_reason="component_missing",
        missing_component="synthetic-local-component",
        created_at="2026-09-02T00:02:00+00:00",
    )

    assert unavailable["availability"] == {
        "state": "unavailable",
        "reason": "component_missing",
        "missing_component": "synthetic-local-component",
    }


def test_support_registry_is_independent_effective_closed_and_ai_unavailable(
    tmp_path: Path,
) -> None:
    instance, _version_id = _seed(tmp_path)
    support = instance.representation_support()
    records = support["records"]

    assert support["operations"] == list(SUPPORT_OPERATIONS)
    assert support["reason_codes"] == list(SUPPORT_REASON_CODES)
    assert len(records) % len(SUPPORT_OPERATIONS) == 0
    for profile_id in {record["profile_id"] for record in records}:
        profile = [record for record in records if record["profile_id"] == profile_id]
        assert {record["operation"] for record in profile} == set(SUPPORT_OPERATIONS)
    original = next(
        record
        for record in records
        if record["profile_id"] == "universal-original-v1" and record["operation"] == "preserve"
    )
    original_extract = next(
        record
        for record in records
        if record["profile_id"] == "universal-original-v1" and record["operation"] == "extract"
    )
    assert original["effective_state"] == "available"
    assert original_extract["effective_state"] == "unavailable"
    assert all(
        record["effective_state"] == "unavailable"
        and record["reason"] == "not_implemented"
        and record["missing_component"] is None
        for record in records
        if record["operation"] == "ai_enrich"
    )
    ocr = next(
        record
        for record in records
        if record["profile_id"] == "lectio-local-ocr-v1" and record["operation"] == "local_enrich"
    )
    assert ocr["declared_state"] == "optional"
    assert ocr["effective_state"] == "unavailable"
    assert ocr["reason"] == "disabled_by_configuration"
    degraded = next(record for record in records if record["effective_state"] == "degraded")
    assert degraded["reason"] in SUPPORT_REASON_CODES
    assert degraded["missing_component"] is None
    assert support["network_used"] is False
    assert support["mutated"] is False


@pytest.mark.parametrize("platform_contract", ("ubuntu", "windows"))
def test_disabled_offline_read_model_never_opens_a_network_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    platform_contract: str,
) -> None:
    instance, _version_id = _seed(tmp_path)

    def reject_network(*_args, **_kwargs):
        raise AssertionError(f"{platform_contract} offline read model attempted network access")

    client = TestClient(create_app(instance.root))
    with client:
        # Start AnyIO's in-process ASGI transport before blocking application
        # socket use. On Windows the event loop implements its private wake-up
        # socketpair with a loopback connect; that transport detail is not an
        # outbound request by the representation read model.
        monkeypatch.setattr(socket, "create_connection", reject_network)
        monkeypatch.setattr(socket.socket, "connect", reject_network)

        service = instance.representation_read_model()
        assert main(["representation-support", str(instance.root)]) == 0
        cli = json.loads(capsys.readouterr().out)
        api = client.get("/api/v1/representations/support")
        browser = client.get("/representations")

    assert service["network_used"] is False
    assert cli["network_used"] is False
    assert api.status_code == 200 and api.json()["network_used"] is False
    assert browser.status_code == 200


def test_enabled_ocr_support_probe_is_read_only(tmp_path: Path) -> None:
    instance, _version_id = _seed(tmp_path)
    settings = replace(instance.ocr.configured_settings(), mode="automatic")
    instance.ocr.configure(settings)

    def snapshot() -> list[tuple[str, int, bytes | None]]:
        return [
            (
                path.relative_to(instance.root).as_posix(),
                path.lstat().st_mode,
                path.read_bytes() if path.is_file() else None,
            )
            for path in sorted(instance.root.rglob("*"))
        ]

    before = snapshot()
    support = instance.representation_support(profile_id="lectio-local-ocr-v1")
    after = snapshot()

    assert support["network_used"] is False
    assert support["mutated"] is False
    assert after == before


def test_lectio_compatibility_view_is_complete_and_byte_unchanged(tmp_path: Path) -> None:
    instance, _version_id = _seed(tmp_path)
    before = {
        path.relative_to(instance.root).as_posix(): path.read_bytes()
        for path in instance.root.rglob("*")
        if path.is_file()
    }

    compatibility = RepresentationReadModel(instance.store).compatibility()

    assert {item["compatibility_id"] for item in compatibility} == {
        "document-extraction",
        "local-ocr",
        "email-intake",
        "google-readonly",
        "transcript-srt",
        "transcript-webvtt",
        "cross-source-findings",
    }
    assert all(item["source_byte_unchanged"] for item in compatibility)
    assert all(item["migration_performed"] is False for item in compatibility)
    assert (
        next(item for item in compatibility if item["compatibility_id"] == "document-extraction")[
            "records_visible"
        ]
        == 1
    )
    after = {
        path.relative_to(instance.root).as_posix(): path.read_bytes()
        for path in instance.root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_service_cli_api_and_browser_share_one_read_model(tmp_path: Path, capsys) -> None:
    instance, version_id = _seed(tmp_path)
    materialized = _materialize(instance, version_id)
    expected = instance.representation_read_model()

    assert main(["representations", str(instance.root)]) == 0
    cli = json.loads(capsys.readouterr().out)
    client = TestClient(create_app(instance.root))
    api = client.get("/api/v1/representations")
    browser = client.get("/representations")
    detail = client.get(f"/api/v1/representations/{materialized['representation_id']}")

    assert cli == expected
    assert api.status_code == 200 and api.json() == expected
    assert detail.status_code == 200
    assert detail.json() == instance.get_representation(materialized["representation_id"])
    assert browser.status_code == 200
    assert "Representations &amp; support" in browser.text
    assert "AI" not in browser.text or "ai_enrich" in browser.text
    assert "not_implemented" in browser.text
    assert client.post("/api/v1/representations", json={}).status_code == 405
    assert expected["network_used"] is False and expected["mutated"] is False


def test_backup_restore_portable_transfer_and_deep_validation(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    representation = _materialize(instance, version_id)
    selected_id = str(representation["representation_id"])
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    backup = create_backup(
        instance.store,
        destination=tmp_path / "backups",
        reason="representation-conformance",
    )
    assert verify_backup(backup["archive"])["status"] == "valid"
    restored_root = tmp_path / "restored"
    extract_backup(backup["archive"], restored_root)
    restored = InstanceStore(restored_root)
    assert inspect_instance(restored_root, deep=True)["status"] == "valid"
    assert RepresentationBundleManager(restored).get(selected_id) == representation

    exported = instance.export_portable(tmp_path / "portable.zip")
    assert exported["status"] == "completed"
    target = ProvelumeInstance.initialise(tmp_path / "target")
    imported = target.import_portable(tmp_path / "portable.zip")
    assert imported["status"] == "imported"
    assert inspect_instance(target.root, deep=True)["status"] == "valid"
    assert RepresentationBundleManager(target.store).get(selected_id) == representation


def test_deep_validation_rejects_tampered_representation_without_original_mutation(
    tmp_path: Path,
) -> None:
    instance, version_id = _seed(tmp_path)
    bundle = _materialize(instance, version_id)
    _canonical_before, originals_before = _snapshots(instance.store)
    output = instance.root / bundle["outputs"][0]["storage_ref"]
    output.write_bytes(b"tampered")

    report = inspect_instance(instance.root, deep=True)

    assert report["status"] == "invalid"
    assert "representation_state_invalid" in {item["code"] for item in report["errors"]}
    assert _snapshots(instance.store)[1] == originals_before


def test_deep_validation_rejects_bundle_without_canonical_version(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    existing = _materialize(instance, version_id)
    fake = copy.deepcopy(existing)
    fake["version"]["id"] = "ver_missing"
    fake_id = representation_id(
        version_id="ver_missing",
        original_sha256=fake["version"]["original_sha256"],
        recipe_sha256=fake["recipe"]["fingerprint"],
        output_sha256=fake["output_fingerprint"],
    )
    fake["representation_id"] = fake_id
    fake["provenance"]["derived_from_version_id"] = "ver_missing"
    for output in fake["outputs"]:
        output["storage_ref"] = (
            f"state/derived/representations/{fake_id}/outputs/{Path(output['storage_ref']).name}"
        )
    for anchor in fake["anchors"]:
        anchor["version_id"] = "ver_missing"
        anchor["representation_id"] = fake_id
    validate_representation_bundle(fake)

    root = instance.root / "state" / "derived" / "representations" / fake_id
    (root / "outputs").mkdir(parents=True)
    for output in fake["outputs"]:
        source = instance.root / existing["outputs"][0]["storage_ref"]
        (root / "outputs" / Path(output["storage_ref"]).name).write_bytes(source.read_bytes())
    (root / "bundle.json").write_bytes(canonical_json_bytes(fake))

    manager = RepresentationBundleManager(instance.store)
    assert manager.get(fake_id) is None
    report = inspect_instance(instance.root, deep=True)
    assert report["status"] == "invalid"
    assert "representation_state_invalid" in {item["code"] for item in report["errors"]}


def test_deep_validation_rejects_tampered_removal_history(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    bundle = _materialize(instance, version_id)
    selected_id = str(bundle["representation_id"])
    manager = RepresentationBundleManager(instance.store)
    manager.remove(selected_id, removed_at="2026-09-02T00:01:00+00:00")
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    receipt_path = manager.history / f"{selected_id}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["original_mutated"] = True
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    report = inspect_instance(instance.root, deep=True)
    assert report["status"] == "invalid"
    assert "representation_history_invalid" in {item["code"] for item in report["errors"]}


def test_public_contract_files_are_first_party_and_json_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "core/provelume/representation_bundle.schema.json").read_text(encoding="utf-8")
    )
    registry_schema = json.loads(
        (root / "core/provelume/representation-support-registry.schema.json").read_text(
            encoding="utf-8"
        )
    )
    registry = json.loads(
        (root / "core/provelume/representation-support-registry.json").read_text(encoding="utf-8")
    )
    compatibility = json.loads(
        (root / "core/provelume/lectio-representation-compatibility.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["schema_version"]["const"] == 1
    assert "availability" in schema["required"]
    reserved_anchor_rule = schema["properties"]["anchors"]["items"]["allOf"][3]
    assert reserved_anchor_rule["then"]["properties"]["target"]["const"] == {"reserved": True}
    activated = schema["properties"]["anchors"]["items"]["allOf"][4:]
    assert [rule["if"]["properties"]["kind"]["const"] for rule in activated] == [
        "sheet",
        "cell",
        "member",
    ]
    assert registry_schema["properties"]["schema_version"]["const"] == 1
    assert registry_schema["properties"]["operations"]["const"] == list(SUPPORT_OPERATIONS)
    assert registry["operations"] == list(SUPPORT_OPERATIONS)
    assert compatibility["instance_schema_2_byte_unchanged"] is True
    assert compatibility["legacy_bundles_byte_unchanged"] is True
    assert compatibility["eager_migration"] is False
    assert compatibility["original_sidecar_markdown"] is False
    browser_template = (root / "core/provelume/templates/representations.html").read_text(
        encoding="utf-8"
    )
    assert "row.reason or '—'" in browser_template
    assert "row.missing_component" in browser_template


def test_activated_cell_anchor_requires_coordinate_to_match_row_and_column(
    tmp_path: Path,
) -> None:
    instance, version_id = _seed(tmp_path)
    bundle = _materialize(instance, version_id)
    cell = next(item for item in bundle["anchors"] if item["kind"] == "cell")
    cell["target"] = {
        "schema_version": 1,
        "profile": "csv",
        "row": 1,
        "column": 1,
        "coordinate": "B1",
    }
    with pytest.raises(RepresentationContractError) as caught:
        validate_representation_bundle(bundle)
    assert caught.value.code == "representation_invalid"
