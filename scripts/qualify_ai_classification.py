"""Two real governed native calls on public synthetic text; no accuracy scoring."""

import os

from provelume.ai_contract import digest
from provelume.ai_runtime_diagnostics import native_failure, valid_native_failure
from provelume.ai_setup import AiSetup
from provelume.service import ProvelumeInstance
from scripts.iudicium_journey import finish, prepare, review_assessment


def measure_classification(root, store, runtime, *, checkpoint=lambda _result: None):
    instance = ProvelumeInstance.initialise(root / "iudicium-instance")
    setup = AiSetup(instance, runtime_directory=runtime.directory)
    setup.models, setup.runtime = store, runtime
    setup.save({"mode": "local"}, setup.configuration()["revision"])
    result = {"status": "NOT_RUN", "quality": "NOT_EVALUATED", "samples": [],
              "synthetic_content": True, "gold_labels": "NOT_REVIEWED"}

    def stage(name):
        result["stage"] = name
        checkpoint(result)

    try:
        stage("folder_capture_and_reviewed_local_processing")
        cases = prepare(root, instance)
        stage("self_test")
        operation = setup.begin_operation("self_test")
        setup.run_operation(operation)
        if setup.operation["state"] != "completed":
            raise ValueError("classification_self_test_failed")
        if os.name == "nt":
            if (os.environ.get("GITHUB_ACTIONS") != "true"
                    or os.environ.get("S06_WFP_VERIFIED") != "1"):
                raise ValueError("independent_wfp_control_missing")
            # Same independent exact-interpreter OS control as existing S08.
            setup.local_evidence = digest({
                "control": "verified-ci-exact-interpreter-wfp",
                "self_test": setup.self_test_evidence.public_record(),
            })
        stage("activation")
        operation = setup.begin_operation("activate")
        setup.run_operation(operation)
        if setup.operation["state"] != "completed":
            raise ValueError("classification_activation_failed")
        setup.enable()
        area = instance.create_hierarchy_node("area", "Public synthetic Atlas")
        for case in cases:
            language, bundle = case["language"], case["bundle"]
            before = instance.store.original_bytes(bundle["version"]["original_id"])
            ref, _, _ = setup.classification.preview(
                case["document_id"], bundle["representation_id"], bundle["outputs"][0]["id"],
                (("area", area["id"]),), language,
            )
            setup.approve_generation(ref)
            job = setup.enqueue(ref)
            stage("execution")
            terminal = instance.run_ai_job(job["id"])
            if terminal["id"] != job["id"]:
                result.update(status="FAIL", failure="classification_job_identity")
                return result
            sample = {"language": language, "status": terminal["status"],
                      "blocked": terminal["ai"]["blocked"]}
            result["samples"].append(sample)
            if terminal["status"] != "succeeded":
                attempts = terminal["ai"].get("attempts", [])
                observed = attempts[-1].get("native_failure") if attempts else None
                if valid_native_failure(observed):
                    sample["native_failure"] = native_failure(
                        observed, code=observed.get("model_code"),
                        cancellation=observed.get("cancellation_reason"))
                result.update(status="FAIL", failure="classification_job_failed")
                stage("execution_failed")
                return result
            stage("result_read")
            body, _, _, _, _ = setup.classification.read(job["id"])
            usage = setup.jobs.status()["accounting"]
            stage("independent_destination_review")
            reviewed = review_assessment(instance, case, job["id"], body, area["id"])
            stage("discard")
            setup.classification.discard(job["id"])
            retained, _, _ = setup.classification.reference(job["id"])
            sample.update({
                "language": language, "status": terminal["status"],
                "assessment": body["assessment"]["status"],
                "quality": body["classification_quality"], "confidence": body["confidence"],
                "application_authorized": body["automation_authorized"],
                "receipt_bound": retained["status"] == "succeeded",
                "discarded": not setup.classification.path(job["id"]).exists(),
                "source_preserved": before == instance.store.original_bytes(
                    bundle["version"]["original_id"]),
                "accounting_preserved": usage == setup.jobs.status()["accounting"],
                "journey": {**case["journey"], "destination_review": reviewed},
            })
        stage("reopen_and_rebuild")
        setup.close()
        result["journey"] = finish(instance, cases)
        result["status"] = "MEASURED"
    except Exception as exc:
        result.update(status="FAIL", failure=type(exc).__name__)
    finally:
        if result["status"] == "FAIL":
            result["failed_stage"] = result.get("stage")
        result["stage"] = "cleanup"
        setup.close()
        result.update(worker_absent=not runtime.loaded,
                      final_off=setup.jobs.status()["mode"] == "off")
        checkpoint(result)
    return result
