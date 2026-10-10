from __future__ import annotations

import pytest

from provelume.ai_contract import digest
from provelume.ai_models import ModelError
from provelume.ai_setup import AiSetup
from provelume.desktop import declare_startup_update_policy, startup_update_policy_enabled
from provelume.service import ProvelumeInstance


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("startup", [False, True])
def test_launcher_declaration_preserves_independent_global_consent(tmp_path, external, startup):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.google_connection.set_network(enabled=external, consent=True)
    before = instance.store.read_config()
    declare_startup_update_policy(instance.root, enabled=startup)
    after = instance.store.read_config()
    assert after == {**before, "network": {
        **before["network"], "update_checks": startup,
        "update_endpoint": "https://api.github.com", "update_data_categories": [],
    }}
    assert startup_update_policy_enabled(instance.root) is (external and startup)


def test_saved_startup_preference_cannot_undo_a_later_global_revocation(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.google_connection.set_network(enabled=True, consent=True)
    declare_startup_update_policy(instance.root, enabled=True)
    assert startup_update_policy_enabled(instance.root)
    instance.google_connection.set_network(enabled=False, consent=True)
    # The launcher makes this same declaration on restart and Instance selection.
    declare_startup_update_policy(instance.root, enabled=True)
    assert instance.store.read_config()["network"]["external_access"] is False
    assert not startup_update_policy_enabled(instance.root)


def test_explicit_model_download_still_requires_global_network_consent(tmp_path, monkeypatch):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    setup = AiSetup(instance)
    calls = []

    def transport(*args, **kwargs):
        calls.append(1)
        raise ModelError("network")

    monkeypatch.setattr("provelume.ai_setup.ArtifactDownload.fetch", transport)
    identity = setup.begin_operation("install")
    setup.run_operation(identity)
    assert setup.operation["state"] == "failed"
    assert setup.operation["error"] == "network"
    assert calls == []
    assert instance.store.read_config()["network"]["external_access"] is False
    instance.google_connection.set_network(enabled=True, consent=True)
    setup.run_operation(setup.begin_operation("install"))
    assert calls == [1]


def test_revocation_during_native_transfer_prevents_publication(tmp_path, monkeypatch):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    setup = AiSetup(instance)
    instance.google_connection.set_network(enabled=True, consent=True)
    chunks = []

    def transport(*args, **kwargs):
        chunks.append(1)
        yield b"GGUF\x03\0\0\0" + b"P" * (65536 - 8)
        instance.google_connection.set_network(enabled=False, consent=True)
        chunks.append(2)
        yield b"P" * 65536
        pytest.fail("revoked transfer continued")

    monkeypatch.setattr("provelume.ai_setup.ArtifactDownload.fetch", transport)
    setup.run_operation(setup.begin_operation("install"))
    assert setup.operation["state"] == "failed"
    assert setup.operation["error"] == "network"
    assert chunks == [1, 2]
    assert not list((setup.models.root / "verified").glob("*.pkg"))
    assert not list((setup.models.root / "staging").iterdir())
    assert not instance.store.read_config()["network"]["external_access"]


def test_explicit_network_setting_is_narrow_stale_checked_and_never_enables_ai(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    setup = AiSetup(instance)
    before = instance.store.read_config()
    revision = digest(before["network"])
    setup.set_network(True, revision)
    after = instance.store.read_config()
    assert after == {**before, "network": {**before["network"], "external_access": True}}
    assert setup.jobs._control()["mode"] == "off" and not setup.jobs.session_authorized
    assert setup.configuration()["mode"] == "off"
    assert setup.operation is None
    with pytest.raises(ValueError, match="ai_setup_stale"):
        setup.set_network(False, revision)
    setup.set_network(False, digest(after["network"]))
    assert instance.store.read_config() == before


def test_ordinary_acquisition_forms_keep_network_and_ai_revisions_separate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from provelume.web import create_app
    from scripts.custodia_ordinary import Page, model_action

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    app = create_app(instance.root)
    calls = []
    monkeypatch.setattr("provelume.ai_setup.ArtifactDownload.fetch",
                        lambda *_args, **_kwargs: calls.append(True))
    with TestClient(app, follow_redirects=False) as client:
        report = {}
        model_action(client, "install", report, expected="failed")
        assert report["operations"]["install"]["error"] == "network"
        assert report["operations"]["install"]["bytes"] == "0"
        assert calls == []
        for enabled in (True, False):
            parsed = Page(client.get("/settings/ai").text)
            form = next(row["fields"] for row in parsed.forms
                        if row["action"] == "/settings/ai/network")
            assert len(form["revision"]) == 64
            assert form["enabled"] == ("yes" if enabled else "no")
            response = client.post("/settings/ai/network", data={
                **form, "acknowledge": "instance-network"})
            assert response.status_code == 303
            assert instance.store.read_config()["network"]["external_access"] is enabled
            assert app.state.ai_setup.configuration()["mode"] == "off"
            assert not app.state.ai_setup.jobs.session_authorized
