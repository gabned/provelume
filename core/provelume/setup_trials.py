"""Synthetic setup intake through the existing ingestion/OCR/Inbox/scheduler owners."""

import hashlib
import re
import sqlite3
from dataclasses import asdict, replace
from datetime import datetime
from importlib.resources import files

from .action_center_model import digest
from .inbox_transit import _source
from .index_evidence import publish_once
from .instance_lifecycle import InstanceLifecycleManager
from .maintenance_local_files import open_local_directory, open_local_file, write_local_bytes
from .ocr_contract import OcrContractError, ocr_settings_from_config, require_ocr_available
from .operations import OperationLedger
from .review_decisions import checked_path, read_json
from .review_effects import ReviewConflict, ReviewDenied, ReviewUnavailable
from .scheduler_model import idempotency_digest, schedule_payload
from .setup_trial_authority import (
    ROOT,
    SetupTrialAuthority,
    acquisition_id,
    ingestion_run_id,
    operation_id,
    permit_path,
    read_record,
)
from .setup_trial_inputs import FIXTURES, ROOT_ID, observe_selection

JOB_KIND = "setup.trial"


class SetupTrials:
    def __init__(self, store):
        self.store = store
        self.authority = SetupTrialAuthority(store)

    def _policy(self, source_id):
        from .scheduler import SchedulerStore

        journal = SchedulerStore(self.store)
        existing = [p for p in journal.list_policies() if p["job_kind"] == JOB_KIND
                    and p["scope"] == {"kind": "source", "id": source_id}]
        if len(existing) > 1:
            raise ReviewUnavailable("Another scheduler policy owns this trial Source")
        return existing[0] if existing else journal.create_policy(
            job_kind=JOB_KIND, scope={"kind": "source", "id": source_id}, state="disabled",
            schedule=schedule_payload(mode="manual", timezone="UTC"))

    def start(self, source_id, *, retention, ocr_required, languages, request_key,
              principal="local_browser"):
        with InstanceLifecycleManager(self.store)._hold(purpose="setup-trial-submit"):
            return self.start_locked(source_id, retention=retention, ocr_required=ocr_required,
                                     languages=languages, request_key=request_key,
                                     principal=principal)

    def start_locked(self, source_id, *, retention, ocr_required, languages, request_key,
              principal="local_browser", _on_operation=None):
        """Explicit named action. GET/reopen never calls this method."""
        from .ocr_jobs import OcrJobManager

        if (not isinstance(request_key, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{16,100}", request_key) is None
                or retention not in {"keep", "transit"} or type(ocr_required) is not bool
                or principal not in {"local_browser", "local_cli"}
                or languages not in [["eng"], ["ita"], ["eng", "ita"]]):
            raise ReviewDenied("Select the displayed bounded trial settings")
        parameters = {"source_id": source_id, "retention": retention,
                      "ocr_required": ocr_required, "languages": languages,
                      "principal": principal}
        submission = f"{ROOT}/submissions/{digest(request_key)}.json"
        from .setup_coordinator import assert_admission_ready

        assert_admission_ready(self.store, source_id)
        previous = read_record(self.store, submission)
        if previous is not None:
            if (set(previous) != {"schema", "id", "parameters", "root_binding",
                                 "source_revision"}
                    or previous["schema"] != "setup-trial-submission/v1"
                    or previous["parameters"] != parameters):
                raise ReviewConflict("This submission belongs to different trial settings")
            op_id = operation_id(previous["id"])
            # A replay never recreates a consumed input or duplicates a
            # terminal child. An unconfirmed crash needs this explicit action.
            if (read_record(self.store, permit_path(op_id)) is not None
                    and self.authority.retained(op_id)[1]):
                if _on_operation is not None:
                    _on_operation(op_id)
                return self.queue_locked(op_id)
        else:
            if ocr_required:
                selected = replace(ocr_settings_from_config(self.store.read_config()),
                                   mode="automatic", languages=tuple(languages))
                require_ocr_available(OcrJobManager(self.store).capability(selected))
            op_id = OperationLedger(self.store).start(
                "setup.trial", "Acquire only the displayed synthetic setup resources",
                related={"source_id": source_id}).id
        if _on_operation is not None:
            _on_operation(op_id)
        root, revision, _folder = _source(self.store, source_id)
        with open_local_directory(root) as (_path, binding):
            expected = {"schema": "setup-trial-submission/v1", "id": op_id,
                        "parameters": parameters, "root_binding": binding,
                        "source_revision": revision}
            if previous is not None and previous != expected:
                raise ReviewConflict("The selected trial Source or root changed")
            publish_once(self.store, submission, expected)
            index_path = self.store.paths.root / "indexes" / "search.sqlite3"
            if not index_path.exists():
                if self.store.list_canonical("documents"):
                    raise ReviewUnavailable(
                        "The existing search index needs its separate maintenance review")
                from .index import rebuild_search_index

                # The explicit trial action may prepare a new empty index. This
                # cannot rebuild or read another Document's contribution.
                rebuild_search_index(self.store)
                OperationLedger(self.store).append(
                    op_id, "setup.trial.empty-index-initialized",
                    "Prepared the search index of the empty space before trial acquisition")
            from .setup_source_scope import CLAIMS, claim_trial_names, validate_claim

            named = {kind: f"setup-{op_id.removeprefix('op_')}-{FIXTURES[kind]['name']}"
                     for kind in (["native", "scan"] if ocr_required else ["native"])}
            claim = read_record(self.store, f"{CLAIMS}/{source_id}/{op_id}.json")
            if claim is None:
                if any((root / name).exists() or (root / name).is_symlink()
                       for name in named.values()):
                    raise ReviewConflict("A preexisting input owns a trial resource name")
            else:
                validate_claim(self.store, claim)
            # Reserve only our exact names before writing even the first byte.
            # The ordinary Source/AI owner must never observe partial trial inputs.
            claim_trial_names(self.store, op_id, source_id, binding, named)
            for kind, name in named.items():
                resource = FIXTURES[kind]
                data = files("provelume").joinpath(
                    "resources", "setup-trial", resource["name"]).read_bytes()
                if (len(data) != resource["size_bytes"]
                        or hashlib.sha256(data).hexdigest() != resource["sha256"]):
                    raise ReviewUnavailable("The packaged synthetic resource failed integrity")
                target = root / name
                if target.exists():
                    with open_local_file(target) as stream:
                        current = stream.read(len(data) + 1)
                    if current != data:
                        raise ReviewConflict("A different input owns the trial resource name")
                else:
                    write_local_bytes(target, data)
            selected = observe_selection(self.store, source_id, named)
            self.authority.issue(op_id, selected, retention=retention,
                                 ocr_required=ocr_required, languages=languages,
                                 principal=principal)
        return self.queue_locked(op_id)


    def queue_locked(self, op_id):
        from .scheduler import SchedulerStore

        journal = SchedulerStore(self.store)
        for job in journal._all_jobs():
            if job["job_kind"] == JOB_KIND:
                request, _historical = self.request_for_job(job, current=False)
                if request["id"] == op_id:
                    return {"operation_id": op_id, "job": job, "created": False}
        permit = self.authority.read(op_id)
        policy = self._policy(permit["selection"]["source_id"])
        request_key = "setup-trial:" + op_id
        key = idempotency_digest("manual", policy["id"], str(policy["revision"]), request_key)
        request = {"schema": "setup-trial-request/v1", "id": op_id,
                   "permit_sha256": digest(permit), "scheduler_key": key}
        publish_once(self.store, f"{ROOT}/requests/{key}.json", request)
        result = journal.run_now(policy["id"], request_key=request_key)
        return {"operation_id": op_id, **result}

    def request_for_job(self, job, *, current=True):
        if job["job_kind"] != JOB_KIND:
            raise ReviewDenied("Another producer owns this scheduler job")
        request = read_record(self.store, f"{ROOT}/requests/{job['idempotency_key']}.json")
        if (not isinstance(request, dict)
                or set(request) != {"schema", "id", "permit_sha256", "scheduler_key"}
                or request["schema"] != "setup-trial-request/v1"
                or request["scheduler_key"] != job["idempotency_key"]):
            raise ReviewUnavailable("The trial scheduler request is missing or changed")
        permit = self.authority.read(request["id"], current=current)
        if (digest(permit) != request["permit_sha256"]
                or job["scope"] != {"kind": "source", "id": permit["selection"]["source_id"]}):
            raise ReviewDenied("The scheduler request does not own this exact trial")
        return request, permit

    def execute_locked(self, job):
        from .ingest import _refresh_after_ingestion, _run_ingestion_filesystem_locked

        request, permit = self.request_for_job(job)
        op_id = request["id"]
        source_id = permit["selection"]["source_id"]
        result = _run_ingestion_filesystem_locked(
            self.store, self.store.source_path(source_id),
            max_file_bytes=max(row["input"]["size_bytes"] for row in permit["selection"]["inputs"]),
            max_files=len(permit["selection"]["inputs"]), run_id=ingestion_run_id(op_id),
            trial_id=op_id)
        if result.run.status != "completed":
            raise ReviewUnavailable("The selected synthetic acquisition needs recovery")
        _refresh_after_ingestion(self.store, result, producer_job=job, trial_id=op_id)
        return {"processed": len(result.acquisitions), "skipped": 0, "errors": 0}

    def admit_acquisitions(self, op_id, result, producer_job):
        from .inbox_transit import InboxTransit
        from .ocr_sources import SourceOcrFlow

        request, permit = self.request_for_job(producer_job)
        if request["id"] != op_id or result.run.id != ingestion_run_id(op_id):
            raise ReviewDenied("The ingestion run belongs to another trial")
        for acquired in result.acquisitions:
            acquisition = asdict(acquired)
            typed = {"kind": "setup-trial", "id": op_id, "sha256": digest(permit)}
            self.authority.ocr_authorization(
                acquisition["source_id"], acquisition["version_id"], typed, acquisition)
            InboxTransit(self.store).admit_trial(acquisition, op_id)
            queued = SourceOcrFlow(self.store).admit(acquisition, trial_id=op_id)
            publish_once(self.store, f"{ROOT}/children/{op_id}/{acquisition['id']}.json", {
                "schema": "setup-trial-child/v1", "id": op_id,
                "acquisition_id": acquisition["id"], "job_id": queued["job"]["id"],
                "permit_sha256": digest(permit)})
        from .index import IndexScopeError, refresh_search_index

        # Bring only these newly acquired contributions into the existing index
        # before each OCR child publishes its own current selection. An empty
        # scan contribution is not a completed text or Inbox-exit proof.
        try:
            refresh_search_index(self.store, [a.document_id for a in result.acquisitions],
                                 recover_missing_derived=False, allow_full_rebuild=False)
        except IndexScopeError:
            # Acquisition remains true. The child still needs its own successful
            # scoped index publication after the separately reviewed repair.
            return

    def acquisitions(self, op_id):
        permit = self.authority.read(op_id, current=False)
        return [read_json(self.store, "knowledge/acquisitions/" + acquisition_id(
            op_id, row["input"]["locator"]) + ".json") for row in permit["selection"]["inputs"]]

    def child(self, op_id, acquisition):
        from .scheduler import SchedulerStore

        permit = self.authority.read(op_id, current=False)
        row = read_record(self.store, f"{ROOT}/children/{operation_id(op_id)}/"
                          f"{acquisition['id']}.json")
        if row is None:
            return None
        if (set(row) != {"schema", "id", "acquisition_id", "job_id", "permit_sha256"}
                or row["schema"] != "setup-trial-child/v1" or row["id"] != op_id
                or row["acquisition_id"] != acquisition["id"]
                or row["permit_sha256"] != digest(permit)):
            raise ReviewUnavailable("The trial child reference is invalid")
        job = SchedulerStore(self.store).get_job(row["job_id"])
        if job is None or job["job_kind"] != "ocr.execute":
            raise ReviewUnavailable("The trial child scheduler job is unavailable")
        return job

    def observations(self, op_id):
        """Read producer facts without repairing, replaying or creating state."""
        from .inbox_transit import _input
        from .ocr_jobs import OcrJobManager
        from .producer_index_evidence import resolve_index_contribution
        from .review_effects import ReviewError

        permit = self.authority.read(op_id, current=False)
        stale = False
        try:
            self.authority.read(op_id)
        except (ReviewError, OSError):
            stale = True
        history = self.probe_history(op_id)
        latest_probe = history[-1] if history else None
        rows = []
        for selected, acquisition in zip(permit["selection"]["inputs"],
                                         self.acquisitions(op_id), strict=True):
            row = {"fixture": selected["fixture"], "acquisition": acquisition,
                   "original_verified": False, "index_verified": False,
                   "search_verified": False, "consultation_verified": False,
                   "inbox_outcome": None, "job": None, "proof_sha256": None,
                   "text_kind": None, "error": None}
            if acquisition is not None:
                try:
                    _version, _document, original, _path = OcrJobManager(
                        self.store)._version_source(acquisition["version_id"])
                    row["original_verified"] = original["sha256"] == selected["input"]["sha256"]
                    child = self.child(op_id, acquisition)
                    row["job"] = child
                    if child is not None and child["status"] == "succeeded" and not stale:
                        proof = resolve_index_contribution(self.store, "processing", child["id"],
                                                           acquisition["document_id"])
                        row["index_verified"] = proof["profile"] in {"embedded", "ocr-complete"}
                        row["text_kind"] = proof["profile"]
                        row["proof_sha256"] = digest(proof)
                        tokens = (["LUMENATIVE731"] if selected["fixture"] == "native" else
                                  [("LUMESCANENGLISH953" if language == "eng" else
                                    "LUMESCANITALIA842") for language in permit["languages"]])
                        path = checked_path(self.store, "indexes/search.sqlite3")
                        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
                            row["search_verified"] = all(connection.execute(
                                "SELECT document_id, version_id FROM search "
                                "WHERE search MATCH ? AND document_id = ? AND version_id = ?",
                                ("content:" + token, acquisition["document_id"],
                                 acquisition["version_id"])).fetchall() == [(
                                     acquisition["document_id"], acquisition["version_id"])]
                                for token in tokens)
                    outcome = read_record(self.store, f"{ROOT}/inbox/{op_id}/"
                                          f"{acquisition['id']}-result.json")
                    if outcome is not None:
                        _validate_history_record(self.store, "inbox",
                                                 ("inbox", op_id,
                                                  acquisition["id"] + "-result.json"), outcome)
                        if outcome["outcome"] == "input_kept":
                            root, _revision, _folder = _source(
                                self.store, acquisition["source_id"])
                            if _input(root, acquisition["locator"]) != selected["input"]:
                                raise ReviewConflict("The retained synthetic input changed")
                        row["inbox_outcome"] = outcome["outcome"]
                    if latest_probe is not None and latest_probe["settled"]:
                        probe = latest_probe["record"]
                        response = probe["responses"].get(acquisition["id"])
                        row["consultation_verified"] = bool(
                            probe["success"] and response is not None
                            and response["proof_sha256"] == row["proof_sha256"])
                except (ReviewError, OcrContractError, OSError, sqlite3.Error):
                    row["error"] = "setup_trial_needs_review"
            rows.append(row)
        required = ["acquisition", "original_verified", "index_verified", "search_verified",
                    "inbox_outcome"]
        ready = not stale and all(all(row[key] for key in required) and row["error"] is None
                                 for row in rows)
        return {"operation_id": op_id, "permit": permit, "stale": stale, "documents": rows,
                "processing_ready": ready,
                "complete": ready and all(row["consultation_verified"] for row in rows)}

    def probe_history(self, op_id):
        permit = self.authority.read(op_id, current=False)
        root = checked_path(self.store, f"{ROOT}/probes/{operation_id(op_id)}")
        if not root.exists():
            return []
        paths = sorted(root.iterdir())
        if len(paths) > 128:
            raise ReviewUnavailable("The trial consultation history exceeds its bound")
        results, previous = [], None
        for sequence, path in enumerate(paths, 1):
            if path.name != f"{sequence:04d}.json":
                raise ReviewUnavailable("The trial consultation history is incomplete")
            value = read_record(self.store, path.relative_to(self.store.paths.root).as_posix())
            _validate_probe_record(self.store, value, permit)
            if value["sequence"] != sequence or value["previous_sha256"] != previous:
                raise ReviewUnavailable("The trial consultation history changed")
            operation = OperationLedger(self.store).get(value["operation_id"])
            settled = operation["status"] == ("completed" if value["success"] else "failed")
            results.append({"record": value, "settled": settled})
            previous = digest(value)
        return results

    def record_consultation(self, op_id, responses):
        """Consume actual server-collected responses, never client click/status flags."""
        from .storage import utc_now

        with InstanceLifecycleManager(self.store)._hold(purpose="setup-trial-consultation"):
            observed = self.observations(op_id)
            if not observed["processing_ready"]:
                raise ReviewUnavailable("Acquisition, text, search or Inbox remains unverified")
            permit = observed["permit"]
            expected = {row["acquisition"]["id"] for row in observed["documents"]}
            if set(responses) != expected:
                raise ReviewDenied("The consultation probe selected another acquisition")
            history = self.probe_history(op_id)
            if len(history) >= 128:
                raise ReviewUnavailable("The trial consultation history exceeds its bound")
            results, success = {}, True
            for row in observed["documents"]:
                acquisition = row["acquisition"]
                document, original = responses[acquisition["id"]]
                valid = (document[0] == 200 and original[0] == 200 and bool(document[1])
                         and acquisition["document_id"].encode() in document[1]
                         and hashlib.sha256(original[1]).hexdigest() == acquisition["content_hash"])
                success = success and valid
                results[acquisition["id"]] = {
                    "document_status": document[0],
                    "document_sha256": hashlib.sha256(document[1]).hexdigest(),
                    "original_status": original[0],
                    "original_sha256": hashlib.sha256(original[1]).hexdigest(),
                    "proof_sha256": row["proof_sha256"]}
            operation = OperationLedger(self.store).start(
                "setup.consultation", "Verify the actual synthetic Document and Original responses",
                parent_operation_id=op_id, related={"setup_operation_id": op_id})
            record = {"schema": "setup-trial-probe/v1", "id": op_id,
                      "operation_id": operation.id, "sequence": len(history) + 1,
                      "previous_sha256": digest(history[-1]["record"]) if history else None,
                      "permit_sha256": digest(permit), "success": success,
                      "responses": results, "recorded_at": utc_now()}
            publish_once(self.store, f"{ROOT}/probes/{op_id}/{record['sequence']:04d}.json", record)
            OperationLedger(self.store).close(
                operation.id, status="completed" if success else "failed",
                summary="The resource responses were verified" if success else
                        "The resource responses failed verification",
                error_code=None if success else "setup_trial_consultation_failed")
            if not success:
                raise ReviewUnavailable("The Document or Original response failed verification")
            result = self.observations(op_id)
            if not result["complete"]:
                raise ReviewUnavailable("The trial response evidence changed")
            parent = OperationLedger(self.store).get(op_id)
            if parent is not None and parent["status"] == "running":
                OperationLedger(self.store).close(
                    op_id, status="completed",
                    summary="The exact synthetic setup trial was verified",
                    metrics={"documents_verified": len(observed["documents"])})
            return result


def _validate_probe_record(store, value, permit):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "id", "operation_id", "sequence", "previous_sha256", "permit_sha256",
            "success", "responses", "recorded_at"}
            or value["schema"] != "setup-trial-probe/v1" or value["id"] != permit["id"]
            or type(value["sequence"]) is not int or not 1 <= value["sequence"] <= 128
            or type(value["success"]) is not bool or value["permit_sha256"] != digest(permit)
            or not isinstance(value["responses"], dict)
            or not isinstance(value["recorded_at"], str)
            or datetime.fromisoformat(value["recorded_at"]).tzinfo is None):
        raise ReviewUnavailable("The trial consultation record has an invalid closed identity")
    expected = {acquisition_id(permit["id"], row["input"]["locator"]): row["input"]["sha256"]
                for row in permit["selection"]["inputs"]}
    if set(value["responses"]) != set(expected):
        raise ReviewUnavailable("The consultation record selects another acquisition")
    for acq_id, response in value["responses"].items():
        if (not isinstance(response, dict) or set(response) != {
                "document_status", "document_sha256", "original_status", "original_sha256",
                "proof_sha256"}
                or any(type(response[key]) is not int or response[key] not in {0, *range(100, 600)}
                       for key in ["document_status", "original_status"])
                or any(re.fullmatch(r"[0-9a-f]{64}", str(response[key])) is None for key in [
                    "document_sha256", "original_sha256", "proof_sha256"])
                or (value["success"] and (response["document_status"] != 200
                    or response["original_status"] != 200
                    or response["original_sha256"] != expected[acq_id]))):
            raise ReviewUnavailable("The resource response record is invalid")
    if value["previous_sha256"] is not None and re.fullmatch(
            r"[0-9a-f]{64}", str(value["previous_sha256"])) is None:
        raise ReviewUnavailable("The consultation predecessor is invalid")
    operation = OperationLedger(store).get(operation_id(value["operation_id"]))
    if (operation is None or operation["kind"] != "setup.consultation"
            or operation["parent_operation_id"] != permit["id"]
            or operation["related"] != {"setup_operation_id": permit["id"]}
            or operation["status"] not in {
                "running", "completed" if value["success"] else "failed"}):
        raise ReviewUnavailable("The resource probe has no corresponding operation")


