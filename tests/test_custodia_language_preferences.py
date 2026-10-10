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


@pytest.mark.parametrize("language", ["system", "en", "it", "de", "es", "fr", "pt", "ro"])
def test_language_only_save_preserves_other_preferences_and_survives_restart(
    tmp_path, monkeypatch, language,
):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = ShellSettingsManager(tmp_path / "shell.json", LauncherSettings(
        instance_path=str(instance.root), language="en", login_startup=True,
        check_on_start=True, theme="dark", update_channel="stable"))
    manager.save(manager.defaults)
    before = manager.load().settings
    config_before = instance.store.read_config()
    client = TestClient(create_app(instance.root, shell_settings_file=manager.path))

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
    restarted = TestClient(create_app(instance.root, shell_settings_file=manager.path))
    if language != "system":
        assert f'<html lang="{language}"' in restarted.get("/").text
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
