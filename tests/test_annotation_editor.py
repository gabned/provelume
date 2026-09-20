from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from provelume.annotation_model import (
    AnnotationError,
    apply_operations,
    encoded,
    source_segment,
    validate_segments,
)
from provelume.annotation_sources import AnnotationSources
from provelume.annotation_store import (
    AnnotationProvider,
    AnnotationStore,
    annotation_state_findings,
    validate_annotation_record,
)
from provelume.audio_profiles import AudioProfileManager
from provelume.review_decisions import ReviewDecisions
from provelume.review_effects import ReviewConflict
from provelume.review_runtime import review_transaction_factory


def source_rows():
    return [
        source_segment("one", "wrong first", [{"kind": "time", "start_ms": 0, "end_ms": 40}], 0.2),
        source_segment("two", "second", [{"kind": "time", "start_ms": 40, "end_ms": 80}]),
    ]


def test_split_merge_edits_keep_authentic_lineage_and_unknown_confidence():
    source = source_rows()
    split = apply_operations(
        source, [{"kind": "split", "segment": source[0]["id"], "offset": 5}], source
    )
    assert len(split) == 3 and split[0]["anchors"] == split[1]["anchors"] == source[0]["anchors"]
    assert split[0]["lineage"] == split[1]["lineage"] == [source[0]["id"]]
    joined = apply_operations(
        split, [{"kind": "merge", "segment": split[1]["id"], "next": split[2]["id"]}], source
    )
    assert joined[1]["confidence"] is None
    assert joined[1]["anchors"] == source[0]["anchors"] + source[1]["anchors"]
    changed = apply_operations(
        joined,
        [
            {
                "kind": "edit",
                "segment": joined[0]["id"],
                "text": "<script>alert('synthetic')</script>",
            },
            {"kind": "speaker", "segment": joined[0]["id"], "label": "Unverified Alice"},
        ],
        source,
    )
    assert changed[0]["text"].startswith("<script>")
    assert source[0]["text"] == "wrong first" and source[0]["speaker_label"] is None
    validate_segments(changed, source)


@pytest.mark.parametrize("change", ["anchor", "confidence", "lineage", "discard", "unknown_field"])
def test_fabricated_anchor_confidence_or_lineage_is_rejected(change):
    source = source_rows()
    edited = deepcopy(source)
    if change == "anchor":
        edited[0]["anchors"][0]["start_ms"] = 1
    elif change == "confidence":
        edited[1]["confidence"] = 0.99
    elif change == "lineage":
        edited[0]["lineage"] = ["aseg_" + "a" * 64]
    elif change == "discard":
        edited.pop()
    else:
        edited[0]["verified"] = True
    with pytest.raises(AnnotationError):
        validate_segments(edited, source)


def audio_fixture(tmp_path):
    from test_audio_profiles import LowConfidenceAdapter, _seed

    instance, version_id = _seed(tmp_path)
    manager = AudioProfileManager(instance.store, asr_adapter=LowConfidenceAdapter())
    created = manager.create(version_id)
    subject = created["representation_id"]
    provider = AnnotationProvider(instance.store)
    coordinator = ReviewDecisions(
        instance.store,
        [provider],
        authority_resolver=lambda domain, subject, action: {
            "revision": "a" * 64,
            "mode": "confirm-each",
            "scope": {"subject": subject},
            "automatic_allowed": False,
        },
        transaction_factory=review_transaction_factory(instance.store),
        mutation_guard=lambda store: None,
    )
    return instance, manager, subject, provider, coordinator


def confirm(coordinator, plan, request_id):
    return coordinator.confirm(
        plan["domain"],
        plan["subject"],
        plan["action"],
        plan["parameters"],
        expected_plan_revision=plan["plan_revision"],
        expected_authority_revision=plan["authority_revision"],
        request_id=request_id,
    )


