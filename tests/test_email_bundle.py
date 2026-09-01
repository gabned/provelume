from __future__ import annotations

import hashlib
import json
from pathlib import Path

from provelume.email_bundle import build_email_bundle, observed_threads
from provelume.email_contract import EmailLimits, settings_fingerprint
from provelume.email_mime import parse_email

ROOT = Path(__file__).resolve().parents[1]


def _id(prefix: str, digit: str, length: int) -> str:
    return prefix + digit * length


def _manifest(
    message_id: str,
    source_id: str,
    declared_id: str,
    *,
    references: list[str] | None = None,
    in_reply_to: list[str] | None = None,
) -> dict[str, object]:
    return {
        "message": {"id": message_id, "source_id": source_id},
        "declared_identity": {
            "message_ids": [declared_id],
            "references": references or [],
            "in_reply_to": in_reply_to or [],
            "authoritative": False,
        },
    }


def test_bundle_is_complete_schema_versioned_atomic_and_inert() -> None:
    raw = (
        b"Date: Tue, 04 Feb 2025 10:11:12 +0100\r\n"
        b"Message-ID: <one@example.invalid>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"derived body"
    )
    parsed = parse_email(raw)
    limits = EmailLimits()
    plan = build_email_bundle(
        parsed=parsed,
        job_id=_id("job_", "1", 32),
        source_id=_id("src_", "2", 32),
        message_id=_id("emsg_", "3", 64),
        observation_id=_id("eobs_", "4", 64),
        acquisition_id=_id("acq_", "5", 32),
        document_id=_id("doc_", "6", 32),
        version_id=_id("ver_", "7", 32),
        original_id=_id("sha256_", "8", 64),
        observed_at="2025-02-04T09:11:13+00:00",
        acquired_at="2025-02-04T09:11:14+00:00",
        container_identity_sha256="9" * 64,
        snapshot_sha256="a" * 64,
        locator_sha256="b" * 64,
        filesystem_identity_sha256="c" * 64,
        filesystem_mtime_ns=1,
        adapter={
            "adapter_id": "provelume.local-email",
            "adapter_version": "1.0.0",
            "network_access": "none",
        },
        settings_sha256=settings_fingerprint(limits),
        attachments=[],
    )
    schema = json.loads(
        (ROOT / "core" / "provelume" / "email_bundle.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(schema["required"]) == set(plan.manifest)
    assert schema["properties"]["schema_version"]["const"] == 1
    assert schema["properties"]["kind"]["const"] == "email_message_bundle"
    assert plan.manifest["status"] == "complete"
    assert plan.manifest["complete"] is True
    assert plan.manifest["job"]["state"] == "message-complete"
    assert plan.manifest["original_authoritative"] is True
    assert plan.manifest["derived"] is plan.manifest["removable"] is True
    assert plan.manifest["rebuildable_from_original"] is True
    assert plan.manifest["active_content_executed"] is False
    assert plan.manifest["remote_fetch"] is plan.manifest["network_used"] is False
    assert plan.manifest["timestamps"]["declared"]["parsed"] == [
        "2025-02-04T10:11:12+01:00"
    ]
    assert plan.body_bytes == b"derived body"
    assert plan.text_artifact is not None
    assert hashlib.sha256(plan.manifest_bytes).hexdigest() == plan.bundle_artifact.checksum

    definitions = schema["$defs"]
    for value in (schema,):
        encoded = json.dumps(value)
        for reference in (
            "#/$defs/message",
            "#/$defs/timestamps",
            "#/$defs/body",
            "#/$defs/attachment",
            "#/$defs/thread",
            "#/$defs/identityWarning",
        ):
            if reference in encoded:
                assert reference.removeprefix("#/$defs/") in definitions


def test_observed_threads_are_source_scoped_collision_aware_and_nonsemantic() -> None:
    source_a = _id("src_", "a", 32)
    source_b = _id("src_", "b", 32)
    one = _id("emsg_", "1", 64)
    two = _id("emsg_", "2", 64)
    three = _id("emsg_", "3", 64)
    cross = _id("emsg_", "4", 64)
    duplicate = _id("emsg_", "5", 64)
    manifests = [
        _manifest(one, source_a, "<one@example.invalid>", references=["<two@example.invalid>"]),
        _manifest(two, source_a, "<two@example.invalid>", references=["<one@example.invalid>"]),
        _manifest(three, source_a, "<duplicate@example.invalid>"),
        _manifest(duplicate, source_a, "<duplicate@example.invalid>"),
        _manifest(
            cross,
            source_b,
            "<cross@example.invalid>",
            references=["<two@example.invalid>"],
        ),
    ]
    threads, observations = observed_threads(manifests)
    assert all(item["authoritative"] is False for item in threads)
    assert all(item["source_scoped"] is True for item in threads)
    assert all(item["cross_source_merge"] is False for item in threads)
    assert "declared_message_id_collision" in observations[three]["warning_codes"]
    assert "declared_message_id_collision" in observations[duplicate]["warning_codes"]
    assert "thread_reference_cycle" in observations[one]["warning_codes"]
    assert "thread_reference_cycle" in observations[two]["warning_codes"]
    assert observations[one]["parent_message_id"] is None
    assert observations[two]["parent_message_id"] is None
    assert observations[cross]["parent_message_id"] is None
    assert "thread_reference_cross_source" in observations[cross]["warning_codes"]
