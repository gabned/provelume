"""Language-only persistence cannot apply endpoint, startup or network settings."""

import re
from dataclasses import replace
from html import unescape

import pytest
from fastapi.testclient import TestClient

from provelume.service import ProvelumeInstance
from provelume.shell_settings import LauncherSettings, ShellSettingsManager
from provelume.web import create_app


def language_form(client):
    response = client.get("/settings/shell?lang=it")
    assert response.status_code == 200
    form = re.search(r'<form id="language-preference-form".*?</form>', response.text, re.S)[0]
    return {name: unescape(value) for name, value in re.findall(
        r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form)}


def selected_language(response):
    assert response.status_code == 200
    selector = re.search(
        r'<select id="shell-language"(?=\s|>)[^>]*>(.*?)</select>', response.text, re.S,
    )
    assert selector is not None
    options = re.findall(r'<option value="([^"]+)"([^>]*)>', selector[1])
    assert len(options) == 8
    assert {value for value, _ in options} == {
        "system", "en", "it", "de", "es", "fr", "pt", "ro",
    }
    selected = [value for value, attributes in options if re.search(r"\bselected\b", attributes)]
    assert len(selected) == 1  # No implicit browser fallback to the first option.
    return selected[0]


@pytest.mark.parametrize("mode", ["current", "preview"])
@pytest.mark.parametrize("language", ["system", "en", "it", "de", "es", "fr", "pt", "ro"])
def test_language_only_save_preserves_other_preferences_and_survives_restart(
    tmp_path, monkeypatch, language, mode,
):
    monkeypatch.setattr("provelume.catalog_registry.locale.getlocale", lambda: ("it_IT", "UTF-8"))
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = ShellSettingsManager(tmp_path / "shell.json", LauncherSettings(
        instance_path=str(instance.root), language="en", login_startup=True,
        check_on_start=True, theme="dark", update_channel="stable"))
    manager.save(manager.defaults)
    manager.set_interface_mode(mode, expected_revision=0)
    before = manager.load().settings
    config_before = instance.store.read_config()
    client = TestClient(create_app(instance.root, shell_settings_file=manager.path))
    export_before = client.get("/settings/preferences/export").json()
    assert selected_language(client.get("/settings/shell?lang=it")) == "en"

    def forbidden(*args, **kwargs):
        pytest.fail("language save invoked unrelated shell or network authority")

    monkeypatch.setattr("provelume.shell_settings.configure_login_startup", forbidden)
    monkeypatch.setattr("provelume.shell_settings.probe_port", forbidden)
    monkeypatch.setattr(ShellSettingsManager, "configure", forbidden)
    fields = language_form(client)
    assert manager.load().settings == before  # GET remains observational.
    result = client.post("/settings/shell", data={**fields, "language": language},
                         follow_redirects=False)
    assert result.status_code == 303
    assert manager.load().settings == replace(
        before, language=language, revision=before.revision + 1)
    assert instance.store.read_config() == config_before
    saved_bytes = manager.path.read_bytes()
    saved_page = client.get(result.headers["location"])
    assert selected_language(saved_page) == language
    effective_language = "it" if language == "system" else language
    assert f'<html lang="{effective_language}"' in saved_page.text
    assert client.get("/api/v1/shell").json()["shell"]["language"] == language
    assert client.get("/settings/preferences/export").json() == {
        **export_before, "language": language,
    }

    # A URL override changes page language, never the saved selector or export.
    overridden = client.get("/settings/shell?lang=de")
    assert '<html lang="de"' in overridden.text
    assert selected_language(overridden) == language
    assert client.get("/settings/preferences?lang=en").status_code == 200
    assert selected_language(client.get("/settings/shell")) == language

    restarted = TestClient(create_app(instance.root, shell_settings_file=manager.path))
    reopened = restarted.get("/settings/shell")
    assert selected_language(reopened) == language
    assert f'<html lang="{effective_language}"' in reopened.text
    assert restarted.get("/settings/preferences/export").json()["language"] == language
    assert manager.path.read_bytes() == saved_bytes
    assert instance.store.read_config() == config_before
    assert client.post("/settings/shell", data={**fields, "language": language}).status_code == 409


@pytest.mark.parametrize("extra", [{"language": "xx"}, {"port": "12345"},
                                   {"login_startup": "on"}, {"csrf_token": "wrong"}])
def test_language_save_rejects_extra_authority_or_invalid_request(tmp_path, extra):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = ShellSettingsManager(tmp_path / "shell.json", LauncherSettings(
        instance_path=str(instance.root)))
    manager.save(manager.defaults)
    before = manager.path.read_bytes()
    client = TestClient(create_app(instance.root, shell_settings_file=manager.path))
    fields = language_form(client)
    result = client.post("/settings/shell", data={**fields, "language": "it", **extra})
    assert result.status_code in {400, 403}
    assert manager.path.read_bytes() == before
