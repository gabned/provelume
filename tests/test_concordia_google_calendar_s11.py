"""Google Calendar mapping and separate PKCE grants; synthetic provider only."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from test_google_connection import CLIENT, FakeGoogle, MemoryVault, connect

from provelume.google_calendar import GoogleCalendarAdapter, map_calendar_event
from provelume.google_connection import GoogleConnectionManager
from provelume.google_contract import GoogleCursorInvalidated
from provelume.google_credentials import GoogleCredentialError
from provelume.google_oauth import PROFILE_ENDPOINTS
from provelume.productivity_contract import ProductivityError
from provelume.productivity_intake import ProductivityIntake
from provelume.service import ProvelumeInstance


class CalendarGoogle(FakeGoogle):
    def request(self, endpoint, **options):
        if endpoint == PROFILE_ENDPOINTS["calendar"]:
            self.calls.append((endpoint, None, options.get("token")))
            return {"id": self.email}
        return super().request(endpoint, **options)


@pytest.fixture
def google(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    vault, transport = MemoryVault(), CalendarGoogle()
    manager = GoogleConnectionManager(instance.store, vault=vault, transport=transport)
    manager.configure(json.dumps(CLIENT))
    return instance, manager, vault, transport


def event():
    return {
        "id": "stable-event",
        "etag": '"remote-etag"',
        "summary": "Synthetic appointment",
        "status": "confirmed",
        "iCalUID": "synthetic-uid@example.invalid",
        "start": {"dateTime": "2026-10-25T02:30:00+02:00", "timeZone": "Europe/Rome"},
        "end": {"dateTime": "2026-10-25T02:45:00+01:00", "timeZone": "Europe/Rome"},
        "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"],
    }


def test_same_identity_three_separate_grants_and_selected_calendar_sources(google):
    instance, manager, _vault, transport = google
    _request, gmail = connect(manager, transport)
    _request, drive = connect(manager, transport, "drive", gmail["instance_id"])
    request, calendar = connect(manager, transport, "calendar", gmail["instance_id"])
    assert calendar["instance_id"] == gmail["instance_id"] == drive["instance_id"]
    scopes = parse_qs(urlsplit(request["authorization_uri"]).query)["scope"]
    assert scopes == ["https://www.googleapis.com/auth/calendar.readonly"]
    assert len({gmail["source_id"], drive["source_id"], calendar["source_id"]}) == 3
    source = manager.sources.source_record(calendar["source_id"])
    assert source["selectors"] == ["primary"] and source["state"] == "disabled"
    other = manager.sources.create_source(
        calendar["instance_id"],
        name="Second selected calendar",
        capability="calendar",
        selection_kind="calendar",
        selectors=["other@example.invalid"],
    )
    assert other["id"] != source["source_id"]
    manager.disconnect(calendar["instance_id"], "calendar")
    state = manager.sources._instance_record(calendar["instance_id"])["capabilities"]
    assert state["calendar"]["authorization_status"] == "revoked"
    assert (
        state["gmail"]["authorization_status"]
        == state["drive"]["authorization_status"]
        == "authorized"
    )
    assert instance.validate_instance()["status"] == "valid"
    # References, access/refresh tokens and client JSON stay in the injected
    # external vault, including the independently retained operation history.
    assert all(
        b"google_grant_" not in path.read_bytes()
        and b"synthetic-access-secret" not in path.read_bytes()
        and b"synthetic-refresh-secret" not in path.read_bytes()
        for path in instance.root.rglob("*")
        if path.is_file()
    )


def test_mapping_preserves_dst_all_day_original_occurrence_and_cancellation():
    mapped = map_calendar_event(event(), "calendar-one", "Europe/Rome")
    assert mapped["starts"]["value"].endswith("+02:00")
    assert mapped["ends"]["value"].endswith("+01:00")
    assert mapped["provenance"]["recurrence"] == ["RRULE:FREQ=WEEKLY;COUNT=3"]
    all_day = {**event(), "start": {"date": "2026-11-07"}, "end": {"date": "2026-11-08"}}
    assert map_calendar_event(all_day, "calendar-one", None)["starts"] == {
        "kind": "date",
        "value": "2026-11-07",
        "time_zone": None,
    }
    tombstone = {
        "id": "exception-one",
        "status": "cancelled",
        "recurringEventId": "series-one",
        "originalStartTime": {"date": "2026-11-07"},
    }
    cancelled = map_calendar_event(tombstone, "calendar-one", None)
    assert cancelled["starts"] is None and cancelled["title"] == ""
    assert cancelled["provenance"]["parent_id"] == "series-one"
    assert json.loads(cancelled["provenance"]["recurrence_id"]) == {"date": "2026-11-07"}
    assert cancelled["revision_kind"] == "content_sha256"


@pytest.mark.parametrize("failure", ["vault_link", "canonical_cas"])
def test_failed_reauthorization_preserves_owned_external_link_and_previous_grant(
    google, monkeypatch, failure
):
    _instance, manager, vault, transport = google
    _request, connected = connect(manager, transport, "calendar")
    identity = connected["instance_id"]
    before = manager.sources._instance_record(identity)
    slot = manager._link_slot(identity, "calendar")
    previous = vault.read(slot)
    original_write = vault.write

    def write(name, value):
        if failure == "vault_link" and name == slot:
            raise GoogleCredentialError("google_secure_store_unavailable")
        original_write(name, value)

    def compare_write(*_args, **_kwargs):
        raise GoogleCredentialError("synthetic_cas_conflict")

    monkeypatch.setattr(vault, "write", write)
    if failure == "canonical_cas":
        monkeypatch.setattr(manager.sources, "compare_write_instance", compare_write)
    with pytest.raises(GoogleCredentialError):
        connect(manager, transport, "calendar", identity)
    assert manager.sources._instance_record(identity) == before
    assert vault.read(slot) == previous
    assert [name for name in vault.values if name.startswith("google_grant_")] == [
        previous["name"]
    ]


def test_independent_google_identities_do_not_share_grants_sources_or_cursors(google):
    _instance, manager, vault, transport = google
    _request, first = connect(manager, transport, "calendar")
    transport.email = "another-synthetic-account@example.invalid"
    _request, second = connect(manager, transport, "calendar")
    assert first["instance_id"] != second["instance_id"]
    assert first["source_id"] != second["source_id"]
    first_link = manager._owned_reference(first["instance_id"], "calendar")
    second_link = manager._owned_reference(second["instance_id"], "calendar")
    assert first_link != second_link
    manager.disconnect(first["instance_id"], "calendar")
    assert vault.read(first_link["name"]) is None
    assert vault.read(second_link["name"])["capability"] == "calendar"
    assert manager.sources.source_record(second["source_id"])["cursor"]["provider_cursor"] is None


def test_calendar_wire_pagination_retains_exact_response_and_source_binding(google):
    instance, manager, _vault, transport = google
    _request, connected = connect(manager, transport, "calendar")
    source_id = connected["source_id"]
    manager.sources.set_capability_state(connected["instance_id"], "calendar", "enabled")
    manager.sources.set_source_state(source_id, "enabled")
    raw = json.dumps(
        {"items": [event()], "timeZone": "Europe/Rome", "nextSyncToken": "exact-terminal-token"}
    ).encode()

    class Api:
        calls = []

        def _request(self, url, **options):
            self.calls.append((url, options))
            return raw, "application/json"

    api = Api()
    adapter = GoogleCalendarAdapter(manager, source_id, sync_token="previous-token", api=api)
    identity = instance.store.read_canonical("connector-instances", connected["instance_id"])
    source = instance.store.read_canonical("sources", source_id)
    page = adapter.read_page(identity=identity, source=source, cursor="page-two", credential=None)
    assert page.originals == (raw,) and page.checkpoint == "exact-terminal-token"
    query = parse_qs(urlsplit(api.calls[0][0]).query)
    assert query["syncToken"] == ["previous-token"] and query["pageToken"] == ["page-two"]
    assert query["singleEvents"] == ["false"] and query["showDeleted"] == ["true"]
    assert not any(key in query for key in ["timeMin", "timeMax", "q", "orderBy"])
    assert adapter._active_token is None
    with pytest.raises(ProductivityError):
        adapter.read_page(
            identity={**identity, "id": "foreign"}, source=source, cursor=None, credential=None
        )


def test_normal_calendar_job_import_replay_offline_disconnect_and_schedule_consent(google):
    instance, manager, _vault, transport = google
    _request, connection = connect(manager, transport, "calendar")
    source_id = connection["source_id"]
    manager.sources.set_capability_state(connection["instance_id"], "calendar", "enabled")
    manager.sources.set_source_state(source_id, "enabled")
    assert instance.productivity_connectors().policy(source_id)["mode"] == "manual"
    manager.sources.configure_schedule(source_id, mode="interval", interval_seconds=300)
    assert instance.productivity_connectors().policy(source_id)["mode"] == "scheduled"
    manager.sources.configure_schedule(source_id, mode="manual")
    assert instance.productivity_connectors().policy(source_id)["mode"] == "manual"
    raw = json.dumps(
        {"items": [event()], "timeZone": "Europe/Rome", "nextSyncToken": "terminal-sync"}
    ).encode()

    class Api:
        calls = []

        def _request(self, url, **options):
            self.calls.append(url)
            return raw, "application/json"

    instance.google.calendar_connection = manager
    instance.google.calendar_api = Api()
    instance.scheduler._google_manager_factory = lambda store: instance.google
    first = instance.google.queue(source_id, request_key="calendar-first", guided=True)
    result = instance.run_google_job(first["job"]["id"])
    assert result["status"] == "succeeded", result
    rows = instance.list_productivity_records(source_id)
    assert len(rows) == 1 and rows[0]["item"]["kind"] == "calendar_event"
    assert instance.document_original(rows[0]["document_id"])["data"] == raw
    assert (
        instance.get_google_job(first["job"]["id"])["google_run"]["execution_adapter"]
        == "synthetic"
    )
    second = instance.google.queue(source_id, request_key="calendar-second", guided=True)
    replay = instance.run_google_job(second["job"]["id"])
    assert replay["status"] == "succeeded", replay
    assert len(instance.store.versions_for_document(rows[0]["document_id"])) == 1
    assert parse_qs(urlsplit(instance.google.calendar_api.calls[-1]).query)["syncToken"] == [
        "terminal-sync"
    ]
    manager.disconnect(connection["instance_id"], "calendar")
    assert instance.list_productivity_records(source_id) == rows
    assert instance.document_original(rows[0]["document_id"])["data"] == raw
    assert instance.validate_instance()["status"] == "valid"


def test_revocation_during_response_does_not_promote_items_or_checkpoint(google):
    instance, manager, _vault, _transport = google

    class Api:
        def _request(self, _url, **_options):
            manager.sources.set_source_state(source_id, "disabled")
            return json.dumps({"items": [event()], "timeZone": "Europe/Rome",
                               "nextSyncToken": "refused"}).encode(), "application/json"

    instance, manager, source_id = prepare_job(google, Api())
    result, _run = run_guided(instance, source_id, "revoke-during-response")
    assert result["status"] != "succeeded"
    assert instance.store.list_canonical("documents") == []
    assert ProductivityIntake(instance.store).checkpoint(source_id) is None


def prepare_job(google, api):
    instance, manager, _vault, transport = google
    _request, connection = connect(manager, transport, "calendar")
    source_id = connection["source_id"]
    manager.sources.set_capability_state(connection["instance_id"], "calendar", "enabled")
    manager.sources.set_source_state(source_id, "enabled")
    instance.google.calendar_connection = manager
    instance.google.calendar_api = api
    instance.scheduler._google_manager_factory = lambda store: instance.google
    return instance, manager, source_id


def run_guided(instance, source_id, key):
    queued = instance.google.queue(source_id, request_key=key, guided=True)
    result = instance.run_google_job(queued["job"]["id"])
    return result, instance.get_google_job(queued["job"]["id"])["google_run"]


def test_calendar_continuation_preserves_unchanged_guided_limits_and_completeness(google):
    class Api:
        calls = []

        def _request(self, url, **_options):
            query = parse_qs(urlsplit(url).query)
            self.calls.append(query)
            start = int(query.get("pageToken", ["0"])[0])
            count = int(query["maxResults"][0])
            rows = [
                {**event(), "id": str(index), "iCalUID": f"uid-{index}@example.invalid"}
                for index in range(start, min(start + count, 70))
            ]
            data = {"items": rows, "timeZone": "Europe/Rome"}
            data.update(
                {"nextPageToken": str(start + count)}
                if start + count < 70
                else {"nextSyncToken": "full-source-complete"}
            )
            return json.dumps(data).encode(), "application/json"

    api = Api()
    instance, manager, source = prepare_job(google, api)
    result, run = run_guided(instance, source, "first-bounded-slice")
    assert result["status"] == "succeeded" and run["status"] == "continuation_available"
    assert run["progress"]["processed"] == 50
    assert ProductivityIntake(instance.store).checkpoint(source) is None
    assert {row["availability"] for row in instance.list_productivity_records(source)} == {
        "not_in_completed_snapshot"
    }
    assert manager.sources.source_record(source)["cursor"]["provider_cursor"] == "50"
    result, run = run_guided(instance, source, "second-bounded-slice")
    assert result["status"] == "succeeded" and run["status"] == "completed"
    assert len(api.calls) == 3 and all(query["maxResults"] == ["25"] for query in api.calls)
    rows = instance.list_productivity_records(source)
    assert len(rows) == 70 and {row["availability"] for row in rows} == {"in_completed_snapshot"}
    assert (
        ProductivityIntake(instance.store).checkpoint(source)["checkpoint"]
        == "full-source-complete"
    )


def test_delta_empty_preserves_membership_full_resync_empty_does_not_invent_deletion(google):
    class Api:
        count = 0

        def _request(self, url, **_options):
            self.count += 1
            rows = [event()] if self.count == 1 else []
            return json.dumps(
                {"items": rows, "timeZone": "Europe/Rome", "nextSyncToken": f"token-{self.count}"}
            ).encode(), "application/json"

    api = Api()
    instance, manager, source = prepare_job(google, api)
    assert run_guided(instance, source, "initial")[0]["status"] == "succeeded"
    assert run_guided(instance, source, "delta-empty")[0]["status"] == "succeeded"
    assert instance.list_productivity_records(source)[0]["availability"] == "in_completed_snapshot"
    manager.sources.reset_cursor(source)
    assert run_guided(instance, source, "explicit-full-reset")[0]["status"] == "succeeded"
    row = instance.list_productivity_records(source)[0]
    assert row["availability"] == "not_in_completed_snapshot"
    assert row["item"]["state"] == "confirmed"
    assert (
        len(
            [
                document
                for document in instance.store.list_canonical("documents")
                if document["locator"].startswith("productivity-response:")
            ]
        )
        == 3
    )


def test_410_retains_old_checkpoint_and_requires_explicit_reset_without_retry(google):
    class Api:
        failed, calls = False, []

        def _request(self, url, **_options):
            self.calls.append(url)
            if self.failed:
                raise GoogleCursorInvalidated()
            return json.dumps(
                {"items": [event()], "timeZone": "Europe/Rome", "nextSyncToken": "known-complete"}
            ).encode(), "application/json"

    api = Api()
    instance, manager, source = prepare_job(google, api)
    assert run_guided(instance, source, "initial")[0]["status"] == "succeeded"
    before = ProductivityIntake(instance.store).checkpoint(source)
    api.failed = True
    assert run_guided(instance, source, "expired-token")[0]["status"] == "manual_intervention"
    assert len(api.calls) == 2
    assert ProductivityIntake(instance.store).checkpoint(source) == before
    queued = instance.google.queue(source, request_key="still-invalid", guided=True)
    assert instance.run_google_job(queued["job"]["id"])["status"] == "manual_intervention"
    assert len(api.calls) == 2
    manager.sources.reset_cursor(source)
    api.failed = False
    assert run_guided(instance, source, "explicit-reset")[0]["status"] == "succeeded"
    assert "syncToken" not in parse_qs(urlsplit(api.calls[-1]).query)
