"""Local browser/API journeys, authority denial and retained exact-source semantics."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from provelume.catalog_registry import SUPPORTED_LANGUAGES, validate_catalogs
from provelume.knowledge_object_activity import API
from provelume.knowledge_object_contract import KnowledgeObjectError
from provelume.knowledge_object_evidence import current_instance_id
from provelume.service import ProvelumeInstance
from provelume.web import create_app

ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def browser(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "shell"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "shell"))
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_bytes(b"First exact original.\n")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    with TestClient(app) as client:
        yield instance, client, source


class Form(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.fields = {}
        self.checked = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        row = dict(attrs)
        if tag == "input" and row.get("type") == "hidden":
            assert row["name"] not in self.fields
            self.fields[row["name"]] = row.get("value", "")
        if tag == "input" and row.get("type") == "checkbox" and "checked" in row:
            self.checked.append((row["name"], row.get("value", "")))


def _authorization(client, identity=None, relation=False):
    response = client.get(API + "/authorization", params={
        **({"identity": identity} if identity else {}), "relation": str(relation).lower(),
    })
    assert response.status_code == 200, response.text
    return {k: v for k, v in response.json().items() if k not in {"one_use", "expires_in_seconds"}}


def _create(client, title="Manual", **changes):
    data = {"kind": "entity", "title": title, "body": {"description": "Inert <script> text"},
            "state": "active", "aliases": [], "evidence": [], **changes}
    return client.post(API, json={**_authorization(client), "confirmed": True, "data": data},
                       headers=ORIGIN)


def _ref(view):
    return {"id": view["record"]["id"], "revision": view["record"]["revision"],
            "sha256": view["sha256"]}


def _snapshot(instance):
    return {p.relative_to(instance.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in instance.root.rglob("*") if p.is_file()}


def _post_form(client, form, fields):
    pairs = list(form.fields.items()) + form.checked + list(fields.items())
    return client.post("/objects/save", content=urlencode(pairs), headers={
        **ORIGIN, "Content-Type": "application/x-www-form-urlencoded",
    }, follow_redirects=False)


def test_api_creation_is_manual_and_reads_are_inert(browser):
    instance, client, _ = browser
    before = _snapshot(instance)
    for path in ("/objects", "/objects/new", API, API + "/authorization"):
        assert client.get(path).status_code == 200
    assert _snapshot(instance) == before
    response = _create(client)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["record"]["origin"] == {"kind": "manual", "proposal_id": None}
    assert view["mutated"] is True and view["truth"] == "NOT_VERIFIED"
    identity = view["record"]["id"]
    assert client.get(API + "/" + identity).json()["mutated"] is False
    assert len(client.get(API + "/" + identity + "/history").json()["items"]) == 1
    after = _snapshot(instance)
    for path in (f"/objects/{identity}", f"/objects/{identity}/history",
                 f"/objects/{identity}?revision=1", f"/objects/{identity}/edit"):
        result = client.get(path)
        assert result.status_code == 200, result.text
        assert "<script> text" not in result.text
    assert after == _snapshot(instance)
    assert all(after[name] == digest for name, digest in before.items()
               if not name.startswith(("knowledge/", "index/", "library/")))


@pytest.mark.parametrize("confirmed", [False, None, 1, "true", [], {}])
def test_no_confirmation_never_writes(browser, confirmed):
    instance, client, _ = browser
    auth = _authorization(client)
    before = _snapshot(instance)
    response = client.post(API, json={**auth, "confirmed": confirmed, "data": {}}, headers=ORIGIN)
    assert response.status_code == 403
    assert before == _snapshot(instance)


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://attacker.invalid"},
    {"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "http://testserver", "Sec-Fetch-Site": "none"}])
def test_origin_denial_precedes_any_domain_write(browser, headers):
    instance, client, _ = browser
    before = _snapshot(instance)
    response = client.post(API, json={**_authorization(client), "confirmed": True, "data": {}},
                           headers=headers)
    assert response.status_code == 403
    assert before == _snapshot(instance)


def test_nonce_subject_instance_preimage_and_replay(browser):
    instance, client, _ = browser
    first = _create(client).json()
    second = _create(client, "Other").json()
    identity = first["record"]["id"]
    auth = _authorization(client, identity)
    value = {**auth, "confirmed": True, "data": {"changes": {"title": "New"}, "evidence": []}}
    for field, bad in (("nonce", "bad"), ("instance_id", "inst_" + "0" * 32),
                       ("expected_sha256", "0" * 64), ("request_id", "wrong")):
        before = _snapshot(instance)
        assert client.post(API + "/" + identity, json={**value, field: bad},
                           headers=ORIGIN).status_code in {403, 409}
        assert before == _snapshot(instance)
    assert client.post(API + "/" + second["record"]["id"], json=value,
                       headers=ORIGIN).status_code == 409
    assert client.post(API + "/" + identity, json=value, headers=ORIGIN).status_code == 200
    before = _snapshot(instance)
    assert client.post(API + "/" + identity, json=value, headers=ORIGIN).status_code == 409
    assert before == _snapshot(instance)


def test_two_forms_do_not_overwrite_current_or_auto_retry(browser):
    instance, client, _ = browser
    original = _create(client).json()
    identity = original["record"]["id"]
    first, second = _authorization(client, identity), _authorization(client, identity)
    def save(auth, title):
        return client.post(API + "/" + identity, json={**auth, "confirmed": True,
            "data": {"changes": {"title": title}, "evidence": []}}, headers=ORIGIN)
    assert save(first, "Winner").status_code == 200
    before = _snapshot(instance)
    assert save(second, "Lost").status_code == 409
    assert before == _snapshot(instance)
    assert save(second, "Lost").status_code == 409
    assert client.get(API + "/" + identity).json()["record"]["title"] == "Winner"
    history = client.get(API + "/" + identity + "/history").json()
    assert [r["title"] for r in history["items"]] == ["Manual", "Winner"]


@pytest.mark.parametrize("payload", [b'{"nonce":"a","nonce":"b"}', b'{"x":NaN}',
    b'{"x":Infinity}', b'\xff', b'[' * 1100, b' ' * (256 * 1024 + 1)],
    ids=["duplicate", "nan", "infinity", "invalid-utf8", "deep", "oversize"])
def test_hostile_json_is_bounded_and_inert(browser, payload):
    instance, client, _ = browser
    before = _snapshot(instance)
    response = client.post(API, content=payload,
                           headers={**ORIGIN, "Content-Type":"application/json"})
    assert response.status_code in {400, 413}
    assert before == _snapshot(instance)


@pytest.mark.parametrize("extra", ["origin", "instance_id", "id", "provider", "proposal_id"])
def test_api_closed_fields_refuse_authority_or_identity_injection(browser, extra):
    instance, client, _ = browser
    auth = _authorization(client)
    before = _snapshot(instance)
    response = client.post(API, json={**auth, "confirmed": True, "data": {
        "kind": "entity", "title": "Injected", "body": {"description":""},
        "state": "active", "aliases": [], "evidence": [], extra:"forged",
    }}, headers=ORIGIN)
    assert response.status_code == 400
    assert before == _snapshot(instance)


def test_attributed_claim_keeps_old_original_after_new_version(browser):
    instance, client, source = browser
    version = instance.store.list_canonical("versions")[0]
    evidence = client.get(API + "/evidence", params={"version_id":version["id"]}).json()["record"]
    response = _create(client, "Claim", kind="claim", body={"statement":"My explicit statement"},
                       state="asserted", evidence=[evidence])
    assert response.status_code == 200, response.text
    view = response.json()
    (source / "note.txt").write_bytes(b"Second independent exact original.\n")
    instance.ingest(source)
    assert len(instance.versions(version["document_id"])) == 2
    old = client.get("/objects/versions/" + version["id"] + "/original")
    assert old.status_code == 200 and old.content == b"First exact original.\n"
    assert old.headers["content-type"] == "application/octet-stream"
    assert "attachment" in old.headers["content-disposition"]
    current = client.get(API + "/" + view["record"]["id"]).json()
    assert current["record"]["evidence_ids"] == [evidence["id"]]
    assert current["evidence"][0]["status"] == "AVAILABLE"
    assert current["truth"] == "NOT_VERIFIED"
    doc = client.get("/documents/" + version["document_id"])
    assert f"version_id={version['id']}" in doc.text


def test_form_withdrawal_preserves_unavailable_evidence_and_multiline_body(browser):
    instance, client, _ = browser
    version = instance.store.list_canonical("versions")[0]
    evidence = instance.object_services().evidence_for_version(version["id"])
    view = _create(client, "Claim", kind="claim", body={"statement":"One line\nSecond line"},
                   state="asserted", evidence=[evidence]).json()
    identity = view["record"]["id"]
    original = instance.store.read_canonical("originals", evidence["original_id"])
    (instance.root / original["storage_ref"]).unlink()
    page = client.get(f"/objects/{identity}/edit")
    form = Form(page.text)
    response = _post_form(client, form, {"title":"Claim", "aliases":"", "state":"retracted",
        "statement":"One line\r\nSecond line", "confirmed":"yes"})
    assert response.status_code == 303, response.text
    current = client.get(API + "/" + identity).json()
    assert current["record"]["state"] == "retracted"
    assert current["record"]["body"] == view["record"]["body"]
    assert current["record"]["evidence_ids"] == [evidence["id"]]
    assert current["evidence"][0]["status"] == "UNAVAILABLE"
    assert client.get("/objects/versions/" + version["id"] + "/original").status_code == 400


def test_html_creation_exact_source_and_nonce_replay(browser):
    instance, client, _ = browser
    version = instance.store.list_canonical("versions")[0]
    page = client.get("/objects/new", params={"kind":"claim", "version_id":version["id"]})
    assert page.status_code == 200
    assert page.headers["referrer-policy"] == "same-origin"
    form = Form(page.text)
    fields = {"title":"Browser claim", "aliases":"Alias", "statement":"Literal <img src=x>",
              "state":"asserted", "confirmed":"yes"}
    saved = _post_form(client, form, fields)
    assert saved.status_code == 303, saved.text
    detail = client.get(saved.headers["location"])
    assert "Literal &lt;img src=x&gt;" in detail.text and "Literal <img src=x>" not in detail.text
    before = _snapshot(instance)
    assert _post_form(client, form, fields).status_code == 409
    assert before == _snapshot(instance)


def test_native_form_referrer_exception_is_narrow_and_never_accepts_null_origin(browser):
    instance, client, _ = browser
    for path in ("/objects", API, API + "/authorization", "/objects/sources", "/browse"):
        assert client.get(path).headers["referrer-policy"] == "no-referrer"
    form = Form(client.get("/objects/new").text)
    before = _snapshot(instance)
    body = urlencode({**form.fields, "title":"Blocked", "description":"", "aliases":"",
                      "state":"active", "confirmed":"yes"})
    response = client.post("/objects/save", content=body, headers={
        "Origin":"null", "Content-Type":"application/x-www-form-urlencoded",
    })
    assert response.status_code == 403
    assert response.headers["referrer-policy"] == "no-referrer"
    assert before == _snapshot(instance)


def test_relations_pin_reviewed_endpoint_and_only_explicit_refresh_advances(browser):
    instance, client, _ = browser
    a, b = _create(client, "A").json(), _create(client, "B").json()
    auth = _authorization(client, relation=True)
    response = client.post(API + "?relation=true", json={**auth, "confirmed":True, "data": {
        "relation_type":"relates_to", "source":_ref(a), "target":_ref(b), "evidence":[],
    }}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    relation = response.json()
    identity = relation["record"]["id"]
    instance.object_services().update(a["record"]["id"], {"title":"A now"},
                                     expected_sha256=a["sha256"], consent=True)
    path = f"/objects/{identity}?relation=true"
    assert "retained reference is historical" in client.get(path).text
    edit = path.split("?")[0] + "/edit?relation=true"
    fields = {"source":a["record"]["id"], "target":b["record"]["id"],
              "relation_type":"relates_to", "state":"active", "confirmed":"yes"}
    # Nothing silently retargets the same selected ID to its newer revision.
    before = _snapshot(instance)
    assert _post_form(client, Form(client.get(edit).text), fields).status_code == 400
    assert before == _snapshot(instance)
    fields["refresh_source"] = "yes"
    assert _post_form(client, Form(client.get(edit).text), fields).status_code == 303
    current = client.get(API + "/" + identity + "?relation=true").json()
    assert current["record"]["source"]["revision"] == 2
    assert current["endpoints"][0]["current"] is True
    fields.pop("refresh_source")
    fields["state"] = "retracted"
    assert _post_form(client, Form(client.get(edit).text), fields).status_code == 303
    assert client.get(path + "&revision=1").status_code == 200


@pytest.mark.parametrize("kind", ["project", "collection"])
def test_existing_hierarchy_identity_and_name_authority_are_preserved(browser, kind):
    instance, client, _ = browser
    node = instance.create_hierarchy_node(kind, "Existing stable node")
    identity = node["id"]
    page = client.get(f"/objects/{identity}/edit")
    assert page.status_code == 200 and 'name="title"' in page.text and " readonly" in page.text
    view = client.get(API + "/" + identity).json()
    before = _snapshot(instance)
    auth = _authorization(client, identity)
    result = client.post(API + "/" + identity, json={**auth, "confirmed":True,
        "data":{"changes":{"title":"Different authority"}, "evidence":[]}}, headers=ORIGIN)
    assert result.status_code == 400 and before == _snapshot(instance)
    result = _create(client, kind=kind)
    assert result.status_code == 400
    auth = _authorization(client, identity)
    result = client.post(API + "/" + identity, json={**auth, "confirmed":True,
        "data":{"changes":{"body":{"description":"Explicit metadata"}}, "evidence":[]}},
        headers=ORIGIN)
    assert result.status_code == 200
    assert result.json()["record"]["id"] == identity
    assert instance.get_hierarchy_node(identity)["name"] == "Existing stable node"
    assert view["record"]["revision"] + 1 == result.json()["record"]["revision"]


@pytest.mark.parametrize("language", sorted(SUPPORTED_LANGUAGES))
def test_shared_pages_catalog_and_safe_semantics_in_both_interfaces(browser, language):
    instance, client, _ = browser
    view = _create(client, "Hostile <script>alert(1)</script>").json()
    identity = view["record"]["id"]
    for mode in ("current", "preview"):
        # Existing shell state chooses the primary or explicit reversible backup.
        manager = client.app.state.shell_settings_manager
        from dataclasses import replace
        loaded = manager.load()
        manager.save(replace(loaded.settings, interface_mode=mode))
        for path in ("/objects", "/objects/new", f"/objects/{identity}",
                     f"/objects/{identity}/edit", f"/objects/{identity}/history",
                     "/objects/sources"):
            response = client.get(path, params={"lang":language})
            assert response.status_code == 200, response.text
            assert '<html lang="' + language + '"' in response.text
            assert 'id="main-content"' in response.text
            assert '<script>alert(1)</script>' not in response.text
            assert "objects." not in response.text
            assert response.headers["cache-control"] == "no-store"
        page = client.get(f"/objects/{identity}/edit?lang={language}").text
        assert '<label for="object-title">' in page
        assert 'name="confirmed" value="yes" required' in page
        assert 'aria-' in page
    assert validate_catalogs()["automatic_contract"] == "PASS"


def test_instance_binding_is_checked_inside_write_lock(browser):
    instance, _client, _ = browser
    service = instance.object_services()
    before = _snapshot(instance)
    with pytest.raises(KnowledgeObjectError, match="conflict"):
        service.create("entity", "Wrong Instance", {"description":""}, consent=True,
                       expected_instance_id="inst_" + "0" * 32)
    assert before == _snapshot(instance)
    view = service.create("entity", "Bound", {"description":""}, consent=True,
                          expected_instance_id=current_instance_id(instance.store))
    assert view["record"]["title"] == "Bound"


def test_remote_client_cannot_read_or_write_local_objects(browser, monkeypatch):
    instance, client, _ = browser
    from provelume.knowledge_object_services import KnowledgeObjectServices

    def forbidden(*args, **kwargs):
        raise AssertionError("remote request reached object IO")

    monkeypatch.setattr(KnowledgeObjectServices, "list", forbidden)
    monkeypatch.setattr(KnowledgeObjectServices, "create", forbidden)
    before = _snapshot(instance)
    with TestClient(client.app, client=("192.0.2.7", 1234)) as remote:
        for path in (API, API + "/authorization", "/objects", "/objects/new"):
            assert remote.get(path).status_code == 403
        assert remote.post(API, json={}, headers=ORIGIN).status_code == 403
        assert remote.post("/objects/save", content="confirmed=yes", headers={
            **ORIGIN, "Content-Type":"application/x-www-form-urlencoded",
        }).status_code == 403
    assert before == _snapshot(instance)


def test_expired_confirmation_is_not_a_new_authority_grant(browser, monkeypatch):
    instance, client, _ = browser
    from provelume import review_security

    auth = _authorization(client)
    before = _snapshot(instance)
    now = review_security.monotonic()
    monkeypatch.setattr(review_security, "monotonic", lambda: now + 601)
    result = client.post(API, json={**auth, "confirmed":True, "data":{}}, headers=ORIGIN)
    assert result.status_code == 409
    assert before == _snapshot(instance)


@pytest.mark.parametrize("suffix", ["&title=duplicate", "&consent=always", "&retain=forged"])
def test_browser_closed_fields_and_duplicate_scalars_cannot_add_authority(browser, suffix):
    instance, client, _ = browser
    form = Form(client.get("/objects/new").text)
    body = urlencode({**form.fields, "title":"Manual", "description":"", "aliases":"",
                      "state":"active", "confirmed":"yes"}) + suffix
    before = _snapshot(instance)
    response = client.post("/objects/save", content=body, headers={
        **ORIGIN, "Content-Type":"application/x-www-form-urlencoded",
    })
    assert response.status_code == 400
    assert before == _snapshot(instance)


def test_source_picker_follows_exact_version_not_implicit_current(browser):
    instance, client, source = browser
    old = instance.store.list_canonical("versions")[0]
    (source / "note.txt").write_bytes(b"Later source.\n")
    instance.ingest(source)
    page = client.get("/objects/sources", params={"kind":"claim", "document_id":old["document_id"]})
    assert page.status_code == 200
    for version in instance.versions(old["document_id"]):
        assert f"version_id={version['id']}" in page.text
    assert 'kind=claim' in page.text


def test_exact_original_delivery_has_its_own_bound_and_checks_returned_bytes(browser, monkeypatch):
    instance, client, _ = browser
    from provelume import knowledge_object_activity as activity
    from provelume.knowledge_object_services import KnowledgeObjectServices

    version = instance.store.list_canonical("versions")[0]
    path = "/objects/versions/" + version["id"] + "/original"
    before = _snapshot(instance)
    monkeypatch.setattr(activity, "MAX_DOWNLOAD", 3)
    assert client.get(path).status_code == 413
    assert before == _snapshot(instance)
    monkeypatch.setattr(activity, "MAX_DOWNLOAD", 25 * 1024 * 1024)
    original = instance.store.read_canonical("originals", version["original_id"])
    source_path = instance.root / original["storage_ref"]
    real = KnowledgeObjectServices.evidence_for_version

    def swapped(self, *args, **kwargs):
        evidence = real(self, *args, **kwargs)
        source_path.write_bytes(b"X" * original["size_bytes"])
        return evidence

    monkeypatch.setattr(KnowledgeObjectServices, "evidence_for_version", swapped)
    assert client.get(path).status_code == 400
    assert not instance.store.list_canonical("objects")


@pytest.mark.parametrize("kind,body,state", [
    ("entity", {"description":""}, "active"),
    ("decision", {"rationale":"An explicit reason"}, "proposed"),
    ("task", {"description":"Task", "due_at":None}, "open"),
    ("outcome", {"description":"Outcome"}, "proposed"),
    ("commitment", {"description":"Commitment", "due_at":"2026-10-18T09:00:00+02:00"}, "open"),
    ("calendar_event", {"description":"DST fold", "starts_at":"2026-10-25T02:15:00+02:00",
                        "ends_at":"2026-10-25T02:45:00+01:00", "time_zone":"Europe/Rome"},
     "tentative"),
])
def test_typed_browser_forms_create_the_selected_kind_without_default_withdrawal(
    browser, kind, body, state,
):
    _instance, client, _ = browser
    page = client.get("/objects/new", params={"kind":kind})
    assert page.status_code == 200
    assert f'value="{state}" selected' in page.text
    fields = {"title":"Typed manual", "aliases":"", "state":state, "confirmed":"yes",
              **{k:v or "" for k,v in body.items()}}
    result = _post_form(client, Form(page.text), fields)
    assert result.status_code == 303, result.text
    identity = result.headers["location"].split("?")[0].split("/")[-1]
    record = client.get(API + "/" + identity).json()["record"]
    assert record["kind"] == kind and record["body"] == body and record["state"] == state


@pytest.mark.parametrize("family", ["documents", "versions"])
def test_non_object_canonical_source_fails_with_redacted_error(browser, family):
    instance, client, _ = browser
    version = instance.store.list_canonical("versions")[0]
    identity = version["document_id"] if family == "documents" else version["id"]
    (instance.root / "knowledge" / family / (identity + ".json")).write_text("[]\n")
    before = _snapshot(instance)
    response = client.get(API + "/evidence", params={"version_id":version["id"]})
    assert response.status_code in {400, 503}
    assert "knowledge_object_" in response.text
    assert before == _snapshot(instance)


@pytest.mark.parametrize("field", ["title", "aliases"])
def test_withdrawal_keeps_multiline_canonical_metadata(browser, field):
    instance, client, _ = browser
    version = instance.store.list_canonical("versions")[0]
    evidence = instance.object_services().evidence_for_version(version["id"])
    title = "\nClaim\nTitle" if field == "title" else "Claim"
    aliases = ["\nAlias\ninside"] if field == "aliases" else []
    view = _create(client, title, kind="claim", body={"statement":"\nRetained statement\n"},
                   state="asserted", aliases=aliases, evidence=[evidence]).json()
    identity = view["record"]["id"]
    original = instance.store.read_canonical("originals", evidence["original_id"])
    (instance.root / original["storage_ref"]).unlink()
    page = client.get(f"/objects/{identity}/edit")
    result = _post_form(client, Form(page.text), {
        "title":title.replace("\n", "\r\n"),
        "aliases":"\n".join(aliases).replace("\n", "\r\n"),
        "statement":"\r\nRetained statement\r\n", "state":"retracted", "confirmed":"yes",
    })
    assert result.status_code == 303, result.text
    current = client.get(API + "/" + identity).json()["record"]
    assert current["state"] == "retracted"
    assert all(current[key] == view["record"][key] for key in
               ("title", "aliases", "body", "evidence_ids"))