def _validate_history_record(store, category, parts, value):
    """Closed historical schemas; live applicability stays with each producer."""
    from .scheduler import SchedulerStore

    def require(condition):
        if not condition:
            raise ReviewUnavailable("The trial history has an invalid closed identity")

    def checksum(item):
        return isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item) is not None

    def aware(item):
        return isinstance(item, str) and datetime.fromisoformat(item).tzinfo is not None

    require(isinstance(value, dict) and len(parts) in {2, 3})
    if category == "submissions":
        require(len(parts) == 2 and checksum(parts[-1][:-5]) and set(value) == {
            "schema", "id", "parameters", "root_binding", "source_revision"}
            and value["schema"] == "setup-trial-submission/v1")
        parameters = value["parameters"]
        require(isinstance(parameters, dict) and set(parameters) == {
            "source_id", "retention", "ocr_required", "languages", "principal"})
        require(re.fullmatch(r"src_[0-9a-f]{32}", str(parameters["source_id"])) is not None
                and parameters["retention"] in {"keep", "transit"}
                and type(parameters["ocr_required"]) is bool
                and parameters["languages"] in [["eng"], ["ita"], ["eng", "ita"]]
                and parameters["principal"] in {"local_browser", "local_cli"}
                and ROOT_ID.fullmatch(str(value["root_binding"])) is not None
                and checksum(value["source_revision"]))
        operation = OperationLedger(store).get(operation_id(value["id"]))
        require(operation is not None and operation["kind"] == "setup.trial"
                and operation["related"] == {"source_id": parameters["source_id"]})
        return
    if category == "requests":
        require(len(parts) == 2 and checksum(parts[-1][:-5]) and set(value) == {
            "schema", "id", "permit_sha256", "scheduler_key"}
            and value["schema"] == "setup-trial-request/v1"
            and value["scheduler_key"] == parts[-1][:-5])
        permit = SetupTrialAuthority(store).read(value["id"], current=False)
        require(value["permit_sha256"] == digest(permit))
        return
    require(len(parts) == 3 and operation_id(parts[1]) == value.get("id"))
    permit = SetupTrialAuthority(store).read(parts[1], current=False)
    require(value.get("permit_sha256") == digest(permit))
    if category == "probes":
        require(parts[-1] == f"{value['sequence']:04d}.json")
        _validate_probe_record(store, value, permit)
        return
    name = parts[-1][:-5]
    acq_id = name.split("-", 1)[0]
    require(re.fullmatch(r"acq_[0-9a-f]{32}", acq_id) is not None)
    acquisition = read_json(store, f"knowledge/acquisitions/{acq_id}.json")
    require(isinstance(acquisition, dict))
    expected_inputs = [row["input"] for row in permit["selection"]["inputs"]
                       if acquisition_id(permit["id"], row["input"]["locator"]) == acq_id]
    require(len(expected_inputs) == 1
            and acquisition["source_id"] == permit["selection"]["source_id"]
            and acquisition["locator"] == expected_inputs[0]["locator"]
            and acquisition["content_hash"] == expected_inputs[0]["sha256"])
    if category == "children":
        require(name == acq_id and set(value) == {
            "schema", "id", "acquisition_id", "job_id", "permit_sha256"}
            and value["schema"] == "setup-trial-child/v1" and value["acquisition_id"] == acq_id
            and re.fullmatch(r"job_[0-9a-f]{32}", str(value["job_id"])) is not None)
        job = SchedulerStore(store).get_job(value["job_id"])
        require(job is not None and job["job_kind"] == "ocr.execute")
        return
    require(category == "inbox")
    if name.endswith("-admission"):
        require(set(value) == {"schema", "id", "instance_id", "acquisition", "input",
                               "permit_sha256"}
                and value["schema"] == "setup-trial-inbox-admission/v1"
                and value["instance_id"] == permit["instance_id"]
                and value["acquisition"] == acquisition and value["input"] == expected_inputs[0])
    elif name.endswith("-intent"):
        require(set(value) == {"schema", "id", "operation_id", "item", "permit_sha256"}
                and value["schema"] == "setup-trial-inbox-intent/v1")
        item = value["item"]
        require(isinstance(item, dict) and set(item) == {
            "selection", "acquisition", "input", "contribution", "proof"}
            and item["acquisition"] == acquisition and item["input"] == expected_inputs[0])
        child = SetupTrials(store).child(permit["id"], acquisition)
        require(child is not None and item["selection"] == {
            "producer": "processing", "job_id": child["id"], "acquisition_id": acq_id}
            and item["proof"]["receipt_id"] == "receipt_" + child["id"].removeprefix("job_")
            and item["proof"]["publication"]["job_id"] == child["id"]
            and item["contribution"]["original_sha256"] == expected_inputs[0]["sha256"])
        operation = OperationLedger(store).get(operation_id(value["operation_id"]))
        require(operation is not None and operation["parent_operation_id"] == permit["id"]
                and operation["kind"] == (
                    "inbox.exit" if permit["retention"] == "transit" else "inbox.keep")
                and operation["related"] == {"source_id": acquisition["source_id"],
                                              "acquisition_id": acq_id})
    elif name.endswith("-result"):
        require(set(value) == {"schema", "id", "operation_id", "acquisition_id", "permit_sha256",
                               "recorded_at", "outcome", "empty_directories_removed"}
                and value["schema"] == "setup-trial-inbox-result/v1"
                and value["acquisition_id"] == acq_id and value["outcome"] == (
                    "input_exited" if permit["retention"] == "transit" else "input_kept")
                and type(value["empty_directories_removed"]) is int
                and 0 <= value["empty_directories_removed"] <= 1000
                and aware(value["recorded_at"]))
        intent = read_record(store, f"{ROOT}/inbox/{permit['id']}/{acq_id}-intent.json")
        require(intent is not None and intent["operation_id"] == value["operation_id"])
    else:
        require(False)


