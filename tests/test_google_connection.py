from __future__ import annotations

import copy
import json
import os
import re
import time
import zipfile
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient

from provelume.google_connection import GoogleConnectionManager
from provelume.google_contract import GOOGLE_CAPABILITY_SCOPES, GoogleItem, GooglePage
from provelume.google_credentials import GoogleCredentialError, GoogleCredentialVault
from provelume.google_oauth import (
    AUTHORIZATION_ENDPOINT,
    PROFILE_ENDPOINTS,
    REVOCATION_ENDPOINT,
    TOKEN_ENDPOINT,
    GoogleConnectionError,
    desktop_client,
    resolve_google_credential,
)
from provelume.oauth_authorization import OAuthAuthorizationError
from provelume.service import ProvelumeInstance
from provelume.web import create_app

REDIRECT = "http://127.0.0.1:18765/google/oauth/callback"
CLIENT = {
    "installed": {
        "client_id": "123-desktop.apps.googleusercontent.com",
        "client_secret": "synthetic-client-secret",
        "project_id": "test-project",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": ["http://localhost"],
    }
}


class MemoryVault:
    def __init__(self):
        self.values = {}
        self.reads = 0

    def read(self, slot):
        self.reads += 1
        return copy.deepcopy(self.values.get(slot))

    def write(self, slot, value):
        self.values[slot] = copy.deepcopy(value)

    def delete(self, slot):
        self.values.pop(slot, None)