def test_real_asr_result_atomic_save_replay_conflict_undo_and_removed_derived_history(tmp_path):
    instance, manager, subject, provider, coordinator = audio_fixture(tmp_path)
    original = instance.store.list_canonical("originals")[0]
    original_before = instance.store.original_bytes(original["id"])
    canonical_before = instance.store.knowledge_fingerprint()
    source = provider.annotations.read(subject)
    assert source["source"]["media"]["kind"] == "audio"
    assert source["segments"][0]["confidence"] == 0.2
    assert source["segments"][0]["anchors"] == [{"kind": "time", "start_ms": 0, "end_ms": 80}]
    retained = instance.store.paths.state / "review" / "annotations"
    assert not retained.exists()
    operations = [
        {"kind": "edit", "segment": source["segments"][0]["id"], "text": "corrected ciao"}
    ]
    plan = coordinator.preview("annotations", subject, "save", {"operations": operations})
    assert not retained.exists(), "Preview must not persist a plan or journal"
    effect = provider.prepare(
        plan,
        request_id="preview-only",
        principal="local_browser",
        recorded_at="2026-09-19T00:00:00Z",
    )
    assert len(effect.writes) == 1 and effect.writes[0].immutable
    assert not retained.exists(), "Provider preparation must perform no IO"
    saved = confirm(coordinator, plan, "annotation-save-one")
    assert saved["replayed"] is False
    assert confirm(coordinator, plan, "annotation-save-one")["replayed"] is True
    with pytest.raises(AnnotationError, match="no annotation changes"):
        confirm(coordinator, plan, "stale-second-tab")
    with pytest.raises(ReviewConflict):
        coordinator.confirm(
            "annotations",
            subject,
            "undo",
            {"revision": 0},
            expected_plan_revision=plan["plan_revision"],
            expected_authority_revision=plan["authority_revision"],
            request_id="annotation-save-one",
        )
    reopened = AnnotationStore(instance.store).read(subject)
    assert reopened["revision"] == 1 and reopened["segments"][0]["text"] == "corrected ciao"
    undo = coordinator.preview("annotations", subject, "undo", {"revision": 0})
    confirm(coordinator, undo, "annotation-undo-one")
    restored = provider.annotations.read(subject)
    assert restored["revision"] == 2 and restored["segments"] == source["segments"]
    assert instance.store.knowledge_fingerprint() == canonical_before
    assert instance.store.original_bytes(original["id"]) == original_before
    history_hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (retained / subject).iterdir()
    }
    manager.remove(subject)
    assert {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (retained / subject).iterdir()
    } == history_hashes
    assert len(provider.annotations.history(subject)["records"]) == 2
    with pytest.raises(AnnotationError):
        provider.annotations.read(subject)
    assert annotation_state_findings(instance.store, deep=True) == []


def test_engine_output_change_denies_confirm_without_creating_history(tmp_path):
    instance, _, subject, provider, coordinator = audio_fixture(tmp_path)
    current = provider.annotations.read(subject)
    plan = coordinator.preview(
        "annotations",
        subject,
        "save",
        {
            "operations": [
                {"kind": "edit", "segment": current["segments"][0]["id"], "text": "corrected"}
            ]
        },
    )
    output = (
        instance.store.paths.state
        / "derived"
        / "representations"
        / subject
        / "outputs"
        / "audio.json"
    )
    original = output.read_bytes()
    output.write_bytes(original + b" ")
    with pytest.raises(AnnotationError):
        confirm(coordinator, plan, "changed-engine")
    assert not (instance.store.paths.state / "review" / "annotations").exists()


