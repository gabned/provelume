from __future__ import annotations

import hashlib
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import provelume.email_jobs as email_jobs
from provelume.email_contract import EmailContractError
from provelume.email_sources import EmailSourceError
from provelume.service import ProvelumeInstance

WINDOWS_MAILDIR_UNQUALIFIED = pytest.mark.skipif(
    os.name == "nt", reason="Maildir is not qualified on Windows"
)


@pytest.fixture(autouse=True)
def qualified_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name != "nt":
        monkeypatch.setattr(
            "provelume.email_contract.qualified_runtime_target",
            lambda: "ubuntu-24.04-x86_64-cpython312",
        )


def _message(
    *,
    message_id: str = "<one@example.invalid>",
    body: str = "bounded body",
) -> bytes:
    return (
        "From: Sender <sender@example.invalid>\r\n"
        "To: Group: One <one@example.invalid>, Two <two@example.invalid>;\r\n"
        "Subject: =?utf-8?q?Synthetic_message?=\r\n"
        "Date: Tue, 04 Feb 2025 10:11:12 +0100\r\n"
        f"Message-ID: {message_id}\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: multipart/mixed; boundary=mail-boundary\r\n"
        "\r\n"
        "--mail-boundary\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
        "--mail-boundary\r\n"
        'Content-Type: image/png; name="..\\CON.png"\r\n'
        'Content-Disposition: attachment; filename="../../CON.png"\r\n'
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        "iVBORw0KGgo=\r\n"
        "--mail-boundary--\r\n"
    ).encode()


def _enabled_source(
    tmp_path: Path,
    data: bytes,
) -> tuple[ProvelumeInstance, Path, str]:
    eml = tmp_path / "synthetic.eml"
    eml.write_bytes(data)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = instance.create_email_source(
        name="Synthetic EML",
        path=eml,
        profile="eml-file-v1",
    )
    assert source["state"] == "disabled"
    with pytest.raises((EmailContractError, EmailSourceError)) as caught:
        instance.queue_email_intake(source["id"])
    assert caught.value.code == "email_source_disabled"
    instance.set_email_source_state(source["id"], "enabled")
    return instance, eml, str(source["id"])


