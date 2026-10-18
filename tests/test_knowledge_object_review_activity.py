"""Synthetic local browser review journeys; machine checks do not imply human review."""

from dataclasses import replace
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from test_ai_synthesis import execute
from test_ai_synthesis import synthesis as _synthesis
from test_knowledge_object_review import _grant, _proposal
from test_review_placement_routing import _bytes

from provelume.catalog_registry import SUPPORTED_LANGUAGES, validate_catalogs
from provelume.knowledge_object_review import history_record
from provelume.web import create_app

synthesis = _synthesis
ORIGIN = {"Origin": "http://testserver"}


class Forms(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.forms, self.current = {}, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        row = dict(attrs)
        if tag == "form":
            self.current = {}
            self.forms[row["action"].split("?")[0]] = self.current
        if tag == "input" and row.get("type") == "hidden" and self.current is not None:
            assert row["name"] not in self.current
            self.current[row["name"]] = row.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def _fields(response, action):
    assert response.status_code == 200, response.text
    return Forms(response.text).forms["/objects/proposals/" + action]


def _post(client, operation, fields, **values):
    return client.post("/objects/proposals/" + operation, content=urlencode({**fields, **values}),
                       headers={**ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
                       follow_redirects=False)


@pytest.fixture
def browser(synthesis, tmp_path, monkeypatch):
    setup, _, _ = synthesis
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "shell"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "shell"))
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    # These synchronous form-contract tests own AI execution explicitly. Worker
    # lifecycle/concurrency is qualified separately, including the native browser.
    c = TestClient(app)
    try:
        yield synthesis, c
    finally:
        c.close()


@pytest.mark.parametrize("mode", ["preview", "current"])
def test_local_prepare_edit_preview_approve_and_discard_history(browser, mode):
    synthesis, client = browser
    setup, _, _ = synthesis
    instance = setup.instance
    job = execute(synthesis)
    _grant(instance)
    manager = client.app.state.shell_settings_manager
    manager.save(replace(manager.load().settings, interface_mode=mode))
    before = _bytes(instance.store.paths.knowledge)
    page = client.get("/objects/proposals/new", params={"job_id": job["id"]})
    assert page.headers["Referrer-Policy"] == "same-origin"
    create = _fields(page, "prepare")
    result = _post(client, "prepare", create, title="Draft <script>inert</script>", aliases="",
                   statement="\nMonday\r\n", state="asserted", confirmed="yes")
    assert result.status_code == 303, result.text
    assert _bytes(instance.store.paths.knowledge) == before
    identity = result.headers["location"].split("?")[0].split("/")[-1]
    assert _post(client, "prepare", create, title="Replay", aliases="", statement="Monday",
                  state="asserted", confirmed="yes").status_code == 409
    detail = client.get(result.headers["location"])
    assert "&lt;script&gt;inert&lt;/script&gt;" in detail.text
    assert "<script>inert</script>" not in detail.text
    plan = _post(client, "preview", _fields(detail, "preview"), title="Reviewed date", aliases="",
                 statement="\r\nMonday\r\n", state="asserted", action="apply")
    confirmation = _fields(plan, "confirm")
    assert _bytes(instance.store.paths.knowledge) == before
    applied = _post(client, "confirm", confirmation, confirmed="yes")
    assert applied.status_code == 303, applied.text
    retained = history_record(instance.store, identity)
    value = instance.object_services().get(retained["canonical"]["id"])["record"]
    assert value["title"] == "Reviewed date" and value["body"] == {"statement": "\nMonday\n"}
    assert retained["edited"]
    assert _post(client, "confirm", confirmation, confirmed="yes").status_code == 409
    committed = client.get(applied.headers["location"])
    discard = _post(client, "discard", _fields(committed, "discard"), confirmed="yes")
    assert discard.status_code == 303 and client.get(discard.headers["location"]).status_code == 200
    history = client.get("/objects/proposals/" + identity)
    assert history.status_code == 200 and "/objects/" + value["id"] in history.text
    assert "/objects/proposals/discard" not in Forms(history.text).forms
    assert history_record(instance.store, identity) == retained
    assert instance.object_services().get(value["id"])["record"] == value


@pytest.mark.parametrize("language", sorted(SUPPORTED_LANGUAGES))
def test_proposals_and_capability_labels_work_in_both_interfaces(browser, language):
    synthesis, client = browser
    setup, job, proposal = _proposal(synthesis)
    before = _bytes(setup.instance.root)
    manager = client.app.state.shell_settings_manager
    for mode in ("current", "preview"):
        manager.save(replace(manager.load().settings, interface_mode=mode))
        for path in ("/objects/proposals", "/objects/proposals/" + proposal["id"],
                     "/review/capabilities", "/review/decisions/capabilities/knowledge_objects",
                     "/attention?queue=knowledge_objects"):
            response = client.get(path + ("&" if "?" in path else "?") + "lang=" + language)
            assert response.status_code == 200, response.text
            assert "object_review." not in response.text
            assert "review.knowledge_objects" not in response.text
            assert "action.knowledge_objects" not in response.text
        new = client.get("/objects/proposals/new", params={"job_id": job["id"], "lang": language})
        assert new.status_code == 200 and "object_review." not in new.text
    assert _bytes(setup.instance.root) == before
    assert validate_catalogs()["automatic_contract"] == "PASS"


