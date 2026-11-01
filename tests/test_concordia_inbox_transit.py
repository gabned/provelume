"""Synthetic acquisition/index/exit journeys, with native Windows race checks."""

import json
import os
import sqlite3
from contextlib import contextmanager

import pytest
from test_concordia_ocr_sources import enable, pdf
from test_concordia_ocr_sources import source_ocr as _source_ocr
from test_review_placement_routing import _bytes, _confirm

from provelume.action_center_model import digest
from provelume.inbox_transit import EXITS, InboxTransitReview, inventory
from provelume.instance_lifecycle import InstanceLifecycleBusy, InstanceLifecycleManager
from provelume.maintenance_local_files import MaintenanceTargetError
from provelume.producer_index_evidence import resolve_index_contribution
from provelume.review_effects import ReviewDenied, ReviewStale, ReviewUnavailable
from provelume.scheduler_model import schedule_payload
from provelume.service import ProvelumeInstance

ocr_inbox = _source_ocr


@pytest.fixture
def inbox(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.rebuild_index()
    source = instance.register_folder_source(root, name="Inbox",
                                              quiescence_seconds=0, stable_observations=1)
    source_id = source["id"]
    plan = instance.review_decisions.preview("capabilities", "inbox_transit", "configure", {
        "mode": "confirm-each", "scope": {"subjects": [source_id],
        "actions": ["release", "save_policy"], "sources": [source_id]},
    })
    _confirm(instance.review_decisions, plan, "grant-inbox")
    return instance, root, source_id


def policy(instance, source_id, mode="transit", request="inbox-policy"):
    plan = instance.review_decisions.preview("inbox_transit", source_id, "save_policy",
                                              {"mode": mode})
    return _confirm(instance.review_decisions, plan, request)


def acquire(inbox, *, before_policy=False, newline=b"\n"):
    instance, root, source_id = inbox
    # Acquire before conversion for the separate backlog permit journey. Future
    # admissions exercise the same exact bytes but only the confirmed policy.
    if not before_policy:
        policy(instance, source_id)
    (root / "note.txt").write_bytes(b"Preserved synthetic searchable input." + newline)
    job = instance.refresh_folder_source(source_id, request_key="ingest")["job"]
    assert job["status"] == "succeeded", job
    if before_policy:
        policy(instance, source_id)
        # A new exact maintenance producer proves the existing Version after conversion.
        p = instance.scheduler.create_policy(
            job_kind="search.reindex", state="disabled",
            scope={"kind": "instance", "id": instance.instance_summary()["id"]},
            schedule=schedule_payload(mode="manual", timezone="UTC"))
        job = instance.scheduler.run_now(p["id"], request_key="backlog-index")["job"]
        job = instance.scheduler.run_one(job_id=job["id"])
        assert job["status"] == "succeeded", job
    acquisition = instance.store.list_canonical("acquisitions")[0]
    return job, acquisition


def preview_exit(instance, source_id, job, acquisition):
    return instance.review_decisions.preview("inbox_transit", source_id, "release", {
        "items": [{"acquisition_id": acquisition["id"], "job_id": job["id"],
                   "producer": "maintenance" if job["job_kind"].startswith("search.")
                   else "processing"}],
    })


def permit_exit(inbox):
    instance, _root, source_id = inbox
    job, acquisition = acquire(inbox, before_policy=True)
    plan = preview_exit(instance, source_id, job, acquisition)
    receipt = _confirm(instance.review_decisions, plan, "exit-backlog")["receipt"]["id"]
    return job, acquisition, receipt


def test_existing_folder_is_keep_and_policy_conversion_does_not_exit_backlog(inbox):
    instance, root, source_id = inbox
    (root / "old.txt").write_text("Previously present input", encoding="utf-8")
    state = instance.inbox_transit.status(source_id)
    assert state["role"] == "folder" and state["mode"] == "keep"
    observer = instance.folder_sources.observer(source_id)
    canonical = _bytes(instance.root / "knowledge")
    receipt = policy(instance, source_id)
    assert receipt["result"]["execution"] is None
    assert (root / "old.txt").exists()
    assert instance.folder_sources.observer(source_id) == observer
    assert _bytes(instance.root / "knowledge") == canonical
    with pytest.raises(ReviewDenied, match="backlog"):
        instance.inbox_transit.release(receipt["receipt"]["id"])


def test_policy_preview_is_read_only_and_changed_backlog_invalidates_confirmation(inbox):
    instance, root, source_id = inbox
    before = _bytes(instance.root)
    plan = instance.review_decisions.preview("inbox_transit", source_id, "save_policy",
                                              {"mode": "transit"})
    assert _bytes(instance.root) == before
    (root / "arrived.txt").write_text("New material after preview", encoding="utf-8")
    with pytest.raises(ReviewStale):
        _confirm(instance.review_decisions, plan, "stale-policy")
    assert instance.inbox_transit_review.policy(source_id) is None


def test_policy_history_rejects_unconfirmed_effective_mode(inbox):
    instance, _root, source_id = inbox
    policy(instance, source_id)
    path = instance.root / f"state/review/inbox_transit/policies/{source_id}.json"
    value = json.loads(path.read_text())
    value["mode"] = "keep"
    path.write_text(json.dumps(value))
    with pytest.raises(ReviewUnavailable):
        instance.inbox_transit_review.policy(source_id)
    assert instance.validate_instance()["status"] == "invalid"


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_future_text_has_exact_source_refresh_proof_and_preserves_original(inbox, newline):
    instance, root, source_id = inbox
    job, acquisition = acquire(inbox, newline=newline)
    proof = resolve_index_contribution(instance.store, "processing", job["id"],
                                        acquisition["document_id"])
    assert proof["profile"] == "native"
    assert proof["receipt_id"] == "receipt_" + job["id"].removeprefix("job_")
    assert instance.store.original_bytes(
        instance.store.read_canonical("versions", acquisition["version_id"])["original_id"]
    ) == b"Preserved synthetic searchable input." + newline
    assert instance.search("synthetic")[0]["version_id"] == acquisition["version_id"]
    assert (root / "note.txt").exists() == (os.name != "nt")
    assert instance.inbox_transit.status(source_id)["mode"] == "transit"
    assert instance.validate_instance()["status"] == "valid"


@pytest.mark.parametrize("change", ["input", "row", "original", "policy", "new_file"])
def test_changed_release_input_or_evidence_retains_copy(inbox, change):
    instance, root, source_id = inbox
    _job, acquisition, receipt = permit_exit(inbox)
    original = instance.store.read_canonical("originals", "sha256_" + acquisition["content_hash"])
    if change == "input":
        (root / "note.txt").write_text("Changed source input", encoding="utf-8")
    elif change == "row":
        with sqlite3.connect(instance.root / "indexes/search.sqlite3") as connection:
            connection.execute("UPDATE search SET content = 'changed'")
    elif change == "original":
        (instance.root / original["storage_ref"]).write_bytes(b"changed original")
    elif change == "new_file":
        (root / "unselected.txt").write_bytes(b"another input")
    else:
        policy(instance, source_id, "keep", "keep-policy")
    with pytest.raises((ReviewDenied, ReviewStale, ReviewUnavailable, ValueError)):
        instance.inbox_transit.release(receipt)
    assert (root / "note.txt").exists()
    assert instance.store.read_canonical("versions", acquisition["version_id"])


def test_revoking_local_authority_blocks_a_previously_confirmed_exit(inbox):
    instance, root, _source_id = inbox
    _job, _acquisition, receipt = permit_exit(inbox)
    plan = instance.review_decisions.preview("capabilities", "inbox_transit", "configure", {
        "mode": "disabled", "scope": {"subjects": [inbox[2]],
        "actions": ["release", "save_policy"], "sources": [inbox[2]]}})
    _confirm(instance.review_decisions, plan, "revoke-inbox")
    with pytest.raises(ReviewDenied):
        instance.inbox_transit.release(receipt)
    assert (root / "note.txt").exists()


def test_keep_mode_has_no_future_admission_and_no_needless_acquisition(inbox):
    instance, root, source_id = inbox
    policy(instance, source_id, "keep")
    (root / "note.txt").write_text("Kept searchable file", encoding="utf-8")
    first = instance.refresh_folder_source(source_id, request_key="keep-one")["job"]
    assert first["status"] == "succeeded"
    canonical = _bytes(instance.root / "knowledge")
    assert instance.refresh_folder_source(source_id, request_key="keep-two")["job"][
        "status"] == "succeeded"
    assert _bytes(instance.root / "knowledge") == canonical
    assert (root / "note.txt").exists()
    assert not (instance.root / "state/inbox-transit/admissions").exists()


def test_unqualified_exit_host_retains_input_and_durable_intent(inbox):
    if os.name == "nt":
        pytest.skip("Unsupported-host refusal is a POSIX boundary")
    instance, root, _source_id = inbox
    _job, _acquisition, receipt = permit_exit(inbox)
    with pytest.raises(MaintenanceTargetError, match="platform_unqualified"):
        instance.inbox_transit.release(receipt)
    assert (root / "note.txt").exists()
    intents = list((instance.root / EXITS).glob("*/intent.json"))
    assert len(intents) == 1
    assert not intents[0].with_name("result.json").exists()


def test_interrupted_exit_without_outcome_never_infers_success_from_absence(inbox, monkeypatch):
    instance, root, _source_id = inbox
    _job, _acquisition, receipt = permit_exit(inbox)

    @contextmanager
    def crash_after_exit(path, expected):
        with path.open("rb") as handle:
            def remove():
                handle.close()
                path.unlink()
                raise OSError("simulated post-exit crash")
            yield handle, remove

    monkeypatch.setattr("provelume.inbox_exit_files.guarded_input_exit", crash_after_exit)
    with pytest.raises((OSError, MaintenanceTargetError)):
        instance.inbox_transit.release(receipt)
    assert not (root / "note.txt").exists()
    with pytest.raises((ReviewStale, MaintenanceTargetError)):
        ProvelumeInstance(instance.root).inbox_transit.release(receipt)
    assert list((instance.root / EXITS).glob("*/intent.json"))
    assert not list((instance.root / EXITS).glob("*/result.json"))


def test_index_writers_share_existing_lifecycle_and_cannot_run_during_exit(inbox):
    from concurrent.futures import ThreadPoolExecutor

    instance, _root, _source_id = inbox
    with InstanceLifecycleManager(instance.store)._hold(purpose="synthetic-exit"):
        # Same thread joins its actual owner; another thread must acquire the lock.
        instance.rebuild_index()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(instance.rebuild_index)
            with pytest.raises(InstanceLifecycleBusy):
                future.result()


def test_input_aliases_and_inventory_limits_fail_closed(inbox, tmp_path):
    instance, root, source_id = inbox
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"must stay")
    try:
        os.link(outside, root / "alias.txt")
    except OSError:
        pytest.skip("Host cannot create hard links")
    with pytest.raises(ReviewDenied):
        policy(instance, source_id)
    assert outside.read_bytes() == b"must stay"


