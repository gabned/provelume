from __future__ import annotations

import pytest

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
