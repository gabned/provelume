from __future__ import annotations

import base64
import json
import socket
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.google_adapters import GoogleApiAdapter, SyntheticGoogleAdapter
from provelume.google_contract import (
    GOOGLE_CAPABILITY_SCOPES,
    GoogleAdapterError,
    GoogleAuthorizationError,
    GoogleContractError,
    GoogleCursorInvalidated,
    GoogleItem,
    GoogleLimits,
    GooglePage,
    GoogleRateLimitError,
)
from provelume.google_jobs import GoogleJobManager
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _message(body: str = "synthetic Gmail body") -> bytes:
    return (
        "From: Synthetic <sender@example.invalid>\r\n"
        "To: Recipient <recipient@example.invalid>\r\n"
        "Subject: Google fixture\r\n"
        "Date: Tue, 04 Feb 2025 10:11:12 +0100\r\n"
        "Message-ID: <provider-declared@example.invalid>\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{body}\r\n"
    ).encode()


def _configured_source(
    tmp_path: Path,
    *,
    capability: str,
    selection_kind: str,
    selectors: list[str],
) -> tuple[ProvelumeInstance, str, str]:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    connector = instance.create_google_instance(
        name="Synthetic Google identity",
        account_identity="synthetic@example.invalid",
    )
    connector_id = str(connector["connector"]["id"])
    instance.set_google_connector_state(connector_id, enabled=True)
    authorized = instance.authorize_google_capability(
        connector_id,
        capability,
        credential_reference={"kind": "environment", "name": "PROVELUME_TEST_GOOGLE"},
        consent=True,
    )
    assert authorized["scope"] == list(GOOGLE_CAPABILITY_SCOPES[capability])
    instance.set_google_capability_state(connector_id, capability, state="enabled")
    source = instance.create_google_source(
        connector_id,
        name=f"Synthetic {capability}",
        capability=capability,
        selection_kind=selection_kind,
        selectors=selectors,
    )
    source_id = str(source["id"])
    instance.set_google_source_state(source_id, state="enabled")
    return instance, connector_id, source_id


def _use_adapter(instance: ProvelumeInstance, adapter: SyntheticGoogleAdapter) -> None:
    instance.google.adapter = adapter
    instance.scheduler._google_manager_factory = lambda store: GoogleJobManager(
        store, adapter=adapter
    )


def test_gmail_paging_exact_original_replay_and_independent_revoke(tmp_path: Path) -> None:
    instance, connector_id, source_id = _configured_source(
        tmp_path,
        capability="gmail",
        selection_kind="mailbox",
        selectors=["me"],
    )
    first = GoogleItem(
        capability="gmail",
        provider_item_id="provider-message-one",
        provider_revision_id="history-1",
        provider_thread_id="provider-thread",
        provider_labels=("INBOX", "private-label"),
        provider_observed_at="2025-02-04T09:11:12+00:00",
        payload=_message(),
        media_type="message/rfc822",
    )
    duplicate = GoogleItem(
        capability="gmail",
        provider_item_id="provider-message-two",
        provider_revision_id="history-2",
        payload=_message(),
        media_type="message/rfc822",
    )
    adapter = SyntheticGoogleAdapter(
        {
            source_id: (
                GooglePage(capability="gmail", items=(first,)),
                GooglePage(capability="gmail", items=(duplicate,)),
            )
        }
    )
    _use_adapter(instance, adapter)
    queued = instance.queue_google_intake(source_id)
    result = instance.run_google_job(str(queued["job"]["id"]))
    assert result is not None and result["status"] == "succeeded"
    assert result["progress"] == {"processed": 2, "skipped": 0, "errors": 0}
    messages = instance.store.list_canonical("email-messages")
    assert len(messages) == 1
    assert instance.store.original_bytes(str(messages[0]["original_id"])) == _message()
    observations = instance.list_google_gmail_observations()
    assert len(observations) == 2
    encoded = json.dumps(observations)
    assert "provider-message" not in encoded
    assert "provider-thread" not in encoded
    assert "private-label" not in encoded
    assert "provider-declared@example.invalid" not in encoded
    assert instance.get_google_source(source_id)["cursor"]["provider_cursor_present"] is False

    replay = instance.queue_google_intake(source_id)
    replayed = instance.run_google_job(str(replay["job"]["id"]))
    assert replayed is not None and replayed["status"] == "succeeded"
    assert len(instance.store.list_canonical("email-messages")) == 1
    assert len(instance.list_google_gmail_observations()) == 2

    instance.revoke_google_capability(connector_id, "gmail")
    with pytest.raises(GoogleContractError) as caught:
        instance.queue_google_intake(source_id)
    assert (
        caught.value.code == "google_source_disabled"
        or caught.value.code == "google_authorization_required"
    )
    assert (
        instance.get_google_instance(connector_id)["capabilities"]["drive"][
            "authorization_status"
        ]
        == "not_authorized"
    )


