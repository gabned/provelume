from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from provelume.qualification import QualificationManager
from provelume.qualification_contract import QualificationError, QualificationLimits
from provelume.service import ProvelumeInstance


def _seed(tmp_path: Path, *, same_bytes: bool = True) -> tuple[ProvelumeInstance, list[str]]:
    root = tmp_path / "instance"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "record.txt").write_text("shared synthetic bytes\n", encoding="utf-8")
    (second / "record.txt").write_text(
        "shared synthetic bytes\n" if same_bytes else "shared synthetic bytez\n",
        encoding="utf-8",
    )
    instance = ProvelumeInstance.initialise(root)
    first_acquisition = instance.ingest(first, source_name="private-source-one")[0]
    second_acquisition = instance.ingest(second, source_name="private-source-two")[0]
    return instance, sorted([first_acquisition["source_id"], second_acquisition["source_id"]])


def _run(instance: ProvelumeInstance, source_ids: list[str]) -> tuple[dict, list[dict]]:
    queued = instance.queue_qualification(source_ids)
    job = instance.run_qualification(queued["job"]["id"])
    assert job["status"] == "succeeded"
    return job, instance.list_qualification_findings(limit=500)


def test_exact_bytes_are_findings_without_cross_source_merge(tmp_path: Path) -> None:
    instance, source_ids = _seed(tmp_path)
    before = {
        kind: instance.store.list_canonical(kind)
        for kind in ("sources", "documents", "versions", "originals", "provenance")
    }
    job, findings = _run(instance, source_ids)
    exact = [item for item in findings if item["finding_type"] == "possible-exact-byte-duplicate"]
    assert len(exact) == 1
    assert exact[0]["source_ids"] == source_ids
    assert exact[0]["epistemic_state"] == "deterministic-observation"
    assert exact[0]["provenance"]["qualification_job_id"] == job["id"]
    assert exact[0]["provenance"]["snapshot_fingerprint"] == job["snapshot_fingerprint"]
    assert set(exact[0]["provenance"]["source_snapshot_fingerprints"]) == set(source_ids)
    assert exact[0]["provenance"]["network_used"] is False
    assert exact[0]["provenance"]["provider_mutation"] is False
    assert exact[0]["provenance"]["canonical_source_mutation"] is False
    assert exact[0]["provenance"]["automatic_merge"] is False
    after = {
        kind: instance.store.list_canonical(kind)
        for kind in ("sources", "documents", "versions", "originals", "provenance")
    }
    assert after == before
    assert len(instance.store.list_canonical("documents")) == 2
    assert len(instance.store.list_canonical("originals")) == 1


def test_similar_metadata_different_bytes_is_only_low_confidence_revision_candidate(
    tmp_path: Path,
) -> None:
    instance, source_ids = _seed(tmp_path, same_bytes=False)
    _job, findings = _run(instance, source_ids)
    assert not any(item["finding_type"] == "possible-exact-byte-duplicate" for item in findings)
    revisions = [item for item in findings if item["finding_type"] == "possible-revision-relation"]
    assert revisions
    assert all(item["confidence"]["value"] == 0.25 for item in revisions)
    assert all(item["epistemic_state"] == "possible" for item in revisions)


def test_checksum_metadata_and_timestamp_inconsistencies_are_deterministic(
    tmp_path: Path,
) -> None:
    instance, source_ids = _seed(tmp_path)
    first_document = instance.store.list_canonical("documents")[0]
    version = instance.store.read_canonical("versions", str(first_document["current_version_id"]))
    assert version is not None
    version["media_type"] = "application/octet-stream"
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("versions") / f"{version['id']}.json", version
    )
    original = instance.store.read_canonical("originals", str(version["original_id"]))
    assert original is not None
    original["sha256"] = "0" * 64
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("originals") / f"{original['id']}.json", original
    )
    acquisition = next(
        item
        for item in instance.store.list_canonical("acquisitions")
        if item["version_id"] == version["id"]
    )
    acquisition["observed_at"] = "2020-01-01T00:00:00+00:00"
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("acquisitions") / f"{acquisition['id']}.json",
        acquisition,
    )
    _job, findings = _run(instance, source_ids)
    types = {item["finding_type"] for item in findings}
    assert "checksum-provenance-incompatible" in types
    assert "observed-metadata-inconsistent" in types
    assert "timestamp-inconsistent" in types
    stable_ids = {item["id"] for item in findings}
    replay = instance.queue_qualification(source_ids)
    assert replay["replayed"] is True
    assert {item["id"] for item in instance.list_qualification_findings(limit=500)} == stable_ids


