"""The real Instance lock must become a safe browser conflict, never a write."""

import re
from copy import deepcopy
from html import unescape

import pytest
from fastapi.testclient import TestClient

from provelume.folder_source_exclusion_i18n import exclusion_message
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.service import ProvelumeInstance
from provelume.web import create_app


@pytest.mark.parametrize("language", ["en", "it"])
def test_exclusion_apply_retains_state_during_real_writer_contention(tmp_path, language):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    folder = tmp_path / "source"
    folder.mkdir()
    (folder / "note.md").write_text("synthetic document", encoding="utf-8")
    source = instance.register_folder_source(folder, name="Rules")
    # This test owns the competing writer explicitly; no background lifespan
    # worker is needed to manufacture or replace the real operating-system lock.
    client = TestClient(create_app(instance.root))
    url = f"/sources/{source['id']}/exclusions?lang={language}"
    page = client.get(url)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    fields = dict(csrf_token=token, action="preview", operation="upsert", revision="1",
                  kind="extension", pattern="md", rule_action="exclude", rule_enabled="true")
    preview = client.post(url, data=fields)
    assert preview.status_code == 200
    fingerprint = re.search(r'name="preview_fingerprint" value="([^"]+)"', preview.text).group(1)
    before = deepcopy(instance.store.read_config())
    with InstanceLifecycleManager(instance.store)._hold(purpose="competing-test-writer"):
        response = client.post(url, data={**fields, "action": "apply",
                                         "preview_fingerprint": fingerprint})
        assert response.status_code == 409
        assert exclusion_message("instance_busy", language) in unescape(response.text)
        assert 'value="md"' in response.text
        assert "Permission denied" not in response.text
        assert instance.store.read_config() == before
        assert instance.store.list_canonical("acquisitions") == []
    assert instance.folder_source_exclusions(source["id"])["policy"]["revision"] == 1
    preview = client.post(url, data=fields)
    assert preview.status_code == 200
    fingerprint = re.search(r'name="preview_fingerprint" value="([^"]+)"', preview.text).group(1)
    response = client.post(url, data={**fields, "action": "apply",
                                     "preview_fingerprint": fingerprint})
    assert response.status_code == 200
    assert instance.folder_source_exclusions(source["id"])["policy"]["revision"] == 2
    assert instance.store.list_canonical("acquisitions") == []
