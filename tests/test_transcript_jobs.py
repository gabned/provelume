from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from provelume.instance_backup import create_backup, verify_backup
from provelume.portable_transfer import PortableInstanceTransfer
from provelume.service import ProvelumeInstance
from provelume.transcript_contract import TranscriptContractError
from provelume.transcript_files import LocalTranscriptAdapter
from provelume.transcript_jobs import TranscriptJobManager
from provelume.transcript_parsers import BoundedTranscriptParser


def _srt(text: str = "synthetic transcript") -> bytes:
    return (
        "1\r\n00:00:00,000 --> 00:00:01,000\r\n"
        f"{text}\r\n\r\n"
        "2\r\n00:00:01,000 --> 00:00:02,000\r\n"
        "second cue\r\n"
    ).encode()


def _enabled(
    tmp_path: Path, data: bytes | None = None, *, name: str = "selected.srt"
) -> tuple[ProvelumeInstance, Path, str]:
    path = tmp_path / name
    path.write_bytes(data or _srt())
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = instance.create_transcript_source(
        name="Private source title",
        path=path,
        profile="srt-v1",
        selection_kind="file",
    )
    with pytest.raises(TranscriptContractError) as disabled:
        instance.queue_transcript_intake(str(source["id"]))
    assert disabled.value.code == "transcript_source_disabled"
    instance.set_transcript_source_state(str(source["id"]), "enabled")
    return instance, path, str(source["id"])


def _run(instance: ProvelumeInstance, source_id: str, *, request_key: str | None = None):
    queued = instance.queue_transcript_intake(source_id, request_key=request_key)
    job = instance.run_transcript_job(str(queued["job"]["id"]))
    assert job is not None
    return queued, job


