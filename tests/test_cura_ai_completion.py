"""Current/Cura parity and read-only model observation, with public fixtures."""

import base64
import hashlib
import json
from dataclasses import replace
from html import unescape
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient

from provelume.ai_runtime_contract import MODEL_ID
from provelume.service import ProvelumeInstance
from provelume.shell_settings import LauncherSettings, ShellSettingsManager, default_settings
from provelume.web import create_app


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def find(self, tag, **attrs):
        return next(v for t, v in self.tags if t == tag and attrs.items() <= v.items())

    def links(self):
        return [v["href"] for t, v in self.tags if t == "a" and "href" in v]


@pytest.fixture
def ui(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Public Cura audit")
    manager = ShellSettingsManager(tmp_path / "launcher.json", default_settings())
    app = create_app(instance.root, shell_settings_file=manager.path)
    with TestClient(app) as client:
        yield app, client, manager


def watch(client):
    response = client.get("/settings/ai?lang=en")
    assert response.status_code == 200
    data = Page(response.text).find("section", **{"data-ai-model-watch": None})
    url = data["data-url"] + "&" + urlencode({
        "session": data["data-session"], "operation": data["data-operation"],
    })
    return response, url


@pytest.mark.parametrize("mode", ["current", "preview"])
def test_progress_is_read_only_bound_and_does_not_invalidate_other_forms(ui, mode, monkeypatch):
    app, client, manager = ui
    manager.set_interface_mode(mode, expected_revision=manager.load().settings.revision)
    host = app.state.ai_setup
    operation = host.begin_operation("install")
    page, url = watch(client)
    before = host.configuration()

    def forbidden(*args, **kwargs):
        pytest.fail("status GET performed acquisition, verification, inference or activation")

    for obj, methods in ((host, ("run_operation", "enable", "save")),
                         (host.models, ("install", "_verify")),
                         (host.runtime, ("validate_installation",))):
        for method in methods:
            monkeypatch.setattr(obj, method, forbidden)
    for size in (0, 4096, 12001672):
        host.operation["bytes"] = size
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert data["bytes"] == size and data["operation"] == operation
        assert "fragments" not in data  # No nonce churn while polling.
        assert response.headers["cache-control"] == "no-store"
        assert str(host.models.root) not in response.text
        assert "credential" not in response.text
    assert host.configuration() == before
    assert not host.jobs.session_authorized and not host.jobs.journal.list_jobs()
    # The original cancel form remains valid after repeated status reads.
    parsed = Page(page.text)
    values = {key: parsed.find("input", name=key)["value"]
              for key in ("csrf_token", "mutation_nonce", "instance_id")}
    values["operation_id"] = operation
    assert client.post("/settings/ai/model/cancel", data=values,
                       follow_redirects=False).status_code == 303
    assert client.get(url).json()["cancel_requested"] is True
    assert client.get(url.replace(operation, "op_other")).status_code == 409
    assert client.get(url + "x").status_code == 409
    with TestClient(app, client=("192.0.2.5", 12345)) as remote:
        assert remote.get(url).status_code == 403


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled"])
def test_terminal_status_supplies_fresh_actions_without_enabling_model(ui, state):
    app, client, _ = ui
    host = app.state.ai_setup
    host.begin_operation("install")
    _, url = watch(client)
    if state == "completed":
        path = host.models._path(host.models.registry.entry(MODEL_ID))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Public synthetic model presence; never loaded")
    host.operation["state"] = state
    data = client.get(url).json()
    assert data["state"] == state
    actions = Page(data["fragments"]["ai-model-actions"])
    assert actions.find("input", name="csrf_token")["value"]
    assert actions.find("input", name="authority")["value"] == host.model_authority()
    if state == "completed":
        assert actions.find("input", name="action")["value"] == "enable_local"
    assert not host.jobs.session_authorized
    assert 'data-ai-session="off"' in data["fragments"]["ai-session-state"]


def test_progress_script_has_exact_csp_and_integrity(ui):
    _, client, _ = ui
    page = client.get("/settings/ai")
    script = Page(page.text).find("script", src="/static/ai-model-progress.js")
    raw = client.get(script["src"]).content
    integrity = "sha256-" + base64.b64encode(hashlib.sha256(raw).digest()).decode()
    assert script["integrity"] == integrity
    assert f"'{integrity}'" in page.headers["content-security-policy"]
    assert "'unsafe-inline'" not in page.headers["content-security-policy"]
    assert integrity not in client.get("/browse").headers["content-security-policy"]


def test_slow_download_renews_cancellation_without_nonce_churn(ui, monkeypatch):
    from provelume import ai_activity, shell_activity

    app, client, _ = ui
    host = app.state.ai_setup
    operation = host.begin_operation("install")
    page, url = watch(client)
    first = client.get(url).json()["cancel_nonce"]
    assert client.get(url).json()["cancel_nonce"] == first
    now = ai_activity.time.monotonic()
    clock = SimpleNamespace(monotonic=lambda: now + 601)
    monkeypatch.setattr(ai_activity, "time", clock)
    monkeypatch.setattr(shell_activity, "time", clock)
    fresh = client.get(url).json()["cancel_nonce"]
    assert fresh != first
    parsed = Page(page.text)
    values = {key: parsed.find("input", name=key)["value"]
              for key in ("csrf_token", "instance_id")}
    response = client.post("/settings/ai/model/cancel", data={
        **values, "mutation_nonce": fresh, "operation_id": operation,
    }, follow_redirects=False)
    assert response.status_code == 303
    assert host.operation["cancel_requested"]


@pytest.mark.parametrize("schema", [1, 2, 3, 4])
def test_upgrade_offer_then_cura_and_explicit_rollback_preserve_preferences(ui, schema):
    app, client, manager = ui
    old = LauncherSettings(instance_path=str(app.state.ai_setup.instance.root),
                           language="it", theme="dark", check_on_start=True)
    # Install historical bytes as an upgrade fixture, not via the modern writer
    # whose deliberate schema-downgrade guard must remain intact.
    manager.path.write_text(json.dumps(old.as_payload()))
    if schema >= 3:
        manager.save(replace(manager.load().settings, schema_version=3))
    if schema == 4:
        manager.configure_notifications(manager.load().settings.notifications,
                                        expected_revision=manager.load().settings.revision)
    if schema == 1:
        manager.path.write_text(json.dumps({
            "schema_version": 1, "instance_path": old.instance_path,
            "update_channel": "preview", "check_on_start": True, "language": "it",
        }))
    baseline = manager.load().settings
    original = manager.path.read_bytes()
    assert "Scegli l’interfaccia" in client.get("/").text
    assert manager.path.read_bytes() == original  # Viewing never migrates on disk.
    for mode in ("preview", "current"):
        # Interface form has its own one-time reference, not the general form's.
        text = client.get("/settings/shell?lang=it").text
        start = text.index('<form id="interface-mode-form"')
        form = Page(text[start:text.index("</form>", start)])
        values = {key: form.find("input", name=key)["value"]
                  for key in ("csrf_token", "mutation_nonce", "revision", "action")}
        values["interface_mode"] = mode
        response = client.post("/settings/shell?lang=it", data=values)
        assert response.status_code == 200
        current = manager.load().settings
        assert current.interface_mode == mode and current.interface_mode_change.to_mode == mode
        for field in ("instance_path", "language", "theme", "check_on_start", "notifications"):
            assert getattr(current, field) == getattr(baseline, field)
        home = client.get("/").text
        assert "Scegli l’interfaccia" not in home
        assert ('class="cura"' in home) == (mode == "preview")
    # Restart and an explicit keep-current choice retain the rollback and dismiss offer.
    with TestClient(create_app(app.state.ai_setup.instance.root,
                               shell_settings_file=manager.path)) as restarted:
        assert "Scegli l’interfaccia" not in restarted.get("/").text


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
def test_cura_management_and_special_views_cover_existing_destinations(ui, language):
    _, client, _ = ui
    management = client.get("/management", params={"lang": language})
    assert 'class="cura"' in management.text
    links = Page(management.text).links()
    required = {"/settings/ai", "/settings/preferences", "/settings/notifications",
                "/operations/ai", "/sources", "/connectors", "/google/connect",
                "/components", "/scheduler", "/security/network", "/settings/shell"}
    assert required <= {urlsplit(link).path for link in links}
    browse = Page(client.get("/browse", params={"lang": language}).text)
    special = {"/email", "/photos", "/audio", "/video", "/file-families", "/ocr",
               "/transcripts", "/duplicates", "/bundles", "/representations"}
    assert special <= {urlsplit(link).path for link in browse.links()}
    for link in links + browse.links():
        if urlsplit(link).path in required | special:
            response = client.get(link)
            assert response.status_code == 200, link
            assert 'class="cura"' in response.text, link
            assert f'<html lang="{language}"' in response.text


def test_ai_document_roundtrip_keeps_search_context_and_rejects_external_return(ui, tmp_path):
    app, client, _ = ui
    source = tmp_path / "synthetic-source"
    source.mkdir()
    (source / "orchid.txt").write_text("Public orchid audit document.")
    instance = app.state.ai_setup.instance
    instance.ingest(source)
    document = instance.list_documents()[0]["id"]
    back = "/search?lang=it&q=orchid#result-" + document
    query = urlencode({"lang": "it", "return_to": back})
    page = Page(client.get(f"/documents/{document}?{query}").text)
    link = next(link for link in page.links() if "/synthesis?" in link)
    assert parse_qs(urlsplit(link).query)["return_to"] == [back]
    synthesis = Page(client.get(link).text)
    return_link = next(link for link in synthesis.links()
                       if urlsplit(link).path == f"/documents/{document}")
    assert parse_qs(urlsplit(return_link).query)["return_to"] == [back]
    assert back in Page(client.get(return_link).text).links()
    attack = client.get(f"/documents/{document}/synthesis",
                        params={"return_to": "https://evil.invalid/", "lang": "it"})
    assert "evil.invalid" not in unescape(attack.text)


def test_no_settings_manager_uses_standard_layout(ui):
    app, client, _ = ui
    del app.state.shell_settings_manager
    assert 'class="cura"' in client.get("/").text
