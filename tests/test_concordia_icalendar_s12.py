"""Synthetic local feeds and transport seam; no real account or remote destination."""

import json
import re
import subprocess
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_google_connection import MemoryVault

from provelume.icalendar_feeds import IcalendarFeeds, parse_isolated
from provelume.icalendar_worker import MAX_FEED_BYTES, parse_feed
from provelume.productivity_contract import ProductivityError
from provelume.productivity_intake import ProductivityIntake
from provelume.productivity_jobs import ProductivityJobs
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def feed(*events, method="PUBLISH", extra=""):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Synthetic//Concordia//EN\r\n"
            + f"METHOD:{method}\r\n" + extra + "".join(events) + "END:VCALENDAR\r\n").encode()


def event(uid="stable-uid", *, fields="", start="DTSTART;VALUE=DATE:20261107",
          end="DTEND;VALUE=DATE:20261108"):
    return ("BEGIN:VEVENT\r\n" + f"UID:{uid}\r\nSUMMARY:Synthetic event\r\n"
            + (start + "\r\n" if start else "") + (end + "\r\n" if end else "")
            + fields + "END:VEVENT\r\n")


@pytest.fixture
def journey(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    vault = MemoryVault()
    return instance, IcalendarFeeds(instance.store, vault=vault), vault


def add_local(journey, tmp_path, raw, name="Feed"):
    _instance, manager, _vault = journey
    path = tmp_path / (name + ".ics")
    path.write_bytes(raw)
    source = manager.add(name=name, kind="local", location=path, confirmed=True)
    return source["source_id"], path


def test_actual_isolated_local_read_is_offline_idempotent_and_canonical(journey, tmp_path):
    instance, manager, vault = journey
    raw = feed(event(fields="DESCRIPTION:Complete source text\\nWith a newline\r\n"))
    source, path = add_local(journey, tmp_path, raw)
    assert not instance.store.read_config()["network"]["external_access"]
    first = manager.refresh(source)
    assert first["count"] == 1 and first["provider_write"] is False
    row = ProductivityIntake(instance.store).records(source)[0]
    assert row["availability"] == "in_completed_snapshot"
    assert instance.document_original(row["document_id"])["data"] == raw
    obj = instance.store.list_canonical("objects")[0]
    assert obj["body"]["starts_on"] == "2026-11-07" and obj["body"]["ends_on"] == "2026-11-08"
    assert manager.refresh(source)["results"][0]["status"] == "unchanged"
    assert len(instance.store.versions_for_document(row["document_id"])) == 1
    assert instance.validate_instance()["status"] == "valid"
    assert all(str(path).encode() not in value.read_bytes() for value in instance.root.rglob("*")
               if value.is_file())
    assert vault.read(manager.slot(source))["location"] == str(path)


def test_dst_recurrence_exception_exdate_cancel_and_stable_instance_provenance():
    raw = feed(
        event(start="DTSTART;TZID=Europe/Rome:20261025T023000",
              end="DTEND;TZID=Europe/Rome:20261025T034500",
              fields="RRULE:FREQ=WEEKLY;COUNT=3\r\n"
                     "EXDATE;TZID=Europe/Rome:20261101T023000\r\n"),
        event(start="DTSTART;TZID=Europe/Rome:20261108T043000",
              end="DTEND;TZID=Europe/Rome:20261108T053000",
              fields="RECURRENCE-ID;TZID=Europe/Rome:20261108T023000\r\n"),
        event(start="", end="", fields="RECURRENCE-ID;VALUE=DATE:20261115\r\nSTATUS:CANCELLED\r\n"),
    )
    values = parse_feed(raw, "synthetic-feed")
    assert len(values) == 3 and len({value["remote_id"] for value in values}) == 3
    assert values[0]["starts"]["value"].endswith("+02:00")
    assert values[0]["ends"]["value"].endswith("+01:00")
    assert values[0]["provenance"]["recurrence"] == [
        "RRULE:FREQ=WEEKLY;COUNT=3", "EXDATE;TZID=Europe/Rome:20261101T023000"]
    assert values[1]["provenance"]["recurrence_id"] == "20261108T023000;TZID=Europe/Rome"
    assert values[2]["state"] == "cancelled" and values[2]["starts"] is None
    assert values[2]["revision_kind"] == "content_sha256"


def test_custom_vtimezone_maps_exact_utc_and_preserves_original_zone():
    zone = ("BEGIN:VTIMEZONE\r\nTZID:Custom/Plus0300\r\nBEGIN:STANDARD\r\n"
            "DTSTART:19700101T000000\r\nTZOFFSETFROM:+0300\r\nTZOFFSETTO:+0300\r\n"
            "END:STANDARD\r\nEND:VTIMEZONE\r\n")
    values = parse_feed(feed(event(start="DTSTART;TZID=Custom/Plus0300:20261107T100000",
                                  end="DTEND;TZID=Custom/Plus0300:20261107T110000"),
                             extra=zone), "f")
    assert values[0]["starts"] == {"kind": "instant", "value": "2026-11-07T07:00:00+00:00",
                                  "time_zone": "UTC"}
    assert values[0]["provenance"]["original_time_zones"]["starts"] == "Custom/Plus0300"


@pytest.mark.parametrize("raw", [
    feed(event(), event()), b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n",
    feed(event(start="DTSTART;TZID=Unknown/Zone:20261107T100000",
               end="DTEND;TZID=Unknown/Zone:20261107T110000")),
    feed(event(start="DTSTART:20261107T100000", end="DTEND:20261107T110000")),
    feed(event(fields="SUMMARY:Duplicate singleton\r\n")),
    feed(event(), method="REQUEST"), b"x" * (MAX_FEED_BYTES + 1),
])
def test_ambiguous_incomplete_unsupported_and_oversized_feeds_fail_visibly(raw):
    with pytest.raises((ProductivityError, ValueError)):
        parse_feed(raw, "feed")


def test_explicit_floating_zone_and_calendar_cancel_keep_semantics():
    value = parse_feed(feed(event(start="DTSTART:20261107T100000",
                                 end="DTEND:20261107T110000")), "feed", "Europe/Rome")[0]
    assert value["starts"]["value"] == "2026-11-07T10:00:00+01:00"
    assert parse_feed(feed(event(), method="CANCEL"), "feed")[0]["state"] == "cancelled"


def test_instantaneous_source_event_keeps_zero_duration_in_canonical_object(journey, tmp_path):
    instance, manager, _vault = journey
    source, _path = add_local(journey, tmp_path,
        feed(event(start="DTSTART:20261107T100000Z", end="")))
    manager.refresh(source)
    value = instance.store.list_canonical("objects")[0]
    assert value["body"]["starts_at"] == value["body"]["ends_at"] == "2026-11-07T10:00:00+00:00"
    assert instance.validate_instance()["status"] == "valid"


def test_independent_feeds_explain_duplicate_uid_without_merging(journey, tmp_path):
    instance, manager, _vault = journey
    first, _path = add_local(journey, tmp_path, feed(event()), "First")
    second, _path = add_local(journey, tmp_path, feed(event()), "Second")
    manager.refresh(first)
    manager.refresh(second)
    groups = manager.duplicates()
    assert len(groups) == 1 and groups[0]["merged"] is False
    assert {row["source_id"] for row in groups[0]["members"]} == {first, second}
    assert len(instance.store.list_canonical("objects")) == 2


def test_source_change_during_https_response_keeps_previous_checkpoint(journey):
    instance, manager, _vault = journey
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    connected = manager.add(name="Remote synthetic", kind="https",
                            location="https://example.invalid/private-token.ics",
                            authorization="Bearer synthetic-feed-secret", confirmed=True)
    source = connected["source_id"]
    manager.transport = lambda *_args: feed(event())
    manager.refresh(source)
    checkpoint = deepcopy(ProductivityIntake(instance.store).checkpoint(source))

    def revoked(*_args):
        manager.host.consent(source, capabilities=["calendar_read"], mode="disabled",
                             expected_revision=1, confirmed=True)
        return feed(event("new-event"))

    manager.transport = revoked
    with pytest.raises(ProductivityError):
        manager.refresh(source)
    assert ProductivityIntake(instance.store).checkpoint(source) == checkpoint
    assert all(b"synthetic-feed-secret" not in path.read_bytes()
               and b"private-token.ics" not in path.read_bytes()
               for path in instance.root.rglob("*") if path.is_file())


def test_https_without_network_consent_never_calls_transport(journey):
    _instance, manager, _vault = journey
    source = manager.add(name="Uncontacted", kind="https", location="https://example.invalid/a.ics",
                         confirmed=True)["source_id"]
    calls = []
    manager.transport = lambda *args: calls.append(args)
    with pytest.raises(ProductivityError, match="network_disabled"):
        manager.refresh(source)
    assert calls == []


def test_scheduler_runs_actual_local_feed_and_no_retry_policy(journey, tmp_path):
    instance, manager, _vault = journey
    source, _path = add_local(journey, tmp_path, feed(event()))
    jobs = ProductivityJobs(instance.store, feeds=manager)
    instance.scheduler._productivity_manager_factory = lambda _store: jobs
    queued = jobs.queue(source, request_key="one-controlled-acquisition")
    result = instance.scheduler.run_one(job_id=queued["job"]["id"])
    assert result["status"] == "succeeded", result
    assert result["retry"]["max_attempts"] == 1
    assert instance.validate_instance()["status"] == "valid"


def test_changed_external_binding_cannot_import(journey, tmp_path):
    instance, manager, vault = journey
    source, _path = add_local(journey, tmp_path, feed(event()))
    preview, adapter = manager.preview(source)
    location = vault.read(manager.slot(source))
    vault.write(manager.slot(source), {**location, "revision": 2})
    with pytest.raises(ProductivityError, match="stale"):
        ProductivityIntake(instance.store).accept(preview, recheck=adapter.recheck)
    assert instance.store.list_canonical("documents") == []


def test_isolated_worker_has_fixed_timeout_and_closed_private_diagnostics(monkeypatch):
    def hung(*_args, **options):
        assert options["timeout"] <= 15
        assert not any("TOKEN" in key for key in options["env"])
        raise subprocess.TimeoutExpired("synthetic", options["timeout"])

    monkeypatch.setattr(subprocess, "run", hung)
    with pytest.raises(ProductivityError, match="parse"):
        parse_isolated(b"private source", "feed", None, float("inf"))


def test_linked_local_feed_is_refused(journey, tmp_path):
    _instance, manager, _vault = journey
    original = tmp_path / "original.ics"
    original.write_bytes(feed(event()))
    linked = tmp_path / "linked.ics"
    try:
        linked.symlink_to(original)
    except OSError:
        pytest.skip("host does not permit synthetic symlinks")
    with pytest.raises(ProductivityError, match="location"):
        manager.add(name="Linked", kind="local", location=linked, confirmed=True)


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
def test_local_feed_ui_is_governed_translated_and_get_never_opens_vault(
    journey, tmp_path, language
):
    instance, manager, vault = journey
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._icalendar_manager = manager
    client = TestClient(app)
    path = tmp_path / "Synthetic UI.ics"
    path.write_bytes(feed(event()))
    before = vault.reads
    response = client.get("/icalendar?lang=" + language)
    assert response.status_code == 200 and vault.reads == before
    assert "icalendar.title" not in response.text
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    fields = {"csrf_token": token, "action": "add", "name": "Synthetic UI",
              "kind": "local", "location": str(path), "confirm": "yes"}
    assert client.post("/icalendar", data={**fields, "csrf_token": "bad"}).status_code == 403
    response = client.post("/icalendar?lang=" + language, data=fields)
    assert response.status_code == 200 and "notice=saved" in str(response.url)
    source = [value for value in instance.store.list_canonical("sources")
              if value.get("source_kind") == "icalendar"][0]
    jobs = ProductivityJobs(instance.store, feeds=manager)
    app.state.provelume.scheduler._productivity_manager_factory = lambda _store: jobs
    response = client.post("/icalendar?lang=" + language, data={"csrf_token": token,
        "action": "read", "source_id": source["id"], "revision": "1", "confirm": "yes"})
    assert "notice=saved" in str(response.url)
    assert instance.store.list_canonical("objects")[0]["origin"]["source_id"] == source["id"]
    reads = vault.reads
    assert client.get("/icalendar?lang=" + language).status_code == 200
    assert vault.reads == reads


def test_device_reconnect_after_portable_transfer_preserves_source_identity(journey, tmp_path):
    instance, manager, vault = journey
    source, path = add_local(journey, tmp_path, feed(event()))
    manager.refresh(source)
    objects = instance.store.list_canonical("objects")
    archive = tmp_path / "portable.zip"
    instance.export_portable(archive, derived_state="rebuild")
    target = ProvelumeInstance.initialise(tmp_path / "target")
    target.import_portable(archive)
    rebound = IcalendarFeeds(target.store, vault=MemoryVault())
    with pytest.raises(ProductivityError, match="authorization_required"):
        rebound.refresh(source)
    assert target.store.list_canonical("objects") == objects
    rebound.reconnect(source, kind="local", location=path, expected_policy_revision=1,
                      confirmed=True)
    assert rebound.refresh(source)["results"][0]["status"] == "unchanged"
    wrong = tmp_path / "wrong.ics"
    wrong.write_bytes(feed(event()))
    with pytest.raises(ProductivityError, match="stale"):
        rebound.reconnect(source, kind="local", location=wrong, expected_policy_revision=1,
                          confirmed=True)
    assert vault.values != {}


def test_installed_qualification_entry_exercises_actual_worker_and_transfer(tmp_path):
    from provelume.icalendar_qualification import qualify_icalendar

    vault = MemoryVault()
    report = qualify_icalendar(tmp_path / "Fresh", vault=vault)
    assert report["result"] == "PASS" and not report["network_used"]
    assert report["parser_process"] == "REAL_ISOLATED_WORKER"
    assert report["portable_rebuild"] == "PASS" and vault.values == {}


def test_https_worker_owner_covers_dns_and_preserves_proxy_ca_without_logging(monkeypatch):
    from pathlib import Path

    from provelume.icalendar_feeds import fetch_https

    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic-proxy.invalid:3128")
    monkeypatch.setenv("SSL_CERT_FILE", "/synthetic/ca.pem")
    monkeypatch.setenv("UNRELATED_PROVIDER_TOKEN", "must-not-inherit")

    def run(command, **options):
        assert options["timeout"] <= 30 and options["env"]["SSL_CERT_FILE"] == "/synthetic/ca.pem"
        assert options["env"]["HTTPS_PROXY"] == "http://synthetic-proxy.invalid:3128"
        assert "UNRELATED_PROVIDER_TOKEN" not in options["env"]
        source = Path(command[command.index("--input") + 1])
        header = json.loads(source.read_bytes().split(b"\n", 1)[0])
        assert header["mode"] == "fetch" and header["location"]["authorization"] == "Bearer secret"
        Path(command[command.index("--output") + 1]).write_bytes(feed(event()))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    raw = fetch_https({"location": "https://example.invalid/feed",
                       "authorization": "Bearer secret"}, float("inf"))
    assert raw == feed(event())


def test_separate_parser_processes_cannot_share_conflicting_custom_timezone_cache(
    journey, tmp_path
):
    instance, manager, _vault = journey
    starts = []
    for index, offset in enumerate(("+0300", "+0400")):
        zone = ("BEGIN:VTIMEZONE\r\nTZID:Custom/SameName\r\nBEGIN:STANDARD\r\n"
                f"DTSTART:19700101T000000\r\nTZOFFSETFROM:{offset}\r\nTZOFFSETTO:{offset}\r\n"
                "END:STANDARD\r\nEND:VTIMEZONE\r\n")
        raw = feed(event(start="DTSTART;TZID=Custom/SameName:20261107T100000",
                         end="DTEND;TZID=Custom/SameName:20261107T110000"), extra=zone)
        source, _path = add_local(journey, tmp_path, raw, "Zone" + str(index))
        manager.refresh(source)
        starts.append(ProductivityIntake(instance.store).records(source)[0]["item"]["starts"]["value"])
    assert starts == ["2026-11-07T07:00:00+00:00", "2026-11-07T06:00:00+00:00"]
