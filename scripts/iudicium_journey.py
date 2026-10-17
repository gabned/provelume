"""Public synthetic integration mechanics; no classifier quality or human attestation."""

import time
from datetime import UTC, datetime, timedelta

from provelume.ai_contract import digest
from provelume.service import ProvelumeInstance

# Frozen conformance inputs, deliberately not a representative evaluation corpus.
INPUTS = (("en", "Public synthetic Atlas workshop on Monday."),
          ("it", "Seminario pubblico sintetico Atlas di lunedì."))
INPUTS_SHA256 = digest(INPUTS)
ROW_CHECKS = ("managed_source", "default_quiescence", "ai_off_capture",
              "processing_disabled_capture", "original_exact", "three_reviewed_jobs",
              "derived_receipts_local", "scoped_search", "queue_replay")
FINAL_CHECKS = ("source_pause", "refresh_replay", "reopened", "library_rebuilt",
                "index_rebuilt", "originals_preserved", "versions_preserved",
                "ai_receipts_preserved", "accounting_preserved", "ai_off",
                "no_automatic_processing")


def require(value, code):
    if not value:
        raise ValueError(code)


def confirm(instance, domain, subject, action, parameters, request_id):
    """Exercise the existing local CLI review boundary on this synthetic Instance."""
    decisions = instance.review_decisions
    plan = decisions.preview(domain, subject, action, parameters)
    return decisions.confirm(
        domain, subject, action, plan["parameters"],
        expected_plan_revision=plan["plan_revision"],
        expected_authority_revision=plan["authority_revision"],
        request_id=request_id, principal="local_cli",
    )


def policy_parameters(mode):
    return {"mode": mode, "path_prefix": "",
            "operations": ["extract", "index", "representation"], "max_jobs": 3,
            "max_input_bytes": 26214400,
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()
            .replace("+00:00", "Z")}


def prepare(root, instance):
    """Capture with AI/derivation off, then review three exact local jobs per Source."""
    require(instance.ai_jobs.status()["mode"] == "off", "journey_ai_must_start_off")
    accounting = instance.ai_jobs.status()["accounting"]
    # Explicit empty-cache preparation is separate from the narrow processing rule.
    require(instance.rebuild_index() == 0, "journey_requires_empty_instance")
    cases = []
    # Enroll every Source before binding policies to the host configuration revision.
    for language, text in INPUTS:
        folder = root / ("iudicium-source-" + language)
        folder.mkdir()
        (folder / "note.txt").write_text(text, encoding="utf-8")
        source = instance.register_folder_source(folder, name="Public synthetic " + language)
        cases.append({"language": language, "text": text, "source_id": source["id"]})
    sources = sorted(case["source_id"] for case in cases)
    confirm(instance, "capabilities", "processing", "configure", {
        "mode": "confirm-each", "scope": {"subjects": sources, "sources": sources,
        "actions": ["revoke_policy", "run", "save_policy"]}}, "journey-processing-grant")
    for case in cases:
        sid = case["source_id"]
        confirm(instance, "processing", sid, "save_policy", policy_parameters("disabled"),
                "journey-disabled-" + sid)
        require(instance.observe_folder_source(sid)["phase"] == "quiescing",
                "journey_initial_observation")
    # Observe the actual existing five-second quiescence; no lowered setting or fake clock.
    time.sleep(5)
    for case in cases:
        sid = case["source_id"]
        refreshed = instance.refresh_folder_source(sid, request_key="journey-first-" + sid)
        require(refreshed["job"]["status"] == "succeeded", "journey_capture_failed")
        documents = [row for row in instance.list_documents() if row["source_id"] == sid]
        require(len(documents) == 1, "journey_document_identity")
        document = documents[0]
        version = instance.store.read_canonical("versions", document["current_version_id"])
        before = instance.store.original_bytes(version["original_id"])
        require(before == case["text"].encode(), "journey_original_differs")
        require(instance.store.derived_artifact_for_version(version["id"]) is None,
                "journey_inline_derivation")
        require(instance.ai_jobs.status()["mode"] == "off", "journey_capture_enabled_ai")
        observer = instance.folder_sources.observer(sid)
        require(observer["phase"] == "current" and observer["stable_observations"] >= 2,
                "journey_source_not_current")
        confirm(instance, "processing", sid, "save_policy", policy_parameters("confirm-each"),
                "journey-local-rule-" + sid)
        jobs = []
        for operation in ("extract", "representation", "index"):
            approval = confirm(instance, "processing", sid, "run", {
                "version_id": version["id"], "operation": operation,
            }, "journey-permit-" + sid + "-" + operation)["receipt"]["id"]
            queued = instance.processing.queue(sid, version["id"], operation,
                                               permit_receipt=approval)
            replay = instance.processing.queue(sid, version["id"], operation,
                                               permit_receipt=approval)
            require(queued["created"] and not replay["created"]
                    and replay["job"]["id"] == queued["job"]["id"], "journey_queue_replay")
            job = instance.scheduler.run_one(job_id=queued["job"]["id"])
            require(job["status"] == "succeeded", "journey_processing_failed")
            receipt = instance.scheduler.journal.get_receipt("receipt_" + job["id"][4:])
            require(receipt["network_used"] is False and receipt["canonical_mutation"] is False,
                    "journey_processing_receipt")
            jobs.append(job["id"])
        bundle, = instance.representations.bundles.list(version_id=version["id"])
        require(bundle["recipe"]["id"] == "provelume.local-text", "journey_bundle_recipe")
        artifact = instance.store.derived_artifact_for_version(version["id"])
        require(instance.store.read_derived_text(artifact) == case["text"],
                "journey_extracted_text")
        require(instance.ai_jobs.status()["mode"] == "off"
                and instance.ai_jobs.status()["accounting"] == accounting,
                "journey_derivation_enabled_ai")
        require(document["id"] in {d["document_id"] for d in instance.search("Atlas")},
                "journey_search_missing")
        case.update(document_id=document["id"], version_id=version["id"],
                    version_record=version, original_id=version["original_id"],
                    bundle=bundle, jobs=jobs,
                    journey={**dict.fromkeys(ROW_CHECKS, True), "inputs_sha256": INPUTS_SHA256})
    return cases