@pytest.mark.skipif(os.name != "nt", reason="Native exclusive Windows input disposition")
def test_windows_exit_is_idempotent_and_blocks_writers_and_parent_rename(inbox):
    from provelume.inbox_exit_files import guarded_input_exit
    from provelume.maintenance_local_files import file_identity

    instance, root, source_id = inbox
    _job, acquisition, receipt = permit_exit(inbox)
    canonical = _bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")
    path = root / "note.txt"
    with path.open("rb") as handle:
        identity = file_identity(handle)
    with guarded_input_exit(path, identity):
        with pytest.raises(OSError):
            path.write_bytes(b"concurrent writer")
        with pytest.raises(OSError):
            path.unlink()
        with pytest.raises(OSError):
            root.rename(root.with_name("replacement"))
    first = instance.inbox_transit.release(receipt)
    assert first[0]["outcome"] == "input_exited"
    assert instance.inbox_transit.release(receipt) == first
    assert not path.exists()
    assert (_bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")) == canonical
    assert instance.store.read_canonical("documents", acquisition["document_id"])
    assert instance.validate_instance()["status"] == "valid"


def test_preview_refuses_unproved_or_foreign_acquisition(inbox):
    instance, root, source_id = inbox
    (root / "note.txt").write_text("No exact producer yet", encoding="utf-8")
    instance.ingest(root)
    policy(instance, source_id)
    acquisition = instance.store.list_canonical("acquisitions")[0]
    with pytest.raises((ReviewDenied, ReviewUnavailable)):
        preview_exit(instance, source_id, {"id": "job_" + "1" * 32,
                                          "job_kind": "processing.execute"}, acquisition)


def test_tampered_exit_intent_blocks_deep_validation(inbox):
    instance, _root, _source_id = inbox
    policy(instance, inbox[2])
    directory = instance.root / EXITS / digest("unknown")
    directory.mkdir(parents=True)
    (directory / "intent.json").write_text(json.dumps({"schema": "untrusted"}))
    report = instance.validate_instance()
    assert report["status"] == "invalid"
    assert any(row["code"] == "inbox_transit_invalid" for row in report["errors"])


def test_fifo_is_refused_without_opening_it(inbox):
    if os.name != "posix":
        pytest.skip("POSIX special-file observation")
    _instance, root, _source_id = inbox
    os.mkfifo(root / "named-pipe")
    with pytest.raises(ReviewDenied):
        inventory(root)


def test_policy_reader_rejects_unknown_closed_fields(inbox):
    instance, _root, source_id = inbox
    assert InboxTransitReview(instance.store).policy(source_id) is None
    with pytest.raises(ReviewDenied):
        instance.review_decisions.preview("inbox_transit", source_id, "save_policy",
                                           {"mode": "transit", "release_backlog": True})


def test_existing_unpreserved_input_is_not_silently_admitted_after_conversion(inbox):
    instance, root, source_id = inbox
    (root / "old.txt").write_text("Preexisting unpreserved input", encoding="utf-8")
    policy(instance, source_id)
    job = instance.refresh_folder_source(source_id, request_key="existing")["job"]
    assert job["status"] == "succeeded"
    assert (root / "old.txt").exists()
    assert not (instance.root / "state/inbox-transit/admissions").exists()


def test_required_ocr_keeps_input_until_its_exact_terminal_index_proof(ocr_inbox):
    instance, root, source_id, _manager, _renderer, _adapter = ocr_inbox
    name = instance.store.read_canonical("sources", source_id)["name"]
    instance.register_folder_source(root, name=name, quiescence_seconds=0, stable_observations=1)
    grant = instance.review_decisions.preview("capabilities", "inbox_transit", "configure", {
        "mode": "confirm-each", "scope": {"subjects": [source_id],
        "actions": ["release", "save_policy"], "sources": [source_id]}})
    _confirm(instance.review_decisions, grant, "inbox-ocr-grant")
    enable(instance, source_id)
    policy(instance, source_id)
    path = root / "new.pdf"
    path.write_bytes(pdf("inbox-ocr"))
    refresh = instance.refresh_folder_source(source_id, request_key="new-pdf")["job"]
    assert refresh["status"] == "succeeded"
    assert path.exists()
    job = next(j for j in instance.scheduler.journal.list_jobs() if j["job_kind"] == "ocr.execute")
    canonical = _bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")
    result = instance.scheduler.run_one(job_id=job["id"])
    assert result["status"] == "succeeded", result
    assert path.exists() == (os.name != "nt")
    assert (root / "old.pdf").exists()
    assert (_bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")) == canonical
    assert instance.search("Page 1 local OCR")
    assert instance.validate_instance()["status"] == "valid"


def test_cli_default_transit_and_source_bound_confirmation(inbox, tmp_path, capsys):
    from provelume.cli import main

    instance, _root, source_id = inbox
    assert main(["inbox-transit-preview", str(instance.root), source_id, "policy"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["parameters"] == {"mode": "transit"}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    assert main(["inbox-transit-confirm", str(instance.root), source_id, str(path),
                 "--request-id", "cli-policy"]) == 0
    capsys.readouterr()
    assert main(["inbox-transit-status", str(instance.root), source_id]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "transit"
    plan["subject"] = "src_" + "1" * 32
    path.write_text(json.dumps(plan))
    assert main(["inbox-transit-confirm", str(instance.root), source_id, str(path),
                 "--request-id", "foreign-policy"]) == 2


def test_unknown_outcome_status_is_read_only_and_does_not_claim_exit(inbox, monkeypatch):
    instance, root, source_id = inbox
    _job, _acquisition, receipt = permit_exit(inbox)

    @contextmanager
    def crash_after_exit(path, expected):
        with path.open("rb") as handle:
            def remove():
                handle.close()
                path.unlink()
                raise OSError("post-disposition interruption")
            yield handle, remove

    monkeypatch.setattr("provelume.inbox_exit_files.guarded_input_exit", crash_after_exit)
    with pytest.raises((OSError, MaintenanceTargetError)):
        instance.inbox_transit.release(receipt)
    before = _bytes(instance.root)
    status = instance.inbox_transit.status(source_id)
    assert status["files_present"] == 0
    assert status["exit_actions"][0]["outcome"] == "outcome_unknown"
    assert _bytes(instance.root) == before
    assert not (root / "note.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows empty directory disposition")
def test_nested_input_exit_removes_only_empty_selected_ancestors(inbox):
    instance, root, source_id = inbox
    policy(instance, source_id)
    nested = root / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "note.txt").write_text("Nested completed input", encoding="utf-8")
    (root / "unrelated-empty").mkdir()
    job = instance.refresh_folder_source(source_id, request_key="nested")["job"]
    assert job["status"] == "succeeded", job
    assert not (root / "one").exists()
    assert (root / "unrelated-empty").is_dir()
    assert root.is_dir()
    assert instance.inbox_transit.status(source_id)["exit_actions"][0]["outcome"] == "input_exited"


def test_backup_and_restore_retain_history_but_cannot_reuse_a_changed_root(inbox, tmp_path):
    instance, _root, source_id = inbox
    policy(instance, source_id)
    target = tmp_path / "backup.zip"
    InstanceLifecycleManager(instance.store).backup(destination=target)
    from provelume.instance_backup import extract_backup

    destination = tmp_path / "restored"
    extract_backup(target, destination)
    restored = ProvelumeInstance(destination)
    assert restored.inbox_transit_review.policy(source_id)["mode"] == "transit"
    assert restored.validate_instance()["status"] == "valid"


@pytest.mark.parametrize("language", ["en", "it", "de", "fr", "es", "pt", "ro"])
@pytest.mark.parametrize("layout", ["preview", "current"])
def test_existing_capability_pages_render_new_scope_in_every_catalog(
    inbox, language, layout, tmp_path,
):
    from fastapi.testclient import TestClient

    from provelume.review_i18n import review_labels
    from provelume.shell_settings import ShellSettingsManager, default_settings
    from provelume.web import create_app

    instance, _root, source_id = inbox
    shell = ShellSettingsManager(tmp_path / "shell.json", default_settings())
    shell.save(default_settings())
    shell.set_interface_mode(layout, expected_revision=0)
    with TestClient(create_app(instance.root, shell_settings_file=shell.path)) as client:
        page = client.get(f"/review/capabilities?lang={language}")
        assert page.status_code == 200
        assert review_labels(language)["inbox_transit"] in page.text
        choices = client.get(
            f"/review/decisions/capabilities/inbox_transit?lang={language}")
        assert choices.status_code == 200
        assert source_id in choices.text


def test_missing_active_index_retains_input_without_scope_escalation(inbox):
    instance, root, source_id = inbox
    policy(instance, source_id)
    (instance.root / "indexes/search.sqlite3").unlink()
    (root / "note.txt").write_text("Needs explicit index recovery", encoding="utf-8")
    job = instance.refresh_folder_source(source_id, request_key="missing-index")["job"]
    assert job["status"] == "succeeded"
    assert not (instance.root / "indexes/search.sqlite3").exists()
    acquisition = instance.store.list_canonical("acquisitions")[0]
    with pytest.raises(ReviewUnavailable):
        resolve_index_contribution(instance.store, "processing", job["id"],
                                     acquisition["document_id"])
    assert (root / "note.txt").exists()


@pytest.mark.parametrize("layout", ["preview", "current"])
@pytest.mark.parametrize("language", ["en", "it"])
def test_busy_cold_search_stays_navigable_without_a_false_zero_count(
    inbox, tmp_path, layout, language, monkeypatch,
):
    from fastapi.testclient import TestClient

    from provelume.i18n import translator
    from provelume.shell_settings import ShellSettingsManager, default_settings
    from provelume.web import create_app

    instance, _root, _source_id = inbox
    (instance.root / "indexes/search.sqlite3").unlink()
    shell = ShellSettingsManager(tmp_path / "shell.json", default_settings())
    shell.save(default_settings())
    shell.set_interface_mode(layout, expected_revision=0)
    app = create_app(instance.root, shell_settings_file=shell.path)
    # Exercise only the deliberately held exit owner, without a startup cycle
    # competing for the same barrier before this controlled assertion begins.
    monkeypatch.setattr(app.state.provelume, "run_scheduler_cycle", lambda **kwargs: None)
    with TestClient(app) as client:
        with InstanceLifecycleManager(instance.store)._hold(purpose="synthetic-input-exit"):
            response = client.get(f"/search?q=synthetic&lang={language}")
            assert response.status_code == 200
            assert translator(language)("search.index_pending") in response.text
            assert translator(language)("search.empty") not in response.text
            assert 'class="cura-result-count"' not in response.text
            assert not (instance.root / "indexes/search.sqlite3").exists()
        response = client.get(f"/search?q=synthetic&lang={language}")
        assert response.status_code == 200
        assert translator(language)("search.index_pending") not in response.text


def test_admission_cannot_fabricate_future_authority_for_an_old_acquisition(inbox):
    instance, _root, source_id = inbox
    _job, acquisition = acquire(inbox, before_policy=True)
    before = _bytes(instance.root)
    fabricated = {**acquisition, "observed_at": "2099-01-01T00:00:00+00:00"}
    with pytest.raises(ReviewDenied):
        instance.inbox_transit.admit(fabricated)
    assert _bytes(instance.root) == before
    assert instance.inbox_transit_review.policy(source_id)["mode"] == "transit"


def test_unusable_input_file_identity_blocks_consent_and_retains_input(inbox, monkeypatch):
    from provelume.maintenance_local_files import file_identity

    instance, root, source_id = inbox
    (root / "note.txt").write_bytes(b"Retain unknown physical identity")
    monkeypatch.setattr("provelume.inbox_transit.file_identity",
                        lambda handle: {**file_identity(handle), "inode": 0})
    with pytest.raises(ReviewDenied, match="physical file identity"):
        policy(instance, source_id)
    assert (root / "note.txt").read_bytes() == b"Retain unknown physical identity"
    assert instance.inbox_transit_review.policy(source_id) is None