class FakeGoogle:
    def __init__(self):
        self.capability = "gmail"
        self.email = "private-account@example.invalid"
        self.calls = []
        self.on_exchange = None
        self.scope_override = None
        self.fail = None

    def request(self, endpoint, *, fields=None, token=None):
        self.calls.append((endpoint, copy.deepcopy(fields), token))
        if self.fail:
            raise GoogleConnectionError(self.fail)
        if endpoint == TOKEN_ENDPOINT:
            if self.on_exchange:
                self.on_exchange()
            return {
                "access_token": "synthetic-access-secret",
                "refresh_token": "synthetic-refresh-secret",
                "scope": self.scope_override or " ".join(GOOGLE_CAPABILITY_SCOPES[self.capability]),
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        if endpoint == PROFILE_ENDPOINTS["gmail"]:
            return {"emailAddress": self.email}
        if endpoint == PROFILE_ENDPOINTS["drive"]:
            return {"user": {"emailAddress": self.email}}
        assert endpoint == REVOCATION_ENDPOINT
        return {}


@pytest.fixture
def journey(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    vault, transport = MemoryVault(), FakeGoogle()
    manager = GoogleConnectionManager(instance.store, vault=vault, transport=transport)
    manager.configure(json.dumps(CLIENT))
    return instance, manager, vault, transport


def callback(request):
    fields = parse_qs(urlsplit(request["authorization_uri"]).query)
    return urlencode(
        {
            "state": fields["state"][0],
            "code": "synthetic-authorization-code",
            "scope": " ".join(request["scopes"]),
        }
    ).encode()


def connect(manager, transport, capability="gmail", identity=None):
    transport.capability = capability
    request = manager.begin(
        capability=capability, consent=True, redirect_uri=REDIRECT, instance_id=identity
    )
    result = manager.complete(callback(request), redirect_uri=REDIRECT)
    return request, result


def test_guided_pkce_separate_consent_and_reconnect_preserves_source(journey):
    instance, manager, vault, transport = journey
    request, first = connect(manager, transport)
    assert request["authorization_uri"].split("?", 1)[0] == AUTHORIZATION_ENDPOINT
    identity = first["instance_id"]
    query = parse_qs(urlsplit(request["authorization_uri"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == list(GOOGLE_CAPABILITY_SCOPES["gmail"])
    assert query["include_granted_scopes"] == ["false"]
    assert "code_verifier" not in query and "client_secret" not in query
    token_request = transport.calls[0][1]
    assert token_request["grant_type"] == "authorization_code"
    assert 43 <= len(token_request["code_verifier"]) <= 128
    connector = instance.connectors.get_instance(identity)
    assert connector["authorization_mode"] == "none" and connector["scopes"] == []
    state = manager.sources._instance_record(identity)
    assert state["capabilities"]["drive"]["authorization_status"] == "not_authorized"
    assert state["capabilities"]["gmail"]["state"] == "disabled"
    source = manager.sources.source_record(first["source_id"])
    cursor = {**source["cursor"], "provider_cursor": "synthetic-private-cursor", "page_ordinal": 2}
    manager.sources.update_cursor(first["source_id"], cursor=cursor, health=source["health"])
    manager.sources.configure_schedule(first["source_id"], mode="interval", interval_seconds=300)
    _, second = connect(manager, transport, identity=identity)
    assert first["source_id"] == second["source_id"]
    retained = manager.sources.source_record(first["source_id"])
    assert retained["cursor"] == cursor and retained["schedule"]["interval_seconds"] == 300
    _, drive = connect(manager, transport, "drive", identity)
    assert drive["source_id"] != first["source_id"]
    manager.disconnect(identity, "gmail")
    assert manager.view()["connections"][0]["capabilities"][0]["name"] == "drive"
    assert (
        manager.sources.capability_record(identity, "drive")["authorization_status"] == "authorized"
    )
    assert not any(call[0] == REVOCATION_ENDPOINT for call in transport.calls)
    assert len([key for key in vault.values if key.startswith("google_grant_")]) == 1


@pytest.mark.parametrize(
    "auth_uri", [None, "https://accounts.google.com/o/oauth2/auth", AUTHORIZATION_ENDPOINT]
)
def test_desktop_client_accepts_google_download_metadata(auth_uri):
    document = copy.deepcopy(CLIENT)
    if auth_uri is None:
        document["installed"].pop("auth_uri")
    else:
        document["installed"]["auth_uri"] = auth_uri
    assert desktop_client(document) == {
        key: CLIENT["installed"][key] for key in ("client_id", "client_secret", "project_id")
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("auth_uri", "https://example.invalid/o/oauth2/auth"),
        ("auth_uri", "https://accounts.google.com.example.invalid/o/oauth2/auth"),
        ("auth_uri", "http://accounts.google.com/o/oauth2/auth"),
        ("auth_uri", "https://accounts.google.com/o/oauth2/auth?redirect_uri=https://example.invalid"),
        ("auth_uri", "https://accounts.google.com/o/oauth2/auth/"),
        ("auth_uri", "https://accounts.google.com/o/oauth2/v2/auth#fragment"),
        ("auth_uri", None),
        ("auth_uri", []),
        ("token_uri", "https://example.invalid/token"),
    ],
)
def test_desktop_client_rejects_untrusted_endpoint_metadata(field, value):
    document = copy.deepcopy(CLIENT)
    document["installed"][field] = value
    with pytest.raises(GoogleConnectionError, match="google_client_invalid"):
        desktop_client(document)


@pytest.mark.parametrize("change", ["network", "scope", "cancel", "account", "expired"])
def test_callback_failure_never_commits_or_retains_staged_grant(journey, change):
    instance, manager, vault, transport = journey
    _, initial = connect(manager, transport)
    identity = initial["instance_id"]
    before = manager.sources._instance_record(identity)
    secrets_before = copy.deepcopy(vault.values)
    request = manager.begin(
        capability="gmail", consent=True, redirect_uri=REDIRECT, instance_id=identity
    )
    if change == "network":

        def disable():
            config = instance.store.read_config()
            config["network"]["external_access"] = False
            instance.store.write_config(config)

        transport.on_exchange = disable
    elif change == "scope":
        transport.scope_override = "https://www.googleapis.com/auth/drive"
    elif change == "cancel":
        transport.on_exchange = lambda: manager.cancel(identity, "gmail")
    elif change == "account":
        transport.email = "other-account@example.invalid"
    else:
        for session in manager._sessions.values():
            session["deadline"] = 0
    with pytest.raises((GoogleConnectionError, OAuthAuthorizationError)):
        manager.complete(callback(request), redirect_uri=REDIRECT)
    assert manager.sources._instance_record(identity) == before
    assert vault.values == secrets_before


@pytest.mark.parametrize("change", ["state", "redirect", "replay", "duplicate", "denied"])
def test_callback_bindings_reject_without_exchanging(journey, change):
    _, manager, _, transport = journey
    request = manager.begin(capability="gmail", consent=True, redirect_uri=REDIRECT)
    query = callback(request)
    redirect = REDIRECT
    if change == "state":
        query = b"state=wrong&code=no&scope=no"
    elif change == "redirect":
        redirect = REDIRECT.replace("18765", "18766")
    elif change == "duplicate":
        query += b"&code=second"
    elif change == "denied":
        query = query.replace(b"code=synthetic-authorization-code", b"error=access_denied")
    else:
        manager.complete(query, redirect_uri=redirect)
        transport.calls.clear()
    with pytest.raises((GoogleConnectionError, OAuthAuthorizationError)):
        manager.complete(query, redirect_uri=redirect)
    assert transport.calls == []


def test_offline_and_get_never_resolve_credentials_or_open_socket(journey):
    instance, manager, vault, transport = journey
    _, connected = connect(manager, transport)
    before_reads, before_calls = vault.reads, len(transport.calls)
    config = instance.store.read_config()
    config["network"]["external_access"] = False
    instance.store.write_config(config)
    assert manager.view()["network_enabled"] is False
    with pytest.raises(GoogleConnectionError, match="google_network_disabled"):
        manager.begin(capability="gmail", consent=True, redirect_uri=REDIRECT)
    with pytest.raises(GoogleConnectionError, match="google_network_disabled"):
        manager.test(connected["instance_id"], "gmail")
    assert vault.reads == before_reads and len(transport.calls) == before_calls


def test_refresh_and_remote_project_revocation_are_explicit(journey):
    _, manager, vault, transport = journey
    _, gmail = connect(manager, transport)
    identity = gmail["instance_id"]
    _, _drive = connect(manager, transport, "drive", identity)
    item = manager.sources.capability_record(identity, "gmail")
    slot = item["credential_reference"]["name"]
    vault.values[slot]["expires_at"] = time.time() - 1
    transport.capability = "gmail"
    assert resolve_google_credential(item["credential_reference"], vault=vault, transport=transport)
    assert transport.calls[-1][1]["grant_type"] == "refresh_token"
    with pytest.raises(GoogleConnectionError, match="google_consent_required"):
        manager.revoke_project(identity, "gmail", consent=False)
    result = manager.revoke_project(identity, "gmail", consent=True)
    assert result["affected_capabilities"] == 2
    assert {c["status"] for c in manager.view()["connections"][0]["capabilities"]} == {"revoked"}
    assert len([call for call in transport.calls if call[0] == REVOCATION_ENDPOINT]) == 1
    assert not any(key.startswith("google_grant_") for key in vault.values)


def test_secrets_and_unneeded_identity_absent_from_state_backup_and_portable(journey, tmp_path):
    instance, manager, _, transport = journey
    connect(manager, transport)
    paths = [path for path in instance.store.paths.root.rglob("*") if path.is_file()]
    stored = b"\n".join(path.read_bytes() for path in paths)
    outputs = [stored, json.dumps(manager.view()).encode()]
    archive = tmp_path / "portable.zip"
    instance.export_portable(archive)
    backup = instance.backup(destination=tmp_path / "backup.zip")
    for path in (archive, backup["archive"]):
        with zipfile.ZipFile(path) as bundle:
            outputs.append(b"\n".join(bundle.read(name) for name in bundle.namelist()))
    for output in outputs:
        for prohibited in (
            b"synthetic-access-secret",
            b"synthetic-refresh-secret",
            b"synthetic-client-secret",
            b"synthetic-authorization-code",
            b"private-account@example.invalid",
            b"access_token",
            b"refresh_token",
            CLIENT["installed"]["client_id"].encode(),
        ):
            assert prohibited not in output


def test_guided_browser_and_read_model_are_safe_local_and_bilingual(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    app = create_app(instance.store.paths.root, effective_port=18765)
    manager = app.state.provelume.google_connection
    manager.vault = MemoryVault()
    manager.transport = FakeGoogle()
    client = TestClient(app)
    english = client.get("/google/connect?lang=en")
    italian = client.get("/google/connect?lang=it")
    assert english.status_code == italian.status_code == 200
    assert "Connect Google" in english.text and "Connetti Google" in italian.text
    assert 'name="consent" value="yes" required' in english.text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', english.text)[1]
    assert english.headers["cache-control"] == "no-store"
    assert client.post("/google/connect", data={"action": "configure"}).status_code == 403
    response = client.post(
        "/google/connect",
        data={"action": "configure", "csrf_token": csrf, "client_json": json.dumps(CLIENT)},
    )
    assert response.status_code == 200 and "synthetic-client-secret" not in response.text
    assert (
        client.post(
            "/google/connect",
            content=f"csrf_token={csrf}&action=test&action=connect",
            headers={"content-type": "application/x-www-form-urlencoded"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/google/connect",
            content=b"x" * 25000,
            headers={"content-type": "application/x-www-form-urlencoded"},
        ).status_code
        == 413
    )
    remote = TestClient(app, client=("192.0.2.8", 41000))
    assert remote.post("/google/connect", data={"csrf_token": csrf}).status_code == 403
    assert 'name="client_json"' not in remote.get("/google/connect").text
    public = client.get("/api/v1/google/connection").json()
    assert public["read_only"] is True and public["connections"] == []
    assert client.post("/api/v1/google/connection").status_code == 405


@pytest.mark.skipif(os.name != "nt", reason="actual current-user Windows DPAPI")
def test_actual_windows_dpapi_restart_delete_and_tamper(tmp_path):
    root = tmp_path / "external-credentials"
    vault = GoogleCredentialVault(windows_root=root)
    value = {
        "access_token": "windows-synthetic-access",
        "refresh_token": "windows-synthetic-refresh",
    }
    vault.write("google_test_vault", value)
    encrypted = (root / "google_test_vault.dpapi").read_bytes()
    assert b"windows-synthetic" not in encrypted
    assert GoogleCredentialVault(windows_root=root).read("google_test_vault") == value
    (root / "google_test_vault.dpapi").write_bytes(encrypted[:-20] + b"tampered")
    with pytest.raises(GoogleCredentialError):
        vault.read("google_test_vault")
    vault.delete("google_test_vault")
    assert vault.read("google_test_vault") is None


def test_backfill_checkpoints_continue_without_dropping_pages(journey):
    from provelume.google_adapters import SyntheticGoogleAdapter
    from provelume.google_jobs import GoogleJobManager

    instance, manager, _, transport = journey
    _, connected = connect(manager, transport)
    identity, source_id = connected["instance_id"], connected["source_id"]
    manager.sources.set_capability_state(identity, "gmail", "enabled")
    manager.sources.set_source_state(source_id, "enabled")
    pages = [
        GooglePage(
            capability="gmail",
            items=tuple(
                GoogleItem(
                    capability="gmail",
                    provider_item_id=f"message-{number}",
                    provider_revision_id=f"revision-{number}",
                    payload=f"Subject: message {number}\r\n\r\nBody {number}\r\n".encode(),
                    media_type="message/rfc822",
                )
                for number in range(page * 2, page * 2 + 2)
            ),
        )
        for page in range(5)
    ]
    adapter = SyntheticGoogleAdapter({source_id: pages})
    instance.google.adapter = adapter
    instance.scheduler._google_manager_factory = lambda store: GoogleJobManager(
        store, adapter=adapter
    )
    for expected_status in ("continuation_available", "continuation_available", "completed"):
        queued = instance.google.queue(source_id, guided=True)
        assert queued["request"]["limits"]["max_items_per_run"] == 50
        job_id = queued["job"]["id"]
        result = instance.run_google_job(job_id)
        assert result["status"] == "succeeded"
        assert instance.google.get_job(job_id)["google_run"]["status"] == expected_status
    assert [call["page"] for call in adapter.calls] == [0, 1, 2, 3, 4]
    assert manager.sources.source_record(source_id)["cursor"]["provider_cursor"] is None
    assert len(instance.store.list_canonical("email-messages")) == 10


def test_ordinary_http_connect_callback_reconnect_and_evidence_binding(
    tmp_path, monkeypatch, caplog
):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    app = create_app(instance.store.paths.root, effective_port=18765)
    manager = app.state.provelume.google_connection
    manager.vault, manager.transport = MemoryVault(), FakeGoogle()
    manager.configure(json.dumps(CLIENT))
    client = TestClient(app, base_url="http://127.0.0.1:18765")
    page = client.get("/google/connect?lang=it")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    assert (
        client.post(
            "/google/connect",
            data={"csrf_token": csrf, "action": "network", "enabled": "yes", "consent": "yes"},
        ).status_code
        == 200
    )
    identities = []
    for _ in range(2):
        response = client.post(
            "/google/connect",
            data={
                "csrf_token": csrf,
                "action": "connect",
                "capability": "gmail",
                "consent": "yes",
                "instance_id": identities[0] if identities else "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        query = parse_qs(urlsplit(response.headers["location"]).query)
        response = client.get(
            "/google/oauth/callback?"
            + urlencode(
                {
                    "state": query["state"][0],
                    "code": "synthetic-authorization-code",
                    "scope": query["scope"][0],
                }
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303 and response.headers["location"] == "/google/connect"
        assert response.headers["referrer-policy"] == "no-referrer"
        view = client.get("/api/v1/google/connection").json()
        identities.append(view["connections"][0]["id"])
    assert identities[0] == identities[1] and len(view["sources"]) == 1
    assert "synthetic-authorization-code" not in response.text + caplog.text
    assert client.get("/google/connect/evidence?expected_head=" + "a" * 40).status_code == 400
    monkeypatch.setattr(
        "provelume.google_connection_evidence.current_build_info",
        lambda: {
            "commit": "a" * 40,
            "source_repository": "gabned/provelume",
            "metadata_present": True,
        },
    )
    report = client.get("/google/connect/evidence?expected_head=" + "a" * 40)
    assert report.status_code == 200 and report.json()["status"] == "INCOMPLETE"
    assert "attachment;" in report.headers["content-disposition"]


def test_expired_authorization_can_reconnect_and_discard_owned_old_secret(journey):
    _, manager, vault, transport = journey
    _, gmail = connect(manager, transport)
    _, drive = connect(manager, transport, "drive", gmail["instance_id"])
    identity = gmail["instance_id"]
    reference = manager.sources.capability_record(identity, "gmail")["credential_reference"]
    vault.values[reference["name"]]["expires_at"] = 0
    transport.fail = "google_reconnect_required"
    with pytest.raises(GoogleConnectionError, match="google_reconnect_required"):
        manager.test(identity, "gmail")
    assert (
        manager.sources._instance_record(identity)["capabilities"]["gmail"]["authorization_status"]
        == "reauthorization_required"
    )
    assert (
        manager.sources.capability_record(identity, "drive")["authorization_status"] == "authorized"
    )
    transport.fail = None
    _, again = connect(manager, transport, "gmail", identity)
    assert again["source_id"] == gmail["source_id"] != drive["source_id"]
    assert reference["name"] not in vault.values


def test_transient_refresh_failure_does_not_revoke_a_grant(journey):
    from provelume.google_contract import GoogleAdapterError

    _, manager, vault, transport = journey
    _, connection = connect(manager, transport)
    identity = connection["instance_id"]
    item = manager.sources.capability_record(identity, "gmail")
    vault.values[item["credential_reference"]["name"]]["expires_at"] = 0
    transport.fail = "google_connection_failed"
    with pytest.raises(GoogleAdapterError, match="Google connection is unavailable"):
        manager.test(identity, "gmail")
    assert manager.sources.capability_record(identity, "gmail") == item


def test_project_revocation_does_not_disconnect_another_google_account(journey):
    _, manager, _, transport = journey
    _, first = connect(manager, transport)
    transport.email = "another-private@example.invalid"
    _, second = connect(manager, transport)
    manager.revoke_project(first["instance_id"], "gmail", consent=True)
    assert (
        manager.sources.capability_record(second["instance_id"], "gmail")["authorization_status"]
        == "authorized"
    )


def test_remote_revoke_disables_every_affected_capability_even_if_secret_cleanup_fails(journey):
    _, manager, vault, transport = journey
    _, first = connect(manager, transport)
    connect(manager, transport, "drive", first["instance_id"])

    def locked(_slot):
        raise GoogleCredentialError("google_secure_store_unavailable")

    vault.delete = locked
    with pytest.raises(GoogleCredentialError):
        manager.revoke_project(first["instance_id"], "gmail", consent=True)
    assert {item["status"] for item in manager.view()["connections"][0]["capabilities"]} == {
        "revoked"
    }


def test_credential_store_never_selects_a_plaintext_backend(monkeypatch):
    vault = GoogleCredentialVault()

    def unavailable():
        raise RuntimeError("private-backend-detail")

    monkeypatch.setattr(vault, "_backend", unavailable)
    if os.name != "nt":
        with pytest.raises(GoogleCredentialError) as caught:
            vault.write("google_test_secret", {"secret": "private-value"})
        assert str(caught.value) == "google_secure_store_unavailable"
    with pytest.raises(GoogleCredentialError):
        vault.read("../not-a-slot")


def test_vault_rejects_instance_storage_and_redirected_directory(tmp_path):
    root = tmp_path / "instance"
    root.mkdir()
    vault = GoogleCredentialVault(windows_root=root / "credentials", forbidden_root=root)
    with pytest.raises(GoogleCredentialError):
        vault._path("google_test_secret")


def test_qualification_report_rejects_unexpected_private_fields(journey, monkeypatch):
    _, manager, _, transport = journey
    connect(manager, transport)
    value = json.loads(manager.evidence.path.read_text())
    value["events"][0]["access_token"] = "prohibited-secret"
    manager.evidence.path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="google_qualification_evidence_invalid"):
        manager.evidence.read()


@pytest.mark.parametrize("action", ["cancel", "disable"])
def test_cancel_or_policy_change_during_page_fetch_prevents_promotion(journey, action):
    from provelume.google_adapters import SyntheticGoogleAdapter
    from provelume.google_jobs import GoogleJobManager

    instance, manager, _, transport = journey
    _, connected = connect(manager, transport)
    identity, source_id = connected["instance_id"], connected["source_id"]
    manager.sources.set_capability_state(identity, "gmail", "enabled")
    manager.sources.set_source_state(source_id, "enabled")
    queued = instance.google.queue(source_id, guided=True)
    job_id = queued["job"]["id"]
    item = GoogleItem(
        capability="gmail",
        provider_item_id="message",
        provider_revision_id="revision",
        payload=b"Subject: cancellation\r\n\r\nNever acquired\r\n",
        media_type="message/rfc822",
    )

    class Interrupting(SyntheticGoogleAdapter):
        def fetch_page(self, **kwargs):
            page = super().fetch_page(**kwargs)
            if action == "cancel":
                instance.cancel_google_job(job_id)
            else:
                manager.sources.set_source_state(source_id, "disabled")
            return page

    adapter = Interrupting({source_id: [GooglePage(capability="gmail", items=(item,))]})
    instance.scheduler._google_manager_factory = lambda store: GoogleJobManager(
        store, adapter=adapter
    )
    result = instance.run_google_job(job_id)
    assert result["status"] in {"cancelled", "failed"}
    assert instance.store.list_canonical("email-messages") == []
    assert instance.google.get_job(job_id)["google_run"]["status"] == result["status"]


def test_legacy_alias_source_cannot_silently_switch_accounts(journey):
    instance, manager, _, transport = journey
    connector = instance.create_google_instance(name="Legacy", account_identity="private alias")
    identity = connector["connector"]["id"]
    source = instance.create_google_source(
        identity,
        name="Legacy Gmail",
        capability="gmail",
        selection_kind="mailbox",
        selectors=["me"],
    )
    before = manager.sources.source_record(source["id"])
    with pytest.raises(GoogleConnectionError, match="google_legacy_connection"):
        manager.begin(capability="gmail", consent=True, redirect_uri=REDIRECT, instance_id=identity)
    assert manager.sources.source_record(source["id"]) == before
    assert transport.calls == []


def test_connection_translation_inventory_has_semantic_parity():
    from provelume.google_connection_i18n import TEXT, connection_translator

    for key, pair in TEXT.items():
        assert len(pair) == 2 and all(isinstance(item, str) and item.strip() for item in pair)
        assert connection_translator("en")(key) == pair[0]
        assert connection_translator("it")(key) == pair[1]
    for key in ("consent", "revoke_help", "network_consent", "bounds", "google_account_mismatch"):
        assert TEXT[key][0] != TEXT[key][1]


def test_locked_store_is_retryable_for_test_and_intake_without_losing_grant(journey, monkeypatch):
    from provelume.google_adapters import GoogleApiAdapter
    from provelume.google_contract import GoogleAdapterError
    from provelume.google_jobs import GoogleJobManager

    instance, manager, vault, transport = journey
    _, connected = connect(manager, transport)
    identity, source_id = connected["instance_id"], connected["source_id"]
    manager.sources.set_capability_state(identity, "gmail", "enabled")
    manager.sources.set_source_state(source_id, "enabled")
    before = manager.sources.capability_record(identity, "gmail")
    saved_read = vault.read

    def locked(slot):
        if slot.startswith("google_grant_"):
            raise GoogleCredentialError("google_secure_store_unavailable")
        return saved_read(slot)

    monkeypatch.setattr(vault, "read", locked)
    with pytest.raises(GoogleAdapterError) as caught:
        manager.test(identity, "gmail")
    assert caught.value.code == "google_secure_store_unavailable"
    assert manager.sources.capability_record(identity, "gmail") == before
    adapter = GoogleApiAdapter(
        credential_resolver=lambda ref: resolve_google_credential(
            ref, vault=vault, transport=transport
        )
    )
    instance.scheduler._google_manager_factory = lambda store: GoogleJobManager(
        store, adapter=adapter
    )
    queued = instance.google.queue(source_id, guided=True)
    result = instance.run_google_job(queued["job"]["id"])
    assert result["status"] == "retry_wait"
    observed = instance.google.get_job(queued["job"]["id"])
    assert observed["google_run"]["error_codes"] == ["google_secure_store_unavailable"]
    assert manager.sources.capability_record(identity, "gmail") == before
    assert instance.store.list_canonical("email-messages") == []
    monkeypatch.setattr(vault, "read", saved_read)
    assert manager.test(identity, "gmail")["status"] == "google_connected"
    assert manager.sources.capability_record(identity, "gmail") == before


def test_failed_callback_always_redirects_browser_to_clean_diagnostic_url(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    app = create_app(instance.store.paths.root, effective_port=18765)
    manager = app.state.provelume.google_connection
    manager.vault, manager.transport = MemoryVault(), FakeGoogle()
    manager.configure(json.dumps(CLIENT))
    manager.set_network(enabled=True, consent=True)
    request = manager.begin(capability="gmail", consent=True, redirect_uri=REDIRECT)
    manager.transport.fail = "google_connection_failed"
    client = TestClient(app, base_url="http://127.0.0.1:18765")
    response = client.get(
        "/google/oauth/callback?" + callback(request).decode(), follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/google/connect?notice=google_connection_failed"
    assert response.headers["referrer-policy"] == "no-referrer"
    page = client.get(response.headers["location"])
    assert page.status_code == 200 and 'role="alert"' in page.text
    assert "synthetic-authorization-code" not in str(page.url) + page.text
    assert "code=" not in str(page.url) and "state=" not in str(page.url)


@pytest.mark.parametrize("failure", ["denied", "expired", "exchange", "cancel", "restart"])
def test_failed_new_consent_removes_only_its_provisional_google_card(journey, failure):
    instance, manager, vault, transport = journey
    request = manager.begin(capability="gmail", consent=True, redirect_uri=REDIRECT)
    identity = request["instance_id"]
    assert len(manager.view()["connections"]) == 1
    if failure == "denied":
        query = callback(request).replace(
            b"code=synthetic-authorization-code", b"error=access_denied"
        )
        with pytest.raises(GoogleConnectionError):
            manager.complete(query, redirect_uri=REDIRECT)
    elif failure == "expired":
        for session in manager._sessions.values():
            session["deadline"] = 0
        with pytest.raises(GoogleConnectionError):
            manager.complete(callback(request), redirect_uri=REDIRECT)
    elif failure == "exchange":
        transport.fail = "google_connection_failed"
        with pytest.raises(GoogleConnectionError):
            manager.complete(callback(request), redirect_uri=REDIRECT)
    elif failure == "cancel":
        manager.cancel(identity, "gmail")
    else:
        record = manager.sources._instance_record(identity)
        manager.sources._write_instance_record({**record, "guided_provisional_until": 0})
        manager = GoogleConnectionManager(instance.store, vault=vault, transport=transport)
        new = manager.begin(capability="gmail", consent=True, redirect_uri=REDIRECT)
        manager.cancel(new["instance_id"], "gmail")
    assert manager.view()["connections"] == []
    assert manager.sources.list_instances() == []
    assert instance.connectors.get_instance(identity)["lifecycle_state"] == "removed"
    assert manager.sources.list_sources() == []
    assert not any(key.startswith("google_grant_") for key in vault.values)


def test_failed_request_preparation_cleans_up_new_provisional_connection(journey, monkeypatch):
    from provelume.oauth_authorization import OAuthAdapterError

    _, manager, _, _ = journey

    def fail(*args):
        raise OAuthAdapterError("synthetic preparation failure")

    monkeypatch.setattr(
        "provelume.google_oauth.GoogleInstalledAppAdapter.build_authorization_uri", fail
    )
    with pytest.raises(OAuthAdapterError):
        manager.begin(capability="gmail", consent=True, redirect_uri=REDIRECT)
    assert manager.view()["connections"] == []


def test_cancelled_reconnect_preserves_established_connection_and_source(journey):
    _, manager, _, transport = journey
    _, original = connect(manager, transport)
    identity = original["instance_id"]
    before = manager.sources._instance_record(identity)
    manager.begin(capability="gmail", consent=True, redirect_uri=REDIRECT, instance_id=identity)
    manager.cancel(identity, "gmail")
    assert manager.sources._instance_record(identity) == before
    assert manager.sources.list_sources()[0]["id"] == original["source_id"]
    assert len(manager.view()["connections"]) == 1