def test_queue_replay_is_idempotent_and_resync_creates_a_new_snapshot(tmp_path: Path) -> None:
    instance, source_ids = _seed(tmp_path)
    first = instance.queue_qualification(source_ids)
    replay = instance.queue_qualification(list(reversed(source_ids)))
    assert replay["replayed"] is True
    assert replay["job"]["id"] == first["job"]["id"]
    assert instance.run_qualification(first["job"]["id"])["status"] == "succeeded"
    finding_ids = {item["id"] for item in instance.list_qualification_findings(limit=500)}
    assert instance.run_qualification(first["job"]["id"])["status"] == "succeeded"
    assert {item["id"] for item in instance.list_qualification_findings(limit=500)} == finding_ids
    checkpoint = instance.reset_qualification_source(source_ids[0])
    assert checkpoint["resync_required"] is True
    replacement = instance.queue_qualification(source_ids)
    assert replacement["job"]["id"] != first["job"]["id"]


def test_input_change_fails_without_complete_partial_result(tmp_path: Path) -> None:
    instance, source_ids = _seed(tmp_path)
    queued = instance.queue_qualification(source_ids)["job"]
    source = tmp_path / "first" / "record.txt"

    def mutate() -> None:
        source.write_text("changed after qualification snapshot\n", encoding="utf-8")
        instance.ingest(source.parent)

    result = instance.qualification.run(queued["id"], before_commit=mutate)
    assert result["status"] == "failed"
    assert result["error_code"] == "qualification_input_changed"
    assert result["result_ref"] is None
    assert not instance.qualification._result_path(queued["id"]).exists()


def test_representation_change_during_analysis_invalidates_candidate(tmp_path: Path) -> None:
    instance, source_ids = _seed(tmp_path)
    queued = instance.queue_qualification(source_ids)["job"]
    artifact = instance.store.list_derived_artifacts()[0]
    artifact_path = instance.root / artifact["storage_ref"]

    def mutate() -> None:
        artifact_path.unlink()

    result = instance.qualification.run(queued["id"], before_commit=mutate)
    assert result["status"] == "failed"
    assert result["error_code"] == "qualification_input_changed"
    assert result["result_ref"] is None


def test_decisions_are_attributed_append_only_reversible_and_concurrency_safe(
    tmp_path: Path,
) -> None:
    instance, source_ids = _seed(tmp_path)
    _job, findings = _run(instance, source_ids)
    finding = next(
        item for item in findings if item["finding_type"] == "possible-exact-byte-duplicate"
    )
    first = instance.decide_qualification_finding(
        finding["id"],
        action="accept",
        actor_id="reviewer.one",
        reason="Exact bytes observed; identity remains unverified.",
        expected_revision=0,
    )
    assert first["resulting_state"] == "accepted"
    second = instance.decide_qualification_finding(
        finding["id"],
        action="revert",
        actor_id="reviewer.one",
        reason="Withdraw the prior interpretation while preserving history.",
        expected_revision=1,
        payload={"target_decision_id": first["id"]},
    )
    assert second["resulting_state"] == "reverted"
    selected = instance.get_qualification_finding(finding["id"])
    assert selected is not None
    assert selected["workflow_state"] == "reverted"
    assert [item["revision"] for item in selected["decisions"]] == [1, 2]
    assert all(item["provenance"]["originals_modified"] is False for item in selected["decisions"])
    with pytest.raises(QualificationError, match="revision is stale"):
        instance.decide_qualification_finding(
            finding["id"],
            action="reject",
            actor_id="reviewer.two",
            reason="Concurrent stale submission.",
            expected_revision=1,
        )


