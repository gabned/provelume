from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import struct
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from provelume.domain import DerivedArtifact
from provelume.google_adapters import SyntheticGoogleAdapter
from provelume.google_contract import GOOGLE_CAPABILITY_SCOPES, GoogleItem, GooglePage
from provelume.google_jobs import GoogleJobManager
from provelume.qualification_contract import QUALIFICATION_SOURCE_PROFILES
from provelume.service import ProvelumeInstance
from provelume.storage import utc_now

pytestmark = pytest.mark.skipif(
    os.environ.get("PROVELUME_QUALIFICATION_CONFORMANCE_SMOKE") != "1",
    reason="cross-source qualification conformance smoke is opt-in",
)

EMAIL = (
    b"From: Synthetic Participant <same@example.invalid>\r\n"
    b"To: Another Participant <other@example.invalid>\r\n"
    b"Subject: Public synthetic fixture\r\n"
    b"Date: Tue, 04 Feb 2025 10:11:12 +0100\r\n"
    b"Message-ID: <qualification-smoke@example.invalid>\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"synthetic cross-source email body\r\n"
)
SRT = b"1\n00:00:00,000 --> 00:00:01,000\nSynthetic speaker observation\n"
VTT = b"WEBVTT\n\n00:00.000 --> 00:01.000\n<v Synthetic>Inert https://invalid.test\n"
SHARED = b"public synthetic exact bytes\n"