def test_exact_original_provider_neutral_chain_and_inert_bundle_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _srt("<script>alert(1)</script> https://example.invalid")
    instance, selected, source_id = _enabled(tmp_path, data)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("local transcript intake attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    before = selected.read_bytes()
    _queued, job = _run(instance, source_id)
    assert job["status"] == "succeeded"
    assert job["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    assert selected.read_bytes() == before

    revisions = instance.list_transcript_revisions()
    assert len(revisions) == 1
    revision = revisions[0]
    assert revision["source_id"] == source_id
    assert revision["original_sha256"] == hashlib.sha256(data).hexdigest()
    original, original_bytes = instance.get_transcript_original(revision["id"])
    assert original_bytes == data
    assert original["sha256"] == revision["original_sha256"]
    detail = instance.get_transcript_revision(revision["id"], include_content=True)
    assert detail is not None
    assert detail["manifest"]["active_content_executed"] is False
    assert detail["manifest"]["remote_resources_fetched"] is False
    assert detail["manifest"]["network_used"] is False
    assert "<script>alert(1)</script>" in detail["text"]
    assert detail["cues"][0]["speaker_identity_verified"] is False
    assert detail["cues"][0]["media_existence_attested"] is False
    for representation in detail["manifest"]["representations"].values():
        reference = representation["storage_ref"]
        assert reference.startswith(f"state/derived/transcripts/{revision['id']}/")
        assert ".." not in Path(reference).parts
        assert selected.name not in reference

    acquisition = instance.store.read_canonical("acquisitions", revision["acquisition_id"])
    document = instance.store.read_canonical("documents", revision["document_id"])
    version = instance.store.read_canonical("versions", revision["version_id"])
    assert acquisition is not None and acquisition["acquisition_kind"] == "transcript"
    assert acquisition["requested_url"] is None and acquisition["final_url"] is None
    assert document is not None and document["source_id"] == source_id
    assert document["locator"].startswith("transcript-locator:sha256:")
    assert selected.name not in json.dumps(document)
    assert version is not None and version["original_id"] == original["id"]
    canonical_revision = instance.store.read_canonical(
        "transcript-revisions", revision["id"]
    )
    assert canonical_revision is not None
    assert {
        "profile",
        "format",
        "parser_id",
        "parser_version",
        "settings_sha256",
        "filesystem_identity_sha256",
        "filesystem_mtime_ns",
    }.isdisjoint(canonical_revision)
    assert acquisition["media_type"] == "application/octet-stream"
    assert acquisition["content_encoding"] is None
    assert acquisition["derived_status"] is None
    assert acquisition["derived_artifact_id"] is None

    for path in (
        instance.transcripts.requests,
        instance.transcripts.runs,
        instance.transcripts.work,
        instance.transcripts.source_states,
    ):
        for record in path.glob("*.json"):
            operational = record.read_text(encoding="utf-8")
            assert "Private source title" not in operational
            assert "<script>alert(1)</script>" not in operational
            assert selected.name not in operational
            assert str(tmp_path) not in operational


def test_replay_unchanged_bytes_new_revision_and_source_isolation(tmp_path: Path) -> None:
    instance, selected, first_source = _enabled(tmp_path)
    first_queue, first_job = _run(instance, first_source)
    assert first_job["status"] == "succeeded"
    first_revision = instance.list_transcript_revisions()[0]

    duplicate = instance.queue_transcript_intake(first_source)
    assert duplicate["created"] is False
    assert duplicate["job"]["id"] == first_queue["job"]["id"]
    replay_queue, replay_job = _run(instance, first_source, request_key="explicit-replay")
    assert replay_queue["job"]["id"] != first_queue["job"]["id"]
    assert replay_job["progress"] == {"processed": 0, "skipped": 1, "errors": 0}
    assert len(instance.store.list_canonical("versions")) == 1
    assert len(instance.store.list_canonical("acquisitions")) == 1

    selected.write_bytes(_srt("new exact bytes"))
    _new_queue, new_job = _run(instance, first_source)
    assert new_job["progress"]["processed"] == 1
    revisions = instance.list_transcript_revisions(source_id=first_source)
    assert len(revisions) == 2
    documents = instance.store.list_canonical("documents")
    assert len(documents) == 1
    versions = instance.store.versions_for_document(first_revision["document_id"])
    assert [item["sequence"] for item in versions] == [1, 2]
    assert documents[0]["current_version_id"] == versions[1]["id"]

    selected.write_bytes(_srt())
    _revert_queue, revert_job = _run(instance, first_source, request_key="revert-to-a")
    assert revert_job["progress"] == {"processed": 0, "skipped": 1, "errors": 0}
    reverted_document = instance.store.read_canonical(
        "documents", first_revision["document_id"]
    )
    assert reverted_document is not None
    assert reverted_document["current_version_id"] == versions[0]["id"]

    other_file = tmp_path / "other.srt"
    other_file.write_bytes(_srt("new exact bytes"))
    other = instance.create_transcript_source(
        name="Other",
        path=other_file,
        profile="srt-v1",
        selection_kind="file",
    )
    other_source = str(other["id"])
    instance.set_transcript_source_state(other_source, "enabled")
    _run(instance, other_source)
    other_revision = instance.list_transcript_revisions(source_id=other_source)[0]
    assert other_revision["document_id"] != documents[0]["id"]
    assert other_revision["transcript_id"] != revisions[0]["transcript_id"]
    assert other_revision["original_id"] == revisions[0]["original_id"]
    assert all(item["cross_source_merge"] is False for item in instance.list_transcript_revisions())


def test_malformed_files_fail_visibly_without_complete_or_partial_bundle(tmp_path: Path) -> None:
    instance, _selected, source_id = _enabled(
        tmp_path, b"1\n00:00:02,000 --> 00:00:01,000\ninvalid\n"
    )
    queued, job = _run(instance, source_id)
    assert job["status"] == "succeeded"
    assert job["progress"] == {"processed": 0, "skipped": 0, "errors": 1}
    detail = instance.get_transcript_job(str(queued["job"]["id"]))
    assert detail is not None
    assert detail["intake_run"]["status"] == "completed_with_errors"
    assert detail["intake_run"]["error_codes"] == ["transcript_timestamp_invalid"]
    assert instance.list_transcript_revisions() == []
    assert instance.store.list_canonical("originals") == []
    assert instance.store.list_derived_artifacts() == []
    checkpoint = instance.transcript_source_checkpoint(source_id)
    assert checkpoint["complete"] is False
    assert checkpoint["resync_required"] is True


def test_source_change_after_queue_and_mutation_after_parse_fail_without_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, selected, source_id = _enabled(tmp_path)
    queued = instance.queue_transcript_intake(source_id)
    selected.write_bytes(_srt("changed before run"))
    result = instance.run_transcript_job(str(queued["job"]["id"]))
    assert result is not None and result["status"] == "retry_wait"
    assert result["attempts"][-1]["error_code"] == "transcript_input_changed"
    assert instance.list_transcript_revisions() == []

    second_root = tmp_path / "second"
    second_root.mkdir()
    second, second_path, second_source = _enabled(second_root)
    original_read = LocalTranscriptAdapter.read_exact

    def read_then_mutate(self, candidate, *, limits, deadline):
        observed = original_read(self, candidate, limits=limits, deadline=deadline)
        second_path.write_bytes(_srt("changed after read"))
        return observed

    monkeypatch.setattr(LocalTranscriptAdapter, "read_exact", read_then_mutate)
    queued_second = second.queue_transcript_intake(second_source)
    changed = second.run_transcript_job(str(queued_second["job"]["id"]))
    assert changed is not None and changed["status"] == "retry_wait"
    assert second.list_transcript_revisions() == []
    assert second.store.list_derived_artifacts() == []


def test_mutation_during_replay_parse_fails_before_unchanged_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, selected, source_id = _enabled(tmp_path)
    _run(instance, source_id)
    original_parse = BoundedTranscriptParser.parse

    def parse_then_mutate(self, data, *, profile, limits=None, deadline=None):
        parsed = original_parse(
            self,
            data,
            profile=profile,
            limits=limits,
            deadline=deadline,
        )
        selected.write_bytes(_srt("changed while replay parser was active"))
        return parsed

    monkeypatch.setattr(BoundedTranscriptParser, "parse", parse_then_mutate)
    queued = instance.queue_transcript_intake(source_id, request_key="mutation-replay")
    replay = instance.run_transcript_job(str(queued["job"]["id"]))
    assert replay is not None and replay["status"] == "retry_wait"
    assert replay["attempts"][-1]["error_code"] == "transcript_input_changed"
    assert len(instance.store.list_canonical("versions")) == 1
    assert len(instance.store.list_canonical("acquisitions")) == 1
    assert len(instance.list_transcript_revisions()) == 1


def test_replaceable_parser_creates_new_recipe_not_canonical_version(
    tmp_path: Path,
) -> None:
    class ReplacementParser(BoundedTranscriptParser):
        parser_id = "example.synthetic-transcript"
        parser_version = "2.0.0"

        def parse(self, data, *, profile, limits=None, deadline=None):
            parsed = super().parse(
                data,
                profile=profile,
                limits=limits,
                deadline=deadline,
            )
            return replace(
                parsed,
                parser_id=self.parser_id,
                parser_version=self.parser_version,
            )

    instance, _selected, source_id = _enabled(tmp_path)
    _run(instance, source_id)
    first = instance.list_transcript_revisions()[0]
    replacement = TranscriptJobManager(instance.store, parser=ReplacementParser())
    instance.transcripts = replacement
    instance.scheduler._transcript_manager_factory = lambda _store: replacement
    queued = instance.queue_transcript_intake(source_id, request_key="replacement-parser")
    result = instance.run_transcript_job(str(queued["job"]["id"]))
    assert result is not None and result["status"] == "succeeded"
    assert result["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    assert len(instance.store.list_canonical("versions")) == 1
    assert len(instance.store.list_canonical("acquisitions")) == 1
    assert len(instance.store.list_canonical("transcript-revisions")) == 1
    current = instance.get_transcript_revision(first["id"], include_content=True)
    assert current is not None
    assert current["parser_id"] == ReplacementParser.parser_id
    assert current["parser_version"] == ReplacementParser.parser_version
    assert len(replacement._recipes_for_revision(first["id"])) == 2
    instance.remove_transcript_derived(first["id"])
    rebuilt = instance.rebuild_transcript_derived(first["id"])
    assert rebuilt["derived_status"] == "complete"
    assert rebuilt["parser_id"] == ReplacementParser.parser_id


def test_cancellation_retry_checkpoint_and_cursor_resync_are_source_confined(
    tmp_path: Path,
) -> None:
    instance, _selected, source_id = _enabled(tmp_path)
    queued = instance.queue_transcript_intake(source_id)
    cancelled = instance.cancel_transcript_job(str(queued["job"]["id"]))
    assert cancelled["status"] == "cancelled"
    retry = instance.retry_transcript_job(str(queued["job"]["id"]))
    assert retry["job"]["id"] != queued["job"]["id"]
    finished = instance.run_transcript_job(str(retry["job"]["id"]))
    assert finished is not None and finished["status"] == "succeeded"
    checkpoint = instance.transcript_source_checkpoint(source_id)
    assert checkpoint["source_id"] == source_id
    assert checkpoint["item_count"] == 1
    assert checkpoint["complete"] is True
    reset = instance.reset_transcript_source_cursor(source_id)
    assert reset["resync_required"] is True
    assert reset["snapshot_sha256"] is None


def test_running_cancellation_and_expired_lease_recovery_are_bounded_and_resumable(
    tmp_path: Path,
) -> None:
    cancel_root = tmp_path / "cancel"
    cancel_root.mkdir()
    cancelled_instance, _selected, cancelled_source = _enabled(cancel_root)
    cancel_queue = cancelled_instance.queue_transcript_intake(cancelled_source)
    cancel_job_id = str(cancel_queue["job"]["id"])
    claimed = cancelled_instance.scheduler.journal.claim_next(
        worker_id="transcript-cancel-worker",
        job_id=cancel_job_id,
        lease_seconds=30,
        now=datetime.now(UTC),
    )
    assert claimed is not None
    cancellation = cancelled_instance.cancel_transcript_job(cancel_job_id)
    assert cancellation["status"] == "cancellation_requested"
    with pytest.raises(TranscriptContractError) as stopped:
        cancelled_instance.transcripts.execute(claimed)
    assert stopped.value.code == "transcript_cancelled"
    assert cancelled_instance.list_transcript_revisions() == []
    cancelled_detail = cancelled_instance.get_transcript_job(cancel_job_id)
    assert cancelled_detail is not None
    assert cancelled_detail["intake_run"]["status"] == "cancelled"
    assert cancelled_detail["intake_run"]["error_codes"] == ["transcript_cancelled"]

    recovery_root = tmp_path / "recovery"
    recovery_root.mkdir()
    recovered_instance, _recovery_file, recovered_source = _enabled(recovery_root)
    queued = recovered_instance.queue_transcript_intake(recovered_source)
    job_id = str(queued["job"]["id"])
    started = datetime.now(UTC)
    interrupted = recovered_instance.scheduler.journal.claim_next(
        worker_id="transcript-interrupted-worker",
        job_id=job_id,
        lease_seconds=5,
        now=started,
    )
    assert interrupted is not None
    token = str(interrupted["lease"]["token"])
    recovered_instance.scheduler.journal.checkpoint(
        job_id,
        token,
        sequence=1,
        phase="executing",
        progress=interrupted["progress"],
        now=started,
    )
    recovery_time = datetime.fromisoformat(
        str(interrupted["lease"]["expires_at"])
    ) + timedelta(seconds=1)
    recovery = recovered_instance.scheduler.recover(now=recovery_time)
    assert recovery["expired_leases"] == 1
    resumable = recovered_instance.scheduler.journal.get_job(job_id)
    assert resumable is not None
    assert resumable["status"] == "queued"
    assert resumable["recovery_state"] == "resumable"
    finished = recovered_instance.scheduler.run_one(job_id=job_id, now=recovery_time)
    assert finished is not None and finished["status"] == "succeeded"
    assert finished["attempt"] == 2
    assert len(recovered_instance.store.list_canonical("versions")) == 1
    assert len(recovered_instance.store.list_canonical("acquisitions")) == 1
    assert recovered_instance.transcript_source_checkpoint(recovered_source)["complete"] is True


def test_remove_and_rebuild_only_derived_representation(tmp_path: Path) -> None:
    instance, _selected, source_id = _enabled(tmp_path)
    _run(instance, source_id)
    revision = instance.list_transcript_revisions()[0]
    canonical_before = {
        kind: instance.store.list_canonical(kind)
        for kind in (
            "sources",
            "acquisitions",
            "originals",
            "documents",
            "versions",
            "provenance",
            "transcript-revisions",
        )
    }
    original_before = instance.get_transcript_original(revision["id"])[1]
    removed = instance.remove_transcript_derived(revision["id"])
    assert removed["derived_status"] == "removed"
    assert instance.get_transcript_revision(revision["id"], include_content=True)[
        "private_content_included"
    ] is False
    rebuilt = instance.rebuild_transcript_derived(revision["id"])
    assert rebuilt["derived_status"] == "complete"
    assert instance.get_transcript_original(revision["id"])[1] == original_before
    assert {
        kind: instance.store.list_canonical(kind) for kind in canonical_before
    } == canonical_before


def test_backup_restore_export_import_preserve_exact_original_and_source_isolation(
    tmp_path: Path,
) -> None:
    instance, _selected, source_id = _enabled(tmp_path)
    _run(instance, source_id)
    revision = instance.list_transcript_revisions()[0]
    original = instance.get_transcript_original(revision["id"])[1]
    backup = create_backup(instance.store, reason="transcript_regression")
    verified = verify_backup(Path(backup["archive"]))
    assert verified["status"] == "valid"

    instance.remove_transcript_derived(revision["id"])
    assert instance.get_transcript_revision(revision["id"])["derived_status"] == "removed"
    assert instance.restore(backup["archive"])["status"] == "restored"
    instance = ProvelumeInstance(instance.root)
    restored_from_backup = instance.list_transcript_revisions()[0]
    assert instance.get_transcript_original(restored_from_backup["id"])[1] == original
    assert instance.get_transcript_revision(
        restored_from_backup["id"], include_content=True
    )["derived_status"] == "complete"
    assert instance.validate_instance(deep=True)["status"] == "valid"

    archive = PortableInstanceTransfer(instance.store).export(
        tmp_path / "exports", derived_state="rebuild"
    )
    target = ProvelumeInstance.initialise(tmp_path / "target")
    imported = PortableInstanceTransfer(target.store).import_bundle(Path(archive["archive"]))
    assert imported["status"] == "imported"
    restored = ProvelumeInstance(tmp_path / "target")
    restored_revision = restored.list_transcript_revisions()[0]
    assert restored_revision["source_id"] == source_id
    assert restored.get_transcript_original(restored_revision["id"])[1] == original
    assert restored.get_transcript_revision(
        restored_revision["id"], include_content=True
    )["derived_status"] == "complete"


def test_operational_state_contains_only_sanitised_codes_ids_hashes_and_counts(
    tmp_path: Path,
) -> None:
    private = "Speaker Private Secret Meeting"
    instance, _selected, source_id = _enabled(tmp_path, _srt(private))
    _run(instance, source_id)
    roots = [
        instance.transcripts.requests,
        instance.transcripts.runs,
        instance.transcripts.work,
        instance.transcripts.cancellations,
        instance.transcripts.source_states,
        instance.store.paths.state / "scheduler",
        instance.store.paths.state / "operations",
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            assert private not in path.read_text(encoding="utf-8")