def test_ocr_page_region_source_and_unknown_confidence_are_actual_bound_results(tmp_path):
    from test_ocr_execution import _fixture

    instance, manager, _, _, version_id = _fixture(tmp_path)
    queued = manager.queue(version_id, mode="forced", languages=("eng",))
    result = instance.scheduler.run_one(job_id=queued["job"]["id"])
    assert result["status"] == "succeeded"
    bundle = manager.list_bundles(version_id)[0]
    subject = bundle["artifact"]["id"]
    source = AnnotationSources(instance.store).get(subject)
    assert source["kind"] == "ocr" and source["version"]["id"] == version_id
    page = bundle["manifest"]["pages"][0]
    raw = json.loads((instance.store.paths.root / page["result_ref"]).read_bytes())["result"]
    assert source["segments"][0]["text"] == raw["spans"][0]["text"]
    assert source["segments"][0]["confidence"] == raw["spans"][0]["confidence"]
    anchor = source["segments"][0]["anchors"][0]
    assert anchor["page"] == page["page_number"]
    if raw["spans"][0]["box"] is not None:
        assert anchor["kind"] == "region"
        assert anchor["x"] == raw["spans"][0]["box"]["left"]
    assert source["binding"]["result_sha256"] == bundle["artifact"]["checksum"]


def test_unknown_or_future_retained_history_is_not_an_empty_queue(tmp_path):
    instance, _, subject, provider, _ = audio_fixture(tmp_path)
    root = instance.store.paths.state / "review" / "annotations" / subject
    root.mkdir(parents=True)
    (root / "000001.json").write_bytes(encoded({"schema_version": 2}))
    with pytest.raises(AnnotationError):
        provider.annotations.read(subject)
    assert annotation_state_findings(instance.store)


def test_video_asr_segments_resolve_real_time_map_and_original_media(tmp_path):
    from test_video_profiles import _manager, _seed

    instance, version_id = _seed(tmp_path)
    manager = _manager(instance)
    created = manager.create(version_id)
    subject = created["representation_id"]
    source = AnnotationSources(instance.store).get(subject)
    assert source["kind"] == "video" and source["media"]["media_type"] == "video/mp4"
    assert source["segments"]
    profile = manager.get(subject)
    original_segment = profile["record"]["transcript"]["segments"][0]
    assert source["segments"][0]["anchors"] == [
        {
            "kind": "time",
            "start_ms": original_segment["start_ms"],
            "end_ms": original_segment["end_ms"],
        }
    ]
    assert source["segments"][0]["text"] == original_segment["text"]


def test_subtitle_unknown_confidence_does_not_invent_media_or_speaker_identity(tmp_path):
    from test_transcript_jobs import _enabled, _run

    instance, _, source_id = _enabled(tmp_path)
    _, job = _run(instance, source_id)
    assert job["status"] == "succeeded"
    artifact = next(
        row for row in instance.store.list_derived_artifacts() if row["kind"] == "transcript_bundle"
    )
    source = AnnotationSources(instance.store).get(artifact["id"])
    assert source["kind"] == "subtitle" and len(source["segments"]) == 2
    assert all(row["confidence"] is None for row in source["segments"])
    assert source["media"] == {"kind": "unavailable", "media_type": None, "available": False}


