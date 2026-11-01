"""Synthetic Source consent, real scheduler and exact selected-row evidence."""

import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from pypdf import PdfWriter
from test_ocr_execution import FakeAdapter, FakeRenderer, _renderer_capability
from test_review_placement_routing import _bytes, _confirm

from provelume.index_evidence import resolve_ocr_contribution
from provelume.ocr_contract import OcrSettings
from provelume.ocr_jobs import OcrJobManager
from provelume.ocr_selection import selected_text
from provelume.review_effects import ReviewDenied, ReviewUnavailable
from provelume.scheduler_model import SchedulerConflictError
from provelume.service import ProvelumeInstance


def pdf(label, pages=2):
    output = io.BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": label})
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def source_ocr(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "old.pdf").write_bytes(pdf("old"))
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    source_id = instance.list_documents()[0]["source_id"]
    renderer = FakeRenderer(page_count=2)
    adapter = FakeAdapter(_renderer_capability())
    manager = OcrJobManager(instance.store,
                            renderer_factory=lambda s, t: renderer,
                            adapter_factory=lambda s, c, t: adapter)
    manager.configure(OcrSettings(mode="automatic", languages=("eng", "ita")))
    instance.scheduler._ocr_manager_factory = lambda store: manager
    plan = instance.review_decisions.preview("capabilities", "ocr_sources", "configure", {
        "mode": "confirm-each", "scope": {"subjects": [source_id],
        "actions": ["backlog", "limited_result", "revoke_policy", "save_policy"],
        "sources": [source_id]},
    })
    _confirm(instance.review_decisions, plan, "grant-source-ocr")
    return instance, source, source_id, manager, renderer, adapter


def enable(instance, source_id, request="enable-source-ocr"):
    plan = instance.review_decisions.preview("ocr_sources", source_id, "save_policy", {
        "enabled": True, "languages": ["eng", "ita"],
    })
    return _confirm(instance.review_decisions, plan, request)