def test_completed_scan_discards_page_fingerprints_before_remote_change(tmp_path: Path) -> None:
    instance, _connector_id, source_id = _configured_source(
        tmp_path,
        capability="drive",
        selection_kind="file",
        selectors=["one"],
    )
    first = GoogleItem(
        capability="drive",
        provider_item_id="provider-file",
        provider_revision_id="revision-1",
        payload=b"first revision",
        media_type="application/octet-stream",
    )
    adapter = SyntheticGoogleAdapter(
        {source_id: (GooglePage(capability="drive", items=(first,)),)}
    )
    _use_adapter(instance, adapter)
    queued = instance.queue_google_intake(source_id)
    assert instance.run_google_job(str(queued["job"]["id"]))["status"] == "succeeded"
    cursor = instance.get_google_source(source_id)["cursor"]
    assert cursor["page_ordinal"] == 0
    assert cursor["page_fingerprints"] == []

    changed = GoogleItem(
        capability="drive",
        provider_item_id="provider-file",
        provider_revision_id="revision-2",
        payload=b"second revision",
        media_type="application/octet-stream",
    )
    changed_adapter = SyntheticGoogleAdapter(
        {source_id: (GooglePage(capability="drive", items=(changed,)),)}
    )
    _use_adapter(instance, changed_adapter)
    queued = instance.queue_google_intake(source_id)
    assert instance.run_google_job(str(queued["job"]["id"]))["status"] == "succeeded"
    assert len(instance.list_google_drive_revisions()) == 2


