from __future__ import annotations

import hashlib
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from provelume import operations_maintenance_activity
from provelume.capacity_admission import CapacityAdmission
from provelume.instance_validation import inspect_instance
from provelume.service import ProvelumeInstance
from provelume.web import create_recovery_app


class _Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "form":
            self.current = {"action": attrs.get("action"), "fields": {}}
            self.forms.append(self.current)
        if tag == "input" and self.current is not None and attrs.get("name"):
            self.current["fields"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def _repair_tokens(client):
    page = client.get("/maintenance/repair")
    assert page.status_code == 200 and "Recovery mode" in page.text
    forms = _Forms(page.text).forms
    assert all(form["action"].split("?")[0] != "/maintenance/capacity" for form in forms)
    names = {"csrf_token", "mutation_nonce", "instance_id"}
    form = next(form for form in forms if names <= form["fields"].keys())
    return {name: form["fields"][name] for name in names}


def _snapshot(root):
    return {
        path.relative_to(root).as_posix(): (
            "file" if path.is_file() else "directory",
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        )
        for path in root.rglob("*")
    }


@pytest.fixture
def damaged_instance(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "i")
    seed = tmp_path / "seed.txt"
    seed.write_text("synthetic recovery capacity boundary", encoding="utf-8")
    instance.ingest(seed)
    instance.run_maintenance_action("search.reindex.full")
    run = next((instance.store.paths.state / "maintenance/reindex-runs").glob("*.json"))
    run.with_name("." + run.name + ".synthetic").write_bytes(run.read_bytes())
    assert inspect_instance(instance.root, deep=True)["status"] == "invalid"
    return instance


def test_recovery_repair_tokens_cannot_prepare_capacity_policy(tmp_path, damaged_instance):
    policy = CapacityAdmission(damaged_instance.store)
    current = policy.status()
    before = _snapshot(tmp_path)
    with TestClient(
        create_recovery_app(damaged_instance.root, shell_settings_file=tmp_path / "shell.json")
    ) as client:
        response = client.post(
            "/maintenance/capacity",
            data={**_repair_tokens(client), "mode": "paused", "revision": str(current["revision"])},
        )
        assert response.status_code == 409
        assert not any(
            form["action"].split("?")[0] == "/maintenance/confirm"
            for form in _Forms(response.text).forms
        )
    assert policy.status() == current
    assert not policy.path.exists()
    assert _snapshot(tmp_path) == before


def test_recovery_confirm_rejects_internal_capacity_preview_and_replay(
    tmp_path, damaged_instance, monkeypatch
):
    policy = CapacityAdmission(damaged_instance.store)
    current = policy.status()
    previews = operations_maintenance_activity.ReviewedMaintenancePlans()
    # Inject a genuine stored preview independently of the HTTP preview guard.
    preview_id = previews.put(
        "capacity_policy", {"mode": "paused", "revision": current["revision"]}, {}
    )
    monkeypatch.setattr(
        operations_maintenance_activity, "ReviewedMaintenancePlans", lambda: previews
    )
    before = _snapshot(tmp_path)
    with TestClient(
        create_recovery_app(damaged_instance.root, shell_settings_file=tmp_path / "shell.json")
    ) as client:
        forged = client.post(
            "/maintenance/confirm",
            data={**_repair_tokens(client), "preview_id": "unknown", "confirmed": "yes"},
        )
        assert forged.status_code == 409
        assert _snapshot(tmp_path) == before
        data = {**_repair_tokens(client), "preview_id": preview_id, "confirmed": "yes"}
        rejected = client.post("/maintenance/confirm", data=data)
        assert rejected.status_code == 409
        assert _snapshot(tmp_path) == before
        assert client.post("/maintenance/confirm", data=data).status_code == 409
        renewed = client.post(
            "/maintenance/confirm", data={**data, **_repair_tokens(client)}
        )
        assert renewed.status_code == 409
    assert policy.status() == current
    assert not policy.path.exists()
    assert _snapshot(tmp_path) == before
