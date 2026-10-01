"""Synthetic host-binding conformance, distinct from native DPAPI/device acceptance."""

import base64
import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from provelume.capture_adapter import CaptureAdapter
from provelume.capture_authority import CaptureAuthority
from provelume.capture_http import create_capture_app
from provelume.capture_journal import CaptureJournalError
from provelume.mobile_retrieval import MobileRetrieval
from provelume.storage import InstanceStore

ORIGIN = "https://mobile.example.test"


@pytest.fixture
def mobile(tmp_path, monkeypatch):
    store = InstanceStore.initialise(tmp_path / "i")
    # A synthetic host capability lets conformance run without an OS credential vault.
    # Existing test_capture_surface still requires actual DPAPI on Windows, unchanged.
    key = b"synthetic-test-host-key-32-bytes!!"
    monkeypatch.setattr(CaptureAuthority, "_key", lambda self, create=False: key)
    authority = CaptureAuthority(store)
    authority.configure(ORIGIN, confirm_rebind=True, authorize_owner=lambda: None)
    devices, acquired = [], []
    for label in ("Synthetic phone A", "Synthetic phone B"):
        code = authority.challenge(authorize_owner=lambda: None)
        device = authority.redeem(code["challenge"], label, origin=ORIGIN)
        devices.append(device)
        adapter = CaptureAdapter(store, authorize=lambda *a: None)
        identifier = str(uuid4())
        adapter.submit(
            device["device_id"],
            b"synthetic searchable text <script>active</script>",
            {
                "schema_version": 1,
                "client_submission_id": identifier,
                "captured_at": datetime.now(UTC).isoformat(),
                "mode": "text",
                "channel": "paired_pwa",
            },
            channel="paired_pwa",
        )
        result = adapter.process(device["device_id"], identifier, channel="paired_pwa")
        acquired.append(result["receipt"])
    client = TestClient(
        create_capture_app(store.paths.root, trusted_origin=ORIGIN), base_url=ORIGIN
    )
    return store, authority, devices, acquired, client


def grant(mobile, sources=None, device=0):
    _, authority, devices, acquired, _ = mobile
    return authority.grant_retrieval(
        devices[device]["device_id"],
        sources or [acquired[0]["source_id"]],
        600,
        authorize_owner=lambda: None,
    )


def headers(value):
    return {
        "Origin": ORIGIN,
        "Authorization": "Bearer " + value["credential"],
        "X-Retrieval-Device": value["device_id"],
    }


def test_capture_credential_never_authorizes_knowledge(mobile):
    _, _, devices, _, client = mobile
    assert client.get("/capture/knowledge/recent", headers=headers(devices[0])).status_code == 403
    assert client.get("/capture/knowledge/recent").status_code == 403
    value = grant(mobile)
    capture = {**headers(value), "X-Capture-Device": value["device_id"]}
    assert client.get("/capture/submissions", headers=capture).status_code == 403