def test_source_consent_is_future_only_and_does_not_grant_ai_or_change_originals(source_ocr):
    instance, source, source_id, _manager, _renderer, _adapter = source_ocr
    before = _bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")
    enable(instance, source_id)
    assert (_bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")) == before
    assert instance.scheduler.journal.list_jobs() == []
    instance.ingest(source)
    assert instance.scheduler.journal.list_jobs() == []
    (source / "new.pdf").write_bytes(pdf("new"))
    instance.ingest(source)
    jobs = instance.scheduler.journal.list_jobs()
    assert len(jobs) == 1 and jobs[0]["job_kind"] == "ocr.execute"
    instance.ingest(source)
    assert len(instance.scheduler.journal.list_jobs()) == 1


def test_complete_ocr_selected_for_index_and_resolves_exact_terminal_attempt(source_ocr):
    instance, source, source_id, manager, renderer, adapter = source_ocr
    enable(instance, source_id)
    (source / "new.pdf").write_bytes(pdf("new"))
    instance.ingest(source)
    job = instance.scheduler.journal.list_jobs()[0]
    protected = _bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")
    result = instance.scheduler.run_one(job_id=job["id"])
    assert result["status"] == "succeeded", result
    request = manager._request_for_job(result)
    selection, text = selected_text(instance.store, request["version_id"])
    assert text == "Page 1 local OCR\n\nPage 2 local OCR"
    assert renderer.rendered == [1, 2] and adapter.calls == [1, 2]
    proof = resolve_ocr_contribution(instance.store, job["id"])
    assert proof["snapshot"]["selection"] == selection
    assert proof["publication"]["attempt"] == 1
    assert proof["profile"] == "ocr-complete"
    assert (_bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")) == protected
    assert instance.search("local OCR")[0]["version_id"] == request["version_id"]


def test_historical_original_requires_exact_separate_preview_and_is_idempotent(source_ocr):
    instance, _source, source_id, manager, _renderer, _adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    enable(instance, source_id)
    assert instance.scheduler.journal.list_jobs() == []
    plan = instance.review_decisions.preview("ocr_sources", source_id, "backlog",
                                              {"versions": [version]})
    receipt = _confirm(instance.review_decisions, plan, "historical-original")["receipt"]["id"]
    first = instance.ocr_sources.backlog(receipt)
    second = instance.ocr_sources.backlog(receipt)
    assert first[0]["created"] and not second[0]["created"]
    assert first[0]["job"]["id"] == second[0]["job"]["id"]
    assert manager._request_for_job(first[0]["job"])["source_authorization"]["permit"] == receipt
    assert instance.scheduler.run_one(job_id=first[0]["job"]["id"])["status"] == "succeeded"


def test_policy_revocation_blocks_pending_work_without_completing_it(source_ocr):
    instance, source, source_id, _manager, renderer, _adapter = source_ocr
    enable(instance, source_id)
    (source / "new.pdf").write_bytes(pdf("new"))
    instance.ingest(source)
    job = instance.scheduler.journal.list_jobs()[0]
    plan = instance.review_decisions.preview("ocr_sources", source_id, "revoke_policy", {})
    _confirm(instance.review_decisions, plan, "disable-source-ocr")
    result = instance.scheduler.run_one(job_id=job["id"])
    assert result["status"] == "failed"
    assert result["attempts"][-1]["error_code"] == "ocr_contract_violation"
    assert renderer.rendered == []
    with pytest.raises(ReviewUnavailable):
        resolve_ocr_contribution(instance.store, job["id"])


@pytest.mark.parametrize("tamper", ["text", "publication", "row", "original"])
def test_historical_success_cannot_prove_changed_current_contribution(source_ocr, tamper):
    instance, source, source_id, manager, _renderer, _adapter = source_ocr
    enable(instance, source_id)
    (source / "new.pdf").write_bytes(pdf("new"))
    instance.ingest(source)
    job = instance.scheduler.journal.list_jobs()[0]
    result = instance.scheduler.run_one(job_id=job["id"])
    assert result["status"] == "succeeded", result
    request = manager._request_for_job(result)
    proof = resolve_ocr_contribution(instance.store, job["id"])
    if tamper == "publication":
        path = instance.root / "state/processing/index-evidence" / job["id"] / "publication_a1.json"
        value = json.loads(path.read_text())
        value["attempt"] = 2
        path.write_text(json.dumps(value))
    elif tamper == "row":
        import sqlite3

        with sqlite3.connect(instance.root / "indexes/search.sqlite3") as connection:
            connection.execute("UPDATE search SET content = 'different'")
    elif tamper == "original":
        original = instance.store.read_canonical("originals", request["original_id"])
        (instance.root / original["storage_ref"]).write_bytes(b"changed")
    else:
        manifest = manager.list_bundles(request["version_id"])[0]["manifest"]
        (instance.root / manifest["pages"][0]["text_ref"]).write_text("changed")
    assert proof["publication"]["row_sha256"]
    with pytest.raises((ReviewUnavailable, ValueError)):
        resolve_ocr_contribution(instance.store, job["id"])


def test_backlog_rejects_foreign_scope_and_duplicate_versions(source_ocr, tmp_path):
    instance, _source, source_id, _manager, _renderer, _adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    with pytest.raises(ReviewDenied):
        instance.review_decisions.preview("ocr_sources", source_id, "backlog",
                                           {"versions": [version, version]})
    other = tmp_path / "other"
    other.mkdir()
    (other / "other.pdf").write_bytes(pdf("other"))
    instance.ingest(other)
    foreign = next(d for d in instance.list_documents() if d["source_id"] != source_id)
    with pytest.raises(ReviewDenied):
        instance.review_decisions.preview("ocr_sources", source_id, "backlog",
                                           {"versions": [foreign["current_version_id"]]})


def test_preparing_global_ocr_settings_does_not_consent_to_a_source(source_ocr):
    instance, source, source_id, _manager, _renderer, _adapter = source_ocr
    (source / "new.pdf").write_bytes(pdf("new"))
    instance.ingest(source)
    assert instance.ocr_source_review.policy(source_id) is None
    assert instance.scheduler.journal.list_jobs() == []


def historical_job(instance, source_id, version, request="history-permit"):
    plan = instance.review_decisions.preview("ocr_sources", source_id, "backlog",
                                              {"versions": [version]})
    receipt = _confirm(instance.review_decisions, plan, request)["receipt"]["id"]
    return instance.ocr_sources.backlog(receipt)[0]["job"]


def test_reliable_pdf_skips_ocr_components_but_has_exact_native_index_proof(source_ocr):
    from provelume.derived import materialize_extracted_text
    from provelume.extractors import ExtractionResult

    instance, _source, source_id, _manager, renderer, adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    old = instance.store.derived_artifact_for_version(version)
    (instance.store.paths.derived_artifacts / (old["id"] + ".json")).unlink()
    materialize_extracted_text(instance.store, version, ExtractionResult(
        text="Reliable native text identifies the synthetic orchid archive. " * 3,
        generator="pypdf", generator_version="synthetic"))
    job = historical_job(instance, source_id, version)
    result = instance.scheduler.run_one(job_id=job["id"])
    assert result["status"] == "succeeded", result
    assert renderer.rendered == [] and adapter.calls == []
    assert resolve_ocr_contribution(instance.store, job["id"])["profile"] == "embedded"


def test_pause_at_page_boundary_resumes_same_request_and_preserves_partial_work(source_ocr):
    instance, _source, source_id, manager, _renderer, adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    job = historical_job(instance, source_id, version)
    real = adapter.recognise_page

    def pause_once(request, image):
        result = real(request, image)
        if request.source_page.page_number == 1:
            preview = instance.scheduler.preview_job_control(job["id"], "pause")
            instance.scheduler.control_job(job["id"], "pause",
                                             expected_revision=preview["revision"],
                                             request_id="pause-ocr-after-page")
        return result

    adapter.recognise_page = pause_once
    paused = instance.scheduler.run_one(job_id=job["id"])
    assert paused["status"] == "paused" and adapter.calls == [1]
    assert manager.get_run(job["id"])["state"] == "paused"
    with pytest.raises(ReviewUnavailable):
        resolve_ocr_contribution(instance.store, job["id"])
    preview = instance.scheduler.preview_job_control(job["id"], "resume")
    instance.scheduler.control_job(job["id"], "resume", expected_revision=preview["revision"],
                                     request_id="resume-same-ocr")
    completed = instance.scheduler.run_one(job_id=job["id"])
    assert completed["status"] == "succeeded", completed
    assert adapter.calls == [1, 2]
    assert resolve_ocr_contribution(instance.store, job["id"])["publication"]["attempt"] == 2


def test_cancel_is_terminal_and_replaying_same_permit_cannot_restart_it(source_ocr):
    instance, _source, source_id, _manager, renderer, _adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    job = historical_job(instance, source_id, version)
    preview = instance.scheduler.preview_job_control(job["id"], "cancel")
    cancelled = instance.scheduler.control_job(job["id"], "cancel",
                                                expected_revision=preview["revision"],
                                                request_id="cancel-source-ocr")
    assert cancelled["job"]["status"] == "cancelled"
    assert historical_job(instance, source_id, version)["id"] == job["id"]
    assert instance.scheduler.run_one(job_id=job["id"]) is None
    assert renderer.rendered == []
    with pytest.raises(SchedulerConflictError):
        instance.scheduler.preview_job_control(job["id"], "restart")


def test_proof_write_fault_retains_failed_attempt_and_reconciles_current_row(
    source_ocr, monkeypatch,
):
    import provelume.index_evidence as evidence

    instance, _source, source_id, _manager, _renderer, _adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    job = historical_job(instance, source_id, version)
    original = evidence.publish_once

    def interrupted(store, relative, value):
        result = original(store, relative, value)
        if relative.endswith("publication_a1.json"):
            raise OSError("synthetic interruption after final proof publication")
        return result

    monkeypatch.setattr(evidence, "publish_once", interrupted)
    first = instance.scheduler.run_one(job_id=job["id"])
    assert first["status"] == "retry_wait", first
    with pytest.raises(ReviewUnavailable):
        resolve_ocr_contribution(instance.store, job["id"])
    second = instance.scheduler.run_one(job_id=job["id"],
                                        now=datetime.now(UTC) + timedelta(hours=1))
    assert second["status"] == "succeeded", second
    assert second["attempts"][0]["outcome"] == "retry"
    proof = resolve_ocr_contribution(instance.store, job["id"])
    assert proof["publication"]["mode"] == "reconciled_current_state"
    assert proof["publication"]["actor"] is None
    assert proof["publication"]["recorded_at"] is None
    directory = instance.root / "state/processing/index-evidence" / job["id"]
    assert (directory / "publication_a1.json").is_file()
    (directory / "publication_a2.json").unlink()
    with pytest.raises(ReviewUnavailable):
        resolve_ocr_contribution(instance.store, job["id"])


def test_limited_metadata_requires_exact_acceptance_and_never_claims_no_text(source_ocr):
    instance, _source, source_id, _manager, renderer, adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    plan = instance.review_decisions.preview("ocr_sources", source_id, "limited_result", {
        "version_id": version, "profile": "limited-metadata", "artifact_id": None,
    })
    receipt = _confirm(instance.review_decisions, plan, "accept-limited-metadata")
    selection, text = selected_text(instance.store, version)
    assert text == "" and selection["acceptance"] == receipt["receipt"]["id"]
    job = historical_job(instance, source_id, version)
    completed = instance.scheduler.run_one(job_id=job["id"])
    assert completed["status"] == "succeeded", completed
    proof = resolve_ocr_contribution(instance.store, job["id"])
    assert proof["profile"] == "limited-metadata"
    assert proof["snapshot"]["selection"]["text_sha256"]
    assert renderer.rendered == [] and adapter.calls == []


def test_deep_validation_and_read_only_resolution_preserve_historical_evidence(source_ocr):
    from provelume.index_evidence import index_evidence_state_findings

    instance, _source, source_id, _manager, _renderer, _adapter = source_ocr
    job = historical_job(instance, source_id, instance.list_documents()[0]["current_version_id"])
    assert instance.scheduler.run_one(job_id=job["id"])["status"] == "succeeded"
    before = _bytes(instance.root)
    resolve_ocr_contribution(instance.store, job["id"])
    assert index_evidence_state_findings(instance.store) == []
    assert _bytes(instance.root) == before
    root = instance.root / "state/processing/index-evidence" / job["id"]
    (root / "publication_a9.json").write_text("{}")
    assert index_evidence_state_findings(instance.store)[0]["code"] == "index_evidence_invalid"


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
@pytest.mark.parametrize("interface", ["current", "preview"])
def test_local_source_review_renders_translated_choices_and_queues_only_confirmed_scope(
    source_ocr, monkeypatch, tmp_path, language, interface,
):
    from fastapi.testclient import TestClient
    from test_review_decision_routes import _confirm as browser_confirm
    from test_review_decision_routes import _preview, _token

    from provelume.shell_settings import ShellSettingsManager, default_settings
    from provelume.web import create_app

    instance, _source, source_id, _manager, _renderer, _adapter = source_ocr
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "shell"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "shell"))
    version = instance.list_documents()[0]["current_version_id"]
    path = "/review/decisions/ocr_sources/" + source_id
    shell = ShellSettingsManager(tmp_path / "shell.json", default_settings())
    shell.save(default_settings())
    shell.set_interface_mode(interface, expected_revision=0)
    with TestClient(create_app(instance.root, shell_settings_file=shell.path)) as client:
        before = _bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")
        response = client.get(path + "?lang=" + language)
        assert response.status_code == 200, response.text
        assert 'name="versions" multiple' in response.text
        assert 'name="enabled" type="checkbox"' in response.text
        assert "review.ocr_sources" not in response.text
        token = _token(client, path)
        preview = _preview(client, path, token, "backlog", {"versions": [version]})
        assert preview.status_code == 200, preview.text
        assert instance.scheduler.journal.list_jobs() == []
        result = browser_confirm(client, path, token, preview)
        assert result.status_code == 200, result.text
        assert len(result.json()["ocr_jobs"]) == 1
        assert browser_confirm(client, path, token, preview).status_code == 409
        hostile = client.post(path + "/preview", json={"csrf_token": token, "action": "backlog",
                                                       "parameters": {"versions": [version]}},
                              headers={"Origin": "https://example.invalid"})
        assert hostile.status_code == 403
        assert (_bytes(instance.root / "knowledge"), _bytes(instance.root / "originals")) == before