@pytest.mark.parametrize(
    ("action", "payload", "state"),
    [
        ("acknowledge", None, "acknowledged"),
        ("reject", None, "rejected"),
        ("defer", {"until": "2026-10-01T00:00:00Z"}, "deferred"),
        ("declare-distinct", "objects", "accepted"),
        ("add-relation", "relation", "accepted"),
        ("correct-observation", {"field": "format-observation", "value": "text/plain"}, "accepted"),
    ],
)
def test_supported_human_corrections(
    tmp_path: Path, action: str, payload: object, state: str
) -> None:
    instance, source_ids = _seed(tmp_path)
    _job, findings = _run(instance, source_ids)
    finding = next(item for item in findings if len(item["object_refs"]) >= 2)
    object_ids = [item["id"] for item in finding["object_refs"][:2]]
    if payload == "objects":
        payload = {"object_ids": object_ids}
    if payload == "relation":
        payload = {"relation_type": "related", "object_ids": object_ids}
    decision = instance.decide_qualification_finding(
        finding["id"],
        action=action,
        actor_id="reviewer.local",
        reason="Bounded synthetic review rationale.",
        expected_revision=0,
        payload=payload if isinstance(payload, dict) else None,
    )
    assert decision["resulting_state"] == state


def test_cancel_retry_lease_recovery_and_limits(tmp_path: Path) -> None:
    instance, source_ids = _seed(tmp_path)
    queued = instance.queue_qualification(source_ids)["job"]
    cancelled = instance.cancel_qualification(queued["id"])
    assert cancelled["status"] == "cancelled"
    retried = instance.retry_qualification(queued["id"])
    assert retried["job"]["status"] == "queued"
    internal = instance.qualification.get_job(queued["id"], public=False)
    assert internal is not None
    internal["status"] = "running"
    internal["attempt"] = 1
    internal["lease"] = {
        "token": "internal-not-public",
        "owner": "crashed-worker",
        "heartbeat_at": (datetime.now(UTC) - timedelta(minutes=3)).isoformat(),
        "expires_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
    }
    instance.store._atomic_json(instance.qualification._job_path(queued["id"]), internal)
    recovered = QualificationManager(instance.store).get_job(queued["id"])
    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["error_code"] == "qualification_lease_expired"
    assert "token" not in json.dumps(recovered)
    with pytest.raises(QualificationError, match="Source count"):
        instance.queue_qualification(source_ids[:1])
    with pytest.raises(QualificationError, match="outside the closed boundary"):
        QualificationLimits(max_output_bytes=2 * 1024 * 1024 * 1024)
    bounded = replace(QualificationLimits(), max_findings=1)
    amplified = instance.qualification.queue(source_ids, limits=bounded)["job"]
    failed = instance.run_qualification(amplified["id"])
    assert failed["status"] == "failed"
    assert failed["error_code"] == "qualification_limit_exceeded"


