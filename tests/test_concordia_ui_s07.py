"""Real synthetic service readback, separate from human/Windows qualification."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_review_placement_routing import _bytes

from provelume.daily_journeys import document_journey, runtime_state, source_journey
from provelume.service import ProvelumeInstance
from provelume.setup_progress import SetupProgress, SetupProgressError
from provelume.web import create_app


@pytest.fixture
def archive(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = tmp_path / "input"
    source.mkdir()
    registered = instance.register_folder_source(source, name="Synthetic input")
    instance.rebuild_index()
    return instance, source, registered["id"]


def test_keep_counts_distinguish_present_files_from_text_pending_and_do_not_mutate(archive):
    instance, source, source_id = archive
    (source / "first.txt").write_text("Synthetic searchable alpha document.")
    instance.ingest(source)
    (source / "pending.txt").write_text("Synthetic unacquired beta document.")
    original = _bytes(instance.root)
    view = source_journey(instance, instance.folder_sources.public_view(source_id))
    assert view["files_present"] == 2
    assert view["to_complete"] == 1
    assert view["role"] == "folder" and view["mode"] == "keep"
    assert view["automation"] == "manual" and view["runtime"] == "stopped"
    assert view["counts_state"] == "current" and view["ocr_enabled"] is False
    assert _bytes(instance.root) == original
    instance.ingest(source)
    assert source_journey(instance, instance.folder_sources.public_view(source_id))[
        "to_complete"] == 0
    assert len(list(source.iterdir())) == 2


def test_unreadable_or_changed_input_cannot_become_false_zero(archive, monkeypatch):
    instance, source, source_id = archive
    def unavailable(*args):
        raise OSError("synthetic read failure")
    monkeypatch.setattr(instance.inbox_transit, "status", unavailable)
    view = source_journey(instance, instance.folder_sources.public_view(source_id))
    assert view["to_complete"] is None and view["counts_state"] == "attention"


def test_unobserved_nonlocal_source_has_unknown_count_and_retains_observation_time(archive):
    instance, _source, source_id = archive
    source = {**instance.folder_sources.public_view(source_id), "source_class": "network"}
    unobserved = source_journey(instance, source)
    assert unobserved["files_present"] is None and unobserved["counts_state"] == "unknown"
    stamp = "2026-11-02T00:00:00+00:00"
    source["observer"] = {**source["observer"], "file_count": 0, "last_observed_at": stamp}
    observed = source_journey(instance, source)
    assert observed["files_present"] == 0 and observed["files_observed_at"] == stamp
    assert observed["counts_state"] == "observed"


def test_changed_source_configuration_discloses_stale_inbox_policy(archive):
    from test_concordia_inbox_transit import policy
    from test_review_placement_routing import _confirm

    instance, source, source_id = archive
    grant = instance.review_decisions.preview("capabilities", "inbox_transit", "configure", {
        "mode": "confirm-each", "scope": {"subjects": [source_id], "sources": [source_id],
                                          "actions": ["release", "save_policy"]}})
    _confirm(instance.review_decisions, grant, "s07-inbox-grant")
    policy(instance, source_id)
    assert not source_journey(instance, instance.folder_sources.public_view(source_id))[
        "inbox_policy_needs_review"]
    instance.set_folder_source_state(source_id, "paused")
    view = source_journey(instance, instance.folder_sources.public_view(source_id))
    assert view["role"] == "inbox" and view["mode"] == "transit"
    assert view["inbox_policy_needs_review"] is True
    assert view["files_present"] == 0 and view["to_complete"] == 0
    source.rename(source.with_name("disconnected"))
    unavailable = source_journey(instance, instance.folder_sources.public_view(source_id))
    assert unavailable["role"] == "inbox" and unavailable["mode"] == "transit"
    assert unavailable["inbox_policy_needs_review"] is True
    assert unavailable["to_complete"] is None and unavailable["counts_state"] == "attention"


def test_approved_metadata_only_result_is_not_presented_as_body_text(archive):
    from test_concordia_ocr_sources import pdf
    from test_review_placement_routing import _confirm

    instance, source, source_id = archive
    (source / "scan.pdf").write_bytes(pdf("synthetic blank scan"))
    acquisition = instance.ingest(source)[0]
    original_before = _bytes(instance.root / "originals")
    grant = instance.review_decisions.preview("capabilities", "ocr_sources", "configure", {
        "mode": "confirm-each", "scope": {"subjects": [source_id], "sources": [source_id],
                                          "actions": ["limited_result"]}})
    _confirm(instance.review_decisions, grant, "s07-limited-grant")
    limited = instance.review_decisions.preview("ocr_sources", source_id, "limited_result", {
        "version_id": acquisition["version_id"], "profile": "limited-metadata",
        "artifact_id": None})
    receipt = _confirm(instance.review_decisions, limited, "s07-limited-result")
    queued = instance.ocr_sources.backlog(receipt["receipt"]["id"])[0]
    job = instance.scheduler.run_one(job_id=queued["job"]["id"])
    assert job["status"] == "succeeded", job
    document = instance.get_document(acquisition["document_id"])
    view = document_journey(instance, document, instance.document_content(document["id"]))
    assert view["text"] == "metadata" and view["indexed"] is True
    source_view = source_journey(instance, instance.folder_sources.public_view(source_id))
    assert source_view["files_present"] == 1 and source_view["to_complete"] == 1
    assert _bytes(instance.root / "originals") == original_before


def test_changed_ocr_settings_disclose_stale_source_consent(archive):
    from dataclasses import replace

    from test_review_placement_routing import _confirm

    instance, _source, source_id = archive
    grant = instance.review_decisions.preview("capabilities", "ocr_sources", "configure", {
        "mode": "confirm-each", "scope": {"subjects": [source_id], "sources": [source_id],
                                          "actions": ["save_policy"]}})
    _confirm(instance.review_decisions, grant, "s07-ocr-grant")
    selected = instance.review_decisions.preview("ocr_sources", source_id, "save_policy", {
        "enabled": True, "languages": list(instance.ocr.configured_settings().languages)})
    _confirm(instance.review_decisions, selected, "s07-ocr-consent")
    assert not source_journey(instance, instance.folder_sources.public_view(source_id))[
        "ocr_consent_needs_review"]
    instance.configure_ocr(replace(instance.ocr.configured_settings(), render_dpi=200))
    view = source_journey(instance, instance.folder_sources.public_view(source_id))
    assert view["ocr_enabled"] is True and view["ocr_consent_needs_review"] is True


def test_document_reads_actual_text_index_and_materialized_library_separately(archive):
    instance, source, _source_id = archive
    (source / "note.txt").write_text("Synthetic searchable text.")
    acquisition = instance.ingest(source)[0]
    document = instance.get_document(acquisition["document_id"])
    before = _bytes(instance.root)
    view = document_journey(instance, document, instance.document_content(document["id"]))
    assert view["text"] == "native" and view["indexed"] is True
    assert view["library"] == "missing"
    assert _bytes(instance.root) == before


def test_saved_automation_does_not_invent_a_running_runtime():
    app = SimpleNamespace(state=SimpleNamespace())
    assert runtime_state(app) == "stopped"
    app.state.scheduler_runtime_active = True
    assert runtime_state(app) == "active"
    app.state.scheduler_runtime_error = "scheduler_cycle_failed"
    assert runtime_state(app) == "attention"
    app.state.scheduler_runtime_active = False
    assert runtime_state(app) == "stopped"
    app.state.scheduler_runtime_stopping = True
    assert runtime_state(app) == "stopping"


@pytest.mark.parametrize("language", ["en", "it", "de", "fr", "es", "pt", "ro"])
@pytest.mark.parametrize("mode", ["current", "preview"])
def test_daily_pages_render_all_catalogs_without_raw_keys(archive, tmp_path, language, mode):
    from provelume.shell_settings import LauncherSettings, ShellSettingsManager

    instance, source, _source_id = archive
    (source / "note.txt").write_text("Synthetic UI document.")
    document_id = instance.ingest(source)[0]["document_id"]
    manager = ShellSettingsManager(tmp_path / "shell.json", LauncherSettings(
        instance_path=str(instance.root), interface_mode=mode, language=language, schema_version=3))
    manager.save(manager.defaults)
    client = TestClient(create_app(instance.root, shell_settings_file=manager.path))
    for path in ("/inbox", "/sources", "/documents/" + document_id):
        response = client.get(path + "?lang=" + language)
        assert response.status_code == 200, response.text
        assert "journey." not in response.text
        assert '<svg' in response.text and 'aria-hidden="true"' in response.text
    assert not client.app.state.scheduler_runtime_active


def test_progress_is_private_minimal_revision_bound_and_per_instance(tmp_path):
    first = SetupProgress(tmp_path / "launcher.json", "inst_" + "a" * 32)
    second = SetupProgress(tmp_path / "launcher.json", "inst_" + "b" * 32)
    assert first.read()["revision"] == second.read()["revision"] == 0
    assert not first.root.exists()  # GET/read creates no progress or effects.
    applied = {"prepare": "op_" + "c" * 32}
    first.update(expected_revision=0, step="folders", completed=["space"],
                 bindings={"space": "d" * 64}, operations=applied)
    assert second.read()["revision"] == 0
    raw = first.path.read_text()
    assert str(tmp_path) not in raw and "credential" not in raw
    assert "path" not in json.loads(raw)
    with pytest.raises(SetupProgressError, match="stale"):
        first.update(expected_revision=0, step="ocr")
    discarded = first.discard(expected_revision=1)
    assert discarded["completed"] == [] and discarded["operations"] == applied
    assert discarded["revision"] == 2
    assert SetupProgress(tmp_path / "launcher.json", first.instance_id).read() == discarded


@pytest.mark.parametrize("changes", [
    {"step": "unknown"}, {"completed": ["space", "space"]},
    {"operations": {"download": "op_" + "a" * 32}},
    {"operations": {"test": "/private/input.pdf"}},
    {"bindings": {"folders": "private path"}},
])
def test_progress_refuses_unbounded_or_sensitive_payloads(tmp_path, changes):
    progress = SetupProgress(tmp_path / "launcher.json", "inst_" + "a" * 32)
    with pytest.raises(SetupProgressError):
        progress.update(**{"expected_revision": 0, "step": "space", **changes})
    assert not progress.path.exists()


def test_progress_refuses_symlink_storage(tmp_path):
    progress = SetupProgress(tmp_path / "launcher.json", "inst_" + "a" * 32)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    try:
        progress.root.symlink_to(foreign, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("host cannot create a synthetic directory symlink")
    with pytest.raises(SetupProgressError):
        progress.read()
    assert list(Path(foreign).iterdir()) == []


@pytest.mark.parametrize("payload", [b"x" * 8193, b"[" * 2000 + b"]" * 2000,
                                     b'{"revision":0,"revision":1}'])
def test_corrupt_progress_has_a_closed_recoverable_error_without_overwriting_it(tmp_path, payload):
    progress = SetupProgress(tmp_path / "launcher.json", "inst_" + "a" * 32)
    progress.root.mkdir()
    progress.path.write_bytes(payload)
    with pytest.raises(SetupProgressError, match="setup_progress_invalid"):
        progress.read()
    assert progress.path.read_bytes() == payload