@pytest.mark.parametrize("origin", [None, "null", "https://foreign.test", "http://localhost"])
def test_no_confirmation_from_missing_null_or_foreign_origin(browser, origin):
    synthesis, client = browser
    setup, _, proposal = _proposal(synthesis)
    page = client.get("/objects/proposals/" + proposal["id"])
    values = {**_fields(page, "preview"), "title": "Denied", "aliases": "",
              "statement": "No canonical effect", "state": "asserted", "action": "apply"}
    before = _bytes(setup.instance.root)
    response = client.post("/objects/proposals/preview", content=urlencode(values), headers={
        "Content-Type": "application/x-www-form-urlencoded",
        **({"Origin": origin} if origin is not None else {}),
    })
    assert response.status_code == 403
    assert _bytes(setup.instance.root) == before


def test_disabled_capability_shows_explicit_setup_without_a_confirm_control(browser):
    synthesis, client = browser
    setup, _, proposal = _proposal(synthesis)
    page = client.get("/objects/proposals/" + proposal["id"])
    plan = _post(client, "preview", _fields(page, "preview"), title="Inspect", aliases="",
                 statement="A manual assertion", state="asserted", action="apply")
    assert plan.status_code == 200
    assert "/objects/proposals/confirm" not in Forms(plan.text).forms
    assert "/review/decisions/capabilities/knowledge_objects" in plan.text
    assert not setup.instance.store.list_canonical("objects")


def test_stale_source_leaves_only_disposal_and_canonical_bytes_unchanged(browser):
    synthesis, client = browser
    setup, job, proposal = _proposal(synthesis)
    setup.synthesis.discard(job["id"])
    before = _bytes(setup.instance.store.paths.knowledge)
    page = client.get("/objects/proposals/" + proposal["id"])
    assert page.status_code == 200 and 'role="alert"' in page.text
    assert "/objects/proposals/preview" not in Forms(page.text).forms
    discarded = _post(client, "discard", _fields(page, "discard"), confirmed="yes")
    assert discarded.status_code == 303
    assert _bytes(setup.instance.store.paths.knowledge) == before


def test_duplicate_and_unconfirmed_form_fields_are_rejected(browser):
    synthesis, client = browser
    setup, _, proposal = _proposal(synthesis)
    before = _bytes(setup.instance.root)
    page = client.get("/objects/proposals/" + proposal["id"])
    values = _fields(page, "discard")
    response = client.post("/objects/proposals/discard", content=urlencode(values) +
                           "&identity=" + proposal["id"] + "&confirmed=yes", headers={
                               **ORIGIN, "Content-Type": "application/x-www-form-urlencoded",
                           })
    assert response.status_code == 400
    assert _post(client, "discard", values).status_code == 400
    assert _post(client, "discard", values, confirmed="no").status_code == 403
    assert _bytes(setup.instance.root) == before


def test_explicit_browser_rejection_retains_receipt_without_canonical_facts(browser):
    synthesis, client = browser
    setup, _, proposal = _proposal(synthesis)
    _grant(setup.instance)
    before = _bytes(setup.instance.store.paths.knowledge)
    page = client.get("/objects/proposals/" + proposal["id"])
    preview = _post(client, "preview", _fields(page, "preview"), title="Rejected", aliases="",
                    statement="Not a canonical assertion", state="asserted", action="reject")
    result = _post(client, "confirm", _fields(preview, "confirm"), confirmed="yes")
    assert result.status_code == 303, result.text
    assert history_record(setup.instance.store, proposal["id"])["action"] == "reject"
    assert _bytes(setup.instance.store.paths.knowledge) == before


def test_relation_form_preserves_pinned_endpoints_until_explicit_refresh(browser):
    synthesis, client = browser
    setup, _, _ = synthesis
    instance = setup.instance
    service = instance.object_services()
    objects = [service.create("entity", title, {"description": ""}, consent=True)
               for title in ("Source", "Target")]
    refs = [{"id": row["record"]["id"], "revision": 1, "sha256": row["sha256"]} for row in objects]
    draft = {"kind": "relation", "relation_type": "relates_to", "source": refs[0],
             "target": refs[1], "state": "active"}
    _, _, proposal = _proposal(synthesis, draft)
    _grant(instance)
    page = client.get("/objects/proposals/" + proposal["id"])
    updated = service.update(refs[1]["id"], {"title": "Current target"},
                             expected_sha256=refs[1]["sha256"], consent=True)
    fields = {"relation_type": "relates_to", "source": refs[0]["id"], "target": refs[1]["id"],
              "action": "apply"}
    stale = _post(client, "preview", _fields(page, "preview"), **fields)
    assert stale.status_code == 409
    fresh = client.get("/objects/proposals/" + proposal["id"])
    preview = _post(client, "preview", _fields(fresh, "preview"), refresh_target="yes", **fields)
    result = _post(client, "confirm", _fields(preview, "confirm"), confirmed="yes")
    assert result.status_code == 303, result.text
    retained = history_record(instance.store, proposal["id"])
    relation = service.get(retained["canonical"]["id"], relation=True)["record"]
    assert relation["target"] == {"id": refs[1]["id"], "revision": 2, "sha256": updated["sha256"]}