def review_assessment(instance, case, job_id, body, target_id):
    """Review an actual selection or retain actual abstention without applying it."""
    require(body["classification_quality"] == "NOT_EVALUATED"
            and body["confidence"] is None and body["automation_authorized"] is False,
            "journey_no_quality_authority")
    document = case["document_id"]
    require(instance.hierarchy.get_classification(document) is None,
            "journey_unexpected_placement")
    if body["assessment"]["status"] == "abstained":
        return "NOT_APPLICABLE_ABSTENTION"
    require(body["assessment"]["status"] == "selected"
            and body["assessment"]["target"] == 0, "journey_closed_target")
    confirm(instance, "capabilities", "iudicium", "configure", {
        "mode": "confirm-each", "scope": {"subjects": ["*"], "sources": [],
        "actions": ["apply", "revoke_policy", "save_policy", "undo"]}},
        "journey-classification-grant-" + job_id)
    policy_id = "autonomy_" + job_id[4:]
    confirm(instance, "iudicium", policy_id, "save_policy", {
        "job_id": job_id, "path_prefix": "", "target_ids": [target_id],
        "languages": [case["language"]], "mode": "confirm-each", "max_applications": 1,
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()
        .replace("+00:00", "Z")}, "journey-destination-rule-" + job_id)
    applied = confirm(instance, "iudicium", document, "apply", {
        "job_id": job_id, "policy_id": policy_id, "primary_node_id": target_id,
        "secondary_node_ids": [], "reviewed": True}, "journey-apply-" + job_id)
    require(instance.hierarchy.get_classification(document)["primary_node_id"] == target_id,
            "journey_apply_missing")
    # Projection rebuild while applied must not replace the canonical classification.
    library = instance.rebuild_library()
    require(library["status"] == "completed" and library["canonical_mutation"] == "none"
            and library["network_used"] is False and library["ai_used"] is False,
            "journey_applied_library")
    confirm(instance, "iudicium", policy_id, "revoke_policy", {}, "journey-revoke-" + job_id)
    confirm(instance, "iudicium", document, "undo", {
        "application": applied["receipt"]["id"]}, "journey-undo-" + job_id)
    require(instance.hierarchy.get_classification(document) is None, "journey_undo_differs")
    return "REVIEWED_APPLIED_UNDONE"


def finish(instance, cases):
    """Reopen, pause and refresh unchanged Sources; rebuild only disposable projections."""
    def records(host, kind):
        return digest(sorted(host.store.list_canonical(kind), key=lambda row: row["id"]))

    originals = {case["original_id"]: instance.store.original_bytes(case["original_id"])
                 for case in cases}
    before = {kind: records(instance, kind) for kind in ("originals", "versions", "documents")}
    accounting = instance.ai_jobs.status()["accounting"]
    receipts = {r["id"]: r for r in instance.ai_jobs.journal.list_receipts()}
    reopened = ProvelumeInstance(instance.root)
    require(reopened.ai_jobs.status()["mode"] == "off", "journey_reopened_ai")
    for case in cases:
        sid = case["source_id"]
        reopened.set_folder_source_state(sid, "paused")
        paused = reopened.refresh_folder_source(sid, request_key="journey-paused-" + sid)
        require(paused["job"]["status"] == "succeeded"
                and paused["job"]["progress"]["processed"] == 0, "journey_source_pause")
        reopened.set_folder_source_state(sid, "enabled")
        key = "journey-unchanged-" + sid
        unchanged = reopened.refresh_folder_source(sid, request_key=key)
        replay = reopened.refresh_folder_source(sid, request_key=key)
        require(unchanged["job"]["status"] == "succeeded"
                and unchanged["job"]["progress"]["processed"] == 0
                and replay["job"]["id"] == unchanged["job"]["id"], "journey_refresh_replay")
    library = reopened.rebuild_library()
    require(library["status"] == "completed" and library["canonical_mutation"] == "none"
            and library["network_used"] is False and library["ai_used"] is False,
            "journey_rebuilt_library")
    reopened.rebuild_index()
    require(all(case["document_id"] in {d["document_id"] for d in reopened.search("Atlas")}
                for case in cases), "journey_rebuilt_index")
    require(before == {kind: records(reopened, kind) for kind in before},
            "journey_duplicate_canonical")
    require(all(reopened.store.read_canonical("versions", case["version_id"])
                == case["version_record"] for case in cases), "journey_version_changed")
    require(all(data == reopened.store.original_bytes(oid) for oid, data in originals.items()),
            "journey_original_changed")
    require(reopened.ai_jobs.status()["accounting"] == accounting, "journey_accounting_changed")
    retained = {r["id"]: r for r in reopened.ai_jobs.journal.list_receipts()}
    require(all(retained.get(rid) == row for rid, row in receipts.items()),
            "journey_ai_receipts_changed")
    require(reopened.processing.reconcile_automatic()["queued"] == [],
            "journey_unreviewed_processing")
    return {"status": "MEASURED", "inputs_sha256": INPUTS_SHA256,
            **dict.fromkeys(FINAL_CHECKS, True)}
