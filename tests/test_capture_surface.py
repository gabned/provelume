"""Real Capture domain operations through both protected HTTP boundaries."""

import base64
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from provelume.capture_authority import CaptureAuthority
from provelume.capture_http import attach_capture_routes, create_capture_app
from provelume.capture_integrity import capture_state_findings
from provelume.capture_journal import CaptureJournalError
from provelume.capture_quarantine import CaptureQuarantine
from provelume.instance_validation import inspect_instance
from provelume.storage import InstanceStore

ORIGIN = "https://capture.example.test"


@pytest.fixture
def store(tmp_path):
    return InstanceStore.initialise(tmp_path / "i")


def configured(store):
    authority = CaptureAuthority(store)
    authority.configure(ORIGIN, confirm_rebind=True, authorize_owner=lambda: None)
    return authority


def paired(authority):
    challenge = authority.challenge(authorize_owner=lambda: None)
    return authority.redeem(challenge["challenge"], "Phone", origin=ORIGIN)


def credentials(value):
    return {
        "Origin": ORIGIN,
        "Authorization": "Bearer " + value["credential"],
        "X-Capture-Device": value["device_id"],
    }


def submission(channel="paired_pwa", payload=b"Captured text", **changes):
    return {
        "metadata": {
            "schema_version": 1,
            "client_submission_id": str(uuid4()),
            "mode": "text",
            "channel": channel,
            "captured_at": "2026-09-27T10:00:00Z",
            **changes,
        },
        "payload_base64": base64.b64encode(payload).decode(),
    }


def test_pairing_verifiers_revocation_and_import_isolation(store, tmp_path):
    authority = configured(store)
    value = paired(authority)
    authority.authorize(value["device_id"], value["credential"], origin=ORIGIN)
    serialized = authority.path.read_text()
    assert value["credential"] not in serialized
    imported = tmp_path / "import"
    shutil.copytree(store.paths.root, imported)
    imported_authority = CaptureAuthority(InstanceStore(imported))
    assert not imported_authority.management()["active"]
    with pytest.raises(PermissionError):
        imported_authority.authorize(value["device_id"], value["credential"], origin=ORIGIN)
    authority.revoke(value["device_id"], authorize_owner=lambda: None)
    with pytest.raises(PermissionError):
        authority.authorize(value["device_id"], value["credential"], origin=ORIGIN)
    assert authority.read()["devices"][value["device_id"]]["revoked_at"]


def test_single_use_challenge_and_destination_scope(store):
    authority = configured(store)
    code = authority.challenge(authorize_owner=lambda: None)
    with pytest.raises(PermissionError):
        authority.redeem(code["challenge"], "Wrong", origin="https://foreign.test")
    authority.redeem(code["challenge"], "Phone", origin=ORIGIN)
    with pytest.raises(PermissionError):
        authority.redeem(code["challenge"], "Again", origin=ORIGIN)
    assert len(authority.read()["devices"]) == 1


def test_device_and_credential_collisions_do_not_overwrite_authority(store, monkeypatch):
    from uuid import UUID

    from provelume import capture_authority as module

    authority = configured(store)
    existing = paired(authority)
    code = authority.challenge(authorize_owner=lambda: None)
    before = authority.path.read_bytes()
    monkeypatch.setattr(module, "uuid4", lambda: UUID(existing["device_id"][4:]))
    with pytest.raises(CaptureJournalError, match="conflict"):
        authority.redeem(code["challenge"], "Collision", origin=ORIGIN)
    assert authority.path.read_bytes() == before
    monkeypatch.undo()
    monkeypatch.setattr(module.secrets, "token_urlsafe", lambda _: existing["credential"])
    with pytest.raises(CaptureJournalError, match="conflict"):
        authority.redeem(code["challenge"], "Collision", origin=ORIGIN)
    assert authority.path.read_bytes() == before
    authority.authorize(existing["device_id"], existing["credential"], origin=ORIGIN)


def test_concurrent_pairing_has_one_winner(store):
    authority = configured(store)
    code = authority.challenge(authorize_owner=lambda: None)

    def attempt():
        try:
            return authority.redeem(code["challenge"], "Phone", origin=ORIGIN)
        except (PermissionError, RuntimeError):
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(authority.read()["devices"]) == 1