def test_backup_preserves_final_history_and_restore_invalidates_old_applicability(
    source_ocr, tmp_path,
):
    from provelume.index_evidence import index_evidence_state_findings

    instance, _source, source_id, _manager, _renderer, _adapter = source_ocr
    job = historical_job(instance, source_id, instance.list_documents()[0]["current_version_id"])
    assert instance.scheduler.run_one(job_id=job["id"])["status"] == "succeeded"
    before = _bytes(instance.root / "state/processing/index-evidence")
    result = instance.backup(destination=tmp_path / "source-ocr.zip")
    assert result
    instance.restore(tmp_path / "source-ocr.zip")
    assert _bytes(instance.root / "state/processing/index-evidence") == before
    assert index_evidence_state_findings(instance.store) == []
    with pytest.raises(ReviewUnavailable):
        resolve_ocr_contribution(instance.store, job["id"])


def test_selection_scope_reaches_1000_versions_without_global_500_document_inventory(
    source_ocr, monkeypatch,
):
    from uuid import uuid4

    from provelume.ocr_sources import MAX_BACKLOG_VERSIONS, source_pdf_choices
    from provelume.review_routing import _Inputs

    instance, _source, source_id, _manager, _renderer, _adapter = source_ocr
    document = instance.list_documents()[0]
    version = instance.store.read_canonical("versions", document["current_version_id"])
    ids = [version["id"]]
    # Synthetic canonical metadata shares an actual immutable Original. This
    # checks real direct record/byte authority, not a mocked enumeration count.
    for _ in range(MAX_BACKLOG_VERSIONS - 1):
        document_id, version_id = "doc_" + uuid4().hex, "ver_" + uuid4().hex
        instance.store._atomic_json(instance.root / "knowledge/documents" / (document_id + ".json"),
                                    {**document, "id": document_id,
                                     "current_version_id": version_id})
        instance.store._atomic_json(instance.root / "knowledge/versions" / (version_id + ".json"),
                                    {**version, "id": version_id, "document_id": document_id})
        ids.append(version_id)
    original_inventory = _Inputs.inventory

    def no_global_document_inventory(self, relative, maximum):
        assert relative != "knowledge/documents"
        return original_inventory(self, relative, maximum)

    monkeypatch.setattr(_Inputs, "inventory", no_global_document_inventory)
    plan = instance.review_decisions.preview("ocr_sources", source_id, "backlog", {"versions": ids})
    rows = plan["provider"]["execution"]["versions"]
    assert len(rows) == MAX_BACKLOG_VERSIONS and {r["version_id"] for r in rows} == set(ids)
    assert sum(r["size_bytes"] for r in rows) == version["size_bytes"] * MAX_BACKLOG_VERSIONS
    assert len(source_pdf_choices(instance.store, source_id)) == MAX_BACKLOG_VERSIONS
    with pytest.raises(ReviewDenied):
        instance.review_decisions.preview("ocr_sources", source_id, "backlog",
                                           {"versions": ids + ["ver_" + uuid4().hex]})


