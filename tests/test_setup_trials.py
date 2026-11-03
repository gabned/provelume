"""Canonical service integration; automatic and installed/manual evidence stay separate."""

import asyncio
import hashlib
import json
from copy import deepcopy

import pytest

from provelume.ocr_jobs import OcrJobManager
from provelume.review_effects import ReviewError
from provelume.service import ProvelumeInstance
from provelume.setup_trial_http import verify_trial_http
from provelume.setup_trials import SetupTrials
from provelume.web import create_app


def test_native_trial_uses_existing_owners_without_source_consent_or_folder_scan(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    folder = tmp_path / "input"
    folder.mkdir()
    (folder / "unrelated-sentinel.txt").write_text("UNSELECTED SYNTHETIC SENTINEL")
    source = instance.register_folder_source(
        folder, name="Synthetic trial", lifecycle_state="paused")
    before = deepcopy(instance.store.read_config())
    trials = SetupTrials(instance.store)
    queued = trials.start(source["id"], retention="keep", ocr_required=False, languages=["eng"],
                          request_key="synthetic-trial-001")
    assert instance.store.list_canonical("acquisitions") == []
    parent = instance.scheduler.run_one(job_id=queued["job"]["id"])
    assert parent["status"] == "succeeded", parent
    acquired = trials.acquisitions(queued["operation_id"])
    assert len(acquired) == 1 and acquired[0] is not None
    child = trials.child(queued["operation_id"], acquired[0])
    assert child is not None and child["status"] == "queued"
    # Let the existing runtime scheduler choose the automatically admitted child;
    # this test never calls the manual OCR command or grants Source-wide consent.
    instance.run_scheduler_cycle(max_jobs=1)
    child = trials.child(queued["operation_id"], acquired[0])
    assert child["status"] == "succeeded", child
    request = OcrJobManager(instance.store)._request_for_job(child)
    assert request["operation"] == "index-only"
    original = instance.document_original(acquired[0]["document_id"])
    assert hashlib.sha256(original["data"]).hexdigest() == acquired[0]["content_hash"]
    assert len(instance.store.list_canonical("acquisitions")) == 1
    assert (folder / "unrelated-sentinel.txt").read_text() == "UNSELECTED SYNTHETIC SENTINEL"
    assert instance.store.read_config() == before
    assert trials.start(source["id"], retention="keep", ocr_required=False, languages=["eng"],
                        request_key="synthetic-trial-001")["job"]["id"] == parent["id"]
    assert trials.observations(queued["operation_id"])["processing_ready"]
    assert not trials.observations(queued["operation_id"])["complete"]
    app = create_app(instance.root, shell_settings_file=tmp_path / "launcher.json",
                     effective_port=8765)
    verified = asyncio.run(verify_trial_http(app, instance.store, queued["operation_id"]))
    assert verified["complete"]
    assert instance.validate_instance()["status"] == "valid", instance.validate_instance()

    async def failed_document(scope, receive, send):
        if scope["path"].startswith("/documents/"):
            await send({"type": "http.response.start", "status": 500, "headers": []})
            await send({"type": "http.response.body", "body": b"Synthetic consultation failure"})
        else:
            await app(scope, receive, send)

    with pytest.raises(ReviewError):
        asyncio.run(verify_trial_http(failed_document, instance.store, queued["operation_id"]))
    assert not trials.observations(queued["operation_id"])["complete"]
    assert instance.store.list_canonical("acquisitions") == acquired
    assert asyncio.run(verify_trial_http(app, instance.store, queued["operation_id"]))["complete"]
    assert [entry["record"]["success"] for entry in trials.probe_history(
        queued["operation_id"])] == [True, False, True]


@pytest.mark.parametrize("corruption", ["oversized", "nested", "foreign", "extra"])
def test_trial_permit_corruption_is_refused_before_acquisition(tmp_path, corruption):
    from provelume.setup_trial_authority import permit_path

    instance = ProvelumeInstance.initialise(tmp_path / "space")
    folder = tmp_path / "input"
    folder.mkdir()
    source = instance.register_folder_source(
        folder, name="Synthetic trial", lifecycle_state="paused")
    trials = SetupTrials(instance.store)
    queued = trials.start(source["id"], retention="keep", ocr_required=False, languages=["eng"],
                          request_key="synthetic-trial-002")
    path = instance.root / permit_path(queued["operation_id"])
    value = json.loads(path.read_text())
    if corruption == "oversized":
        path.write_bytes(b" " * 16385)
    elif corruption == "nested":
        path.write_text('{"x":' + '[' * 1500 + '0' + ']' * 1500 + '}')
    else:
        if corruption == "foreign":
            value["instance_id"] = "inst_" + "0" * 32
        else:
            value["authority"] = "global"
        path.write_text(json.dumps(value))
    with pytest.raises(ReviewError):
        trials.authority.read(queued["operation_id"])
    assert instance.store.list_canonical("acquisitions") == []
