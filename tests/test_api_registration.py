from collections import Counter

from fastapi.dependencies import utils
from fastapi.testclient import TestClient

from provelume.service import ProvelumeInstance
from provelume.web import create_app


def test_api_validation_is_built_once_and_apps_keep_independent_instances(tmp_path, monkeypatch):
    builds = Counter()
    original = utils.get_typed_signature

    def observe(call):
        if getattr(call, "__module__", "") == "provelume.api":
            builds[call] += 1
        return original(call)

    monkeypatch.setattr(utils, "get_typed_signature", observe)
    instances, apps = [], []
    for name in ("First", "Second"):
        instance = ProvelumeInstance.initialise(tmp_path / name, name=name)
        app = create_app(instance.root, shell_settings_file=tmp_path / (name + ".json"))
        app.openapi()
        instances.append(instance)
        apps.append(app)

    assert builds and set(builds.values()) == {1}
    assert apps[0].openapi() == apps[1].openapi()
    for instance, app in zip(instances, apps, strict=True):
        with TestClient(app) as client:
            result = client.get("/api/v1/instance")
            assert result.status_code == 200
            assert result.json()["id"] == instance.store.read_config()["instance"]["id"]
            assert result.json()["name"] == instance.store.read_config()["instance"]["name"]
            assert client.get("/api/v1/search", params={"q": "synthetic", "limit": 0}) \
                .status_code == 422
            assert client.get("/api/v1/documents/missing").status_code == 404
            assert client.post("/api/v1/documents", json={}).status_code == 405
            assert client.get("/api/v1/security/installation", params={
                "release_bundle": "forged",
            }).status_code == 400