def test_unsafe_representation_reference_is_inert_and_visible(tmp_path: Path) -> None:
    instance, source_ids = _seed(tmp_path)
    version_id = instance.store.list_canonical("versions")[0]["id"]
    instance.store._atomic_json(
        instance.store.paths.derived_artifacts / "derived_unsafe_reference.json",
        {
            "id": "derived_unsafe_reference",
            "version_id": version_id,
            "kind": "synthetic_unsafe_representation",
            "generator": "synthetic-test",
            "generator_version": "1",
            "storage_ref": "../outside-instance.txt",
            "checksum": "0" * 64,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    _job, findings = _run(instance, source_ids)
    unsafe = [
        item for item in findings if item["finding_type"] == "representation-not-reconstructible"
    ]
    assert unsafe
    serialized = json.dumps(unsafe)
    assert "outside-instance" not in serialized
    assert "../" not in serialized


def test_no_network_private_content_or_active_like_reason(tmp_path: Path, monkeypatch) -> None:
    instance, source_ids = _seed(tmp_path)
    marker = "private-source-one"

    def deny_network(*_args, **_kwargs):
        raise AssertionError("qualification attempted network access")

    monkeypatch.setattr("socket.socket", deny_network)
    _job, findings = _run(instance, source_ids)
    operational = json.dumps(
        {
            "jobs": instance.list_qualification_jobs(limit=100),
            "findings": findings,
        },
        sort_keys=True,
    )
    assert marker not in operational
    assert "shared synthetic bytes" not in operational
    finding = next(item for item in findings if len(item["object_refs"]) >= 2)
    with pytest.raises(QualificationError, match="active-like"):
        instance.decide_qualification_finding(
            finding["id"],
            action="accept",
            actor_id="reviewer.local",
            reason="<script>alert(1)</script>",
            expected_revision=0,
        )


def test_source_change_supersedes_obsolete_finding_and_stale_reference_fails(
    tmp_path: Path,
) -> None:
    instance, source_ids = _seed(tmp_path)
    _job, findings = _run(instance, source_ids)
    exact = next(
        item for item in findings if item["finding_type"] == "possible-exact-byte-duplicate"
    )
    changed = tmp_path / "second" / "record.txt"
    changed.write_text("distinct replacement bytes\n", encoding="utf-8")
    instance.ingest(changed.parent)
    next_job = instance.queue_qualification(source_ids)["job"]
    assert instance.run_qualification(next_job["id"])["status"] == "succeeded"
    old = instance.get_qualification_finding(exact["id"])
    assert old is not None
    assert old["workflow_state"] == "superseded"
    with pytest.raises(QualificationError, match="superseded"):
        instance.decide_qualification_finding(
            exact["id"],
            action="reject",
            actor_id="reviewer.local",
            reason="Stale synthetic review.",
            expected_revision=0,
        )


def test_backup_restore_and_portable_export_include_decisions_and_derived_state(
    tmp_path: Path,
) -> None:
    instance, source_ids = _seed(tmp_path)
    _job, findings = _run(instance, source_ids)
    finding = next(item for item in findings if len(item["object_refs"]) >= 2)
    decision = instance.decide_qualification_finding(
        finding["id"],
        action="reject",
        actor_id="reviewer.local",
        reason="Synthetic correction retained for portability.",
        expected_revision=0,
    )
    backup = instance.backup(destination=tmp_path / "backup.zip", reason="qualification-test")
    assert Path(backup["archive"]).is_file()
    instance.rebuild_index()
    instance.rebuild_library()
    exported = instance.export_portable(tmp_path / "portable.zip", derived_state="include")
    assert Path(exported["archive"]).is_file()
    rebuilt_export = instance.export_portable(
        tmp_path / "portable-rebuild.zip", derived_state="rebuild"
    )
    assert Path(rebuilt_export["archive"]).is_file()
    instance.restore(tmp_path / "backup.zip")
    reopened = ProvelumeInstance(tmp_path / "instance")
    assert reopened.get_qualification_decision(decision["id"]) == decision
    imported = ProvelumeInstance.initialise(tmp_path / "imported")
    imported.import_portable(tmp_path / "portable.zip")
    reopened_import = ProvelumeInstance(tmp_path / "imported")
    assert reopened_import.get_qualification_decision(decision["id"]) == decision
    assert reopened_import.list_qualification_findings(limit=500)
    rebuild_import = ProvelumeInstance.initialise(tmp_path / "rebuild-import")
    rebuild_import.import_portable(tmp_path / "portable-rebuild.zip")
    reopened_rebuild = ProvelumeInstance(tmp_path / "rebuild-import")
    assert reopened_rebuild.get_qualification_decision(decision["id"]) == decision
    restored_finding = reopened_rebuild.get_qualification_finding(finding["id"])
    assert restored_finding is not None
    assert restored_finding["workflow_state"] == "rejected"
