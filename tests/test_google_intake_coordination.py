from __future__ import annotations

import json
from datetime import UTC, datetime
from threading import Event, Timer, current_thread
from urllib.parse import parse_qs, urlsplit

import pytest
from test_google_connection import connect, journey  # noqa: F401
from test_google_jobs import _configured_source, _use_adapter

from provelume import scheduler
from provelume.google_adapters import GoogleApiAdapter, SyntheticGoogleAdapter
from provelume.google_contract import GoogleItem, GooglePage
from provelume.google_jobs import GoogleJobManager


def test_gmail_checkpoint_waits_for_its_heartbeat_writer(journey, monkeypatch):  # noqa: F811
    instance, manager, _, transport = journey
    _, connected = connect(manager, transport)
    source_id = connected["source_id"]
    manager.sources.set_capability_state(connected["instance_id"], "gmail", "enabled")
    manager.sources.set_source_state(source_id, "enabled")
    heartbeat_writing, release_writer = Event(), Event()
    journal = instance.scheduler.journal
    original_write, original_heartbeat = journal._write_job, journal.heartbeat
    # Exercise real worker coordination without making lease ownership depend
    # on filesystem latency on a contended Windows runner.
    fixed_now = datetime.now(UTC)
    original_instant = scheduler.utc_instant

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(scheduler, "datetime", FixedDateTime)
    monkeypatch.setattr(
        scheduler, "utc_instant",
        lambda value=None: original_instant(fixed_now if value is None else value),
    )

    def write(job):
        if current_thread().name == "provelume-scheduler-heartbeat":
            heartbeat_writing.set()
            assert release_writer.wait(30)
        return original_write(job)

    def heartbeat(*args, **kwargs):
        if heartbeat_writing.is_set() and current_thread().name != (
            "provelume-scheduler-heartbeat"
        ):
            Timer(0.1, release_writer.set).start()
        return original_heartbeat(*args, **kwargs)

    class DelayedGmail(SyntheticGoogleAdapter):
        def fetch_page(self, **kwargs):
            assert heartbeat_writing.wait(30)
            return super().fetch_page(**kwargs)

    adapter = DelayedGmail({source_id: [GooglePage(capability="gmail", items=(
        GoogleItem(capability="gmail", provider_item_id="synthetic-message",
                   provider_revision_id="1", payload=b"Subject: synthetic\r\n\r\nBody\r\n",
                   media_type="message/rfc822"),
    ))]})
    instance.scheduler._google_manager_factory = lambda store: GoogleJobManager(
        store, adapter=adapter
    )
    queued = instance.google.queue(source_id, guided=True)
    monkeypatch.setattr(journal, "_write_job", write)
    monkeypatch.setattr(journal, "heartbeat", heartbeat)
    try:
        result = instance.scheduler.run_one(job_id=queued["job"]["id"], lease_seconds=3)
    finally:
        release_writer.set()
    assert result["status"] == "succeeded"
    assert result["attempt"] == 1
    assert result["progress"]["processed"] == 1
    assert len(instance.store.list_canonical("email-messages")) == 1


@pytest.mark.parametrize("all_skipped", [False, True])
def test_drive_unsupported_entries_count_towards_limits_and_resume(
    tmp_path, monkeypatch, all_skipped
):
    instance, _, source_id = _configured_source(
        tmp_path, capability="drive", selection_kind="folder", selectors=["root"]
    )
    types = ["folder", "shortcut", "form", "map"] * 13
    rows = [
        {"id": f"private-synthetic-{i}", "version": "1",
         "mimeType": "application/vnd.google-apps." + kind}
        for i, kind in enumerate(types)
    ]
    if not all_skipped:
        rows[1] = {**rows[1], "mimeType": "text/plain"}
    adapter = GoogleApiAdapter(credential_resolver=lambda _: "synthetic")
    listed, downloaded = [], []

    def request(url, *, credential_reference, limits, maximum):
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if parsed.path == "/drive/v3/files":
            start = int(query.get("pageToken", ["0"])[0])
            count = int(query["pageSize"][0])
            listed.append((start, count))
            page = {"files": rows[start:start + count]}
            if start + count < len(rows):
                page["nextPageToken"] = str(start + count)
            return json.dumps(page).encode(), "application/json"
        row = next(row for row in rows if parsed.path.endswith("/" + row["id"]))
        assert row["mimeType"] == "text/plain"  # Never follow a folder or shortcut.
        if "alt" in query:
            downloaded.append(row["id"])
            assert maximum <= limits.max_total_bytes_per_run
            return b"synthetic content", "text/plain"
        return json.dumps(row).encode(), "application/json"

    monkeypatch.setattr(adapter, "_request", request)
    _use_adapter(instance, adapter)
    first = instance.google.queue(source_id, guided=True)
    result = instance.run_google_job(first["job"]["id"])
    assert result["status"] == "succeeded"
    assert result["progress"] == {
        "processed": 0 if all_skipped else 1,
        "skipped": 50 if all_skipped else 49, "errors": 0,
    }
    source = instance.google_sources.source_record(source_id)
    assert source["cursor"]["provider_cursor"] == "50"
    assert source["cursor"]["page_ordinal"] == 2
    second = instance.google.queue(source_id, guided=True)
    result = instance.run_google_job(second["job"]["id"])
    assert result["status"] == "succeeded"
    assert result["progress"] == {"processed": 0, "skipped": 2, "errors": 0}
    assert instance.google_sources.source_record(source_id)["cursor"]["provider_cursor"] is None
    assert listed == [(0, 25), (25, 25), (50, 25)]
    assert len(downloaded) == (0 if all_skipped else 1)
    assert len(instance.store.list_canonical("originals")) == len(downloaded)
    evidence = "".join(p.read_text() for p in instance.google.work.glob("*.json"))
    assert "private-synthetic" not in evidence


