from dataclasses import replace
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from provelume import shell_settings
from provelume.catalog_registry import SUPPORTED_LANGUAGES
from provelume.cura_shell import script_integrity
from provelume.service import ProvelumeInstance
from provelume.shell_preference_activity import PreferencePlans
from provelume.shell_preferences import (
    apply_preferences,
    parse_preferences,
    preference_bytes,
    preference_digest,
    preference_payload,
    reset_preview,
)
from provelume.shell_settings import (
    LauncherSettings,
    ShellPreferencesError,
    ShellSettingsManager,
    ShellSettingsStale,
)


def manager(tmp_path):
    selected = ShellSettingsManager(
        tmp_path / "launcher.json",
        LauncherSettings(
            instance_path=str(tmp_path / "synthetic-instance"),
            theme="dark",
            language="ro",
        ),
    )
    selected.save(selected.defaults)
    return selected


@pytest.mark.parametrize("scope", ["appearance_language", "notifications_background", "all"])
def test_reset_undo_preserves_instance_and_unknown_state(tmp_path, scope):
    selected = manager(tmp_path)
    preserved = {}
    for name in (
        "originals/original.bin",
        "sources/source.json",
        "credentials/fake.json",
        "history/job.json",
        "backups/backup.bin",
        "capture/outbox.json",
        "knowledge/provenance.json",
    ):
        marker = tmp_path / "synthetic-instance" / name
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(b"Synthetic preservation fixture; not a real credential")
        preserved[marker] = marker.read_bytes()
    before = selected.load().settings
    plan = reset_preview(before, scope)
    result = apply_preferences(
        selected,
        plan["after"],
        expected_revision=0,
        expected_digest=preference_digest(plan["before"]),
    )
    assert result.instance_path == before.instance_path
    assert {path: path.read_bytes() for path in preserved} == preserved
    undo = apply_preferences(selected, plan["before"], expected_revision=result.revision)
    assert preference_payload(undo) == preference_payload(before)
    assert undo.revision == 2
    assert {path: path.read_bytes() for path in preserved} == preserved


def test_preview_digest_and_revision_refuse_lost_update(tmp_path):
    selected = manager(tmp_path)
    before = selected.load().settings
    plan = reset_preview(before, "all")
    selected.set_preferences(language="de", expected_revision=0)
    with pytest.raises(ShellSettingsStale):
        apply_preferences(selected, plan["after"], expected_revision=0)
    with pytest.raises(ShellPreferencesError, match="changed after preview"):
        apply_preferences(
            selected,
            plan["after"],
            expected_revision=1,
            expected_digest=preference_digest(plan["before"]),
        )
    assert selected.load().settings.language == "de"


def test_failed_atomic_reset_keeps_complete_prior_document(tmp_path, monkeypatch):
    selected = manager(tmp_path)
    before = selected.path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(shell_settings, "_atomic_json", fail)
    with pytest.raises(OSError):
        apply_preferences(
            selected, reset_preview(selected.load().settings, "all")["after"], expected_revision=0
        )
    assert selected.path.read_bytes() == before


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":2,"schema_version":2}',
        b"[]",
        b"{}",
        b"\xff",
        b"x" * 16385,
    ],
)
def test_import_rejects_untrusted_shapes(tmp_path, raw):
    with pytest.raises((ShellPreferencesError, ValueError)):
        parse_preferences(raw, current=manager(tmp_path).defaults)


def test_transfer_is_complete_but_has_no_paths_or_history(tmp_path):
    current = manager(tmp_path).defaults
    payload = preference_payload(replace(current, check_on_start=True, update_channel="stable"))
    encoded = preference_bytes(payload)
    assert str(tmp_path).encode() not in encoded
    assert "instance_path" not in payload
    assert parse_preferences(encoded, current=current) == payload
    payload["credentials"] = "synthetic-invalid-field"
    with pytest.raises(ShellPreferencesError):
        parse_preferences(preference_bytes(payload), current=current)


def test_preview_expiration_and_single_use():
    now = [0.0]
    plans = PreferencePlans(clock=lambda: now[0])
    key = plans.put({"synthetic": True})
    now[0] = 601
    with pytest.raises(ValueError):
        plans.take(key)
    key = plans.put({"synthetic": True})
    assert plans.take(key)["synthetic"]
    with pytest.raises(ValueError):
        plans.take(key)


