"""Actual HTTP forms; these do not claim rendered-browser or human qualification."""

from copy import deepcopy
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from provelume.service import ProvelumeInstance
from provelume.setup_progress import STEPS
from provelume.shell_settings import ShellSettingsManager, default_settings
from provelume.web import create_app


class HiddenFields(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.values = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("type") == "hidden":
            self.values[attrs["name"]] = attrs.get("value", "")


def post(client, step, action, **fields):
    form = client.get("/setup", params={"step": step})
    assert form.status_code == 200, form.text
    values = HiddenFields(form.text).values
    return client.post("/setup", data={**values, "action": action, **fields})


@pytest.mark.parametrize("interface", ["current", "preview"])
def test_six_screen_http_contract_in_all_catalogs_without_replaying_effects(tmp_path, interface):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    shell = ShellSettingsManager(tmp_path / "launcher.json", default_settings())
    shell.set_interface_mode(interface, expected_revision=0)
    client = TestClient(create_app(instance.root, shell_settings_file=shell.path))
    before = deepcopy(instance.store.read_config())
    for language in ["en", "it", "de", "es", "fr", "pt", "ro"]:
        for step in STEPS:
            response = client.get("/setup", params={"step": step, "lang": language})
            assert response.status_code == 200
            assert f'lang="{language}"' in response.text
            assert 'name="mutation_nonce"' in response.text
            assert 'aria-current="step"' in response.text
            assert 'setup.error.' not in response.text
            assert response.headers["cache-control"] == "no-store"
    assert instance.store.read_config() == before
    assert not instance.store.list_canonical("acquisitions")
    assert not (tmp_path / "setup-progress").exists()


def test_actual_form_trial_apply_and_language_readback_preserve_sentinel(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    client = TestClient(create_app(instance.root, shell_settings_file=tmp_path / "launcher.json"))
    root = tmp_path / "input"
    root.mkdir()
    (root / "sentinel.txt").write_text("Unselected synthetic input")
    response = post(client, "folders", "prepare", source_id="", path=str(root), name="Synthetic",
                    retention="keep")
    assert response.status_code == 200, response.text
    assert len(instance.folder_sources.list_public()) == 1
    assert instance.folder_sources.list_public()[0]["lifecycle_state"] == "paused"
    assert post(client, "space", "save", language="it").status_code == 200
    assert post(client, "ocr", "save", ocr="no", languages="eng").status_code == 200
    assert post(client, "automation", "save", automation="manual").status_code == 200
    response = post(client, "test", "trial")
    assert response.status_code == 200, response.text
    instance.run_scheduler_cycle(max_jobs=1)
    instance.run_scheduler_cycle(max_jobs=1)
    response = post(client, "test", "verify")
    assert response.status_code == 200, response.text
    response = post(client, "summary", "apply")
    assert response.status_code == 200, response.text
    assert '<html lang="it"' in response.text
    assert 'Impostazioni scelte salvate e rilette' in response.text
    assert (root / "sentinel.txt").read_text() == "Unselected synthetic input"
    assert len(instance.store.list_canonical("documents")) == 1
    assert instance.validate_instance()["status"] == "valid", instance.validate_instance()
    # Starting/resuming after closing the browser must reuse the owned trial.
    acquisitions = instance.store.list_canonical("acquisitions")
    for _ in range(2):
        assert client.get("/setup?step=summary").status_code == 200
    assert instance.store.list_canonical("acquisitions") == acquisitions


def test_mutation_requires_local_csrf_one_use_nonce_and_current_revision(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    app = create_app(instance.root, shell_settings_file=tmp_path / "launcher.json")
    client = TestClient(app)
    fields = HiddenFields(client.get("/setup").text).values
    data = {**fields, "action": "save"}
    assert client.post("/setup", data={**data, "csrf_token": "wrong"}).status_code == 403
    assert client.post("/setup", data=data).status_code == 200
    assert client.post("/setup", data=data).status_code == 403
    oversized = client.post("/setup", content=b"x" * 24577,
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert oversized.status_code == 413
    assert TestClient(app, client=("192.0.2.5", 1234)).get("/setup").status_code == 403