def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("qualification smoke attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "gethostbyname", forbidden)


def _google_source(
    instance: ProvelumeInstance,
    connector_id: str,
    capability: str,
    selection_kind: str,
) -> str:
    instance.authorize_google_capability(
        connector_id,
        capability,
        credential_reference={"kind": "environment", "name": "UNRESOLVED_SMOKE_SECRET"},
        consent=True,
    )
    instance.set_google_capability_state(connector_id, capability, state="enabled")
    source = instance.create_google_source(
        connector_id,
        name=f"Synthetic {capability}",
        capability=capability,
        selection_kind=selection_kind,
        selectors=["me" if capability == "gmail" else "synthetic-selection"],
    )
    source_id = str(source["id"])
    instance.set_google_source_state(source_id, state="enabled")
    assert instance.get_google_instance(connector_id)["capabilities"][capability]["scope"] == list(
        GOOGLE_CAPABILITY_SCOPES[capability]
    )
    return source_id


def _synthetic_ocr_bundle(instance: ProvelumeInstance, version_id: str) -> None:
    key = f"{version_id}:qualification-smoke-ocr-bundle"
    artifact_id = f"derived_{uuid5(NAMESPACE_URL, key).hex}"
    relative, checksum = instance.store.write_derived_text(
        artifact_id,
        json.dumps(
            {
                "schema_version": 1,
                "fixture": "public-synthetic-ocr-document-bundle",
                "authoritative": False,
                "network_used": False,
            },
            sort_keys=True,
        ),
    )
    instance.store.write_derived_artifact(
        DerivedArtifact(
            id=artifact_id,
            version_id=version_id,
            kind="ocr_document_bundle",
            generator="provelume.synthetic-qualification-smoke",
            generator_version="1.0.0",
            storage_ref=relative,
            checksum=checksum,
            created_at=utc_now(),
        )
    )


def test_permanent_cross_source_qualification_smoke_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert platform.python_implementation() == "CPython"
    assert platform.python_version_tuple()[:2] == ("3", "12")
    assert struct.calcsize("P") * 8 == 64
    _deny_network(monkeypatch)

    filesystem = tmp_path / "filesystem"
    filesystem.mkdir()
    (filesystem / "shared.txt").write_bytes(SHARED)
    email_path = tmp_path / "synthetic.eml"
    email_path.write_bytes(EMAIL)
    srt_path = tmp_path / "synthetic.srt"
    srt_path.write_bytes(SRT)
    vtt_path = tmp_path / "synthetic.vtt"
    vtt_path.write_bytes(VTT)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")

    filesystem_acquisition = instance.ingest(filesystem)[0]
    filesystem_source = str(filesystem_acquisition["source_id"])
    _synthetic_ocr_bundle(instance, str(filesystem_acquisition["version_id"]))

    email = instance.create_email_source(
        name="Synthetic local email", path=email_path, profile="eml-file-v1"
    )
    email_source = str(email["id"])
    instance.set_email_source_state(email_source, "enabled")
    email_job = instance.queue_email_intake(email_source)["job"]
    assert instance.run_email_job(str(email_job["id"]))["status"] == "succeeded"

    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    connector = instance.create_google_instance(
        name="Synthetic Google identity", account_identity="synthetic@example.invalid"
    )
    connector_id = str(connector["connector"]["id"])
    instance.set_google_connector_state(connector_id, enabled=True)
    gmail_source = _google_source(instance, connector_id, "gmail", "mailbox")
    drive_source = _google_source(instance, connector_id, "drive", "file")
    adapter = SyntheticGoogleAdapter(
        {
            gmail_source: (
                GooglePage(
                    capability="gmail",
                    items=(
                        GoogleItem(
                            capability="gmail",
                            provider_item_id="public-message",
                            provider_revision_id="public-revision",
                            payload=EMAIL,
                            media_type="message/rfc822",
                        ),
                    ),
                ),
            ),
            drive_source: (
                GooglePage(
                    capability="drive",
                    items=(
                        GoogleItem(
                            capability="drive",
                            provider_item_id="public-file",
                            provider_revision_id="public-revision",
                            payload=SHARED,
                            media_type="text/plain",
                        ),
                    ),
                ),
            ),
        }
    )
    instance.google.adapter = adapter
    instance.scheduler._google_manager_factory = lambda store: GoogleJobManager(
        store, adapter=adapter
    )
    for source_id in (gmail_source, drive_source):
        queued = instance.queue_google_intake(source_id)["job"]
        assert instance.run_google_job(str(queued["id"]))["status"] == "succeeded"

    transcript_sources: list[str] = []
    for path, profile in ((srt_path, "srt-v1"), (vtt_path, "webvtt-v1")):
        source = instance.create_transcript_source(
            name=f"Synthetic {profile}",
            path=path,
            profile=profile,
            selection_kind="file",
        )
        source_id = str(source["id"])
        transcript_sources.append(source_id)
        instance.set_transcript_source_state(source_id, "enabled")
        queued = instance.queue_transcript_intake(source_id)["job"]
        assert instance.run_transcript_job(str(queued["id"]))["status"] == "succeeded"

    config = instance.store.read_config()
    config["network"]["external_access"] = False
    instance.store.write_config(config)
    source_ids = sorted(
        [
            filesystem_source,
            email_source,
            gmail_source,
            drive_source,
            *transcript_sources,
        ]
    )
    queued = instance.queue_qualification(source_ids)
    result = instance.run_qualification(str(queued["job"]["id"]))
    assert result["status"] == "succeeded"
    assert result["source_ids"] == source_ids
    findings = instance.list_qualification_findings(limit=500)
    assert any(item["finding_type"] == "possible-exact-byte-duplicate" for item in findings)
    assert any(
        item["finding_type"] == "possible-participant-homonym" for item in findings
    )
    assert any(item["finding_type"] == "qualification-required" for item in findings)
    profiles = {
        profile
        for source in instance.qualification.get_job(result["id"], public=False)["snapshot"][
            "sources"
        ]
        for profile in source["profiles"]
    }
    assert profiles == set(QUALIFICATION_SOURCE_PROFILES)
    exact = next(
        item for item in findings if item["finding_type"] == "possible-exact-byte-duplicate"
    )
    original_hashes = {
        item["id"]: hashlib.sha256(instance.store.original_bytes(item["id"])).hexdigest()
        for item in instance.store.list_canonical("originals")
    }
    accepted = instance.decide_qualification_finding(
        exact["id"],
        action="accept",
        actor_id="smoke.reviewer",
        reason="Synthetic exact-byte observation only.",
        expected_revision=0,
    )
    reverted = instance.decide_qualification_finding(
        exact["id"],
        action="revert",
        actor_id="smoke.reviewer",
        reason="Revert without changing Source records.",
        expected_revision=1,
        payload={"target_decision_id": accepted["id"]},
    )
    assert reverted["resulting_state"] == "reverted"
    assert instance.queue_qualification(source_ids)["replayed"] is True
    assert {
        item["id"]: hashlib.sha256(instance.store.original_bytes(item["id"])).hexdigest()
        for item in instance.store.list_canonical("originals")
    } == original_hashes
    assert adapter.calls
    assert all(
        item["authenticated_real_qualification"] != "qualified"
        for item in instance.qualification_matrix()["profiles"]
        if item["id"] in {"gmail-synthetic-v1", "drive-synthetic-v1"}
    )