class Forms(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.rows = []
        self.active = None
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.active = {}
            self.rows.append(self.active)
        if tag == "input" and self.active is not None and attrs.get("type") == "hidden":
            self.active[attrs["name"]] = attrs["value"]

    def handle_endtag(self, tag):
        if tag == "form":
            self.active = None


def test_local_browser_preview_confirm_undo_and_replay(tmp_path):
    from provelume.web import create_app

    selected = manager(tmp_path)
    ProvelumeInstance.initialise(tmp_path / "synthetic-instance", name="Synthetic S09")
    client = TestClient(
        create_app(tmp_path / "synthetic-instance", shell_settings_file=selected.path)
    )
    page = client.get("/settings/preferences?lang=en")
    assert page.status_code == 200
    assert script_integrity() in page.headers["content-security-policy"]
    assert "'unsafe-inline'" not in page.headers["content-security-policy"]
    assert "script-src 'self'" not in page.headers["content-security-policy"]
    fields = next(x for x in Forms(page.text).rows if x["action"] == "preview-reset")
    body = urlencode({**fields, "scope": "appearance_language"})
    headers = {"content-type": "application/x-www-form-urlencoded"}
    preview = client.post("/settings/preferences?lang=en", content=body, headers=headers)
    assert preview.status_code == 200
    assert "<dialog open" in preview.text
    assert "data-preference-cancel autofocus" in preview.text
    assert selected.load().settings.theme == "dark"
    assert client.post("/settings/preferences", content=body, headers=headers).status_code == 409
    fields = Forms(preview.text).rows[0]
    saved = client.post("/settings/preferences?lang=en", content=urlencode(fields), headers=headers)
    assert saved.status_code == 200
    assert selected.load().settings.theme == "system"
    assert selected.load().settings.language == "system"
    undo = Forms(saved.text).rows[0]
    assert undo["action"] == "undo"
    reverted = client.post(
        "/settings/preferences?lang=en", content=urlencode(undo), headers=headers
    )
    assert reverted.status_code == 200
    assert selected.load().settings.language == "ro"
    assert selected.load().settings.theme == "dark"
    exported = client.get("/settings/preferences/export")
    assert exported.status_code == 200 and exported.headers["cache-control"] == "no-store"
    assert str(tmp_path).encode() not in exported.content


@pytest.mark.parametrize("language", sorted(SUPPORTED_LANGUAGES))
@pytest.mark.parametrize("mode", ["current", "preview"])
def test_integrated_journey_pages_keep_language_theme_and_inert_policy(tmp_path, language, mode):
    from provelume.web import create_app

    root = tmp_path / "instance"
    ProvelumeInstance.initialise(root, name="Synthetic S09 integrated pages")
    selected = ShellSettingsManager(
        tmp_path / "launcher.json",
        LauncherSettings(
            instance_path=str(root), schema_version=3, theme="dark", language=language,
            interface_mode=mode
        ),
    )
    selected.save(selected.defaults)
    client = TestClient(create_app(root, shell_settings_file=selected.path))
    for path in (
        "/",
        "/capture",
        "/browse",
        "/inbox",
        "/attention",
        "/maintenance",
        "/settings/preferences",
    ):
        response = client.get(path + "?lang=" + language)
        assert response.status_code == 200, (path, response.text[:200])
        if path == "/capture":
            # Capture's explicit device-local choice is restored by its existing
            # IndexedDB settings, independently of desktop language query links.
            assert '<html lang="en" data-theme="dark"' in response.text
            assert '/capture/shell.js' in response.text
            assert f'<option value="{language}">' in response.text
            continue
        assert f'<html lang="{language}" data-theme="dark"' in response.text
        assert "'unsafe-inline'" not in response.headers["content-security-policy"]
        assert 'id="main-content"' in response.text
        assert "preferences.field." not in response.text


def test_browser_bad_token_and_invalid_import_leave_settings_unchanged(tmp_path):
    from provelume.web import create_app

    selected = manager(tmp_path)
    ProvelumeInstance.initialise(tmp_path / "synthetic-instance", name="Synthetic S09 denial")
    client = TestClient(
        create_app(tmp_path / "synthetic-instance", shell_settings_file=selected.path)
    )
    before = selected.path.read_bytes()
    page = client.get("/settings/preferences?lang=en")
    fields = next(x for x in Forms(page.text).rows if x["action"] == "preview-import")
    headers = {"content-type": "application/x-www-form-urlencoded"}
    bad_token = {**fields, "csrf_token": "synthetic invalid token", "preferences_json": "{}"}
    assert (
        client.post(
            "/settings/preferences", content=urlencode(bad_token), headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/settings/preferences",
            content=urlencode({**fields, "preferences_json": "{}"}),
            headers=headers,
        ).status_code
        == 400
    )
    assert selected.path.read_bytes() == before


def test_remote_host_cannot_read_preferences_or_queue(tmp_path):
    from provelume.web import create_app

    ProvelumeInstance.initialise(tmp_path / "instance", name="Synthetic remote denial")
    client = TestClient(
        create_app(tmp_path / "instance", shell_settings_file=tmp_path / "launcher.json"),
        client=("192.0.2.4", 1234),
    )
    for path in ["/settings/preferences", "/settings/preferences/export", "/api/v1/shell/queue"]:
        assert client.get(path).status_code == 403