def test_corrupt_authority_is_not_reset(store):
    authority = configured(store)
    broken = authority.read()
    broken["schema_version"] = 2
    authority.path.write_text(json.dumps(broken))
    before = authority.path.read_bytes()
    with pytest.raises(CaptureJournalError):
        authority.configure(ORIGIN, confirm_rebind=True, authorize_owner=lambda: None)
    assert authority.path.read_bytes() == before
    assert capture_state_findings(store)[0]["code"] == "capture_state_invalid"


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://foreign.test"},
        {"Host": "foreign.test"},
        {"Origin": ORIGIN, "X-Forwarded-Proto": "https"},
    ],
)
def test_plaintext_or_foreign_boundary_rejected(store, headers):
    configured(store)
    client = TestClient(
        create_capture_app(store.paths.root, trusted_origin=ORIGIN),
        base_url="http://capture.example.test",
    )
    assert client.get("/capture/capabilities", headers=headers).status_code == 403


def test_paired_receipt_replay_cross_device_revocation_and_safe_download(store):
    authority = configured(store)
    first, second = paired(authority), paired(authority)
    client = TestClient(
        create_capture_app(store.paths.root, trusted_origin=ORIGIN), base_url=ORIGIN
    )
    headers = credentials(first)
    body = submission()
    response = client.post("/capture/submissions", json=body, headers=headers)
    assert response.status_code == 200, response.text
    accepted = response.json()["submission"]
    assert (
        client.post("/capture/submissions", json=body, headers=headers).json()["submission"]
        == accepted
    )
    identifier = body["metadata"]["client_submission_id"]
    path = "/capture/submissions/" + identifier
    assert client.get(path, headers=credentials(second)).status_code == 404
    result = client.post(path + "/process", json={}, headers=headers)
    assert result.status_code == 200, result.text
    original = client.get(path + "/original", headers=headers)
    assert original.content == b"Captured text"
    assert original.headers["content-type"] == "application/octet-stream"
    assert "attachment" in original.headers["content-disposition"]
    assert original.headers["cache-control"] == "no-store"
    assert original.headers["x-content-type-options"] == "nosniff"
    assert client.get("/capture/admin/devices", headers=headers).status_code == 404
    assert capture_state_findings(store) == []
    authority.revoke(first["device_id"], authorize_owner=lambda: None)
    assert client.get(path, headers=headers).status_code == 403
    assert len(store.list_canonical("acquisitions")) == 1


def test_local_nonce_origin_and_http_fallback(store):
    app = FastAPI()
    attach_capture_routes(app, store)
    client = TestClient(app)
    assert client.get("/capture/").status_code == 200
    assert client.get("/capture/worker.js").status_code == 409
    assert client.post("/capture/session", json={}).status_code == 403
    session = client.post("/capture/session", json={}, headers={"Origin": "http://testserver"})
    assert session.status_code == 200, session.text
    headers = {"Origin": "http://testserver", "X-Capture-Nonce": session.json()["nonce"]}
    body = submission(channel="local_browser")
    assert client.post("/capture/submissions", json=body, headers=headers).status_code == 200
    headers["Origin"] = "https://foreign.test"
    assert client.post("/capture/submissions", json=body, headers=headers).status_code == 403


def test_actual_photo_decode_precedes_ack_and_original_is_retained(store):
    authority = configured(store)
    value = paired(authority)
    client = TestClient(
        create_capture_app(store.paths.root, trusted_origin=ORIGIN), base_url=ORIGIN
    )
    headers = credentials(value)
    invalid = submission(
        payload=b"not a PNG", mode="photo", filename="capture.png", declared_mime="image/png"
    )
    assert client.post("/capture/submissions", json=invalid, headers=headers).status_code == 400
    image = BytesIO()
    Image.new("RGB", (16, 16), "blue").save(image, "PNG")
    valid = submission(
        payload=image.getvalue(), mode="photo", filename="capture.png", declared_mime="image/png"
    )
    result = client.post("/capture/submissions", json=valid, headers=headers)
    assert result.status_code == 200, result.text
    path = "/capture/submissions/" + valid["metadata"]["client_submission_id"]
    acquired = client.post(path + "/process", json={}, headers=headers)
    assert acquired.status_code == 200, acquired.text
    assert acquired.json()["receipt"]["processing"]["status"] == "attention"
    assert client.get(path + "/original", headers=headers).content == image.getvalue()