def test_granted_recent_search_detail_and_exact_download(mobile):
    store, _, _, acquired, client = mobile
    value = grant(mobile)
    h = headers(value)
    recent = client.get("/capture/knowledge/recent", headers=h)
    assert recent.status_code == 200, recent.text
    assert [r["id"] for r in recent.json()["items"]] == [acquired[0]["document_id"]]
    assert recent.headers["cache-control"] == "no-store"
    result = client.post("/capture/knowledge/search", json={"query": "searchable"}, headers=h)
    assert result.status_code == 200, result.text
    assert [r["id"] for r in result.json()["items"]] == [acquired[0]["document_id"]]
    path = "/capture/knowledge/documents/" + acquired[0]["document_id"]
    detail = client.get(path, headers=h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["preview"] == "metadata-only"
    assert detail.json()["persistent_cache"] is False
    assert detail.json()["source"]["id"] == acquired[0]["source_id"]
    assert detail.json()["provenance"]
    assert detail.json()["versions"][0]["acquired_at"]
    assert "<script>" not in detail.text
    original = client.post(
        path + "/versions/" + acquired[0]["version_id"] + "/original", json={}, headers=h
    )
    assert original.status_code == 200, original.text
    assert original.content == b"synthetic searchable text <script>active</script>"
    assert "attachment" in original.headers["content-disposition"]
    assert original.headers["content-type"] == "application/octet-stream"
    assert original.headers["cache-control"] == "no-store"
    assert original.headers["x-content-type-options"] == "nosniff"
    assert original.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert len(store.list_canonical("acquisitions")) == 2


def test_admin_grant_is_local_owner_only_and_consent_is_scoped(mobile):
    from fastapi import FastAPI

    from provelume.capture_http import attach_capture_routes

    store, _, devices, acquired, remote = mobile
    app = FastAPI()
    attach_capture_routes(app, store)
    local = TestClient(app)
    data = {
        "device_id": devices[0]["device_id"],
        "source_ids": [acquired[0]["source_id"]],
        "seconds": 600,
    }
    assert local.post("/capture/admin/retrieval/grant", json=data).status_code == 403
    session = local.post("/capture/session", json={}, headers={"Origin": "http://testserver"})
    h = {"Origin": "http://testserver", "X-Capture-Nonce": session.json()["nonce"]}
    result = local.post("/capture/admin/retrieval/grant", json=data, headers=h)
    assert result.status_code == 200, result.text
    assert remote.post("/capture/admin/retrieval/grant", json=data).status_code == 404
    assert (
        remote.get("/capture/knowledge/recent", headers=headers(result.json())).status_code == 200
    )
    h["Origin"] = "https://foreign.test"
    assert local.post("/capture/admin/retrieval/grant", json=data, headers=h).status_code == 403


def test_cross_source_device_instance_and_version_isolation(mobile, tmp_path):
    store, authority, devices, acquired, client = mobile
    value = grant(mobile)
    h = headers(value)
    forbidden = "/capture/knowledge/documents/" + acquired[1]["document_id"]
    assert client.get(forbidden, headers=h).status_code == 404
    selected = "/capture/knowledge/documents/" + acquired[0]["document_id"]
    assert (
        client.post(
            selected + "/versions/" + acquired[1]["version_id"] + "/original", json={}, headers=h
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/capture/knowledge/recent",
            headers={**h, "X-Retrieval-Device": devices[1]["device_id"]},
        ).status_code
        == 403
    )
    other = InstanceStore.initialise(tmp_path / "other")
    with pytest.raises(PermissionError):
        CaptureAuthority(other).authorize_retrieval(
            value["device_id"], value["credential"], origin=ORIGIN
        )
    assert value["credential"] not in authority.path.read_text()
    assert (
        hashlib.sha256(value["credential"].encode()).hexdigest() not in authority.path.read_text()
    )
    assert store.read_config()["instance"]["id"] == value["instance_id"]


@pytest.mark.parametrize("change", ["expired", "grant-revoked", "device-revoked", "rebind"])
def test_expiry_revocation_and_rebind_stop_every_read(mobile, change):
    _, authority, devices, acquired, client = mobile
    value = grant(mobile)
    if change == "expired":
        state = authority.read()
        state["retrieval"][value["device_id"]]["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        authority._write(state)
    elif change == "grant-revoked":
        authority.revoke_retrieval(value["device_id"], authorize_owner=lambda: None)
    elif change == "device-revoked":
        authority.revoke(value["device_id"], authorize_owner=lambda: None)
    else:
        authority.configure(ORIGIN, confirm_rebind=True, authorize_owner=lambda: None)
    h = headers(value)
    root = "/capture/knowledge/documents/" + acquired[0]["document_id"]
    assert client.get("/capture/knowledge/recent", headers=h).status_code == 403
    assert (
        client.post("/capture/knowledge/search", json={"query": "text"}, headers=h).status_code
        == 403
    )
    assert client.get(root, headers=h).status_code == 403
    assert (
        client.post(
            root + "/versions/" + acquired[0]["version_id"] + "/original", json={}, headers=h
        ).status_code
        == 403
    )
    if change in {"expired", "grant-revoked"}:
        authority.authorize(devices[0]["device_id"], devices[0]["credential"], origin=ORIGIN)


@pytest.mark.parametrize("query", ["", "x" * 129, None, {"malformed": True}])
def test_bounded_search_errors_preserve_state(mobile, query):
    store, authority, _, _, client = mobile
    value = grant(mobile)
    before = authority.path.read_bytes()
    assert (
        client.post(
            "/capture/knowledge/search", json={"query": query}, headers=headers(value)
        ).status_code
        == 400
    )
    assert authority.path.read_bytes() == before
    assert len(store.list_canonical("acquisitions")) == 2


def test_integrity_error_rejects_download_without_reacquisition(mobile):
    store, _, _, acquired, client = mobile
    value = grant(mobile)
    original = store.read_canonical("originals", acquired[0]["original_id"])
    (store.paths.root / original["storage_ref"]).write_bytes(b"tampered")
    path = (
        "/capture/knowledge/documents/"
        + acquired[0]["document_id"]
        + "/versions/"
        + acquired[0]["version_id"]
        + "/original"
    )
    assert client.post(path, json={}, headers=headers(value)).status_code == 409
    assert len(store.list_canonical("acquisitions")) == 2


def test_mid_read_revocation_is_rechecked(mobile):
    store, _, _, acquired, _ = mobile
    source = acquired[0]["source_id"]
    calls = []

    def authorize():
        calls.append(True)
        if len(calls) > 1:
            raise PermissionError("revoked during read")
        return {"source_ids": [source], "expires_at": "synthetic"}

    with pytest.raises(PermissionError, match="during read"):
        MobileRetrieval(store, authorize).detail(acquired[0]["document_id"])


def test_grant_replacement_invalidates_previous_token_and_import_without_key(
    mobile, tmp_path, monkeypatch
):
    store, authority, _, _, client = mobile
    old = grant(mobile)
    new = grant(mobile)
    assert client.get("/capture/knowledge/recent", headers=headers(old)).status_code == 403
    assert client.get("/capture/knowledge/recent", headers=headers(new)).status_code == 200
    imported = tmp_path / "imported"
    shutil.copytree(store.paths.root, imported)
    monkeypatch.setattr(CaptureAuthority, "_key", lambda self, create=False: None)
    with pytest.raises(PermissionError):
        CaptureAuthority(InstanceStore(imported)).authorize_retrieval(
            new["device_id"], new["credential"], origin=ORIGIN
        )


@pytest.mark.parametrize("seconds", [True, 59, 86401, "600"])
def test_grant_requires_explicit_bounded_owner_scope(mobile, seconds):
    _, authority, devices, acquired, _ = mobile
    with pytest.raises(CaptureJournalError):
        authority.grant_retrieval(
            devices[0]["device_id"],
            [acquired[0]["source_id"]],
            seconds,
            authorize_owner=lambda: None,
        )


def test_foreign_origin_queries_and_unauthenticated_original_fail_before_payload(mobile):
    _, _, _, acquired, client = mobile
    value = grant(mobile)
    assert (
        client.get(
            "/capture/knowledge/recent?credential=synthetic", headers=headers(value)
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/capture/knowledge/recent",
            headers={**headers(value), "Origin": "https://foreign.test"},
        ).status_code
        == 403
    )


    root = "/capture/knowledge/documents/" + acquired[0]["document_id"]
    assert (
        client.post(
            root + "/versions/" + acquired[0]["version_id"] + "/original",
            content=base64.b64encode(b"malformed"),
        ).status_code
        == 403
    )


@pytest.mark.parametrize("point", ["prepared", "replaced", "committed"])
def test_interrupted_retrieval_revocation_uses_existing_atomic_recovery(mobile, monkeypatch, point):
    from provelume import capture_authority as module
    from provelume.atomic_commit import replace_file

    store, authority, _, _, _ = mobile
    value = grant(mobile)
    factory = module.AtomicInstanceCommit
    original_write = store._atomic_bytes

    def replace(source, target):
        if point == "replaced":
            replace_file(source, target)
        raise SystemExit()

    def write(path, data):
        original_write(path, data)
        if path.name == "manifest.json" and b'"status": "committed"' in data:
            raise SystemExit()

    with monkeypatch.context() as fault:
        if point == "committed":
            fault.setattr(store, "_atomic_bytes", write)
        else:
            fault.setattr(
                module, "AtomicInstanceCommit", lambda *a, **k: factory(*a, **k, replace=replace)
            )
        with pytest.raises(SystemExit):
            authority.revoke_retrieval(value["device_id"], authorize_owner=lambda: None)
    with pytest.raises(CaptureJournalError, match="recovery required"):
        authority.authorize_retrieval(value["device_id"], value["credential"], origin=ORIGIN)
    InstanceStore.open(store.paths.root)
    if point == "committed":
        with pytest.raises(PermissionError):
            authority.authorize_retrieval(value["device_id"], value["credential"], origin=ORIGIN)
    else:
        authority.authorize_retrieval(value["device_id"], value["credential"], origin=ORIGIN)
    assert len(store.list_canonical("acquisitions")) == 2
