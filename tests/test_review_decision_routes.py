from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from provelume.duplicates import DuplicateCaseManager
from provelume.review_i18n import REVIEW_TRANSLATIONS
from provelume.service import ProvelumeInstance
from provelume.web import create_app

ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def browser(tmp_path, monkeypatch):
    shell = tmp_path / "shell"
    shell.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(shell))
    monkeypatch.setenv("XDG_STATE_HOME", str(shell))
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("Synthetic reviewed placement", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Review browser fixture")
    instance.ingest(source, source_name="Synthetic source")
    area = instance.create_hierarchy_node("area", "Area <unsafe>")
    other = instance.create_hierarchy_node("project", "Another Project")
    document = instance.list_documents()[0]
    with TestClient(create_app(instance.root)) as client:
        yield instance, client, document, area, other


def _snapshot(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _token(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.text
    return re.search(r'data-token="([^"]+)"', response.text).group(1)


def _preview(client, path, token, action, parameters):
    return client.post(
        path + "/preview",
        json={"csrf_token": token, "action": action, "parameters": parameters},
        headers=ORIGIN,
    )


def _confirm(client, path, token, preview):
    value = preview.json()
    return client.post(
        path + "/confirm",
        json={
            "csrf_token": token,
            **{
                key: value[key]
                for key in (
                    "plan_revision",
                    "authority_revision",
                    "request_id",
                )
            },
        },
        headers=ORIGIN,
    )


def _grant(client, domain, *, mode="confirm-each", actions=None):
    path = "/review/decisions/capabilities/" + domain
    token = _token(client, path)
    preview = _preview(
        client,
        path,
        token,
        "configure",
        {
            "mode": mode,
            "scope": {
                "subjects": ["*"],
                "actions": actions or ["classify"],
                "sources": [],
            },
        },
    )
    assert preview.status_code == 200, preview.text
    committed = _confirm(client, path, token, preview)
    assert committed.status_code == 200
    refreshed = client.get(path)
    assert refreshed.status_code == 200 and committed.json()["receipt"]["id"] in refreshed.text


def test_permission_placement_preview_confirmation_history_and_one_use(browser):
    instance, client, document, area, _other = browser
    _grant(client, "placement")
    path = "/review/decisions/placement/" + document["id"]
    token = _token(client, path)
    page = client.get(path)
    assert "Area &lt;unsafe&gt;" in page.text and "<unsafe>" not in page.text
    assert 'name="primary_node_id"' in page.text and 'name="secondary_node_ids"' in page.text
    assert "textarea" not in page.text
    assert "sha256-" in page.headers["content-security-policy"]
    before = _snapshot(instance.root)
    preview = _preview(
        client, path, token, "classify", {"primary_node_id": area["id"], "secondary_node_ids": []}
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["mutated"] is False and preview.json()["confirmable"] is True
    assert preview.json()["summary"]["changes"][0]["before"] == "None"
    assert area["id"] in preview.json()["summary"]["changes"][0]["after"]
    assert _snapshot(instance.root) == before
    committed = _confirm(client, path, token, preview)
    assert committed.status_code == 200, committed.text
    assert instance.hierarchy.get_classification(document["id"])["primary_node_id"] == area["id"]
    assert _confirm(client, path, token, preview).status_code == 409
    history = client.get(path)
    assert committed.json()["receipt"]["id"] in history.text
    assert not (instance.root / "state/action-center/state.json").exists()


def test_pure_pages_do_not_create_review_state_or_grant_defaults(browser):
    instance, client, document, _area, _other = browser
    before = _snapshot(instance.root)
    for path in (
        "/review/capabilities",
        "/review/routing",
        "/review/decisions/capabilities/placement",
        "/review/decisions/placement/" + document["id"],
    ):
        assert client.get(path).status_code == 200
    assert _snapshot(instance.root) == before
    assert not (instance.root / "state/review").exists()
    assert client.get("/review/decisions/unknown/" + document["id"]).status_code == 404


def test_disabled_and_proposal_only_permissions_allow_observation_but_deny_confirm(browser):
    instance, client, document, area, _other = browser
    path = "/review/decisions/placement/" + document["id"]
    for mode in ("disabled", "proposal-only"):
        if mode == "proposal-only":
            _grant(client, "placement", mode=mode)
        token = _token(client, path)
        preview = _preview(
            client,
            path,
            token,
            "classify",
            {"primary_node_id": area["id"], "secondary_node_ids": []},
        )
        assert preview.status_code == 200 and preview.json()["confirmable"] is False
        assert _confirm(client, path, token, preview).status_code == 409
        assert instance.hierarchy.get_classification(document["id"]) is None


def test_stale_hierarchy_and_changed_preview_are_denied_without_effect(browser):
    instance, client, document, area, other = browser
    _grant(client, "placement")
    path = "/review/decisions/placement/" + document["id"]
    token = _token(client, path)
    first = _preview(
        client, path, token, "classify", {"primary_node_id": area["id"], "secondary_node_ids": []}
    )
    second = _preview(
        client, path, token, "classify", {"primary_node_id": other["id"], "secondary_node_ids": []}
    )
    assert _confirm(client, path, token, first).status_code == 409
    instance.rename_hierarchy_node(other["id"], "Changed after preview")
    assert _confirm(client, path, token, second).status_code == 409
    assert instance.hierarchy.get_classification(document["id"]) is None


def test_local_origin_csrf_closed_fields_and_scope_binding(browser):
    _instance, client, document, area, _other = browser
    path = "/review/decisions/placement/" + document["id"]
    token = _token(client, path)
    payload = {
        "csrf_token": token,
        "action": "classify",
        "parameters": {
            "primary_node_id": area["id"],
            "secondary_node_ids": [],
        },
    }
    assert client.post(path + "/preview", json=payload).status_code == 403
    assert (
        client.post(
            path + "/preview", json=payload, headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            path + "/preview", json={**payload, "principal": "local_cli"}, headers=ORIGIN
        ).status_code
        == 400
    )
    assert (
        client.post(
            path + "/preview", json={**payload, "csrf_token": "invalid"}, headers=ORIGIN
        ).status_code
        == 409
    )
    other = "/review/decisions/routing/routing_" + "a" * 32
    assert _preview(client, other, token, "save_rule", {}).status_code == 409


def test_rule_controls_and_capability_auto_scope_are_explicit(browser):
    instance, client, document, area, _other = browser
    _grant(client, "routing", actions=["save_rule"])
    rule_id = "routing_" + "d" * 32
    path = "/review/decisions/routing/" + rule_id
    page = client.get(path)
    assert page.status_code == 200
    for name in ("source_id", "path_prefix", "primary_node_id", "automatic_enabled"):
        assert f'name="{name}"' in page.text
    token = _token(client, path)
    preview = _preview(
        client,
        path,
        token,
        "save_rule",
        {
            "source_id": document["source_id"],
            "path_prefix": "",
            "primary_node_id": area["id"],
            "secondary_node_ids": [],
            "automatic_enabled": True,
        },
    )
    assert preview.status_code == 200
    assert _confirm(client, path, token, preview).status_code == 200
    assert instance.review_routing.rules()[0]["id"] == rule_id
    assert instance.hierarchy.get_classification(document["id"]) is None
    capabilities = client.get("/review/decisions/capabilities/routing")
    assert 'value="controlled-automatic"' in capabilities.text
    assert 'name="scope_action"' in capabilities.text and 'name="scope_source"' in capabilities.text
    assert (
        'value="controlled-automatic"'
        not in client.get("/review/decisions/capabilities/placement").text
    )


def test_italian_labels_and_unknown_confidence_remain_honest(browser):
    _instance, client, document, _area, _other = browser
    page = client.get("/review/decisions/placement/" + document["id"] + "?lang=it")
    assert page.status_code == 200 and "Anteprima della modifica" in page.text
    assert "Permessi di revisione" in page.text
    assert set(REVIEW_TRANSLATIONS["en"]) == set(REVIEW_TRANSLATIONS["it"])


def test_annotation_permission_can_be_configured_without_an_existing_annotation(browser):
    instance, client, _document, _area, _other = browser
    path = "/review/decisions/capabilities/annotations"
    before = _snapshot(instance.root)
    token = _token(client, path)
    assert _snapshot(instance.root) == before
    preview = _preview(
        client,
        path,
        token,
        "configure",
        {
            "mode": "confirm-each",
            "scope": {"subjects": ["*"], "actions": ["save", "undo"], "sources": []},
        },
    )
    assert preview.status_code == 200, preview.text
    assert _confirm(client, path, token, preview).status_code == 200
    assert instance.review_authority.read()["grants"]["annotations"]["mode"] == "confirm-each"


def test_domain_routes_preserve_every_legacy_review_route_without_double_registration(browser):
    _instance, client, _document, _area, _other = browser
    get_paths = [
        route.path for route in client.app.routes if "GET" in getattr(route, "methods", set())
    ]
    paths = (
        "/api/v1/duplicates",
        "/api/v1/duplicates/{case_id}",
        "/api/v1/assurance",
        "/api/v1/assurance/reports",
        "/api/v1/assurance/reports/{report_id}",
        "/duplicates",
        "/duplicates/{case_id}",
        "/assurance",
        "/assurance/{report_id}",
        "/review/capabilities",
        "/review/routing",
        "/review/decisions/{domain}/{subject}",
    )
    assert all(get_paths.count(path) == 1 for path in paths)
    for path in ("/duplicates", "/assurance", "/api/v1/duplicates", "/api/v1/assurance"):
        assert client.get(path).status_code == 200


def test_confirmed_duplicate_effect_is_visible_in_action_center_without_accepting_inspection(
    browser,
):
    instance, client, _document, _area, _other = browser
    source = instance.root.parent / "source"
    (source / "copy.txt").write_bytes((source / "note.txt").read_bytes())
    instance.ingest(source, source_name="Synthetic source")
    duplicates = DuplicateCaseManager(instance.store)
    duplicates.scan()
    case = duplicates.list_cases(kind="exact")[0]
    _grant(client, "duplicates", actions=["link_exact"])
    path = "/review/decisions/duplicates/" + case["id"]
    token = _token(client, path)
    proposed = _preview(client, path, token, "link_exact", {})
    assert proposed.status_code == 200, proposed.text
    result = _confirm(client, path, token, proposed)
    assert result.status_code == 200, result.text
    receipt_id = result.json()["receipt"]["id"]
    attention = client.get("/attention?queue=exact_duplicate&lang=en")
    assert receipt_id in attention.text and "Confirmed domain effect" in attention.text
    item = client.get("/api/v1/action-center?queue=exact_duplicate").json()["items"][0]
    assert item["review_state"] == "awaiting_review" and item["history"] == []
    detail = client.get("/attention/items/" + item["id"] + "?lang=en")
    assert receipt_id in detail.text and "Evidence inspection state" in detail.text
    assert "Confirmed domain effect" in detail.text
    api_detail = client.get("/api/v1/action-center/items/" + item["id"]).json()
    assert api_detail["domain_history"]["items"][0]["id"] == receipt_id
    assert api_detail["history"] == [] and api_detail["review_state"] == "awaiting_review"


def test_incomplete_domain_history_never_claims_empty(browser, monkeypatch):
    _instance, client, document, _area, _other = browser
    monkeypatch.setattr(
        client.app.state.provelume.review_decisions,
        "history",
        lambda **kwargs: {
            "items": [],
            "complete": False,
            "count_relation": "unknown",
            "observed_count": 0,
        },
    )
    for path in (
        "/attention?lang=en",
        "/review/decisions/placement/" + document["id"] + "?lang=en",
    ):
        response = client.get(path)
        assert response.status_code == 200
        visible = []
        parser = HTMLParser()
        parser.handle_data = visible.append
        parser.feed(response.text)
        text = " ".join(visible)
        assert "This view is incomplete or unavailable" in text
        assert "No recorded domain decisions for this object." not in text