@pytest.mark.parametrize("producer", ["maintenance", "processing"])
def test_other_index_producers_preserve_complete_ocr_and_publish_their_own_exact_proof(
    source_ocr, producer,
):
    from provelume.producer_index_evidence import resolve_index_contribution
    from provelume.scheduler_model import schedule_payload

    instance, _source, source_id, _manager, _renderer, _adapter = source_ocr
    document = instance.list_documents()[0]
    job = historical_job(instance, source_id, document["current_version_id"])
    assert instance.scheduler.run_one(job_id=job["id"])["status"] == "succeeded"
    if producer == "maintenance":
        policy = instance.scheduler.create_policy(
            job_kind="search.reindex", state="disabled",
            scope={"kind": "instance", "id": instance.instance_summary()["id"]},
            schedule=schedule_payload(mode="manual", timezone="UTC"))
        job = instance.scheduler.run_now(policy["id"], request_key="reindex-selected-ocr")["job"]
    else:
        from test_processing_autonomy import grant, permit, policy, queue

        grant(instance, source_id)
        policy(instance, source_id)
        receipt = permit(instance, document, "index")
        job = queue(instance, document, "index", permit_receipt=receipt)["job"]
    result = instance.scheduler.run_one(job_id=job["id"])
    assert result["status"] == "succeeded", result
    before = _bytes(instance.root)
    proof = resolve_index_contribution(instance.store, producer, job["id"], document["id"])
    assert proof["profile"] == "ocr-complete"
    assert _bytes(instance.root) == before
    assert instance.search("local OCR")[0]["version_id"] == document["current_version_id"]
    from provelume.index_evidence import index_evidence_state_findings

    assert index_evidence_state_findings(instance.store) == []
    directory = instance.root / f"state/{producer}/index-evidence" / job["id"]
    (directory / "publication_a1.json").unlink()
    with pytest.raises(ReviewUnavailable):
        resolve_index_contribution(instance.store, producer, job["id"], document["id"])


