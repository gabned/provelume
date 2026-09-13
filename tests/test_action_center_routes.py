from __future__ import annotations

import copy
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from provelume.service import ProvelumeInstance
from provelume.shell_settings import LauncherSettings, ShellSettingsManager
from provelume.web import create_app


class Form(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.hidden = {}
        self.feed(markup)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "input" and attrs.get("type") == "hidden":
            self.hidden[attrs["name"]] = attrs.get("value", "")


def protected_bytes(instance):
    return {
        p.relative_to(instance.root).as_posix(): p.read_bytes()
        for name in ("knowledge", "originals")
        for p in (instance.root / name).rglob("*")
        if p.is_file()
    }


@pytest.fixture
def browser(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "private-title-orchid.txt").write_text(
        "Synthetic Orchid evidence.\n", encoding="utf-8"
    )
    (source / "failed.txt").write_bytes(b"\xff\xfe")
    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Synthetic action review")
    instance.ingest(source, source_name="Synthetic Source")
    manager = ShellSettingsManager(
        tmp_path / "launcher.json",
        LauncherSettings(instance_path=str(instance.root), language="en"),
    )
    manager.save(manager.defaults)
    manager.set_interface_mode("preview", expected_revision=manager.load().settings.revision)
    app = create_app(instance.root, shell_settings_file=manager.path)
    return TestClient(app), instance, manager, app


def extraction(client):
    result = client.get("/api/v1/action-center?queue=extraction_error")
    assert result.status_code == 200
    assert result.json()["total"] == 1
    return result.json()["items"][0]


def decision_form(client, item):
    response = client.get(f"/attention/items/{item['id']}?lang=en")
    assert response.status_code == 200
    return {**Form(response.text).hidden, "action": "acknowledge_evidence", "confirmed": "on"}


def test_real_queue_api_overview_and_both_renderers_preserve_evidence(browser):
    client, instance, manager, _app = browser
    before = protected_bytes(instance)
    expected = client.get("/api/v1/action-center").json()
    assert expected["queues"]["extraction_error"]["count"] == 1
    for mode in ("current", "preview"):
        manager.set_interface_mode(mode, expected_revision=manager.load().settings.revision)
        for language in ("en", "it"):
            for route in (
                "/",
                "/attention",
                "/attention/authority",
                "/attention/notifications",
                "/settings/notifications",
            ):
                response = client.get(f"{route}?lang={language}")
                assert response.status_code == 200, (route, response.text[:200])
                assert "action.reason." not in response.text
                assert "action.notification_state." not in response.text
            item = extraction(client)
            detail = client.get(f"/attention/items/{item['id']}?lang={language}")
            assert detail.status_code == 200
            assert "action.impact." not in detail.text
            assert item["revision"] in detail.text
        assert client.get("/api/v1/action-center").json() == expected
    assert protected_bytes(instance) == before


def test_review_confirmation_receipt_replay_and_original_preservation(browser):
    client, instance, _manager, _app = browser
    item = extraction(client)
    before = protected_bytes(instance)
    values = decision_form(client, item)
    target = f"/attention/items/{item['id']}/decision"
    saved = client.post(target, data=values, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    receipt_page = client.get(saved.headers["location"])
    assert receipt_page.status_code == 200
    assert "decision receipt was saved" in receipt_page.text
    assert (
        client.get(f"/api/v1/action-center/items/{item['id']}").json()["review_state"] == "accepted"
    )
    assert client.post(target, data=values).status_code == 409
    assert client.get("/api/v1/action-center?queue=extraction_error").json()["total"] == 0
    assert protected_bytes(instance) == before


def test_stale_notification_links_and_foreign_instance_cannot_decide(browser):
    client, instance, _manager, _app = browser
    item = extraction(client)
    before = protected_bytes(instance)
    stale = client.get(f"/attention/items/{item['id']}?revision={'0' * 64}")
    assert stale.status_code == 200 and "earlier revision" in stale.text
    assert 'name="confirmed"' not in stale.text
    assert (
        client.get(f"/attention/items/{item['id']}?instance_id=inst_{'0' * 32}").status_code == 409
    )
    fields = decision_form(client, item)
    fields["instance_id"] = "inst_" + "0" * 32
    assert client.post(f"/attention/items/{item['id']}/decision", data=fields).status_code == 409
    assert extraction(client)["review_state"] == "awaiting_review"
    assert protected_bytes(instance) == before


def test_decision_form_csrf_duplicate_fields_and_size_fail_closed(browser):
    client, instance, _manager, _app = browser
    item = extraction(client)
    before = protected_bytes(instance)
    fields = decision_form(client, item)
    target = f"/attention/items/{item['id']}/decision"
    assert client.post(target, data={**fields, "csrf_token": "wrong"}).status_code == 403
    duplicate = urlencode(fields) + "&action=reject_proposal"
    assert (
        client.post(
            target, content=duplicate, headers={"content-type": "application/x-www-form-urlencoded"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            target,
            content=b"x=" + b"a" * 8192,
            headers={"content-type": "application/x-www-form-urlencoded"},
        ).status_code
        == 413
    )
    assert client.post(target, json=fields).status_code == 415
    assert protected_bytes(instance) == before


def test_notification_dismissal_is_not_review_and_preferences_keep_interface(browser):
    client, instance, manager, _app = browser
    before = protected_bytes(instance)
    snapshot = client.get("/api/v1/action-center").json()
    notification = client.get("/api/v1/action-center/notifications").json()
    assert notification["state"] == "ready"
    assert "private-title-orchid" not in str(notification)
    page = client.get("/attention/notifications")
    values = Form(page.text).hidden
    assert client.post("/attention/notifications/acknowledge", data=values).status_code == 200
    assert client.get("/api/v1/action-center/notifications").json()["state"] == "empty"
    assert client.get("/api/v1/action-center").json() == snapshot
    preferences = Form(client.get("/settings/notifications").text).hidden
    selected = {
        **preferences,
        "quiet_start": "22:00",
        "quiet_end": "08:00",
        "timezone": "Europe/Rome",
        "aggregation_seconds": "60",
        "in_app": "on",
        "quiet_enabled": "on",
    }
    result = client.post("/settings/notifications", data=selected)
    assert result.status_code == 200, result.text
    saved = manager.load().settings
    assert saved.schema_version == 4 and saved.interface_mode == "preview"
    assert saved.notifications.timezone == "Europe/Rome"
    assert protected_bytes(instance) == before


def test_scope_authority_change_invalidates_previously_prepared_decision(browser):
    client, instance, _manager, _app = browser
    item = extraction(client)
    values = decision_form(client, item)
    authority = client.get("/api/v1/action-center/authority").json()
    fields = Form(client.get("/attention/authority").text).hidden
    choice = {
        **fields,
        "queue": "extraction_error",
        "mode": "disabled",
        "scope": "instance:" + authority["instance_id"],
        "confirmed": "on",
    }
    assert client.post("/attention/authority", data=choice).status_code == 200
    assert client.post(f"/attention/items/{item['id']}/decision", data=values).status_code == 409
    assert extraction(client)["allowed_actions"] == []
    assert protected_bytes(instance)


def test_notification_history_reset_requires_confirmation_and_preserves_review(browser):
    client, instance, manager, _app = browser
    before = protected_bytes(instance)
    snapshot = client.get("/api/v1/action-center").json()
    settings = manager.path.read_bytes()
    acknowledgement = Form(client.get("/attention/notifications").text).hidden
    assert (
        client.post("/attention/notifications/acknowledge", data=acknowledgement).status_code == 200
    )
    assert client.get("/api/v1/action-center/notifications").json()["state"] == "empty"
    fields = Form(client.get("/settings/notifications/history").text).hidden
    assert client.post("/settings/notifications/history", data=fields).status_code == 400
    assert client.get("/api/v1/action-center/notifications").json()["state"] == "empty"
    fields = Form(client.get("/settings/notifications/history").text).hidden
    result = client.post(
        "/settings/notifications/history", data={**fields, "confirm_redelivery": "on"}
    )
    assert result.status_code == 200, result.text
    notification = client.get("/api/v1/action-center/notifications").json()
    assert notification["state"] == "ready" and notification["last_reset"]
    assert (
        notification["last_reset"]["reset_at"] in client.get("/settings/notifications/history").text
    )
    assert client.get("/api/v1/action-center").json() == snapshot
    assert manager.path.read_bytes() == settings
    assert protected_bytes(instance) == before


def test_notification_pagination_reaches_later_items_without_acknowledging_first_page(
    browser, monkeypatch
):
    client, instance, _manager, app = browser
    before = protected_bytes(instance)
    real_snapshot = client.get("/api/v1/action-center").json()
    exemplar = real_snapshot["items"][0]
    # Synthetic producer snapshot tests HTTP pagination with the real delivery journal.
    # The producer and canonical-evidence behavior are covered separately.
    items = [{**copy.deepcopy(exemplar), "id": f"aci_{index:032x}"} for index in range(101)]

    def snapshot(*, limit=100, offset=0, **_filters):
        return {
            **copy.deepcopy(real_snapshot),
            "items": copy.deepcopy(items[offset : offset + limit]),
            "total": 101,
            "observed_count": 101,
            "limit": limit,
            "offset": offset,
        }

    monkeypatch.setattr(app.state.action_center, "snapshot", snapshot)
    first = client.get("/attention/notifications")
    assert "offset=100" in first.text
    later = client.get("/attention/notifications?offset=100")
    fields = Form(later.text).hidden
    assert fields["offset"] == "100"
    result = client.post(
        "/attention/notifications/acknowledge", data=fields, follow_redirects=False
    )
    assert result.status_code == 303 and "offset=100" in result.headers["location"]
    assert client.get("/api/v1/action-center/notifications?offset=100").json()["state"] == "empty"
    first_view = client.get("/api/v1/action-center/notifications").json()
    assert first_view["count"] == 100 and first_view["acknowledged_count"] == 1
    assert all(member["item_id"] != items[100]["id"] for member in first_view["items"])
    assert protected_bytes(instance) == before


def test_corrupt_review_state_is_unknown_not_empty_and_does_not_hide_knowledge(browser):
    client, instance, _manager, app = browser
    before = protected_bytes(instance)
    item = extraction(client)
    state_path = app.state.action_center.path
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_bytes(b"{invalid synthetic state")
    snapshot = client.get("/api/v1/action-center").json()
    assert snapshot["total"] is None and snapshot["count_relation"] == "unknown"
    notification = client.get("/api/v1/action-center/notifications").json()
    assert notification["state"] == "unavailable" and notification["queue_count"] is None
    page = client.get("/attention?lang=en")
    assert page.status_code == 200 and "prevents the queue contents" in page.text
    assert client.get(f"/attention/items/{item['id']}").status_code == 503
    assert client.get("/api/v1/action-center/authority").status_code == 503
    assert client.get("/browse").status_code == 200
    assert state_path.read_bytes() == b"{invalid synthetic state"
    assert protected_bytes(instance) == before
