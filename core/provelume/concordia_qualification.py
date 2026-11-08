"""Integrated synthetic Concordia journey. No live account or remote destination."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .asana_qualification import seed_asana
from .google_adapters import SyntheticGoogleAdapter
from .google_connection import GoogleConnectionManager
from .google_contract import GOOGLE_CAPABILITY_SCOPES, GoogleContractError, GoogleItem, GooglePage
from .google_oauth import PROFILE_ENDPOINTS, TOKEN_ENDPOINT
from .icalendar_feeds import IcalendarFeeds
from .icalendar_qualification import RAW
from .index import verified_email_text_artifact
from .mirror_folder import FolderMirrors
from .mirror_git import GitMirrors
from .mirrors import Mirrors
from .productivity_contract import ProductivityError, require
from .productivity_jobs import ProductivityJobs
from .service import ProvelumeInstance
from .task_writeback_qualification import SyntheticWriteBackFixture
from .tududi_qualification import SyntheticVault, seed_tududi

MAIL = (b"From: sender@example.invalid\r\nTo: recipient@example.invalid\r\n"
        b"Subject: Integrated Concordia\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Synthetic Concordia Gmail searchable body.\r\n")


class SyntheticGoogleOAuth:
    def __init__(self):
        self.subject, self.capability, self.calls = "", "gmail", 0

    def request(self, endpoint, **_options):
        self.calls += 1
        if endpoint == TOKEN_ENDPOINT:
            return {"access_token": "synthetic-concordia-access",
                    "refresh_token": "synthetic-concordia-refresh", "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": " ".join(GOOGLE_CAPABILITY_SCOPES[self.capability])}
        require(endpoint == PROFILE_ENDPOINTS[self.capability], "qualification")
        if self.capability == "drive":
            return {"user": {"emailAddress": self.subject}}
        return {"emailAddress" if self.capability == "gmail" else "id": self.subject}


def canonical_bytes(instance):
    return {p.relative_to(instance.root).as_posix(): p.read_bytes()
            for name in ("knowledge", "originals")
            for p in (instance.root / name).rglob("*") if p.is_file()}


def qualify_concordia(root):
    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    instance = ProvelumeInstance.initialise(root / "Synthetic Space")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    cases = []
    vault, oauth = SyntheticVault(), SyntheticGoogleOAuth()
    google = GoogleConnectionManager(instance.store, vault=vault, transport=oauth)
    google.configure(json.dumps({"installed": {
        "client_id": "123-concordia.apps.googleusercontent.com",
        "client_secret": "synthetic-concordia-client", "project_id": "concordia",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost"]}}))
    redirect = "http://127.0.0.1:18765/google/oauth/callback"
    grants = []
    for account in ("first", "second"):
        oauth.subject = account + "@example.invalid"
        identity = None
        for capability in ("gmail", "drive", "calendar"):
            oauth.capability = capability
            request = google.begin(capability=capability, consent=True,
                                   redirect_uri=redirect, instance_id=identity)
            state = parse_qs(urlsplit(request["authorization_uri"]).query)["state"][0]
            connected = google.complete(urlencode({"state": state, "code": "synthetic-code",
                "scope": " ".join(request["scopes"])}).encode(), redirect_uri=redirect)
            identity, source = connected["instance_id"], connected["source_id"]
            google.sources.set_capability_state(identity, capability, "enabled")
            google.sources.set_source_state(source, "enabled")
            grants.append((identity, source, capability))
    require(len({row[0] for row in grants}) == 2 and len({row[1] for row in grants}) == 6,
            "qualification")
    require(len([key for key in vault.values if key.startswith("google_grant_")]) == 6,
            "qualification")
    cases.append("two_google_identities_six_independent_grants")
    for _identity, source, capability in grants:
        if capability == "calendar":
            class CalendarApi:
                def _request(self, _url, **_options):
                    return json.dumps({"items": [{"id": "synthetic-event", "etag": '"one"',
                        "status": "confirmed", "summary": "Synthetic all-day calendar",
                        "iCalUID": "integrated-uid", "start": {"date": "2026-11-07"},
                        "end": {"date": "2026-11-08"},
                        "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"]}],
                        "timeZone": "Europe/Rome", "nextSyncToken": "synthetic-terminal"
                    }).encode(), "application/json"
            instance.google.calendar_connection = google
            instance.google.calendar_api = CalendarApi()
        else:
            payload = MAIL if capability == "gmail" else b"Synthetic Concordia Drive bytes.\n"
            item = GoogleItem(capability=capability, provider_item_id="same-provider-id",
                              provider_revision_id="same-revision", payload=payload,
                              media_type=("message/rfc822" if capability == "gmail"
                                          else "text/plain"))
            instance.google.adapter = SyntheticGoogleAdapter({source: (
                GooglePage(capability=capability, items=(item,)),)})
        instance.scheduler._google_manager_factory = lambda _store: instance.google
        for attempt in ("initial", "replay"):
            job = instance.google.queue(source, request_key=attempt, guided=True)["job"]
            result = instance.run_google_job(job["id"])
            require(result is not None and result["status"] == "succeeded", "qualification")
    messages = instance.store.list_canonical("email-messages")
    require(len(messages) == 2 and len({m["source_id"] for m in messages}) == 2, "qualification")
    require(all(verified_email_text_artifact(instance.store, m["version_id"]) is not None
                for m in messages), "qualification")
    cases.append("google_read_replay_exact_gmail_bodies_and_calendar_mapping")
    providers = []
    for seed in (seed_asana, seed_tududi):
        for number in (1, 2):
            manager, provider, source = seed(instance, subject="synthetic-user-" + str(number))
            providers.append((manager, provider, source))
    require(len({source for _manager, _provider, source in providers}) == 4, "qualification")
    cases.append("four_independent_read_only_task_identities")
    feed = root / "Synthetic feed.ics"
    feed.write_bytes(RAW)
    feeds = IcalendarFeeds(instance.store, vault=SyntheticVault())
    sources = [feeds.add(name="Synthetic feed " + str(n), kind="local", location=feed,
                         confirmed=True)["source_id"] for n in (1, 2)]
    jobs = ProductivityJobs(instance.store, feeds=feeds)
    instance.scheduler._productivity_manager_factory = lambda _store: jobs
    for source in sources:
        job = jobs.queue(source)["job"]
        result = instance.scheduler.run_one(job_id=job["id"])
        require(result is not None and result["status"] == "succeeded", "qualification")
    require(len(feeds.duplicates()) == 1, "qualification")
    cases.append("two_local_ics_sources_attributed_duplicates")
    task = SyntheticWriteBackFixture(instance)
    task.consent()
    plan = task.prepare({"completed": True})
    receipt = task.engine.confirm(task.object_id, plan["id"],
        expected_plan_sha256=plan["sha256"], confirmed=True)
    require(receipt["status"] == "APPLIED" and task.remote.cas_calls == 1, "qualification")
    require(task.engine.confirm(task.object_id, plan["id"],
        expected_plan_sha256=plan["sha256"], confirmed=True) == receipt
        and task.remote.cas_calls == 1, "qualification")
    for _manager, _provider, source in providers:
        try:
            task.engine.consent(source, enabled=True, fields=["completed"],
                                expected_revision=0, confirmed=True)
        except ProductivityError as error:
            require(error.code == "conditional_write_unavailable", "qualification")
        else:
            require(False, "qualification")
    cases.append("public_tasks_read_only_separate_synthetic_once_only_guard")
    before = canonical_bytes(instance)
    for identity, _source, capability in grants[:1]:
        google.disconnect(identity, capability)
    require(google.sources.capability_record(grants[1][0], "drive")["authorization_status"]
            == "authorized", "qualification")
    try:
        instance.google.queue(grants[0][1], guided=True)
    except GoogleContractError:
        pass
    else:
        require(False, "qualification")
    require(canonical_bytes(instance) == before, "qualification")
    cases.append("gmail_revocation_preserves_other_grants_and_acquired_knowledge")
    for manager, _provider, source in (providers[0], providers[2]):
        identity, _source, _definition = instance.productivity_connectors()._records(source)
        manager.disconnect(identity["id"], expected_revision=manager.record(identity["id"])[
            "revision"], confirmed=True)
        require(manager.record(identity["id"])["status"] == "revoked", "qualification")
        try:
            manager.resolve(identity["id"], "task_read")
        except ProductivityError as error:
            require(error.code == "authorization_required", "qualification")
        else:
            require(False, "qualification")
    for manager, _provider, source in (providers[1], providers[3]):
        identity, _source, _definition = instance.productivity_connectors()._records(source)
        require(manager.record(identity["id"])["status"] == "authorized", "qualification")
    require(canonical_bytes(instance) == before, "qualification")
    cases.append("asana_tududi_revocation_isolated_from_second_identity_and_canonical_data")
    mirrors = Mirrors(instance.store, vault=SyntheticVault())
    mirrors.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    # The integrated Instance includes sensitive provider observations. Its mirror
    # projection is explicitly scoped to a new synthetic Area before any transfer.
    local = root / "Synthetic local input"
    local.mkdir()
    (local / "mirror.md").write_text("# Synthetic integrated mirror\n", encoding="utf-8")
    instance.ingest_run(local)
    area = instance.create_hierarchy_node("area", "Synthetic mirror scope")
    document = next(d for d in instance.store.list_canonical("documents")
                    if d["title"] == "mirror.md")
    instance.classify_document(document["id"], area["id"])
    scope = {"kind": "area", "id": area["id"]}
    for profile in ("folder", "git"):
        identity = mirrors.create_identity(name="Synthetic " + profile, profile=profile,
                                           credential={"reference": ""}, confirmed=True)
        target = ({"transport": "folder", "path": str(root / "Synthetic folder")}
                  if profile == "folder" else {"transport": "local",
                    "repository": str(root / "Synthetic Git.git"), "branch": "concordia",
                    "path": "knowledge", "commit_name": "Synthetic Integration",
                    "commit_email": "integration@example.invalid"})
        row = mirrors.configure(identity_id=identity["id"], name="Synthetic " + profile,
            target=target, scope=scope, include_rules={"originals": [], "attachments": [],
            "ai_receipts": []}, mode="manual", confirmed=True)
        engine = FolderMirrors(instance.store, mirrors=mirrors) if profile == "folder" else (
            GitMirrors(instance.store, mirrors=mirrors))
        engine.initialize_local(row["id"], expected_destination_sha256=row["destination_sha256"],
                                confirmed=True)
        for _repeat in (False, True):
            prepared = engine.prepare(row["id"], expected_revision=1, confirmed=True)
            arguments = {"expected_plan_sha256": prepared["plan_sha256"], "confirmed": True}
            arguments["expected_" + profile + "_plan_sha256"] = prepared[profile + "_plan_sha256"]
            outcome = engine.publish(prepared["id"], **arguments)
            require(outcome["receipt"]["generation"] == prepared["generation"], "qualification")
        cases.append("native_local_" + profile + "_generation_and_repeat")
    before = canonical_bytes(instance)
    calls = oauth.calls + sum(getattr(p, "calls", 0) if type(getattr(p, "calls", 0)) is int
                               else len(p.calls) for _m, p, _s in providers)
    config = instance.store.read_config()
    config["network"]["external_access"] = False
    instance.store.write_config(config)
    archive = root / "Synthetic Root backup"
    backup = instance.backup(destination=archive)
    require(instance.restore(backup["archive"])["status"] == "restored", "qualification")
    require(canonical_bytes(instance) == before, "qualification")
    cases.append("actual_root_backup_restore_canonical_invariance")
    for message in messages:
        instance.email.remove_derived(message["id"])
    portable = root / "Synthetic Portable.zip"
    instance.export_portable(portable, derived_state="rebuild")
    restored = ProvelumeInstance.initialise(root / "Restored Space")
    restored.import_portable(portable)
    require(canonical_bytes(restored) == before, "qualification")
    require(all(verified_email_text_artifact(restored.store, m["version_id"]) is not None
                for m in messages), "qualification")
    require(restored.validate_instance()["status"] == "valid", "qualification")
    require(not restored.store.read_config()["network"]["external_access"], "qualification")
    require(calls == oauth.calls + sum(getattr(p, "calls", 0) if type(getattr(p, "calls", 0)) is int
                else len(p.calls) for _m, p, _s in providers), "qualification")
    cases.append("offline_portable_rebuild_gmail_and_all_provider_records")
    from .build_info import current_build_info

    return {"schema": "concordia-integrated-s23/v1", "result": "PASS", "cases": cases,
            "build": current_build_info(),
            "google_identities": 2, "google_grants": 6, "task_identities": 4, "ics_sources": 2,
            "provider_execution": "SYNTHETIC_ONLY", "live_providers": "NOT_RUN",
            "remote_destinations": "NOT_RUN", "external_network_used": False,
            "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN", "s23_acceptance": "NOT_ACCEPTED"}