def test_uncertain_complete_ocr_blocks_until_that_bundle_is_explicitly_accepted(source_ocr):
    from dataclasses import replace

    instance, _source, source_id, manager, _renderer, adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    real = adapter.recognise_page
    adapter.recognise_page = lambda request, image: replace(
        real(request, image), text_status="needs-review")
    job = historical_job(instance, source_id, version)
    first = instance.scheduler.run_one(job_id=job["id"])
    assert first["status"] == "failed", first
    assert selected_text(instance.store, version) is None
    with pytest.raises(ReviewUnavailable):
        resolve_ocr_contribution(instance.store, job["id"])
    artifact = manager.list_bundles(version)[0]["artifact"]
    plan = instance.review_decisions.preview("ocr_sources", source_id, "limited_result", {
        "version_id": version, "profile": "ocr-accepted", "artifact_id": artifact["id"],
    })
    accepted = _confirm(instance.review_decisions, plan, "accept-exact-uncertain-bundle")
    selected, text = selected_text(instance.store, version)
    assert selected["acceptance"] == accepted["receipt"]["id"]
    assert text == "Page 1 local OCR\n\nPage 2 local OCR"
    queued = instance.ocr_sources.backlog(accepted["receipt"]["id"])[0]["job"]
    result = instance.scheduler.run_one(job_id=queued["id"])
    assert result["status"] == "succeeded", result
    assert resolve_ocr_contribution(instance.store, queued["id"])["profile"] == "ocr-accepted"