def test_explicit_eml_job_commits_exact_original_attachment_and_inert_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _message()
    instance, _eml, source_id = _enabled_source(tmp_path, data)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("local email intake attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    queued = instance.queue_email_intake(source_id)
    job = instance.run_email_job(queued["job"]["id"])
    assert job is not None and job["status"] == "succeeded"
    assert job["progress"] == {"processed": 1, "skipped": 0, "errors": 0}

    messages = instance.list_email_messages()
    assert len(messages) == 1
    message = messages[0]
    assert message["original_sha256"] == hashlib.sha256(data).hexdigest()
    assert instance.store.original_bytes(message["original_id"]) == data
    assert message["body"]["selection_rule"] == "first-safe-text-plain-depth-first"
    assert message["active_content_executed"] is False
    assert message["remote_fetch"] is False

    attachments = instance.list_email_attachments(message_id=message["id"])
    assert len(attachments) == 1
    attachment = attachments[0]
    assert instance.store.original_bytes(attachment["original_id"]) == b"\x89PNG\r\n\x1a\n"
    assert attachment["representation"]["filename"] == "../../CON.png"
    assert attachment["representation"]["ocr"]["eligible"] is True
    assert attachment["representation"]["ocr"]["execution_started"] is False

    validation = instance.validate_instance(deep=True)
    assert validation["status"] == "valid", validation["errors"]


def test_replay_collision_and_derived_rebuild_preserve_canonical_state(
    tmp_path: Path,
) -> None:
    first = _message()
    instance, eml, source_id = _enabled_source(tmp_path, first)
    queued = instance.queue_email_intake(source_id)
    assert instance.run_email_job(queued["job"]["id"])["status"] == "succeeded"

    duplicate = instance.queue_email_intake(source_id)
    assert duplicate["job"]["id"] == queued["job"]["id"]
    assert duplicate["created"] is False

    eml.write_bytes(_message(body="different exact bytes"))
    collision = instance.queue_email_intake(source_id)
    assert collision["job"]["id"] != queued["job"]["id"]
    assert instance.run_email_job(collision["job"]["id"])["status"] == "succeeded"
    messages = instance.list_email_messages(source_id=source_id)
    assert len(messages) == 2
    assert any(
        warning["code"] == "declared_message_id_collision"
        for message in messages
        for warning in message.get("identity_warnings", [])
    )

    selected = messages[0]
    original_before = instance.store.original_bytes(selected["original_id"])
    canonical_before = {
        kind: instance.store.list_canonical(kind)
        for kind in (
            "email-messages",
            "email-observations",
            "email-attachments",
            "documents",
            "versions",
            "originals",
            "provenance",
        )
    }
    removed = instance.remove_email_derived(selected["id"])
    assert removed["status"] == "removed"
    assert instance.get_email_message(selected["id"])["derived_status"] == "removed"
    rebuilt = instance.rebuild_email_derived(selected["id"])
    assert rebuilt["status"] == "rebuilt"
    assert instance.store.original_bytes(selected["original_id"]) == original_before
    assert {
        kind: instance.store.list_canonical(kind) for kind in canonical_before
    } == canonical_before
    assert instance.validate_instance(deep=True)["status"] == "valid"


@WINDOWS_MAILDIR_UNQUALIFIED
def test_scheduled_maildir_materializes_request_and_isolates_message_errors(
    tmp_path: Path,
) -> None:
    root = tmp_path / "maildir"
    for name in ("cur", "new", "tmp"):
        (root / name).mkdir(parents=True)
    good = _message(message_id="<good@example.invalid>")
    bad = (
        b"Message-ID: <bad@example.invalid>\r\n"
        b"Content-Type: application/octet-stream\r\n"
        b"Content-Disposition: attachment\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\ntruncated"
    )
    (root / "new" / "good").write_bytes(good)
    (root / "new" / "bad").write_bytes(bad)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = instance.create_email_source(
        name="Synthetic Maildir",
        path=root,
        profile="maildir-cur-new-v1",
    )
    source_id = str(source["id"])
    instance.set_email_source_state(source_id, "enabled")
    instance.configure_email_source_schedule(
        source_id,
        mode="interval",
        interval_seconds=60,
    )
    policy = next(
        item
        for item in instance.scheduler.journal.list_policies()
        if item["job_kind"] == "email.intake"
    )
    due = datetime.fromisoformat(policy["next_due_at"])
    evaluated = instance.scheduler.journal.evaluate(now=due + timedelta(seconds=1))
    assert len(evaluated["created_jobs"]) == 1
    job_id = evaluated["created_jobs"][0]
    request_path = instance.store.paths.state / "email-intake" / "requests" / f"{job_id}.json"
    assert not request_path.exists()
    job = instance.scheduler.run_one(
        job_id=job_id,
        now=due + timedelta(seconds=1),
    )
    assert job is not None and job["status"] == "succeeded"
    assert job["progress"] == {"processed": 1, "skipped": 0, "errors": 1}
    detail = instance.get_email_job(job_id)
    assert detail is not None
    assert detail["intake_run"]["status"] == "completed_with_errors"
    assert detail["intake_run"]["error_codes"] == ["email_transfer_invalid"]
    assert request_path.is_file()
    assert len(instance.list_email_messages(source_id=source_id)) == 1


def test_receipts_and_work_journals_are_content_free_and_source_removal_is_a_tombstone(
    tmp_path: Path,
) -> None:
    data = _message(body="uniquely-private-derived-body")
    instance, eml, source_id = _enabled_source(tmp_path, data)
    queued = instance.queue_email_intake(source_id, request_key="opaque-request")
    job_id = str(queued["job"]["id"])
    assert instance.run_email_job(job_id)["status"] == "succeeded"
    message = instance.list_email_messages()[0]
    original = instance.store.original_bytes(message["original_id"])
    instance.remove_email_source(source_id)
    assert instance.get_email_source(source_id)["lifecycle_state"] == "removed"
    assert instance.store.original_bytes(message["original_id"]) == original
    assert instance.get_email_message(message["id"]) is not None
    assert eml.read_bytes() == data

    forbidden = (
        b"uniquely-private-derived-body",
        b"Synthetic_message",
        b"sender@example.invalid",
        b"../../CON.png",
        str(eml).encode(),
    )
    state_paths = [
        instance.store.paths.state / "email-intake" / "requests" / f"{job_id}.json",
        instance.store.paths.state / "email-intake" / "work" / f"{job_id}.json",
        instance.store.paths.state / "email-intake" / "runs" / f"{job_id}.json",
        instance.store.paths.state / "scheduler" / "receipts" / f"receipt_{job_id[4:]}.json",
    ]
    for path in state_paths:
        payload = path.read_bytes()
        assert all(value not in payload for value in forbidden)


def test_message_mutation_before_promotion_never_publishes_stale_success(
    tmp_path: Path,
) -> None:
    data = _message()
    instance, eml, source_id = _enabled_source(tmp_path, data)
    queued = instance.queue_email_intake(source_id)
    parser = instance.email.parser

    class MutatingParser:
        parser_id = parser.parser_id
        parser_version = parser.parser_version

        def parse(self, payload: bytes, **kwargs: object):
            parsed = parser.parse(payload, **kwargs)
            eml.write_bytes(_message(body="mutated-before-promotion"))
            return parsed

    instance.email.parser = MutatingParser()  # type: ignore[assignment]
    instance.scheduler._email_manager_factory = lambda _store: instance.email
    job = instance.run_email_job(queued["job"]["id"])
    assert job is not None and job["status"] == "succeeded"
    assert job["progress"] == {"processed": 0, "skipped": 0, "errors": 1}
    assert instance.list_email_messages() == []
    assert instance.get_email_job(job["id"])["intake_run"]["status"] == (
        "completed_with_errors"
    )


def test_running_job_cancellation_is_cooperative_and_content_free(tmp_path: Path) -> None:
    instance, _eml, source_id = _enabled_source(tmp_path, _message())
    queued = instance.queue_email_intake(source_id)
    job_id = str(queued["job"]["id"])
    claimed = instance.scheduler.journal.claim_next(
        worker_id="email-test-worker",
        allowed_kinds=("email.intake",),
        job_id=job_id,
        now=datetime.now(UTC),
    )
    assert claimed is not None
    result = instance.cancel_email_job(job_id)
    assert result["status"] == "cancellation_requested"
    with pytest.raises(EmailContractError) as caught:
        instance.email.execute(claimed)
    assert caught.value.code == "email_cancelled"
    assert instance.list_email_messages() == []


def test_manual_queue_binds_job_key_and_request_to_one_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _eml, source_id = _enabled_source(tmp_path, _message())
    config = instance.email_sources.source_config(source_id, require_enabled=True)
    adapter = email_jobs.adapter_for_profile(config)
    calls = 0

    class CountingAdapter:
        def snapshot(self, **kwargs: object):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise AssertionError("manual queue observed the Source more than once")
            return adapter.snapshot(**kwargs)

    monkeypatch.setattr(email_jobs, "adapter_for_profile", lambda _config: CountingAdapter())
    queued = instance.queue_email_intake(source_id, request_key="caller-scope")
    assert calls == 1
    request_path = (
        instance.store.paths.state
        / "email-intake"
        / "requests"
        / f"{queued['job']['id']}.json"
    )
    payload = request_path.read_bytes()
    assert b"caller-scope" not in payload
    assert queued["request"]["container_snapshot_sha256"] in payload.decode("ascii")


def test_expired_lease_recovers_commit_before_scheduler_checkpoint(
    tmp_path: Path,
) -> None:
    instance, _eml, source_id = _enabled_source(tmp_path, _message())
    queued = instance.queue_email_intake(source_id)
    job_id = str(queued["job"]["id"])
    started = datetime.now(UTC)
    claimed = instance.scheduler.journal.claim_next(
        worker_id="crash-before-checkpoint",
        lease_seconds=1,
        job_id=job_id,
        now=started,
    )
    assert claimed is not None

    class SimulatedCrash(RuntimeError):
        pass

    def crash_after_commit(_progress: dict[str, int]) -> None:
        raise SimulatedCrash

    with pytest.raises(SimulatedCrash):
        instance.email.execute(claimed, checkpoint=crash_after_commit)
    assert len(instance.list_email_messages()) == 1
    assert instance.scheduler.journal.get_job(job_id)["progress"] == {
        "processed": 0,
        "skipped": 0,
        "errors": 0,
    }

    recovered_at = started + timedelta(seconds=2)
    recovery = instance.scheduler.journal.recover(now=recovered_at)
    assert recovery["expired_leases"] == 1
    instance.scheduler._email_manager_factory = lambda _store: instance.email
    finished = instance.scheduler.run_one(job_id=job_id, now=recovered_at)
    assert finished is not None and finished["status"] == "succeeded"
    assert finished["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    assert finished["recovery_state"] == "restart_only"
    assert finished["recovery_count"] == 1
    assert len(instance.list_email_messages()) == 1
    assert instance.validate_instance(deep=True)["status"] == "valid"


@WINDOWS_MAILDIR_UNQUALIFIED
def test_locator_rename_reuses_message_but_retains_a_new_observation(
    tmp_path: Path,
) -> None:
    maildir = tmp_path / "maildir"
    for name in ("cur", "new", "tmp"):
        (maildir / name).mkdir(parents=True)
    data = _message()
    first_path = maildir / "new" / "first"
    first_path.write_bytes(data)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = instance.create_email_source(
        name="Rename Maildir",
        path=maildir,
        profile="maildir-cur-new-v1",
    )
    source_id = str(source["id"])
    instance.set_email_source_state(source_id, "enabled")
    first = instance.queue_email_intake(source_id)
    assert instance.run_email_job(str(first["job"]["id"]))["status"] == "succeeded"

    first_path.rename(maildir / "cur" / "renamed")
    second = instance.queue_email_intake(source_id)
    assert second["job"]["id"] != first["job"]["id"]
    assert instance.run_email_job(str(second["job"]["id"]))["status"] == "succeeded"
    assert len(instance.list_email_messages(source_id=source_id)) == 1
    assert len(instance.store.list_canonical("email-observations")) == 2
    assert len(instance.store.list_canonical("acquisitions")) == 2
    assert len(instance.store.list_canonical("versions")) == 1
    assert instance.store.original_bytes(
        instance.list_email_messages()[0]["original_id"]
    ) == data


def test_equal_bytes_in_different_sources_never_merge_identity(tmp_path: Path) -> None:
    data = (
        b"Message-ID: <cross-source@example.invalid>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"same exact source bytes"
    )
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source_ids: list[str] = []
    for index in range(2):
        path = tmp_path / f"source-{index}.eml"
        path.write_bytes(data)
        source = instance.create_email_source(
            name=f"Source {index}",
            path=path,
            profile="eml-file-v1",
        )
        source_id = str(source["id"])
        source_ids.append(source_id)
        instance.set_email_source_state(source_id, "enabled")
        queued = instance.queue_email_intake(source_id)
        assert instance.run_email_job(str(queued["job"]["id"]))["status"] == (
            "succeeded"
        )

    messages = instance.list_email_messages()
    assert len(messages) == 2
    assert {item["source_id"] for item in messages} == set(source_ids)
    assert len({item["id"] for item in messages}) == 2
    assert len({item["document_id"] for item in messages}) == 2
    assert len({item["original_id"] for item in messages}) == 1
    assert len(instance.store.list_canonical("originals")) == 1
    assert all(
        warning["code"] != "declared_message_id_collision"
        for message in messages
        for warning in message["identity_warnings"]
    )
    assert len(instance.list_email_threads()) == 2


def test_untrusted_attachment_names_never_select_storage_paths(tmp_path: Path) -> None:
    filenames = (
        'filename="../../escape.txt"',
        'filename="/absolute/path.txt"',
        'filename="C:\\\\Windows\\\\CON"',
        'filename="NUL"',
        'filename="same.txt"',
        'filename="same.txt"',
        "filename*=utf-8''%E2%80%AEtxt.exe",
    )
    parts = []
    for filename in filenames:
        parts.append(
            "--names\r\n"
            "Content-Type: application/octet-stream\r\n"
            f"Content-Disposition: attachment; {filename}\r\n"
            "Content-Transfer-Encoding: base64\r\n\r\n"
            "c2FtZQ==\r\n"
        )
    data = (
        "Message-ID: <names@example.invalid>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: multipart/mixed; boundary=names\r\n\r\n"
        + "".join(parts)
        + "--names--\r\n"
    ).encode()
    instance, _eml, source_id = _enabled_source(tmp_path, data)
    queued = instance.queue_email_intake(source_id)
    assert instance.run_email_job(str(queued["job"]["id"]))["status"] == "succeeded"
    attachments = instance.list_email_attachments()
    assert len(attachments) == len(filenames)
    assert len({item["id"] for item in attachments}) == len(filenames)
    assert len({item["original_id"] for item in attachments}) == 1
    for item in attachments:
        original = instance.store.read_canonical("originals", item["original_id"])
        assert original is not None
        assert original["storage_ref"] == (
            f"originals/sha256/{item['original_sha256'][:2]}/"
            f"{item['original_sha256']}"
        )
        assert instance.store.original_bytes(item["original_id"]) == b"same"
    observed_names = {
        item["representation"]["filename"] for item in attachments
    }
    assert "../../escape.txt" in observed_names
    assert "/absolute/path.txt" in observed_names
    assert "NUL" in observed_names
    assert "same.txt" in observed_names
    assert any("\u202e" in item for item in observed_names if item is not None)