def browser_fixture(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from provelume.annotation_activity import attach_annotation_routes
    from provelume.web import TEMPLATES, _context
    from provelume.web_security import LocalWebSecurityMiddleware

    instance, _, subject, provider, coordinator = audio_fixture(tmp_path)
    instance.annotations = provider
    instance.review_decisions = coordinator
    app = FastAPI()
    app.add_middleware(LocalWebSecurityMiddleware)
    attach_annotation_routes(app, instance, TEMPLATES, _context)
    return instance, subject, provider, TestClient(app)


def test_editor_real_routes_origin_nonce_stale_review_and_safe_hostile_text(tmp_path):
    import html
    import re

    from provelume.annotation_activity import annotation_script_integrity

    instance, subject, provider, client = browser_fixture(tmp_path)
    url = f"/review/annotations/{subject}"
    page = client.get(url)
    assert page.status_code == 200
    assert annotation_script_integrity() in page.headers["content-security-policy"]
    assert "script-src 'self'" not in page.headers["content-security-policy"]
    token = html.unescape(re.search(r'data-token="([^"]+)"', page.text)[1])
    model = provider.annotations.read(subject)
    hostile = '<img src=x onerror="alert(1)"><script>evil()</script>'
    payload = {
        "csrf_token": token,
        "action": "save",
        "parameters": {
            "operations": [{"kind": "edit", "segment": model["segments"][0]["id"], "text": hostile}]
        },
    }
    assert client.post(url + "/preview", json=payload).status_code == 403
    assert (
        client.post(
            url + "/preview", json=payload, headers={"Origin": "https://example.invalid"}
        ).status_code
        == 403
    )
    headers = {"Origin": "http://testserver"}
    preview = client.post(url + "/preview", json=payload, headers=headers)
    assert preview.status_code == 200 and preview.json()["mutated"] is False
    assert not (instance.store.paths.state / "review" / "annotations").exists()
    plan = preview.json()
    fields = {
        "csrf_token": token,
        **{key: plan[key] for key in ("plan_revision", "authority_revision", "request_id")},
    }
    saved = client.post(url + "/confirm", json=fields, headers=headers)
    assert saved.status_code == 200
    assert client.post(url + "/confirm", json=fields, headers=headers).status_code == 409
    reopened = client.get(url + "?lang=it")
    assert reopened.status_code == 200 and "Correggi OCR" in reopened.text
    assert hostile not in reopened.text
    assert provider.annotations.read(subject)["segments"][0]["text"] == hostile
    media = client.get(url + "/media")
    assert media.status_code == 200 and media.headers["content-type"] == "audio/wav"
    assert media.content.startswith(b"RIFF")
    assert media.headers["x-content-type-options"] == "nosniff"


def test_annotation_schema_accepts_real_history_and_rejects_unknown_fields(tmp_path):
    from pathlib import Path

    _, _, subject, provider, coordinator = audio_fixture(tmp_path)
    model = provider.annotations.read(subject)
    plan = coordinator.preview(
        "annotations",
        subject,
        "save",
        {
            "operations": [
                {"kind": "speaker", "segment": model["segments"][0]["id"], "label": "Speaker A"}
            ]
        },
    )
    record = json.loads(
        provider.prepare(
            plan,
            request_id="schema-check",
            principal="local_cli",
            recorded_at="2026-09-20T00:00:00Z",
        )
        .writes[0]
        .data
    )
    schema = json.loads(
        (Path(__file__).parents[1] / "core/provelume/annotation_revision.schema.json").read_text()
    )
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(record)
    assert schema["properties"]["schema_version"]["const"] == record["schema_version"]
    assert validate_annotation_record(record) == record
    record["verified_speaker"] = True
    with pytest.raises(AnnotationError):
        validate_annotation_record(record)


def test_browser_session_nonce_is_bound_expiring_and_one_use():
    from fastapi import HTTPException

    from provelume.review_security import ReviewBrowserSessions

    sessions = ReviewBrowserSessions(maximum=2)
    token = sessions.issue("subject")
    plan = {"plan_revision": "a" * 64, "authority_revision": "b" * 64}
    request_id = sessions.retain(token, "subject", plan)
    with pytest.raises(HTTPException):
        sessions.consume(
            token, "other", plan["plan_revision"], plan["authority_revision"], request_id
        )
    assert (
        sessions.consume(
            token, "subject", plan["plan_revision"], plan["authority_revision"], request_id
        )
        == plan
    )
    with pytest.raises(HTTPException):
        sessions.check(token, "subject")
    first, second, third = [sessions.issue("subject") for _ in range(3)]
    with pytest.raises(HTTPException):
        sessions.check(first, "subject")
    sessions.check(second, "subject")
    sessions.sessions[third]["created"] -= 601
    with pytest.raises(HTTPException):
        sessions.check(third, "subject")


@pytest.mark.parametrize("operation", ["materialize", "remove", "rebuild"])
def test_representation_writers_respect_annotation_lifecycle_boundary(tmp_path, operation):
    from provelume.instance_lifecycle import InstanceLifecycleBusy, InstanceLifecycleManager
    from provelume.representations import RepresentationBundleManager
    from provelume.service import ProvelumeInstance

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = RepresentationBundleManager(instance.store)
    with (
        InstanceLifecycleManager(instance.store)._hold(purpose="synthetic-annotation-confirm"),
        pytest.raises(InstanceLifecycleBusy),
    ):
        if operation == "materialize":
            manager.materialize(
                "ver_" + "0" * 32,
                recipe_id="synthetic",
                recipe_version="1",
                recipe_settings={},
                output_payloads={},
                implementation={},
            )
        elif operation == "remove":
            manager.remove("repr_" + "0" * 64)
        else:
            manager.rebuild("repr_" + "0" * 64, {})
    assert not manager.root.exists()


def test_different_stale_tab_cannot_overwrite_saved_annotation(tmp_path):
    from provelume.review_effects import ReviewStale

    _, _, subject, provider, coordinator = audio_fixture(tmp_path)
    segment = provider.annotations.read(subject)["segments"][0]["id"]
    plans = [
        coordinator.preview(
            "annotations",
            subject,
            "save",
            {"operations": [{"kind": "edit", "segment": segment, "text": text}]},
        )
        for text in ("first tab", "second tab")
    ]
    confirm(coordinator, plans[0], "first-tab")
    with pytest.raises(ReviewStale):
        confirm(coordinator, plans[1], "second-tab")
    actual = provider.annotations.read(subject)
    assert actual["revision"] == 1 and actual["segments"][0]["text"] == "first tab"


@pytest.mark.parametrize("change", ["missing_original", "corrupt_original", "recipe"])
def test_missing_original_or_changed_result_binding_denies_save(tmp_path, change):
    from provelume.paths import native_path
    from provelume.review_decisions import checked_path

    instance, _, subject, provider, coordinator = audio_fixture(tmp_path)
    model = provider.annotations.read(subject)
    plan = coordinator.preview(
        "annotations",
        subject,
        "save",
        {"operations": [{"kind": "edit", "segment": model["segments"][0]["id"], "text": "new"}]},
    )
    if change == "recipe":
        path = native_path(
            checked_path(instance.store, f"state/derived/representations/{subject}/bundle.json")
        )
        value = json.loads(path.read_bytes())
        value["recipe"]["settings"]["unexpected"] = "changed"
        path.write_bytes(encoded(value))
    else:
        original = instance.store.list_canonical("originals")[0]
        path = native_path(checked_path(instance.store, original["storage_ref"]))
        if change == "missing_original":
            path.unlink()
        else:
            path.write_bytes(b"corrupt synthetic Original")
    with pytest.raises(ValueError):
        confirm(coordinator, plan, "invalid-evidence")
    assert not (instance.store.paths.state / "review" / "annotations").exists()


def test_editor_inventory_version_filter_preserves_partial_evidence(tmp_path):
    instance, subject, provider, client = browser_fixture(tmp_path)
    version = provider.annotations.read(subject)["source"]["version"]["id"]
    listed = provider.annotations.sources.list(version_id=version)
    assert listed["complete"] is True and [item["id"] for item in listed["items"]] == [subject]
    assert provider.annotations.sources.list(version_id="ver_" + "0" * 32)["items"] == []
    assert subject in client.get("/review/annotations", params={"version_id": version}).text
    assert (
        subject
        not in client.get("/review/annotations", params={"version_id": "ver_" + "0" * 32}).text
    )
    assert client.get("/review/annotations", params={"version_id": "../escape"}).status_code == 400
    invalid = instance.store.paths.derived_artifacts / ("derived_" + "0" * 32 + ".json")
    invalid.parent.mkdir(parents=True, exist_ok=True)
    invalid.write_bytes(b"{broken synthetic record")
    filtered = provider.annotations.sources.list(version_id="ver_" + "0" * 32)
    assert filtered["items"] == [] and filtered["complete"] is False
    assert filtered["count_relation"] == "at_least"