def acquired_text(store):
    from provelume.capture_adapter import CaptureAdapter

    manager = CaptureAdapter(store, authorize=lambda *args: None)
    body = submission(channel="local_browser")
    device = "dev_" + "a" * 32
    receipt = manager.submit(device, b"Captured text", body["metadata"], channel="local_browser")
    result = manager.process(
        device, body["metadata"]["client_submission_id"], channel="local_browser"
    )
    return manager, receipt, result["receipt"]


def test_quarantine_replay_conflict_compensation_and_deep_validation(store):
    manager, receipt, acquired = acquired_text(store)
    quarantine = CaptureQuarantine(store)
    request = str(uuid4())
    event = quarantine.transition(
        receipt["id"], "quarantine", 30, request, authorize_owner=lambda: None
    )
    assert (
        quarantine.transition(
            receipt["id"], "quarantine", 30, request, authorize_owner=lambda: None
        )
        == event
    )
    with pytest.raises(CaptureJournalError, match="Conflicting"):
        quarantine.transition(
            receipt["id"], "quarantine", 31, request, authorize_owner=lambda: None
        )
    assert inspect_instance(store.paths.root)["status"] == "valid"
    quarantine.transition(receipt["id"], "undo", 30, str(uuid4()), authorize_owner=lambda: None)
    assert len(quarantine.read()["events"]) == 2
    assert manager._record(f"state/capture-processing/{receipt['id']}.json") == acquired
    assert len(store.list_canonical("originals")) == 1


@pytest.mark.parametrize("restart", ["open", "listener"])
@pytest.mark.parametrize("domain", ["authority", "quarantine"])
@pytest.mark.parametrize("point", ["prepared", "replaced", "committed"])
def test_new_state_interruptions_recover_without_reset(store, monkeypatch, domain, point, restart):
    from provelume import capture_authority, capture_quarantine
    from provelume.atomic_commit import replace_file

    authority = configured(store)
    value = paired(authority)
    _, receipt, _ = acquired_text(store)
    module = capture_authority if domain == "authority" else capture_quarantine
    factory = module.AtomicInstanceCommit

    def replace(source, target):
        if point == "replaced":
            replace_file(source, target)
        raise SystemExit()

    original_write = store._atomic_bytes

    def write(path, data):
        original_write(path, data)
        if path.name == "manifest.json" and b'"status": "committed"' in data:
            raise SystemExit()

    if point == "committed":
        monkeypatch.setattr(store, "_atomic_bytes", write)
    else:
        monkeypatch.setattr(
            module, "AtomicInstanceCommit", lambda *a, **k: factory(*a, **k, replace=replace)
        )
    with pytest.raises(SystemExit):
        if domain == "authority":
            authority.revoke(value["device_id"], authorize_owner=lambda: None)
        else:
            CaptureQuarantine(store).transition(
                receipt["id"], "quarantine", 30, str(uuid4()), authorize_owner=lambda: None
            )
    monkeypatch.undo()
    with pytest.raises(CaptureJournalError, match="recovery required"):
        authority.management()
    if restart == "listener":
        create_capture_app(store.paths.root, trusted_origin=ORIGIN)
    else:
        InstanceStore.open(store.paths.root)
    assert capture_state_findings(store) == []
    if domain == "authority":
        assert bool(authority.read()["devices"][value["device_id"]]["revoked_at"]) == (
            point == "committed"
        )
    else:
        assert bool(CaptureQuarantine(store).read()["events"]) == (point == "committed")