def test_partial_bundle_cannot_be_selected_as_complete_source_text(source_ocr):
    from provelume.ocr_selection import bundle_selection

    instance, _source, _source_id, manager, _renderer, _adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    queued = manager.queue(version, mode="selected-page", pages=[1])
    result = instance.scheduler.run_one(job_id=queued["job"]["id"])
    assert result["status"] == "succeeded", result
    artifact = manager.list_bundles(version)[0]["artifact"]
    with pytest.raises(ReviewUnavailable, match="complete bound PDF"):
        bundle_selection(instance.store, version, artifact, acceptance="preview-only")


def test_empty_ocr_never_becomes_complete_or_accepted_search_text(source_ocr):
    from dataclasses import replace

    instance, _source, source_id, manager, _renderer, adapter = source_ocr
    version = instance.list_documents()[0]["current_version_id"]
    real = adapter.recognise_page
    adapter.recognise_page = lambda request, image: replace(
        real(request, image), text="", spans=())
    job = historical_job(instance, source_id, version)
    result = instance.scheduler.run_one(job_id=job["id"])
    assert result["status"] == "failed", result
    assert selected_text(instance.store, version) is None
    artifact = manager.list_bundles(version)[0]["artifact"]
    with pytest.raises(ReviewUnavailable, match="Empty OCR"):
        instance.review_decisions.preview("ocr_sources", source_id, "limited_result", {
            "version_id": version, "profile": "ocr-accepted", "artifact_id": artifact["id"],
        })
