from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_annotation_editor import audio_fixture

from provelume.annotation_activity import attach_annotation_routes
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.review_runtime import review_transaction_factory
from provelume.service import ProvelumeInstance
from provelume.web import TEMPLATES, _context
from provelume.web_security import LocalWebSecurityMiddleware


@pytest.fixture
def actual_browser(tmp_path):
    seeded, _, subject, _, _ = audio_fixture(tmp_path)
    instance = ProvelumeInstance(seeded.root)
    decisions = instance.review_decisions
    grant = decisions.preview(
        "capabilities",
        "annotations",
        "configure",
        {
            "mode": "confirm-each",
            "scope": {"subjects": [subject], "actions": ["save", "undo"], "sources": []},
        },
    )
    result = decisions.confirm(
        "capabilities",
        "annotations",
        "configure",
        grant["parameters"],
        expected_plan_revision=grant["plan_revision"],
        expected_authority_revision=grant["authority_revision"],
        request_id="annotation-browser-real-grant",
        principal="local_cli",
    )
    assert result["receipt"]["status"] == "committed"
    app = FastAPI()
    app.add_middleware(LocalWebSecurityMiddleware)
    attach_annotation_routes(app, instance, TEMPLATES, _context)
    return instance, subject, TestClient(app)


def pending_authority_transaction(instance):
    # Real prepared journal simulates interruption before publication, not invented authority.
    transaction = review_transaction_factory(instance.store)("review_" + "0" * 32)
    grant = instance.review_decisions.preview(
        "capabilities",
        "annotations",
        "configure",
        {
            "mode": "proposal-only",
            "scope": {"subjects": ["*"], "actions": ["save", "undo"], "sources": []},
        },
    )
    effect = instance.review_authority.prepare(
        grant,
        request_id="pending-synthetic-grant",
        principal="local_cli",
        recorded_at="2026-09-20T00:00:00Z",
    )
    for write in effect.writes:
        transaction.add(write.relative, write.data, immutable=write.immutable)
    stage, _ = transaction._prepare()
    return stage


@pytest.mark.parametrize("failure", ["corrupt_authority", "pending"])
def test_editor_get_unavailable_without_token_when_authority_is_not_readable(
    actual_browser, failure
):
    instance, subject, client = actual_browser
    if failure == "corrupt_authority":
        (instance.root / "state/review/authority.json").write_bytes(b"{corrupt synthetic authority")
    else:
        pending_authority_transaction(instance)
    response = client.get(f"/review/annotations/{subject}")
    assert response.status_code == 200
    assert 'data-editable="false"' in response.text
    assert 'data-token=""' in response.text
    assert 'role="alert"' in response.text
    assert not (instance.root / "state/review/annotations").exists()


def prepared_confirmation(instance, subject, client):
    url = f"/review/annotations/{subject}"
    page = client.get(url)
    assert page.status_code == 200
    token = re.search(r'data-token="([^"]+)"', page.text).group(1)
    segment = instance.annotations.annotations.read(subject)["segments"][0]["id"]
    result = client.post(
        url + "/preview",
        headers={"Origin": "http://testserver"},
        json={
            "csrf_token": token,
            "action": "save",
            "parameters": {
                "operations": [{"kind": "edit", "segment": segment, "text": "new synthetic text"}]
            },
        },
    )
    assert result.status_code == 200
    return url, {
        "csrf_token": token,
        **{
            key: result.json()[key] for key in ("plan_revision", "authority_revision", "request_id")
        },
    }


@pytest.mark.parametrize("failure", ["busy", "atomic_recovery"])
def test_confirm_busy_or_failed_recovery_is_409_and_never_reuses_nonce(actual_browser, failure):
    instance, subject, client = actual_browser
    url, fields = prepared_confirmation(instance, subject, client)
    if failure == "busy":
        with InstanceLifecycleManager(instance.store)._hold(purpose="synthetic-concurrent-writer"):
            response = client.post(
                url + "/confirm", headers={"Origin": "http://testserver"}, json=fields
            )
    else:
        stage = pending_authority_transaction(instance)
        # Keep the original prepared manifest; corrupt only the sacrificial candidate bytes.
        (stage / "candidates/0000.bin").write_bytes(b"corrupt synthetic transaction candidate")
        response = client.post(
            url + "/confirm", headers={"Origin": "http://testserver"}, json=fields
        )
    assert response.status_code == 409
    assert "outcome is unconfirmed" in response.json()["detail"]
    assert not (instance.root / "state/review/annotations").exists()
    # Expired nonce is rejected before any recovery/transaction attempt, with no automatic retry.
    repeated = client.post(url + "/confirm", headers={"Origin": "http://testserver"}, json=fields)
    assert repeated.status_code == 409
    assert not (instance.root / "state/review/annotations").exists()