def setup_trial_findings(store):
    """Recognize bounded durable roots before any trial state is operational."""
    findings = []
    try:
        root = checked_path(store, ROOT)
        if not root.exists():
            return findings
        allowed = {"permits", "submissions", "requests", "children", "inbox", "probes",
                   "source-claims"}
        count, total_bytes = 0, 0
        for directory in root.iterdir():
            if directory.name not in allowed or not directory.is_dir() or directory.is_symlink():
                raise ReviewUnavailable("Unknown synthetic trial state")
            for path in directory.rglob("*"):
                count += 1
                if count > 10000 or path.is_symlink() or path.is_junction():
                    raise ReviewUnavailable("Trial history is unsafe or exceeds its bound")
                parts = path.relative_to(root).parts
                if path.is_dir():
                    if (len(parts) != 2
                            or directory.name not in {
                                "children", "inbox", "probes", "source-claims"}):
                        raise ReviewUnavailable("Trial history has an unknown directory")
                    if directory.name == "source-claims":
                        from .setup_source_scope import _source_id

                        _source_id(path.name)
                    else:
                        operation_id(path.name)
                    continue
                if path.suffix != ".json":
                    raise ReviewUnavailable("Unknown trial history entry")
                relative = path.relative_to(store.paths.root).as_posix()
                if len(parts) > 3:
                    raise ReviewUnavailable("Trial history exceeds its directory bound")
                total_bytes += path.stat().st_size
                if total_bytes > 32 * 1024 * 1024:
                    raise ReviewUnavailable("Trial history exceeds its byte bound")
                record = read_record(store, relative)
                if directory.name == "source-claims":
                    from .setup_source_scope import validate_claim

                    validate_claim(store, record)
                    if (len(parts) != 3 or record["source_id"] != parts[1]
                            or record["id"] != path.stem):
                        raise ReviewUnavailable("The trial name claim has another owner")
                elif directory.name == "permits":
                    if len(parts) != 2:
                        raise ReviewUnavailable("The trial permit path is invalid")
                    SetupTrialAuthority(store).retained(path.stem)
                else:
                    _validate_history_record(store, directory.name, parts, record)
            if directory.name == "probes":
                for child in directory.iterdir():
                    SetupTrials(store).probe_history(child.name)
        return findings
    except (ValueError, TypeError, KeyError, OSError) as exc:
        findings.append({"code": "setup_trial_invalid", "path": ROOT, "message": str(exc)})
    return findings