@pytest.mark.parametrize("code,expected,status", [
    ("email_internal_error", "google_internal_error", "retry_wait"),
])
def test_gmail_commit_error_is_recorded_without_abandoned_lease(tmp_path, monkeypatch,
                                                               code, expected, status):
    from provelume.email_contract import EmailContractError
    from provelume.email_jobs import EmailJobManager

    instance, _, source_id = _configured_source(
        tmp_path, capability="gmail", selection_kind="mailbox", selectors=["me"]
    )
    item = GoogleItem(capability="gmail", provider_item_id="synthetic",
                      provider_revision_id="1", payload=b"Subject: synthetic\r\n\r\nBody",
                      media_type="message/rfc822")
    _use_adapter(instance, SyntheticGoogleAdapter({source_id: [
        GooglePage(capability="gmail", items=(item,))
    ]}))

    def fail_commit(*args, **kwargs):
        raise EmailContractError(code, "synthetic private detail")

    monkeypatch.setattr(EmailJobManager, "_commit_message", fail_commit)
    queued = instance.google.queue(source_id, guided=True)
    result = instance.run_google_job(queued["job"]["id"])
    assert result["status"] == status
    job = instance.scheduler.journal.get_job(queued["job"]["id"])
    assert job["lease"] is None
    assert job["attempts"][0]["error_code"] == expected
    assert "synthetic private detail" not in json.dumps(job)


def test_gmail_long_bundle_remains_valid_and_portable(tmp_path):
    root = tmp_path / ("nested-" + "p" * max(1, 100 - len(str(tmp_path))))
    root.mkdir()
    instance, _, source_id = _configured_source(
        root, capability="gmail", selection_kind="mailbox", selectors=["me"]
    )
    item = GoogleItem(capability="gmail", provider_item_id="synthetic-long-path",
                      provider_revision_id="1", payload=b"Subject: synthetic\r\n\r\nBody",
                      media_type="message/rfc822")
    _use_adapter(instance, SyntheticGoogleAdapter({source_id: [
        GooglePage(capability="gmail", items=(item,))
    ]}))
    queued = instance.google.queue(source_id, guided=True)
    assert instance.run_google_job(queued["job"]["id"])["status"] == "succeeded"
    validation = instance.validate_instance(deep=True)
    assert validation["status"] == "valid", validation["errors"]

    instance.export_portable(tmp_path / "portable.zip")


def test_drive_reuses_exact_original_without_rewriting_first_acquisition(tmp_path):
    instance, _, source_id = _configured_source(
        tmp_path, capability="drive", selection_kind="folder", selectors=["root"]
    )
    folder = tmp_path / "local-input"
    folder.mkdir()
    payload = b"shared synthetic bytes"
    (folder / "shared.txt").write_bytes(payload)
    instance.ingest(folder)
    before = instance.store.list_canonical("originals")
    item = GoogleItem(capability="drive", provider_item_id="synthetic-file",
                      provider_revision_id="1", payload=payload, media_type="text/plain")
    _use_adapter(instance, SyntheticGoogleAdapter({source_id: [
        GooglePage(capability="drive", items=(item,))
    ]}))
    queued = instance.google.queue(source_id, guided=True)
    result = instance.run_google_job(queued["job"]["id"])
    assert result["status"] == "succeeded"
    assert result["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    assert instance.store.list_canonical("originals") == before
    assert len(instance.store.list_canonical("documents")) == 2


def test_drive_changed_export_bytes_preserve_immutable_versions(tmp_path):
    instance, _, source_id = _configured_source(
        tmp_path, capability="drive", selection_kind="folder", selectors=["root"]
    )

    def acquire(payload):
        item = GoogleItem(
            capability="drive", provider_item_id="synthetic-native-document",
            provider_revision_id="same-provider-revision", payload=payload,
            media_type="application/pdf",
            source_format="application/vnd.google-apps.document",
            export_format="application/pdf", google_native=True,
        )
        _use_adapter(instance, SyntheticGoogleAdapter({source_id: [
            GooglePage(capability="drive", items=(item,))
        ]}))
        queued = instance.google.queue(source_id, guided=True)
        return instance.run_google_job(queued["job"]["id"])

    first_payload = b"%PDF-synthetic-export-one"
    second_payload = b"%PDF-synthetic-export-two"
    assert acquire(first_payload)["status"] == "succeeded"
    first_version = instance.store.list_canonical("versions")[0]
    result = acquire(second_payload)
    assert result["status"] == "succeeded"
    assert result["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    versions = sorted(instance.store.list_canonical("versions"), key=lambda row: row["sequence"])
    assert len(versions) == 2
    assert versions[0] == first_version
    assert versions[0]["id"] != versions[1]["id"]
    assert [instance.store.original_bytes(row["original_id"]) for row in versions] == [
        first_payload, second_payload,
    ]
    assert instance.store.list_canonical("documents")[0]["current_version_id"] == versions[1]["id"]
    replay = acquire(second_payload)
    assert replay["status"] == "succeeded"
    assert replay["progress"] == {"processed": 0, "skipped": 1, "errors": 0}
    assert sorted(
        instance.store.list_canonical("versions"), key=lambda row: row["sequence"]
    ) == versions
    assert instance.validate_instance(deep=True)["status"] == "valid"