def test_gmail_raw_json_uses_item_bound_not_metadata_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GoogleApiAdapter(credential_resolver=lambda _reference: "synthetic")
    raw_payload = _message("x" * 2048)
    raw_json = json.dumps(
        {"raw": base64.urlsafe_b64encode(raw_payload).decode().rstrip("=")}
    ).encode()
    maxima: list[int] = []

    def fake_request(
        url: str,
        *,
        credential_reference: object,
        limits: GoogleLimits,
        maximum: int,
    ) -> tuple[bytes, str]:
        del credential_reference, limits
        maxima.append(maximum)
        if url.endswith("/messages?maxResults=1"):
            return b'{"messages":[{"id":"one"}]}', "application/json"
        assert len(raw_json) <= maximum
        return raw_json, "application/json"

    monkeypatch.setattr(adapter, "_request", fake_request)
    limits = GoogleLimits(
        max_items_per_page=1,
        max_items_per_run=1,
        max_item_bytes=4096,
        max_total_bytes_per_run=4096,
        max_json_bytes=128,
    )
    page = adapter.fetch_page(
        instance={},
        capability={
            "capability": "gmail",
            "credential_reference": {"kind": "environment", "name": "SYNTHETIC"},
        },
        source={"capability": "gmail", "selection_kind": "mailbox", "selectors": ["me"]},
        cursor=None,
        limits=limits,
    )
    assert page.items[0].payload == raw_payload
    assert maxima == [limits.max_json_bytes, ((limits.max_item_bytes + 2) // 3) * 4 + 128]


def test_drive_adapter_applies_remaining_run_budget_while_buffering_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GoogleApiAdapter(credential_resolver=lambda _reference: "synthetic")
    content_maxima: list[int] = []

    def fake_request(
        url: str,
        *,
        credential_reference: object,
        limits: GoogleLimits,
        maximum: int,
    ) -> tuple[bytes, str]:
        del credential_reference, limits
        if "/drive/v3/files?" in url:
            return (
                b'{"files":[{"id":"one","mimeType":"application/pdf","version":"1"},'
                b'{"id":"two","mimeType":"application/pdf","version":"1"}]}',
                "application/json",
            )
        if "alt=media" in url:
            content_maxima.append(maximum)
            payload = b"123456" if len(content_maxima) == 1 else b"12345"
            if len(payload) > maximum:
                raise GoogleAdapterError(
                    "google_payload_limit_exceeded",
                    "synthetic response exceeds remaining bytes",
                )
            return payload, "application/pdf"
        return (
            b'{"id":"one","mimeType":"application/pdf","version":"1"}',
            "application/json",
        )

    monkeypatch.setattr(adapter, "_request", fake_request)
    limits = GoogleLimits(
        max_items_per_page=2,
        max_items_per_run=2,
        max_item_bytes=8,
        max_total_bytes_per_run=10,
    )
    with pytest.raises(GoogleAdapterError) as caught:
        adapter.fetch_page(
            instance={},
            capability={
                "capability": "drive",
                "credential_reference": {"kind": "environment", "name": "SYNTHETIC"},
            },
            source={"capability": "drive", "selection_kind": "file", "selectors": ["one"]},
            cursor=None,
            limits=limits,
        )
    assert caught.value.code == "google_payload_limit_exceeded"
    assert content_maxima == [8, 4]


def test_malformed_gmail_item_is_recorded_as_bounded_error(tmp_path: Path) -> None:
    instance, _connector_id, source_id = _configured_source(
        tmp_path,
        capability="gmail",
        selection_kind="mailbox",
        selectors=["me"],
    )
    malformed = GoogleItem(
        capability="gmail",
        provider_item_id="bad-message",
        provider_revision_id="bad-revision",
        payload=b"X-Too-Long: " + b"x" * (17 * 1024) + b"\r\n\r\n",
        media_type="message/rfc822",
    )
    adapter = SyntheticGoogleAdapter(
        {source_id: (GooglePage(capability="gmail", items=(malformed,)),)}
    )
    _use_adapter(instance, adapter)
    queued = instance.queue_google_intake(source_id)
    job_id = str(queued["job"]["id"])
    result = instance.run_google_job(job_id)
    assert result["status"] == "succeeded"
    retained = instance.get_google_job(job_id)
    assert retained["google_run"]["status"] == "completed_with_errors"
    assert retained["google_run"]["progress"] == {"processed": 0, "skipped": 0, "errors": 1}
    assert retained["google_run"]["error_codes"] == ["google_payload_invalid"]


def test_drive_binary_revision_and_bounded_google_native_export(tmp_path: Path) -> None:
    instance, _connector_id, source_id = _configured_source(
        tmp_path,
        capability="drive",
        selection_kind="folder",
        selectors=["synthetic-folder"],
    )
    binary = GoogleItem(
        capability="drive",
        provider_item_id="provider-file",
        provider_revision_id="revision-1",
        payload=b"%PDF-binary-original",
        media_type="application/pdf",
    )
    exported = GoogleItem(
        capability="drive",
        provider_item_id="provider-native",
        provider_revision_id="revision-7",
        payload=b"%PDF-exported-native",
        media_type="application/pdf",
        source_format="application/vnd.google-apps.document",
        export_format="application/pdf",
        google_native=True,
    )
    adapter = SyntheticGoogleAdapter(
        {source_id: (GooglePage(capability="drive", items=(binary, exported)),)}
    )
    _use_adapter(instance, adapter)
    queued = instance.queue_google_intake(source_id)
    result = instance.run_google_job(str(queued["job"]["id"]))
    assert result is not None and result["status"] == "succeeded"
    revisions = instance.list_google_drive_revisions()
    assert len(revisions) == 2
    native = next(item for item in revisions if item["google_native"])
    assert native["source_format"] == "application/vnd.google-apps.document"
    assert native["export_format"] == "application/pdf"
    assert native["exact_byte_original"] is True
    assert native["provider_write"] is False
    assert instance.store.original_bytes(native["original_id"]) == b"%PDF-exported-native"
    assert instance.validate_instance(deep=True)["status"] == "valid"


@pytest.mark.parametrize(
    "failure",
    [
        GoogleRateLimitError(),
        GoogleCursorInvalidated(),
        GoogleAuthorizationError(expired=True),
        GoogleContractError("google_remote_mutation", "synthetic remote mutation"),
    ],
)
def test_retry_and_cursor_invalidation_fail_visibly(
    tmp_path: Path, failure: GoogleContractError
) -> None:
    instance, _connector_id, source_id = _configured_source(
        tmp_path,
        capability="drive",
        selection_kind="file",
        selectors=["one"],
    )
    adapter = SyntheticGoogleAdapter(
        {source_id: (GooglePage(capability="drive", items=()),)},
        fail_at={source_id: {0: failure}},
    )
    _use_adapter(instance, adapter)
    queued = instance.queue_google_intake(source_id)
    result = instance.run_google_job(str(queued["job"]["id"]))
    assert result is not None
    if failure.code == "google_rate_limited":
        assert result["status"] == "retry_wait"
    elif failure.code in {"google_cursor_invalidated", "google_authorization_expired"}:
        assert result["status"] == "manual_intervention"
        if failure.code == "google_cursor_invalidated":
            source = instance.get_google_source(source_id)
            assert source["cursor"]["resync_required"] is True
    else:
        assert result["status"] == "failed"
    assert instance.list_google_drive_revisions() == []


def test_disabled_network_never_calls_adapter_or_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    connector = instance.create_google_instance(
        name="Disabled Google", account_identity="disabled@example.invalid"
    )
    connector_id = str(connector["connector"]["id"])
    instance.set_google_connector_state(connector_id, enabled=True)
    instance.authorize_google_capability(
        connector_id,
        "gmail",
        credential_reference={"kind": "environment", "name": "PROVELUME_TEST_GOOGLE"},
        consent=True,
    )
    instance.set_google_capability_state(connector_id, "gmail", state="enabled")
    source = instance.create_google_source(
        connector_id,
        name="Disabled source",
        capability="gmail",
        selection_kind="mailbox",
        selectors=["me"],
    )
    instance.set_google_source_state(str(source["id"]), state="enabled")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("network was attempted while globally disabled")

    monkeypatch.setattr(socket, "socket", forbidden)
    with pytest.raises(GoogleContractError) as caught:
        instance.queue_google_intake(str(source["id"]))
    assert caught.value.code == "google_network_disabled"


def test_api_is_read_only_browser_is_bilingual_and_secrets_never_export(tmp_path: Path) -> None:
    instance, _connector_id, source_id = _configured_source(
        tmp_path,
        capability="drive",
        selection_kind="file",
        selectors=["hostile-<script>-file"],
    )
    secret = "never-store-real-secret-123"
    adapter = SyntheticGoogleAdapter(
        {
            source_id: (
                GooglePage(
                    capability="drive",
                    items=(
                        GoogleItem(
                            capability="drive",
                            provider_item_id="hostile-provider-id",
                            provider_revision_id="revision",
                            payload=b"synthetic export payload",
                            media_type="application/octet-stream",
                        ),
                    ),
                ),
            )
        }
    )
    _use_adapter(instance, adapter)
    queued = instance.queue_google_intake(source_id)
    assert instance.run_google_job(str(queued["job"]["id"]))["status"] == "succeeded"
    client = TestClient(create_app(instance.root))
    assert client.get("/api/v1/google/capability").json()["real_google_qualified"] is False
    assert client.get("/api/v1/google/sources").status_code == 200
    assert client.post("/api/v1/google/sources").status_code == 405
    english = client.get("/google?lang=en")
    italian = client.get("/google?lang=it")
    assert "Google read-only adapters" in english.text
    assert "Adapter Google in sola lettura" in italian.text
    assert "hostile-&lt;script&gt;-file" not in english.text

    archive = tmp_path / "google-portable.zip"
    assert instance.export_portable(archive)["status"] == "completed"
    with zipfile.ZipFile(archive) as bundle:
        payload = b"\n".join(bundle.read(name) for name in bundle.namelist())
    assert secret.encode() not in payload
    assert b"access_token" not in payload
    assert b"refresh_token" not in payload
    backup = instance.backup(destination=tmp_path / "google-backup.zip")
    instance.reset_google_source_cursor(source_id)
    assert instance.restore(backup["archive"])["status"] == "restored"
    instance = ProvelumeInstance(tmp_path / "instance")
    assert instance.list_google_drive_revisions()
    target = ProvelumeInstance.initialise(tmp_path / "target")
    assert target.import_portable(archive)["status"] == "imported"
    restored = ProvelumeInstance(tmp_path / "target")
    assert restored.list_google_drive_revisions()
    assert restored.validate_instance(deep=True)["status"] == "valid"


def test_google_packaging_distinguishes_preview_from_real_qualification() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = json.loads((root / "core" / "provelume" / "google_contract.schema.json").read_text())
    evidence = json.loads(
        (root / "packaging" / "google" / "google-readonly-adapters.json").read_text()
    )
    assert contract["properties"]["real_google_qualified"] == {"const": False}
    assert evidence["release_identity"] == "0.9.0"
    assert evidence["status"] == "local-conformance-preview"
    assert evidence["real_google_qualified"] is False
    assert evidence["public_ci"] == {
        "adapter": "SyntheticGoogleAdapter",
        "network": False,
        "credentials": False,
        "fixtures": "synthetic",
        "claims_real_google_qualification": False,
    }