def test_action_center_projects_capture_without_mutation(store):
    from provelume.action_center_adapters import collect_proposals

    manager, receipt, _ = acquired_text(store)
    CaptureQuarantine(store).transition(
        receipt["id"], "quarantine", 30, str(uuid4()), authorize_owner=lambda: None
    )
    before = {str(p): p.read_bytes() for p in store.paths.root.rglob("*") if p.is_file()}
    result = collect_proposals(store)
    capture = [item for item in result["items"] if item["evidence"].get("producer") == "capture"]
    assert len(capture) == 1
    assert capture[0]["evidence"]["status"] == "quarantined"
    assert capture[0]["allowed_actions"] == ["acknowledge_evidence"]
    assert {str(p): p.read_bytes() for p in store.paths.root.rglob("*") if p.is_file()} == before
    assert (
        manager.journal.lookup(
            receipt["device_id"],
            receipt["metadata"]["client_submission_id"],
            authorize=lambda *a: None,
        )
        == receipt
    )


def test_backup_and_portable_preserve_capture_without_activating_credentials(store, tmp_path):
    from provelume.capture_adapter import CaptureAdapter
    from provelume.instance_backup import verify_backup
    from provelume.portable_transfer import PortableInstanceTransfer
    from provelume.service import ProvelumeInstance

    # Portable staging adds two governed transaction components; keep Windows fixtures short.
    tmp_path = tmp_path.parent / ("p" + uuid4().hex[:6])
    tmp_path.mkdir()

    authority = configured(store)
    device = paired(authority)
    _, receipt, acquired = acquired_text(store)
    quarantine = CaptureQuarantine(store)
    quarantine.transition(
        receipt["id"], "quarantine", 30, str(uuid4()), authorize_owner=lambda: None
    )
    instance = ProvelumeInstance(store.paths.root)
    backup = instance.backup(destination=tmp_path / "backup.zip")
    assert verify_backup(backup["archive"])["status"] == "valid"
    instance.restore(backup["archive"])
    assert CaptureAuthority(store).management()["active"]
    assert capture_state_findings(store) == []
    exported = PortableInstanceTransfer(store).export(tmp_path / "portable.zip")
    target = InstanceStore.initialise(tmp_path / "imported")
    PortableInstanceTransfer(target).import_bundle(exported["archive"])
    assert inspect_instance(target.paths.root)["status"] == "valid"
    imported = CaptureAuthority(target)
    assert not imported.management()["active"]
    with pytest.raises(PermissionError):
        imported.authorize(device["device_id"], device["credential"], origin=ORIGIN)
    reader = CaptureAdapter(target, authorize=lambda *args: None)
    assert reader._record(f"state/capture-processing/{receipt['id']}.json") == acquired
    assert CaptureQuarantine(target).read() == quarantine.read()


def test_expiry_and_authentication_before_body_decode(store):
    authority = configured(store)
    code = authority.challenge(authorize_owner=lambda: None)
    value = authority.read()
    value["challenges"][0]["expires_at"] = "2000-01-01T00:00:00Z"
    authority._write(value)
    with pytest.raises(PermissionError):
        authority.redeem(code["challenge"], "Phone", origin=ORIGIN)
    client = TestClient(
        create_capture_app(store.paths.root, trusted_origin=ORIGIN), base_url=ORIGIN
    )
    assert (
        client.post(
            "/capture/submissions", content=b"not JSON", headers={"Origin": ORIGIN}
        ).status_code
        == 403
    )
    device = paired(authority)
    headers = credentials(device)
    assert (
        client.post(
            "/capture/submissions",
            content=b'{"metadata":{},"metadata":{},"payload_base64":"YQ=="}',
            headers={**headers, "Content-Type": "application/json"},
        ).status_code
        == 400
    )
    assert client.get("/capture/submissions?credential=secret", headers=headers).status_code == 400


def test_unavailable_photo_decoder_is_removed_from_file_selection(monkeypatch):
    from provelume.capture_payloads import capture_capabilities
    from provelume.photo_profiles import PillowPhotoDecoder

    monkeypatch.setattr(
        PillowPhotoDecoder,
        "capability",
        lambda self: {"state": "unavailable", "qualified": False},
    )
    capabilities = capture_capabilities()
    assert capabilities["unavailable_modes"] == ["photo", "scan", "screenshot"]
    assert not any(kind.startswith("image/") for kind in capabilities["modes"]["file"]["types"])
    assert capabilities["modes"]["file"]["extensions"] == [".txt", ".md", ".pdf", ".wav"]
