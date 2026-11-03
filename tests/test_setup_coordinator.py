"""K uses real producers, durable partial readback and explicit retry only."""

import asyncio
from copy import deepcopy

import pytest

from provelume.review_effects import ReviewError
from provelume.service import ProvelumeInstance
from provelume.setup_coordinator import SetupCoordinator, assert_admission_ready
from provelume.setup_progress import SetupProgressError
from provelume.setup_trial_http import verify_trial_http
from provelume.shell_settings import ShellSettingsManager, default_settings
from provelume.web import create_app


def prepared_trial(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    shell = ShellSettingsManager(tmp_path / "launcher.json", default_settings())
    coordinator = SetupCoordinator(instance, shell)
    root = tmp_path / "inbox"
    root.mkdir()
    (root / "private-sentinel.txt").write_text("Unselected synthetic existing input")
    coordinator.prepare(0, path=root, name="Synthetic Inbox")
    choices = {**coordinator.defaults(), "retention": "keep", "ocr": False,
               "languages": ["eng"], "automation": "manual", "language": "it"}
    coordinator.start_trial(coordinator.progress.read()["revision"], choices,
                            request_key="coordinator-trial-001")
    instance.run_scheduler_cycle(max_jobs=1)
    instance.run_scheduler_cycle(max_jobs=1)
    op_id = coordinator.progress.read()["operations"]["test"]
    app = create_app(instance.root, shell_settings_file=tmp_path / "launcher.json")
    assert asyncio.run(verify_trial_http(app, instance.store, op_id))["complete"]
    return instance, shell, coordinator, choices


def test_apply_preserves_other_preferences_identity_and_existing_backlog(tmp_path):
    instance, shell, setup, choices = prepared_trial(tmp_path)
    before = shell.load().settings
    canonical_before = {kind: instance.store.list_canonical(kind)
                        for kind in ["sources", "documents", "versions", "originals"]}
    preview = setup.preview(choices)
    setup.apply(setup.progress.read()["revision"], choices=choices,
                preview_revision=preview["revision"])
    assert setup.application()["complete"]
    assert_admission_ready(instance.store, choices["source_id"])
    assert shell.load().settings.language == "it"
    assert shell.load().settings.theme == before.theme
    assert shell.load().settings.endpoint_port == before.endpoint_port
    assert shell.load().settings.tray_enabled == before.tray_enabled
    assert instance.ocr.configured_settings().mode == "disabled"
    assert instance.inbox_transit_review.policy(choices["source_id"])["mode"] == "keep"
    assert instance.ocr_source_review.policy(choices["source_id"]) is None
    assert canonical_before == {
        kind: instance.store.list_canonical(kind) for kind in canonical_before}
    instance.refresh_folder_source(choices["source_id"])
    assert len(instance.store.list_canonical("acquisitions")) == 1
    assert (tmp_path / "inbox/private-sentinel.txt").exists()
    assert instance.validate_instance()["status"] == "valid", instance.validate_instance()
    progress = setup.progress.read()
    text = setup.progress.path.read_text()
    assert str(tmp_path) not in text and "private-sentinel" not in text
    setup.navigate(progress["revision"], "space", discard=True)
    assert setup.progress.read()["operations"] == progress["operations"]
    assert shell.load().settings.language == "it"


@pytest.mark.parametrize("boundary", ["baseline", "activation", "grant_inbox_transit", "inbox",
                                      "shell"])
def test_crash_after_effect_resumes_from_readback(tmp_path, monkeypatch, boundary):
    instance, shell, setup, choices = prepared_trial(tmp_path)
    preview = setup.preview(choices)
    execute = setup._execute_stage
    executed = []

    def crash(plan, intent):
        execute(plan, intent)
        executed.append(intent["kind"])
        if intent["kind"] == boundary:
            raise RuntimeError("Synthetic crash after service effect before coordinator receipt")

    monkeypatch.setattr(setup, "_execute_stage", crash)
    with pytest.raises(RuntimeError):
        setup.apply(setup.progress.read()["revision"], choices=choices,
                    preview_revision=preview["revision"])
    with pytest.raises(ReviewError):
        assert_admission_ready(instance.store, choices["source_id"])
    snapshot = deepcopy(instance.store.read_config())
    reopened = SetupCoordinator(instance, shell)
    assert reopened.application()["pending"] and not reopened.application()["complete"]
    assert instance.store.read_config() == snapshot  # GET/reopen is an observation.
    monkeypatch.setattr(reopened, "_execute_stage", execute)
    reopened.apply(reopened.progress.read()["revision"], choices=choices,
                   preview_revision=preview["revision"])
    assert reopened.application()["complete"]
    assert executed.count(boundary) == 1
    assert len(instance.store.list_canonical("documents")) == 1
    assert shell.load().settings.revision == 1


def test_stale_preview_and_second_tab_cannot_overwrite_new_preferences(tmp_path):
    instance, shell, setup, choices = prepared_trial(tmp_path)
    preview = setup.preview(choices)
    before = deepcopy(instance.store.read_config())
    shell.set_preferences(theme="dark", expected_revision=0)
    with pytest.raises(ReviewError):
        setup.apply(setup.progress.read()["revision"], choices=choices,
                    preview_revision=preview["revision"])
    assert instance.store.read_config() == before
    assert shell.load().settings.theme == "dark" and shell.load().settings.language != "it"
    revision = setup.progress.read()["revision"]
    setup.navigate(revision, "space")
    with pytest.raises(SetupProgressError):
        setup.navigate(revision, "folders")


def test_prepare_crash_reuses_reserved_source_identity_and_one_observer(tmp_path, monkeypatch):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    shell = ShellSettingsManager(tmp_path / "launcher.json", default_settings())
    setup = SetupCoordinator(instance, shell)
    write = instance.store.write_config

    def fail_config(value):
        if value.get("sources"):
            raise RuntimeError("Synthetic crash after Source identity before configuration")
        write(value)

    monkeypatch.setattr(instance.store, "write_config", fail_config)
    with pytest.raises(RuntimeError):
        setup.prepare(0, path=tmp_path / "input", name="Synthetic Inbox")
    reserved = instance.store.list_canonical("sources")
    assert len(reserved) == 1
    monkeypatch.setattr(instance.store, "write_config", write)
    setup.prepare(setup.progress.read()["revision"], path=tmp_path / "input",
                  name="Synthetic Inbox")
    assert instance.store.list_canonical("sources") == reserved
    assert len(instance.folder_sources.list_public()) == 1
    assert len(instance.scheduler.journal.list_policies()) == 1
    assert instance.validate_instance()["status"] == "valid"


def test_trial_crash_before_first_input_resumes_after_session_restart(tmp_path, monkeypatch):
    from provelume import setup_trials

    instance = ProvelumeInstance.initialise(tmp_path / "space")
    shell = ShellSettingsManager(tmp_path / "launcher.json", default_settings())
    setup = SetupCoordinator(instance, shell)
    setup.prepare(0, path=tmp_path / "input", name="Synthetic Inbox")
    choices = {**setup.defaults(), "retention": "keep", "ocr": False, "languages": ["eng"]}
    write = setup_trials.write_local_bytes

    def crash(*args, **kwargs):
        raise RuntimeError("Synthetic crash after durable trial reference before input copy")

    monkeypatch.setattr(setup_trials, "write_local_bytes", crash)
    with pytest.raises(RuntimeError):
        setup.start_trial(setup.progress.read()["revision"], choices,
                          request_key="first-browser-session-001")
    first = setup.progress.read()["operations"]["test"]
    assert not instance.store.list_canonical("acquisitions")
    monkeypatch.setattr(setup_trials, "write_local_bytes", write)
    reopened = SetupCoordinator(instance, shell)
    reopened.start_trial(reopened.progress.read()["revision"], reopened.defaults(),
                         request_key="different-browser-session-002")
    assert reopened.progress.read()["operations"]["test"] == first
    instance.run_scheduler_cycle(max_jobs=1)
    instance.run_scheduler_cycle(max_jobs=1)
    assert len(instance.store.list_canonical("acquisitions")) == 1
    assert instance.validate_instance()["status"] == "valid"


def test_partial_policy_activation_finishes_same_observer_on_explicit_resume(tmp_path, monkeypatch):
    instance, _shell, setup, choices = prepared_trial(tmp_path)
    preview = setup.preview(choices)
    set_state = instance.folder_sources.set_state

    def crash(*args):
        raise RuntimeError("Synthetic crash after scheduler policy before observer state")

    monkeypatch.setattr(instance.folder_sources, "set_state", crash)
    with pytest.raises(RuntimeError):
        setup.apply(setup.progress.read()["revision"], choices=choices,
                    preview_revision=preview["revision"])
    source = instance.folder_sources.public_view(choices["source_id"])
    policy = instance.scheduler.journal.get_policy(source["policy_id"])
    assert source["lifecycle_state"] == "paused" and policy["state"] == "enabled"
    revision = policy["revision"]
    monkeypatch.setattr(instance.folder_sources, "set_state", set_state)
    setup.apply(setup.progress.read()["revision"], choices=choices,
                preview_revision=preview["revision"])
    assert instance.scheduler.journal.get_policy(policy["id"])["revision"] == revision
    assert setup.application()["complete"]


def test_cancelled_trial_is_not_resurrected_by_a_new_browser_submission(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    setup = SetupCoordinator(instance, ShellSettingsManager(tmp_path / "launcher.json",
                                                           default_settings()))
    setup.prepare(0, path=tmp_path / "input", name="Synthetic Inbox")
    choices = {**setup.defaults(), "retention": "keep", "ocr": False, "languages": ["eng"]}
    setup.start_trial(setup.progress.read()["revision"], choices, request_key="cancelled-trial-001")
    job = next(job for job in instance.scheduler.journal._all_jobs()
               if job["job_kind"] == "setup.trial")
    control = instance.scheduler.preview_job_control(job["id"], "cancel")
    instance.scheduler.control_job(job["id"], "cancel", expected_revision=control["revision"],
                                   request_id="cancel_setup_trial_001")
    setup.start_trial(setup.progress.read()["revision"], choices,
                      request_key="new-session-trial-002")
    assert instance.scheduler.journal.get_job(job["id"])["status"] == "cancelled"
    assert len([j for j in instance.scheduler.journal._all_jobs()
                if j["job_kind"] == "setup.trial"]) == 1
    assert not instance.store.list_canonical("acquisitions")


def test_partial_apply_review_preserves_external_preferences(tmp_path, monkeypatch):
    instance, shell, setup, choices = prepared_trial(tmp_path)
    preview = setup.preview(choices)
    execute = setup._execute_stage

    def crash(plan, intent):
        execute(plan, intent)
        if intent["kind"] == "activation":
            raise RuntimeError("Synthetic interrupted Apply")

    monkeypatch.setattr(setup, "_execute_stage", crash)
    with pytest.raises(RuntimeError):
        setup.apply(setup.progress.read()["revision"], choices=choices,
                    preview_revision=preview["revision"])
    shell.set_preferences(theme="dark", expected_revision=0)
    monkeypatch.setattr(setup, "_execute_stage", execute)
    with pytest.raises(ReviewError):
        setup.apply(setup.progress.read()["revision"], choices=choices,
                    preview_revision=preview["revision"])
    setup.pause_and_review(setup.progress.read()["revision"])
    assert shell.load().settings.theme == "dark"
    assert instance.folder_sources.public_view(choices["source_id"])["lifecycle_state"] == "paused"
    assert_admission_ready(instance.store, choices["source_id"])
    setup.start_trial(setup.progress.read()["revision"], choices,
                      request_key="reviewed-fresh-trial-002", fresh=True)
    instance.run_scheduler_cycle(max_jobs=1)
    instance.run_scheduler_cycle(max_jobs=1)
    op_id = setup.progress.read()["operations"]["test"]
    app = create_app(instance.root, shell_settings_file=shell.path)
    assert asyncio.run(verify_trial_http(app, instance.store, op_id))["complete"]
    reviewed = setup.preview(choices)
    setup.apply(setup.progress.read()["revision"], choices=choices,
                preview_revision=reviewed["revision"])
    assert setup.application()["complete"] and shell.load().settings.theme == "dark"
    assert len(instance.store.list_canonical("documents")) == 2
    assert instance.validate_instance()["status"] == "valid"


def test_changed_original_after_apply_never_leaves_a_false_complete_flag(tmp_path):
    instance, _shell, setup, choices = prepared_trial(tmp_path)
    preview = setup.preview(choices)
    setup.apply(setup.progress.read()["revision"], choices=choices,
                preview_revision=preview["revision"])
    assert setup.application()["complete"]
    original = instance.store.list_canonical("originals")[0]
    (instance.root / original["storage_ref"]).write_bytes(b"Changed synthetic Original")
    assert not setup.application()["complete"]
