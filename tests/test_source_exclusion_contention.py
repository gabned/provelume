"""The real Instance lock must become a safe browser conflict, never a write."""

import re
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from provelume.folder_source_exclusion_i18n import exclusion_message
from provelume.folder_source_exclusions import propose_change
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.service import ProvelumeInstance
from provelume.web import create_app


class Forms(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.forms = []
        self.current = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"id": attrs.get("id"), "fields": {}}
            self.forms.append(self.current)
        elif tag == "input" and self.current is not None and "name" in attrs:
            self.current["fields"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


@pytest.mark.parametrize("language", ["en", "it"])
@pytest.mark.parametrize(
    "operation", ["add", "add_disabled", "edit", "state", "remove", "defaults"]
)
def test_exclusion_apply_retains_state_during_real_writer_contention(tmp_path, language, operation):
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
    policy = instance.folder_source_exclusions(source["id"])["policy"]
    if operation == "add_disabled":
        fields.update(rule_enabled="false", rule_action="include")
    elif operation == "edit":
        fields.update(rule_id=policy["rules"][0]["id"], pattern="txt",
                      rule_enabled="false", rule_action="include")
    elif operation == "state":
        fields = dict(csrf_token=token, action="preview", operation="state", revision="1",
                      enabled="false")
    elif operation == "remove":
        fields = dict(csrf_token=token, action="preview", operation="remove", revision="1",
                      rule_id=policy["rules"][0]["id"])
    elif operation == "defaults":
        fields = dict(csrf_token=token, action="preview", operation="defaults", revision="1")
    expected = propose_change(policy, fields)
    preview = client.post(url, data=fields)
    assert preview.status_code == 200
    fingerprint = re.search(r'name="preview_fingerprint" value="([^"]+)"', preview.text).group(1)
    before = deepcopy(instance.store.read_config())
    with InstanceLifecycleManager(instance.store)._hold(purpose="competing-test-writer"):
        response = client.post(url, data={**fields, "action": "apply",
                                         "preview_fingerprint": fingerprint})
        assert response.status_code == 409
        assert exclusion_message("instance_busy", language) in unescape(response.text)
        retry = next(form["fields"] for form in Forms(response.text).forms
                     if form["id"] == "exclusion-conflict-retry")
        assert retry == fields
        assert "preview_fingerprint" not in retry
        assert not any(form["fields"].get("action") == "apply"
                       for form in Forms(response.text).forms)
        assert "Permission denied" not in response.text
        assert instance.store.read_config() == before
        assert instance.store.list_canonical("acquisitions") == []
    assert instance.folder_source_exclusions(source["id"])["policy"]["revision"] == 1
    # Submit the actual returned browser form, not the original test payload.
    preview = client.post(url, data=retry)
    assert preview.status_code == 200
    apply = next(form["fields"] for form in Forms(preview.text).forms
                 if form["fields"].get("action") == "apply")
    response = client.post(url, data=apply)
    assert response.status_code == 200
    assert instance.folder_source_exclusions(source["id"])["policy"] == expected
    assert instance.store.list_canonical("acquisitions") == []
