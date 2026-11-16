"""Integrated passive Gmail reading and offline portable recovery of exact Originals."""

import hashlib
import json

import pytest
from test_google_jobs import _configured_source, _message, _use_adapter

from provelume.email_contract import EmailContractError
from provelume.google_adapters import SyntheticGoogleAdapter
from provelume.google_contract import GoogleItem, GooglePage
from provelume.index import verified_email_text_artifact
from provelume.service import ProvelumeInstance


def acquire(tmp_path):
    instance, _identity, source = _configured_source(
        tmp_path, capability="gmail", selection_kind="mailbox", selectors=["me"]
    )
    item = GoogleItem(capability="gmail", provider_item_id="synthetic-message",
                      provider_revision_id="synthetic-revision", payload=_message(),
                      media_type="message/rfc822")
    adapter = SyntheticGoogleAdapter({source: (GooglePage(capability="gmail", items=(item,)),)})
    _use_adapter(instance, adapter)
    job = instance.queue_google_intake(source)["job"]
    assert instance.run_google_job(job["id"])["status"] == "succeeded"
    return instance, instance.store.list_canonical("email-messages")[0]


def test_gmail_passive_body_is_bound_and_readable(tmp_path):
    instance, message = acquire(tmp_path)
    assert instance.validate_instance()["status"] == "valid"
    selected = verified_email_text_artifact(instance.store, message["version_id"])
    assert selected is not None and "synthetic Gmail body" in selected[1]
    assert instance.email._bundle_for_message(message["id"]) is not None


def test_gmail_unknown_rebuild_settings_are_refused_without_canonical_rewrite(tmp_path):
    instance, message = acquire(tmp_path)
    with pytest.raises(EmailContractError, match="settings are unavailable"):
        instance.email._limits_for_rebuild({**message, "settings_sha256": "f" * 64}, None)


@pytest.mark.parametrize("field,value", [("network_used", False), ("remote_fetch", False),
                                         ("provider_observation", None)])
def test_gmail_cannot_be_relabelled_as_local_or_lose_provider_binding(tmp_path, field, value):
    instance, message = acquire(tmp_path)
    artifact = next(row for row in instance.store.list_derived_artifacts()
                    if row["kind"] == "email_message_bundle")
    path = instance.root / artifact["storage_ref"]
    manifest = json.loads(path.read_text())
    manifest[field] = value
    payload = json.dumps(manifest).encode()
    path.write_bytes(payload)
    artifact["checksum"] = hashlib.sha256(payload).hexdigest()
    (instance.store.paths.derived_artifacts / (artifact["id"] + ".json")).write_text(
        json.dumps(artifact))
    assert verified_email_text_artifact(instance.store, message["version_id"]) is None
    assert instance.email._bundle_for_message(message["id"]) is None


def test_gmail_portable_rebuild_after_removed_derived_preserves_canonical_bytes(tmp_path):
    instance, message = acquire(tmp_path)
    original = instance.store.original_bytes(message["original_id"])
    before = {p.relative_to(instance.root).as_posix():p.read_bytes()
              for p in (instance.root / "knowledge").rglob("*") if p.is_file()}
    instance.email.remove_derived(message["id"])
    archive = tmp_path / "Synthetic Portable.zip"
    instance.export_portable(archive, derived_state="rebuild")
    restored = ProvelumeInstance.initialise(tmp_path / "Restored")
    restored.import_portable(archive)
    assert restored.validate_instance()["status"] == "valid"
    assert restored.store.original_bytes(message["original_id"]) == original
    assert before == {p.relative_to(restored.root).as_posix():p.read_bytes()
                      for p in (restored.root / "knowledge").rglob("*") if p.is_file()}
    selected = verified_email_text_artifact(restored.store, message["version_id"])
    assert selected is not None and "synthetic Gmail body" in selected[1]
