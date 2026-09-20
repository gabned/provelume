from __future__ import annotations

import json

import pytest

from provelume import review_documents
from provelume.review_documents import DuplicateDecisionProvider
from provelume.review_effects import ReviewUnavailable
from provelume.storage import InstanceStore


def replace_after_first_read(monkeypatch, store, relative, original, replacement):
    path = store.paths.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(original)
    real_read_bytes = review_documents.read_bytes

    def read_and_replace(current_store, current_relative, **kwargs):
        raw = real_read_bytes(current_store, current_relative, **kwargs)
        if current_relative == relative:
            assert raw == original
            path.write_bytes(replacement)
        return raw

    monkeypatch.setattr(review_documents, "read_bytes", read_and_replace)


def test_target_versions_does_not_validate_replacement_after_bounded_observation(
    tmp_path, monkeypatch,
):
    store = InstanceStore.initialise(tmp_path / "instance")
    identifier, document_id = "ver_" + "a" * 32, "doc_" + "b" * 32
    replacement = {"id": identifier, "document_id": document_id, "sequence": 1}
    observed = dict(replacement, sequence="invalid")
    replace_after_first_read(
        monkeypatch, store, "knowledge/versions/" + identifier + ".json",
        json.dumps(observed).encode(), json.dumps(replacement).encode(),
    )
    with pytest.raises(ReviewUnavailable, match="sequence"):
        review_documents._target_versions(store, document_id)


def relation_provider(tmp_path, monkeypatch):
    store = InstanceStore.initialise(tmp_path / "instance")
    provider = DuplicateDecisionProvider(store)
    subject = "dup_" + "c" * 32
    monkeypatch.setattr(provider, "_subject", lambda selected: (
        {"queue": "exact_duplicate", "producer_id": selected},
        ["doc_" + "d" * 32, "doc_" + "e" * 32],
        ["ver_" + "f" * 32, "ver_" + "a" * 32],
    ))
    return store, provider, subject


def test_prior_decision_subject_comes_from_the_bytes_bound_to_its_digest(tmp_path, monkeypatch):
    store, provider, subject = relation_provider(tmp_path, monkeypatch)
    relative = "state/review/duplicates/review_" + "b" * 32 + ".json"
    observed = {"schema_version": 1, "subject": "dup_" + "d" * 32}
    replacement = dict(observed, subject=subject)
    replace_after_first_read(
        monkeypatch, store, relative,
        json.dumps(observed).encode(), json.dumps(replacement).encode(),
    )
    result = provider.preview(subject, "link_exact", {})
    assert result["evidence"]["prior_decisions"] == {}


def test_prior_decision_schema_is_not_validated_from_a_second_observation(tmp_path, monkeypatch):
    store, provider, subject = relation_provider(tmp_path, monkeypatch)
    relative = "state/review/duplicates/review_" + "b" * 32 + ".json"
    observed = {"schema_version": 2, "subject": subject}
    replacement = dict(observed, schema_version=1)
    replace_after_first_read(
        monkeypatch, store, relative,
        json.dumps(observed).encode(), json.dumps(replacement).encode(),
    )
    with pytest.raises(ReviewUnavailable, match="history"):
        provider.preview(subject, "link_exact", {})
