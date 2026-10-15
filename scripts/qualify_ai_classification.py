"""Two real governed native calls on public synthetic text; no accuracy scoring."""

import os

from provelume.ai_contract import digest
from provelume.ai_setup import AiSetup
from provelume.service import ProvelumeInstance


def measure_classification(root, store, runtime):
    instance = ProvelumeInstance.initialise(root / "iudicium-instance")
    setup = AiSetup(instance, runtime_directory=runtime.directory)
    setup.models, setup.runtime = store, runtime
    setup.save({"mode": "local"}, setup.configuration()["revision"])
    result = {"status": "NOT_RUN", "quality": "NOT_EVALUATED", "samples": [],
              "synthetic_content": True, "gold_labels": "NOT_REVIEWED"}
    try:
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
        operation = setup.begin_operation("activate")
        setup.run_operation(operation)
        if setup.operation["state"] != "completed":
            raise ValueError("classification_activation_failed")
        setup.enable()
        area = instance.create_hierarchy_node("area", "Public synthetic Atlas")
        for language, text in (("en", "Public synthetic Atlas workshop on Monday."),
                               ("it", "Seminario pubblico sintetico Atlas di lunedì.")):
            source = root / ("iudicium-source-" + language)
            source.mkdir()
            (source / "note.txt").write_text(text, encoding="utf-8")
            instance.ingest(source)
            # Resolve the source by its acquired text, never by fixture list order.
            document = next(d for d in instance.store.list_canonical("documents")
                            if instance.store.original_bytes(instance.get_document(
                                d["id"])["current_version"]["original_id"]) == text.encode())
            version = instance.get_document(document["id"])["current_version"]["id"]
            bundle = instance.representations.bundles.materialize(
                version, recipe_id="iudicium-public-execution", recipe_version="1",
                recipe_settings={"language": language},
                output_payloads={"text.txt": ("text/plain", text.encode())},
                implementation={"component": "provelume.core", "component_version": "0.12.1",
                                "adapter": "iudicium-public-fixture", "adapter_version": "1",
                                "settings": {}}, anchor_targets=({"kind": "page", "page": 1},),
            )
            before = instance.store.original_bytes(bundle["version"]["original_id"])
            ref, _, _ = setup.classification.preview(
                document["id"], bundle["representation_id"], bundle["outputs"][0]["id"],
                (("area", area["id"]),), language,
            )
            setup.approve_generation(ref)
            job = setup.enqueue(ref)
            terminal = instance.run_ai_job(job["id"])
            sample = {"language": language, "status": terminal["status"],
                      "blocked": terminal["ai"]["blocked"]}
            result["samples"].append(sample)
            body, _, _, _, _ = setup.classification.read(job["id"])
            usage = setup.jobs.status()["accounting"]
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
            })
        result["status"] = "MEASURED"
    except Exception as exc:
        result.update(status="FAIL", failure=type(exc).__name__)
    finally:
        setup.close()
        result.update(worker_absent=not runtime.loaded,
                      final_off=setup.jobs.status()["mode"] == "off")
    return result
