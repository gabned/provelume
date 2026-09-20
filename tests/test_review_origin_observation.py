from __future__ import annotations

import json

import pytest

from provelume import review_integrity
from provelume.review_decisions import receipt_identifier
from provelume.review_effects import ReviewUnavailable, sha256
from provelume.storage import InstanceStore


def origin_fixture(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    source_id, previous_id, selected_id = ("ver_" + letter * 32 for letter in "abc")
    source_doc, target_doc = "doc_" + "d" * 32, "doc_" + "e" * 32
    original_id = "orig_" + "f" * 32
    stamp = "2026-09-20T00:00:00+00:00"
    shared = {
        "original_id": original_id, "content_hash": "1" * 64, "size_bytes": 4,
        "media_type": "text/plain", "acquired_at": stamp,
    }
    records = {
        "documents": {source_doc: {}, target_doc: {}},
        "versions": {
            source_id: dict(shared, id=source_id, document_id=source_doc, sequence=1),
            previous_id: dict(shared, id=previous_id, document_id=target_doc, sequence=1),
            selected_id: dict(shared, id=selected_id, document_id=target_doc, sequence=2),
        },
        "originals": {original_id: {"id": original_id, "sha256": "1" * 64, "size_bytes": 4}},
    }
    instance_id = store.read_config()["instance"]["id"]
    request_id = "synthetic-origin-observation"
    identifier = receipt_identifier(instance_id, request_id)
    history_ref = "state/review/versions/" + identifier + ".json"
    history = {
        "action": "new_version", "selected_version_id": selected_id,
        "previous_current_version_id": previous_id, "principal": "local_browser",
        "recorded_at": stamp,
    }
    origin = {
        "schema_version": 1, "id": selected_id, "source_version_id": source_id,
        "source_document_id": source_doc, "target_document_id": target_doc,
        "previous_current_version_id": previous_id, "original_id": original_id,
        "content_hash": "1" * 64, "history_ref": history_ref, "history_sha256": "",
        "principal": "local_browser", "recorded_at": stamp,
    }
    receipt = {
        "schema_version": 1, "id": identifier, "instance_id": instance_id,
        "request_id": request_id, "request_digest": "2" * 64, "domain": "versions",
        "subject": target_doc, "action": "new_version", "principal": "local_browser",
        "recorded_at": stamp, "plan_revision": "3" * 64, "authority_revision": "4" * 64,
        "history_ref": history_ref, "history_sha256": "", "effect": "Synthetic new version",
        "reversibility": "Retain history", "result": {"version_id": selected_id},
        "status": "committed", "canonical_mutation": True,
    }
    return store, origin, records, history, receipt


def retain_observation(store, origin, history_bytes, receipt):
    path = store.paths.root / origin["history_ref"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(history_bytes)
    origin["history_sha256"] = receipt["history_sha256"] = sha256(history_bytes)
    store._atomic_json(
        store.paths.root / "state/review/receipts" / (receipt["id"] + ".json"), receipt,
    )
    return path


@pytest.mark.parametrize("invalid_observation", ["wrong_action", "invalid_json", "duplicate_key"])
def test_origin_rejects_invalid_hashed_history_even_if_file_is_replaced(
    tmp_path, monkeypatch, invalid_observation,
):
    store, origin, records, history, receipt = origin_fixture(tmp_path)
    replacement = json.dumps(history).encode()
    if invalid_observation == "wrong_action":
        observed = json.dumps(dict(history, action="select_current")).encode()
    elif invalid_observation == "invalid_json":
        observed = b"not a JSON object"
    else:
        observed = b'{"action":"new_version",' + replacement[1:]
    path = retain_observation(store, origin, observed, receipt)
    real_read_bytes = review_integrity.read_bytes
    observations = []

    def replace_after_read(current_store, relative, **kwargs):
        raw = real_read_bytes(current_store, relative, **kwargs)
        if relative == origin["history_ref"]:
            observations.append(raw)
            path.write_bytes(replacement)
        return raw

    monkeypatch.setattr(review_integrity, "read_bytes", replace_after_read)
    with pytest.raises(ReviewUnavailable):
        review_integrity.validate_review_origin(store, origin, records)
    assert observations == [observed]
    assert path.read_bytes() == replacement


def test_origin_accepts_history_and_receipt_from_one_consistent_observation(tmp_path):
    store, origin, records, history, receipt = origin_fixture(tmp_path)
    raw = json.dumps(history).encode()
    path = retain_observation(store, origin, raw, receipt)
    review_integrity.validate_review_origin(store, origin, records)
    assert path.read_bytes() == raw
