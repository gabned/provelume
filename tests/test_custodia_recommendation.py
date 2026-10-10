"""A published recommendation cannot grant execution or qualify changed bytes."""

from __future__ import annotations

import json

import pytest

from provelume import ai_runtime_contract as contract
from provelume.ai_models import ModelError, ModelRegistry, parse_manifest


def test_recommendation_is_bounded_and_keeps_local_installation_unverified():
    inventory = ModelRegistry.packaged().inventory()
    assert inventory["recommended"] == contract.MODEL_ID
    scope = inventory["recommended_scope"]
    assert scope["tasks"] == ["summary", "key-points"]
    assert scope["languages"] == ["en", "it"]
    assert scope["hardware_scope"] == "observed-hosted-profiles"
    assert scope["inference_authorized"] is False
    assert scope["configuration_sha256"] == (
        "51c7539e89a4a29c6bc3ad04fb7b1e2b1cf8afdf33ed2f23261a47c6ccc56640"
    )
    for row in inventory["entries"]:
        assert row["offline_qualified"] is False
        assert row["inference_authorized"] is False
        assert row["installation"] == "not_observed"


@pytest.mark.parametrize("coordinate", ["model", "runtime", "configuration"])
def test_changed_native_identity_cannot_inherit_recommendation(monkeypatch, coordinate):
    registry = ModelRegistry.packaged()
    if coordinate == "model":
        monkeypatch.setattr(contract, "MODEL_SHA256", "a" * 64)
    elif coordinate == "runtime":
        monkeypatch.setattr(contract, "LOCK_SHA256", "b" * 64)
    else:
        monkeypatch.setitem(contract.CONFIGURATION, "output_tokens", 129)
    assert contract.qualified_local_profile() is None
    assert registry.inventory()["recommended"] is None
    assert registry.inventory()["recommended_scope"] is None
    with pytest.raises(ModelError):
        parse_manifest(registry.raw)


@pytest.mark.parametrize("target", ["fixture.model-v1", *contract.RETIRED_MODEL_IDS])
def test_synthetic_and_retired_models_cannot_claim_current_qualification(target):
    payload = json.loads(ModelRegistry.packaged().raw)
    row = next(row for row in payload["entries"] if row["id"] == target)
    row["qualification"] = "QUALIFIED_EN_IT_EXTRACTIVE"
    with pytest.raises(ModelError):
        parse_manifest(json.dumps(payload).encode())


def test_returned_scope_cannot_mutate_the_repository_recommendation():
    scope = contract.qualified_local_profile()
    scope["languages"].append("unqualified")
    scope["tasks"].append("autonomous-filing")
    scope["inference_authorized"] = True
    fresh = contract.qualified_local_profile()
    assert fresh["languages"] == ["en", "it"]
    assert fresh["tasks"] == ["summary", "key-points"]
    assert fresh["inference_authorized"] is False
